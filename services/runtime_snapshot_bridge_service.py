"""
Runner-owned runtime snapshot bridge.

Publishes read-only dashboard/runtime snapshots for app consumption so the app
does not need to rebuild REST-heavy views on every request or SSE update.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


LIVE_POSITION_OWNER_STATUSES = {
    "running",
    "paused",
    "recovering",
    "flash_crash_paused",
    "stop_cleanup_pending",
    "error",
    "risk_stopped",
}


def extract_market_symbol_bot(bot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": bot.get("symbol"),
        "status": bot.get("status"),
    }


class RuntimeSnapshotBridgeService:
    """Atomic JSON snapshot bridge between runner and app."""

    SNAPSHOT_VERSION = 1
    DEFAULT_FILE_PATH = os.path.join("storage", "runtime_snapshot_bridge.json")
    DEFAULT_WRITE_INTERVAL_SEC = 5.0
    DEFAULT_EVENT_TIMEOUT_SEC = 1.0
    REBUILD_INTERVALS_SEC = {
        "market": 1.0,
        "open_orders": 1.5,
        "positions": 2.0,
        "bots_runtime": 2.0,
        "bots_runtime_light": 2.0,
        "summary": 5.0,
    }
    EVENT_REBUILD_INTERVALS_SEC = {
        "market": {
            "ticker": 0.5,
            "health": 1.0,
            "timer": 4.0,
        },
        "open_orders": {
            "order": 1.0,
            "health": 2.0,
            "timer": 5.0,
        },
        "positions": {
            "position": 1.0,
            "execution": 0.5,
            "order": 1.5,
            "health": 2.0,
            "timer": 5.0,
        },
        "bots_runtime": {
            "orderbook": 0.35,
            "ticker": 0.5,
            "execution": 0.5,
            "position": 0.5,
            "order": 0.5,
            "health": 1.0,
            "startup": 0.0,
            "timer": 2.0,
        },
        "bots_runtime_light": {
            "orderbook": 0.35,
            "ticker": 0.5,
            "execution": 0.5,
            "position": 0.5,
            "order": 0.5,
            "health": 1.0,
            "startup": 0.0,
            "timer": 2.0,
        },
    }
    READ_STALE_AGE_SEC = {
        "market": 5.0,
        "open_orders": 6.0,
        "positions": 8.0,
        "bots_runtime": 6.0,
        "bots_runtime_light": 6.0,
        "summary": 12.0,
    }
    PUBLISH_DIAGNOSTIC_LOG_THROTTLE_SEC = 30.0
    PUBLISH_DIAGNOSTIC_SLOW_PASS_MS = 5000.0
    PUBLISH_DIAGNOSTIC_SLOW_SECTION_MS = 2000.0
    SECTION_DEPENDENCIES = {
        "market": (
            "stream_service.get_health_snapshot + "
            "stream_service.get_dashboard_snapshot + "
            "bot_storage.list_bots/get_runtime_positions_payload"
        ),
        "open_orders": (
            "bot_status_service.get_live_open_orders_by_symbol -> "
            "stream_service.get_open_orders_fresh or bybit_client.get_open_orders"
        ),
        "positions": (
            "bot_status_service.get_runtime_positions_payload or "
            "position_service.get_positions + bot_storage.list_bots"
        ),
        "summary": (
            "account_service.get_overview + pnl_service.get_today_stats + "
            "risk_manager.get_risk_state"
        ),
        "bots_runtime_light": (
            "bot_status_service.get_runtime_bots_light + bot_storage.list_bots + "
            "symbol_pnl_service + cached scanner/stopped-preview/runtime positions"
        ),
        "bots_runtime": (
            "cached full enrichment payload from _run_full_enrich_loop or storage fallback"
        ),
    }

    def __init__(
        self,
        file_path: Optional[str] = None,
        *,
        owner_name: str = "app",
        write_enabled: bool = False,
        stream_service: Optional[Any] = None,
        bot_storage: Optional[Any] = None,
        account_service: Optional[Any] = None,
        position_service: Optional[Any] = None,
        pnl_service: Optional[Any] = None,
        risk_manager: Optional[Any] = None,
        bot_status_service: Optional[Any] = None,
        write_interval_sec: float = DEFAULT_WRITE_INTERVAL_SEC,
    ):
        self.file_path = Path(file_path or self.DEFAULT_FILE_PATH)
        self.owner_name = str(owner_name or "app").strip().lower() or "app"
        self.write_enabled = bool(write_enabled)
        self.stream_service = stream_service
        self.bot_storage = bot_storage
        self.account_service = account_service
        self.position_service = position_service
        self.pnl_service = pnl_service
        self.risk_manager = risk_manager
        self.bot_status_service = bot_status_service
        self.write_interval_sec = max(float(write_interval_sec or 0), 1.0)

        self._state_lock = threading.RLock()
        self._read_cache: Optional[Dict[str, Any]] = None
        self._read_cache_mtime_ns: Optional[int] = None
        self._last_publish_at: Dict[str, float] = {}
        self._last_account_snapshot: Optional[Dict[str, Any]] = None
        self._last_summary_snapshot: Optional[Dict[str, Any]] = None
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._next_writer_seq = 1

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self._full_enrich_interval_sec = 30.0
        self._cached_bots_runtime_payload: Optional[Dict[str, Any]] = None
        self._cached_bots_list: Optional[List[Dict[str, Any]]] = None
        self._cached_bots_list_at: float = 0.0
        self._last_market_symbol_diagnostics: Dict[str, Any] = {}
        self._last_full_enrich_at: float = 0.0

        # Background full-enrichment thread — runs independently so the fast
        # publish loop is never blocked by expensive get_runtime_bots() calls.
        self._enrich_result_lock = threading.Lock()
        self._enrich_thread: Optional[threading.Thread] = None
        self._enrich_stop_event = threading.Event()
        self._full_enrich_in_progress = False
        self._full_enrich_last_duration_ms: Optional[float] = None
        self._light_publish_count_during_full: int = 0
        self._last_publish_diag_log_at: float = 0.0
        self._read_diagnostics_local = threading.local()

        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _copy(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, separators=(",", ":")))
        except (TypeError, ValueError):
            return copy.deepcopy(value)

    def _get_read_diagnostics_stack(self) -> List[Dict[str, Any]]:
        stack = getattr(self._read_diagnostics_local, "stack", None)
        if stack is None:
            stack = []
            self._read_diagnostics_local.stack = stack
        return stack

    def _active_read_diagnostics(self) -> Optional[Dict[str, Any]]:
        stack = getattr(self._read_diagnostics_local, "stack", None)
        if not stack:
            return None
        return stack[-1]

    @staticmethod
    def _increment_counter(bucket: Dict[str, Any], key: str, amount: int = 1) -> None:
        bucket[key] = int(bucket.get(key) or 0) + int(amount or 0)

    @staticmethod
    def _accumulate_ms(bucket: Dict[str, Any], key: str, elapsed_ms: float) -> None:
        bucket[key] = round(
            float(bucket.get(key) or 0.0) + max(float(elapsed_ms or 0.0), 0.0),
            3,
        )

    def _record_read_diagnostic(
        self,
        *,
        operation: Optional[str] = None,
        section_name: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_ms: Optional[float] = None,
    ) -> None:
        trace = self._active_read_diagnostics()
        if trace is None:
            return
        if operation:
            self._increment_counter(trace.setdefault("operation_counts", {}), operation)
        if section_name:
            self._increment_counter(
                trace.setdefault("section_call_counts", {}),
                str(section_name),
            )
        if metric_name and metric_ms is not None:
            self._accumulate_ms(trace.setdefault("phase_ms", {}), metric_name, metric_ms)

    def _finalize_read_diagnostics(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        completed_at = time.time()
        trace["completed_at"] = completed_at
        trace["total_ms"] = round(
            max(completed_at - float(trace.get("started_at") or completed_at), 0.0) * 1000.0,
            3,
        )
        top_section = None
        top_count = 0
        for name, count in (trace.get("section_call_counts") or {}).items():
            if int(count or 0) > top_count:
                top_section = str(name)
                top_count = int(count or 0)
        trace["top_repeated_section"] = (
            {
                "name": top_section,
                "count": top_count,
            }
            if top_section and top_count > 1
            else None
        )
        return trace

    @contextmanager
    def capture_read_diagnostics(self, label: str):
        trace = {
            "label": str(label or "").strip() or "runtime_snapshot_bridge",
            "started_at": time.time(),
            "operation_counts": {},
            "section_call_counts": {},
            "phase_ms": {},
        }
        stack = self._get_read_diagnostics_stack()
        stack.append(trace)
        try:
            yield trace
        finally:
            if stack and stack[-1] is trace:
                stack.pop()
            else:
                try:
                    stack.remove(trace)
                except ValueError:
                    pass
            self._finalize_read_diagnostics(trace)

    def start(self) -> None:
        if not self.write_enabled:
            return
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._enrich_stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="RuntimeSnapshotBridge",
                daemon=True,
            )
            self._enrich_thread = threading.Thread(
                target=self._run_full_enrich_loop,
                name="RuntimeSnapshotBridgeEnrich",
                daemon=True,
            )
            self._thread.start()
            self._enrich_thread.start()

    def stop(self) -> None:
        with self._state_lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            self._enrich_stop_event.set()
            thread = self._thread
            enrich_thread = self._enrich_thread
            self._thread = None
            self._enrich_thread = None
        if thread:
            thread.join(timeout=2.0)
        if enrich_thread:
            enrich_thread.join(timeout=5.0)

    def publish_now(self, reason: str = "manual", event_types: Optional[Iterable[str]] = None) -> None:
        if not self.write_enabled:
            return
        self._publish(reason=reason, event_types=event_types, force=True)

    def read_snapshot(
        self,
        *,
        copy_payload: bool = True,
    ) -> Optional[Dict[str, Any]]:
        self._record_read_diagnostic(operation="read_snapshot")
        stat_started = time.monotonic()
        try:
            stat = self.file_path.stat()
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug("Runtime snapshot bridge stat failed: %s", exc)
            return None
        self._record_read_diagnostic(
            metric_name="snapshot_stat_ms",
            metric_ms=(time.monotonic() - stat_started) * 1000.0,
        )

        with self._state_lock:
            if (
                self._read_cache is not None
                and self._read_cache_mtime_ns == getattr(stat, "st_mtime_ns", None)
            ):
                self._record_read_diagnostic(operation="read_snapshot:cache_hit")
                if not copy_payload:
                    self._record_read_diagnostic(
                        operation="read_snapshot:shared_reference",
                    )
                    return self._read_cache
                copy_started = time.monotonic()
                payload = self._copy(self._read_cache)
                self._record_read_diagnostic(
                    metric_name="snapshot_cache_copy_ms",
                    metric_ms=(time.monotonic() - copy_started) * 1000.0,
                )
                return payload

        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                self._record_read_diagnostic(operation="read_snapshot:file_read")
                read_started = time.monotonic()
                raw_payload = handle.read()
                self._record_read_diagnostic(
                    metric_name="snapshot_file_read_ms",
                    metric_ms=(time.monotonic() - read_started) * 1000.0,
                )
            parse_started = time.monotonic()
            payload = json.loads(raw_payload)
            self._record_read_diagnostic(
                metric_name="snapshot_json_parse_ms",
                metric_ms=(time.monotonic() - parse_started) * 1000.0,
            )
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug("Runtime snapshot bridge read failed: %s", exc)
            return None

        if not isinstance(payload, dict):
            return None

        with self._state_lock:
            self._read_cache = payload
            self._read_cache_mtime_ns = getattr(stat, "st_mtime_ns", None)
            if not copy_payload:
                self._record_read_diagnostic(
                    operation="read_snapshot:shared_reference",
                )
                return self._read_cache
        copy_started = time.monotonic()
        copied = self._copy(payload)
        self._record_read_diagnostic(
            metric_name="snapshot_payload_copy_ms",
            metric_ms=(time.monotonic() - copy_started) * 1000.0,
        )
        return copied

    def read_section(
        self,
        section_name: str,
        *,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized_section_name = str(section_name or "").strip()
        self._record_read_diagnostic(
            operation="read_section",
        )
        snapshot = self.read_snapshot()
        return self.extract_section_from_snapshot(
            snapshot,
            normalized_section_name,
            max_age_sec=max_age_sec,
        )

    def extract_section_from_snapshot(
        self,
        snapshot: Optional[Dict[str, Any]],
        section_name: str,
        *,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized_section_name = str(section_name or "").strip()
        self._record_read_diagnostic(
            operation="extract_section_from_snapshot",
            section_name=normalized_section_name,
        )
        section_started = time.monotonic()
        if not snapshot:
            return None
        sections = snapshot.get("sections") or {}
        if not isinstance(sections, dict):
            return None
        section = sections.get(normalized_section_name)
        if not isinstance(section, dict):
            return None

        copy_started = time.monotonic()
        payload = self._copy(section.get("payload"))
        self._record_read_diagnostic(
            metric_name="section_payload_copy_ms",
            metric_ms=(time.monotonic() - copy_started) * 1000.0,
        )
        if not isinstance(payload, dict):
            return None

        shape_started = time.monotonic()
        payload_valid = self._payload_shape_valid(normalized_section_name, payload)
        self._record_read_diagnostic(
            metric_name="section_shape_validation_ms",
            metric_ms=(time.monotonic() - shape_started) * 1000.0,
        )
        if not payload_valid:
            payload.setdefault("stale_data", True)
            payload["error"] = (
                str(payload.get("error") or "").strip()
                or f"{normalized_section_name}_payload_invalid"
            )
            payload["integrity_shape_valid"] = False

        published_at = self._safe_float(section.get("published_at"), 0.0)
        now_ts = time.time()
        age_limit = (
            self._safe_float(max_age_sec, 0.0)
            if max_age_sec is not None
            else self.READ_STALE_AGE_SEC.get(normalized_section_name, 10.0)
        )
        if age_limit <= 0:
            age_limit = self.READ_STALE_AGE_SEC.get(normalized_section_name, 10.0)
        age_sec = now_ts - published_at if published_at > 0 else float("inf")
        meta = snapshot.get("meta", {}) if isinstance(snapshot.get("meta"), dict) else {}
        snapshot_fresh = age_sec <= age_limit
        if age_sec > age_limit:
            payload["stale_data"] = True
            if payload.get("error") in (None, "", 0):
                payload["error"] = f"{normalized_section_name}_stale"
        payload.setdefault("snapshot_published_at", published_at or None)
        payload.setdefault("snapshot_produced_at", meta.get("produced_at"))
        payload.setdefault("snapshot_producer", meta.get("producer"))
        payload.setdefault("snapshot_producer_pid", meta.get("producer_pid"))
        payload.setdefault("snapshot_owner", meta.get("stream_owner"))
        payload.setdefault("snapshot_source", section.get("source"))
        payload.setdefault("snapshot_reason", section.get("reason"))
        payload.setdefault(
            "snapshot_epoch",
            meta.get("snapshot_epoch"),
        )
        payload.setdefault(
            "snapshot_age_sec",
            round(age_sec, 3) if age_sec != float("inf") else None,
        )
        payload.setdefault("bridge_published_at", published_at or None)
        payload.setdefault(
            "bridge_age_ms",
            round(age_sec * 1000.0, 2) if age_sec != float("inf") else None,
        )
        runtime_publish_ts = self._safe_float(payload.get("runtime_publish_ts"), 0.0)
        payload.setdefault(
            "runtime_snapshot_age_ms",
            round(max(now_ts - runtime_publish_ts, 0.0) * 1000.0, 2)
            if runtime_publish_ts > 0
            else None,
        )
        payload.setdefault("snapshot_fresh", bool(snapshot_fresh))
        payload.setdefault("integrity_shape_valid", payload_valid)
        self._record_read_diagnostic(
            metric_name="section_total_ms",
            metric_ms=(time.monotonic() - section_started) * 1000.0,
        )
        return payload

    def read_dashboard_payload(self, reason: str) -> Optional[Dict[str, Any]]:
        market = self.read_section("market")
        summary = self.read_section("summary")
        positions = self.read_section("positions")
        bots_payload = self.read_section("bots_runtime")
        if not summary or not positions or not bots_payload:
            return None
        payload = {
            "reason": reason,
            "emitted_at": time.time(),
            "summary": summary,
            "positions": positions,
            "bots": list(bots_payload.get("bots") or []),
        }
        if market:
            payload["market"] = market
        return payload

    def read_market_snapshot(self) -> Optional[Dict[str, Any]]:
        return self.read_section("market")

    def _run_loop(self) -> None:
        self._publish(reason="startup", event_types={"startup"}, force=True)
        last_seq = (
            self.stream_service.get_latest_event_seq()
            if self.stream_service and hasattr(self.stream_service, "get_latest_event_seq")
            else 0
        )
        last_periodic_at = time.monotonic()

        while not self._stop_event.is_set():
            event_types = set()
            if self.stream_service and hasattr(self.stream_service, "wait_for_events"):
                try:
                    events = self.stream_service.wait_for_events(
                        last_seq,
                        timeout_sec=self.DEFAULT_EVENT_TIMEOUT_SEC,
                    )
                except Exception as exc:
                    logger.debug("Runtime snapshot bridge wait failed: %s", exc)
                    events = []
                for event in events:
                    last_seq = max(last_seq, int(event.get("seq") or 0))
                    event_type = str(event.get("type") or "").strip().lower()
                    if event_type:
                        event_types.add(event_type)
            else:
                time.sleep(self.DEFAULT_EVENT_TIMEOUT_SEC)

            now_mono = time.monotonic()
            periodic_due = (now_mono - last_periodic_at) >= self.write_interval_sec
            if not event_types and not periodic_due:
                continue

            if periodic_due:
                last_periodic_at = now_mono
                event_types.add("timer")

            self._publish(
                reason=",".join(sorted(event_types)) if event_types else "timer",
                event_types=event_types,
                force=False,
            )

    def _publish(
        self,
        *,
        reason: str,
        event_types: Optional[Iterable[str]] = None,
        force: bool = False,
    ) -> None:
        event_set = {
            str(event_type or "").strip().lower()
            for event_type in (event_types or [])
            if str(event_type or "").strip()
        }
        now_ts = time.time()
        with self._state_lock:
            snapshot = self._copy(self._last_snapshot) if self._last_snapshot else {
                "version": self.SNAPSHOT_VERSION,
                "meta": {},
                "sections": {},
            }

        snapshot["version"] = self.SNAPSHOT_VERSION
        snapshot["meta"] = self._build_meta(now_ts)
        sections = snapshot.setdefault("sections", {})
        section_order = (
            "market",
            "open_orders",
            "positions",
            "summary",
            "bots_runtime_light",
            "bots_runtime",
        )
        rebuild_plan = {
            name: self._should_rebuild(name, event_set, force)
            for name in section_order
        }
        publish_diag = self._build_publish_diagnostics(
            reason=reason,
            event_set=event_set,
            force=force,
            sections=sections,
            rebuild_plan=rebuild_plan,
            started_at=now_ts,
        )
        rebuilt_before_light = False

        if rebuild_plan["market"]:
            market_payload = self._run_publish_section(
                publish_diag,
                "market",
                lambda: self._build_market_payload(
                    symbols=self._collect_market_symbols(),
                    health=dict(
                        ((snapshot.get("meta") or {}).get("stream_health") or {})
                    ),
                ),
            )
            market_published_at = time.time()
            sections["market"] = self._wrap_section(
                market_payload,
                reason=reason,
                published_at=market_published_at,
                source="runner_stream_snapshot",
            )
            self._last_publish_at["market"] = market_published_at
            rebuilt_before_light = True

        if rebuild_plan["open_orders"]:
            open_orders_payload = self._run_publish_section(
                publish_diag,
                "open_orders",
                self._build_open_orders_payload,
            )
            open_orders_published_at = time.time()
            sections["open_orders"] = self._wrap_section(
                open_orders_payload,
                reason=reason,
                published_at=open_orders_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["open_orders"] = open_orders_published_at
            rebuilt_before_light = True

        positions_payload: Optional[Dict[str, Any]] = None
        if rebuild_plan["positions"]:
            account_payload = self._get_cached_account_snapshot(force=force)
            positions_payload = self._run_publish_section(
                publish_diag,
                "positions",
                lambda: self._build_positions_payload(account_payload),
            )
            positions_published_at = time.time()
            sections["positions"] = self._wrap_section(
                positions_payload,
                reason=reason,
                published_at=positions_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["positions"] = positions_published_at
            rebuilt_before_light = True

        if rebuild_plan["summary"]:
            account_payload = self._get_cached_account_snapshot(force=True)
            if positions_payload is None:
                positions_payload = self._run_publish_section(
                    publish_diag,
                    "positions",
                    lambda: self._build_positions_payload(account_payload),
                )
                positions_published_at = time.time()
                sections["positions"] = self._wrap_section(
                    positions_payload,
                    reason=f"{reason}:summary_positions",
                    published_at=positions_published_at,
                    source="runner_runtime_snapshot",
                )
                self._last_publish_at["positions"] = positions_published_at
                rebuilt_before_light = True
            summary_payload = self._run_publish_section(
                publish_diag,
                "summary",
                lambda: self._build_summary_payload(
                    account_payload=account_payload,
                    positions_payload=positions_payload or {},
                ),
            )
            summary_published_at = time.time()
            sections["summary"] = self._wrap_section(
                summary_payload,
                reason=reason,
                published_at=summary_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["summary"] = summary_published_at
            rebuilt_before_light = True

        # Publish whatever we have before the proven slow light runtime build.
        # This keeps fresh market/orders/positions/summary truth visible even if
        # bots_runtime_light stalls for many seconds.
        if rebuild_plan["bots_runtime_light"] and rebuilt_before_light:
            self._write_publish_snapshot(
                snapshot,
                publish_diag,
                stage="pre_bots_runtime_light",
            )

        # bots_runtime_light — fast, every cycle, never blocks
        if rebuild_plan["bots_runtime_light"]:
            light_payload = self._run_publish_section(
                publish_diag,
                "bots_runtime_light",
                self._build_bots_runtime_light_payload,
            )
            light_published_at = time.time()
            sections["bots_runtime_light"] = self._wrap_section(
                light_payload,
                reason=reason,
                published_at=light_published_at,
                source="runner_runtime_snapshot_light",
            )
            self._last_publish_at["bots_runtime_light"] = light_published_at
            # Track light publishes during full builds for diagnostics
            if self._full_enrich_in_progress:
                self._light_publish_count_during_full += 1

        # bots_runtime (full) — reads the background enrichment thread's
        # cached result.  NEVER calls get_runtime_bots(cache_only=False)
        # from this thread — the background _run_full_enrich_loop does that.
        if rebuild_plan["bots_runtime"]:
            def _build_bots_runtime_section() -> Dict[str, Any]:
                with self._enrich_result_lock:
                    cached_full = (
                        self._copy(self._cached_bots_runtime_payload)
                        if self._cached_bots_runtime_payload is not None
                        else None
                    )
                if cached_full is not None:
                    return cached_full
                # No full payload yet (startup or background thread hasn't
                # completed first build).  Publish an explicitly stale
                # placeholder so the section exists but is clearly marked.
                try:
                    fallback_bots = self._get_bots_cached()
                except Exception:
                    fallback_bots = []
                return {
                    "bots": fallback_bots,
                    "error": "full_enrich_not_ready",
                    "stale_data": True,
                    "runtime_state_source": "storage_fallback_awaiting_full",
                    "bots_scope": "full",
                }

            bots_runtime_payload = self._run_publish_section(
                publish_diag,
                "bots_runtime",
                _build_bots_runtime_section,
            )
            bots_runtime_published_at = time.time()
            sections["bots_runtime"] = self._wrap_section(
                bots_runtime_payload,
                reason=reason,
                published_at=bots_runtime_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["bots_runtime"] = bots_runtime_published_at

        self._write_publish_snapshot(snapshot, publish_diag, stage="final")
        self._maybe_log_publish_diagnostics(publish_diag)

    def _write_snapshot(self, payload: Dict[str, Any]) -> None:
        serialization_started = time.monotonic()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        serialization_ms = round(
            max(time.monotonic() - serialization_started, 0.0) * 1000.0,
            3,
        )
        serialized_bytes = serialized.encode("utf-8")
        total_bytes = len(serialized_bytes)
        tmp_path = None
        write_file_ms = 0.0
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.file_path.parent),
                prefix=f"{self.file_path.name}.",
                suffix=".tmp",
            )
            write_started = time.monotonic()
            with os.fdopen(fd, "wb") as handle:
                handle.write(serialized_bytes)
            os.replace(tmp_path, self.file_path)
            write_file_ms = round(
                max(time.monotonic() - write_started, 0.0) * 1000.0,
                3,
            )
            try:
                os.chmod(self.file_path, 0o644)
            except OSError:
                pass
            try:
                stat = self.file_path.stat()
            except Exception:
                stat = None
            with self._state_lock:
                self._read_cache = self._copy(payload)
                self._read_cache_mtime_ns = (
                    getattr(stat, "st_mtime_ns", None) if stat is not None else None
                )
        except Exception as exc:
            logger.warning("Failed to write runtime snapshot bridge: %s", exc)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return {
            "serialization_ms": serialization_ms,
            "write_file_ms": write_file_ms,
            "total_bytes": total_bytes,
        }

    def _build_meta(self, now_ts: float) -> Dict[str, Any]:
        stream_health = self._build_market_health(now_ts)
        return {
            "producer": self.owner_name,
            "producer_pid": os.getpid(),
            "produced_at": now_ts,
            "stream_owner": "runner",
            "stream_health": stream_health,
        }

    def _build_market_health(self, now_ts: float) -> Dict[str, Any]:
        if self.stream_service and hasattr(self.stream_service, "get_health_snapshot"):
            try:
                health = self.stream_service.get_health_snapshot() or {}
                if isinstance(health, dict):
                    health = dict(health)
                    health["transport"] = "stream"
                    health["snapshot_emitted_at"] = now_ts
                    return health
            except Exception as exc:
                logger.debug("Runtime snapshot bridge health snapshot failed: %s", exc)
        return {
            "transport": "snapshot_poll",
            "stream_service": False,
            "stream_owner": "runner",
            "snapshot_emitted_at": now_ts,
        }

    def _should_rebuild(
        self,
        section_name: str,
        event_set: Iterable[str],
        force: bool,
    ) -> bool:
        if force:
            return True
        triggers = {
            "market": {"ticker", "health", "timer"},
            "open_orders": {"order", "health", "startup", "timer"},
            "positions": {"position", "execution", "order", "health", "startup", "timer"},
            "summary": {"execution", "position", "health", "startup", "timer"},
            "bots_runtime": {"ticker", "orderbook", "position", "execution", "order", "health", "startup", "timer"},
            "bots_runtime_light": {"ticker", "orderbook", "position", "execution", "order", "health", "startup", "timer"},
        }.get(section_name, {"timer"})
        if not (set(event_set) & triggers):
            return False
        last_publish_at = self._last_publish_at.get(section_name, 0.0)
        min_interval = self._resolve_rebuild_interval_sec(section_name, event_set)
        if (time.time() - last_publish_at) < min_interval:
            return False
        return True

    def _resolve_rebuild_interval_sec(
        self,
        section_name: str,
        event_set: Iterable[str],
    ) -> float:
        base_interval = float(self.REBUILD_INTERVALS_SEC.get(section_name, 1.0))
        event_overrides = self.EVENT_REBUILD_INTERVALS_SEC.get(section_name) or {}
        if not isinstance(event_overrides, dict):
            return base_interval
        effective_interval = base_interval
        for event_name in set(event_set or []):
            if event_name not in event_overrides:
                continue
            try:
                effective_interval = min(
                    effective_interval,
                    max(float(event_overrides[event_name]), 0.0),
                )
            except (TypeError, ValueError):
                continue
        return effective_interval

    def _build_publish_diagnostics(
        self,
        *,
        reason: str,
        event_set: Iterable[str],
        force: bool,
        sections: Dict[str, Any],
        rebuild_plan: Dict[str, bool],
        started_at: float,
    ) -> Dict[str, Any]:
        diag = {
            "reason": reason,
            "event_types": sorted(set(event_set or [])),
            "force": bool(force),
            "pass_started_at": started_at,
            "pass_elapsed_ms": 0.0,
            "write_events": [],
            "sections": {},
        }
        for name, planned in rebuild_plan.items():
            existing = sections.get(name) if isinstance(sections, dict) else None
            existing_payload = (
                existing.get("payload")
                if isinstance(existing, dict)
                else None
            )
            diag["sections"][name] = {
                "section": name,
                "upstream_dependency": self.SECTION_DEPENDENCIES.get(name),
                "planned_rebuild": bool(planned),
                "start_at": None,
                "end_at": None,
                "elapsed_ms": None,
                "success": None,
                "stale_data": (
                    bool(existing_payload.get("stale_data"))
                    if isinstance(existing_payload, dict)
                    else None
                ),
                "stale_reason": (
                    self._derive_section_stale_reason(name, existing_payload)
                    if isinstance(existing_payload, dict)
                    else None
                ),
                "error": (
                    existing_payload.get("error")
                    if isinstance(existing_payload, dict)
                    else None
                ),
                "reused_previous": bool(existing) and not bool(planned),
                "skipped": not bool(planned),
                "present_before_pass": bool(existing),
            }
        return diag

    def _run_publish_section(
        self,
        publish_diag: Dict[str, Any],
        section_name: str,
        builder,
    ) -> Dict[str, Any]:
        info = (
            publish_diag.setdefault("sections", {}).setdefault(section_name, {})
            if isinstance(publish_diag, dict)
            else {}
        )
        start_ts = time.time()
        info["planned_rebuild"] = True
        info["start_at"] = start_ts
        info["skipped"] = False
        info["reused_previous"] = False
        try:
            payload = builder()
        except Exception as exc:
            end_ts = time.time()
            info["end_at"] = end_ts
            info["elapsed_ms"] = round(max(end_ts - start_ts, 0.0) * 1000.0, 2)
            info["success"] = False
            info["stale_data"] = True
            info["stale_reason"] = "exception"
            info["error"] = str(exc)
            publish_diag["pass_elapsed_ms"] = round(
                max(end_ts - float(publish_diag.get("pass_started_at") or end_ts), 0.0)
                * 1000.0,
                2,
            )
            raise
        end_ts = time.time()
        payload_dict = payload if isinstance(payload, dict) else {}
        info["end_at"] = end_ts
        info["elapsed_ms"] = round(max(end_ts - start_ts, 0.0) * 1000.0, 2)
        info["success"] = True
        info["stale_data"] = bool(payload_dict.get("stale_data"))
        info["stale_reason"] = self._derive_section_stale_reason(
            section_name,
            payload_dict,
        )
        info["error"] = payload_dict.get("error")
        return payload_dict

    def _write_publish_snapshot(
        self,
        snapshot: Dict[str, Any],
        publish_diag: Dict[str, Any],
        *,
        stage: str,
    ) -> None:
        requested_at = time.time()
        publish_diag["pass_elapsed_ms"] = round(
            max(requested_at - float(publish_diag.get("pass_started_at") or requested_at), 0.0)
            * 1000.0,
            2,
        )
        write_event = {
            "stage": stage,
            "requested_at": requested_at,
        }
        publish_diag.setdefault("write_events", []).append(write_event)
        if stage == "final":
            publish_diag["final_write_requested_at"] = requested_at
        if stage != "final":
            snapshot.setdefault("meta", {})["publish_pass"] = self._copy(publish_diag)
            with self._state_lock:
                snapshot["meta"]["snapshot_epoch"] = self._next_writer_seq
                self._next_writer_seq += 1
                self._write_snapshot(snapshot)
                self._last_snapshot = self._copy(snapshot)
            completed_at = time.time()
            write_event["completed_at"] = completed_at
            publish_diag["pass_elapsed_ms"] = round(
                max(completed_at - float(publish_diag.get("pass_started_at") or completed_at), 0.0)
                * 1000.0,
                2,
            )
            return

        with self._state_lock:
            snapshot_epoch = self._next_writer_seq
        snapshot_meta = snapshot.setdefault("meta", {})
        snapshot_meta.pop("publish_pass", None)
        snapshot_meta["snapshot_epoch"] = snapshot_epoch
        write_stats = self._write_snapshot(snapshot)
        completed_at = time.time()
        write_event["completed_at"] = completed_at
        self._finalize_publish_diagnostics(
            publish_diag,
            snapshot=snapshot,
            completed_at=completed_at,
            write_stats=write_stats,
        )
        snapshot["meta"]["publish_pass"] = self._copy(publish_diag)
        with self._state_lock:
            snapshot["meta"]["snapshot_epoch"] = self._next_writer_seq
            self._next_writer_seq += 1
            self._write_snapshot(snapshot)
            self._last_snapshot = self._copy(snapshot)

    def _finalize_publish_diagnostics(
        self,
        publish_diag: Dict[str, Any],
        *,
        snapshot: Dict[str, Any],
        completed_at: float,
        write_stats: Optional[Dict[str, Any]],
    ) -> None:
        normalized_write_stats = write_stats if isinstance(write_stats, dict) else {}
        publish_diag["final_write_completed_at"] = completed_at
        publish_diag["pass_elapsed_ms"] = round(
            max(completed_at - float(publish_diag.get("pass_started_at") or completed_at), 0.0)
            * 1000.0,
            2,
        )
        publish_diag["serialization_ms"] = round(
            self._safe_float(normalized_write_stats.get("serialization_ms"), 0.0),
            3,
        )
        publish_diag["write_file_ms"] = round(
            self._safe_float(normalized_write_stats.get("write_file_ms"), 0.0),
            3,
        )
        publish_diag["total_bytes"] = max(
            int(normalized_write_stats.get("total_bytes") or 0),
            0,
        )

        sections = publish_diag.get("sections") or {}
        long_pole_name = None
        long_pole_elapsed_ms = -0.01
        for name in (
            "market",
            "open_orders",
            "positions",
            "summary",
            "bots_runtime_light",
            "bots_runtime",
        ):
            elapsed_ms = self._safe_float((sections.get(name) or {}).get("elapsed_ms"), 0.0)
            if elapsed_ms > long_pole_elapsed_ms:
                long_pole_name = name
                long_pole_elapsed_ms = elapsed_ms
        publish_diag["long_pole_section"] = long_pole_name

        section_ages_at_final_ms: Dict[str, Optional[float]] = {}
        max_section_age_at_final_ms = None
        snapshot_sections = snapshot.get("sections") or {}
        for name in (
            "market",
            "open_orders",
            "positions",
            "summary",
            "bots_runtime_light",
            "bots_runtime",
        ):
            section = snapshot_sections.get(name) or {}
            published_at = self._safe_float(section.get("published_at"), 0.0)
            age_ms = (
                round(max(completed_at - published_at, 0.0) * 1000.0, 2)
                if published_at > 0
                else None
            )
            section_ages_at_final_ms[name] = age_ms
            if age_ms is None:
                continue
            if max_section_age_at_final_ms is None or age_ms > max_section_age_at_final_ms:
                max_section_age_at_final_ms = age_ms
        publish_diag["section_ages_at_final_ms"] = section_ages_at_final_ms
        publish_diag["max_section_age_at_final_ms"] = max_section_age_at_final_ms

    def _maybe_log_publish_diagnostics(self, publish_diag: Dict[str, Any]) -> None:
        total_ms = self._safe_float(publish_diag.get("pass_elapsed_ms"), 0.0)
        sections = publish_diag.get("sections") or {}
        section_summaries: List[str] = []
        slow_section_names: List[str] = []
        failed_sections: List[str] = []
        for name in (
            "market",
            "open_orders",
            "positions",
            "summary",
            "bots_runtime_light",
            "bots_runtime",
        ):
            info = sections.get(name) or {}
            elapsed_ms = self._safe_float(info.get("elapsed_ms"), 0.0)
            skipped = bool(info.get("skipped"))
            reused = bool(info.get("reused_previous"))
            if skipped:
                status = "skipped"
            elif info.get("success") is False:
                status = "failed"
                failed_sections.append(name)
            elif bool(info.get("stale_data")):
                status = "stale"
            else:
                status = "ok"
            if reused:
                status = f"{status}/reused"
            if elapsed_ms >= self.PUBLISH_DIAGNOSTIC_SLOW_SECTION_MS:
                slow_section_names.append(name)
            elapsed_label = (
                f"{round(elapsed_ms, 1)}ms"
                if elapsed_ms > 0
                else "-"
            )
            section_summaries.append(f"{name}={status}@{elapsed_label}")

        should_log = bool(failed_sections or slow_section_names) or (
            total_ms >= self.PUBLISH_DIAGNOSTIC_SLOW_PASS_MS
        )
        if not should_log:
            return
        now_mono = time.monotonic()
        if (
            self._last_publish_diag_log_at > 0
            and (now_mono - self._last_publish_diag_log_at)
            < self.PUBLISH_DIAGNOSTIC_LOG_THROTTLE_SEC
        ):
            return
        self._last_publish_diag_log_at = now_mono
        logger.warning(
            "Runtime snapshot bridge publish pass total_ms=%.1f reason=%s "
            "slow_sections=%s failed_sections=%s final_write_completed_at=%.3f sections=%s",
            total_ms,
            publish_diag.get("reason"),
            ",".join(slow_section_names) or "-",
            ",".join(failed_sections) or "-",
            self._safe_float(publish_diag.get("final_write_completed_at"), 0.0),
            "; ".join(section_summaries),
        )

    @staticmethod
    def _derive_section_stale_reason(
        section_name: str,
        payload: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        if not bool(payload.get("stale_data")):
            return None
        error = str(payload.get("error") or "").strip()
        if error:
            return error
        normalized = str(section_name or "").strip().lower() or "section"
        return f"{normalized}_stale"

    @staticmethod
    def _wrap_section(
        payload: Dict[str, Any],
        *,
        reason: str,
        published_at: float,
        source: str,
    ) -> Dict[str, Any]:
        return {
            "published_at": published_at,
            "reason": reason,
            "source": source,
            "payload": payload,
        }

    def _get_bots_cached(self, max_age: float = 5.0) -> List[Dict[str, Any]]:
        """Return bot list, caching for up to max_age seconds to avoid repeated disk reads."""
        now = time.monotonic()
        if self._cached_bots_list is not None and (now - self._cached_bots_list_at) < max_age:
            return list(self._cached_bots_list)
        bots = []
        if self.bot_storage:
            try:
                bots = self.bot_storage.list_bots()
            except Exception:
                bots = list(self._cached_bots_list or [])
        self._cached_bots_list = list(bots)
        self._cached_bots_list_at = now
        return bots

    def _collect_market_symbols(self) -> List[str]:
        started_at = time.monotonic()
        diagnostics: Dict[str, Any] = {
            "path": "running_bots",
            "symbol_count": 0,
            "symbol_collection_ms": 0.0,
            "bot_storage_cache_result_counts": {},
            "bot_storage_phase_ms": {},
            "bot_storage_lock_wait_ms": {},
        }
        symbols = set()
        if self.bot_storage:
            try:
                with self.bot_storage.capture_read_diagnostics(
                    "runtime_snapshot_bridge.market_symbols"
                ) as storage_diag:
                    bots = self.bot_storage.list_bots(
                        source="runtime_bridge_market_symbols",
                        projector=extract_market_symbol_bot,
                        read_only_projected_cache=True,
                    )
                diagnostics["bot_storage_cache_result_counts"] = dict(
                    storage_diag.get("cache_result_counts") or {}
                )
                diagnostics["bot_storage_phase_ms"] = {
                    key: round(float(value or 0.0), 3)
                    for key, value in (storage_diag.get("phase_ms") or {}).items()
                }
                diagnostics["bot_storage_lock_wait_ms"] = {
                    key: round(float(value or 0.0), 3)
                    for key, value in (storage_diag.get("lock_wait_ms") or {}).items()
                }
                diagnostics["bot_candidate_count"] = len(bots or [])
                for bot in bots or []:
                    if bot.get("status") != "running":
                        continue
                    symbol = str(bot.get("symbol") or "").strip().upper()
                    if not symbol or symbol == "AUTO-PILOT":
                        continue
                    symbols.add(symbol)
            except Exception as exc:
                diagnostics["bot_storage_error"] = str(exc)
                logger.debug("Runtime snapshot bridge symbol collection failed: %s", exc)

        if not symbols and self.bot_status_service and hasattr(
            self.bot_status_service,
            "get_runtime_positions_payload",
        ):
            # Use cached positions to avoid exchange API calls on every cycle
            now = time.monotonic()
            cache = getattr(self, "_market_symbols_cache", None)
            if cache and (now - cache.get("at", 0)) < 30.0:
                cached_symbols = list(cache.get("symbols", []))
                diagnostics["path"] = "positions_cache"
                diagnostics["positions_cached"] = True
                diagnostics["symbol_count"] = len(cached_symbols)
                diagnostics["symbol_collection_ms"] = round(
                    max(time.monotonic() - started_at, 0.0) * 1000.0,
                    3,
                )
                self._last_market_symbol_diagnostics = diagnostics
                return cached_symbols
            try:
                positions_payload = self.bot_status_service.get_runtime_positions_payload(
                    skip_cache=False
                )
                for position in positions_payload.get("positions", []) or []:
                    symbol = str(position.get("symbol") or "").strip().upper()
                    if symbol:
                        symbols.add(symbol)
                self._market_symbols_cache = {"symbols": sorted(symbols), "at": now}
                diagnostics["path"] = "positions_payload"
                diagnostics["positions_cached"] = False
            except Exception as exc:
                diagnostics["positions_error"] = str(exc)
                logger.debug(
                    "Runtime snapshot bridge position symbol collection failed: %s",
                    exc,
                )

        sorted_symbols = sorted(symbols)
        diagnostics["symbol_count"] = len(sorted_symbols)
        diagnostics["symbol_collection_ms"] = round(
            max(time.monotonic() - started_at, 0.0) * 1000.0,
            3,
        )
        self._last_market_symbol_diagnostics = diagnostics
        return sorted_symbols

    def _build_market_payload(
        self,
        *,
        symbols: List[str],
        health: Dict[str, Any],
    ) -> Dict[str, Any]:
        build_started = time.monotonic()
        shaping_ms = 0.0
        prices = {}
        stale_data = False
        missing_symbols: List[str] = []
        fresh_symbol_count = 0
        requested_symbol_count = len(list(symbols or []))
        price_received_at: Dict[str, float] = {}
        ticker_topic_fresh: Optional[bool] = None
        runtime_diagnostics = self._copy(
            getattr(self, "_last_market_symbol_diagnostics", None) or {}
        )
        runtime_diagnostics["symbol_source"] = runtime_diagnostics.get("path")
        runtime_diagnostics["path"] = "stream_dashboard_snapshot"
        runtime_diagnostics["health_source"] = (
            "meta_stream_health" if health else "stream_snapshot"
        )
        snapshot_fetch_started = time.monotonic()
        if self.stream_service and hasattr(self.stream_service, "get_dashboard_snapshot"):
            try:
                snapshot = self.stream_service.get_dashboard_snapshot(
                    symbols,
                    include_health=False,
                    symbols_are_normalized=True,
                ) or {}
                runtime_diagnostics["snapshot_fetch_ms"] = round(
                    max(time.monotonic() - snapshot_fetch_started, 0.0) * 1000.0,
                    3,
                )
                shaping_started = time.monotonic()
                prices = dict(snapshot.get("prices") or {})
                stale_data = bool(snapshot.get("stale_data"))
                missing_symbols = list(snapshot.get("missing_symbols") or [])
                fresh_symbol_count = int(snapshot.get("fresh_symbol_count") or 0)
                requested_symbol_count = int(
                    snapshot.get("requested_symbol_count") or requested_symbol_count
                )
                price_received_at = dict(snapshot.get("price_received_at") or {})
                if "ticker_topic_fresh" in snapshot:
                    raw_ticker_topic_fresh = snapshot.get("ticker_topic_fresh")
                    ticker_topic_fresh = (
                        None
                        if raw_ticker_topic_fresh is None
                        else bool(raw_ticker_topic_fresh)
                    )
                if not health:
                    health = dict(snapshot.get("health") or {})
                    runtime_diagnostics["health_source"] = "stream_snapshot"
                shaping_ms = round(
                    max(time.monotonic() - shaping_started, 0.0) * 1000.0,
                    3,
                )
            except Exception as exc:
                logger.debug("Runtime snapshot bridge market snapshot failed: %s", exc)
                stale_data = True
                runtime_diagnostics["path"] = "stream_dashboard_snapshot_error"
                runtime_diagnostics["error"] = str(exc)
                runtime_diagnostics["snapshot_fetch_ms"] = round(
                    max(time.monotonic() - snapshot_fetch_started, 0.0) * 1000.0,
                    3,
                )
        else:
            runtime_diagnostics["path"] = "stream_service_unavailable"
            runtime_diagnostics["snapshot_fetch_ms"] = round(
                max(time.monotonic() - snapshot_fetch_started, 0.0) * 1000.0,
                3,
            )
        runtime_diagnostics["shaping_ms"] = shaping_ms
        runtime_diagnostics["requested_symbol_count"] = requested_symbol_count
        runtime_diagnostics["fresh_symbol_count"] = fresh_symbol_count
        runtime_diagnostics["missing_symbol_count"] = len(missing_symbols)
        runtime_diagnostics["total_ms"] = round(
            max(time.monotonic() - build_started, 0.0) * 1000.0,
            3,
        )
        return {
            "health": health,
            "prices": prices,
            "symbols": list(symbols or []),
            "stale_data": stale_data,
            "missing_symbols": missing_symbols,
            "fresh_symbol_count": fresh_symbol_count,
            "requested_symbol_count": requested_symbol_count,
            "price_received_at": price_received_at,
            "ticker_topic_fresh": ticker_topic_fresh,
            "market_runtime_diagnostics": runtime_diagnostics,
        }

    def _get_cached_account_snapshot(self, *, force: bool) -> Dict[str, Any]:
        cached = self._copy(self._last_account_snapshot) if self._last_account_snapshot else None
        if cached and not force:
            return cached
        if not self.account_service:
            return cached or {
                "equity": 0.0,
                "available_balance": 0.0,
                "funding_balance": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "error": "account_service_unavailable",
            }
        try:
            account_snapshot = self.account_service.get_overview() or {}
        except Exception as exc:
            logger.warning("Runtime snapshot bridge account overview failed: %s", exc)
            account_snapshot = {
                "equity": 0.0,
                "available_balance": 0.0,
                "funding_balance": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "error": str(exc),
                "stale_data": True,
            }
        self._last_account_snapshot = self._copy(account_snapshot)
        return account_snapshot

    def _build_positions_payload(
        self,
        account_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = {
            "positions": [],
            "summary": {
                "total_positions": 0,
                "longs": 0,
                "shorts": 0,
                "total_unrealized_pnl": 0.0,
                "total_position_value": 0.0,
                "account_equity": 0.0,
                "total_effective_leverage": None,
            },
            "wallet_balance": 0.0,
            "available_balance": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "error": None,
        }
        if self.bot_status_service and hasattr(
            self.bot_status_service,
            "get_runtime_positions_payload",
        ):
            try:
                result = (
                    self.bot_status_service.get_runtime_positions_payload(
                        skip_cache=False
                    )
                    or result
                )
            except Exception as exc:
                logger.warning("Runtime snapshot bridge positions build failed: %s", exc)
                result["error"] = str(exc)
        elif self.position_service:
            try:
                result = self.position_service.get_positions(skip_cache=False) or result
            except Exception as exc:
                logger.warning("Runtime snapshot bridge positions build failed: %s", exc)
                result["error"] = str(exc)

        account = account_payload or self._get_cached_account_snapshot(force=False)
        account_equity = self._safe_float(
            account.get("equity")
            or account.get("wallet_balance")
            or account.get("available_balance"),
            0.0,
        )
        result["wallet_balance"] = (
            account.get("equity")
            or account.get("wallet_balance")
            or account.get("available_balance")
            or 0
        )
        result["available_balance"] = float(account.get("available_balance", 0) or 0)
        result["realized_pnl"] = account.get("realized_pnl", 0)
        result["unrealized_pnl"] = account.get("unrealized_pnl", 0)
        summary = result.setdefault("summary", {})
        total_position_value = 0.0
        for position in result.get("positions", []) or []:
            total_position_value += self._safe_float(position.get("position_value"), 0.0)
        summary["total_position_value"] = round(total_position_value, 2)
        summary["account_equity"] = round(account_equity, 2) if account_equity > 0 else 0.0
        summary["total_effective_leverage"] = (
            round(total_position_value / account_equity, 2)
            if account_equity > 0 and total_position_value > 0
            else None
        )

        bots = []
        if self.bot_storage:
            try:
                bots = self.bot_storage.list_bots()
            except Exception as exc:
                logger.debug("Runtime snapshot bridge bot list failed: %s", exc)

        bot_lookup: Dict[str, List[Dict[str, Any]]] = {}
        bot_ids_by_symbol: Dict[str, List[str]] = {}
        for bot in bots:
            symbol = bot.get("symbol")
            if symbol and bot.get("status") in LIVE_POSITION_OWNER_STATUSES:
                bot_lookup.setdefault(symbol, []).append(bot)
                bot_ids_by_symbol.setdefault(symbol, []).append(bot.get("id"))

        for position in result.get("positions", []) or []:
            symbol = position.get("symbol")
            matching_bots = bot_lookup.get(symbol, [])
            position["bot_count_for_symbol"] = len(matching_bots)
            if len(matching_bots) == 1:
                bot = matching_bots[0]
                position["bot_mode"] = bot.get("mode", "neutral")
                position["bot_range_mode"] = bot.get("range_mode", "fixed")
                position["tp_pct"] = bot.get("tp_pct")
                position["auto_stop"] = bot.get("auto_stop")
                position["auto_stop_target_usdt"] = bot.get(
                    "auto_stop_target_usdt", 0
                )
                position["bot_id"] = bot.get("id")
                position["bot_attribution"] = "unique_running_bot"
                position["bot_ids"] = [bot.get("id")] if bot.get("id") else []
                position["bot_modes"] = [bot.get("mode", "neutral")]
                position["bot_range_modes"] = [bot.get("range_mode", "fixed")]
            else:
                position["bot_mode"] = None
                position["bot_range_mode"] = None
                position["tp_pct"] = None
                position["auto_stop"] = None
                position["auto_stop_target_usdt"] = 0
                position["bot_id"] = None
                position["bot_attribution"] = (
                    "ambiguous_symbol" if len(matching_bots) > 1 else "none"
                )
                position["bot_ids"] = [
                    bot_id for bot_id in bot_ids_by_symbol.get(symbol, []) if bot_id
                ]
                position["bot_modes"] = [
                    bot.get("mode", "neutral") for bot in matching_bots
                ]
                position["bot_range_modes"] = [
                    bot.get("range_mode", "fixed") for bot in matching_bots
                ]
        result.setdefault("stale_data", False)
        return result

    def _build_summary_payload(
        self,
        *,
        account_payload: Dict[str, Any],
        positions_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        today = {}
        if self.pnl_service:
            try:
                today = self.pnl_service.get_today_stats()
            except Exception as exc:
                logger.debug("Runtime snapshot bridge today pnl failed: %s", exc)

        risk_state = {}
        if self.risk_manager and hasattr(self.risk_manager, "get_risk_state"):
            try:
                risk_state = self.risk_manager.get_risk_state() or {}
            except Exception as exc:
                logger.debug("Runtime snapshot bridge risk state failed: %s", exc)

        summary = {
            "account": account_payload,
            "positions_summary": positions_payload.get("summary", {}),
            "today_pnl": today,
            "daily_loss_pct": risk_state.get("daily_loss_pct", 0.0),
            "kill_switch_triggered": risk_state.get("kill_switch_triggered", False),
            "kill_switch_triggered_at": risk_state.get("kill_switch_triggered_at"),
        }
        summary.setdefault("stale_data", False)
        self._last_summary_snapshot = self._copy(summary)
        return summary

    def _build_bots_runtime_payload(self, cache_only: bool = False) -> Dict[str, Any]:
        if not self.bot_status_service:
            return {
                "bots": [],
                "error": "bot_status_service_unavailable",
                "stale_data": True,
                "runtime_state_source": "bot_status_service_unavailable",
            }
        # Fast cycle: return cached payload from last full build if available
        if cache_only and self._cached_bots_runtime_payload is not None:
            return self._copy(self._cached_bots_runtime_payload)
        try:
            bots = self.bot_status_service.get_runtime_bots(
                positions_skip_cache=False, cache_only=cache_only
            )
            cache_status = (
                self.bot_status_service.get_last_runtime_cache_status()
                if hasattr(self.bot_status_service, "get_last_runtime_cache_status")
                else {}
            )
            batch_context = (
                self.bot_status_service.get_last_runtime_batch_context()
                if hasattr(self.bot_status_service, "get_last_runtime_batch_context")
                else {}
            )
            payload = {
                "bots": bots,
                "error": cache_status.get("error"),
                "stale_data": bool(cache_status.get("stale_data")),
                "runtime_state_source": "runner_runtime_bots",
            }
            if isinstance(batch_context, dict):
                payload["runtime_publish_at"] = batch_context.get("runtime_publish_at")
                payload["runtime_publish_ts"] = batch_context.get("runtime_publish_ts")
                payload["runtime_build_duration_ms"] = batch_context.get(
                    "runtime_build_duration_ms"
                )
                payload["readiness_latency"] = dict(
                    batch_context.get("readiness_latency") or {}
                )
            if not cache_only:
                self._cached_bots_runtime_payload = self._copy(payload)
            return payload
        except Exception as exc:
            logger.warning("Runtime snapshot bridge bot runtime build failed: %s", exc)
            try:
                fallback_bots = (
                    self._get_bots_cached()
                )
            except Exception:
                fallback_bots = []
            return {
                "bots": fallback_bots,
                "error": str(exc),
                "stale_data": True,
                "runtime_state_source": "storage_fallback",
            }

    # ------------------------------------------------------------------
    # Light bots runtime — dashboard-critical fields, cache-only lookups
    # ------------------------------------------------------------------

    def _build_bots_runtime_light_payload(self) -> Dict[str, Any]:
        """Build lightweight bot runtime payload for fast publish cadence."""
        if not self.bot_status_service:
            return {
                "bots": [],
                "error": "bot_status_service_unavailable",
                "stale_data": True,
                "runtime_state_source": "bot_status_service_unavailable",
                "bots_scope": "light",
            }
        try:
            bots = self.bot_status_service.get_runtime_bots_light(
                positions_skip_cache=False,
            )
            light_runtime_diagnostics = (
                self.bot_status_service.get_last_runtime_light_diagnostics()
                if hasattr(self.bot_status_service, "get_last_runtime_light_diagnostics")
                else {}
            )
            return {
                "bots": bots,
                "error": None,
                "stale_data": False,
                "runtime_state_source": "runner_runtime_bots_light",
                "runtime_publish_ts": time.time(),
                "bots_scope": "light",
                "light_runtime_diagnostics": (
                    dict(light_runtime_diagnostics)
                    if isinstance(light_runtime_diagnostics, dict)
                    else {}
                ),
            }
        except Exception as exc:
            logger.warning("Runtime snapshot bridge light bot runtime build failed: %s", exc)
            try:
                fallback_bots = self._get_bots_cached()
            except Exception:
                fallback_bots = []
            return {
                "bots": fallback_bots,
                "error": str(exc),
                "stale_data": True,
                "runtime_state_source": "storage_fallback",
                "bots_scope": "light",
            }

    # ------------------------------------------------------------------
    # Background full-enrichment loop — runs on a separate thread so the
    # fast publish loop is never blocked.
    # ------------------------------------------------------------------

    def _run_full_enrich_loop(self) -> None:
        """Background thread: periodically runs expensive get_runtime_bots()
        and stores the result for the fast publish loop to read.

        The fast publish loop NEVER waits on this thread — it always reads
        the last cached result (or an explicitly stale placeholder).
        """
        # Allow the first light publish to happen before we do the expensive
        # first full build — sleep briefly to avoid startup contention.
        self._enrich_stop_event.wait(timeout=2.0)

        while not self._enrich_stop_event.is_set():
            now_mono = time.monotonic()
            if (now_mono - self._last_full_enrich_at) >= self._full_enrich_interval_sec:
                self._full_enrich_in_progress = True
                self._light_publish_count_during_full = 0
                build_start = time.monotonic()
                try:
                    payload = self._do_full_enrich_build()
                    duration_ms = round((time.monotonic() - build_start) * 1000.0, 1)
                    with self._enrich_result_lock:
                        self._cached_bots_runtime_payload = self._copy(payload)
                        self._full_enrich_last_duration_ms = duration_ms
                    self._last_full_enrich_at = time.monotonic()
                    logger.debug(
                        "Background full enrichment completed in %.1fms "
                        "(light publishes during build: %d)",
                        duration_ms,
                        self._light_publish_count_during_full,
                    )
                except Exception as exc:
                    logger.warning("Background full enrichment failed: %s", exc)
                finally:
                    self._full_enrich_in_progress = False
            self._enrich_stop_event.wait(timeout=1.0)

    def _do_full_enrich_build(self) -> Dict[str, Any]:
        """Run the full get_runtime_bots() call.  Called only from the
        background enrichment thread — never from the fast publish loop."""
        bots = self.bot_status_service.get_runtime_bots(
            positions_skip_cache=False,
            cache_only=False,
        )
        cache_status = (
            self.bot_status_service.get_last_runtime_cache_status()
            if hasattr(self.bot_status_service, "get_last_runtime_cache_status")
            else {}
        )
        batch_context = (
            self.bot_status_service.get_last_runtime_batch_context()
            if hasattr(self.bot_status_service, "get_last_runtime_batch_context")
            else {}
        )
        payload = {
            "bots": bots,
            "error": cache_status.get("error"),
            "stale_data": bool(cache_status.get("stale_data")),
            "runtime_state_source": "runner_runtime_bots",
            "bots_scope": "full",
        }
        if isinstance(batch_context, dict):
            payload["runtime_publish_at"] = batch_context.get("runtime_publish_at")
            payload["runtime_publish_ts"] = batch_context.get("runtime_publish_ts")
            payload["runtime_build_duration_ms"] = batch_context.get(
                "runtime_build_duration_ms"
            )
            payload["readiness_latency"] = dict(
                batch_context.get("readiness_latency") or {}
            )
        return payload

    def get_enrichment_diagnostics(self) -> Dict[str, Any]:
        """Expose diagnostics proving the light/full separation works."""
        with self._enrich_result_lock:
            has_cached_full = self._cached_bots_runtime_payload is not None
            full_enrich_duration_ms = self._full_enrich_last_duration_ms
        return {
            "full_enrich_in_progress": self._full_enrich_in_progress,
            "full_enrich_interval_sec": self._full_enrich_interval_sec,
            "full_enrich_last_duration_ms": full_enrich_duration_ms,
            "full_enrich_has_cached_payload": has_cached_full,
            "last_full_enrich_at": self._last_full_enrich_at,
            "light_publish_count_during_last_full": self._light_publish_count_during_full,
            "enrich_thread_alive": (
                self._enrich_thread.is_alive()
                if self._enrich_thread is not None
                else False
            ),
        }

    def _build_open_orders_payload(self) -> Dict[str, Any]:
        bots = self._get_bots_cached()

        symbols_summary = {}
        open_orders_runtime_diagnostics = None
        if self.bot_status_service and hasattr(
            self.bot_status_service,
            "get_live_open_order_summary_by_symbol",
        ):
            try:
                symbols_summary = self.bot_status_service.get_live_open_order_summary_by_symbol(bots)
                if hasattr(self.bot_status_service, "get_last_live_open_orders_diagnostics"):
                    open_orders_runtime_diagnostics = (
                        self.bot_status_service.get_last_live_open_orders_diagnostics()
                    )
            except Exception as exc:
                logger.debug("Runtime snapshot bridge open order summary failed: %s", exc)
        elif self.bot_status_service and hasattr(
            self.bot_status_service,
            "get_live_open_orders_by_symbol",
        ):
            order_map = {}
            try:
                order_map = self.bot_status_service.get_live_open_orders_by_symbol(bots)
            except Exception as exc:
                logger.debug("Runtime snapshot bridge open order summary failed: %s", exc)
            for symbol, orders in (order_map or {}).items():
                order_list = list(orders or [])
                symbols_summary[symbol] = {
                    "open_order_count": len(order_list),
                    "reduce_only_count": sum(
                        1 for order in order_list if bool(order.get("reduceOnly"))
                    ),
                    "entry_order_count": sum(
                        1 for order in order_list if not bool(order.get("reduceOnly"))
                    ),
                }
        return {
            "symbols": symbols_summary,
            "stale_data": False,
            "error": None,
            "open_orders_runtime_diagnostics": (
                dict(open_orders_runtime_diagnostics)
                if isinstance(open_orders_runtime_diagnostics, dict)
                else None
            ),
        }

    @staticmethod
    def _payload_shape_valid(section_name: str, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        normalized = str(section_name or "").strip().lower()
        if normalized in ("bots_runtime", "bots_runtime_light"):
            bots = payload.get("bots")
            return isinstance(bots, list) and all(isinstance(bot, dict) for bot in bots)
        if normalized == "positions":
            return isinstance(payload.get("positions"), list)
        if normalized == "summary":
            return isinstance(payload.get("account"), dict) and isinstance(
                payload.get("positions_summary"), dict
            )
        if normalized == "market":
            health = payload.get("health")
            return health is None or isinstance(health, dict)
        return True

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
