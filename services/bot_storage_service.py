"""
Bybit Control Center - Bot Storage Service

Provides JSON-based storage for grid bot configurations and state.
Implements file locking to prevent race conditions between runner and API.
"""

from pathlib import Path
import json
import uuid
import os
import tempfile
import time
import logging
import copy
import threading
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple, Callable
from contextlib import contextmanager

from services.lock_service import file_lock
from services.mode_semantics import (
    configured_mode,
    configured_range_mode,
    runtime_mode_is_non_persistent,
)

logger = logging.getLogger(__name__)

BotProjector = Callable[[Dict[str, Any]], Dict[str, Any]]


SETTINGS_PROTECTED_FIELDS = (
    "auto_stop",
    "auto_stop_target_usdt",
    "auto_stop_target_effective_usdt",
    "auto_stop_target_session_base_usdt",
    "auto_stop_target_rearm_on_start",
    "auto_stop_armed",
    "auto_stop_triggered",
    "settings_version",
    "settings_updated_at",
)

CONTROL_PROTECTED_FIELDS = (
    "status",
    "started_at",
    "control_version",
    "control_updated_at",
    "last_error",
    "error_code",
    "symbol",
    "mode",
    "range_mode",
    "profile",
    "lower_price",
    "upper_price",
    "grid_lower_price",
    "grid_upper_price",
    "investment",
    "leverage",
    "paper_trading",
    "trading_env",
    "reduce_only_mode",
    "auto_stop_paused",
    "created_at",
)

PAUSE_RUNTIME_STATUSES = {
    "paused",
    "recovering",
    "flash_crash_paused",
    "stop_cleanup_pending",
}

PAUSE_RUNTIME_FIELDS = (
    "pause_reason",
    "pause_reason_type",
    "paused_at",
    "pause_unrealized_pnl",
    "recovery_entry_pnl",
    "_last_pause_recovery_check",
    "_last_recovery_check",
    "_neutral_trend_exit",
    "flash_crash_paused_at",
)

STOP_CLEANUP_RUNTIME_FIELDS = (
    "stop_cleanup_pending",
    "stop_cleanup_target_status",
    "stop_cleanup_scope",
    "stop_cleanup_reason",
    "stop_cleanup_requested_at",
    "stop_cleanup_final_last_error",
)

AUTO_PILOT_PLACEHOLDER_PROTECTED_FIELDS = (
    "lower_price",
    "upper_price",
    "grid_lower_price",
    "grid_upper_price",
    "grid_levels_total",
    "current_price",
    "last_trade_price",
    "open_order_count",
    "entry_orders_open",
    "exit_orders_open",
    "active_long_slots",
    "active_short_slots",
    "neutral_grid",
    "neutral_grid_initialized",
    "_entry_structure_skip_buy",
    "_entry_structure_skip_sell",
    "neutral_grid_last_reconcile_at",
    "grid_levels_total_effective",
    "levels_count",
    "mid_index",
    "last_fill_event",
    "auto_pilot_first_orders_at",
    "auto_pilot_last_fill_at",
    "last_replacement_action",
    "_last_recenter_ts",
    "_position_mode",
    "_position_mode_ts",
    "_entry_structure_buy_reason",
    "_entry_structure_sell_reason",
)

PNL_PROTECTED_FIELDS = (
    "realized_pnl",
    "total_pnl",
)

DEFAULT_INTERNAL_LOCK_TIMEOUT_SEC = max(
    float(os.environ.get("BOT_STORAGE_INTERNAL_LOCK_TIMEOUT_SEC", "0.25") or 0.25),
    0.01,
)
RUNTIME_PERSIST_OBSERVATION_LOG_INTERVAL_SEC = 60.0
READ_OBSERVATION_LOG_INTERVAL_SEC = 60.0


class BotStorageService:
    """
    Service for persisting bot data to JSON file storage.
    Uses file locking to prevent concurrent access issues.
    """

    def __init__(self, file_path: str):
        """
        Initialize the bot storage service.

        Args:
            file_path: Path to the JSON file for bot storage
        """
        self.file_path = Path(file_path)
        self.lock_path = Path(str(file_path) + ".lock")
        self._cache_lock = threading.RLock()
        self._cached_bots: Optional[List[Dict[str, Any]]] = None
        self._cached_mtime_ns: Optional[int] = None
        self._cached_projected_bots: Dict[int, Dict[str, Any]] = {}
        self._runtime_lock = threading.RLock()
        self._pending_runtime_updates: Dict[str, Dict[str, Any]] = {}
        self._runtime_flush_timer: Optional[threading.Timer] = None
        self._runtime_persist_observation_lock = threading.RLock()
        self._runtime_persist_observations: Dict[str, Dict[str, Any]] = {}
        self._read_observation_lock = threading.RLock()
        self._read_observations: Dict[str, Dict[str, Any]] = {}
        self._read_diagnostics_local = threading.local()
        self.runtime_flush_delay_sec = max(
            float(os.environ.get("BOT_RUNTIME_FLUSH_DELAY_SEC", "0.5") or 0.5),
            0.1,
        )
        self.internal_lock_timeout_sec = DEFAULT_INTERNAL_LOCK_TIMEOUT_SEC

        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create lock file if it doesn't exist
        if not self.lock_path.exists():
            self.lock_path.touch()

        # Create file with empty array if it doesn't exist
        if not self.file_path.exists():
            self._write_all_locked([])

    @staticmethod
    def _clone_bots(bots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return copy.deepcopy(bots)

    @staticmethod
    def _materialize_bots(
        bots: List[Dict[str, Any]],
        *,
        projector: Optional[BotProjector] = None,
    ) -> List[Dict[str, Any]]:
        if projector is None:
            return copy.deepcopy(bots)
        materialized: List[Dict[str, Any]] = []
        for bot in bots:
            projected = projector(bot)
            materialized.append(copy.deepcopy(projected if isinstance(projected, dict) else {}))
        return materialized

    @staticmethod
    def _projector_cache_key(projector: BotProjector) -> int:
        return id(projector)

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
        source: Optional[str] = None,
        cache_result: Optional[str] = None,
        full_list_read: bool = False,
        elapsed_ms: Optional[float] = None,
        metric_name: Optional[str] = None,
        metric_ms: Optional[float] = None,
        bot_count: Optional[int] = None,
    ) -> None:
        trace = self._active_read_diagnostics()
        if trace is None:
            return
        if operation:
            self._increment_counter(trace.setdefault("operation_counts", {}), operation)
        if source:
            self._increment_counter(trace.setdefault("source_counts", {}), source)
        if cache_result:
            self._increment_counter(
                trace.setdefault("cache_result_counts", {}),
                str(cache_result),
            )
        if full_list_read:
            trace["full_list_read_count"] = int(trace.get("full_list_read_count") or 0) + 1
        if elapsed_ms is not None:
            trace["storage_read_call_count"] = int(
                trace.get("storage_read_call_count") or 0
            ) + 1
            self._accumulate_ms(trace.setdefault("operation_elapsed_ms", {}), operation or "read", elapsed_ms)
        if metric_name and metric_ms is not None:
            self._accumulate_ms(trace.setdefault("phase_ms", {}), metric_name, metric_ms)
        if bot_count is not None:
            trace["last_bot_count"] = int(bot_count)

    def _record_lock_diagnostic(
        self,
        *,
        lock_name: str,
        wait_ms: float,
        acquired: bool,
    ) -> None:
        trace = self._active_read_diagnostics()
        if trace is None:
            return
        lock_wait_ms = trace.setdefault("lock_wait_ms", {})
        self._accumulate_ms(lock_wait_ms, lock_name, wait_ms)
        self._increment_counter(trace.setdefault("lock_acquire_counts", {}), lock_name)
        max_waits = trace.setdefault("lock_wait_max_ms", {})
        max_waits[lock_name] = round(
            max(float(max_waits.get(lock_name) or 0.0), max(float(wait_ms or 0.0), 0.0)),
            3,
        )
        if not acquired:
            self._increment_counter(trace.setdefault("lock_timeout_counts", {}), lock_name)

    def _finalize_read_diagnostics(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        completed_at = time.time()
        trace["completed_at"] = completed_at
        trace["total_ms"] = round(
            max(completed_at - float(trace.get("started_at") or completed_at), 0.0) * 1000.0,
            3,
        )
        top_operation = None
        top_count = 0
        for name, count in (trace.get("operation_counts") or {}).items():
            if int(count or 0) > top_count:
                top_operation = str(name)
                top_count = int(count or 0)
        trace["top_repeated_operation"] = (
            {
                "name": top_operation,
                "count": top_count,
            }
            if top_operation and top_count > 1
            else None
        )
        return trace

    @contextmanager
    def capture_read_diagnostics(self, label: str):
        trace = {
            "label": str(label or "").strip() or "bot_storage",
            "started_at": time.time(),
            "storage_read_call_count": 0,
            "full_list_read_count": 0,
            "cache_result_counts": {},
            "source_counts": {},
            "operation_counts": {},
            "operation_elapsed_ms": {},
            "phase_ms": {},
            "lock_wait_ms": {},
            "lock_wait_max_ms": {},
            "lock_acquire_counts": {},
            "lock_timeout_counts": {},
            "last_bot_count": 0,
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

    def _get_file_mtime_ns(self) -> Optional[int]:
        try:
            return self.file_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _update_cache(
        self,
        bots: List[Dict[str, Any]],
        *,
        mtime_ns: Optional[int] = None,
        assume_owned: bool = False,
    ) -> None:
        started_at = time.monotonic()
        # Perform expensive deepcopy OUTSIDE the lock so that _cache_lock
        # only protects an O(1) pointer swap instead of blocking other
        # threads for the full copy duration.
        if assume_owned:
            cloned = bots
            clone_ms = 0.0
        else:
            cloned = self._clone_bots(bots)
            clone_ms = (time.monotonic() - started_at) * 1000.0
        self._record_read_diagnostic(
            metric_name="cache_update_clone_ms",
            metric_ms=clone_ms,
        )
        resolved_mtime = (
            mtime_ns if mtime_ns is not None
            else self._get_file_mtime_ns()
        )
        t0 = time.monotonic()
        with self._timed_internal_lock(
            self._cache_lock,
            "cache_lock",
            fail_open=True,
        ) as acquired:
            if not acquired:
                return
            self._cached_bots = cloned
            self._cached_mtime_ns = resolved_mtime
            self._cached_projected_bots = {}
        lock_hold_ms = (time.monotonic() - t0) * 1000.0
        self._record_read_diagnostic(
            metric_name="cache_update_lock_ms",
            metric_ms=lock_hold_ms,
        )
        total_ms = (time.monotonic() - started_at) * 1000.0
        self._record_read_diagnostic(
            metric_name="cache_update_total_ms",
            metric_ms=total_ms,
        )
        if lock_hold_ms > 50.0:
            logger.debug(
                "_update_cache: lock held %.1fms (%d bots)",
                lock_hold_ms,
                len(bots),
            )

    @contextmanager
    def _timed_internal_lock(
        self,
        lock: Any,
        lock_name: str,
        *,
        timeout_sec: Optional[float] = None,
        fail_open: bool = False,
    ):
        wait_timeout = (
            self.internal_lock_timeout_sec
            if timeout_sec is None
            else max(float(timeout_sec or 0.0), 0.0)
        )
        wait_started = time.monotonic()
        acquired = lock.acquire(timeout=wait_timeout)
        wait_ms = (time.monotonic() - wait_started) * 1000.0
        self._record_lock_diagnostic(
            lock_name=lock_name,
            wait_ms=wait_ms,
            acquired=bool(acquired),
        )
        if not acquired:
            logger.warning(
                "Bot storage %s timed out after %.3fs",
                lock_name,
                wait_timeout,
            )
            if fail_open:
                yield False
                return
            raise TimeoutError(
                f"bot storage {lock_name} timed out after {wait_timeout:.3f}s"
            )
        try:
            yield True
        finally:
            lock.release()

    def _get_pending_runtime_updates_snapshot(
        self,
        *,
        fail_open: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        with self._timed_internal_lock(
            self._runtime_lock,
            "runtime_lock",
            fail_open=fail_open,
        ) as acquired:
            if not acquired:
                return {}
            return copy.deepcopy(self._pending_runtime_updates)

    @staticmethod
    def _apply_runtime_updates_to_bots(
        bots: List[Dict[str, Any]],
        updates_by_bot_id: Dict[str, Dict[str, Any]],
    ) -> bool:
        if not updates_by_bot_id:
            return False
        bots_by_id = {
            str(bot.get("id") or "").strip(): bot
            for bot in bots
            if str(bot.get("id") or "").strip()
        }
        applied = False
        for bot_id, fields in updates_by_bot_id.items():
            target = bots_by_id.get(str(bot_id or "").strip())
            if not target:
                continue
            for field, value in fields.items():
                target[field] = copy.deepcopy(value)
            applied = True
        return applied

    def _drain_runtime_updates(self, *, fail_open: bool = False) -> Dict[str, Dict[str, Any]]:
        with self._timed_internal_lock(
            self._runtime_lock,
            "runtime_lock",
            fail_open=fail_open,
        ) as acquired:
            if not acquired:
                return {}
            pending = copy.deepcopy(self._pending_runtime_updates)
            self._pending_runtime_updates.clear()
            timer = self._runtime_flush_timer
            self._runtime_flush_timer = None
        if timer:
            timer.cancel()
        return pending

    def _observe_runtime_persistence(
        self,
        *,
        path: Optional[str],
        bot_id: str,
        symbol: Optional[str],
        reason: Optional[str],
        persistence_class: Optional[str],
        outcome: str,
        changed_fields_count: int,
        elapsed_ms: float,
        lock_timeout: bool = False,
    ) -> None:
        if not path or not bot_id:
            return
        now = time.monotonic()
        normalized_reason = str(reason or "").strip().lower()
        normalized_class = str(persistence_class or "").strip().lower()
        observation_key = "|".join(
            (
                str(path),
                str(bot_id),
                normalized_reason,
                normalized_class,
            )
        )
        should_log = False
        snapshot: Optional[Dict[str, Any]] = None
        with self._runtime_persist_observation_lock:
            stats = self._runtime_persist_observations.get(observation_key)
            if stats is None:
                stats = {
                    "path": str(path),
                    "bot_id": str(bot_id),
                    "symbol": str(symbol or ""),
                    "reason": normalized_reason,
                    "persistence_class": normalized_class,
                    "first_seen_at": now,
                    "last_logged_at": 0.0,
                    "count": 0,
                    "queued_flush": 0,
                    "cache_only": 0,
                    "skipped_unchanged": 0,
                    "runtime_lock_timeout": 0,
                    "save_bot_fallback": 0,
                    "max_elapsed_ms": 0.0,
                    "last_changed_fields_count": 0,
                }
                self._runtime_persist_observations[observation_key] = stats
            if symbol:
                stats["symbol"] = str(symbol)
            stats["count"] += 1
            if outcome == "queued_flush":
                stats["queued_flush"] += 1
            elif outcome == "cache_only":
                stats["cache_only"] += 1
            elif outcome == "skipped_unchanged":
                stats["skipped_unchanged"] += 1
            elif outcome == "runtime_lock_timeout_cache_only":
                stats["runtime_lock_timeout"] += 1
                stats["cache_only"] += 1
            elif outcome == "save_bot_fallback":
                stats["save_bot_fallback"] += 1
            if lock_timeout and outcome != "runtime_lock_timeout_cache_only":
                stats["runtime_lock_timeout"] += 1
            stats["max_elapsed_ms"] = max(
                float(stats.get("max_elapsed_ms") or 0.0),
                float(elapsed_ms or 0.0),
            )
            stats["last_changed_fields_count"] = int(changed_fields_count or 0)
            should_log = (
                int(stats.get("count") or 0) == 1
                or (now - float(stats.get("last_logged_at") or 0.0))
                >= RUNTIME_PERSIST_OBSERVATION_LOG_INTERVAL_SEC
            )
            if should_log:
                stats["last_logged_at"] = now
                snapshot = dict(stats)
        if not should_log or snapshot is None:
            return
        window_sec = max(now - float(snapshot.get("first_seen_at") or now), 0.001)
        logger.debug(
            "BOT_RUNTIME_PERSIST path=%s bot_id=%s symbol=%s reason=%s class=%s count=%d rate_per_min=%.2f "
            "queued_flush=%d cache_only=%d skipped_unchanged=%d runtime_lock_timeout=%d save_bot_fallback=%d "
            "last_changed_fields=%d max_elapsed_ms=%.2f",
            snapshot.get("path"),
            snapshot.get("bot_id"),
            snapshot.get("symbol") or "?",
            snapshot.get("reason") or "-",
            snapshot.get("persistence_class") or "runtime_path",
            int(snapshot.get("count") or 0),
            float(snapshot.get("count") or 0) * 60.0 / window_sec,
            int(snapshot.get("queued_flush") or 0),
            int(snapshot.get("cache_only") or 0),
            int(snapshot.get("skipped_unchanged") or 0),
            int(snapshot.get("runtime_lock_timeout") or 0),
            int(snapshot.get("save_bot_fallback") or 0),
            int(snapshot.get("last_changed_fields_count") or 0),
            float(snapshot.get("max_elapsed_ms") or 0.0),
        )

    def _schedule_runtime_flush_locked(self, delay_sec: float) -> None:
        if self._runtime_flush_timer:
            self._runtime_flush_timer.cancel()
        timer = threading.Timer(delay_sec, self.flush_runtime_updates)
        timer.daemon = True
        self._runtime_flush_timer = timer
        timer.start()

    def _observe_read_access(
        self,
        *,
        path: str,
        source: Optional[str],
        bot_id: Optional[str] = None,
        cache_result: Optional[str] = None,
        full_list_read: bool = False,
        elapsed_ms: float,
    ) -> None:
        if not source:
            return
        now = time.monotonic()
        snapshot = None
        key = "|".join(
            (
                str(path or "").strip() or "-",
                str(source or "").strip() or "-",
                str(cache_result or "").strip() or "-",
            )
        )
        with self._read_observation_lock:
            stats = self._read_observations.setdefault(
                key,
                {
                    "path": str(path or "").strip() or "-",
                    "source": str(source or "").strip() or "-",
                    "cache_result": str(cache_result or "").strip() or "-",
                    "bot_id": str(bot_id or "").strip() or None,
                    "count": 0,
                    "cache_hit": 0,
                    "cache_refill": 0,
                    "direct_read": 0,
                    "full_list_read": 0,
                    "max_elapsed_ms": 0.0,
                    "first_seen_at": now,
                    "last_logged_at": 0.0,
                },
            )
            stats["count"] += 1
            if bot_id:
                stats["bot_id"] = str(bot_id or "").strip() or None
            if cache_result == "hit":
                stats["cache_hit"] += 1
            elif cache_result == "refill":
                stats["cache_refill"] += 1
            else:
                stats["direct_read"] += 1
            if full_list_read:
                stats["full_list_read"] += 1
            stats["max_elapsed_ms"] = max(
                float(stats.get("max_elapsed_ms") or 0.0),
                float(elapsed_ms or 0.0),
            )
            should_log = (
                (now - float(stats.get("last_logged_at") or 0.0))
                >= READ_OBSERVATION_LOG_INTERVAL_SEC
            )
            if should_log:
                stats["last_logged_at"] = now
                snapshot = dict(stats)
        if not snapshot:
            return
        window_sec = max(now - float(snapshot.get("first_seen_at") or now), 0.001)
        logger.debug(
            "BOT_STORAGE_READ path=%s source=%s bot_id=%s count=%d rate_per_min=%.2f "
            "cache_hit=%d cache_refill=%d direct_read=%d full_list_read=%d max_elapsed_ms=%.2f",
            snapshot.get("path"),
            snapshot.get("source"),
            snapshot.get("bot_id") or "-",
            int(snapshot.get("count") or 0),
            float(snapshot.get("count") or 0) * 60.0 / window_sec,
            int(snapshot.get("cache_hit") or 0),
            int(snapshot.get("cache_refill") or 0),
            int(snapshot.get("direct_read") or 0),
            int(snapshot.get("full_list_read") or 0),
            float(snapshot.get("max_elapsed_ms") or 0.0),
        )

    def _read_all_cached(
        self,
        *,
        source: Optional[str] = None,
        bot_id: Optional[str] = None,
        projector: Optional[BotProjector] = None,
        read_only_projected_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        started_at = time.monotonic()
        mtime_ns = self._get_file_mtime_ns()
        pending_updates = self._get_pending_runtime_updates_snapshot(fail_open=True)
        cache_check_started = time.monotonic()
        cached_bots: Optional[List[Dict[str, Any]]] = None
        cached_projected_bots: Optional[List[Dict[str, Any]]] = None
        with self._timed_internal_lock(
            self._cache_lock,
            "cache_lock",
            fail_open=True,
        ) as acquired:
            if acquired and self._cached_bots is not None and self._cached_mtime_ns == mtime_ns:
                cached_bots = self._cached_bots
                if projector is not None:
                    cached_projection_entry = self._cached_projected_bots.get(
                        self._projector_cache_key(projector)
                    )
                    if (
                        isinstance(cached_projection_entry, dict)
                        and cached_projection_entry.get("mtime_ns") == mtime_ns
                        and cached_projection_entry.get("source_bots") is cached_bots
                    ):
                        cached_projected_bots = cached_projection_entry.get("bots")
        if cached_bots is not None:
            cache_lookup_ms = (time.monotonic() - cache_check_started) * 1000.0
            self._record_read_diagnostic(
                metric_name="projection_cache_lookup_ms",
                metric_ms=0.0 if projector is None else cache_lookup_ms,
            )
            if cached_projected_bots is not None:
                projection_reuse_started = time.monotonic()
                bots = (
                    cached_projected_bots
                    if read_only_projected_cache
                    else self._clone_bots(cached_projected_bots)
                )
                projection_reuse_ms = (time.monotonic() - projection_reuse_started) * 1000.0
                self._record_read_diagnostic(
                    operation="_read_all_cached:projection_cache_hit",
                    source=source,
                    cache_result="hit",
                    full_list_read=False,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                    metric_name=(
                        "projection_cache_reuse_ms"
                        if read_only_projected_cache
                        else "projection_cache_clone_ms"
                    ),
                    metric_ms=projection_reuse_ms,
                    bot_count=len(bots),
                )
                self._observe_read_access(
                    path="_read_all_cached",
                    source=source,
                    bot_id=bot_id,
                    cache_result="hit",
                    full_list_read=False,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                )
                return bots
            materialize_started = time.monotonic()
            bots = self._materialize_bots(cached_bots, projector=projector)
            materialize_ms = (time.monotonic() - materialize_started) * 1000.0
            if projector is not None and read_only_projected_cache:
                projection_cache_store_started = time.monotonic()
                with self._timed_internal_lock(
                    self._cache_lock,
                    "cache_lock",
                    fail_open=True,
                ) as acquired:
                    if acquired and self._cached_bots is cached_bots and self._cached_mtime_ns == mtime_ns:
                        self._cached_projected_bots[self._projector_cache_key(projector)] = {
                            "mtime_ns": mtime_ns,
                            "source_bots": cached_bots,
                            "bots": bots,
                        }
                self._record_read_diagnostic(
                    metric_name="projection_cache_store_ms",
                    metric_ms=(time.monotonic() - projection_cache_store_started) * 1000.0,
                )
            self._record_read_diagnostic(
                operation="_read_all_cached:hit",
                source=source,
                cache_result="hit",
                full_list_read=False,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                metric_name="cache_lookup_ms",
                metric_ms=cache_lookup_ms,
                bot_count=len(bots),
            )
            self._record_read_diagnostic(
                metric_name="projection_ms" if projector is not None else "clone_ms",
                metric_ms=materialize_ms,
            )
            self._observe_read_access(
                path="_read_all_cached",
                source=source,
                bot_id=bot_id,
                cache_result="hit",
                full_list_read=False,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            )
            return bots
        self._record_read_diagnostic(
            metric_name="cache_lookup_ms",
            metric_ms=(time.monotonic() - cache_check_started) * 1000.0,
        )
        disk_read_started = time.monotonic()
        bots = self._read_all_locked()
        disk_read_ms = (time.monotonic() - disk_read_started) * 1000.0
        self._record_read_diagnostic(
            metric_name="disk_read_ms",
            metric_ms=disk_read_ms,
        )
        runtime_merge_started = time.monotonic()
        self._apply_runtime_updates_to_bots(bots, pending_updates)
        runtime_merge_ms = (time.monotonic() - runtime_merge_started) * 1000.0
        self._record_read_diagnostic(
            metric_name="runtime_merge_ms",
            metric_ms=runtime_merge_ms,
        )
        cache_update_started = time.monotonic()
        self._update_cache(bots, mtime_ns=mtime_ns, assume_owned=True)
        self._record_read_diagnostic(
            metric_name="cache_update_call_ms",
            metric_ms=(time.monotonic() - cache_update_started) * 1000.0,
        )
        materialize_started = time.monotonic()
        cloned = self._materialize_bots(bots, projector=projector)
        materialize_ms = (time.monotonic() - materialize_started) * 1000.0
        if projector is not None and read_only_projected_cache:
            projection_cache_store_started = time.monotonic()
            with self._timed_internal_lock(
                self._cache_lock,
                "cache_lock",
                fail_open=True,
            ) as acquired:
                if acquired and self._cached_bots is bots and self._cached_mtime_ns == mtime_ns:
                    self._cached_projected_bots[self._projector_cache_key(projector)] = {
                        "mtime_ns": mtime_ns,
                        "source_bots": bots,
                        "bots": cloned,
                    }
            self._record_read_diagnostic(
                metric_name="projection_cache_store_ms",
                metric_ms=(time.monotonic() - projection_cache_store_started) * 1000.0,
            )
        self._record_read_diagnostic(
            operation="_read_all_cached:refill",
            source=source,
            cache_result="refill",
            full_list_read=True,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            metric_name="projection_ms" if projector is not None else "clone_ms",
            metric_ms=materialize_ms,
            bot_count=len(cloned),
        )
        self._observe_read_access(
            path="_read_all_cached",
            source=source,
            bot_id=bot_id,
            cache_result="refill",
            full_list_read=True,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
        )
        return cloned

    @contextmanager
    def _file_lock(self, exclusive: bool = False):
        """
        Context manager for file locking.

        Args:
            exclusive: If True, acquire exclusive lock (for writes).
                      If False, acquire shared lock (for reads).

        Yields:
            Lock file descriptor
        """
        lock_name = "file_lock_exclusive" if exclusive else "file_lock_shared"
        wait_started = time.monotonic()
        with file_lock(self.lock_path, exclusive=exclusive) as lock_fd:
            self._record_lock_diagnostic(
                lock_name=lock_name,
                wait_ms=(time.monotonic() - wait_started) * 1000.0,
                acquired=True,
            )
            yield lock_fd

    def _read_all_unlocked(self) -> List[Dict[str, Any]]:
        """
        Read all bots from the JSON file (without locking).
        Internal use only - caller must hold lock.

        Returns:
            List of bot dictionaries, or empty list on error
        """
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                read_started = time.monotonic()
                raw_data = f.read()
                self._record_read_diagnostic(
                    metric_name="file_read_ms",
                    metric_ms=(time.monotonic() - read_started) * 1000.0,
                )
                parse_started = time.monotonic()
                data = json.loads(raw_data)
                self._record_read_diagnostic(
                    metric_name="json_parse_ms",
                    metric_ms=(time.monotonic() - parse_started) * 1000.0,
                )
                if isinstance(data, list):
                    normalize_started = time.monotonic()
                    for bot in data:
                        self._normalize_mode_range_state(bot)
                    self._record_read_diagnostic(
                        metric_name="normalize_ms",
                        metric_ms=(time.monotonic() - normalize_started) * 1000.0,
                        bot_count=len(data),
                    )
                    return data
                return []
        except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
            logger.warning(f"Error reading bots file: {e}")
            return []

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_auto_pilot_placeholder_bot(bot: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(bot, dict):
            return False
        if not bot.get("auto_pilot"):
            return False
        return str(bot.get("symbol") or "").strip().lower() == "auto-pilot"

    @staticmethod
    def _normalize_mode_range_state(bot: Optional[Dict[str, Any]]) -> None:
        if not isinstance(bot, dict):
            return
        bot.pop("lower_bound", None)
        bot.pop("upper_bound", None)
        mode = str(bot.get("mode") or "").strip().lower()
        if mode == "neutral_classic_bybit":
            grid_lower = bot.get("grid_lower_price")
            grid_upper = bot.get("grid_upper_price")
            if grid_lower is None:
                grid_lower = bot.get("lower_price")
            if grid_upper is None:
                grid_upper = bot.get("upper_price")
            bot["grid_lower_price"] = grid_lower
            bot["grid_upper_price"] = grid_upper
            bot["lower_price"] = grid_lower
            bot["upper_price"] = grid_upper
        else:
            bot.pop("grid_lower_price", None)
            bot.pop("grid_upper_price", None)
            bot.pop("grid_levels_total", None)

    @staticmethod
    def _normalize_control_runtime_state(bot: Optional[Dict[str, Any]]) -> None:
        if not isinstance(bot, dict):
            return
        status = str(bot.get("status") or "").strip().lower()
        if status != "stop_cleanup_pending":
            for key in STOP_CLEANUP_RUNTIME_FIELDS:
                bot.pop(key, None)
        if status not in PAUSE_RUNTIME_STATUSES:
            for key in PAUSE_RUNTIME_FIELDS:
                bot.pop(key, None)

    @staticmethod
    def _build_persisted_bot_view(bot: Dict[str, Any]) -> Dict[str, Any]:
        persisted = copy.deepcopy(bot or {})
        if runtime_mode_is_non_persistent(persisted):
            persisted["mode"] = configured_mode(persisted)
            persisted["range_mode"] = configured_range_mode(persisted)
        return persisted

    def _write_all_unlocked(self, bots: List[Dict[str, Any]]) -> None:
        """
        Write all bots to the JSON file (without locking).
        Internal use only - caller must hold lock.

        Uses atomic write (write to temp file, then rename) to prevent corruption.

        Args:
            bots: List of bot dictionaries to write

        Raises:
            RuntimeError: If write operation fails
        """
        try:
            for bot in bots:
                self._normalize_mode_range_state(bot)
            # Write to temporary file first (atomic write pattern)
            dir_path = self.file_path.parent
            fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(bots, f, indent=2, ensure_ascii=False)
                # Atomic rename (on same filesystem)
                # On Windows, this can fail if the file is being read by another process
                import time

                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        os.replace(temp_path, self.file_path)
                        break
                    except OSError as e:
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(0.1)
            except Exception:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
        except (IOError, OSError) as e:
            raise RuntimeError(f"Failed to write bots to {self.file_path}: {str(e)}")

    def _read_all_locked(self) -> List[Dict[str, Any]]:
        """
        Read all bots with shared lock.

        Returns:
            List of bot dictionaries
        """
        with self._file_lock(exclusive=False):
            return self._read_all_unlocked()

    def _write_all_locked(self, bots: List[Dict[str, Any]]) -> None:
        """
        Write all bots with exclusive lock.

        Args:
            bots: List of bot dictionaries to write
        """
        with self._file_lock(exclusive=True):
            self._write_all_unlocked(bots)
        self._update_cache(bots)

    def _read_all(self) -> List[Dict[str, Any]]:
        """
        Read all bots from the JSON file (with locking).

        Returns:
            List of bot dictionaries, or empty list on error
        """
        return self._read_all_locked()

    def _write_all(self, bots: List[Dict[str, Any]]) -> None:
        """
        Write all bots to the JSON file (with locking).

        Args:
            bots: List of bot dictionaries to write
        """
        self._write_all_locked(bots)

    def list_bots(
        self,
        *,
        source: Optional[str] = None,
        projector: Optional[BotProjector] = None,
        read_only_projected_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all bots.

        Returns:
            List of all bot dictionaries
        """
        return self._read_all_cached(
            source=source,
            projector=projector,
            read_only_projected_cache=read_only_projected_cache,
        )

    def get_bot(self, bot_id: str, *, source: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a specific bot by ID.

        Args:
            bot_id: The unique ID of the bot

        Returns:
            Bot dictionary if found, None otherwise
        """
        bots = self._read_all_cached(source=source, bot_id=bot_id)
        for bot in bots:
            if bot.get("id") == bot_id:
                return bot
        return None

    def get_storage_mtime_ns(self) -> Optional[int]:
        """Return the current bots.json mtime for same-cycle freshness checks."""
        return self._get_file_mtime_ns()

    def get_bot_fresh_with_meta(
        self,
        bot_id: str,
        *,
        source: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        """
        Get the latest persisted bot state together with the file mtime used for
        that read. The mtime lets callers safely reuse the same-cycle snapshot
        when the storage file has not changed.
        """
        started_at = time.monotonic()
        pending_updates = self._get_pending_runtime_updates_snapshot(fail_open=True)
        disk_read_started = time.monotonic()
        bots = self._read_all_locked()
        self._record_read_diagnostic(
            metric_name="disk_read_ms",
            metric_ms=(time.monotonic() - disk_read_started) * 1000.0,
        )
        runtime_merge_started = time.monotonic()
        self._apply_runtime_updates_to_bots(bots, pending_updates)
        self._record_read_diagnostic(
            metric_name="runtime_merge_ms",
            metric_ms=(time.monotonic() - runtime_merge_started) * 1000.0,
        )
        # Update the cache so subsequent get_bot() calls benefit
        mtime_ns = self._get_file_mtime_ns()
        self._update_cache(bots, mtime_ns=mtime_ns)
        self._record_read_diagnostic(
            operation="get_bot_fresh:fresh",
            source=source,
            cache_result="fresh",
            full_list_read=True,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            bot_count=len(bots),
        )
        self._observe_read_access(
            path="get_bot_fresh",
            source=source,
            bot_id=bot_id,
            cache_result="fresh",
            full_list_read=True,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
        )
        for bot in bots:
            if bot.get("id") == bot_id:
                return copy.deepcopy(bot), mtime_ns
        return None, mtime_ns

    def get_bot_fresh(self, bot_id: str, *, source: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a specific bot by ID, always reading from disk.

        Bypasses the in-memory cache to guarantee the latest persisted state.
        Use this when stale data would be dangerous (e.g. runner cycle entry).

        Args:
            bot_id: The unique ID of the bot

        Returns:
            Bot dictionary if found, None otherwise
        """
        bot, _mtime_ns = self.get_bot_fresh_with_meta(bot_id, source=source)
        return bot

    def save_bot(
        self,
        bot: Dict[str, Any],
        allow_pnl_override: bool = False,
    ) -> Dict[str, Any]:
        """
        Save a bot (create new or update existing).
        Uses exclusive lock for atomic read-modify-write.

        Args:
            bot: Bot dictionary to save
            allow_pnl_override: Permit authoritative PnL writers to replace
                protected aggregate PnL fields.

        Returns:
            The saved bot dictionary with generated/updated fields
        """
        runtime_non_persistent = runtime_mode_is_non_persistent(bot)
        return_view = copy.deepcopy(bot or {})
        persisted_view = self._build_persisted_bot_view(bot)
        pending_runtime_updates = self._drain_runtime_updates(fail_open=True)
        with self._file_lock(exclusive=True):
            bots = self._read_all_unlocked()
            self._apply_runtime_updates_to_bots(bots, pending_runtime_updates)
            now_iso = datetime.now(timezone.utc).isoformat()
            self._normalize_mode_range_state(persisted_view)

            # Generate ID if missing or empty
            bot_id = persisted_view.get("id")
            if not bot_id:
                bot_id = str(uuid.uuid4())
                persisted_view["id"] = bot_id
                return_view["id"] = bot_id

            # Find existing bot index
            existing_index = None
            for i, existing_bot in enumerate(bots):
                if existing_bot.get("id") == bot_id:
                    existing_index = i
                    break

            if existing_index is not None:
                # Update existing bot - merge fields
                existing_bot = bots[existing_index]
                if existing_bot.get("settings_version") is None:
                    existing_bot["settings_version"] = 1
                if not existing_bot.get("settings_updated_at"):
                    existing_bot["settings_updated_at"] = (
                        existing_bot.get("updated_at") or now_iso
                    )
                existing_control_version = self._safe_int(
                    existing_bot.get("control_version"), 0
                )
                incoming_control_version = self._safe_int(
                    bot.get("control_version"), 0
                )
                existing_settings_version = self._safe_int(
                    existing_bot.get("settings_version"), 0
                )
                incoming_settings_version = self._safe_int(
                    bot.get("settings_version"), 0
                )
                preserve_control_state = (
                    incoming_control_version < existing_control_version
                    or (
                        incoming_control_version == existing_control_version
                        and (bot.get("status") == "running")
                        and (
                            existing_bot.get("status")
                            in (
                                "stopped",
                                "paused",
                                "recovering",
                                "flash_crash_paused",
                                "risk_stopped",
                                "error",
                                "stop_cleanup_pending",
                            )
                        )
                    )
                )
                preserved_control = {
                    key: copy.deepcopy(existing_bot.get(key))
                    for key in CONTROL_PROTECTED_FIELDS
                }
                if self._is_auto_pilot_placeholder_bot(existing_bot):
                    preserved_control.update(
                        {
                            key: copy.deepcopy(existing_bot.get(key))
                            for key in AUTO_PILOT_PLACEHOLDER_PROTECTED_FIELDS
                        }
                    )
                preserve_settings_state = (
                    incoming_settings_version < existing_settings_version
                )
                preserved_settings = {
                    key: existing_bot.get(key) for key in SETTINGS_PROTECTED_FIELDS
                }
                preserve_pnl_state = not allow_pnl_override
                preserved_pnl = {
                    key: copy.deepcopy(existing_bot.get(key))
                    for key in PNL_PROTECTED_FIELDS
                }

                for key, value in persisted_view.items():
                    existing_bot[key] = value

                if preserve_control_state:
                    for key, value in preserved_control.items():
                        existing_bot[key] = value
                    logger.warning(
                        "Ignored stale control-state save for bot %s: incoming status=%s version=%s, current status=%s version=%s",
                        bot_id,
                        bot.get("status"),
                        incoming_control_version,
                        preserved_control.get("status"),
                        existing_control_version,
                    )

                if preserve_settings_state:
                    for key, value in preserved_settings.items():
                        existing_bot[key] = value
                    logger.warning(
                        "Ignored stale settings save for bot %s: incoming settings_version=%s, current settings_version=%s",
                        bot_id,
                        incoming_settings_version,
                        existing_settings_version,
                    )

                if preserve_pnl_state:
                    for key, value in preserved_pnl.items():
                        existing_bot[key] = value

                self._normalize_control_runtime_state(existing_bot)
                existing_bot["updated_at"] = now_iso
                bot = existing_bot
            else:
                # New bot - set timestamps
                if "control_version" not in persisted_view:
                    persisted_view["control_version"] = 0
                if "settings_version" not in persisted_view:
                    persisted_view["settings_version"] = 0
                self._normalize_control_runtime_state(persisted_view)
                persisted_view["created_at"] = now_iso
                persisted_view["updated_at"] = now_iso
                bots.append(persisted_view)
                bot = persisted_view

            self._write_all_unlocked(bots)
            self._update_cache(bots)
            if runtime_non_persistent:
                return_view["updated_at"] = now_iso
                if existing_index is None:
                    return_view["created_at"] = now_iso
                else:
                    return_view["created_at"] = bot.get("created_at")
                return return_view
            return bot

    def save_runtime_bot(
        self,
        bot: Dict[str, Any],
        flush_delay_sec: Optional[float] = None,
        allow_pnl_override: bool = False,
        *,
        persist: bool = True,
        path: Optional[str] = None,
        reason: Optional[str] = None,
        persistence_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save runtime-only bot fields with a short debounce.

        This updates the in-memory cache immediately and batches the disk write.
        Any control/settings/config field falls back to save_bot() immediately.
        """
        started_at = time.monotonic()
        bot_id = str(bot.get("id") or "").strip()
        symbol = str(bot.get("symbol") or "").strip().upper()

        def observe(outcome: str, *, changed_fields_count: int, lock_timeout: bool = False) -> None:
            self._observe_runtime_persistence(
                path=path,
                bot_id=bot_id,
                symbol=symbol,
                reason=reason,
                persistence_class=persistence_class,
                outcome=outcome,
                changed_fields_count=changed_fields_count,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                lock_timeout=lock_timeout,
            )

        if not bot_id:
            saved = self.save_bot(bot)
            observe("save_bot_fallback", changed_fields_count=len(list(bot or {})))
            return saved

        pre_read_mtime = self._get_file_mtime_ns()
        cached_bots = self._read_all_cached(
            source=(
                f"save_runtime_bot:{str(path or '').strip() or 'generic'}"
            ),
            bot_id=bot_id,
        )
        existing_index = None
        existing_bot = None
        for index, cached_bot in enumerate(cached_bots):
            if str(cached_bot.get("id") or "").strip() == bot_id:
                existing_index = index
                existing_bot = cached_bot
                break
        if not existing_bot:
            saved = self.save_bot(bot, allow_pnl_override=allow_pnl_override)
            observe("save_bot_fallback", changed_fields_count=len(list(bot or {})))
            return saved

        changed_fields: Dict[str, Any] = {}
        for field, value in bot.items():
            if field == "updated_at":
                continue
            if existing_bot.get(field) != value:
                changed_fields[field] = copy.deepcopy(value)

        if not allow_pnl_override:
            for field in PNL_PROTECTED_FIELDS:
                changed_fields.pop(field, None)

        if not changed_fields:
            observe("skipped_unchanged", changed_fields_count=0)
            return existing_bot

        protected_fields = set(SETTINGS_PROTECTED_FIELDS) | set(CONTROL_PROTECTED_FIELDS)
        if any(field in protected_fields for field in changed_fields):
            saved = self.save_bot(bot, allow_pnl_override=allow_pnl_override)
            observe("save_bot_fallback", changed_fields_count=len(changed_fields))
            return saved

        now_iso = datetime.now(timezone.utc).isoformat()
        updated_bot = self._clone_bots([existing_bot])[0]
        for field, value in bot.items():
            if not allow_pnl_override and field in PNL_PROTECTED_FIELDS:
                continue
            updated_bot[field] = copy.deepcopy(value)
        updated_bot["updated_at"] = now_iso
        changed_fields["updated_at"] = now_iso

        cached_bots[existing_index] = copy.deepcopy(updated_bot)
        self._update_cache(cached_bots, mtime_ns=pre_read_mtime)

        if not persist:
            observe("cache_only", changed_fields_count=len(changed_fields))
            return updated_bot

        with self._timed_internal_lock(
            self._runtime_lock,
            "runtime_lock",
            fail_open=True,
        ) as acquired:
            if not acquired:
                # Cache already updated above. Return without queuing to
                # disk — avoids amplifying contention by falling back to the
                # heavier save_bot() path.  Next cycle recomputes runtime
                # fields and will succeed under normal lock conditions.
                observe(
                    "runtime_lock_timeout_cache_only",
                    changed_fields_count=len(changed_fields),
                    lock_timeout=True,
                )
                return updated_bot
            pending = self._pending_runtime_updates.setdefault(bot_id, {})
            pending.update(copy.deepcopy(changed_fields))
            delay = (
                self.runtime_flush_delay_sec
                if flush_delay_sec is None
                else max(float(flush_delay_sec or 0), 0.1)
            )
            self._schedule_runtime_flush_locked(delay)

        observe("queued_flush", changed_fields_count=len(changed_fields))
        return updated_bot

    def flush_runtime_updates(self) -> int:
        """Flush any debounced runtime updates to disk."""
        pending_runtime_updates = self._drain_runtime_updates(fail_open=True)
        if not pending_runtime_updates:
            return 0

        with self._file_lock(exclusive=True):
            bots = self._read_all_unlocked()
            applied = self._apply_runtime_updates_to_bots(bots, pending_runtime_updates)
            if not applied:
                return 0
            self._write_all_unlocked(bots)
            self._update_cache(bots)
        return len(pending_runtime_updates)

    def delete_bot(self, bot_id: str) -> bool:
        """
        Delete a bot by ID.
        Uses exclusive lock for atomic read-modify-write.

        Args:
            bot_id: The unique ID of the bot to delete

        Returns:
            True if bot was deleted, False if not found
        """
        pending_runtime_updates = self._drain_runtime_updates(fail_open=True)
        with self._file_lock(exclusive=True):
            bots = self._read_all_unlocked()
            self._apply_runtime_updates_to_bots(bots, pending_runtime_updates)
            original_count = len(bots)

            bots = [bot for bot in bots if bot.get("id") != bot_id]

            if len(bots) < original_count:
                self._write_all_unlocked(bots)
                self._update_cache(bots)
                return True

            return False

    def update_bot_field(self, bot_id: str, field: str, value: Any) -> bool:
        """
        Update a single field on a bot atomically.

        Args:
            bot_id: The unique ID of the bot
            field: Field name to update
            value: New value for the field

        Returns:
            True if bot was updated, False if not found
        """
        pending_runtime_updates = self._drain_runtime_updates(fail_open=True)
        with self._file_lock(exclusive=True):
            bots = self._read_all_unlocked()
            self._apply_runtime_updates_to_bots(bots, pending_runtime_updates)

            for bot in bots:
                if bot.get("id") == bot_id:
                    bot[field] = value
                    bot["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_unlocked(bots)
                    self._update_cache(bots)
                    return True

            return False

    def update_bot_fields(self, bot_id: str, fields: Dict[str, Any]) -> bool:
        """
        Update multiple fields on a bot atomically.

        Args:
            bot_id: The unique ID of the bot
            fields: Dictionary of field names and values to update

        Returns:
            True if bot was updated, False if not found
        """
        pending_runtime_updates = self._drain_runtime_updates(fail_open=True)
        with self._file_lock(exclusive=True):
            bots = self._read_all_unlocked()
            self._apply_runtime_updates_to_bots(bots, pending_runtime_updates)

            for bot in bots:
                if bot.get("id") == bot_id:
                    for field, value in fields.items():
                        bot[field] = value
                    bot["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_unlocked(bots)
                    self._update_cache(bots)
                    return True

            return False
