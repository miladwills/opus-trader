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
        self._last_full_enrich_at: float = 0.0

        # Background full-enrichment thread — runs independently so the fast
        # publish loop is never blocked by expensive get_runtime_bots() calls.
        self._enrich_result_lock = threading.Lock()
        self._enrich_thread: Optional[threading.Thread] = None
        self._enrich_stop_event = threading.Event()
        self._full_enrich_in_progress = False
        self._full_enrich_last_duration_ms: Optional[float] = None
        self._light_publish_count_during_full: int = 0

        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _copy(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, separators=(",", ":")))
        except (TypeError, ValueError):
            return copy.deepcopy(value)

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

    def read_snapshot(self) -> Optional[Dict[str, Any]]:
        try:
            stat = self.file_path.stat()
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug("Runtime snapshot bridge stat failed: %s", exc)
            return None

        with self._state_lock:
            if (
                self._read_cache is not None
                and self._read_cache_mtime_ns == getattr(stat, "st_mtime_ns", None)
            ):
                return self._copy(self._read_cache)

        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.debug("Runtime snapshot bridge read failed: %s", exc)
            return None

        if not isinstance(payload, dict):
            return None

        with self._state_lock:
            self._read_cache = self._copy(payload)
            self._read_cache_mtime_ns = getattr(stat, "st_mtime_ns", None)
        return self._copy(payload)

    def read_section(
        self,
        section_name: str,
        *,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        snapshot = self.read_snapshot()
        if not snapshot:
            return None
        sections = snapshot.get("sections") or {}
        if not isinstance(sections, dict):
            return None
        section = sections.get(str(section_name or "").strip())
        if not isinstance(section, dict):
            return None

        payload = self._copy(section.get("payload"))
        if not isinstance(payload, dict):
            return None

        payload_valid = self._payload_shape_valid(section_name, payload)
        if not payload_valid:
            payload.setdefault("stale_data", True)
            payload["error"] = (
                str(payload.get("error") or "").strip()
                or f"{section_name}_payload_invalid"
            )
            payload["integrity_shape_valid"] = False

        published_at = self._safe_float(section.get("published_at"), 0.0)
        now_ts = time.time()
        age_limit = (
            self._safe_float(max_age_sec, 0.0)
            if max_age_sec is not None
            else self.READ_STALE_AGE_SEC.get(section_name, 10.0)
        )
        if age_limit <= 0:
            age_limit = self.READ_STALE_AGE_SEC.get(section_name, 10.0)
        age_sec = now_ts - published_at if published_at > 0 else float("inf")
        meta = snapshot.get("meta", {}) if isinstance(snapshot.get("meta"), dict) else {}
        snapshot_fresh = age_sec <= age_limit
        if age_sec > age_limit:
            payload["stale_data"] = True
            if payload.get("error") in (None, "", 0):
                payload["error"] = f"{section_name}_stale"
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

        if self._should_rebuild("market", event_set, force):
            market_symbols = self._collect_market_symbols()
            market_health = self._build_market_health(now_ts)
            market_payload = self._build_market_payload(
                symbols=market_symbols,
                health=market_health,
            )
            market_published_at = time.time()
            sections["market"] = self._wrap_section(
                market_payload,
                reason=reason,
                published_at=market_published_at,
                source="runner_stream_snapshot",
            )
            self._last_publish_at["market"] = market_published_at

        if self._should_rebuild("open_orders", event_set, force):
            open_orders_payload = self._build_open_orders_payload()
            open_orders_published_at = time.time()
            sections["open_orders"] = self._wrap_section(
                open_orders_payload,
                reason=reason,
                published_at=open_orders_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["open_orders"] = open_orders_published_at

        positions_payload: Optional[Dict[str, Any]] = None
        if self._should_rebuild("positions", event_set, force):
            account_payload = self._get_cached_account_snapshot(force=force)
            positions_payload = self._build_positions_payload(account_payload)
            positions_published_at = time.time()
            sections["positions"] = self._wrap_section(
                positions_payload,
                reason=reason,
                published_at=positions_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["positions"] = positions_published_at

        if self._should_rebuild("summary", event_set, force):
            account_payload = self._get_cached_account_snapshot(force=True)
            if positions_payload is None:
                positions_payload = self._build_positions_payload(account_payload)
                positions_published_at = time.time()
                sections["positions"] = self._wrap_section(
                    positions_payload,
                    reason=f"{reason}:summary_positions",
                    published_at=positions_published_at,
                    source="runner_runtime_snapshot",
                )
                self._last_publish_at["positions"] = positions_published_at
            summary_payload = self._build_summary_payload(
                account_payload=account_payload,
                positions_payload=positions_payload,
            )
            summary_published_at = time.time()
            sections["summary"] = self._wrap_section(
                summary_payload,
                reason=reason,
                published_at=summary_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["summary"] = summary_published_at

        # Intermediate write on startup: publish critical sections (market,
        # open_orders, positions, summary) before the expensive bots_runtime
        # build so the dashboard gets usable data within seconds.
        if "startup" in event_set and any(
            k in sections for k in ("market", "positions", "summary")
        ):
            with self._state_lock:
                snapshot["meta"]["snapshot_epoch"] = self._next_writer_seq
                self._next_writer_seq += 1
                self._write_snapshot(snapshot)
                self._last_snapshot = self._copy(snapshot)

        # bots_runtime_light — fast, every cycle, never blocks
        if self._should_rebuild("bots_runtime_light", event_set, force):
            light_payload = self._build_bots_runtime_light_payload()
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
        if self._should_rebuild("bots_runtime", event_set, force):
            with self._enrich_result_lock:
                cached_full = (
                    self._copy(self._cached_bots_runtime_payload)
                    if self._cached_bots_runtime_payload is not None
                    else None
                )
            if cached_full is not None:
                bots_runtime_payload = cached_full
            else:
                # No full payload yet (startup or background thread hasn't
                # completed first build).  Publish an explicitly stale
                # placeholder so the section exists but is clearly marked.
                try:
                    fallback_bots = self._get_bots_cached()
                except Exception:
                    fallback_bots = []
                bots_runtime_payload = {
                    "bots": fallback_bots,
                    "error": "full_enrich_not_ready",
                    "stale_data": True,
                    "runtime_state_source": "storage_fallback_awaiting_full",
                    "bots_scope": "full",
                }
            bots_runtime_published_at = time.time()
            sections["bots_runtime"] = self._wrap_section(
                bots_runtime_payload,
                reason=reason,
                published_at=bots_runtime_published_at,
                source="runner_runtime_snapshot",
            )
            self._last_publish_at["bots_runtime"] = bots_runtime_published_at

        with self._state_lock:
            snapshot["meta"]["snapshot_epoch"] = self._next_writer_seq
            self._next_writer_seq += 1
            self._write_snapshot(snapshot)
            self._last_snapshot = self._copy(snapshot)

    def _write_snapshot(self, payload: Dict[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.file_path.parent),
                prefix=f"{self.file_path.name}.",
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
            os.replace(tmp_path, self.file_path)
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
        symbols = set()
        if self.bot_storage:
            try:
                for bot in self._get_bots_cached():
                    if bot.get("status") != "running":
                        continue
                    symbol = str(bot.get("symbol") or "").strip().upper()
                    if not symbol or symbol == "AUTO-PILOT":
                        continue
                    symbols.add(symbol)
            except Exception as exc:
                logger.debug("Runtime snapshot bridge symbol collection failed: %s", exc)

        if not symbols and self.bot_status_service and hasattr(
            self.bot_status_service,
            "get_runtime_positions_payload",
        ):
            # Use cached positions to avoid exchange API calls on every cycle
            now = time.monotonic()
            cache = getattr(self, "_market_symbols_cache", None)
            if cache and (now - cache.get("at", 0)) < 30.0:
                return list(cache.get("symbols", []))
            try:
                positions_payload = self.bot_status_service.get_runtime_positions_payload(
                    skip_cache=False
                )
                for position in positions_payload.get("positions", []) or []:
                    symbol = str(position.get("symbol") or "").strip().upper()
                    if symbol:
                        symbols.add(symbol)
                self._market_symbols_cache = {"symbols": sorted(symbols), "at": now}
            except Exception as exc:
                logger.debug(
                    "Runtime snapshot bridge position symbol collection failed: %s",
                    exc,
                )

        return sorted(symbols)

    def _build_market_payload(
        self,
        *,
        symbols: List[str],
        health: Dict[str, Any],
    ) -> Dict[str, Any]:
        prices = {}
        stale_data = False
        missing_symbols: List[str] = []
        fresh_symbol_count = 0
        requested_symbol_count = len(list(symbols or []))
        price_received_at: Dict[str, float] = {}
        ticker_topic_fresh: Optional[bool] = None
        if self.stream_service and hasattr(self.stream_service, "get_dashboard_snapshot"):
            try:
                snapshot = self.stream_service.get_dashboard_snapshot(symbols) or {}
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
            except Exception as exc:
                logger.debug("Runtime snapshot bridge market snapshot failed: %s", exc)
                stale_data = True
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
            return {
                "bots": bots,
                "error": None,
                "stale_data": False,
                "runtime_state_source": "runner_runtime_bots_light",
                "runtime_publish_ts": time.time(),
                "bots_scope": "light",
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

        order_map = {}
        if self.bot_status_service and hasattr(
            self.bot_status_service,
            "get_live_open_orders_by_symbol",
        ):
            try:
                order_map = self.bot_status_service.get_live_open_orders_by_symbol(bots)
            except Exception as exc:
                logger.debug("Runtime snapshot bridge open order summary failed: %s", exc)

        symbols_summary = {}
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
