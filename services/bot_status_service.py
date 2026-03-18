"""
Bybit Control Center - Bot Status Service

Provides enriched runtime view of all bots for the dashboard.
"""

import logging
import time
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

import config.strategy_config as strategy_cfg
from services.bot_storage_service import BotStorageService
from config.strategy_config import (
    get_upnl_stoploss_defaults,
    GRID_TICK_SECONDS,
    RISK_TICK_SECONDS,
    normalize_auto_pilot_universe_mode,
    ENTRY_READINESS_LIVE_PREVIEW_ENABLED,
    ENTRY_READINESS_STOPPED_PREVIEW_ENABLED,
    ENTRY_READINESS_STOPPED_PREVIEW_MAX_BOTS,
    ENTRY_READINESS_STOPPED_PREVIEW_TTL_SEC,
    ENTRY_READINESS_STOPPED_PREVIEW_STALE_SEC,
)
from services.entry_readiness_service import EntryReadinessService
from services.position_service import PositionService
from services.pnl_service import PnlService
from services.price_action_signal_service import PriceActionSignalService
from services.symbol_pnl_service import SymbolPnlService
from services.watchdog_diagnostics_service import WatchdogDiagnosticsService
from services.performance_baseline_service import PerformanceBaselineService
from services.mode_semantics import (
    MODE_POLICY_RUNTIME_AUTO_SWITCH,
    configured_mode,
    configured_range_mode,
    normalize_bot_mode,
    normalize_mode_policy,
    normalize_range_mode,
)
from services.bot_runtime_contracts import extract_light_bot

MIN_RUNTIME_FOR_RATE_HOURS = 1.0 / 60.0
ACTIVE_POSITION_OWNER_STATUSES = {
    "running",
    "paused",
    "recovering",
    "flash_crash_paused",
}
# Broader set for open-order queries: includes error/risk_stopped/stop_cleanup_pending
# because these bots may still have open orders on exchange that need to be tracked.
LIVE_ORDER_OWNER_STATUSES = ACTIVE_POSITION_OWNER_STATUSES | {
    "error",
    "risk_stopped",
    "stop_cleanup_pending",
}
CAPITAL_STARVED_RUNTIME_REASONS = {
    "insufficient_margin",
    "opening_margin_reserve",
    "qty_below_min",
    "notional_below_min",
}
MODE_READINESS_MATRIX_ORDER = (
    "neutral",
    "neutral_classic_bybit",
    "long",
    "short",
    "scalp_pnl",
)
READINESS_STABILITY_STAGE_RANK = {
    "blocked": -2,
    "late": -1,
    "watch": 0,
    "wait": 0,
    "caution": 0,
    "armed": 1,
    "trigger_ready": 2,
}
READINESS_STABILITY_HARD_REASONS = {
    "preview_disabled",
    "preview_limited",
    "stale_snapshot",
    "stop_cleanup_pending",
    "breakout_extended",
    "late_continuation",
}
READINESS_STABILITY_LIVE_POLICY = {
    "promotion_confirmations": 2,
    "demotion_confirmations": 2,
    "hold_sec": 2.5,
}
READINESS_STABILITY_STOPPED_PREVIEW_POLICY = {
    "promotion_confirmations": 2,
    "demotion_confirmations": 2,
    "hold_sec": 8.0,
}
READINESS_STABILITY_INACTIVE_POLICY = {
    "promotion_confirmations": 2,
    "demotion_confirmations": 2,
    "hold_sec": 4.0,
}
READINESS_STABILITY_CACHE_TTL_SEC = 900.0
RUNTIME_LIGHT_DIAGNOSTIC_LOG_THROTTLE_SEC = 60.0
RUNTIME_LIGHT_DIAGNOSTIC_SLOW_CALL_MS = 1000.0


class BotStatusService:
    """
    Service for retrieving enriched bot runtime status.
    """

    def __init__(
        self,
        bot_storage: BotStorageService,
        position_service: PositionService,
        pnl_service: PnlService,
        symbol_pnl_service: Optional[SymbolPnlService] = None,
        neutral_scanner: Optional[Any] = None,
        indicator_service: Optional[Any] = None,
        scanner_cache_ttl_seconds: int = 20,
        performance_baseline_service: Optional[PerformanceBaselineService] = None,
    ):
        """
        Initialize the bot status service.

        Args:
            bot_storage: BotStorageService for reading bot data
            position_service: PositionService for current positions
            pnl_service: PnlService for PnL data
            symbol_pnl_service: Optional SymbolPnlService for symbol cumulative PnL
            neutral_scanner: Optional NeutralScannerService for live mode recommendations
            indicator_service: Optional IndicatorService for price-action summaries
            scanner_cache_ttl_seconds: Cache lifetime for scanner recommendations
        """
        self.bot_storage = bot_storage
        self.position_service = position_service
        self.pnl_service = pnl_service
        self.symbol_pnl_service = symbol_pnl_service or SymbolPnlService()
        self.performance_baseline_service = performance_baseline_service
        self.neutral_scanner = neutral_scanner
        self.price_action_service = (
            PriceActionSignalService(indicator_service) if indicator_service else None
        )
        client = getattr(position_service, "client", None)
        market_data_provider = getattr(client, "stream_service", None) if client else None
        self.entry_readiness_service = (
            EntryReadinessService(
                indicator_service,
                cache_ttl_seconds=max(int(GRID_TICK_SECONDS or 0), 3),
                live_preview_enabled=ENTRY_READINESS_LIVE_PREVIEW_ENABLED,
                stopped_preview_enabled=ENTRY_READINESS_STOPPED_PREVIEW_ENABLED,
                market_data_provider=market_data_provider,
            )
            if indicator_service
            else None
        )
        self.stopped_preview_enabled = bool(ENTRY_READINESS_STOPPED_PREVIEW_ENABLED)
        self.stopped_preview_max_bots = max(
            int(ENTRY_READINESS_STOPPED_PREVIEW_MAX_BOTS or 0),
            0,
        )
        self.stopped_preview_ttl_sec = max(
            int(ENTRY_READINESS_STOPPED_PREVIEW_TTL_SEC or 0),
            5,
        )
        self.stopped_preview_stale_sec = max(
            int(ENTRY_READINESS_STOPPED_PREVIEW_STALE_SEC or 0),
            self.stopped_preview_ttl_sec,
        )
        self.scanner_cache_ttl_seconds = max(int(scanner_cache_ttl_seconds or 0), 5)
        self._scanner_cache: Dict[str, Dict[str, Any]] = {}
        self._live_open_orders_cache: Dict[str, Dict[str, Any]] = {}
        self._live_open_orders_all_cache: Dict[str, Any] = {}
        self._live_open_orders_cache_ttl_seconds = 5
        self._last_live_open_orders_diagnostics: Dict[str, Any] = {}
        self._runtime_positions_cache: Dict[str, Any] = {}
        self._stopped_preview_cache: Dict[str, Dict[str, Any]] = {}
        self._readiness_stability_cache: Dict[str, Dict[str, Any]] = {}
        self._last_runtime_cache_status: Dict[str, Any] = {
            "stale_data": False,
            "error": None,
        }
        self._last_runtime_batch_context: Dict[str, Any] = {}
        self._last_runtime_light_diagnostics: Dict[str, Any] = {}
        self._runtime_light_diag_log_lock = threading.Lock()
        self._runtime_light_diag_last_logged_at = 0.0

    def _get_watchdog_diagnostics_service(self) -> WatchdogDiagnosticsService:
        service = getattr(self, "_watchdog_diagnostics_service", None)
        if service is None:
            pnl_service = getattr(self, "pnl_service", None)
            service = WatchdogDiagnosticsService(
                getattr(pnl_service, "audit_diagnostics_service", None)
            )
            self._watchdog_diagnostics_service = service
        return service

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _age_seconds_from_iso(
        cls,
        value: Any,
        *,
        now_dt: Optional[datetime] = None,
    ) -> Optional[float]:
        parsed = cls._parse_iso_datetime(value)
        if parsed is None:
            return None
        current = now_dt or datetime.now(timezone.utc)
        return round(max((current - parsed).total_seconds(), 0.0), 3)

    @staticmethod
    def _derive_readiness_source_kind(payload: Dict[str, Any]) -> str:
        analysis_source = str(payload.get("analysis_ready_source") or "").strip().lower()
        if bool(payload.get("setup_ready_fallback_used")) or bool(
            payload.get("analysis_ready_fallback_used")
        ):
            return "fresh_fallback"
        if analysis_source == "stopped_preview_stale":
            return "stopped_preview_stale"
        if analysis_source.startswith("runtime_"):
            return "runtime"
        if analysis_source:
            return "fresh_analysis"
        return "unknown"

    def _annotate_readiness_payload(
        self,
        payload: Dict[str, Any],
        *,
        source_kind_override: Optional[str] = None,
        source_age_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        result = dict(payload or {})
        now_dt = datetime.now(timezone.utc)
        result["entry_ready_age_sec"] = self._age_seconds_from_iso(
            result.get("entry_ready_updated_at"),
            now_dt=now_dt,
        )
        result["analysis_ready_age_sec"] = self._age_seconds_from_iso(
            result.get("analysis_ready_updated_at"),
            now_dt=now_dt,
        )
        result["setup_ready_age_sec"] = self._age_seconds_from_iso(
            result.get("setup_ready_updated_at"),
            now_dt=now_dt,
        )
        result["execution_viability_age_sec"] = self._age_seconds_from_iso(
            result.get("execution_viability_updated_at"),
            now_dt=now_dt,
        )
        result["readiness_observed_at"] = now_dt.isoformat()
        result["readiness_source_kind"] = (
            str(source_kind_override or "").strip().lower()
            or str(result.get("readiness_source_kind") or "").strip().lower()
            or self._derive_readiness_source_kind(result)
        )
        result["readiness_source_age_sec"] = (
            round(max(float(source_age_sec or 0.0), 0.0), 3)
            if source_age_sec is not None
            else None
        )
        return result

    def _ensure_readiness_stability_cache(self) -> Dict[str, Dict[str, Any]]:
        cache = getattr(self, "_readiness_stability_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._readiness_stability_cache = cache
        return cache

    @staticmethod
    def _normalize_readiness_stage_from_payload(payload: Optional[Dict[str, Any]]) -> str:
        source_kind = str((payload or {}).get("readiness_source_kind") or "").strip().lower()
        preview_state = str((payload or {}).get("readiness_preview_state") or "").strip().lower()
        reasons = {
            str((payload or {}).get("setup_timing_reason") or "").strip().lower(),
            str((payload or {}).get("setup_ready_reason") or "").strip().lower(),
            str((payload or {}).get("analysis_ready_reason") or "").strip().lower(),
            str((payload or {}).get("entry_ready_reason") or "").strip().lower(),
        }
        if (
            source_kind == "stop_cleanup_pending"
            or source_kind == "stopped_preview_stale"
            or (source_kind.startswith("stopped_preview") and preview_state == "stale")
            or "stale_snapshot" in reasons
        ):
            return "watch"
        raw_stage = str(
            (payload or {}).get("setup_timing_status")
            or (payload or {}).get("setup_ready_status")
            or (payload or {}).get("analysis_ready_status")
            or (payload or {}).get("entry_ready_status")
            or ""
        ).strip().lower()
        if raw_stage == "ready":
            return "trigger_ready"
        return raw_stage or "watch"

    @staticmethod
    def _readiness_stage_rank(stage: str) -> int:
        normalized = str(stage or "").strip().lower()
        return READINESS_STABILITY_STAGE_RANK.get(normalized, 0)

    @staticmethod
    def _readiness_stage_flags(stage: str) -> Dict[str, bool]:
        normalized = str(stage or "").strip().lower()
        return {
            "actionable": normalized == "trigger_ready",
            "near_trigger": normalized == "armed",
            "late": normalized == "late",
        }

    @classmethod
    def _is_hard_readiness_invalidator(
        cls,
        *,
        raw_stage: str,
        raw_reason: str,
    ) -> bool:
        normalized_stage = str(raw_stage or "").strip().lower()
        normalized_reason = str(raw_reason or "").strip().lower()
        return (
            normalized_stage in {"blocked", "late"}
            or normalized_reason in READINESS_STABILITY_HARD_REASONS
        )

    @staticmethod
    def _stability_iso(ts_value: Optional[float]) -> Optional[str]:
        try:
            ts = float(ts_value)
        except (TypeError, ValueError):
            return None
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    @staticmethod
    def _readiness_policy_name(
        payload: Dict[str, Any],
        *,
        bot_status: str,
    ) -> str:
        source_kind = str(payload.get("readiness_source_kind") or "").strip().lower()
        preview_state = str(payload.get("readiness_preview_state") or "").strip().lower()
        if source_kind.startswith("stopped_preview") or preview_state in {
            "fresh",
            "aging",
            "stale",
            "unavailable",
        }:
            return "stopped_preview"
        if str(bot_status or "").strip().lower() in ACTIVE_POSITION_OWNER_STATUSES:
            return "live_runtime"
        return "inactive_runtime"

    @staticmethod
    def _readiness_policy(policy_name: str) -> Dict[str, Any]:
        if policy_name == "stopped_preview":
            return dict(READINESS_STABILITY_STOPPED_PREVIEW_POLICY)
        if policy_name == "live_runtime":
            return dict(READINESS_STABILITY_LIVE_POLICY)
        return dict(READINESS_STABILITY_INACTIVE_POLICY)

    def _prune_readiness_stability_cache(
        self,
        valid_bot_ids: Optional[set[str]] = None,
    ) -> None:
        cache = self._ensure_readiness_stability_cache()
        now_ts = time.time()
        normalized_valid_ids = {
            str(bot_id or "").strip()
            for bot_id in set(valid_bot_ids or set())
            if str(bot_id or "").strip()
        }
        for cache_key, state in list(cache.items()):
            bot_id = str(cache_key.split(":", 1)[0] or "").strip()
            last_seen_ts = self._safe_float((state or {}).get("last_seen_ts"), 0.0)
            expired = (
                last_seen_ts > 0
                and now_ts - last_seen_ts > READINESS_STABILITY_CACHE_TTL_SEC
            )
            missing = bool(normalized_valid_ids) and bot_id not in normalized_valid_ids
            if expired or missing:
                cache.pop(cache_key, None)

    def _apply_readiness_stability(
        self,
        payload: Dict[str, Any],
        *,
        bot: Optional[Dict[str, Any]],
        scope: str = "configured",
    ) -> Dict[str, Any]:
        result = dict(payload or {})
        raw_stage = self._normalize_readiness_stage_from_payload(result)
        raw_reason = str(
            result.get("setup_timing_reason")
            or result.get("setup_ready_reason")
            or result.get("analysis_ready_reason")
            or result.get("entry_ready_reason")
            or ""
        ).strip().lower()
        raw_reason_text = str(
            result.get("setup_timing_reason_text")
            or result.get("setup_ready_reason_text")
            or result.get("analysis_ready_reason_text")
            or result.get("entry_ready_reason_text")
            or ""
        ).strip()
        raw_detail = str(
            result.get("setup_timing_detail")
            or result.get("setup_ready_detail")
            or result.get("analysis_ready_detail")
            or result.get("entry_ready_detail")
            or ""
        ).strip()
        raw_next = str(
            result.get("setup_timing_next")
            or result.get("setup_ready_next")
            or result.get("analysis_ready_next")
            or ""
        ).strip()
        raw_updated_at = str(
            result.get("setup_timing_updated_at")
            or result.get("setup_ready_updated_at")
            or result.get("analysis_ready_updated_at")
            or result.get("entry_ready_updated_at")
            or result.get("readiness_evaluated_at")
            or result.get("readiness_generated_at")
            or ""
        ).strip()
        source_kind = str(result.get("readiness_source_kind") or "").strip().lower()
        preview_state = str(result.get("readiness_preview_state") or "").strip().lower()
        stale_reason_present = any(
            str(result.get(key) or "").strip().lower() == "stale_snapshot"
            for key in (
                "setup_timing_reason",
                "setup_ready_reason",
                "analysis_ready_reason",
                "entry_ready_reason",
            )
        )
        if source_kind == "stop_cleanup_pending":
            raw_reason = "stop_cleanup_pending"
            raw_reason_text = "Stop cleanup pending"
            raw_detail = raw_detail or (
                "Stop cleanup is still pending. No new trading should occur until "
                "orders are cleared and the position is flat."
            )
        elif (
            source_kind == "stopped_preview_stale"
            or (source_kind.startswith("stopped_preview") and preview_state == "stale")
            or stale_reason_present
        ):
            raw_reason = "stale_snapshot"
            raw_reason_text = raw_reason_text or "Stale snapshot"
            raw_detail = raw_detail or "Stopped-bot analysis preview is stale."
        bot_id = str((bot or {}).get("id") or "").strip()
        bot_status = str((bot or {}).get("status") or "").strip().lower()
        policy_name = self._readiness_policy_name(result, bot_status=bot_status)
        policy = self._readiness_policy(policy_name)
        hard_invalidated = self._is_hard_readiness_invalidator(
            raw_stage=raw_stage,
            raw_reason=raw_reason,
        )
        flags = self._readiness_stage_flags(raw_stage)

        if not bot_id:
            result.update(
                {
                    "raw_readiness_stage": raw_stage,
                    "raw_readiness_reason": raw_reason,
                    "raw_readiness_reason_text": raw_reason_text,
                    "raw_readiness_detail": raw_detail,
                    "stable_readiness_stage": raw_stage,
                    "stable_readiness_reason": raw_reason,
                    "stable_readiness_reason_text": raw_reason_text,
                    "stable_readiness_detail": raw_detail,
                    "stable_readiness_next": raw_next,
                    "stable_readiness_updated_at": raw_updated_at or None,
                    "stable_readiness_actionable": flags["actionable"],
                    "stable_readiness_near_trigger": flags["near_trigger"],
                    "stable_readiness_late": flags["late"],
                    "readiness_stability_state": "stateless",
                    "readiness_stability_policy": policy_name,
                    "readiness_stable_since": raw_updated_at or None,
                    "readiness_hold_until": None,
                    "readiness_flip_suppressed": False,
                    "readiness_hard_invalidated": hard_invalidated,
                }
            )
            return result

        cache = self._ensure_readiness_stability_cache()
        cache_key = f"{bot_id}:{scope}"
        now_ts = time.time()
        stable_stage = raw_stage
        stable_reason = raw_reason
        stable_reason_text = raw_reason_text
        stable_detail = raw_detail
        stable_next = raw_next
        stable_updated_at = raw_updated_at or None
        stable_since_ts = now_ts
        hold_until_ts = None
        stability_state = "stable"
        flip_suppressed = False

        previous = dict(cache.get(cache_key) or {})
        previous_stage = str(previous.get("stable_stage") or "").strip().lower()
        if previous_stage:
            stable_stage = previous_stage
            stable_reason = str(previous.get("stable_reason") or "").strip().lower()
            stable_reason_text = str(previous.get("stable_reason_text") or "").strip()
            stable_detail = str(previous.get("stable_detail") or "").strip()
            stable_next = str(previous.get("stable_next") or "").strip()
            stable_updated_at = str(previous.get("stable_updated_at") or "").strip() or None
            stable_since_ts = self._safe_float(previous.get("stable_since_ts"), now_ts) or now_ts
            hold_until_ts = self._safe_float(previous.get("hold_until_ts"), None)

        raw_rank = self._readiness_stage_rank(raw_stage)
        stable_rank = self._readiness_stage_rank(stable_stage)

        if not previous_stage:
            stable_stage = raw_stage
            stable_reason = raw_reason
            stable_reason_text = raw_reason_text
            stable_detail = raw_detail
            stable_next = raw_next
            stable_updated_at = raw_updated_at or None
            stable_since_ts = now_ts
            hold_until_ts = None
            stability_state = "stable"
            previous["pending_stage"] = None
            previous["pending_direction"] = None
            previous["pending_count"] = 0
        elif hard_invalidated:
            stable_stage = raw_stage
            stable_reason = raw_reason
            stable_reason_text = raw_reason_text
            stable_detail = raw_detail
            stable_next = raw_next
            stable_updated_at = raw_updated_at or None
            stable_since_ts = now_ts
            hold_until_ts = None
            stability_state = "hard_invalidated"
            previous["pending_stage"] = None
            previous["pending_direction"] = None
            previous["pending_count"] = 0
        elif raw_stage == stable_stage:
            stable_reason = raw_reason
            stable_reason_text = raw_reason_text
            stable_detail = raw_detail
            stable_next = raw_next
            stable_updated_at = raw_updated_at or None
            hold_until_ts = None
            stability_state = "stable"
            previous["pending_stage"] = None
            previous["pending_direction"] = None
            previous["pending_count"] = 0
        elif raw_rank == stable_rank:
            stable_stage = raw_stage
            stable_reason = raw_reason
            stable_reason_text = raw_reason_text
            stable_detail = raw_detail
            stable_next = raw_next
            stable_updated_at = raw_updated_at or None
            stable_since_ts = now_ts
            hold_until_ts = None
            stability_state = "stable"
            previous["pending_stage"] = None
            previous["pending_direction"] = None
            previous["pending_count"] = 0
        elif raw_rank > stable_rank:
            pending_direction = str(previous.get("pending_direction") or "").strip().lower()
            pending_stage = str(previous.get("pending_stage") or "").strip().lower()
            pending_count = int(previous.get("pending_count") or 0)
            if pending_direction == "promote" and pending_stage == raw_stage:
                pending_count += 1
            else:
                pending_count = 1
            if pending_count >= int(policy.get("promotion_confirmations") or 1):
                stable_stage = raw_stage
                stable_reason = raw_reason
                stable_reason_text = raw_reason_text
                stable_detail = raw_detail
                stable_next = raw_next
                stable_updated_at = raw_updated_at or None
                stable_since_ts = now_ts
                hold_until_ts = None
                stability_state = "stable"
                previous["pending_stage"] = None
                previous["pending_direction"] = None
                previous["pending_count"] = 0
            else:
                flip_suppressed = True
                stability_state = "promoting"
                previous["pending_stage"] = raw_stage
                previous["pending_direction"] = "promote"
                previous["pending_count"] = pending_count
                hold_until_ts = None
        else:
            pending_direction = str(previous.get("pending_direction") or "").strip().lower()
            pending_stage = str(previous.get("pending_stage") or "").strip().lower()
            pending_count = int(previous.get("pending_count") or 0)
            if pending_direction == "demote" and pending_stage == raw_stage:
                pending_count += 1
            else:
                pending_count = 1
            if hold_until_ts is None:
                hold_until_ts = now_ts + float(policy.get("hold_sec") or 0.0)
            if (
                pending_count >= int(policy.get("demotion_confirmations") or 1)
                or now_ts >= float(hold_until_ts or 0.0)
            ):
                stable_stage = raw_stage
                stable_reason = raw_reason
                stable_reason_text = raw_reason_text
                stable_detail = raw_detail
                stable_next = raw_next
                stable_updated_at = raw_updated_at or None
                stable_since_ts = now_ts
                hold_until_ts = None
                stability_state = "stable"
                previous["pending_stage"] = None
                previous["pending_direction"] = None
                previous["pending_count"] = 0
            else:
                flip_suppressed = True
                stability_state = "holding"
                previous["pending_stage"] = raw_stage
                previous["pending_direction"] = "demote"
                previous["pending_count"] = pending_count

        stable_flags = self._readiness_stage_flags(stable_stage)
        cache[cache_key] = {
            "stable_stage": stable_stage,
            "stable_reason": stable_reason,
            "stable_reason_text": stable_reason_text,
            "stable_detail": stable_detail,
            "stable_next": stable_next,
            "stable_updated_at": stable_updated_at,
            "stable_since_ts": stable_since_ts,
            "hold_until_ts": hold_until_ts,
            "pending_stage": previous.get("pending_stage"),
            "pending_direction": previous.get("pending_direction"),
            "pending_count": int(previous.get("pending_count") or 0),
            "last_seen_ts": now_ts,
            "policy_name": policy_name,
        }

        result.update(
            {
                "raw_readiness_stage": raw_stage,
                "raw_readiness_reason": raw_reason,
                "raw_readiness_reason_text": raw_reason_text,
                "raw_readiness_detail": raw_detail,
                "stable_readiness_stage": stable_stage,
                "stable_readiness_reason": stable_reason,
                "stable_readiness_reason_text": stable_reason_text,
                "stable_readiness_detail": stable_detail,
                "stable_readiness_next": stable_next,
                "stable_readiness_updated_at": stable_updated_at,
                "stable_readiness_actionable": stable_flags["actionable"],
                "stable_readiness_near_trigger": stable_flags["near_trigger"],
                "stable_readiness_late": stable_flags["late"],
                "readiness_stability_state": stability_state,
                "readiness_stability_policy": policy_name,
                "readiness_stable_since": self._stability_iso(stable_since_ts),
                "readiness_hold_until": self._stability_iso(hold_until_ts),
                "readiness_flip_suppressed": flip_suppressed,
                "readiness_hard_invalidated": hard_invalidated,
            }
        )
        return result

    @classmethod
    def _parse_timestamp(cls, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return numeric if numeric > 0 else None
        parsed = cls._parse_iso_datetime(value)
        return parsed.timestamp() if parsed is not None else None

    @staticmethod
    def _iso_from_ts(value: Optional[float]) -> Optional[str]:
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return None
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    @staticmethod
    def _build_ms_stats(samples: List[float]) -> Dict[str, Any]:
        clean = sorted(
            round(max(float(sample), 0.0), 2)
            for sample in list(samples or [])
            if sample is not None
        )
        if not clean:
            return {"count": 0, "min": None, "avg": None, "median": None, "max": None}
        size = len(clean)
        median = (
            clean[size // 2]
            if size % 2 == 1
            else round((clean[(size // 2) - 1] + clean[size // 2]) / 2.0, 2)
        )
        return {
            "count": size,
            "min": clean[0],
            "avg": round(sum(clean) / size, 2),
            "median": median,
            "max": clean[-1],
        }

    @staticmethod
    def _latency_path_for_bot(bot: Dict[str, Any]) -> str:
        source_kind = str(bot.get("readiness_source_kind") or "").strip().lower()
        status = str(bot.get("status") or "").strip().lower()
        if source_kind.startswith("stopped_preview"):
            return "stopped_preview"
        if status in ACTIVE_POSITION_OWNER_STATUSES:
            return "live_runtime"
        return "inactive_runtime"

    def _build_latency_summary(
        self,
        bots: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        source_kind_counts: Dict[str, int] = {}
        market_to_eval = []
        provider_to_eval = []
        eval_duration = []
        eval_to_publish = []
        market_to_publish = []
        market_timestamped_count = 0
        for bot in list(bots or []):
            if not isinstance(bot, dict):
                continue
            stage = str(
                bot.get("readiness_stage")
                or bot.get("setup_timing_status")
                or ""
            ).strip().lower()
            if stage:
                stage_counts[stage] = int(stage_counts.get(stage, 0)) + 1
            status = str(bot.get("status") or "").strip().lower()
            if status:
                status_counts[status] = int(status_counts.get(status, 0)) + 1
            source_kind = str(bot.get("readiness_source_kind") or "").strip().lower()
            if source_kind:
                source_kind_counts[source_kind] = int(
                    source_kind_counts.get(source_kind, 0) + 1
                )
            if bot.get("market_data_ts") is not None:
                market_timestamped_count += 1
            if bot.get("market_to_readiness_eval_start_ms") is not None:
                market_to_eval.append(bot.get("market_to_readiness_eval_start_ms"))
            if bot.get("provider_update_to_eval_ms") is not None:
                provider_to_eval.append(bot.get("provider_update_to_eval_ms"))
            eval_ms = bot.get("readiness_eval_duration_ms")
            if eval_ms is None:
                eval_ms = bot.get("readiness_eval_ms")
            if eval_ms is not None:
                eval_duration.append(eval_ms)
            if bot.get("runtime_publish_age_ms") is not None:
                eval_to_publish.append(bot.get("runtime_publish_age_ms"))
            if bot.get("market_to_runtime_publish_ms") is not None:
                market_to_publish.append(bot.get("market_to_runtime_publish_ms"))

        latest_readiness_ts = max(
            (
                self._parse_timestamp(
                    bot.get("readiness_generated_at")
                    or bot.get("readiness_eval_finished_at")
                    or bot.get("readiness_evaluated_at")
                )
                or 0.0
                for bot in list(bots or [])
                if isinstance(bot, dict)
            ),
            default=0.0,
        )
        return {
            "bot_count": len(list(bots or [])),
            "stage_counts": stage_counts,
            "status_counts": status_counts,
            "source_kind_counts": source_kind_counts,
            "market_timestamped_count": market_timestamped_count,
            "market_timestamp_missing_count": max(
                len(list(bots or [])) - market_timestamped_count,
                0,
            ),
            "market_to_eval_start_ms": self._build_ms_stats(market_to_eval),
            "provider_update_to_eval_ms": self._build_ms_stats(provider_to_eval),
            "readiness_eval_ms": self._build_ms_stats(eval_duration),
            "eval_to_runtime_publish_ms": self._build_ms_stats(eval_to_publish),
            "market_to_runtime_publish_ms": self._build_ms_stats(market_to_publish),
            "latest_readiness_generated_at": self._iso_from_ts(latest_readiness_ts),
            "latest_readiness_generated_ts": latest_readiness_ts or None,
        }

    def _annotate_runtime_publish_latency(
        self,
        bots: List[Dict[str, Any]],
        *,
        runtime_publish_ts: float,
        runtime_build_started_ts: float,
    ) -> List[Dict[str, Any]]:
        runtime_publish_at = self._iso_from_ts(runtime_publish_ts)
        annotated: List[Dict[str, Any]] = []
        for raw_bot in list(bots or []):
            bot = dict(raw_bot or {})
            eval_finished_ts = self._parse_timestamp(
                bot.get("readiness_eval_finished_at")
                or bot.get("readiness_generated_at")
                or bot.get("readiness_evaluated_at")
            )
            market_ts = self._parse_timestamp(bot.get("market_data_ts"))
            bot["readiness_latency_path"] = self._latency_path_for_bot(bot)
            bot["runtime_publish_ts"] = runtime_publish_ts
            bot["runtime_publish_at"] = runtime_publish_at
            bot["runtime_publish_age_ms"] = (
                round(max(runtime_publish_ts - eval_finished_ts, 0.0) * 1000.0, 2)
                if eval_finished_ts is not None
                else None
            )
            bot["market_to_runtime_publish_ms"] = (
                round(max(runtime_publish_ts - market_ts, 0.0) * 1000.0, 2)
                if market_ts is not None
                else None
            )
            annotated.append(bot)

        overall_summary = self._build_latency_summary(annotated)
        latency_paths = {
            "live_runtime": self._build_latency_summary(
                [
                    bot
                    for bot in annotated
                    if bot.get("readiness_latency_path") == "live_runtime"
                ]
            ),
            "stopped_preview": self._build_latency_summary(
                [
                    bot
                    for bot in annotated
                    if bot.get("readiness_latency_path") == "stopped_preview"
                ]
            ),
            "inactive_runtime": self._build_latency_summary(
                [
                    bot
                    for bot in annotated
                    if bot.get("readiness_latency_path") == "inactive_runtime"
                ]
            ),
        }
        dominant_segment = None
        dominant_value = -1.0
        for segment_name in (
            "provider_update_to_eval_ms",
            "market_to_eval_start_ms",
            "readiness_eval_ms",
            "eval_to_runtime_publish_ms",
            "market_to_runtime_publish_ms",
        ):
            stats = overall_summary.get(segment_name) or {}
            avg_value = stats.get("avg")
            if avg_value is None:
                continue
            if float(avg_value) > dominant_value:
                dominant_segment = segment_name
                dominant_value = float(avg_value)

        self._last_runtime_batch_context = {
            "runtime_publish_ts": runtime_publish_ts,
            "runtime_publish_at": runtime_publish_at,
            "runtime_build_duration_ms": round(
                max(runtime_publish_ts - runtime_build_started_ts, 0.0) * 1000.0,
                2,
            ),
            "readiness_latency": {
                "bot_count": overall_summary["bot_count"],
                "stage_counts": overall_summary["stage_counts"],
                "status_counts": overall_summary["status_counts"],
                "source_kind_counts": overall_summary["source_kind_counts"],
                "market_timestamped_count": overall_summary["market_timestamped_count"],
                "market_timestamp_missing_count": overall_summary[
                    "market_timestamp_missing_count"
                ],
                "provider_update_to_eval_ms": overall_summary[
                    "provider_update_to_eval_ms"
                ],
                "market_to_eval_start_ms": overall_summary["market_to_eval_start_ms"],
                "readiness_eval_ms": overall_summary["readiness_eval_ms"],
                "eval_to_runtime_publish_ms": overall_summary[
                    "eval_to_runtime_publish_ms"
                ],
                "market_to_runtime_publish_ms": overall_summary[
                    "market_to_runtime_publish_ms"
                ],
                "paths": latency_paths,
                "dominant_segment": dominant_segment,
                "dominant_segment_avg_ms": (
                    round(dominant_value, 2) if dominant_value >= 0 else None
                ),
                "latest_readiness_generated_at": overall_summary[
                    "latest_readiness_generated_at"
                ],
                "latest_readiness_generated_ts": overall_summary[
                    "latest_readiness_generated_ts"
                ],
            },
        }
        return annotated

    def get_last_runtime_batch_context(self) -> Dict[str, Any]:
        return dict(self._last_runtime_batch_context)

    def get_last_runtime_light_diagnostics(self) -> Dict[str, Any]:
        return dict(self._last_runtime_light_diagnostics)

    @staticmethod
    def _runtime_diag_top_phase(phase_ms: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        top_name = None
        top_elapsed_ms = -1.0
        for name, elapsed in (phase_ms or {}).items():
            try:
                numeric_elapsed = float(elapsed or 0.0)
            except (TypeError, ValueError):
                continue
            if numeric_elapsed > top_elapsed_ms:
                top_name = str(name)
                top_elapsed_ms = numeric_elapsed
        if top_name is None:
            return None
        return {
            "name": top_name,
            "elapsed_ms": round(top_elapsed_ms, 3),
        }

    def _maybe_log_runtime_light_diagnostics(self, diagnostics: Dict[str, Any]) -> None:
        total_ms = self._safe_float(diagnostics.get("total_ms"), 0.0)
        if total_ms < RUNTIME_LIGHT_DIAGNOSTIC_SLOW_CALL_MS:
            return
        now_mono = time.monotonic()
        with self._runtime_light_diag_log_lock:
            if (
                self._runtime_light_diag_last_logged_at > 0
                and (now_mono - self._runtime_light_diag_last_logged_at)
                < RUNTIME_LIGHT_DIAGNOSTIC_LOG_THROTTLE_SEC
            ):
                return
            self._runtime_light_diag_last_logged_at = now_mono
        top_phase = diagnostics.get("top_phase") or {}
        storage = diagnostics.get("storage") or {}
        logging.warning(
            "Runtime bots light diagnostics total_ms=%.1f bot_count=%d top_phase=%s top_phase_ms=%.1f "
            "storage_reads=%d cache_lock_wait_ms=%.1f runtime_lock_wait_ms=%.1f file_lock_wait_ms=%.1f",
            total_ms,
            int(diagnostics.get("bot_count") or 0),
            top_phase.get("name") or "-",
            self._safe_float(top_phase.get("elapsed_ms"), 0.0),
            int(storage.get("storage_read_call_count") or 0),
            self._safe_float((storage.get("lock_wait_ms") or {}).get("cache_lock"), 0.0),
            self._safe_float((storage.get("lock_wait_ms") or {}).get("runtime_lock"), 0.0),
            self._safe_float((storage.get("lock_wait_ms") or {}).get("file_lock_shared"), 0.0),
        )

    @staticmethod
    def _get_raw_runtime_signal_blocker(bot: Dict[str, Any]) -> Optional[str]:
        reconcile = dict(bot.get("exchange_reconciliation") or {})
        reconcile_status = str(reconcile.get("status") or "").strip().lower()
        mismatches = [
            str(item or "").strip().lower()
            for item in list(reconcile.get("mismatches") or [])
            if str(item or "").strip()
        ]
        if reconcile_status in {
            "diverged",
            "error_with_exchange_persist_divergence",
        } or mismatches:
            return "reconciliation_diverged"
        if bot.get("position_assumption_stale") or bot.get("order_assumption_stale"):
            return "exchange_truth_stale"
        ambiguous_follow_up = dict(bot.get("ambiguous_execution_follow_up") or {})
        ambiguous_status = str(
            ambiguous_follow_up.get("status") or ""
        ).strip().lower()
        if bool(ambiguous_follow_up.get("pending")) or ambiguous_status == "still_unresolved" or bool(
            ambiguous_follow_up.get("truth_check_expired")
        ):
            return "exchange_state_untrusted"
        if bot.get("_session_timer_block_opening_orders"):
            return str(bot.get("session_timer_state") or "session_timer")
        if bot.get("_capital_starved_block_opening_orders"):
            return str(bot.get("capital_starved_reason") or "capital_starved")
        if bot.get("_small_capital_block_opening_orders"):
            return str(bot.get("last_skip_reason") or "qty_below_min")
        if bot.get("_watchdog_position_cap_active"):
            return "position_cap_hit"
        if bot.get("_breakout_invalidation_block_opening_orders"):
            return "breakout_invalidation"
        if bot.get("_stall_overlay_block_opening_orders"):
            return "stall_blocked"
        if bot.get("_block_opening_orders"):
            return "opening_blocked"
        return None

    @classmethod
    def _capital_starved_runtime_visible(
        cls,
        bot: Dict[str, Any],
        entry_readiness: Optional[Dict[str, Any]] = None,
    ) -> bool:
        raw_blocker = cls._get_raw_runtime_signal_blocker(bot)
        if raw_blocker not in CAPITAL_STARVED_RUNTIME_REASONS:
            return False
        summary = bot.get("watchdog_bottleneck_summary")
        status = str(bot.get("status") or "").strip().lower()
        if (
            isinstance(summary, dict)
            and summary.get("capital_starved_active") is False
            and status
            and status not in ACTIVE_POSITION_OWNER_STATUSES
        ):
            return False
        if not isinstance(entry_readiness, dict):
            return True
        current_reason = str(
            entry_readiness.get("entry_ready_reason") or ""
        ).strip().lower()
        if current_reason:
            return current_reason in CAPITAL_STARVED_RUNTIME_REASONS
        return True

    @classmethod
    def _get_runtime_signal_blocker(
        cls,
        bot: Dict[str, Any],
        entry_readiness: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        status = str(bot.get("status") or "").strip().lower()
        diagnostic_reason = str(
            (entry_readiness or {}).get("execution_viability_diagnostic_reason") or ""
        ).strip().lower()
        if (
            status
            and status not in ACTIVE_POSITION_OWNER_STATUSES
            and isinstance(entry_readiness, dict)
            and bool(entry_readiness.get("execution_viability_stale_data"))
            and not bool(entry_readiness.get("execution_blocked"))
            and diagnostic_reason
            in {
                "stale_balance",
                "stale_runtime_blocker",
                "stale_snapshot",
                "stop_cleanup_pending",
            }
        ):
            return None
        raw_exchange_truth_blocker = cls._get_raw_runtime_signal_blocker(bot)
        if raw_exchange_truth_blocker in {
            "exchange_truth_stale",
            "reconciliation_diverged",
            "exchange_state_untrusted",
        }:
            return raw_exchange_truth_blocker
        if bot.get("_session_timer_block_opening_orders"):
            return "session_blocked"
        if cls._capital_starved_runtime_visible(bot, entry_readiness):
            return str(bot.get("capital_starved_reason") or "capital_starved")
        if bot.get("_small_capital_block_opening_orders"):
            return str(bot.get("last_skip_reason") or "qty_below_min")
        if bot.get("_watchdog_position_cap_active"):
            return "position_cap_hit"
        if bot.get("_breakout_invalidation_block_opening_orders"):
            return "breakout_invalidation"
        if bot.get("_stall_overlay_block_opening_orders"):
            return "stall_blocked"
        if bot.get("_block_opening_orders"):
            return "opening_blocked"
        return None

    def _maybe_emit_signal_drift_watchdog(
        self,
        bot: Dict[str, Any],
        entry_readiness: Dict[str, Any],
    ) -> None:
        watchdog_service = self._get_watchdog_diagnostics_service()
        if not watchdog_service.enabled("signal_drift"):
            return
        symbol = str(bot.get("symbol") or "").strip().upper()
        mode = str(bot.get("mode") or "").strip().lower()
        if not symbol or mode not in ("long", "short", "neutral", "neutral_classic_bybit", "scalp_market", "scalp_pnl"):
            return
        entry_status = str(entry_readiness.get("entry_ready_status") or "").strip().lower()
        analysis_status = str(entry_readiness.get("analysis_ready_status") or "").strip().lower()
        setup_status = str(
            entry_readiness.get("setup_ready_status") or analysis_status
        ).strip().lower()
        live_gate_status = str(entry_readiness.get("live_gate_status") or "").strip().lower()
        execution_blocked = bool(entry_readiness.get("execution_blocked")) or (
            str(entry_readiness.get("execution_viability_status") or "").strip().lower()
            == "blocked"
        )
        execution_reason = str(
            entry_readiness.get("execution_viability_reason") or ""
        ).strip().lower()
        runtime_blocker = self._get_runtime_signal_blocker(bot, entry_readiness)
        gate_blocked = bool(bot.get("_entry_gate_blocked"))
        signal_executable = bool(bot.get("entry_signal_executable"))
        scanner_differs = bool(bot.get("scanner_recommendation_differs"))
        reasons = []
        if scanner_differs and signal_executable:
            reasons.append("scanner_runtime_disagree")
        if entry_status == "ready" and runtime_blocker and not execution_blocked:
            reasons.append("ready_but_runtime_blocked")
        if setup_status != "ready" and entry_status == "ready" and not execution_blocked:
            reasons.append("analysis_runtime_disagree")
        if signal_executable and gate_blocked:
            reasons.append("signal_executable_but_gate_blocked")
        if entry_status == "ready" and not bot.get("entry_signal_code") and not execution_blocked:
            reasons.append("readiness_without_signal_class")
        if execution_blocked and not runtime_blocker and not execution_reason:
            reasons.append("blocked_without_runtime_blocker")
        for reason in reasons:
            watchdog_service.emit(
                watchdog_type="signal_drift",
                severity="WARN",
                bot=bot,
                symbol=symbol,
                mode=mode,
                reason=reason,
                throttle_key=f"signal_drift:{bot.get('id')}:{reason}",
                compact_metrics={
                    "scanner_recommendation_differs": scanner_differs,
                    "scanner_recommended_mode": bot.get("scanner_recommended_mode"),
                    "entry_ready_status": entry_status,
                    "analysis_ready_status": analysis_status,
                    "setup_ready_status": setup_status,
                    "live_gate_status": live_gate_status,
                    "execution_blocked": execution_blocked,
                    "execution_reason": execution_reason,
                    "signal_code": bot.get("entry_signal_code"),
                    "signal_executable": signal_executable,
                    "signal_preferred": bool(bot.get("entry_signal_preferred")),
                    "gate_blocked": gate_blocked,
                    "runtime_blocker": runtime_blocker,
                },
                suggested_action=(
                    "Treat scanner/readiness/gate disagreement as an observability contract issue, not a trade trigger."
                ),
                source_context={
                    "entry_ready_reason": entry_readiness.get("entry_ready_reason"),
                    "analysis_ready_reason": entry_readiness.get("analysis_ready_reason"),
                    "setup_ready_reason": entry_readiness.get("setup_ready_reason"),
                    "execution_viability_reason": entry_readiness.get(
                        "execution_viability_reason"
                    ),
                    "live_gate_reason": entry_readiness.get("live_gate_reason"),
                    "entry_signal_label": bot.get("entry_signal_label"),
                },
            )

    def get_runtime_bots(
        self,
        *,
        positions_skip_cache: bool = False,
        positions_data: Optional[Dict[str, Any]] = None,
        live_open_orders_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        scanner_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        cache_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Build enriched runtime info for all bots.

        Returns:
            List of enriched bot dictionaries with position and PnL data
        """
        runtime_build_started_ts = time.time()
        # Load all bots
        bots = self.bot_storage.list_bots()
        self._prune_readiness_stability_cache(
            {
                str(bot.get("id") or "").strip()
                for bot in list(bots or [])
                if str(bot.get("id") or "").strip()
            }
        )
        running_bot_ids_by_symbol = self._build_running_bot_ids_by_symbol(bots)
        symbol_pnl_lookup = self.symbol_pnl_service.get_all_symbols_pnl()
        bot_pnl_lookup = self.symbol_pnl_service.get_all_bot_pnl()

        active_symbol_owner_bots = [
            bot
            for bot in bots
            if bot.get("status") in ACTIVE_POSITION_OWNER_STATUSES
            and str(bot.get("symbol") or "").strip()
            and str(bot.get("symbol") or "").strip().lower() != "auto-pilot"
        ]

        if not active_symbol_owner_bots:
            stopped_preview_lookup = self._build_stopped_preview_lookup(bots, cache_only=cache_only)
            enriched_bots = []
            for bot in bots:
                enriched_bots.append(
                    self._enrich_bot(
                        bot,
                        {},
                        {},
                        symbol_pnl_lookup,
                        bot_pnl_lookup,
                        running_bot_ids_by_symbol,
                        {},
                        {},
                        stopped_preview_lookup,
                    )
                )
            enriched_bots.sort(
                key=lambda x: (
                    0 if bool(x.get("auto_pilot")) else 1,
                    str(x.get("symbol") or ""),
                )
            )
            return self._annotate_runtime_publish_latency(
                enriched_bots,
                runtime_publish_ts=time.time(),
                runtime_build_started_ts=runtime_build_started_ts,
            )

        scanner_lookup = scanner_lookup or self._get_scanner_recommendation_lookup(bots, cache_only=cache_only)
        stopped_preview_lookup = self._build_stopped_preview_lookup(bots, cache_only=cache_only)

        # Get current positions
        positions_data = positions_data or self._get_runtime_positions_payload(
            skip_cache=positions_skip_cache
        )
        positions_list = positions_data.get("positions", [])
        positions_by_symbol = self._build_positions_by_symbol(positions_list)

        # Build position lookup by symbol
        position_lookup: Dict[str, Dict[str, Any]] = {}
        for pos in positions_list:
            symbol = pos.get("symbol")
            if symbol:
                position_lookup[symbol] = {
                    "size": pos.get("size", 0.0),
                    "side": pos.get("side", ""),
                    "unrealized_pnl": pos.get("unrealized_pnl", 0.0),
                    "entry_price": pos.get("entry_price", 0.0),
                    "mark_price": pos.get("mark_price", 0.0),
                }

        live_open_orders_by_symbol = (
            live_open_orders_by_symbol
            if live_open_orders_by_symbol is not None
            else self._build_live_open_orders_by_symbol(bots, cache_only=cache_only)
        )

        # Enrich each bot
        enriched_bots = []
        for bot in bots:
            enriched = self._enrich_bot(
                bot,
                position_lookup,
                positions_by_symbol,
                symbol_pnl_lookup,
                bot_pnl_lookup,
                running_bot_ids_by_symbol,
                scanner_lookup,
                live_open_orders_by_symbol,
                stopped_preview_lookup,
            )
            enriched_bots.append(enriched)

        # Keep Auto-Pilot bots first in every runtime list, then sort by symbol.
        enriched_bots.sort(
            key=lambda x: (
                0 if bool(x.get("auto_pilot")) else 1,
                str(x.get("symbol") or ""),
            )
        )

        return self._annotate_runtime_publish_latency(
            enriched_bots,
            runtime_publish_ts=time.time(),
            runtime_build_started_ts=runtime_build_started_ts,
        )

    # ------------------------------------------------------------------
    # Light runtime bots — dashboard-critical fields only, cache-only
    # ------------------------------------------------------------------

    def get_runtime_bots_light(
        self,
        *,
        positions_skip_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """Build a lightweight runtime view for all bots.

        Designed for the fast publish cadence.  Differences from
        ``get_runtime_bots()``:

        * Scanner lookup, stopped-preview lookup, open-order lookup all
          use **cache_only=True** — never trigger expensive recomputation.
        * Per-bot enrichment uses ``_enrich_bot_light()`` which skips the
          mode readiness matrix, alternative-mode deep analysis, and
          price-action recomputation.
        * Only fields in the LIGHT contract are emitted.

        The method is safe to call every 2 seconds without stalling.
        """
        runtime_build_started_ts = time.time()
        started_mono = time.monotonic()
        phase_ms: Dict[str, float] = {}
        operation_counts: Dict[str, int] = {}
        enrich_diagnostics: Dict[str, float] = {
            "readiness_stability_ms": 0.0,
            "light_dict_build_ms": 0.0,
        }

        def record_phase(name: str, phase_started: float) -> None:
            phase_ms[name] = round(
                max(time.monotonic() - phase_started, 0.0) * 1000.0,
                3,
            )

        def count_operation(name: str) -> None:
            operation_counts[name] = int(operation_counts.get(name) or 0) + 1

        with self.bot_storage.capture_read_diagnostics(
            "bot_status_service.get_runtime_bots_light"
        ) as storage_diag:
            phase_started = time.monotonic()
            count_operation("bot_storage.list_bots")
            bots = self.bot_storage.list_bots(
                source="bot_status_runtime_light",
                projector=extract_light_bot,
                read_only_projected_cache=True,
            )
            record_phase("source_bot_load_ms", phase_started)

            phase_started = time.monotonic()
            self._prune_readiness_stability_cache(
                {
                    str(bot.get("id") or "").strip()
                    for bot in list(bots or [])
                    if str(bot.get("id") or "").strip()
                }
            )
            running_bot_ids_by_symbol = self._build_running_bot_ids_by_symbol(bots)
            record_phase("runtime_merge_index_ms", phase_started)

            phase_started = time.monotonic()
            count_operation("symbol_pnl_service.get_all_pnl_data")
            all_pnl_data = self.symbol_pnl_service.get_all_pnl_data()
            record_phase("shared_pnl_read_ms", phase_started)

            phase_started = time.monotonic()
            symbol_pnl_lookup = {
                key: value
                for key, value in (all_pnl_data or {}).items()
                if not str(key).startswith("bot:")
            }
            record_phase("symbol_pnl_lookup_ms", phase_started)

            phase_started = time.monotonic()
            bot_pnl_lookup = {
                str(key)[4:]: value
                for key, value in (all_pnl_data or {}).items()
                if str(key).startswith("bot:")
            }
            record_phase("bot_pnl_lookup_ms", phase_started)

            phase_started = time.monotonic()
            active_symbol_owner_bots = [
                bot
                for bot in bots
                if bot.get("status") in ACTIVE_POSITION_OWNER_STATUSES
                and str(bot.get("symbol") or "").strip()
                and str(bot.get("symbol") or "").strip().lower() != "auto-pilot"
            ]
            record_phase("active_symbol_owner_scan_ms", phase_started)

            phase_started = time.monotonic()
            count_operation("scanner_lookup")
            scanner_lookup = self._get_scanner_recommendation_lookup(
                bots,
                cache_only=True,
            )
            record_phase("scanner_lookup_ms", phase_started)

            phase_started = time.monotonic()
            count_operation("stopped_preview_lookup")
            stopped_preview_lookup = self._build_stopped_preview_lookup(
                bots,
                cache_only=True,
            )
            record_phase("stopped_preview_lookup_ms", phase_started)

            if not active_symbol_owner_bots:
                positions_data = {"positions": []}
                live_open_orders_by_symbol = {}
                phase_ms["positions_payload_ms"] = 0.0
                phase_ms["open_orders_lookup_ms"] = 0.0
            else:
                phase_started = time.monotonic()
                count_operation("runtime_positions_payload")
                positions_data = self._get_runtime_positions_payload(
                    skip_cache=positions_skip_cache
                )
                record_phase("positions_payload_ms", phase_started)

                phase_started = time.monotonic()
                count_operation("live_open_orders_lookup")
                live_open_orders_by_symbol = self._build_live_open_orders_by_symbol(
                    bots,
                    cache_only=True,
                )
                record_phase("open_orders_lookup_ms", phase_started)

            phase_started = time.monotonic()
            positions_list = positions_data.get("positions", [])
            positions_by_symbol = self._build_positions_by_symbol(positions_list)
            position_lookup: Dict[str, Dict[str, Any]] = {}
            for pos in positions_list:
                symbol = pos.get("symbol")
                if symbol:
                    position_lookup[symbol] = {
                        "size": pos.get("size", 0.0),
                        "side": pos.get("side", ""),
                        "unrealized_pnl": pos.get("unrealized_pnl", 0.0),
                        "entry_price": pos.get("entry_price", 0.0),
                        "mark_price": pos.get("mark_price", 0.0),
                    }
            record_phase("position_lookup_ms", phase_started)

            phase_started = time.monotonic()
            enriched_bots = []
            for bot in bots:
                enriched = self._enrich_bot_light(
                    bot,
                    position_lookup,
                    positions_by_symbol,
                    symbol_pnl_lookup,
                    bot_pnl_lookup,
                    running_bot_ids_by_symbol,
                    scanner_lookup,
                    live_open_orders_by_symbol,
                    stopped_preview_lookup,
                    diagnostics=enrich_diagnostics,
                )
                enriched_bots.append(enriched)
            record_phase("per_bot_enrich_ms", phase_started)

            phase_started = time.monotonic()
            enriched_bots.sort(
                key=lambda x: (
                    0 if bool(x.get("auto_pilot")) else 1,
                    str(x.get("symbol") or ""),
                )
            )
            record_phase("sort_and_finalize_ms", phase_started)

            runtime_publish_ts = time.time()
            annotated = self._annotate_runtime_publish_latency(
                enriched_bots,
                runtime_publish_ts=runtime_publish_ts,
                runtime_build_started_ts=runtime_build_started_ts,
            )

        phase_ms["readiness_stability_ms"] = round(
            float(enrich_diagnostics.get("readiness_stability_ms") or 0.0),
            3,
        )
        phase_ms["light_dict_build_ms"] = round(
            float(enrich_diagnostics.get("light_dict_build_ms") or 0.0),
            3,
        )
        diagnostics = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "total_ms": round(max(time.monotonic() - started_mono, 0.0) * 1000.0, 3),
            "bot_count": len(annotated),
            "active_symbol_owner_bot_count": len(active_symbol_owner_bots),
            "position_count": len(positions_list),
            "positions_skip_cache": bool(positions_skip_cache),
            "cache_only_paths": {
                "scanner_lookup": True,
                "stopped_preview_lookup": True,
                "live_open_orders_lookup": True,
            },
            "pnl_row_count": len(all_pnl_data or {}),
            "symbol_pnl_row_count": len(symbol_pnl_lookup),
            "bot_pnl_row_count": len(bot_pnl_lookup),
            "phase_ms": phase_ms,
            "storage": dict(storage_diag),
            "operation_counts": operation_counts,
        }
        diagnostics["top_phase"] = self._runtime_diag_top_phase(phase_ms)
        top_operation_name = None
        top_operation_count = 0
        for name, count in operation_counts.items():
            if int(count or 0) > top_operation_count:
                top_operation_name = str(name)
                top_operation_count = int(count or 0)
        diagnostics["top_repeated_operation"] = (
            {
                "name": top_operation_name,
                "count": top_operation_count,
            }
            if top_operation_name and top_operation_count > 1
            else (dict(storage_diag.get("top_repeated_operation")) if storage_diag.get("top_repeated_operation") else None)
        )
        self._last_runtime_light_diagnostics = diagnostics
        self._maybe_log_runtime_light_diagnostics(diagnostics)
        return annotated

    def get_live_open_orders_by_symbol(
        self,
        bots: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        return self._build_live_open_orders_by_symbol(
            list(bots) if bots is not None else self.bot_storage.list_bots()
        )

    def get_live_open_order_summary_by_symbol(
        self,
        bots: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, int]]:
        started_mono = time.monotonic()
        bot_rows = list(bots) if bots is not None else self.bot_storage.list_bots()
        symbols = self._collect_live_order_symbols(bot_rows)
        diagnostics: Dict[str, Any] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "symbol_count": len(symbols),
            "path": None,
            "client_query_ms": 0.0,
            "fallback_build_ms": 0.0,
            "shaping_ms": 0.0,
            "order_row_count": 0,
            "cache_hit_count": 0,
            "stream_hit_count": 0,
            "rest_call_count": 0,
            "rest_success_count": 0,
            "stream_query_ms": 0.0,
            "rest_query_ms": 0.0,
            "fallback_reason": None,
            "stream_handoff_reason": None,
            "stream_symbol_miss_count": 0,
            "stream_miss_reason": None,
            "stream_miss_symbol": None,
            "stream_miss_state": None,
            "matched_order_row_count": 0,
            "all_orders_cache_hit_count": 0,
            "all_orders_cache_age_ms": None,
            "single_symbol_fill_ms": 0.0,
        }
        if not symbols:
            diagnostics["path"] = "empty"
            diagnostics["total_ms"] = round(
                max(time.monotonic() - started_mono, 0.0) * 1000.0,
                3,
            )
            self._last_live_open_orders_diagnostics = diagnostics
            return {}

        client = getattr(self.position_service, "client", None)
        stream_summary = self._build_stream_open_order_summary_by_symbol(
            symbols=symbols,
            client=client,
            diagnostics=diagnostics,
        )
        if stream_summary is not None:
            diagnostics["path"] = "per_symbol_stream"
            diagnostics["total_ms"] = round(
                max(time.monotonic() - started_mono, 0.0) * 1000.0,
                3,
            )
            self._last_live_open_orders_diagnostics = diagnostics
            return stream_summary

        cached_order_rows, cached_age_ms = self._get_cached_live_all_order_rows()
        if cached_order_rows is not None:
            shaping_started = time.monotonic()
            summary, grouped_rows_by_symbol, matched_order_row_count = (
                self._group_and_summarize_order_rows_by_symbol(
                    symbols=symbols,
                    order_rows=cached_order_rows,
                )
            )
            self._seed_live_open_orders_cache_from_symbol_rows(
                symbols=symbols,
                order_rows_by_symbol=grouped_rows_by_symbol,
            )
            diagnostics["order_row_count"] = len(cached_order_rows)
            diagnostics["matched_order_row_count"] = matched_order_row_count
            diagnostics["all_orders_cache_hit_count"] = 1
            diagnostics["all_orders_cache_age_ms"] = cached_age_ms
            diagnostics["shaping_ms"] = round(
                max(time.monotonic() - shaping_started, 0.0) * 1000.0,
                3,
            )
            diagnostics["path"] = "all_orders_cache"
            diagnostics["total_ms"] = round(
                max(time.monotonic() - started_mono, 0.0) * 1000.0,
                3,
            )
            self._last_live_open_orders_diagnostics = diagnostics
            return summary

        if len(symbols) == 1:
            single_symbol_started = time.monotonic()
            order_map = self._build_live_open_orders_by_symbol(
                bot_rows,
                diagnostics=diagnostics,
                skip_stream=True,
            )
            diagnostics["single_symbol_fill_ms"] = round(
                max(time.monotonic() - single_symbol_started, 0.0) * 1000.0,
                3,
            )
            if symbols[0] in order_map:
                shaping_started = time.monotonic()
                summary = self._summarize_order_rows_by_symbol(
                    symbols=symbols,
                    order_rows_by_symbol=order_map,
                )
                order_rows = list(order_map.get(symbols[0]) or [])
                diagnostics["order_row_count"] = len(order_rows)
                diagnostics["matched_order_row_count"] = len(order_rows)
                diagnostics["shaping_ms"] = round(
                    max(time.monotonic() - shaping_started, 0.0) * 1000.0,
                    3,
                )
                diagnostics["path"] = "single_symbol_rest_fill"
                diagnostics["total_ms"] = round(
                    max(time.monotonic() - started_mono, 0.0) * 1000.0,
                    3,
                )
                self._last_live_open_orders_diagnostics = diagnostics
                return summary

        if client is not None and hasattr(client, "get_open_orders"):
            query_started = time.monotonic()
            try:
                response = client.get_open_orders(
                    limit=200,
                    skip_cache=False,
                )
            except Exception as exc:
                response = None
                diagnostics["fallback_reason"] = f"client_query_exception:{type(exc).__name__}"
            diagnostics["client_query_ms"] = round(
                max(time.monotonic() - query_started, 0.0) * 1000.0,
                3,
            )
            if response and response.get("success"):
                data = response.get("data", {}) or {}
                order_rows = data.get("list", []) if isinstance(data, dict) else data
                if isinstance(order_rows, list):
                    diagnostics["order_row_count"] = len(order_rows)
                    if len(order_rows) < 200:
                        shaping_started = time.monotonic()
                        summary, grouped_rows_by_symbol, matched_order_row_count = (
                            self._group_and_summarize_order_rows_by_symbol(
                                symbols=symbols,
                                order_rows=order_rows,
                            )
                        )
                        self._seed_live_open_orders_all_cache(order_rows)
                        self._seed_live_open_orders_cache_from_symbol_rows(
                            symbols=symbols,
                            order_rows_by_symbol=grouped_rows_by_symbol,
                        )
                        diagnostics["matched_order_row_count"] = matched_order_row_count
                        diagnostics["shaping_ms"] = round(
                            max(time.monotonic() - shaping_started, 0.0) * 1000.0,
                            3,
                        )
                        diagnostics["path"] = (
                            "all_orders_stream"
                            if bool(response.get("from_stream"))
                            else "all_orders_client"
                        )
                        diagnostics["total_ms"] = round(
                            max(time.monotonic() - started_mono, 0.0) * 1000.0,
                            3,
                        )
                        self._last_live_open_orders_diagnostics = diagnostics
                        return summary
                    diagnostics["fallback_reason"] = "all_orders_limit_reached"
                else:
                    diagnostics["fallback_reason"] = "all_orders_invalid_payload"
            elif response is not None and not diagnostics.get("fallback_reason"):
                diagnostics["fallback_reason"] = str(response.get("error") or "client_query_failed")
        elif diagnostics.get("fallback_reason") is None:
            diagnostics["fallback_reason"] = "client_unavailable"

        fallback_started = time.monotonic()
        order_map = self._build_live_open_orders_by_symbol(
            bot_rows,
            diagnostics=diagnostics,
        )
        diagnostics["fallback_build_ms"] = round(
            max(time.monotonic() - fallback_started, 0.0) * 1000.0,
            3,
        )
        shaping_started = time.monotonic()
        summary = self._summarize_order_rows_by_symbol(
            symbols=symbols,
            order_rows_by_symbol=order_map,
        )
        diagnostics["shaping_ms"] = round(
            float(diagnostics.get("shaping_ms") or 0.0)
            + max(time.monotonic() - shaping_started, 0.0) * 1000.0,
            3,
        )
        diagnostics["path"] = "per_symbol_fallback"
        diagnostics["total_ms"] = round(
            max(time.monotonic() - started_mono, 0.0) * 1000.0,
            3,
        )
        self._last_live_open_orders_diagnostics = diagnostics
        return summary

    def get_last_live_open_orders_diagnostics(self) -> Dict[str, Any]:
        return dict(self._last_live_open_orders_diagnostics)

    @staticmethod
    def _collect_live_order_symbols(bots: List[Dict[str, Any]]) -> List[str]:
        return sorted(
            {
                str(bot.get("symbol") or "").strip().upper()
                for bot in (bots or [])
                if str(bot.get("symbol") or "").strip()
                and bot.get("status") in LIVE_ORDER_OWNER_STATUSES
                and str(bot.get("symbol") or "").strip().lower() != "auto-pilot"
            }
        )

    def _build_stream_open_order_summary_by_symbol(
        self,
        *,
        symbols: List[str],
        client: Any,
        diagnostics: Dict[str, Any],
    ) -> Optional[Dict[str, Dict[str, int]]]:
        stream_service = getattr(client, "stream_service", None) if client is not None else None
        if stream_service is None or not hasattr(stream_service, "get_open_orders_fresh"):
            return None

        order_rows_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        total_rows = 0
        for symbol in symbols or []:
            stream_started = time.monotonic()
            try:
                response = stream_service.get_open_orders_fresh(
                    symbol=symbol,
                    limit=200,
                )
            except Exception:
                response = None
            diagnostics["stream_query_ms"] = round(
                float(diagnostics.get("stream_query_ms") or 0.0)
                + max(time.monotonic() - stream_started, 0.0) * 1000.0,
                3,
            )
            if not response or not response.get("success"):
                diagnostics["stream_symbol_miss_count"] = int(
                    diagnostics.get("stream_symbol_miss_count") or 0
                ) + 1
                self._record_open_order_stream_miss(
                    diagnostics=diagnostics,
                    stream_service=stream_service,
                    symbol=symbol,
                    default_reason="stream_query_failed",
                )
                return None
            data = response.get("data", {}) or {}
            order_rows = data.get("list", []) if isinstance(data, dict) else data
            if not isinstance(order_rows, list):
                diagnostics["stream_symbol_miss_count"] = int(
                    diagnostics.get("stream_symbol_miss_count") or 0
                ) + 1
                self._record_open_order_stream_miss(
                    diagnostics=diagnostics,
                    stream_service=stream_service,
                    symbol=symbol,
                    default_reason="stream_invalid_payload",
                )
                return None
            normalized_rows = list(order_rows)
            order_rows_by_symbol[symbol] = normalized_rows
            total_rows += len(normalized_rows)
            diagnostics["stream_hit_count"] = int(diagnostics.get("stream_hit_count") or 0) + 1

        shaping_started = time.monotonic()
        summary = self._summarize_order_rows_by_symbol(
            symbols=symbols,
            order_rows_by_symbol=order_rows_by_symbol,
        )
        self._seed_live_open_orders_cache_from_symbol_rows(
            symbols=symbols,
            order_rows_by_symbol=order_rows_by_symbol,
        )
        diagnostics["order_row_count"] = total_rows
        diagnostics["matched_order_row_count"] = total_rows
        diagnostics["shaping_ms"] = round(
            max(time.monotonic() - shaping_started, 0.0) * 1000.0,
            3,
        )
        return summary

    @staticmethod
    def _record_open_order_stream_miss(
        *,
        diagnostics: Dict[str, Any],
        stream_service: Any,
        symbol: str,
        default_reason: str,
    ) -> None:
        diagnostics["stream_handoff_reason"] = default_reason
        diagnostics["stream_miss_symbol"] = symbol
        helper = getattr(stream_service, "get_open_orders_stream_diagnostics", None)
        if not callable(helper):
            diagnostics["stream_miss_reason"] = default_reason
            return
        try:
            miss_state = helper(symbol=symbol)
        except Exception:
            diagnostics["stream_miss_reason"] = default_reason
            return
        if not isinstance(miss_state, dict):
            diagnostics["stream_miss_reason"] = default_reason
            return
        diagnostics["stream_miss_reason"] = str(
            miss_state.get("miss_reason") or default_reason
        )
        diagnostics["stream_miss_state"] = {
            "symbol": miss_state.get("symbol"),
            "topic_fresh": miss_state.get("topic_fresh"),
            "topic_age_sec": miss_state.get("topic_age_sec"),
            "topic_max_age_sec": miss_state.get("topic_max_age_sec"),
            "topic_source": miss_state.get("topic_source"),
            "topic_bootstrapped": miss_state.get("topic_bootstrapped"),
            "private_connected": miss_state.get("private_connected"),
            "private_authenticated": miss_state.get("private_authenticated"),
            "epoch_matches": miss_state.get("epoch_matches"),
            "all_dirty": miss_state.get("all_dirty"),
            "symbol_dirty": miss_state.get("symbol_dirty"),
            "symbol_bootstrapped": miss_state.get("symbol_bootstrapped"),
            "cache_order_count": miss_state.get("cache_order_count"),
        }

    def _seed_live_open_orders_cache_from_symbol_rows(
        self,
        *,
        symbols: List[str],
        order_rows_by_symbol: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        cached_at = time.monotonic()
        for symbol in symbols or []:
            self._live_open_orders_cache[symbol] = {
                "cached_at": cached_at,
                "orders": list(order_rows_by_symbol.get(symbol) or []),
            }

    def _seed_live_open_orders_all_cache(
        self,
        order_rows: List[Dict[str, Any]],
    ) -> None:
        self._live_open_orders_all_cache = {
            "cached_at": time.monotonic(),
            "orders": [dict(row) for row in list(order_rows or [])],
        }

    def _get_cached_live_all_order_rows(
        self,
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[float]]:
        cached = getattr(self, "_live_open_orders_all_cache", {}) or {}
        cached_at = self._safe_float(cached.get("cached_at"), 0.0)
        order_rows = cached.get("orders")
        if cached_at <= 0.0 or not isinstance(order_rows, list):
            return None, None
        age_sec = max(time.monotonic() - cached_at, 0.0)
        if age_sec >= self._live_open_orders_cache_ttl_seconds:
            return None, None
        return list(order_rows), round(age_sec * 1000.0, 3)

    @staticmethod
    def _group_and_summarize_order_rows_by_symbol(
        *,
        symbols: List[str],
        order_rows: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, List[Dict[str, Any]]], int]:
        summary = {
            symbol: {
                "open_order_count": 0,
                "reduce_only_count": 0,
                "entry_order_count": 0,
            }
            for symbol in (symbols or [])
        }
        grouped_rows_by_symbol = {
            symbol: []
            for symbol in (symbols or [])
        }
        tracked_symbols = set(symbols or [])
        matched_order_row_count = 0
        for order in list(order_rows or []):
            symbol = str((order or {}).get("symbol") or "").strip().upper()
            if symbol not in tracked_symbols:
                continue
            grouped_rows_by_symbol[symbol].append(dict(order or {}))
            matched_order_row_count += 1
            summary_row = summary[symbol]
            summary_row["open_order_count"] += 1
            if bool((order or {}).get("reduceOnly")):
                summary_row["reduce_only_count"] += 1
            else:
                summary_row["entry_order_count"] += 1
        return summary, grouped_rows_by_symbol, matched_order_row_count

    @staticmethod
    def _summarize_order_rows_by_symbol(
        *,
        symbols: List[str],
        order_rows: Optional[List[Dict[str, Any]]] = None,
        order_rows_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Dict[str, int]]:
        summary = {
            symbol: {
                "open_order_count": 0,
                "reduce_only_count": 0,
                "entry_order_count": 0,
            }
            for symbol in (symbols or [])
        }
        if order_rows_by_symbol is not None:
            for symbol in symbols or []:
                for order in list((order_rows_by_symbol.get(symbol) or [])):
                    summary_row = summary[symbol]
                    summary_row["open_order_count"] += 1
                    if bool(order.get("reduceOnly")):
                        summary_row["reduce_only_count"] += 1
                    else:
                        summary_row["entry_order_count"] += 1
            return summary

        grouped_summary, _, _ = BotStatusService._group_and_summarize_order_rows_by_symbol(
            symbols=symbols,
            order_rows=list(order_rows or []),
        )
        return grouped_summary

    def get_last_runtime_cache_status(self) -> Dict[str, Any]:
        return dict(self._last_runtime_cache_status)

    def get_runtime_positions_payload(
        self,
        *,
        skip_cache: bool = False,
    ) -> Dict[str, Any]:
        return self._get_runtime_positions_payload(skip_cache=skip_cache)

    def _get_runtime_positions_payload(
        self,
        *,
        skip_cache: bool = False,
    ) -> Dict[str, Any]:
        client = getattr(self.position_service, "client", None)
        if client is None:
            return self.position_service.get_positions(skip_cache=skip_cache)

        if not skip_cache:
            stream_service = getattr(client, "stream_service", None)
            if stream_service is not None and hasattr(stream_service, "get_positions_fresh"):
                stream_response = stream_service.get_positions_fresh()
                if stream_response and stream_response.get("success"):
                    payload = self._normalize_runtime_positions_response(stream_response)
                    payload["stale_data"] = False
                    self._runtime_positions_cache = {
                        "payload": payload,
                        "cached_at": time.monotonic(),
                    }
                    self._last_runtime_cache_status = {
                        "stale_data": False,
                        "error": None,
                    }
                    return payload
                cached_payload = dict(self._runtime_positions_cache.get("payload") or {})
                if cached_payload:
                    cached_payload["stale_data"] = True
                    cached_payload.setdefault("error", "private_positions_stale")
                    self._last_runtime_cache_status = {
                        "stale_data": True,
                        "error": cached_payload.get("error"),
                    }
                    return cached_payload
                stale_payload = {
                    "positions": [],
                    "summary": {},
                    "error": "private_positions_stale",
                    "stale_data": True,
                }
                self._last_runtime_cache_status = {
                    "stale_data": True,
                    "error": stale_payload["error"],
                }
                return stale_payload

        response = client.get_positions(skip_cache=skip_cache)
        if not response.get("success"):
            payload = {
                "positions": [],
                "summary": {},
                "error": response.get("error"),
                "stale_data": not skip_cache,
            }
            self._last_runtime_cache_status = {
                "stale_data": bool(payload.get("stale_data")),
                "error": payload.get("error"),
            }
            return payload

        raw_positions = ((response.get("data") or {}).get("list") or [])
        payload = self._normalize_runtime_positions_rows(raw_positions)
        payload["stale_data"] = False
        self._runtime_positions_cache = {
            "payload": payload,
            "cached_at": time.monotonic(),
        }
        self._last_runtime_cache_status = {
            "stale_data": False,
            "error": None,
        }
        return payload

    def _normalize_runtime_positions_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        raw_positions = ((response.get("data") or {}).get("list") or [])
        payload = self._normalize_runtime_positions_rows(raw_positions)
        payload["error"] = response.get("error")
        return payload

    def _normalize_runtime_positions_rows(
        self,
        raw_positions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        positions = []
        longs = 0
        shorts = 0
        total_unrealized_pnl = 0.0
        for raw_position in raw_positions:
            normalized = None
            if hasattr(self.position_service, "normalize_position_row"):
                try:
                    normalized = self.position_service.normalize_position_row(
                        raw_position,
                        account_equity=0.0,
                    )
                except Exception:
                    normalized = None

            if normalized is None:
                size = self._safe_float(raw_position.get("size"), 0.0)
                if size <= 0:
                    continue
                side = str(raw_position.get("side") or "").strip()
                mark_price = self._safe_float(raw_position.get("markPrice"))
                liq_price = self._safe_float(raw_position.get("liqPrice"))
                pct_to_liq = None
                if liq_price > 0 and mark_price > 0:
                    pct_to_liq = abs(mark_price - liq_price) / mark_price * 100
                leverage = self._safe_float(raw_position.get("leverage"), 0.0)
                normalized = {
                    "symbol": raw_position.get("symbol", ""),
                    "side": side,
                    "size": size,
                    "position_idx": int(raw_position.get("positionIdx", 0) or 0),
                    "entry_price": self._safe_float(raw_position.get("avgPrice")),
                    "mark_price": mark_price,
                    "liq_price": liq_price or None,
                    "pct_to_liq": round(pct_to_liq, 2) if pct_to_liq is not None else None,
                    "margin": self._safe_float(raw_position.get("positionIM")) or None,
                    "leverage": round(leverage, 2) if leverage > 0 else None,
                    "unrealized_pnl": self._safe_float(
                        raw_position.get("unrealisedPnl"),
                        0.0,
                    ),
                    "realized_pnl": self._safe_float(raw_position.get("curRealisedPnl")),
                    "position_value": self._safe_float(raw_position.get("positionValue")) or None,
                    "take_profit": self._safe_float(raw_position.get("takeProfit")) or None,
                    "stop_loss": self._safe_float(raw_position.get("stopLoss")) or None,
                }

            side = str(normalized.get("side") or "").strip()
            if side == "Buy":
                longs += 1
            elif side == "Sell":
                shorts += 1
            unrealized_pnl = self._safe_float(normalized.get("unrealized_pnl"), 0.0)
            total_unrealized_pnl += unrealized_pnl
            positions.append(dict(normalized))

        return {
            "positions": positions,
            "summary": {
                "total_positions": len(positions),
                "longs": longs,
                "shorts": shorts,
                "total_unrealized_pnl": round(total_unrealized_pnl, 4),
            },
            "error": None,
        }

    def _enrich_bot(
        self,
        bot: Dict[str, Any],
        position_lookup: Dict[str, Dict[str, Any]],
        positions_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        symbol_pnl_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        bot_pnl_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        running_bot_ids_by_symbol: Optional[Dict[str, List[str]]] = None,
        scanner_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        live_open_orders_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        stopped_preview_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Enrich a single bot with position and status data.

        Args:
            bot: Bot dictionary from storage
            position_lookup: Dictionary of positions by symbol
            symbol_pnl_lookup: Optional dictionary of symbol cumulative PnL data
            bot_pnl_lookup: Optional dictionary of bot-specific PnL data

        Returns:
            Enriched bot dictionary
        """
        symbol = bot.get("symbol", "")
        bot_id = bot.get("id", "")
        status = bot.get("status", "stopped")
        symbol_pnl_lookup = symbol_pnl_lookup or {}
        bot_pnl_lookup = bot_pnl_lookup or {}
        positions_by_symbol = positions_by_symbol or {}
        running_bot_ids_by_symbol = running_bot_ids_by_symbol or {}
        scanner_lookup = scanner_lookup or {}
        live_open_orders_by_symbol = live_open_orders_by_symbol or {}
        scanner_recommendation = scanner_lookup.get(symbol) or {}
        scanner_recommended_mode = scanner_recommendation.get("recommended_mode")
        scanner_recommended_range_mode = scanner_recommendation.get(
            "recommended_range_mode"
        )
        scanner_recommended_profile = scanner_recommendation.get(
            "recommended_profile"
        )
        auto_pilot_enabled = bool(bot.get("auto_pilot", False))
        auto_pilot_universe_mode = (
            normalize_auto_pilot_universe_mode(bot.get("auto_pilot_universe_mode"))
            if auto_pilot_enabled
            else bot.get("auto_pilot_universe_mode")
        )
        auto_pilot_universe_summary = bot.get("auto_pilot_universe_summary")
        if auto_pilot_enabled and not auto_pilot_universe_summary:
            auto_pilot_universe_summary = f"mode={auto_pilot_universe_mode}"
        configured_bot_mode = configured_mode(bot)
        configured_bot_range_mode = configured_range_mode(bot)
        effective_runtime_mode = normalize_bot_mode(
            bot.get("effective_runtime_mode") or configured_bot_mode
        )
        effective_runtime_range_mode = normalize_range_mode(
            bot.get("effective_runtime_range_mode") or configured_bot_range_mode
        )
        mode_policy = normalize_mode_policy(bot.get("mode_policy"), bot)
        scanner_recommendation_differs = bool(
            scanner_recommended_mode
            and (
                str(scanner_recommended_mode) != str(configured_bot_mode or "")
                or str(scanner_recommended_range_mode or "")
                != str(configured_bot_range_mode or "")
            )
        )
        entry_gate_bot_enabled = bool(bot.get("entry_gate_enabled", True))
        entry_gate_global_master_applicable = str(
            configured_bot_mode or ""
        ).strip().lower() in {"long", "short"}
        entry_gate_global_master_enabled = (
            bool(getattr(strategy_cfg, "ENTRY_GATE_ENABLED", False))
            if entry_gate_global_master_applicable
            else True
        )
        entry_gate_contract_active = bool(
            entry_gate_bot_enabled and entry_gate_global_master_enabled
        )
        raw_entry_signal_preferred = bool(bot.get("entry_signal_preferred", False))
        raw_entry_signal_executable = bool(bot.get("entry_signal_executable", False))
        effective_entry_signal_preferred = bool(
            raw_entry_signal_preferred and entry_gate_contract_active
        )
        effective_entry_signal_executable = bool(
            raw_entry_signal_executable and entry_gate_contract_active
        )

        # Only attribute a live exchange position when a single active bot owns
        # that symbol. Paused/recovering bots can still hold a real position,
        # so status alone is not enough to treat them as flat.
        position = {}
        symbol_position = position_lookup.get(symbol, {}) if symbol in position_lookup else {}
        symbol_positions = positions_by_symbol.get(symbol, [])
        multi_leg_symbol_position = len(symbol_positions) > 1
        live_position_attribution = "none"
        running_bot_ids = [
            candidate for candidate in running_bot_ids_by_symbol.get(symbol, []) if candidate
        ]
        if multi_leg_symbol_position:
            if len(running_bot_ids) == 1 and running_bot_ids[0] == bot_id:
                live_position_attribution = "symbol_multi_leg"
                # Use the largest leg as the primary position reference
                # so position_size, entry_price, mark_price are populated.
                best_leg = max(
                    symbol_positions,
                    key=lambda p: abs(float((p or {}).get("size") or 0)),
                    default={},
                )
                if best_leg:
                    position = best_leg
            elif len(running_bot_ids) > 1:
                live_position_attribution = "ambiguous_symbol"
        elif symbol in position_lookup:
            if len(running_bot_ids) == 1 and running_bot_ids[0] == bot_id:
                position = position_lookup.get(symbol, {})
                live_position_attribution = "unique_running_bot"
            elif len(running_bot_ids) > 1:
                live_position_attribution = "ambiguous_symbol"

        position_size = position.get("size", 0.0)
        position_side = position.get("side", "")
        position_unrealized_pnl = position.get("unrealized_pnl", 0.0)
        symbol_position_size = symbol_position.get("size", 0.0)
        symbol_position_side = symbol_position.get("side", "")
        symbol_position_unrealized_pnl = symbol_position.get("unrealized_pnl", 0.0)
        symbol_position_unrealized_pnl_total = sum(
            float((candidate or {}).get("unrealized_pnl") or 0.0)
            for candidate in symbol_positions
        )

        # Get realized_pnl from bot (persisted in bots.json by PnlService.update_bots_realized_pnl)
        realized_pnl = float(bot.get("realized_pnl") or 0.0)

        # Use position unrealized PnL if available, otherwise bot's stored value
        # For stopped bots with no live position, unrealized is definitionally zero
        if live_position_attribution == "ambiguous_symbol":
            unrealized_pnl = 0.0
        elif live_position_attribution == "symbol_multi_leg":
            unrealized_pnl = symbol_position_unrealized_pnl_total
        elif position_size > 0:
            unrealized_pnl = float(position_unrealized_pnl or 0.0)
        elif bot.get("status") in ("stopped", "risk_stopped"):
            unrealized_pnl = 0.0
        else:
            unrealized_pnl = float(bot.get("unrealized_pnl") or 0.0)

        total_pnl = realized_pnl + unrealized_pnl

        # Get range mode and width
        range_mode = configured_bot_range_mode
        last_range_width_pct = bot.get("last_range_width_pct")

        # Get TP% from bot
        tp_pct = bot.get("tp_pct")
        try:
            tp_pct = float(tp_pct) if tp_pct is not None else None
        except (TypeError, ValueError):
            tp_pct = None

        # Compute PnL% on invested capital so it matches TP% semantics.
        investment = self._safe_float(bot.get("investment"), 0.0)
        pnl_pct = total_pnl / investment if investment > 0 else 0.0
        position_profit_pct = self._calculate_position_profit_pct(
            position_side=position_side,
            entry_price=self._safe_float(position.get("entry_price"), 0.0),
            mark_price=self._safe_float(position.get("mark_price"), 0.0),
            position_size=self._safe_float(position_size, 0.0),
        )

        # Runtime / earnings per hour
        runtime_hours = 0.0
        profit_per_hour = None
        session_realized_pnl = 0.0
        session_total_pnl = 0.0
        session_profit_per_hour = None

        # Get accumulated runtime from previous sessions
        accumulated_hours = float(bot.get("accumulated_runtime_hours") or 0.0)

        # Calculate current session runtime ONLY if bot is actively running
        session_hours = 0.0
        started_at = bot.get("started_at")
        bot_status = bot.get("status", "stopped")

        # Only count session time if bot is currently running
        if bot_status == "running" and started_at:
            try:
                started_dt = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                )
                curr_dt = datetime.now(timezone.utc)
                session_seconds = max((curr_dt - started_dt).total_seconds(), 0)
                session_hours = session_seconds / 3600.0
            except Exception:
                session_hours = 0.0

        # Total runtime = accumulated (from past sessions) + current session
        runtime_hours = accumulated_hours + session_hours

        if runtime_hours > 0:
            if runtime_hours >= MIN_RUNTIME_FOR_RATE_HOURS:
                profit_per_hour = total_pnl / runtime_hours
        else:
            runtime_hours = None  # Keep None if 0 for consistency with UI checks

        session_realized_baseline = self._safe_float(
            bot.get("tp_session_realized_baseline"), realized_pnl
        )
        if bot_status in {"running", "recovering"}:
            session_realized_pnl = realized_pnl - session_realized_baseline
            session_total_pnl = session_realized_pnl + unrealized_pnl
            if session_hours >= MIN_RUNTIME_FOR_RATE_HOURS:
                session_profit_per_hour = session_total_pnl / session_hours

        now_dt = datetime.now(timezone.utc)
        session_timer_start_at = bot.get("session_start_at")
        session_timer_stop_at = bot.get("session_stop_at")
        session_timer_pre_stop_at = bot.get("session_timer_pre_stop_at")
        session_timer_grace_expires_at = bot.get("session_timer_grace_expires_at")
        session_timer_start_dt = self._parse_iso_datetime(session_timer_start_at)
        session_timer_stop_dt = self._parse_iso_datetime(session_timer_stop_at)
        session_timer_pre_stop_dt = self._parse_iso_datetime(session_timer_pre_stop_at)
        session_timer_grace_expires_dt = self._parse_iso_datetime(
            session_timer_grace_expires_at
        )
        session_timer_state = str(
            bot.get("session_timer_state") or "inactive"
        ).strip().lower() or "inactive"
        session_timer_running = session_timer_state in {
            "running",
            "pre_stop_no_new_entries",
            "grace_active",
        }
        session_timer_complete = session_timer_state == "completed"
        session_timer_no_new_entries_active = bool(
            bot.get("session_timer_no_new_entries_active")
            or bot.get("_session_timer_block_opening_orders")
        )

        def _remaining_seconds(target_dt: Optional[datetime]) -> Optional[int]:
            if target_dt is None:
                return None
            return max(int((target_dt - now_dt).total_seconds()), 0)

        session_timer_starts_in_sec = (
            _remaining_seconds(session_timer_start_dt)
            if session_timer_start_dt and now_dt < session_timer_start_dt
            else 0
            if session_timer_running and session_timer_start_dt
            else None
        )
        session_timer_stops_in_sec = (
            _remaining_seconds(session_timer_stop_dt)
            if session_timer_stop_dt is not None
            else None
        )
        session_timer_pre_stop_in_sec = (
            _remaining_seconds(session_timer_pre_stop_dt)
            if session_timer_pre_stop_dt is not None
            else None
        )
        session_timer_grace_remaining_sec = (
            _remaining_seconds(session_timer_grace_expires_dt)
            if session_timer_grace_expires_dt is not None
            else None
        )

        # Lifetime earnings since creation
        # For stopped bots, freeze lifetime at last_run_at or updated_at
        # so the timer doesn't keep incrementing after the bot stops
        lifetime_hours = None
        lifetime_profit_per_hour = None
        lifetime_pnl = realized_pnl  # realized_pnl is cumulative for the bot
        created_at = bot.get("created_at")
        if created_at:
            try:
                created_dt = datetime.fromisoformat(
                    str(created_at).replace("Z", "+00:00")
                )
                # Use appropriate end time based on bot status
                if bot_status == "running":
                    end_dt = datetime.now(timezone.utc)
                else:
                    # For stopped bots, prefer an explicit stop/control timestamp.
                    # updated_at can drift after stop when stale runtime saves land.
                    end_at = (
                        bot.get("last_run_at")
                        or bot.get("control_updated_at")
                        or bot.get("updated_at")
                    )
                    if end_at:
                        end_dt = datetime.fromisoformat(
                            str(end_at).replace("Z", "+00:00")
                        )
                    else:
                        end_dt = created_dt  # fallback: no runtime
                lifetime_seconds = max(
                    (end_dt - created_dt).total_seconds(), 0
                )
                lifetime_hours = lifetime_seconds / 3600 if lifetime_seconds else 0
                if lifetime_hours and lifetime_hours >= MIN_RUNTIME_FOR_RATE_HOURS:
                    lifetime_profit_per_hour = lifetime_pnl / lifetime_hours
            except Exception:
                lifetime_hours = None
                lifetime_profit_per_hour = None

        live_order_counts = self._get_live_bot_order_counts(
            bot,
            live_open_orders_by_symbol,
        )
        if live_order_counts is not None:
            entry_orders_open = int(live_order_counts.get("entry_orders_open", 0) or 0)
            exit_orders_open = int(live_order_counts.get("exit_orders_open", 0) or 0)
            open_order_count = int(live_order_counts.get("open_order_count", 0) or 0)
        else:
            entry_orders_open = int(bot.get("entry_orders_open", 0) or 0)
            exit_orders_open = int(bot.get("exit_orders_open", 0) or 0)
            open_order_count = entry_orders_open + exit_orders_open
            if open_order_count <= 0:
                open_order_count = int(bot.get("open_order_count", 0) or 0)
        runtime_open_order_cap_total = int(
            self._safe_float(bot.get("runtime_open_order_cap_total"), 0)
        )
        volatility_derisk_open_cap_total = int(
            self._safe_float(bot.get("volatility_derisk_open_cap_total"), 0)
        )
        scalp_learned_opening_order_cap = int(
            self._safe_float(bot.get("scalp_learned_opening_order_cap"), 0)
        )
        effective_opening_order_cap = runtime_open_order_cap_total
        effective_opening_order_cap_reason = None
        if effective_opening_order_cap <= 0:
            effective_opening_order_cap = int(
                self._safe_float(bot.get("grid_count"), 0)
            )
        if (
            scalp_learned_opening_order_cap > 0
            and (
                effective_opening_order_cap <= 0
                or scalp_learned_opening_order_cap < effective_opening_order_cap
            )
        ):
            effective_opening_order_cap = scalp_learned_opening_order_cap
            effective_opening_order_cap_reason = (
                bot.get("scalp_learned_opening_cap_reason") or "learned_cap"
            )
        elif volatility_derisk_open_cap_total > 0 and (
            effective_opening_order_cap <= 0
            or volatility_derisk_open_cap_total < effective_opening_order_cap
        ):
            effective_opening_order_cap = volatility_derisk_open_cap_total
            effective_opening_order_cap_reason = "volatility_derisk"

        price_action_direction = None
        price_action_score = None
        price_action_summary = None
        price_action_mode_fit_score = None
        price_action_mode_fit_summary = None
        price_action_service = getattr(self, "price_action_service", None)
        if (
            price_action_service
            and symbol
            and status in ACTIVE_POSITION_OWNER_STATUSES
            and str(symbol).strip().upper() != "AUTO-PILOT"
        ):
            try:
                context_price = (
                    self._safe_float(bot.get("current_price"), 0.0)
                    or self._safe_float(symbol_position.get("mark_price"), 0.0)
                    or self._safe_float(position.get("mark_price"), 0.0)
                    or None
                )
                price_action_context = price_action_service.analyze(
                    symbol=symbol,
                    current_price=context_price,
                )
                price_action_mode_fit = price_action_service.score_mode_fit(
                    context=price_action_context,
                    mode=configured_bot_mode,
                )
                price_action_direction = price_action_context.get("direction")
                price_action_score = self._safe_float(
                    price_action_context.get("net_score"), 0.0
                )
                price_action_summary = price_action_context.get("summary")
                price_action_mode_fit_score = self._safe_float(
                    price_action_mode_fit.get("score"), 0.0
                )
                price_action_mode_fit_summary = price_action_mode_fit.get("summary")
            except Exception:
                price_action_direction = None
                price_action_score = None
                price_action_summary = None
                price_action_mode_fit_score = None
                price_action_mode_fit_summary = None

        entry_readiness = self._get_entry_readiness(
            bot=bot,
            symbol_position=symbol_position,
            position=position,
            price_action_context={
                "direction": price_action_direction,
                "score": price_action_score,
                "summary": price_action_summary,
                "mode_fit_score": price_action_mode_fit_score,
                "mode_fit_summary": price_action_mode_fit_summary,
            },
            stopped_preview_lookup=stopped_preview_lookup,
        )
        self._maybe_emit_signal_drift_watchdog(bot, entry_readiness)
        capital_starved_visible = self._capital_starved_runtime_visible(
            bot,
            entry_readiness,
        )
        configured_setup_status = str(
            entry_readiness.get("setup_timing_status")
            or entry_readiness.get("setup_ready_status")
            or entry_readiness.get("analysis_ready_status")
            or entry_readiness.get("entry_ready_status")
            or ""
        ).strip().lower()
        alternative_mode_summary = {"available": False}
        if (
            symbol
            and str(symbol).strip().upper() != "AUTO-PILOT"
            and configured_setup_status != "trigger_ready"
        ):
            mode_readiness_matrix = self._build_mode_readiness_matrix(
                {
                    **bot,
                    "configured_mode": configured_bot_mode,
                    "configured_range_mode": configured_bot_range_mode,
                    "effective_runtime_mode": effective_runtime_mode,
                    "effective_runtime_range_mode": effective_runtime_range_mode,
                    "mode_policy": mode_policy,
                },
                configured_readiness=entry_readiness,
                scanner_recommended_mode=scanner_recommended_mode,
            )
            alternative_mode_summary = self._build_alternative_mode_summary(
                mode_readiness_matrix
            )
        exchange_reconciliation = dict(bot.get("exchange_reconciliation") or {})
        ambiguous_execution_follow_up = dict(
            bot.get("ambiguous_execution_follow_up") or {}
        )

        # Build enriched bot dict
        enriched = {
            # Core identification
            "id": bot.get("id"),
            "symbol": symbol,
            "mode": configured_bot_mode,
            "configured_mode": configured_bot_mode,
            "configured_range_mode": configured_bot_range_mode,
            "effective_runtime_mode": effective_runtime_mode,
            "effective_runtime_range_mode": effective_runtime_range_mode,
            "runtime_mode_source": bot.get("runtime_mode_source"),
            "runtime_mode_non_persistent": bool(
                bot.get("runtime_mode_non_persistent", False)
            ),
            "runtime_mode_updated_at": bot.get("runtime_mode_updated_at"),
            "mode_policy": mode_policy,
            "status": status,
            # Profile and auto-direction
            "profile": bot.get("profile", "normal"),
            "auto_pilot": auto_pilot_enabled,
            "auto_direction": bool(bot.get("auto_direction", False)),
            # Range mode
            "range_mode": range_mode,
            "last_range_width_pct": last_range_width_pct,
            "scanner_recommended_mode": scanner_recommended_mode,
            "scanner_recommended_range_mode": scanner_recommended_range_mode,
            "scanner_recommended_profile": scanner_recommended_profile,
            "scanner_recommendation_differs": scanner_recommendation_differs,
            "scanner_recommendation_updated_at": scanner_recommendation.get(
                "updated_at"
            ),
            "scanner_recommendation_regime": scanner_recommendation.get("regime"),
            "scanner_recommendation_trend": scanner_recommendation.get("trend"),
            "price_action_direction": price_action_direction,
            "price_action_score": price_action_score,
            "price_action_summary": price_action_summary,
            "price_action_mode_fit_score": price_action_mode_fit_score,
            "price_action_mode_fit_summary": price_action_mode_fit_summary,
            "entry_ready_status": entry_readiness.get("entry_ready_status"),
            "entry_ready_reason": entry_readiness.get("entry_ready_reason"),
            "entry_ready_reason_text": entry_readiness.get(
                "entry_ready_reason_text"
            ),
            "entry_ready_detail": entry_readiness.get("entry_ready_detail"),
            "entry_ready_score": entry_readiness.get("entry_ready_score"),
            "entry_ready_direction": entry_readiness.get("entry_ready_direction"),
            "entry_ready_mode": entry_readiness.get("entry_ready_mode"),
            "entry_ready_updated_at": entry_readiness.get("entry_ready_updated_at"),
            "entry_ready_source": entry_readiness.get("entry_ready_source"),
            "entry_ready_age_sec": entry_readiness.get("entry_ready_age_sec"),
            "analysis_ready_status": entry_readiness.get("analysis_ready_status"),
            "analysis_ready_reason": entry_readiness.get("analysis_ready_reason"),
            "analysis_ready_reason_text": entry_readiness.get(
                "analysis_ready_reason_text"
            ),
            "analysis_ready_detail": entry_readiness.get("analysis_ready_detail"),
            "analysis_ready_score": entry_readiness.get("analysis_ready_score"),
            "analysis_ready_direction": entry_readiness.get("analysis_ready_direction"),
            "analysis_ready_mode": entry_readiness.get("analysis_ready_mode"),
            "analysis_ready_updated_at": entry_readiness.get(
                "analysis_ready_updated_at"
            ),
            "analysis_ready_source": entry_readiness.get("analysis_ready_source"),
            "analysis_ready_age_sec": entry_readiness.get("analysis_ready_age_sec"),
            "analysis_ready_severity": entry_readiness.get(
                "analysis_ready_severity"
            ),
            "analysis_ready_next": entry_readiness.get("analysis_ready_next"),
            "analysis_ready_fallback_used": bool(
                entry_readiness.get("analysis_ready_fallback_used", False)
            ),
            "analysis_ready_fallback_reason": entry_readiness.get(
                "analysis_ready_fallback_reason"
            ),
            "analysis_ready_fallback_source": entry_readiness.get(
                "analysis_ready_fallback_source"
            ),
            "analysis_timing_status": entry_readiness.get("analysis_timing_status"),
            "analysis_timing_reason": entry_readiness.get("analysis_timing_reason"),
            "analysis_timing_reason_text": entry_readiness.get(
                "analysis_timing_reason_text"
            ),
            "analysis_timing_detail": entry_readiness.get("analysis_timing_detail"),
            "analysis_timing_next": entry_readiness.get("analysis_timing_next"),
            "analysis_timing_score": entry_readiness.get("analysis_timing_score"),
            "analysis_timing_direction": entry_readiness.get(
                "analysis_timing_direction"
            ),
            "analysis_timing_mode": entry_readiness.get("analysis_timing_mode"),
            "analysis_timing_updated_at": entry_readiness.get(
                "analysis_timing_updated_at"
            ),
            "analysis_timing_source": entry_readiness.get("analysis_timing_source"),
            "analysis_timing_actionable": bool(
                entry_readiness.get("analysis_timing_actionable", False)
            ),
            "analysis_timing_near_trigger": bool(
                entry_readiness.get("analysis_timing_near_trigger", False)
            ),
            "analysis_timing_late": bool(
                entry_readiness.get("analysis_timing_late", False)
            ),
            "setup_ready": bool(entry_readiness.get("setup_ready", False)),
            "setup_timing_status": entry_readiness.get("setup_timing_status"),
            "setup_timing_reason": entry_readiness.get("setup_timing_reason"),
            "setup_timing_reason_text": entry_readiness.get(
                "setup_timing_reason_text"
            ),
            "setup_timing_detail": entry_readiness.get("setup_timing_detail"),
            "setup_timing_next": entry_readiness.get("setup_timing_next"),
            "setup_timing_score": entry_readiness.get("setup_timing_score"),
            "setup_timing_direction": entry_readiness.get("setup_timing_direction"),
            "setup_timing_mode": entry_readiness.get("setup_timing_mode"),
            "setup_timing_updated_at": entry_readiness.get(
                "setup_timing_updated_at"
            ),
            "setup_timing_source": entry_readiness.get("setup_timing_source"),
            "setup_timing_actionable": bool(
                entry_readiness.get("setup_timing_actionable", False)
            ),
            "setup_timing_near_trigger": bool(
                entry_readiness.get("setup_timing_near_trigger", False)
            ),
            "setup_timing_late": bool(entry_readiness.get("setup_timing_late", False)),
            "raw_readiness_stage": entry_readiness.get("raw_readiness_stage"),
            "raw_readiness_reason": entry_readiness.get("raw_readiness_reason"),
            "raw_readiness_reason_text": entry_readiness.get(
                "raw_readiness_reason_text"
            ),
            "raw_readiness_detail": entry_readiness.get("raw_readiness_detail"),
            "stable_readiness_stage": entry_readiness.get("stable_readiness_stage"),
            "stable_readiness_reason": entry_readiness.get("stable_readiness_reason"),
            "stable_readiness_reason_text": entry_readiness.get(
                "stable_readiness_reason_text"
            ),
            "stable_readiness_detail": entry_readiness.get(
                "stable_readiness_detail"
            ),
            "stable_readiness_next": entry_readiness.get("stable_readiness_next"),
            "stable_readiness_updated_at": entry_readiness.get(
                "stable_readiness_updated_at"
            ),
            "stable_readiness_actionable": bool(
                entry_readiness.get("stable_readiness_actionable", False)
            ),
            "stable_readiness_near_trigger": bool(
                entry_readiness.get("stable_readiness_near_trigger", False)
            ),
            "stable_readiness_late": bool(
                entry_readiness.get("stable_readiness_late", False)
            ),
            "readiness_stability_state": entry_readiness.get(
                "readiness_stability_state"
            ),
            "readiness_stability_policy": entry_readiness.get(
                "readiness_stability_policy"
            ),
            "readiness_stable_since": entry_readiness.get("readiness_stable_since"),
            "readiness_hold_until": entry_readiness.get("readiness_hold_until"),
            "readiness_flip_suppressed": bool(
                entry_readiness.get("readiness_flip_suppressed", False)
            ),
            "readiness_hard_invalidated": bool(
                entry_readiness.get("readiness_hard_invalidated", False)
            ),
            "setup_ready_status": entry_readiness.get("setup_ready_status"),
            "setup_ready_reason": entry_readiness.get("setup_ready_reason"),
            "setup_ready_reason_text": entry_readiness.get(
                "setup_ready_reason_text"
            ),
            "setup_ready_detail": entry_readiness.get("setup_ready_detail"),
            "setup_ready_score": entry_readiness.get("setup_ready_score"),
            "setup_ready_direction": entry_readiness.get("setup_ready_direction"),
            "setup_ready_mode": entry_readiness.get("setup_ready_mode"),
            "setup_ready_updated_at": entry_readiness.get(
                "setup_ready_updated_at"
            ),
            "setup_ready_age_sec": entry_readiness.get("setup_ready_age_sec"),
            "setup_ready_source": entry_readiness.get("setup_ready_source"),
            "setup_ready_severity": entry_readiness.get("setup_ready_severity"),
            "setup_ready_next": entry_readiness.get("setup_ready_next"),
            "setup_ready_fallback_used": bool(
                entry_readiness.get("setup_ready_fallback_used", False)
            ),
            "setup_ready_fallback_reason": entry_readiness.get(
                "setup_ready_fallback_reason"
            ),
            "setup_ready_fallback_source": entry_readiness.get(
                "setup_ready_fallback_source"
            ),
            "execution_blocked": bool(entry_readiness.get("execution_blocked", False)),
            "execution_viability_status": entry_readiness.get(
                "execution_viability_status"
            ),
            "execution_viability_reason": entry_readiness.get(
                "execution_viability_reason"
            ),
            "execution_viability_reason_text": entry_readiness.get(
                "execution_viability_reason_text"
            ),
            "execution_viability_bucket": entry_readiness.get(
                "execution_viability_bucket"
            ),
            "execution_margin_limited": bool(
                entry_readiness.get("execution_margin_limited", False)
            ),
            "execution_viability_detail": entry_readiness.get(
                "execution_viability_detail"
            ),
            "execution_viability_source": entry_readiness.get(
                "execution_viability_source"
            ),
            "execution_viability_diagnostic_reason": entry_readiness.get(
                "execution_viability_diagnostic_reason"
            ),
            "execution_viability_diagnostic_text": entry_readiness.get(
                "execution_viability_diagnostic_text"
            ),
            "execution_viability_diagnostic_detail": entry_readiness.get(
                "execution_viability_diagnostic_detail"
            ),
            "execution_viability_stale_data": bool(
                entry_readiness.get("execution_viability_stale_data", False)
            ),
            "execution_available_margin_usdt": entry_readiness.get(
                "execution_available_margin_usdt"
            ),
            "execution_required_margin_usdt": entry_readiness.get(
                "execution_required_margin_usdt"
            ),
            "execution_order_notional_usdt": entry_readiness.get(
                "execution_order_notional_usdt"
            ),
            "execution_viability_updated_at": entry_readiness.get(
                "execution_viability_updated_at"
            ),
            "execution_viability_age_sec": entry_readiness.get(
                "execution_viability_age_sec"
            ),
            "readiness_source_kind": entry_readiness.get("readiness_source_kind"),
            "readiness_source_age_sec": entry_readiness.get(
                "readiness_source_age_sec"
            ),
            "readiness_fallback_used": bool(
                entry_readiness.get("readiness_fallback_used", False)
            ),
            "market_data_ts": entry_readiness.get("market_data_ts"),
            "market_data_at": entry_readiness.get("market_data_at"),
            "market_data_age_ms": entry_readiness.get("market_data_age_ms"),
            "market_data_source": entry_readiness.get("market_data_source"),
            "market_data_transport": entry_readiness.get("market_data_transport"),
            "market_data_ts_source": entry_readiness.get("market_data_ts_source"),
            "market_data_price": entry_readiness.get("market_data_price"),
            "bot_current_price_at": entry_readiness.get("bot_current_price_at"),
            "bot_current_price_source": entry_readiness.get(
                "bot_current_price_source"
            ),
            "market_provider_at": entry_readiness.get("market_provider_at"),
            "market_provider_source": entry_readiness.get(
                "market_provider_source"
            ),
            "market_provider_transport": entry_readiness.get(
                "market_provider_transport"
            ),
            "market_provider_age_ms": entry_readiness.get("market_provider_age_ms"),
            "ticker_provider_updated_at": entry_readiness.get(
                "ticker_provider_updated_at"
            ),
            "ticker_provider_age_ms": entry_readiness.get("ticker_provider_age_ms"),
            "ticker_used_at_eval": entry_readiness.get("ticker_used_at_eval"),
            "fresher_ticker_available": entry_readiness.get(
                "fresher_ticker_available"
            ),
            "market_data_refreshed_just_in_time": entry_readiness.get(
                "market_data_refreshed_just_in_time"
            ),
            "market_data_refresh_reason": entry_readiness.get(
                "market_data_refresh_reason"
            ),
            "market_data_refresh_delta_ms": entry_readiness.get(
                "market_data_refresh_delta_ms"
            ),
            "market_to_readiness_eval_start_ms": entry_readiness.get(
                "market_to_readiness_eval_start_ms"
            ),
            "market_to_readiness_eval_finished_ms": entry_readiness.get(
                "market_to_readiness_eval_finished_ms"
            ),
            "readiness_evaluated_at": entry_readiness.get("readiness_evaluated_at"),
            "readiness_eval_started_at": entry_readiness.get(
                "readiness_eval_started_at"
            ),
            "readiness_eval_finished_at": entry_readiness.get(
                "readiness_eval_finished_at"
            ),
            "readiness_eval_duration_ms": entry_readiness.get(
                "readiness_eval_duration_ms"
            ),
            "readiness_eval_ms": entry_readiness.get("readiness_eval_ms"),
            "readiness_stage": entry_readiness.get("readiness_stage"),
            "readiness_source": entry_readiness.get("readiness_source"),
            "readiness_generated_at": entry_readiness.get("readiness_generated_at"),
            "readiness_observed_at": entry_readiness.get("readiness_observed_at"),
            "readiness_preview_cached_at": entry_readiness.get(
                "readiness_preview_cached_at"
            ),
            "readiness_preview_age_sec": entry_readiness.get(
                "readiness_preview_age_sec"
            ),
            "readiness_preview_state": entry_readiness.get(
                "readiness_preview_state"
            ),
            "readiness_preview_fresh_ttl_sec": entry_readiness.get(
                "readiness_preview_fresh_ttl_sec"
            ),
            "readiness_preview_refresh_ttl_sec": entry_readiness.get(
                "readiness_preview_refresh_ttl_sec"
            ),
            "readiness_preview_stale_after_sec": entry_readiness.get(
                "readiness_preview_stale_after_sec"
            ),
            "alternative_mode_ready": bool(
                alternative_mode_summary.get("available", False)
            ),
            "alternative_mode": alternative_mode_summary.get("mode"),
            "alternative_mode_range_mode": alternative_mode_summary.get("range_mode"),
            "alternative_mode_label": alternative_mode_summary.get("label"),
            "alternative_mode_status": alternative_mode_summary.get("status"),
            "alternative_mode_stage_status": alternative_mode_summary.get("status"),
            "alternative_mode_reason": alternative_mode_summary.get("reason"),
            "alternative_mode_reason_text": alternative_mode_summary.get(
                "reason_text"
            ),
            "alternative_mode_detail": alternative_mode_summary.get("detail"),
            "alternative_mode_score": alternative_mode_summary.get("score"),
            "alternative_mode_updated_at": alternative_mode_summary.get("updated_at"),
            "alternative_mode_age_sec": alternative_mode_summary.get("age_sec"),
            "alternative_mode_readiness_source_kind": alternative_mode_summary.get(
                "readiness_source_kind"
            ),
            "alternative_mode_preview_state": alternative_mode_summary.get(
                "preview_state"
            ),
            "alternative_mode_execution_blocked": bool(
                alternative_mode_summary.get("execution_blocked", False)
            ),
            "alternative_mode_execution_viability_status": alternative_mode_summary.get(
                "execution_viability_status"
            ),
            "alternative_mode_execution_reason": alternative_mode_summary.get(
                "execution_reason"
            ),
            "alternative_mode_execution_reason_text": alternative_mode_summary.get(
                "execution_reason_text"
            ),
            "alternative_mode_execution_detail": alternative_mode_summary.get(
                "execution_detail"
            ),
            "alternative_mode_actionable": bool(
                alternative_mode_summary.get("actionable", False)
            ),
            "alternative_mode_near_trigger": bool(
                alternative_mode_summary.get("near_trigger", False)
            ),
            "alternative_mode_late": bool(
                alternative_mode_summary.get("late", False)
            ),
            "alternative_mode_is_scanner_suggestion": bool(
                alternative_mode_summary.get("is_scanner_suggestion", False)
            ),
            "alternative_mode_is_runtime_view": bool(
                alternative_mode_summary.get("is_runtime_view", False)
            ),
            "alternative_mode_setup_ready_fallback_used": bool(
                alternative_mode_summary.get("setup_ready_fallback_used", False)
            ),
            "live_gate_status": entry_readiness.get("live_gate_status"),
            "live_gate_reason": entry_readiness.get("live_gate_reason"),
            "live_gate_reason_text": entry_readiness.get("live_gate_reason_text"),
            "live_gate_detail": entry_readiness.get("live_gate_detail"),
            "live_gate_source": entry_readiness.get("live_gate_source"),
            "live_gate_bot_enabled": entry_readiness.get("live_gate_bot_enabled"),
            "live_gate_global_master_applicable": entry_readiness.get(
                "live_gate_global_master_applicable"
            ),
            "live_gate_global_master_enabled": entry_readiness.get(
                "live_gate_global_master_enabled"
            ),
            "live_gate_contract_active": entry_readiness.get(
                "live_gate_contract_active"
            ),
            "live_gate_updated_at": entry_readiness.get("live_gate_updated_at"),
            "entry_signal_code": bot.get("entry_signal_code"),
            "entry_signal_label": bot.get("entry_signal_label"),
            "entry_signal_phase": bot.get("entry_signal_phase"),
            "entry_signal_detail": bot.get("entry_signal_detail"),
            "entry_signal_preferred": effective_entry_signal_preferred,
            "entry_signal_raw_preferred": raw_entry_signal_preferred,
            "entry_signal_effective_preferred": effective_entry_signal_preferred,
            "entry_signal_late": bool(bot.get("entry_signal_late", False)),
            "entry_signal_executable": effective_entry_signal_executable,
            "entry_signal_raw_executable": raw_entry_signal_executable,
            "entry_signal_effective_executable": effective_entry_signal_executable,
            "capital_starved_block_opening_orders": capital_starved_visible,
            "capital_starved_reason": (
                bot.get("capital_starved_reason") if capital_starved_visible else None
            ),
            "capital_starved_warning_text": (
                bot.get("_capital_starved_warning_text")
                if capital_starved_visible
                else None
            ),
            "watchdog_position_cap_active": bool(
                bot.get("_watchdog_position_cap_active", False)
            ),
            "auto_pilot_last_pick_score": bot.get("auto_pilot_last_pick_score"),
            "auto_pilot_last_pick_summary": bot.get("auto_pilot_last_pick_summary"),
            "auto_pilot_last_pick_at": bot.get("auto_pilot_last_pick_at"),
            "auto_pilot_search_status": bot.get("auto_pilot_search_status"),
            "auto_pilot_pick_status": bot.get("auto_pilot_pick_status"),
            "auto_pilot_block_reason": bot.get("auto_pilot_block_reason"),
            "auto_pilot_top_candidate_symbol": bot.get(
                "auto_pilot_top_candidate_symbol"
            ),
            "auto_pilot_top_candidate_score": bot.get("auto_pilot_top_candidate_score"),
            "auto_pilot_top_candidate_mode": bot.get("auto_pilot_top_candidate_mode"),
            "auto_pilot_top_candidate_eligibility": bot.get(
                "auto_pilot_top_candidate_eligibility"
            ),
            "auto_pilot_candidate_source": bot.get("auto_pilot_candidate_source"),
            "ai_advisor_enabled": bool(bot.get("ai_advisor_enabled", False)),
            "ai_advisor_last_status": bot.get("ai_advisor_last_status"),
            "ai_advisor_last_verdict": bot.get("ai_advisor_last_verdict"),
            "ai_advisor_last_confidence": bot.get("ai_advisor_last_confidence"),
            "ai_advisor_last_reasons": bot.get("ai_advisor_last_reasons") or [],
            "ai_advisor_last_risk_note": bot.get("ai_advisor_last_risk_note"),
            "ai_advisor_last_summary": bot.get("ai_advisor_last_summary"),
            "ai_advisor_last_model": bot.get("ai_advisor_last_model"),
            "ai_advisor_last_provider": bot.get("ai_advisor_last_provider"),
            "ai_advisor_last_base_url": bot.get("ai_advisor_last_base_url"),
            "ai_advisor_last_escalated": bool(
                bot.get("ai_advisor_last_escalated", False)
            ),
            "ai_advisor_last_error": bot.get("ai_advisor_last_error"),
            "ai_advisor_last_latency_ms": bot.get("ai_advisor_last_latency_ms"),
            "ai_advisor_last_decision_at": bot.get("ai_advisor_last_decision_at"),
            "ai_advisor_last_decision_type": bot.get(
                "ai_advisor_last_decision_type"
            ),
            "ai_advisor_call_count": int(bot.get("ai_advisor_call_count", 0) or 0),
            "ai_advisor_error_count": int(bot.get("ai_advisor_error_count", 0) or 0),
            "ai_advisor_timeout_count": int(
                bot.get("ai_advisor_timeout_count", 0) or 0
            ),
            "ai_advisor_cached_hits": int(bot.get("ai_advisor_cached_hits", 0) or 0),
            "ai_advisor_total_tokens": int(bot.get("ai_advisor_total_tokens", 0) or 0),
            "auto_pilot_universe_mode": auto_pilot_universe_mode,
            "auto_pilot_universe_summary": auto_pilot_universe_summary,
            # Grid configuration
            "lower_price": self._safe_float(bot.get("lower_price"), 0.0),
            "upper_price": self._safe_float(bot.get("upper_price"), 0.0),
            "grid_count": bot.get("grid_count", 0),
            "investment": self._safe_float(bot.get("investment"), 0.0),
            "leverage": self._safe_float(bot.get("leverage"), 1.0),
            "trailing": bot.get("trailing", False),
            "auto_stop": bot.get("auto_stop"),
            "auto_stop_target_usdt": bot.get("auto_stop_target_usdt", 0),
            "session_timer_enabled": bool(bot.get("session_timer_enabled", False)),
            "session_start_at": session_timer_start_at,
            "session_stop_at": session_timer_stop_at,
            "session_no_new_entries_before_stop_min": int(
                bot.get("session_no_new_entries_before_stop_min", 0) or 0
            ),
            "session_end_mode": bot.get("session_end_mode") or "hard_stop",
            "session_green_grace_min": int(
                bot.get("session_green_grace_min", 0) or 0
            ),
            "session_force_close_max_loss_pct": bot.get(
                "session_force_close_max_loss_pct"
            ),
            "session_cancel_pending_orders_on_end": bool(
                bot.get("session_cancel_pending_orders_on_end", True)
            ),
            "session_reduce_only_on_end": bool(
                bot.get("session_reduce_only_on_end", False)
            ),
            "session_timer_state": session_timer_state,
            "session_timer_running": session_timer_running,
            "session_timer_complete": session_timer_complete,
            "session_timer_no_new_entries_active": session_timer_no_new_entries_active,
            "session_timer_started_at": bot.get("session_timer_started_at"),
            "session_timer_pre_stop_at": session_timer_pre_stop_at,
            "session_timer_end_triggered_at": bot.get(
                "session_timer_end_triggered_at"
            ),
            "session_timer_grace_started_at": bot.get(
                "session_timer_grace_started_at"
            ),
            "session_timer_grace_expires_at": session_timer_grace_expires_at,
            "session_timer_grace_active": session_timer_state == "grace_active",
            "session_timer_grace_remaining_sec": session_timer_grace_remaining_sec,
            "session_timer_completed_at": bot.get("session_timer_completed_at"),
            "session_timer_completed_reason": bot.get(
                "session_timer_completed_reason"
            ),
            "session_timer_starts_in_sec": session_timer_starts_in_sec,
            "session_timer_stops_in_sec": session_timer_stops_in_sec,
            "session_timer_pre_stop_in_sec": session_timer_pre_stop_in_sec,
            "session_timer_reduce_only_active": bool(
                bot.get("session_timer_reduce_only_active", False)
            ),
            # Per-bot safety toggles
            "auto_stop_loss_enabled": bot.get("auto_stop_loss_enabled", True),
            "auto_take_profit_enabled": bot.get("auto_take_profit_enabled", True),
            "trend_protection_enabled": bot.get("trend_protection_enabled", True),
            "danger_zone_enabled": bot.get("danger_zone_enabled", True),
            "auto_neutral_mode_enabled": bot.get("auto_neutral_mode_enabled", True),
            "breakout_confirmed_entry": bool(
                bot.get("breakout_confirmed_entry", False)
            ),
            "breakout_entry_confirmed": bool(
                bot.get("breakout_entry_confirmed", False)
            ),
            "breakout_reference_level": bot.get("breakout_reference_level"),
            "breakout_reference_type": bot.get("breakout_reference_type"),
            "breakout_no_chase_blocked": bool(
                bot.get("breakout_no_chase_blocked", False)
            ),
            "breakout_no_chase_reason": bot.get("breakout_no_chase_reason"),
            "breakout_invalidation_state": bot.get("breakout_invalidation_state"),
            "breakout_invalidation_reason": bot.get("breakout_invalidation_reason"),
            # TP% (take profit percentage)
            "tp_pct": tp_pct,
            # PnL
            "realized_pnl": round(realized_pnl, 4),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "total_pnl": round(total_pnl, 4),
            "session_realized_pnl": round(session_realized_pnl, 4),
            "session_total_pnl": round(session_total_pnl, 4),
            "session_profit_per_hour": (
                round(session_profit_per_hour, 6)
                if session_profit_per_hour is not None
                else None
            ),
            "pnl_pct": round(pnl_pct, 6),
            "position_profit_pct": (
                round(position_profit_pct, 6)
                if position_profit_pct is not None
                else None
            ),
            "runtime_hours": runtime_hours,
            "profit_per_hour": (
                round(profit_per_hour, 6) if profit_per_hour is not None else None
            ),
            "lifetime_hours": lifetime_hours,
            "lifetime_profit_per_hour": (
                round(lifetime_profit_per_hour, 6)
                if lifetime_profit_per_hour is not None
                else None
            ),
            "lifetime_pnl": round(lifetime_pnl, 4),
            # Position info
            "position_size": position_size,
            "position_side": position_side,
            "entry_price": position.get("entry_price", 0.0),
            "mark_price": position.get("mark_price", 0.0),
            "current_price": bot.get("current_price", 0.0),
            "current_price_updated_at": bot.get("current_price_updated_at"),
            "current_price_source": bot.get("current_price_source"),
            "current_price_transport": bot.get("current_price_transport"),
            "current_price_exchange_at": bot.get("current_price_exchange_at"),
            "price_metadata_written_early": bot.get("price_metadata_written_early"),
            "price_metadata_write_reason": bot.get("price_metadata_write_reason"),
            "price_metadata_write_path": bot.get("price_metadata_write_path"),
            "current_price_persist_delta_ms": bot.get(
                "current_price_persist_delta_ms"
            ),
            "current_price_persisted_before_guard": bot.get(
                "current_price_persisted_before_guard"
            ),
            "provider_update_seen_at": bot.get("provider_update_seen_at"),
            "provider_update_to_eval_ms": bot.get("provider_update_to_eval_ms"),
            "reevaluation_trigger_reason": bot.get("reevaluation_trigger_reason"),
            "reevaluation_trigger_path": bot.get("reevaluation_trigger_path"),
            "blocked_guarded_fast_path_used": bool(
                bot.get("blocked_guarded_fast_path_used", False)
            ),
            "evaluation_deferred_reason": bot.get("evaluation_deferred_reason"),
            "fresh_provider_seen_before_eval": bool(
                bot.get("fresh_provider_seen_before_eval", False)
            ),
            "live_position_attribution": live_position_attribution,
            "exchange_position_size": symbol_position_size,
            "exchange_position_side": symbol_position_side,
            "exchange_entry_price": symbol_position.get("entry_price", 0.0),
            "exchange_mark_price": symbol_position.get("mark_price", 0.0),
            "exchange_unrealized_pnl": round(
                float(symbol_position_unrealized_pnl or 0.0), 4
            ),
            "exchange_position_scope": (
                "symbol_wide"
                if symbol_position and live_position_attribution == "ambiguous_symbol"
                else live_position_attribution
            ),
            # Status flags
            "out_of_range": status == "out_of_range",
            "risk_stopped": status == "risk_stopped",
            "tp_hit": status == "tp_hit",
            # Runtime metadata
            "last_run_at": bot.get("last_run_at"),
            "last_error": bot.get("last_error"),
            "created_at": bot.get("created_at"),
            "updated_at": bot.get("updated_at"),
            "started_at": (
                bot.get("started_at") if bot_status == "running" else None
            ),
            # Orders
            "open_order_count": open_order_count,
            "skipped_small_qty_count": bot.get("skipped_small_qty_count", 0),
            "last_skip_reason": bot.get("last_skip_reason"),
            # Opening-order block flags (for frontend alert display)
            "opening_blocked_reason": self._get_raw_runtime_signal_blocker(bot),
            # Order flow analysis (tick-level)
            "flow_score": bot.get("flow_score"),
            "flow_signal": bot.get("flow_signal"),
            "flow_confidence": bot.get("flow_confidence"),
            "flow_volume_spike": bot.get("flow_volume_spike"),
            # Multi-signal composite confidence
            "composite_confidence": bot.get("composite_confidence"),
            "composite_signals_aligned": bot.get("composite_signals_aligned"),
            "composite_confidence_reasons": bot.get("composite_confidence_reasons"),
            # Market sentiment (OI + L/S ratio + funding)
            "sentiment_score": bot.get("sentiment_score"),
            "sentiment_signal": bot.get("sentiment_signal"),
            "oi_conviction": bot.get("oi_conviction"),
            "long_short_ratio": bot.get("long_short_ratio"),
            "_small_capital_block_opening_orders": bool(bot.get("_small_capital_block_opening_orders")),
            "_block_opening_orders": bool(bot.get("_block_opening_orders")),
            "_capital_starved_block_opening_orders": bool(bot.get("_capital_starved_block_opening_orders")),
            "_session_timer_block_opening_orders": bool(bot.get("_session_timer_block_opening_orders")),
            "_auto_pilot_loss_budget_block_openings": bool(bot.get("_auto_pilot_loss_budget_block_openings")),
            "_stall_overlay_block_opening_orders": bool(bot.get("_stall_overlay_block_opening_orders")),
            "_nlp_block_opening_orders": bool(bot.get("_nlp_block_opening_orders")),
            "_breakout_invalidation_block_opening_orders": bool(bot.get("_breakout_invalidation_block_opening_orders")),
            "small_capital_mode_active": bool(bot.get("small_capital_mode_active")),
            "small_capital_profile": bot.get("small_capital_profile"),
            "runtime_open_order_cap_total": runtime_open_order_cap_total,
            "volatility_derisk_open_cap_total": volatility_derisk_open_cap_total,
            "scalp_learned_opening_order_cap": scalp_learned_opening_order_cap,
            "effective_opening_order_cap": effective_opening_order_cap,
            "effective_opening_order_cap_reason": effective_opening_order_cap_reason,
            # Neutral classic grid status
            "neutral_grid_enabled": bot.get("neutral_grid_enabled", False),
            # Volatility Gate / ATR Guard (Smart Feature #15)
            "neutral_volatility_gate_enabled": bot.get(
                "neutral_volatility_gate_enabled", False
            ),
            "neutral_volatility_gate_threshold_pct": bot.get(
                "neutral_volatility_gate_threshold_pct", 5.0
            ),
            "levels_count": bot.get("levels_count"),
            "mid_index": bot.get("mid_index"),
            "entry_orders_open": entry_orders_open,
            "exit_orders_open": exit_orders_open,
            "active_long_slots": bot.get("active_long_slots", 0),
            "active_short_slots": bot.get("active_short_slots", 0),
            "last_fill_event": bot.get("last_fill_event"),
            "last_replacement_action": bot.get("last_replacement_action"),
            # Scalp Market mode fields
            "scalp_status": bot.get("scalp_status"),
            "scalp_signal_score": bot.get("scalp_signal_score"),
            "scalp_signal_direction": bot.get("scalp_signal_direction"),
            "last_scalp_trade_time": bot.get("last_scalp_trade_time"),
            "direction_change_guard_enabled": bool(
                bot.get("direction_change_guard_enabled", False)
            ),
            "direction_change_guard_state": bot.get("direction_change_guard_state"),
            "direction_change_guard_source": bot.get("direction_change_guard_source"),
            "direction_change_guard_score": bot.get("direction_change_guard_score"),
            "direction_change_guard_detail": bot.get("direction_change_guard_detail"),
            "direction_change_guard_updated_at": bot.get(
                "direction_change_guard_updated_at"
            ),
            "direction_change_guard_last_action": bot.get(
                "direction_change_guard_last_action"
            ),
            "direction_change_guard_last_reason": bot.get(
                "direction_change_guard_last_reason"
            ),
            "direction_change_guard_prev_state": bot.get(
                "direction_change_guard_prev_state"
            ),
            "direction_change_guard_last_event_at": bot.get(
                "direction_change_guard_last_event_at"
            ),
            "direction_change_guard_last_position_action": bot.get(
                "direction_change_guard_last_position_action"
            ),
            "direction_change_guard_last_unrealized_pnl": bot.get(
                "direction_change_guard_last_unrealized_pnl"
            ),
            # Trend and scalp analysis (for live status display)
            "trend_status": bot.get("trend_status"),
            "trend_direction": bot.get(
                "trend_direction", self._extract_trend_direction(bot)
            ),  # 001-trading-bot-audit FR-023
            "scalp_analysis": bot.get("scalp_analysis"),
            "_scalp_adapted_target": bot.get("_scalp_adapted_target"),
            "_scalp_adapted_quick": bot.get("_scalp_adapted_quick"),
            "scalp_live_target": bot.get("scalp_live_target"),
            "scalp_live_quick_profit": bot.get("scalp_live_quick_profit"),
            "scalp_live_min_profit": bot.get("scalp_live_min_profit"),
            "scalp_live_position_notional": bot.get("scalp_live_position_notional"),
            # Regime (multi-timeframe)
            "regime_primary": bot.get("regime_primary"),
            "regime_secondary": bot.get("regime_secondary"),
            "regime_effective": bot.get("regime_effective"),
            "regime_confidence": bot.get("regime_confidence"),
            # Fast execution counters
            "partial_tp_executed_count": bot.get("partial_tp_executed_count", 0),
            "partial_tp_skipped_small_qty_count": bot.get(
                "partial_tp_skipped_small_qty_count", 0
            ),
            "profit_lock_executed_count": bot.get("profit_lock_executed_count", 0),
            "profit_lock_skipped_fee_guard_count": bot.get(
                "profit_lock_skipped_fee_guard_count", 0
            ),
            # Adaptive profit protection / exit advisory
            "profit_protection_mode": bot.get("profit_protection_mode"),
            "profit_protection_advisory": bot.get("profit_protection_advisory"),
            "profit_protection_shadow": bot.get("profit_protection_shadow"),
            "profit_protection_decision": bot.get("profit_protection_decision"),
            "profit_protection_reason_family": bot.get(
                "profit_protection_reason_family"
            ),
            "profit_protection_wait_justified": bot.get(
                "profit_protection_wait_justified"
            ),
            "profit_protection_actionable": bool(
                bot.get("profit_protection_actionable", False)
            ),
            "profit_protection_armed": bool(
                bot.get("profit_protection_armed", False)
            ),
            "profit_protection_blocked": bool(
                bot.get("profit_protection_blocked", False)
            ),
            "profit_protection_blocked_reason": bot.get(
                "profit_protection_blocked_reason"
            ),
            "profit_protection_blocked_detail": bot.get(
                "profit_protection_blocked_detail"
            ),
            "profit_protection_current_profit_pct": bot.get(
                "profit_protection_current_profit_pct"
            ),
            "profit_protection_peak_profit_pct": bot.get(
                "profit_protection_peak_profit_pct"
            ),
            "profit_protection_giveback_pct": bot.get(
                "profit_protection_giveback_pct"
            ),
            "profit_protection_giveback_threshold_pct": bot.get(
                "profit_protection_giveback_threshold_pct"
            ),
            "profit_protection_shadow_status": bot.get(
                "profit_protection_shadow_status"
            ),
            "profit_protection_last_action": bot.get("profit_protection_last_action"),
            "profit_protection_last_action_at": bot.get(
                "profit_protection_last_action_at"
            ),
            # Funding Rate data (from funding_rate_service)
            "funding_rate_pct": bot.get("funding_rate_pct"),
            "funding_signal": bot.get("funding_signal"),
            "funding_score": bot.get("funding_score"),
            "funding_protection_enabled": bot.get("funding_protection_enabled", True),
            "funding_protection_active": bot.get("funding_protection_active", False),
            "funding_protection_reason": bot.get("funding_protection_reason"),
            # Danger zone status
            "danger_score": bot.get("danger_score", 0),
            "danger_level": bot.get("danger_level", "none"),
            "danger_in_zone": bot.get("danger_in_zone", False),
            "danger_warnings": bot.get("danger_warnings", []),
            # Auto-Direction Signals (from grid_bot_service)
            "direction_score": bot.get("direction_score"),
            "direction_signals": bot.get("direction_signals"),
            # Individual signal data
            "rsi_signal": bot.get("rsi_signal"),
            "rsi_score": bot.get("rsi_score"),
            "adx_signal": bot.get("adx_signal"),
            "adx_score": bot.get("adx_score"),
            "macd_signal": bot.get("macd_signal"),
            "macd_score": bot.get("macd_score"),
            "ema_signal": bot.get("ema_signal"),
            "ema_score": bot.get("ema_score"),
            # Volume Profile
            "volume_profile_signal": bot.get("volume_profile_signal"),
            "volume_profile_score": bot.get("volume_profile_score"),
            # Open Interest
            "oi_signal": bot.get("oi_signal"),
            "oi_score": bot.get("oi_score"),
            # Order Book
            "orderbook_signal": bot.get("orderbook_signal"),
            "orderbook_score": bot.get("orderbook_score"),
            "orderbook_imbalance": bot.get("orderbook_imbalance"),
            # Liquidation
            "liquidation_signal": bot.get("liquidation_signal"),
            "liquidation_score": bot.get("liquidation_score"),
            # Session
            "session_signal": bot.get("session_signal"),
            "session_name": bot.get("session_name"),
            "session_modifier": bot.get("session_modifier"),
            "is_weekend": bot.get("is_weekend"),
            # Mean Reversion
            "mean_reversion_signal": bot.get("mean_reversion_signal"),
            "mean_reversion_score": bot.get("mean_reversion_score"),
            "mean_reversion_deviation": bot.get("mean_reversion_deviation"),
            # =================================================================
            # UPnL Stop-Loss Status (NEW - Part 10)
            # =================================================================
            "upnl_stoploss_enabled": bot.get("upnl_stoploss_enabled", False),
            "upnl_stoploss_active": bot.get("_block_opening_orders", False),
            "upnl_stoploss_reason": bot.get("_upnl_stoploss_reason"),
            "upnl_stoploss_cooldown_until": bot.get("upnl_stoploss_cooldown_until"),
            "upnl_stoploss_in_cooldown": self._is_in_cooldown(bot),
            "upnl_stoploss_trigger_count": bot.get("upnl_stoploss_trigger_count", 0),
            "upnl_stoploss_last_trigger": bot.get("upnl_stoploss_last_trigger"),
            "upnl_pct": bot.get("_computed_upnl_pct"),
            # Effective risk params (computed from bot settings or symbol defaults)
            "effective_upnl_soft": self._get_effective_threshold(
                bot, symbol, "soft_pct"
            ),
            "effective_upnl_hard": self._get_effective_threshold(
                bot, symbol, "hard_pct"
            ),
            "effective_upnl_liq_pct": self._get_effective_threshold(
                bot, symbol, "liq_pct"
            ),
            "effective_upnl_k1": self._get_effective_threshold(bot, symbol, "k1"),
            "effective_cooldown": self._get_effective_threshold(
                bot, symbol, "cooldown_seconds"
            ),
            "liq_distance_pct": bot.get("last_liq_distance_pct"),
            "effective_levels": bot.get("effective_levels"),
            "per_order_notional": bot.get("per_order_notional"),
            "effective_step_pct": bot.get("effective_step_pct"),
            "effective_range_pct": bot.get("effective_range_pct"),
            "atr_5m_pct": bot.get("atr_5m_pct"),
            "atr_15m_pct": bot.get("atr_15m_pct"),
            "auto_margin_remaining_cap": bot.get("auto_margin_remaining_cap"),
            "auto_margin_total_added": (bot.get("auto_margin_state") or {}).get("total_added_usdt", 0),
            "auto_margin_last_reason": (bot.get("auto_margin_state") or {}).get("last_add_reason"),
            "auto_margin_last_pct_to_liq": (bot.get("auto_margin_state") or {}).get("last_seen_pct_to_liq"),
            # Tick intervals (for dashboard display)
            "grid_tick_seconds": GRID_TICK_SECONDS,
            "risk_tick_seconds": RISK_TICK_SECONDS,
            # BTC Guard
            "btc_guard_status": bot.get("btc_guard_status"),
            # Entry Gate (long/short mode entry timing)
            "entry_gate_enabled": entry_gate_bot_enabled,  # User's toggle setting
            "entry_gate_bot_enabled": entry_gate_bot_enabled,
            "entry_gate_global_master_applicable": (
                entry_gate_global_master_applicable
            ),
            "entry_gate_global_master_enabled": entry_gate_global_master_enabled,
            "entry_gate_contract_active": entry_gate_contract_active,
            "entry_gate_blocked": bot.get("_entry_gate_blocked", False),
            "entry_gate_reason": bot.get("_entry_gate_blocked_reason"),
            "entry_gate_blocked_until": bot.get("_entry_gate_blocked_until", 0),
            # Partial TP data (from take_profit_service)
            "partial_tp_state": bot.get("partial_tp_state"),
            "last_partial_tp_level": bot.get("last_partial_tp_level"),
            "last_partial_tp_profit_pct": bot.get("last_partial_tp_profit_pct"),
            # Symbol-wide cumulative PnL for the dashboard's Sym PnL surfaces.
            "symbol_pnl": self._get_symbol_pnl_summary(symbol, symbol_pnl_lookup),
            # Bot-specific PnL remains available for drill-downs and future UI use.
            "bot_pnl": self._get_bot_pnl_summary(bot_id, bot_pnl_lookup),
            # Exchange truth / reconciliation metadata
            "exchange_reconciliation": exchange_reconciliation,
            "exchange_reconciliation_status": exchange_reconciliation.get("status"),
            "exchange_reconciliation_reason": exchange_reconciliation.get("reason"),
            "exchange_reconciliation_source": exchange_reconciliation.get("source"),
            "exchange_reconciliation_updated_at": exchange_reconciliation.get(
                "updated_at"
            ),
            "exchange_reconciliation_mismatches": list(
                exchange_reconciliation.get("mismatches") or []
            ),
            "exchange_exposure_detected": bool(
                bot.get("exchange_exposure_detected", False)
            ),
            "exchange_position_detected": bool(
                bot.get("exchange_position_detected", False)
            ),
            "exchange_open_orders_detected": bool(
                bot.get("exchange_open_orders_detected", False)
            ),
            "position_assumption_stale": bool(
                bot.get("position_assumption_stale", False)
            ),
            "order_assumption_stale": bool(bot.get("order_assumption_stale", False)),
            "ambiguous_execution_follow_up": ambiguous_execution_follow_up,
            "ambiguous_execution_follow_up_status": ambiguous_execution_follow_up.get(
                "status"
            ),
            "ambiguous_execution_follow_up_pending": bool(
                ambiguous_execution_follow_up.get("pending", False)
            ),
            "ambiguous_execution_follow_up_action": ambiguous_execution_follow_up.get(
                "action"
            ),
            "ambiguous_execution_follow_up_reason": ambiguous_execution_follow_up.get(
                "exchange_effect_reason"
            )
            or ambiguous_execution_follow_up.get("diagnostic_reason"),
            "ambiguous_execution_follow_up_updated_at": ambiguous_execution_follow_up.get(
                "updated_at"
            ),
            "ambiguous_execution_follow_up_truth_check_expired": bool(
                ambiguous_execution_follow_up.get("truth_check_expired", False)
            ),
            # Directional reanchor state
            "directional_reanchor_pending": bool(
                bot.get("directional_reanchor_pending", False)
            ),
            "directional_reanchor_requested_at": bot.get(
                "directional_reanchor_requested_at"
            ),
            "directional_reanchor_last_completed_at": bot.get(
                "directional_reanchor_last_completed_at"
            ),
            "directional_reanchor_last_expired_at": bot.get(
                "directional_reanchor_last_expired_at"
            ),
            "directional_reanchor_last_result": bot.get(
                "directional_reanchor_last_result"
            ),
            "directional_reanchor_last_cancelled_opening_orders": bot.get(
                "directional_reanchor_last_cancelled_opening_orders"
            ),
        }

        return enriched

    def _enrich_bot_light(
        self,
        bot: Dict[str, Any],
        position_lookup: Dict[str, Dict[str, Any]],
        positions_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        symbol_pnl_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        bot_pnl_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        running_bot_ids_by_symbol: Optional[Dict[str, List[str]]] = None,
        scanner_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        live_open_orders_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        stopped_preview_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        diagnostics: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Lightweight bot enrichment for the dashboard-critical fast path.

        Skips all expensive operations:
        - price_action_service.analyze() / score_mode_fit()
        - _get_entry_readiness() -> evaluate_bot()
        - _build_mode_readiness_matrix()
        - _build_alternative_mode_summary()
        - _maybe_emit_signal_drift_watchdog()

        Readiness fields are sourced from the stability cache (last known good)
        and the persisted bot dict, never from fresh evaluation.
        """
        symbol = bot.get("symbol", "")
        bot_id = bot.get("id", "")
        status = bot.get("status", "stopped")
        symbol_pnl_lookup = symbol_pnl_lookup or {}
        bot_pnl_lookup = bot_pnl_lookup or {}
        positions_by_symbol = positions_by_symbol or {}
        running_bot_ids_by_symbol = running_bot_ids_by_symbol or {}
        scanner_lookup = scanner_lookup or {}
        live_open_orders_by_symbol = live_open_orders_by_symbol or {}
        scanner_recommendation = scanner_lookup.get(symbol) or {}
        scanner_recommended_mode = scanner_recommendation.get("recommended_mode")
        scanner_recommended_range_mode = scanner_recommendation.get(
            "recommended_range_mode"
        )
        scanner_recommended_profile = scanner_recommendation.get(
            "recommended_profile"
        )
        auto_pilot_enabled = bool(bot.get("auto_pilot", False))
        auto_pilot_universe_mode = (
            normalize_auto_pilot_universe_mode(bot.get("auto_pilot_universe_mode"))
            if auto_pilot_enabled
            else bot.get("auto_pilot_universe_mode")
        )
        auto_pilot_universe_summary = bot.get("auto_pilot_universe_summary")
        if auto_pilot_enabled and not auto_pilot_universe_summary:
            auto_pilot_universe_summary = f"mode={auto_pilot_universe_mode}"
        configured_bot_mode = configured_mode(bot)
        configured_bot_range_mode = configured_range_mode(bot)
        effective_runtime_mode = normalize_bot_mode(
            bot.get("effective_runtime_mode") or configured_bot_mode
        )
        effective_runtime_range_mode = normalize_range_mode(
            bot.get("effective_runtime_range_mode") or configured_bot_range_mode
        )
        mode_policy = normalize_mode_policy(bot.get("mode_policy"), bot)
        scanner_recommendation_differs = bool(
            scanner_recommended_mode
            and (
                str(scanner_recommended_mode) != str(configured_bot_mode or "")
                or str(scanner_recommended_range_mode or "")
                != str(configured_bot_range_mode or "")
            )
        )
        entry_gate_bot_enabled = bool(bot.get("entry_gate_enabled", True))
        entry_gate_global_master_applicable = str(
            configured_bot_mode or ""
        ).strip().lower() in {"long", "short"}
        entry_gate_global_master_enabled = (
            bool(getattr(strategy_cfg, "ENTRY_GATE_ENABLED", False))
            if entry_gate_global_master_applicable
            else True
        )
        entry_gate_contract_active = bool(
            entry_gate_bot_enabled and entry_gate_global_master_enabled
        )
        raw_entry_signal_preferred = bool(bot.get("entry_signal_preferred", False))
        raw_entry_signal_executable = bool(bot.get("entry_signal_executable", False))
        effective_entry_signal_preferred = bool(
            raw_entry_signal_preferred and entry_gate_contract_active
        )
        effective_entry_signal_executable = bool(
            raw_entry_signal_executable and entry_gate_contract_active
        )

        # --- Position attribution (same as _enrich_bot, cheap dict ops) ---
        position = {}
        symbol_position = position_lookup.get(symbol, {}) if symbol in position_lookup else {}
        symbol_positions = positions_by_symbol.get(symbol, [])
        multi_leg_symbol_position = len(symbol_positions) > 1
        live_position_attribution = "none"
        running_bot_ids = [
            candidate for candidate in running_bot_ids_by_symbol.get(symbol, []) if candidate
        ]
        if multi_leg_symbol_position:
            if len(running_bot_ids) == 1 and running_bot_ids[0] == bot_id:
                live_position_attribution = "symbol_multi_leg"
                best_leg = max(
                    symbol_positions,
                    key=lambda p: abs(float((p or {}).get("size") or 0)),
                    default={},
                )
                if best_leg:
                    position = best_leg
            elif len(running_bot_ids) > 1:
                live_position_attribution = "ambiguous_symbol"
        elif symbol in position_lookup:
            if len(running_bot_ids) == 1 and running_bot_ids[0] == bot_id:
                position = position_lookup.get(symbol, {})
                live_position_attribution = "unique_running_bot"
            elif len(running_bot_ids) > 1:
                live_position_attribution = "ambiguous_symbol"

        position_size = position.get("size", 0.0)
        position_side = position.get("side", "")
        position_unrealized_pnl = position.get("unrealized_pnl", 0.0)
        symbol_position_size = symbol_position.get("size", 0.0)
        symbol_position_side = symbol_position.get("side", "")
        symbol_position_unrealized_pnl = symbol_position.get("unrealized_pnl", 0.0)
        symbol_position_unrealized_pnl_total = sum(
            float((candidate or {}).get("unrealized_pnl") or 0.0)
            for candidate in symbol_positions
        )

        # --- PnL computation (cheap arithmetic) ---
        realized_pnl = float(bot.get("realized_pnl") or 0.0)
        if live_position_attribution == "ambiguous_symbol":
            unrealized_pnl = 0.0
        elif live_position_attribution == "symbol_multi_leg":
            unrealized_pnl = symbol_position_unrealized_pnl_total
        elif position_size > 0:
            unrealized_pnl = float(position_unrealized_pnl or 0.0)
        elif bot.get("status") in ("stopped", "risk_stopped"):
            unrealized_pnl = 0.0
        else:
            unrealized_pnl = float(bot.get("unrealized_pnl") or 0.0)
        total_pnl = realized_pnl + unrealized_pnl

        range_mode = configured_bot_range_mode
        last_range_width_pct = bot.get("last_range_width_pct")
        tp_pct = bot.get("tp_pct")
        try:
            tp_pct = float(tp_pct) if tp_pct is not None else None
        except (TypeError, ValueError):
            tp_pct = None

        investment = self._safe_float(bot.get("investment"), 0.0)
        pnl_pct = total_pnl / investment if investment > 0 else 0.0
        position_profit_pct = self._calculate_position_profit_pct(
            position_side=position_side,
            entry_price=self._safe_float(position.get("entry_price"), 0.0),
            mark_price=self._safe_float(position.get("mark_price"), 0.0),
            position_size=self._safe_float(position_size, 0.0),
        )

        # --- Runtime hours (cheap) ---
        runtime_hours = 0.0
        profit_per_hour = None
        session_realized_pnl = 0.0
        session_total_pnl = 0.0
        session_profit_per_hour = None
        accumulated_hours = float(bot.get("accumulated_runtime_hours") or 0.0)
        session_hours = 0.0
        bot_status = bot.get("status", "stopped")
        started_at = bot.get("started_at")
        if bot_status == "running" and started_at:
            try:
                started_dt = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                )
                curr_dt = datetime.now(timezone.utc)
                session_seconds = max((curr_dt - started_dt).total_seconds(), 0)
                session_hours = session_seconds / 3600.0
            except Exception:
                session_hours = 0.0
        runtime_hours = accumulated_hours + session_hours
        if runtime_hours > 0:
            if runtime_hours >= MIN_RUNTIME_FOR_RATE_HOURS:
                profit_per_hour = total_pnl / runtime_hours
        else:
            runtime_hours = None

        session_realized_baseline = self._safe_float(
            bot.get("tp_session_realized_baseline"), realized_pnl
        )
        if bot_status in {"running", "recovering"}:
            session_realized_pnl = realized_pnl - session_realized_baseline
            session_total_pnl = session_realized_pnl + unrealized_pnl
            if session_hours >= MIN_RUNTIME_FOR_RATE_HOURS:
                session_profit_per_hour = session_total_pnl / session_hours

        # --- Session timer (cheap datetime math) ---
        now_dt = datetime.now(timezone.utc)
        session_timer_state = str(
            bot.get("session_timer_state") or "inactive"
        ).strip().lower() or "inactive"
        session_timer_running = session_timer_state in {
            "running", "pre_stop_no_new_entries", "grace_active",
        }
        session_timer_complete = session_timer_state == "completed"
        session_timer_no_new_entries_active = bool(
            bot.get("session_timer_no_new_entries_active")
            or bot.get("_session_timer_block_opening_orders")
        )
        session_timer_stop_at = bot.get("session_stop_at")
        session_timer_stop_dt = self._parse_iso_datetime(session_timer_stop_at)
        session_timer_grace_expires_at = bot.get("session_timer_grace_expires_at")
        session_timer_grace_expires_dt = self._parse_iso_datetime(
            session_timer_grace_expires_at
        )

        def _remaining_seconds(target_dt: Optional[datetime]) -> Optional[int]:
            if target_dt is None:
                return None
            return max(int((target_dt - now_dt).total_seconds()), 0)

        session_timer_stops_in_sec = (
            _remaining_seconds(session_timer_stop_dt)
            if session_timer_stop_dt is not None
            else None
        )
        session_timer_grace_remaining_sec = (
            _remaining_seconds(session_timer_grace_expires_dt)
            if session_timer_grace_expires_dt is not None
            else None
        )

        # --- Order counts (cheap, from pre-fetched data) ---
        live_order_counts = self._get_live_bot_order_counts(
            bot, live_open_orders_by_symbol,
        )
        if live_order_counts is not None:
            entry_orders_open = int(live_order_counts.get("entry_orders_open", 0) or 0)
            exit_orders_open = int(live_order_counts.get("exit_orders_open", 0) or 0)
            open_order_count = int(live_order_counts.get("open_order_count", 0) or 0)
        else:
            entry_orders_open = int(bot.get("entry_orders_open", 0) or 0)
            exit_orders_open = int(bot.get("exit_orders_open", 0) or 0)
            open_order_count = entry_orders_open + exit_orders_open
            if open_order_count <= 0:
                open_order_count = int(bot.get("open_order_count", 0) or 0)
        effective_opening_order_cap = int(
            self._safe_float(bot.get("runtime_open_order_cap_total"), 0)
        )
        if effective_opening_order_cap <= 0:
            effective_opening_order_cap = int(
                self._safe_float(bot.get("grid_count"), 0)
            )

        # --- Readiness: use stability cache (NO fresh evaluation) ---
        readiness_started = time.monotonic()
        cache = self._ensure_readiness_stability_cache()
        cache_key = f"{bot_id}:configured"
        cached_readiness = cache.get(cache_key) or {}
        stable_readiness_stage = cached_readiness.get("stable_stage") or bot.get("stable_readiness_stage") or "watch"
        stable_readiness_reason = cached_readiness.get("stable_reason") or bot.get("stable_readiness_reason") or ""
        stable_readiness_reason_text = cached_readiness.get("stable_reason_text") or bot.get("stable_readiness_reason_text") or ""
        stable_flags = self._readiness_stage_flags(stable_readiness_stage)

        # Read last-known readiness fields from bot dict (persisted by runner)
        setup_ready_status = bot.get("setup_ready_status") or cached_readiness.get("stable_stage") or "watch"
        setup_ready_reason = bot.get("setup_ready_reason") or ""
        setup_ready_score = bot.get("setup_ready_score")
        entry_ready_status = bot.get("entry_ready_status") or setup_ready_status
        entry_ready_reason = bot.get("entry_ready_reason") or ""
        execution_viability_status = bot.get("execution_viability_status") or "unknown"
        execution_blocked = bool(bot.get("execution_blocked", False))
        execution_margin_limited = bool(bot.get("execution_margin_limited", False))
        if diagnostics is not None:
            diagnostics["readiness_stability_ms"] = float(
                diagnostics.get("readiness_stability_ms") or 0.0
            ) + ((time.monotonic() - readiness_started) * 1000.0)

        # Exchange truth (cheap dict reads)
        exchange_reconciliation = dict(bot.get("exchange_reconciliation") or {})
        ambiguous_execution_follow_up = dict(
            bot.get("ambiguous_execution_follow_up") or {}
        )

        # --- Build light-only enriched dict ---
        light_dict_started = time.monotonic()
        enriched = {
            "id": bot.get("id"),
            "symbol": symbol,
            "mode": configured_bot_mode,
            "configured_mode": configured_bot_mode,
            "configured_range_mode": configured_bot_range_mode,
            "effective_runtime_mode": effective_runtime_mode,
            "effective_runtime_range_mode": effective_runtime_range_mode,
            "mode_policy": mode_policy,
            "status": status,
            "profile": bot.get("profile", "normal"),
            "auto_pilot": auto_pilot_enabled,
            "auto_direction": bool(bot.get("auto_direction", False)),
            "range_mode": range_mode,
            "last_range_width_pct": last_range_width_pct,
            "scanner_recommended_mode": scanner_recommended_mode,
            "scanner_recommended_range_mode": scanner_recommended_range_mode,
            "scanner_recommended_profile": scanner_recommended_profile,
            "scanner_recommendation_differs": scanner_recommendation_differs,
            "scanner_recommendation_updated_at": scanner_recommendation.get("updated_at"),
            "scanner_recommendation_regime": scanner_recommendation.get("regime"),
            "scanner_recommendation_trend": scanner_recommendation.get("trend"),
            # Readiness — from stability cache, NOT fresh evaluation
            "stable_readiness_stage": stable_readiness_stage,
            "stable_readiness_reason": stable_readiness_reason,
            "stable_readiness_reason_text": stable_readiness_reason_text,
            "stable_readiness_actionable": stable_flags["actionable"],
            "stable_readiness_near_trigger": stable_flags["near_trigger"],
            "stable_readiness_late": stable_flags["late"],
            "readiness_hard_invalidated": bool(
                cached_readiness.get("hard_invalidated", False)
            ),
            "setup_ready_status": setup_ready_status,
            "setup_ready_reason": setup_ready_reason,
            "setup_ready_score": setup_ready_score,
            "entry_ready_status": entry_ready_status,
            "entry_ready_reason": entry_ready_reason,
            "execution_blocked": execution_blocked,
            "execution_viability_status": execution_viability_status,
            "execution_margin_limited": execution_margin_limited,
            "readiness_preview_state": bot.get("readiness_preview_state"),
            # Entry signal (from stored bot state)
            "entry_signal_code": bot.get("entry_signal_code"),
            "entry_signal_label": bot.get("entry_signal_label"),
            "entry_signal_preferred": effective_entry_signal_preferred,
            "entry_signal_late": bool(bot.get("entry_signal_late", False)),
            "entry_signal_executable": effective_entry_signal_executable,
            # Live gate
            "live_gate_status": bot.get("live_gate_status"),
            "live_gate_contract_active": bot.get("live_gate_contract_active"),
            "entry_gate_contract_active": entry_gate_contract_active,
            "entry_gate_blocked": bot.get("_entry_gate_blocked", False),
            "entry_gate_reason": bot.get("_entry_gate_blocked_reason"),
            "entry_gate_blocked_until": bot.get("_entry_gate_blocked_until", 0),
            # Alternative mode summary (lightweight — no matrix)
            "alternative_mode_ready": bool(bot.get("alternative_mode_ready", False)),
            "alternative_mode": bot.get("alternative_mode"),
            "alternative_mode_range_mode": bot.get("alternative_mode_range_mode"),
            "alternative_mode_status": bot.get("alternative_mode_status"),
            "alternative_mode_score": bot.get("alternative_mode_score"),
            "alternative_mode_is_scanner_suggestion": bool(
                bot.get("alternative_mode_is_scanner_suggestion", False)
            ),
            "alternative_mode_actionable": bool(
                bot.get("alternative_mode_actionable", False)
            ),
            "alternative_mode_near_trigger": bool(
                bot.get("alternative_mode_near_trigger", False)
            ),
            "alternative_mode_late": bool(
                bot.get("alternative_mode_late", False)
            ),
            "alternative_mode_is_runtime_view": bool(
                bot.get("alternative_mode_is_runtime_view", False)
            ),
            # Capital starved
            "capital_starved_block_opening_orders": bool(
                bot.get("_capital_starved_block_opening_orders", False)
            ),
            "capital_starved_reason": bot.get("capital_starved_reason"),
            # Auto-pilot
            "auto_pilot_search_status": bot.get("auto_pilot_search_status"),
            "auto_pilot_pick_status": bot.get("auto_pilot_pick_status"),
            "auto_pilot_block_reason": bot.get("auto_pilot_block_reason"),
            "auto_pilot_top_candidate_symbol": bot.get("auto_pilot_top_candidate_symbol"),
            "auto_pilot_top_candidate_score": bot.get("auto_pilot_top_candidate_score"),
            "auto_pilot_top_candidate_mode": bot.get("auto_pilot_top_candidate_mode"),
            "auto_pilot_universe_mode": auto_pilot_universe_mode,
            "auto_pilot_universe_summary": auto_pilot_universe_summary,
            # Grid config
            "lower_price": self._safe_float(bot.get("lower_price"), 0.0),
            "upper_price": self._safe_float(bot.get("upper_price"), 0.0),
            "grid_count": bot.get("grid_count", 0),
            "investment": self._safe_float(bot.get("investment"), 0.0),
            "leverage": self._safe_float(bot.get("leverage"), 1.0),
            "auto_stop": bot.get("auto_stop"),
            "auto_stop_target_usdt": bot.get("auto_stop_target_usdt", 0),
            "session_timer_enabled": bool(bot.get("session_timer_enabled", False)),
            "session_timer_state": session_timer_state,
            "session_timer_running": session_timer_running,
            "session_timer_complete": session_timer_complete,
            "session_timer_no_new_entries_active": session_timer_no_new_entries_active,
            "session_timer_stops_in_sec": session_timer_stops_in_sec,
            "session_timer_grace_active": session_timer_state == "grace_active",
            "session_timer_grace_remaining_sec": session_timer_grace_remaining_sec,
            "breakout_confirmed_entry": bool(bot.get("breakout_confirmed_entry", False)),
            "breakout_entry_confirmed": bool(bot.get("breakout_entry_confirmed", False)),
            # TP%
            "tp_pct": tp_pct,
            # PnL
            "realized_pnl": round(realized_pnl, 4),
            "unrealized_pnl": round(unrealized_pnl, 4),
            "total_pnl": round(total_pnl, 4),
            "session_realized_pnl": round(session_realized_pnl, 4),
            "session_total_pnl": round(session_total_pnl, 4),
            "session_profit_per_hour": (
                round(session_profit_per_hour, 6)
                if session_profit_per_hour is not None
                else None
            ),
            "pnl_pct": round(pnl_pct, 6),
            "position_profit_pct": (
                round(position_profit_pct, 6)
                if position_profit_pct is not None
                else None
            ),
            "runtime_hours": runtime_hours,
            "profit_per_hour": (
                round(profit_per_hour, 6) if profit_per_hour is not None else None
            ),
            # Position
            "position_size": position_size,
            "position_side": position_side,
            "entry_price": position.get("entry_price", 0.0),
            "mark_price": position.get("mark_price", 0.0),
            "current_price": bot.get("current_price", 0.0),
            "live_position_attribution": live_position_attribution,
            "exchange_position_size": symbol_position_size,
            "exchange_position_side": symbol_position_side,
            "exchange_entry_price": symbol_position.get("entry_price", 0.0),
            "exchange_mark_price": symbol_position.get("mark_price", 0.0),
            "exchange_unrealized_pnl": round(
                float(symbol_position_unrealized_pnl or 0.0), 4
            ),
            "exchange_exposure_detected": bool(bot.get("exchange_exposure_detected", False)),
            "exchange_position_detected": bool(bot.get("exchange_position_detected", False)),
            # Status flags
            "out_of_range": status == "out_of_range",
            "risk_stopped": status == "risk_stopped",
            "tp_hit": status == "tp_hit",
            "runtime_snapshot_stale": bool(bot.get("runtime_snapshot_stale", False)),
            # Metadata
            "last_run_at": bot.get("last_run_at"),
            "last_error": bot.get("last_error"),
            "created_at": bot.get("created_at"),
            "updated_at": bot.get("updated_at"),
            "started_at": (
                bot.get("started_at") if bot_status == "running" else None
            ),
            # Orders
            "open_order_count": open_order_count,
            "entry_orders_open": entry_orders_open,
            "exit_orders_open": exit_orders_open,
            "effective_opening_order_cap": effective_opening_order_cap,
            "last_skip_reason": bot.get("last_skip_reason"),
            "last_replacement_action": bot.get("last_replacement_action"),
            "opening_blocked_reason": self._get_raw_runtime_signal_blocker(bot),
            # Grid/scalp
            "neutral_grid_enabled": bot.get("neutral_grid_enabled", False),
            "scalp_status": bot.get("scalp_status"),
            "scalp_signal_score": bot.get("scalp_signal_score"),
            "scalp_analysis": bot.get("scalp_analysis"),
            "trend_status": bot.get("trend_status"),
            "trend_direction": bot.get(
                "trend_direction", self._extract_trend_direction(bot)
            ),
            # Danger/funding
            "danger_score": bot.get("danger_score", 0),
            "danger_level": bot.get("danger_level", "none"),
            "danger_in_zone": bot.get("danger_in_zone", False),
            "danger_warnings": bot.get("danger_warnings", []),
            "funding_rate_pct": bot.get("funding_rate_pct"),
            "funding_signal": bot.get("funding_signal"),
            # Direction
            "direction_score": bot.get("direction_score"),
            "direction_signals": bot.get("direction_signals"),
            "direction_change_guard_state": bot.get("direction_change_guard_state"),
            "direction_change_guard_source": bot.get("direction_change_guard_source"),
            "direction_change_guard_last_event_at": bot.get(
                "direction_change_guard_last_event_at"
            ),
            "direction_change_guard_last_action": bot.get(
                "direction_change_guard_last_action"
            ),
            "direction_change_guard_prev_state": bot.get(
                "direction_change_guard_prev_state"
            ),
            # UPnL stoploss basics
            "upnl_stoploss_enabled": bot.get("upnl_stoploss_enabled", False),
            "upnl_stoploss_active": bot.get("_block_opening_orders", False),
            "upnl_stoploss_reason": bot.get("_upnl_stoploss_reason"),
            "upnl_stoploss_in_cooldown": self._is_in_cooldown(bot),
            "upnl_stoploss_trigger_count": bot.get("upnl_stoploss_trigger_count", 0),
            # Exchange truth
            "exchange_reconciliation": exchange_reconciliation,
            "exchange_reconciliation_status": exchange_reconciliation.get("status"),
            "ambiguous_execution_follow_up": ambiguous_execution_follow_up,
            "ambiguous_execution_follow_up_status": ambiguous_execution_follow_up.get(
                "status"
            ),
            "ambiguous_execution_follow_up_pending": bool(
                ambiguous_execution_follow_up.get("pending", False)
            ),
            # Directional reanchor
            "directional_reanchor_pending": bool(
                bot.get("directional_reanchor_pending", False)
            ),
            # Symbol PnL
            "symbol_pnl": self._get_symbol_pnl_summary(symbol, symbol_pnl_lookup),
            "bot_pnl": self._get_bot_pnl_summary(bot_id, bot_pnl_lookup),
        }
        if diagnostics is not None:
            diagnostics["light_dict_build_ms"] = float(
                diagnostics.get("light_dict_build_ms") or 0.0
            ) + ((time.monotonic() - light_dict_started) * 1000.0)
        return enriched

    def _get_entry_readiness(
        self,
        bot: Dict[str, Any],
        symbol_position: Dict[str, Any],
        position: Dict[str, Any],
        price_action_context: Optional[Dict[str, Any]] = None,
        stopped_preview_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        readiness_service = getattr(self, "entry_readiness_service", None)
        if readiness_service is None:
            return {}

        readiness_bot = dict(bot or {})
        bot_id = str(readiness_bot.get("id") or "").strip()
        status = str(readiness_bot.get("status") or "").strip().lower()
        if not self._safe_float(readiness_bot.get("current_price"), 0.0):
            current_price = (
                self._safe_float(symbol_position.get("mark_price"), 0.0)
                or self._safe_float(position.get("mark_price"), 0.0)
                or None
            )
            if current_price is not None:
                readiness_bot["current_price"] = current_price
        if isinstance(price_action_context, dict):
            for key, value in price_action_context.items():
                if value is not None:
                    readiness_bot[f"readiness_price_action_{key}"] = value

        if (
            bot_id
            and status not in ACTIVE_POSITION_OWNER_STATUSES
            and stopped_preview_lookup is not None
            and bot_id in stopped_preview_lookup
        ):
            preview_payload = dict(stopped_preview_lookup.get(bot_id) or {})
            annotated_preview = self._annotate_readiness_payload(
                preview_payload,
                source_kind_override=preview_payload.get("readiness_source_kind"),
                source_age_sec=self._safe_float(
                    preview_payload.get("readiness_preview_age_sec"),
                    None,
                ),
            )
            return self._apply_readiness_stability(
                annotated_preview,
                bot=readiness_bot,
            )

        # Stopped bot not in preview cache — return lightweight placeholder
        # instead of calling expensive evaluate_bot() on every dashboard poll.
        # Only applies when stopped_preview_lookup is explicitly provided
        # (dashboard context); when None, allow full analysis (tests, non-dashboard).
        if (
            bot_id
            and status not in ACTIVE_POSITION_OWNER_STATUSES
            and stopped_preview_lookup is not None
        ):
            return self._apply_readiness_stability(
                self._annotate_readiness_payload(
                    {"status": "watch", "reason": "preview_unavailable",
                     "reason_text": "Stopped preview pending",
                     "detail": "Readiness preview not yet computed for this bot.",
                     "source": "stopped_placeholder"},
                    source_kind_override="stopped_placeholder",
                ),
                bot=readiness_bot,
            )

        try:
            return self._apply_readiness_stability(
                self._annotate_readiness_payload(
                    readiness_service.evaluate_bot(readiness_bot)
                ),
                bot=readiness_bot,
            )
        except TypeError:
            try:
                return self._apply_readiness_stability(
                    self._annotate_readiness_payload(
                        readiness_service.evaluate_bot(readiness_bot)
                    ),
                    bot=readiness_bot,
                )
            except Exception:
                return {}
        except Exception:
            return {}

    @staticmethod
    def _preview_setup_status(payload: Optional[Dict[str, Any]]) -> str:
        return str(
            (payload or {}).get("setup_timing_status")
            or (payload or {}).get("setup_ready_status")
            or (payload or {}).get("analysis_ready_status")
            or (payload or {}).get("entry_ready_status")
            or ""
        ).strip().lower()

    @classmethod
    def _stopped_preview_refresh_priority(cls, payload: Optional[Dict[str, Any]]) -> int:
        stage = cls._preview_setup_status(payload)
        return {
            "trigger_ready": 0,
            "armed": 1,
            "late": 2,
            "ready": 3,
            "caution": 4,
            "watch": 5,
            "wait": 6,
        }.get(stage, 7)

    def _stopped_preview_time_windows(
        self,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        configured_ttl = max(int(getattr(self, "stopped_preview_ttl_sec", 30) or 0), 5)
        configured_stale = max(
            int(getattr(self, "stopped_preview_stale_sec", configured_ttl) or 0),
            configured_ttl,
        )
        setup_status = self._preview_setup_status(payload)
        grid_tick = max(int(GRID_TICK_SECONDS or 0), 1)
        if setup_status in {"trigger_ready", "armed", "late"}:
            target_ttl = max(grid_tick * 2, 6)
            target_stale = max(target_ttl * 3, 18)
        elif setup_status in {"ready", "caution"}:
            target_ttl = max(grid_tick * 3, 9)
            target_stale = max(target_ttl * 3, 27)
        else:
            target_ttl = max(grid_tick * 6, 18)
            target_stale = max(target_ttl * 3, 60)
        ttl_sec = max(min(configured_ttl, target_ttl), 5)
        stale_sec = max(min(configured_stale, target_stale), ttl_sec + 6)
        aging_after_sec = max(round(ttl_sec * 0.67, 3), min(float(ttl_sec), 6.0))
        return {
            "ttl_sec": float(ttl_sec),
            "stale_sec": float(stale_sec),
            "aging_after_sec": float(aging_after_sec),
        }

    def _annotate_preview_freshness(
        self,
        payload: Dict[str, Any],
        *,
        age_sec: Optional[float],
        windows: Dict[str, float],
        state_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = dict(payload or {})
        preview_age = (
            round(max(float(age_sec or 0.0), 0.0), 3)
            if age_sec is not None
            else None
        )
        preview_state = str(state_override or "").strip().lower()
        if not preview_state:
            if preview_age is None:
                preview_state = "unknown"
            elif preview_age >= float(windows.get("ttl_sec") or 0.0):
                preview_state = "stale"
            elif preview_age >= float(windows.get("aging_after_sec") or 0.0):
                preview_state = "aging"
            else:
                preview_state = "fresh"
        result["readiness_preview_age_sec"] = preview_age
        result["readiness_preview_fresh_ttl_sec"] = round(
            float(windows.get("ttl_sec") or 0.0), 3
        )
        result["readiness_preview_refresh_ttl_sec"] = result[
            "readiness_preview_fresh_ttl_sec"
        ]
        result["readiness_preview_stale_after_sec"] = round(
            float(windows.get("stale_sec") or 0.0), 3
        )
        result["readiness_preview_state"] = preview_state
        return result

    def _build_stopped_preview_lookup(
        self,
        bots: List[Dict[str, Any]],
        cache_only: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        readiness_service = getattr(self, "entry_readiness_service", None)
        if readiness_service is None or not getattr(self, "stopped_preview_enabled", False):
            return {}

        stopped_preview_max_bots = max(
            int(getattr(self, "stopped_preview_max_bots", 0) or 0),
            0,
        )

        now_ts = time.time()
        lookup: Dict[str, Dict[str, Any]] = {}
        candidates: List[Dict[str, Any]] = []
        for bot in bots or []:
            status = str(bot.get("status") or "").strip().lower()
            symbol = str(bot.get("symbol") or "").strip().upper()
            mode = str(bot.get("mode") or "").strip().lower()
            bot_id = str(bot.get("id") or "").strip()
            if not bot_id or not symbol or not mode:
                continue
            if status == "stop_cleanup_pending" or bool(bot.get("stop_cleanup_pending")):
                continue
            if status in ACTIVE_POSITION_OWNER_STATUSES:
                continue
            if symbol == "AUTO-PILOT":
                continue
            candidates.append(bot)

        if not candidates:
            return lookup

        refresh_candidates = []
        for bot in candidates:
            bot_id = str(bot.get("id") or "").strip()
            cached = dict(self._stopped_preview_cache.get(bot_id) or {})
            cached_at = self._safe_float(cached.get("cached_at"), 0.0)
            age_sec = now_ts - cached_at if cached_at > 0 else float("inf")
            cached_payload = dict(cached.get("payload") or {})
            windows = self._stopped_preview_time_windows(cached_payload)
            if cached and age_sec <= windows["ttl_sec"]:
                cached_payload["readiness_source_kind"] = "stopped_preview"
                cached_payload["readiness_preview_cached_at"] = cached_at or None
                cached_payload = self._annotate_preview_freshness(
                    cached_payload,
                    age_sec=(
                        round(max(age_sec, 0.0), 3) if age_sec != float("inf") else None
                    ),
                    windows=windows,
                )
                lookup[bot_id] = cached_payload
                continue
            refresh_candidates.append(
                (
                    self._stopped_preview_refresh_priority(cached_payload),
                    age_sec,
                    bot,
                )
            )

        if cache_only:
            for _, _, bot in refresh_candidates:
                bot_id = str(bot.get("id") or "").strip()
                cached = dict(self._stopped_preview_cache.get(bot_id) or {})
                cached_payload = dict(cached.get("payload") or {})
                if cached_payload:
                    lookup[bot_id] = cached_payload
            return lookup

        refresh_candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
                str(item[2].get("last_run_at") or ""),
                str(item[2].get("symbol") or ""),
                str(item[2].get("id") or ""),
            )
        )

        for _, _, bot in refresh_candidates[:stopped_preview_max_bots]:
            bot_id = str(bot.get("id") or "").strip()
            try:
                payload = readiness_service.evaluate_bot(
                    dict(bot),
                    allow_stopped_analysis_preview=True,
                )
            except TypeError:
                payload = readiness_service.evaluate_bot(dict(bot))
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload:
                payload["readiness_source_kind"] = "stopped_preview"
                payload["readiness_preview_cached_at"] = now_ts
                payload = self._annotate_preview_freshness(
                    payload,
                    age_sec=0.0,
                    windows=self._stopped_preview_time_windows(payload),
                )
                self._stopped_preview_cache[bot_id] = {
                    "payload": dict(payload),
                    "cached_at": now_ts,
                }
                lookup[bot_id] = dict(payload)

        valid_ids = {
            str(bot.get("id") or "").strip()
            for bot in candidates
            if str(bot.get("id") or "").strip()
        }
        for bot_id in list(self._stopped_preview_cache.keys()):
            if bot_id not in valid_ids:
                self._stopped_preview_cache.pop(bot_id, None)

        for bot in candidates:
            bot_id = str(bot.get("id") or "").strip()
            if bot_id in lookup:
                continue
            cached = dict(self._stopped_preview_cache.get(bot_id) or {})
            cached_payload = dict(cached.get("payload") or {})
            cached_at = self._safe_float(cached.get("cached_at"), 0.0)
            age_sec = now_ts - cached_at if cached_at > 0 else float("inf")
            windows = self._stopped_preview_time_windows(cached_payload)
            if cached_payload and age_sec <= windows["stale_sec"]:
                lookup[bot_id] = self._build_stale_stopped_preview_payload(
                    cached_payload,
                    age_sec=age_sec,
                    windows=windows,
                )
            else:
                lookup[bot_id] = self._build_preview_disabled_stopped_payload(bot)

        return lookup

    def _build_stale_stopped_preview_payload(
        self,
        payload: Dict[str, Any],
        *,
        age_sec: float,
        windows: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        result = dict(payload or {})
        windows = windows or self._stopped_preview_time_windows(result)
        detail = "Stopped-bot analysis preview is stale."
        if age_sec == age_sec and age_sec not in (float("inf"),):
            detail = f"{detail} Last refresh {int(max(age_sec, 0))}s ago."
        result.update(
            {
                "entry_ready_status": "watch",
                "entry_ready_reason": "stale_snapshot",
                "entry_ready_reason_text": "Stale snapshot",
                "entry_ready_detail": detail,
                "entry_ready_source": "stopped_preview_stale",
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "stale_snapshot",
                "analysis_ready_reason_text": "Stale snapshot",
                "analysis_ready_detail": detail,
                "analysis_ready_source": "stopped_preview_stale",
                "analysis_ready_severity": "WARN",
                "analysis_ready_next": "Wait for a fresh stopped-bot analysis refresh.",
                "analysis_timing_status": "watch",
                "analysis_timing_reason": "stale_snapshot",
                "analysis_timing_reason_text": "Stale snapshot",
                "analysis_timing_detail": detail,
                "analysis_timing_next": "Wait for a fresh stopped-bot analysis refresh.",
                "analysis_timing_source": "stopped_preview_stale",
                "analysis_timing_actionable": False,
                "analysis_timing_near_trigger": False,
                "analysis_timing_late": False,
                "setup_ready": False,
                "setup_ready_status": "watch",
                "setup_ready_reason": "stale_snapshot",
                "setup_ready_reason_text": "Stale snapshot",
                "setup_ready_detail": detail,
                "setup_ready_source": "stopped_preview_stale",
                "setup_ready_severity": "WARN",
                "setup_ready_next": "Wait for a fresh stopped-bot analysis refresh.",
                "setup_timing_status": "watch",
                "setup_timing_reason": "stale_snapshot",
                "setup_timing_reason_text": "Stale snapshot",
                "setup_timing_detail": detail,
                "setup_timing_next": "Wait for a fresh stopped-bot analysis refresh.",
                "setup_timing_source": "stopped_preview_stale",
                "setup_timing_actionable": False,
                "setup_timing_near_trigger": False,
                "setup_timing_late": False,
                "execution_blocked": False,
                "execution_viability_status": "viable",
                "execution_viability_reason": "openings_clear",
                "execution_viability_reason_text": "Opening clear",
                "execution_viability_bucket": "viable",
                "execution_margin_limited": False,
                "execution_viability_detail": detail,
                "execution_viability_source": "stopped_preview_stale",
                "execution_viability_diagnostic_reason": "stale_snapshot",
                "execution_viability_diagnostic_text": "Stale snapshot",
                "execution_viability_diagnostic_detail": detail,
                "execution_viability_stale_data": True,
                "readiness_stage": "watch",
                "readiness_source_kind": "stopped_preview_stale",
            }
        )
        result = self._annotate_preview_freshness(
            result,
            age_sec=(
                round(max(age_sec, 0.0), 3) if age_sec != float("inf") else None
            ),
            windows=windows,
            state_override="stale",
        )
        return self._annotate_readiness_payload(
            result,
            source_kind_override="stopped_preview_stale",
            source_age_sec=(
                round(max(age_sec, 0.0), 3) if age_sec != float("inf") else None
            ),
        )

    def _build_preview_disabled_stopped_payload(
        self,
        bot: Dict[str, Any],
    ) -> Dict[str, Any]:
        readiness_service = getattr(self, "entry_readiness_service", None)
        if readiness_service is None:
            return {}
        try:
            payload = readiness_service.evaluate_bot(
                dict(bot),
                allow_stopped_analysis_preview=False,
            )
        except TypeError:
            payload = readiness_service.evaluate_bot(dict(bot))
        except Exception:
            payload = {}
        result = dict(payload or {})
        detail = (
            "Stopped-bot analysis preview is bounded and this bot is outside the current preview window."
            if getattr(self, "stopped_preview_enabled", False)
            else "Stopped-bot analysis preview is disabled."
        )
        result.update(
            {
                "analysis_ready_status": "watch",
                "analysis_ready_reason": "preview_disabled",
                "analysis_ready_reason_text": "Preview disabled",
                "analysis_ready_detail": detail,
                "analysis_ready_source": "bounded_preview_disabled",
                "analysis_ready_severity": "INFO",
                "analysis_ready_next": "Wait for this bot to enter the bounded preview window or enable wider preview coverage.",
                "setup_ready": False,
                "setup_ready_status": "watch",
                "setup_ready_reason": "preview_disabled",
                "setup_ready_reason_text": "Preview disabled",
                "setup_ready_detail": detail,
                "setup_ready_source": "bounded_preview_disabled",
                "setup_ready_severity": "INFO",
                "setup_ready_next": "Wait for this bot to enter the bounded preview window or enable wider preview coverage.",
                "readiness_source_kind": "stopped_preview_unavailable",
            }
        )
        result = self._annotate_preview_freshness(
            result,
            age_sec=None,
            windows=self._stopped_preview_time_windows(result),
            state_override="unavailable",
        )
        return self._annotate_readiness_payload(
            result,
            source_kind_override="stopped_preview_unavailable",
            source_age_sec=None,
        )

    @staticmethod
    def _mode_comparison_range_mode(
        bot: Dict[str, Any],
        mode: str,
    ) -> str:
        configured_range = configured_range_mode(bot)
        if mode == "neutral_classic_bybit":
            return "fixed"
        if mode in {"neutral", "scalp_pnl", "scalp_market"}:
            return "dynamic"
        if configured_range in {"dynamic", "trailing"}:
            return configured_range
        return "trailing"

    @staticmethod
    def _mode_comparison_label(mode: str, range_mode: str) -> str:
        if mode == "neutral":
            return "Dynamic Neutral"
        if mode == "neutral_classic_bybit":
            return "Neutral Classic"
        if mode == "scalp_pnl":
            return "Scalp PnL"
        if mode in {"long", "short"}:
            return f"{mode.title()} {range_mode.title()}"
        return mode.replace("_", " ").title()

    def _build_mode_readiness_matrix(
        self,
        bot: Dict[str, Any],
        *,
        configured_readiness: Optional[Dict[str, Any]] = None,
        scanner_recommended_mode: Any = None,
    ) -> Dict[str, Any]:
        readiness_service = getattr(self, "entry_readiness_service", None)
        if readiness_service is None:
            return {"items": []}

        configured = configured_mode(bot)
        configured_range = configured_range_mode(bot)
        effective = normalize_bot_mode(bot.get("effective_runtime_mode") or configured)
        policy = normalize_mode_policy(bot.get("mode_policy"), bot)
        scanner_mode = normalize_bot_mode(scanner_recommended_mode or configured)

        # H7 audit: if stopped bot is outside bounded preview window,
        # return preview_disabled for all candidate modes
        bot_status = str(bot.get("status") or "").lower()
        if bot_status == "stopped":
            _is_outside = False
            _preview_enabled = getattr(self, "stopped_preview_enabled", False)
            if not _preview_enabled:
                _is_outside = True
            else:
                _bot_id = str(bot.get("id") or "").strip()
                _cached = dict((getattr(self, "_stopped_preview_cache", {}) or {}).get(_bot_id) or {})
                _cached_at = self._safe_float(_cached.get("cached_at"), 0.0)
                _age = time.time() - _cached_at if _cached_at > 0 else float("inf")
                _windows = self._stopped_preview_time_windows(_cached.get("payload") or {})
                if _age > _windows.get("stale_sec", 300):
                    _is_outside = True
            if _is_outside:
                return {"items": [
                    {
                        "mode": normalize_bot_mode(m),
                        "status": "watch",
                        "reason": "preview_disabled",
                        "reason_text": "Preview disabled",
                        "detail": "Stopped bot outside bounded preview window.",
                    }
                    for m in MODE_READINESS_MATRIX_ORDER[:5]
                ]}

        candidate_modes: List[str] = []
        for candidate in (
            configured,
            effective,
            scanner_mode,
            *MODE_READINESS_MATRIX_ORDER,
        ):
            normalized = normalize_bot_mode(candidate)
            if normalized not in candidate_modes:
                candidate_modes.append(normalized)

        items = []
        for candidate_mode in candidate_modes[:5]:
            candidate_range_mode = self._mode_comparison_range_mode(bot, candidate_mode)
            if (
                configured_readiness
                and candidate_mode == configured
                and candidate_range_mode == configured_range
            ):
                payload = dict(configured_readiness)
            else:
                candidate_bot = dict(bot or {})
                candidate_bot["mode"] = candidate_mode
                candidate_bot["range_mode"] = candidate_range_mode
                try:
                    payload = self._apply_readiness_stability(
                        self._annotate_readiness_payload(
                            readiness_service.evaluate_bot(dict(candidate_bot))
                        ),
                        bot=candidate_bot,
                        scope=f"mode_matrix:{candidate_mode}:{candidate_range_mode}",
                    )
                except TypeError:
                    try:
                        payload = self._apply_readiness_stability(
                            self._annotate_readiness_payload(
                                readiness_service.evaluate_bot(dict(candidate_bot))
                            ),
                            bot=candidate_bot,
                            scope=f"mode_matrix:{candidate_mode}:{candidate_range_mode}",
                        )
                    except Exception:
                        payload = {}
                except Exception:
                    payload = {}

            status = str(
                payload.get("stable_readiness_stage")
                or payload.get("setup_timing_status")
                or payload.get("setup_ready_status")
                or payload.get("analysis_ready_status")
                or payload.get("entry_ready_status")
                or ""
            ).strip().lower()
            if status == "ready":
                status = "trigger_ready"
            reason = str(
                payload.get("stable_readiness_reason")
                or payload.get("setup_timing_reason")
                or payload.get("setup_ready_reason")
                or payload.get("analysis_ready_reason")
                or payload.get("entry_ready_reason")
                or ""
            ).strip().lower()
            execution_blocked = bool(payload.get("execution_blocked")) or (
                str(payload.get("execution_viability_status") or "").strip().lower()
                == "blocked"
            )
            items.append(
                {
                    "mode": candidate_mode,
                    "range_mode": candidate_range_mode,
                    "label": self._mode_comparison_label(
                        candidate_mode,
                        candidate_range_mode,
                    ),
                    "status": status or "watch",
                    "reason": reason or "preview_unavailable",
                    "reason_text": str(
                        payload.get("stable_readiness_reason_text")
                        or payload.get("setup_timing_reason_text")
                        or payload.get("setup_ready_reason_text")
                        or payload.get("analysis_ready_reason_text")
                        or payload.get("entry_ready_reason_text")
                        or ""
                    ).strip(),
                    "detail": str(
                        payload.get("stable_readiness_detail")
                        or payload.get("setup_timing_detail")
                        or payload.get("setup_ready_detail")
                        or payload.get("analysis_ready_detail")
                        or payload.get("entry_ready_detail")
                        or ""
                    ).strip(),
                    "score": self._safe_float(
                        payload.get("setup_timing_score"),
                        self._safe_float(
                            payload.get("setup_ready_score"),
                            self._safe_float(
                                payload.get("analysis_ready_score"),
                                self._safe_float(payload.get("entry_ready_score"), None),
                            ),
                        ),
                    ),
                    "updated_at": payload.get("stable_readiness_updated_at")
                    or payload.get("setup_timing_updated_at")
                    or payload.get("setup_ready_updated_at")
                    or payload.get("analysis_ready_updated_at")
                    or payload.get("entry_ready_updated_at"),
                    "age_sec": self._safe_float(
                        payload.get("setup_timing_age_sec"),
                        self._safe_float(
                            payload.get("setup_ready_age_sec"),
                            self._safe_float(
                                payload.get("analysis_ready_age_sec"),
                                self._safe_float(
                                    payload.get("entry_ready_age_sec"),
                                    0.0
                                    if payload.get("readiness_evaluated_at")
                                    else None,
                                ),
                            ),
                        ),
                    ),
                    "readiness_source_kind": str(
                        payload.get("readiness_source_kind") or ""
                    ).strip().lower()
                    or None,
                    "preview_state": str(
                        payload.get("readiness_preview_state") or ""
                    ).strip().lower()
                    or None,
                    "execution_blocked": execution_blocked,
                    "execution_viability_status": str(
                        payload.get("execution_viability_status") or ""
                    ).strip().lower()
                    or ("blocked" if execution_blocked else "viable"),
                    "execution_viability_bucket": str(
                        payload.get("execution_viability_bucket") or ""
                    ).strip().lower()
                    or (
                        "margin_limited"
                        if str(payload.get("execution_viability_reason") or "")
                        .strip()
                        .lower()
                        in {"insufficient_margin", "opening_margin_reserve"}
                        else ("blocked" if execution_blocked else "viable")
                    ),
                    "execution_margin_limited": bool(
                        payload.get("execution_margin_limited", False)
                    )
                    or str(payload.get("execution_viability_reason") or "")
                    .strip()
                    .lower()
                    in {"insufficient_margin", "opening_margin_reserve"},
                    "execution_reason": str(
                        payload.get("execution_viability_reason") or ""
                    ).strip().lower()
                    or None,
                    "execution_reason_text": str(
                        payload.get("execution_viability_reason_text") or ""
                    ).strip(),
                    "execution_detail": str(
                        payload.get("execution_viability_detail") or ""
                    ).strip(),
                    "actionable": status == "trigger_ready" and not execution_blocked,
                    "setup_ready": status == "trigger_ready",
                    "near_trigger": status == "armed",
                    "late": status == "late",
                    "setup_ready_fallback_used": bool(
                        payload.get("setup_ready_fallback_used")
                        or payload.get("analysis_ready_fallback_used")
                    ),
                    "readiness_eval_duration_ms": self._safe_float(
                        payload.get("readiness_eval_duration_ms"),
                        None,
                    ),
                    "is_configured_mode": candidate_mode == configured,
                    "is_runtime_view": candidate_mode == effective,
                    "is_scanner_suggestion": candidate_mode == scanner_mode,
                }
            )

        return {
            "configured_mode": configured,
            "configured_range_mode": configured_range,
            "effective_runtime_mode": effective,
            "mode_policy": policy,
            "items": items,
        }

    @staticmethod
    def _build_alternative_mode_summary(
        matrix: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        items = list((matrix or {}).get("items") or [])
        configured_mode = normalize_bot_mode((matrix or {}).get("configured_mode"))
        candidate_items = [
            item
            for item in items
            if str(item.get("mode") or "").strip().lower() != configured_mode
            and str(item.get("status") or "").strip().lower()
            in {"trigger_ready", "armed", "late"}
        ]
        if not candidate_items:
            return {"available": False}

        def _sort_key(item: Dict[str, Any]) -> tuple:
            status = str(item.get("status") or "").strip().lower()
            stage_rank = {
                "trigger_ready": 3,
                "armed": 2,
                "late": 1,
            }.get(status, 0)
            actionable = 1 if bool(item.get("actionable")) else 0
            score = float(item.get("score") or 0.0)
            scanner = 1 if bool(item.get("is_scanner_suggestion")) else 0
            runtime = 1 if bool(item.get("is_runtime_view")) else 0
            return (stage_rank, actionable, score, scanner, runtime)

        best = max(candidate_items, key=_sort_key)
        return {
            "available": True,
            "mode": best.get("mode"),
            "range_mode": best.get("range_mode"),
            "label": best.get("label"),
            "status": best.get("status"),
            "reason": best.get("reason"),
            "reason_text": best.get("reason_text"),
            "detail": best.get("detail"),
            "score": best.get("score"),
            "updated_at": best.get("updated_at"),
            "age_sec": best.get("age_sec"),
            "readiness_source_kind": best.get("readiness_source_kind"),
            "preview_state": best.get("preview_state"),
            "execution_blocked": bool(best.get("execution_blocked")),
            "execution_viability_status": best.get("execution_viability_status"),
            "execution_reason": best.get("execution_reason"),
            "execution_reason_text": best.get("execution_reason_text"),
            "execution_detail": best.get("execution_detail"),
            "actionable": bool(best.get("actionable")),
            "near_trigger": bool(best.get("near_trigger")),
            "late": bool(best.get("late")),
            "is_scanner_suggestion": bool(best.get("is_scanner_suggestion")),
            "is_runtime_view": bool(best.get("is_runtime_view")),
            "setup_ready_fallback_used": bool(best.get("setup_ready_fallback_used")),
        }

    def _extract_trend_direction(self, bot: Dict[str, Any]) -> str:
        """
        Extract structured trend direction from bot data.

        001-trading-bot-audit FR-023: Provides a structured enum field
        instead of parsing freeform trend_status text.

        Args:
            bot: Bot dictionary with scalp_analysis and other fields

        Returns:
            Trend direction: "bullish", "bearish", "neutral", or "unknown"
        """
        # Priority 1: Check scalp_analysis.momentum
        scalp_analysis = bot.get("scalp_analysis") or {}
        momentum = scalp_analysis.get("momentum", "").lower()
        if momentum in ("bullish", "strong_bullish", "rising"):
            return "bullish"
        elif momentum in ("bearish", "strong_bearish", "falling"):
            return "bearish"
        elif momentum in ("neutral", "flat", "sideways"):
            return "neutral"

        # Priority 2: Check direction_signals
        direction_signals = bot.get("direction_signals")
        if isinstance(direction_signals, dict):
            overall = direction_signals.get("overall", "").lower()
        elif isinstance(direction_signals, str):
            overall = direction_signals.lower()
        else:
            overall = ""
        if overall in ("long", "bullish", "buy"):
            return "bullish"
        elif overall in ("short", "bearish", "sell"):
            return "bearish"
        elif overall in ("neutral", "hold"):
            return "neutral"

        # Priority 3: Check mode for directional hint
        mode = bot.get("mode", "").lower()
        if "long" in mode and "neutral" not in mode:
            return "bullish"
        elif "short" in mode and "neutral" not in mode:
            return "bearish"

        # Default to unknown if can't determine
        return "unknown"

    def _get_symbol_pnl_summary(
        self, symbol: str, symbol_pnl_lookup: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Get symbol PnL summary for display.

        Args:
            symbol: Trading symbol
            symbol_pnl_lookup: Dictionary of symbol PnL data

        Returns:
            Summary dict with net_pnl, profit, loss, trade_count, win_rate
        """
        pnl_data = symbol_pnl_lookup.get(symbol, {})

        if not pnl_data:
            return {
                "net_pnl": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "trade_count": 0,
                "win_rate": 0.0,
            }

        trade_count = pnl_data.get("trade_count", 0)
        win_count = pnl_data.get("win_count", 0)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0

        return {
            "net_pnl": round(pnl_data.get("net_pnl", 0.0), 4),
            "total_profit": round(pnl_data.get("total_profit", 0.0), 4),
            "total_loss": round(pnl_data.get("total_loss", 0.0), 4),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 1),
        }

    def _get_bot_pnl_summary(
        self, bot_id: str, bot_pnl_lookup: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Get bot-specific PnL summary for display.
        Each bot has its own P&L tracking, not shared with other bots on same symbol.

        Args:
            bot_id: Bot ID
            bot_pnl_lookup: Dictionary of bot PnL data (keyed by bot_id)

        Returns:
            Summary dict with net_pnl, profit, loss, trade_count, win_rate
        """
        pnl_data = bot_pnl_lookup.get(bot_id, {})

        if not pnl_data:
            return {
                "net_pnl": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "trade_count": 0,
                "win_rate": 0.0,
            }

        trade_count = pnl_data.get("trade_count", 0)
        win_count = pnl_data.get("win_count", 0)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0

        return {
            "net_pnl": round(pnl_data.get("net_pnl", 0.0), 4),
            "total_profit": round(pnl_data.get("total_profit", 0.0), 4),
            "total_loss": round(pnl_data.get("total_loss", 0.0), 4),
            "trade_count": trade_count,
            "win_rate": round(win_rate, 1),
        }

    @staticmethod
    def _calculate_position_profit_pct(
        position_side: str,
        entry_price: float,
        mark_price: float,
        position_size: float,
    ) -> Optional[float]:
        if position_size <= 0 or entry_price <= 0 or mark_price <= 0:
            return None

        side = str(position_side or "").strip().lower()
        if side == "buy":
            return (mark_price - entry_price) / entry_price
        if side == "sell":
            return (entry_price - mark_price) / entry_price
        return None

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """
        Safely convert value to float.

        Args:
            value: Value to convert
            default: Default value if conversion fails

        Returns:
            Float value
        """
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _build_running_bot_ids_by_symbol(
        bots: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        running_bot_ids_by_symbol: Dict[str, List[str]] = {}
        for bot in bots:
            if bot.get("status") not in ACTIVE_POSITION_OWNER_STATUSES:
                continue
            symbol = bot.get("symbol")
            bot_id = bot.get("id")
            if not symbol or not bot_id:
                continue
            running_bot_ids_by_symbol.setdefault(symbol, []).append(bot_id)
        return running_bot_ids_by_symbol

    @staticmethod
    def _build_positions_by_symbol(
        positions_list: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        positions_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for pos in positions_list:
            symbol = pos.get("symbol")
            if not symbol:
                continue
            positions_by_symbol.setdefault(symbol, []).append(
                {
                    "size": pos.get("size", 0.0),
                    "side": pos.get("side", ""),
                    "position_idx": pos.get("position_idx"),
                    "unrealized_pnl": pos.get("unrealized_pnl", 0.0),
                    "entry_price": pos.get("entry_price", 0.0),
                    "mark_price": pos.get("mark_price", 0.0),
                }
            )
        return positions_by_symbol

    def _build_live_open_orders_by_symbol(
        self,
        bots: List[Dict[str, Any]],
        cache_only: bool = False,
        diagnostics: Optional[Dict[str, Any]] = None,
        skip_stream: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        client = getattr(self.position_service, "client", None)
        if client is None:
            return {}

        symbols = self._collect_live_order_symbols(bots)
        if not symbols:
            return {}

        live_orders_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        now = time.monotonic()
        stream_service = getattr(client, "stream_service", None)
        for symbol in symbols:
            cached = self._live_open_orders_cache.get(symbol) or {}
            cached_at = self._safe_float(cached.get("cached_at"), 0.0)
            if cached and (now - cached_at) < self._live_open_orders_cache_ttl_seconds:
                live_orders_by_symbol[symbol] = list(cached.get("orders") or [])
                if diagnostics is not None:
                    diagnostics["cache_hit_count"] = int(diagnostics.get("cache_hit_count") or 0) + 1
                continue

            if cache_only:
                if cached:
                    live_orders_by_symbol[symbol] = list(cached.get("orders") or [])
                    if diagnostics is not None:
                        diagnostics["cache_hit_count"] = int(diagnostics.get("cache_hit_count") or 0) + 1
                continue

            if (
                not skip_stream
                and stream_service is not None
                and hasattr(stream_service, "get_open_orders_fresh")
            ):
                stream_started = time.monotonic()
                try:
                    response = stream_service.get_open_orders_fresh(
                        symbol=symbol,
                        limit=200,
                    )
                except Exception:
                    response = None
                if diagnostics is not None:
                    diagnostics["stream_query_ms"] = round(
                        float(diagnostics.get("stream_query_ms") or 0.0)
                        + max(time.monotonic() - stream_started, 0.0) * 1000.0,
                        3,
                    )
                if response and response.get("success"):
                    data = response.get("data", {}) or {}
                    order_list = data.get("list", []) if isinstance(data, dict) else data
                    if isinstance(order_list, list) and len(order_list) > 0:
                        normalized_orders = list(order_list)
                        live_orders_by_symbol[symbol] = normalized_orders
                        self._live_open_orders_cache[symbol] = {
                            "cached_at": now,
                            "orders": normalized_orders,
                        }
                        if diagnostics is not None:
                            diagnostics["stream_hit_count"] = int(
                                diagnostics.get("stream_hit_count") or 0
                            ) + 1
                        continue
                # Stream empty or failed — fall through to REST for ground truth

            rest_started = time.monotonic()
            try:
                response = client.get_open_orders(
                    symbol=symbol,
                    limit=200,
                    skip_cache=True,
                )
            except Exception:
                if cached:
                    live_orders_by_symbol[symbol] = list(cached.get("orders") or [])
                    if diagnostics is not None:
                        diagnostics["cache_hit_count"] = int(diagnostics.get("cache_hit_count") or 0) + 1
                continue
            if diagnostics is not None:
                diagnostics["rest_call_count"] = int(diagnostics.get("rest_call_count") or 0) + 1
                diagnostics["rest_query_ms"] = round(
                    float(diagnostics.get("rest_query_ms") or 0.0)
                    + max(time.monotonic() - rest_started, 0.0) * 1000.0,
                    3,
                )
            if not response.get("success"):
                if cached:
                    live_orders_by_symbol[symbol] = list(cached.get("orders") or [])
                    if diagnostics is not None:
                        diagnostics["cache_hit_count"] = int(diagnostics.get("cache_hit_count") or 0) + 1
                continue
            data = response.get("data", {}) or {}
            order_list = data.get("list", []) if isinstance(data, dict) else data
            if isinstance(order_list, list):
                normalized_orders = list(order_list)
                live_orders_by_symbol[symbol] = normalized_orders
                self._live_open_orders_cache[symbol] = {
                    "cached_at": now,
                    "orders": normalized_orders,
                }
                if diagnostics is not None:
                    diagnostics["rest_success_count"] = int(
                        diagnostics.get("rest_success_count") or 0
                    ) + 1
        return live_orders_by_symbol

    @staticmethod
    def _parse_live_bot_order_identity(order: Dict[str, Any]) -> Dict[str, Any]:
        order_link_id = str(order.get("orderLinkId") or "").strip()
        reduce_only = bool(order.get("reduceOnly") or order.get("reduce_only"))
        parsed = {
            "bot_id": None,
            "entry": not reduce_only,
            "exit": reduce_only,
        }
        if not order_link_id.startswith("bv2:"):
            return parsed

        parts = order_link_id.split(":")
        if len(parts) >= 2:
            parsed["bot_id"] = parts[1]

        if len(parts) == 5 and parts[4] in ("E", "X"):
            parsed["entry"] = parts[4] == "E"
            parsed["exit"] = parts[4] == "X"
            return parsed

        if len(parts) >= 3:
            suffix = parts[2]
            if suffix.endswith("O"):
                parsed["entry"] = True
                parsed["exit"] = False
            elif suffix.endswith("C"):
                parsed["entry"] = False
                parsed["exit"] = True
        return parsed

    def _get_live_bot_order_counts(
        self,
        bot: Dict[str, Any],
        live_open_orders_by_symbol: Dict[str, List[Dict[str, Any]]],
    ) -> Optional[Dict[str, int]]:
        symbol = str(bot.get("symbol") or "").strip().upper()
        bot_id = str(bot.get("id") or "").replace("-", "").strip()
        if not symbol or not bot_id:
            return None

        orders = live_open_orders_by_symbol.get(symbol)
        if orders is None:
            return None

        bot_id_16 = bot_id[:16]
        entry_open = 0
        exit_open = 0
        total_open = 0

        for order in orders:
            identity = self._parse_live_bot_order_identity(order)
            if identity.get("bot_id") != bot_id_16:
                continue
            total_open += 1
            if identity.get("exit"):
                exit_open += 1
            else:
                entry_open += 1

        return {
            "entry_orders_open": entry_open,
            "exit_orders_open": exit_open,
            "open_order_count": total_open,
        }

    def _is_in_cooldown(self, bot: Dict[str, Any]) -> bool:
        """
        Check if bot is currently in UPnL stop-loss cooldown.

        Args:
            bot: Bot dictionary

        Returns:
            True if in cooldown, False otherwise
        """
        cooldown_until = bot.get("upnl_stoploss_cooldown_until")
        if not cooldown_until:
            return False
        try:
            cooldown_dt = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
            return cooldown_dt > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    def _get_effective_threshold(
        self, bot: Dict[str, Any], symbol: str, field: str
    ) -> Any:
        """
        Get effective UPnL stop-loss threshold for a bot.
        Uses bot's configured value if set, otherwise symbol defaults.

        Args:
            bot: Bot dictionary
            symbol: Trading symbol
            field: Field name (soft_pct, hard_pct, cooldown_seconds)

        Returns:
            Effective threshold value
        """
        # Check bot-level setting first
        bot_field = f"upnl_stoploss_{field}"
        bot_value = bot.get(bot_field)
        if bot_value is not None:
            return bot_value

        # Fall back to symbol defaults
        defaults = get_upnl_stoploss_defaults(symbol)
        return defaults.get(field)

    def get_bot_status(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get enriched status for a single bot.

        Args:
            bot_id: Unique bot identifier

        Returns:
            Enriched bot dictionary or None if not found
        """
        all_bots = self.bot_storage.list_bots()
        running_bot_ids_by_symbol = self._build_running_bot_ids_by_symbol(all_bots)
        bot = next((item for item in all_bots if item.get("id") == bot_id), None)
        if not bot:
            return None
        scanner_lookup = self._get_scanner_recommendation_lookup([bot])

        # Get current positions
        positions_data = self._get_runtime_positions_payload(skip_cache=False)
        positions_list = positions_data.get("positions", [])
        positions_by_symbol = self._build_positions_by_symbol(positions_list)

        # Build position lookup
        position_lookup: Dict[str, Dict[str, Any]] = {}
        for pos in positions_list:
            symbol = pos.get("symbol")
            if symbol:
                position_lookup[symbol] = {
                    "size": pos.get("size", 0.0),
                    "side": pos.get("side", ""),
                    "unrealized_pnl": pos.get("unrealized_pnl", 0.0),
                    "entry_price": pos.get("entry_price", 0.0),
                    "mark_price": pos.get("mark_price", 0.0),
                }

        # Get symbol PnL data
        symbol_pnl_lookup = self.symbol_pnl_service.get_all_symbols_pnl()
        bot_pnl_lookup = self.symbol_pnl_service.get_all_bot_pnl()
        live_open_orders_by_symbol = self._build_live_open_orders_by_symbol(all_bots)

        return self._enrich_bot(
            bot,
            position_lookup,
            positions_by_symbol,
            symbol_pnl_lookup,
            bot_pnl_lookup,
            running_bot_ids_by_symbol,
            scanner_lookup,
            live_open_orders_by_symbol,
        )

    def _get_scanner_recommendation_lookup(
        self, bots: List[Dict[str, Any]], cache_only: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """
        Return cached Neutral Scanner recommendations for active symbol bots.

        The dashboard refreshes every few seconds, so scanner calls are cached
        briefly to avoid recomputing indicators on every poll.
        """
        if not self.neutral_scanner:
            return {}

        active_statuses = {"running", "paused", "recovering"}
        symbols = sorted(
            {
                str(bot.get("symbol") or "").upper()
                for bot in bots
                if bot.get("status") in active_statuses
                and bot.get("symbol")
                and str(bot.get("symbol") or "").strip().lower() != "auto-pilot"
            }
        )
        if not symbols:
            return {}

        now = time.monotonic()
        stale_symbols: List[str] = []
        lookup: Dict[str, Dict[str, Any]] = {}

        for symbol in symbols:
            cached = self._scanner_cache.get(symbol) or {}
            cached_at = self._safe_float(cached.get("cached_at"), 0.0)
            if cached and (now - cached_at) < self.scanner_cache_ttl_seconds:
                lookup[symbol] = cached
            else:
                stale_symbols.append(symbol)

        if stale_symbols:
            if cache_only:
                for symbol in stale_symbols:
                    cached = self._scanner_cache.get(symbol)
                    if cached:
                        lookup[symbol] = cached
                return lookup
            try:
                results = self.neutral_scanner.scan(stale_symbols) or []
                for result in results:
                    symbol = str(result.get("symbol") or "").upper()
                    if not symbol:
                        continue
                    cached = {
                        "recommended_mode": result.get("recommended_mode"),
                        "recommended_range_mode": result.get(
                            "recommended_range_mode"
                        ),
                        "recommended_profile": result.get("recommended_profile"),
                        "regime": result.get("regime"),
                        "trend": result.get("trend"),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "cached_at": now,
                    }
                    self._scanner_cache[symbol] = cached
                    lookup[symbol] = cached
            except Exception:
                for symbol in stale_symbols:
                    cached = self._scanner_cache.get(symbol)
                    if cached:
                        lookup[symbol] = cached

        return lookup

    def get_bot_details(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed bot info including trade history for detail modal.

        Args:
            bot_id: Unique bot identifier

        Returns:
            Detailed bot dictionary with trade history, or None if not found
        """
        # Get base bot status
        bot_status = self.get_bot_status(bot_id)
        if not bot_status:
            return None

        symbol = bot_status.get("symbol", "")

        # Keep raw symbol-wide PnL visible for historical reference.
        symbol_pnl = self.symbol_pnl_service.get_symbol_pnl(symbol) or {}
        performance_summary = self.pnl_service.summarize_logs(bot_id=bot_id, limit=30)
        performance_baseline = (
            self.performance_baseline_service.build_metadata(bot_id=bot_id)
            if self.performance_baseline_service is not None
            else {
                "effective": {
                    "scope": "legacy",
                    "baseline_started_at": None,
                    "epoch_id": None,
                }
            }
        )

        # Get trade history for this bot from PnL service logs
        bot_trades = self.pnl_service.get_log(bot_id=bot_id)
        bot_trades.sort(key=lambda x: x.get("time", ""), reverse=True)
        bot_trades = bot_trades[:100]
        mode_readiness_matrix = self._build_mode_readiness_matrix(
            bot_status,
            scanner_recommended_mode=bot_status.get("scanner_recommended_mode"),
        )

        return {
            **bot_status,
            "mode_readiness_matrix": mode_readiness_matrix,
            "trade_history": bot_trades,
            "trade_history_scope": "bot_only",
            "trade_history_label": "Bot-only trade history since active baseline",
            "performance_summary": performance_summary,
            "performance_baseline": performance_baseline,
            "symbol_total_trades": symbol_pnl.get("trade_count", 0),
            "symbol_recent_trades": symbol_pnl.get("recent_trades", [])[:30],
            "symbol_recent_trades_scope": "symbol_wide",
            "symbol_recent_trades_label": "Symbol-wide recent trades (raw history)",
            "symbol_first_trade_at": symbol_pnl.get("first_trade_at"),
            "symbol_last_trade_at": symbol_pnl.get("last_trade_at"),
            "symbol_bot_ids_used": symbol_pnl.get("bot_ids_used", []),
        }

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics for all bots.

        Returns:
            Summary dictionary with counts and totals
        """
        bots = self.get_runtime_bots()

        total_bots = len(bots)
        running_bots = sum(1 for b in bots if b.get("status") == "running")
        paused_bots = sum(1 for b in bots if b.get("status") == "paused")
        stopped_bots = sum(1 for b in bots if b.get("status") == "stopped")
        error_bots = sum(
            1
            for b in bots
            if b.get("status") in ("error", "risk_stopped", "out_of_range")
        )
        tp_hit_bots = sum(1 for b in bots if b.get("status") == "tp_hit")

        total_investment = sum(
            b.get("investment", 0) for b in bots if b.get("status") == "running"
        )
        total_realized_pnl = sum(b.get("realized_pnl", 0) for b in bots)
        total_unrealized_pnl = sum(b.get("unrealized_pnl", 0) for b in bots)
        total_pnl = total_realized_pnl + total_unrealized_pnl

        return {
            "total_bots": total_bots,
            "running_bots": running_bots,
            "paused_bots": paused_bots,
            "stopped_bots": stopped_bots,
            "error_bots": error_bots,
            "tp_hit_bots": tp_hit_bots,
            "total_investment": round(total_investment, 2),
            "total_realized_pnl": round(total_realized_pnl, 4),
            "total_unrealized_pnl": round(total_unrealized_pnl, 4),
            "total_pnl": round(total_pnl, 4),
        }
