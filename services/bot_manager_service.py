"""
Bybit Control Center - Bot Manager Service

CRUD and lifecycle operations for grid bots.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import copy
import logging
import math
import re
import time

from config.strategy_config import (
    GRID_STEP_PCT,
    DEFAULT_LEVERAGE,
    DEFAULT_INVESTMENT_USDT,
    DEFAULT_GRID_DISTRIBUTION,
    SCALP_DEFAULT_TP_PCT,
    NEUTRAL_DEFAULT_TP_PCT,
    TREND_DEFAULT_TP_PCT,
    SCALP_PNL_TARGET_PROFIT,
    MAX_RISK_PER_BOT_PCT,
    MAX_CAPITAL_PER_SYMBOL_PCT,
    MAX_CAPITAL_PER_SYMBOL_USDT,
    MAX_BOTS_PER_SYMBOL,
    MAX_SYMBOL_SHARE_OF_BOTS_PCT,
    MAX_CONCURRENT_SYMBOLS,
    MAX_CONCURRENT_BOTS,
    ENFORCE_SINGLE_RUNNING_BOT_PER_SYMBOL,
    LAUNCH_AFFORDABILITY_ENABLED,
    LAUNCH_AUTO_RAISE_LEVERAGE,
    LAUNCH_AUTO_CAP_RUNTIME_GRIDS,
    LAUNCH_MIN_ACTIVE_OPEN_ORDERS,
    CAPITAL_PARTITION_ENABLED,
    PROXIMITY_LOW_BALANCE_INVESTMENT_THRESHOLD,
    PROXIMITY_DEFAULT_OPEN_ORDER_CAP_TOTAL,
    PROXIMITY_SCALP_OPEN_ORDER_CAP_TOTAL,
    PROXIMITY_LOW_BALANCE_OPEN_ORDER_CAP_TOTAL,
    PROXIMITY_LOW_BALANCE_SCALP_OPEN_ORDER_CAP_TOTAL,
    FAST_EXEC_TAKER_FEE_RATE,
    FAST_EXEC_SLIPPAGE_BUFFER_PCT,
    FEE_AWARE_MIN_STEP_BUFFER_PCT,
    SYMBOL_DAILY_KILL_SWITCH_ENABLED,
    SYMBOL_DAILY_KILL_SWITCH_LOSS_PCT_OF_INVESTMENT,
    SYMBOL_DAILY_KILL_SWITCH_MIN_USDT,
    SYMBOL_DAILY_KILL_SWITCH_MAX_USDT,
    AUTO_MARGIN_PRESET_NAME,
    get_auto_margin_defaults,
    get_upnl_stoploss_defaults,
    # Long mode quick profit constants
    LONG_QUICK_PROFIT_ENABLED,
    LONG_QUICK_PROFIT_TARGET,
    LONG_QUICK_PROFIT_CLOSE_PCT,
    LONG_QUICK_PROFIT_COOLDOWN_SEC,
    # Neutral mode gate
    NEUTRAL_GATE_ENABLED,
    NEUTRAL_MAJOR_SYMBOLS,
    NEUTRAL_GATE_RECHECK_SECONDS,
    # Entry gate (long/short)
    ENTRY_GATE_RECHECK_SECONDS,
    AUTO_PILOT_UNIVERSE_MODE,
    normalize_auto_pilot_universe_mode,
)
from services.bot_storage_service import BotStorageService
from services.bybit_client import BybitClient
from services.audit_diagnostics_service import AuditDiagnosticsService
from services.control_timing_service import (
    elapsed_ms,
    ensure_bot_timing_scope,
    iso_from_ts,
    now_ts,
    update_bot_timing,
)
from services.mode_semantics import (
    configured_mode as resolve_configured_mode,
    configured_range_mode as resolve_configured_range_mode,
    normalize_mode_policy,
)
from services.order_ownership_service import build_order_ownership_snapshot

logger = logging.getLogger(__name__)

DEFAULT_GRID_COUNT = 10
SESSION_TIMER_TIME_ONLY_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")
SESSION_TIMER_END_MODES = {
    "hard_stop",
    "soft_stop",
    "green_grace_then_stop",
}
SUPPORTED_BOT_MODES = (
    "neutral",
    "long",
    "short",
    "scalp_pnl",
    "scalp_market",
    "neutral_classic_bybit",
)
ACTIVE_SYMBOL_CONTROL_STATUSES = {
    "running",
    "paused",
    "recovering",
    "flash_crash_paused",
    "stop_cleanup_pending",
}


class BotManagerService:
    """
    Service for managing grid bot lifecycle and configuration.
    """

    def __init__(
        self,
        client: BybitClient,
        bot_storage: BotStorageService,
        risk_manager: Optional[Any] = None,
        account_service: Optional[Any] = None
    ):
        """
        Initialize the bot manager service.

        Args:
            client: Initialized BybitClient instance
            bot_storage: BotStorageService for persisting bot data
            risk_manager: Optional RiskManagerService for pre-launch validation
            account_service: Optional AccountService for fetching equity
        """
        self.client = client
        self.bot_storage = bot_storage
        self.risk_manager = risk_manager
        self.account_service = account_service
        self.audit_diagnostics_service = AuditDiagnosticsService()

    def _emit_capital_compression_snapshot(
        self,
        bot: Dict[str, Any],
        launch_analysis: Optional[Dict[str, Any]],
        *,
        symbol: str,
        mode: str,
    ) -> None:
        diagnostics_service = getattr(self, "audit_diagnostics_service", None)
        if diagnostics_service is None or not diagnostics_service.enabled():
            return
        analysis = launch_analysis if isinstance(launch_analysis, dict) else {}
        requested_investment = self._safe_float(
            analysis.get("requested_investment"),
            self._safe_float(bot.get("investment"), 0.0),
        )
        effective_investment = self._safe_float(
            analysis.get("capital_partition_usdt"),
            requested_investment,
        )
        reserve_usdt = self._safe_float(analysis.get("reserve_usdt"), 0.0)
        usable_investment = self._safe_float(analysis.get("usable_investment"), 0.0)
        capital_partition_effect = max(0.0, requested_investment - effective_investment)
        compression_active = capital_partition_effect > 0.01 or reserve_usdt > 0.0
        summary = bot.get("watchdog_bottleneck_summary")
        if not isinstance(summary, dict):
            summary = {}
            bot["watchdog_bottleneck_summary"] = summary
        summary["capital_compression_snapshot_count"] = int(
            summary.get("capital_compression_snapshot_count", 0) or 0
        ) + 1
        summary["capital_compression_active"] = compression_active
        summary["last_requested_investment_usdt"] = (
            round(requested_investment, 4) if requested_investment > 0 else None
        )
        summary["last_effective_investment_usdt"] = (
            round(effective_investment, 4) if effective_investment > 0 else None
        )
        summary["last_runtime_grid_count_cap"] = int(
            self._safe_float(bot.get("runtime_grid_count_cap"), 0) or 0
        ) or None
        summary["last_runtime_open_order_cap_total"] = int(
            self._safe_float(bot.get("runtime_open_order_cap_total"), 0) or 0
        ) or None
        summary["capital_starved_by_effective_capital"] = bool(
            requested_investment > 0 and effective_investment + 0.01 < requested_investment
        )
        summary["updated_at"] = datetime.now(timezone.utc).isoformat()

        payload = {
            "event_type": "capital_compression_snapshot",
            "severity": "WARN" if compression_active else "INFO",
            "symbol": symbol,
            "bot_id": bot.get("id"),
            "mode": mode,
            "requested_investment": round(requested_investment, 4)
            if requested_investment > 0
            else None,
            "effective_investment": round(effective_investment, 4)
            if effective_investment > 0
            else None,
            "capital_partition_effect": round(capital_partition_effect, 4),
            "capital_partition_usdt": round(effective_investment, 4)
            if effective_investment > 0
            else None,
            "reserve_effect": round(reserve_usdt, 4),
            "reserve_usdt": round(reserve_usdt, 4) if reserve_usdt > 0 else 0.0,
            "usable_investment": round(usable_investment, 4)
            if usable_investment > 0
            else None,
            "leverage": self._safe_float(
                analysis.get("effective_leverage"),
                self._safe_float(bot.get("leverage"), 0.0),
            ),
            "grid_count": int(
                self._safe_float(
                    analysis.get("requested_grid_count"),
                    bot.get("grid_count"),
                )
                or 0
            )
            or None,
            "runtime_grid_count_cap": int(
                self._safe_float(bot.get("runtime_grid_count_cap"), 0) or 0
            )
            or None,
            "open_order_cap_total": int(
                self._safe_float(bot.get("runtime_open_order_cap_total"), 0) or 0
            )
            or None,
            "capital_compression_active": compression_active,
        }
        diagnostics_service.record_event(
            payload,
            throttle_key=f"capital_compression:{bot.get('id') or symbol}:{mode}",
            throttle_sec=0,
        )

    @staticmethod
    def _next_control_version(bot: Dict[str, Any]) -> int:
        try:
            return int(bot.get("control_version") or 0) + 1
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _next_settings_version(bot: Dict[str, Any]) -> int:
        try:
            return int(bot.get("settings_version") or 0) + 1
        except (TypeError, ValueError):
            return 1

    def _mark_control_state_change(self, bot: Dict[str, Any]) -> None:
        bot["control_version"] = self._next_control_version(bot)
        bot["control_updated_at"] = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _record_control_stage(
        bot: Optional[Dict[str, Any]],
        scope: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        return update_bot_timing(bot, scope, **fields)

    def _mark_bot_stopped_state(
        self,
        bot: Dict[str, Any],
        *,
        scope: str,
        action_received_at_ts: Optional[float] = None,
        cancel_orders: bool = True,
    ) -> Dict[str, Any]:
        if bot.get("status") in ("running", "paused", "recovering"):
            self._update_accumulated_runtime(bot)

        control_started_at = (
            self._safe_float(action_received_at_ts, 0.0) or now_ts()
        )
        stop_time_ts = now_ts()
        stop_time_iso = iso_from_ts(stop_time_ts)

        self._mark_control_state_change(bot)
        bot["status"] = "stopped"
        bot["started_at"] = None
        bot["last_run_at"] = stop_time_iso
        self._clear_entry_gate_runtime_state(bot)
        self._record_control_stage(
            bot,
            scope,
            control_action_kind=scope,
            control_action_received_at=iso_from_ts(control_started_at),
            stop_state_persisted_at=stop_time_iso,
            control_action_to_stop_state_ms=elapsed_ms(
                control_started_at,
                stop_time_ts,
            ),
        )
        self.bot_storage.save_bot(bot)

        symbol = bot.get("symbol")
        cancel_result = None
        if cancel_orders and self._is_tradeable_symbol(symbol):
            if bot.get("mode") == "neutral_classic_bybit":
                cancel_result = self._cancel_neutral_bot_orders(
                    bot,
                    symbol,
                    cancel_all=True,
                )
            else:
                cancel_result = self._cancel_all_bot_orders(bot, symbol)
            self._record_control_stage(
                bot,
                scope,
                stop_cancel_result=cancel_result,
            )

        bot["entry_orders_open"] = 0
        bot["exit_orders_open"] = 0
        bot["open_order_count"] = 0
        bot["active_long_slots"] = 0
        bot["active_short_slots"] = 0
        bot["status"] = "stopped"
        bot["started_at"] = None
        bot["last_run_at"] = stop_time_iso
        return self.bot_storage.save_bot(bot)

    @staticmethod
    def _clear_stop_cleanup_pending_fields(bot: Dict[str, Any]) -> None:
        for key in (
            "stop_cleanup_pending",
            "stop_cleanup_target_status",
            "stop_cleanup_scope",
            "stop_cleanup_reason",
            "stop_cleanup_requested_at",
            "stop_cleanup_final_last_error",
        ):
            bot.pop(key, None)

    def _mark_bot_stop_cleanup_pending_state(
        self,
        bot: Dict[str, Any],
        *,
        scope: str,
        target_status: str,
        action_received_at_ts: Optional[float] = None,
        pending_message: Optional[str] = None,
        final_last_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        if bot.get("status") in ("running", "paused", "recovering"):
            self._update_accumulated_runtime(bot)

        control_started_at = (
            self._safe_float(action_received_at_ts, 0.0) or now_ts()
        )
        pending_ts = now_ts()
        pending_iso = iso_from_ts(pending_ts)

        self._mark_control_state_change(bot)
        self._clear_pause_runtime_state(bot)
        self._clear_stop_cleanup_pending_fields(bot)
        self._clear_entry_gate_runtime_state(bot)
        bot["status"] = "stop_cleanup_pending"
        bot["started_at"] = None
        bot["last_run_at"] = pending_iso
        bot["reduce_only_mode"] = True
        bot["auto_stop_paused"] = True
        bot["pause_reason"] = "Stop cleanup pending"
        bot["pause_reason_type"] = "stop_cleanup_pending"
        bot["stop_cleanup_pending"] = True
        bot["stop_cleanup_target_status"] = str(target_status or "stopped").strip().lower() or "stopped"
        bot["stop_cleanup_scope"] = scope
        bot["stop_cleanup_reason"] = scope
        bot["stop_cleanup_requested_at"] = pending_iso
        bot["stop_cleanup_final_last_error"] = final_last_error
        if pending_message is not None:
            bot["last_error"] = pending_message
        self._record_control_stage(
            bot,
            scope,
            control_action_kind=scope,
            control_action_received_at=iso_from_ts(control_started_at),
            cleanup_pending_persisted_at=pending_iso,
            cleanup_pending=True,
            cleanup_target_status=bot["stop_cleanup_target_status"],
            control_action_to_cleanup_pending_ms=elapsed_ms(
                control_started_at,
                pending_ts,
            ),
        )
        return self.bot_storage.save_bot(bot)

    def _finalize_bot_stop_cleanup_state(
        self,
        bot: Dict[str, Any],
        *,
        scope: str,
        final_status: str,
    ) -> Dict[str, Any]:
        finalized_ts = now_ts()
        finalized_iso = iso_from_ts(finalized_ts)
        final_last_error = bot.get("stop_cleanup_final_last_error")

        self._mark_control_state_change(bot)
        self._clear_pause_runtime_state(bot)
        self._clear_stop_cleanup_pending_fields(bot)
        bot["status"] = str(final_status or "stopped").strip().lower() or "stopped"
        bot["started_at"] = None
        bot["last_run_at"] = finalized_iso
        bot["reduce_only_mode"] = False
        bot["auto_stop_paused"] = False
        bot["entry_orders_open"] = 0
        bot["exit_orders_open"] = 0
        bot["open_order_count"] = 0
        bot["active_long_slots"] = 0
        bot["active_short_slots"] = 0
        bot["last_error"] = final_last_error
        # Reset auto-pilot symbol to placeholder on any stop path
        if bot.get("auto_pilot"):
            sym = str(bot.get("symbol") or "").strip()
            if sym and sym.lower() != "auto-pilot":
                bot["symbol"] = "Auto-Pilot"
                self._reset_auto_pilot_placeholder_runtime_state(bot)
        self._record_control_stage(
            bot,
            scope,
            cleanup_finalized_at=finalized_iso,
            cleanup_pending=False,
            final_status=bot["status"],
        )
        return self.bot_storage.save_bot(bot)

    def _mark_settings_state_change(self, bot: Dict[str, Any]) -> None:
        bot["settings_version"] = self._next_settings_version(bot)
        bot["settings_updated_at"] = datetime.now(timezone.utc).isoformat()

    def _clear_auto_stop_target_runtime_state(self, bot: Dict[str, Any]) -> None:
        bot["auto_stop_target_effective_usdt"] = 0.0
        bot["auto_stop_target_session_base_usdt"] = None
        bot["auto_stop_target_rearm_on_start"] = False
        bot["auto_stop_armed"] = False

    @staticmethod
    def _supports_auto_direction_mode(mode: str) -> bool:
        return mode in ("neutral", "long", "short")

    @staticmethod
    def _supports_breakout_confirmed_entry(mode: str) -> bool:
        return mode in ("long", "short")

    @staticmethod
    def _supports_trailing_stop_mode(mode: str) -> bool:
        return mode in ("neutral", "long", "short")

    @staticmethod
    def _supports_quick_profit(mode: str, range_mode: str) -> bool:
        return mode in ("neutral", "long", "short") and range_mode in (
            "dynamic",
            "trailing",
        )

    @staticmethod
    def _supports_volatility_gate(mode: str) -> bool:
        return mode == "neutral_classic_bybit"

    @staticmethod
    def _is_auto_pilot_placeholder_symbol(symbol: Any) -> bool:
        return str(symbol or "").strip().lower() == "auto-pilot"

    @classmethod
    def _is_tradeable_symbol(cls, symbol: Any) -> bool:
        normalized = str(symbol or "").strip()
        return bool(normalized) and not cls._is_auto_pilot_placeholder_symbol(
            normalized
        )

    @classmethod
    def _normalize_mode_scoped_settings(cls, bot_data: Dict[str, Any]) -> None:
        mode = (bot_data.get("mode") or "neutral").lower()
        range_mode = (bot_data.get("range_mode") or "fixed").lower()

        if not cls._supports_auto_direction_mode(mode):
            bot_data["auto_direction"] = False

        if not cls._supports_breakout_confirmed_entry(mode):
            bot_data["breakout_confirmed_entry"] = False

        if not cls._supports_trailing_stop_mode(mode):
            bot_data["trailing_sl_enabled"] = False
            bot_data["trailing_sl_activation_pct"] = None
            bot_data["trailing_sl_distance_pct"] = None
            bot_data["trailing_sl_price"] = None
            bot_data["trailing_sl_activated"] = False

        if not cls._supports_quick_profit(mode, range_mode):
            bot_data["quick_profit_enabled"] = False

        if not cls._supports_volatility_gate(mode):
            bot_data["neutral_volatility_gate_enabled"] = False

        # Directional modes default BTC correlation filter OFF
        if mode in ("long", "short"):
            bot_data.setdefault("btc_correlation_filter_enabled", False)

    def _set_auto_stop_target_config(self, bot: Dict[str, Any], target: Any) -> None:
        target_value = self._safe_float(target, 0.0)
        if target_value <= 0:
            bot["auto_stop_target_usdt"] = 0.0
            bot["auto_stop_triggered"] = False
            self._clear_auto_stop_target_runtime_state(bot)
            return

        bot["auto_stop_target_usdt"] = target_value
        bot["auto_stop_triggered"] = False
        bot["auto_stop_target_effective_usdt"] = target_value
        bot["auto_stop_target_session_base_usdt"] = None
        bot["auto_stop_target_rearm_on_start"] = False
        bot["auto_stop_armed"] = True

    def _arm_auto_stop_target_for_session(
        self, bot: Dict[str, Any], current_balance: Any
    ) -> None:
        target_value = self._safe_float(bot.get("auto_stop_target_usdt"), 0.0)
        if target_value <= 0:
            bot["auto_stop_triggered"] = False
            self._clear_auto_stop_target_runtime_state(bot)
            return

        balance_value = max(0.0, self._safe_float(current_balance, 0.0))
        should_rearm = bool(bot.get("auto_stop_target_rearm_on_start")) or bool(
            bot.get("auto_stop_triggered")
        )

        if should_rearm:
            bot["auto_stop_target_session_base_usdt"] = balance_value
            bot["auto_stop_target_effective_usdt"] = balance_value + target_value
        else:
            effective_target = self._safe_float(
                bot.get("auto_stop_target_effective_usdt"), 0.0
            )
            if effective_target <= 0:
                bot["auto_stop_target_effective_usdt"] = target_value
                bot["auto_stop_target_session_base_usdt"] = None

        bot["auto_stop_triggered"] = False
        bot["auto_stop_target_rearm_on_start"] = False
        effective_target = self._safe_float(
            bot.get("auto_stop_target_effective_usdt"), target_value
        )
        bot["auto_stop_armed"] = balance_value < effective_target

    def _reset_session_runtime_state(self, bot: Dict[str, Any]) -> None:
        """
        Clear transient runtime guards when a bot starts a fresh session.

        These fields are derived from recent runtime conditions and should not
        survive an intentional start/resume after the user changed settings.
        """
        bot["_failure_breaker"] = None
        bot["_block_opening_orders"] = False
        bot["_nlp_block_opening_orders"] = False
        bot["_session_timer_block_opening_orders"] = False
        bot["_skip_new_orders_for_margin"] = False
        bot["_skip_opening_orders_for_margin"] = False
        bot["last_skip_reason"] = None
        bot["last_warning"] = None
        bot["scalp_learned_opening_order_cap"] = None
        bot["scalp_learned_opening_cap_at"] = None
        bot["scalp_learned_opening_cap_reason"] = None
        bot["session_timer_state"] = "inactive"
        bot["session_timer_started_at"] = None
        bot["session_timer_pre_stop_at"] = None
        bot["session_timer_end_triggered_at"] = None
        bot["session_timer_grace_started_at"] = None
        bot["session_timer_grace_expires_at"] = None
        bot["session_timer_completed_at"] = None
        bot["session_timer_completed_reason"] = None
        bot["session_timer_last_event"] = None
        bot["session_timer_no_new_entries_active"] = False
        bot["_session_timer_skip_expired_absolute_window"] = False
        if bot.get("session_timer_reduce_only_active"):
            bot["reduce_only_mode"] = False
            bot["auto_stop_paused"] = False
        bot["session_timer_reduce_only_active"] = False

    @staticmethod
    def _normalize_session_datetime_input(value: Any) -> Optional[str]:
        raw = str(value or "").strip()
        if not raw:
            return None
        if SESSION_TIMER_TIME_ONLY_RE.fullmatch(raw):
            return raw
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception as exc:
            raise ValueError(f"Invalid session timer datetime: {raw}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat()

    @staticmethod
    def _clear_entry_gate_runtime_state(bot: Dict[str, Any]) -> None:
        """Clear stale directional/neutral gate and breakout runtime fields."""
        if not bot:
            return
        bot["_entry_gate_blocked"] = False
        bot.pop("_entry_gate_blocked_until", None)
        bot.pop("_entry_gate_blocked_reason", None)
        bot["_entry_structure_skip_buy"] = False
        bot["_entry_structure_skip_sell"] = False
        bot.pop("_entry_structure_buy_reason", None)
        bot.pop("_entry_structure_sell_reason", None)
        bot.pop("_gate_blocked_until", None)
        bot.pop("_gate_blocked_reason", None)
        bot["breakout_entry_confirmed"] = False
        bot["breakout_entry_mode"] = None
        bot["breakout_entry_confirmed_at"] = None
        bot["breakout_reference_level"] = None
        bot["breakout_reference_type"] = None
        bot["breakout_required_close"] = None
        bot["breakout_no_chase_blocked"] = False
        bot["breakout_no_chase_reason"] = None

    def _suppress_expired_absolute_session_window_on_manual_start(
        self,
        bot: Dict[str, Any],
        *,
        now_dt: Optional[datetime] = None,
    ) -> None:
        if not bool(bot.get("session_timer_enabled")):
            bot["_session_timer_skip_expired_absolute_window"] = False
            return

        stop_raw = str(bot.get("session_stop_at") or "").strip()
        if not stop_raw or SESSION_TIMER_TIME_ONLY_RE.fullmatch(stop_raw):
            bot["_session_timer_skip_expired_absolute_window"] = False
            return

        try:
            stop_dt = datetime.fromisoformat(stop_raw.replace("Z", "+00:00"))
        except Exception:
            bot["_session_timer_skip_expired_absolute_window"] = False
            return

        if stop_dt.tzinfo is None:
            stop_dt = stop_dt.replace(tzinfo=timezone.utc)
        else:
            stop_dt = stop_dt.astimezone(timezone.utc)

        effective_now = now_dt or datetime.now(timezone.utc)
        if stop_dt > effective_now:
            bot["_session_timer_skip_expired_absolute_window"] = False
            return

        bot["_session_timer_skip_expired_absolute_window"] = True
        bot["session_timer_state"] = "inactive"
        bot["session_timer_started_at"] = None
        bot["session_timer_pre_stop_at"] = None
        bot["session_timer_end_triggered_at"] = None
        bot["session_timer_grace_started_at"] = None
        bot["session_timer_grace_expires_at"] = None
        bot["session_timer_completed_at"] = None
        bot["session_timer_completed_reason"] = "expired_window_skipped_on_manual_start"
        bot["session_timer_last_event"] = "expired_window_skipped_on_manual_start"
        bot["session_timer_no_new_entries_active"] = False
        bot["_session_timer_block_opening_orders"] = False
        bot["last_warning"] = "Expired session window skipped on manual start"
        bot["entry_signal_code"] = None
        bot["entry_signal_label"] = None
        bot["entry_signal_phase"] = None
        bot["entry_signal_detail"] = None
        bot["entry_signal_preferred"] = False
        bot["entry_signal_late"] = False
        bot["entry_signal_executable"] = False
        bot["entry_signal_aligned"] = False
        bot["entry_signal_extension_ratio"] = None
        bot.pop("_breakout_gate_context", None)
        bot.pop("_breakout_entry_pending_context", None)
        bot.pop("_audit_first_valid_entry_ts", None)
        bot.pop("_audit_actual_entry_ts", None)

    @staticmethod
    def _normalize_mode_range_state(bot: Dict[str, Any]) -> None:
        """Keep one canonical range key family per mode and drop dead aliases."""
        if not bot:
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

    def _refresh_activation_gate_state(
        self,
        bot: Dict[str, Any],
        symbol: str,
        indicator_service: Any,
    ) -> None:
        """Rebuild gate state on start/resume from fresh live checks."""
        if not bot or not symbol or indicator_service is None:
            return
        self._clear_entry_gate_runtime_state(bot)

        mode = str(bot.get("mode") or "").strip().lower()
        now = time.time()
        if mode == "neutral_classic_bybit" and NEUTRAL_GATE_ENABLED:
            try:
                from services.neutral_suitability_service import NeutralSuitabilityService

                gate_service = NeutralSuitabilityService(indicator_service)
                gate_result = gate_service.check_suitability(
                    symbol=symbol,
                    preset=bot.get("neutral_preset"),
                )
                if not gate_result.get("suitable", True) and bot.get(
                    "entry_gate_enabled", True
                ):
                    bot["_nlp_block_opening_orders"] = True
                    bot["_gate_blocked_until"] = now + NEUTRAL_GATE_RECHECK_SECONDS
                    bot["_gate_blocked_reason"] = gate_result.get("reason")
                    logger.warning(
                        "[%s] NEUTRAL_GATE blocking orders on activation: %s",
                        symbol,
                        gate_result.get("reason"),
                    )
            except Exception as gate_err:
                logger.warning(
                    "[%s] Gate check failed on activation (allowing run): %s",
                    symbol,
                    gate_err,
                )

        if mode in ("long", "short"):
            try:
                from services.entry_gate_service import EntryGateService

                entry_gate = EntryGateService(indicator_service)
                gate_result = entry_gate.check_entry(
                    symbol=symbol,
                    mode=mode,
                    bot=bot,
                )
                if not gate_result.get("suitable", True) and bot.get(
                    "entry_gate_enabled", True
                ):
                    bot["_entry_gate_blocked"] = True
                    bot["_entry_gate_blocked_until"] = (
                        now + ENTRY_GATE_RECHECK_SECONDS
                    )
                    bot["_entry_gate_blocked_reason"] = gate_result.get("reason")
                    logger.warning(
                        "[%s] ENTRY_GATE blocking orders on activation (%s): %s",
                        symbol,
                        mode,
                        gate_result.get("reason"),
                    )
                else:
                    entry_gate.clear_blocked(bot)
            except Exception as entry_gate_err:
                logger.warning(
                    "[%s] Entry gate check failed on activation (allowing run): %s",
                    symbol,
                    entry_gate_err,
                )

    @classmethod
    def _reset_auto_pilot_placeholder_runtime_state(
        cls, bot: Dict[str, Any]
    ) -> None:
        if not cls._is_auto_pilot_placeholder_symbol(bot.get("symbol")):
            return

        bot["lower_price"] = None
        bot["upper_price"] = None
        bot["grid_lower_price"] = None
        bot["grid_upper_price"] = None
        bot["grid_levels_total"] = None
        bot["current_price"] = 0.0
        bot["current_price_updated_at"] = None
        bot["current_price_source"] = None
        bot["current_price_transport"] = None
        bot["current_price_exchange_ts"] = None
        bot["current_price_exchange_at"] = None
        bot["last_trade_price"] = None
        bot["open_order_count"] = 0
        bot["entry_orders_open"] = 0
        bot["exit_orders_open"] = 0
        bot["active_long_slots"] = 0
        bot["active_short_slots"] = 0
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False
        bot["neutral_grid_last_reconcile_at"] = None
        bot["grid_levels_total_effective"] = None
        bot["levels_count"] = None
        bot["mid_index"] = None
        bot["last_fill_event"] = None
        bot["last_replacement_action"] = None
        bot["_last_recenter_ts"] = None
        bot["_position_mode"] = None
        bot["_position_mode_ts"] = None
        # Clear entry gate state first, then set explicit None values
        # (order matters: _clear_entry_gate_runtime_state pops these keys)
        cls._clear_entry_gate_runtime_state(bot)
        bot["_entry_structure_skip_buy"] = False
        bot["_entry_structure_skip_sell"] = False
        bot["_entry_structure_buy_reason"] = None
        bot["_entry_structure_sell_reason"] = None

    def _ensure_upnl_stoploss_fields(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure UPnL stop-loss fields exist on a bot (migration for existing bots).

        Args:
            bot: Bot dictionary

        Returns:
            Bot dictionary with UPnL SL fields added if missing
        """
        if "upnl_stoploss_enabled" not in bot:
            # Migration: Add UPnL SL fields with enabled=False (disabled globally)
            bot["upnl_stoploss_enabled"] = False
            bot["upnl_stoploss_soft_pct"] = None
            bot["upnl_stoploss_hard_pct"] = None
            bot["upnl_stoploss_k1"] = None
            bot["upnl_stoploss_liq_pct"] = None
            bot["upnl_stoploss_basis"] = "used_margin"
            bot["upnl_stoploss_cooldown_seconds"] = None
            bot["upnl_stoploss_close_mode"] = "reduce_only_market"
            bot["upnl_stoploss_close_on_soft"] = False
            bot["upnl_stoploss_cooldown_until"] = None
            bot["upnl_stoploss_last_trigger"] = None
            bot["upnl_stoploss_trigger_count"] = 0

            symbol = bot.get("symbol", "unknown")
            defaults = get_upnl_stoploss_defaults(symbol)
            logger.info(
                f"[{symbol}] Migrated bot {bot.get('id', 'unknown')[:8]} with UPnL SL disabled "
                f"(defaults: soft={defaults['soft_pct']}%, hard={defaults['hard_pct']}%, "
                f"cooldown={defaults['cooldown_seconds']}s)"
            )
        return bot

    def _force_cancel_all_orders(self, symbol: str, max_retries: int = 5) -> Dict[str, Any]:
        """
        Forcefully cancel all orders for a symbol with aggressive retry.

        Args:
            symbol: Trading pair symbol
            max_retries: Maximum number of cancel attempts (increased default)

        Returns:
            Dict with success status and details
        """
        import time

        if not self._is_tradeable_symbol(symbol):
            return {"success": True, "cancelled": 0, "skipped": True}

        overall_started_at = now_ts()
        cancelled_count = 0
        remaining_count = 0
        first_cancel_timing = None

        for attempt in range(max_retries):
            # First, try standard cancel all
            cancel_result = self.client.cancel_all_orders(symbol)
            if first_cancel_timing is None:
                first_cancel_timing = dict((cancel_result or {}).get("timing") or {})
            if not cancel_result.get("success"):
                logger.warning(f"[{symbol}] Cancel attempt {attempt + 1} failed: {cancel_result.get('error')}")
            
            # Small delay to let exchange process
            time.sleep(0.3)

            # Verification step
            orders_result = self.client.get_open_orders(
                symbol=symbol,
                limit=200,
                skip_cache=True,
            )
            if orders_result.get("success"):
                orders = orders_result.get("data", {}).get("list", []) or []
                remaining_count = len(orders)
                
                if remaining_count == 0:
                    logger.info(f"[{symbol}] ✓ All orders cancelled (verified on attempt {attempt + 1})")
                    return {
                        "success": True,
                        "cancelled": cancelled_count,
                        "timing": {
                            **(first_cancel_timing or {}),
                            "cancel_total_ms": elapsed_ms(overall_started_at, now_ts()),
                            "cancel_attempts": attempt + 1,
                            "cancel_verification_completed_at": iso_from_ts(),
                        },
                    }
                
                logger.warning(f"[{symbol}] {remaining_count} orders remaining after attempt {attempt + 1}, retrying...")
                
                # Aggressive individual cancellation if bulk fails
                for order in orders:
                    try:
                        oid = order.get("orderId")
                        if oid:
                            self.client.cancel_order(symbol, order_id=oid)
                    except Exception:
                        pass
            else:
                logger.warning(f"[{symbol}] Failed to fetch open orders for verification")

        return {
            "success": False,
            "error": "orders_remaining_after_retries",
            "remaining": remaining_count,
            "timing": {
                **(first_cancel_timing or {}),
                "cancel_total_ms": elapsed_ms(overall_started_at, now_ts()),
                "cancel_attempts": max_retries,
                "cancel_verification_completed_at": iso_from_ts(),
            },
        }

    def _get_other_active_bots_for_symbol(
        self,
        *,
        symbol: str,
        exclude_bot_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self._is_tradeable_symbol(symbol):
            return []
        try:
            bots = self.bot_storage.list_bots()
        except Exception as exc:
            logger.warning("[%s] Failed to inspect sibling bots: %s", symbol, exc)
            return []

        siblings = []
        for candidate in bots:
            if candidate.get("id") == exclude_bot_id:
                continue
            if candidate.get("symbol") != symbol:
                continue
            if candidate.get("status") not in ACTIVE_SYMBOL_CONTROL_STATUSES:
                continue
            siblings.append(candidate)
        return siblings

    def emergency_stop(
        self,
        bot_id: str,
        *,
        action_received_at_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        EXTREMELY SENSITIVE Emergency Stop.
        1. Force stop the bot (prevent new orders).
        2. Aggressively cancel ALL open orders (retry until clear).
        3. Aggressively close ALL positions (Hedge & One-Way).
        
        Args:
            bot_id: Bot ID to stop
            
        Returns:
            Status dict
        """
        action_started_at = self._safe_float(action_received_at_ts, 0.0) or now_ts()
        try:
            existing_bot = self.bot_storage.get_bot(bot_id)
            if not existing_bot:
                return {"success": False, "error": "Bot not found"}
            symbol = existing_bot.get("symbol")

            sibling_bots = self._get_other_active_bots_for_symbol(
                symbol=symbol,
                exclude_bot_id=bot_id,
            )
            if sibling_bots:
                sibling_ids = [bot.get("id") for bot in sibling_bots if bot.get("id")]
                logger.error(
                    "[%s] Refusing single-bot emergency stop; %d other active bots share the symbol: %s",
                    symbol,
                    len(sibling_ids),
                    ",".join(sibling_ids),
                )
                return {
                    "success": False,
                    "error": "shared_symbol_active_bots",
                    "other_bot_ids": sibling_ids,
                }

            bot = self._mark_bot_stop_cleanup_pending_state(
                existing_bot,
                scope="emergency_stop",
                target_status="stopped",
                action_received_at_ts=action_started_at,
                pending_message="Emergency stop cleanup pending",
                final_last_error=None,
            )
            if not bot:
                return {"success": False, "error": "Bot not found"}

            if not self._is_tradeable_symbol(symbol):
                logger.info(
                    "[Auto-Pilot] Emergency stop skipped exchange close/cancel for placeholder symbol"
                )
                bot = self._finalize_bot_stop_cleanup_state(
                    bot,
                    scope="emergency_stop",
                    final_status="stopped",
                )
                return {
                    "success": True,
                    "cancel": {"success": True, "cancelled": 0, "skipped": True},
                    "close": {"success": True, "skipped": True},
                    "flat_confirm": {"success": True, "flat": True, "skipped": True},
                    "timing": ensure_bot_timing_scope(bot, "emergency_stop"),
                    "cleanup_pending": False,
                }

            logger.warning(f"🚨 EMERGENCY STOP TRIGGERED FOR {symbol} 🚨")
            
        except Exception as e:
            logger.error(f"Error in emergency_stop for {bot_id}: {e}")
            return {"success": False, "error": str(e)}

        # Continue with cancellation + position close (outside try/except to avoid burying errors)
        cancel_stage_started_at = now_ts()
        self._record_control_stage(
            bot,
            "emergency_stop",
            cancel_stage_started_at=iso_from_ts(cancel_stage_started_at),
            stop_state_to_cancel_sent_ms=elapsed_ms(action_started_at, cancel_stage_started_at),
        )
        cancel_res = self._force_cancel_all_orders(symbol)
        cancel_stage_completed_at = now_ts()
        self._record_control_stage(
            bot,
            "emergency_stop",
            cancel_stage_completed_at=iso_from_ts(cancel_stage_completed_at),
            cancel_total_ms=elapsed_ms(cancel_stage_started_at, cancel_stage_completed_at),
            cancel_result=cancel_res,
        )
        close_stage_started_at = now_ts()
        self._record_control_stage(
            bot,
            "emergency_stop",
            close_stage_started_at=iso_from_ts(close_stage_started_at),
            cancel_to_close_sent_ms=elapsed_ms(cancel_stage_completed_at, close_stage_started_at),
        )
        close_res = self._close_bot_position_market(bot, symbol)
        close_stage_completed_at = now_ts()
        flat_confirm = self._confirm_symbol_flat(symbol)
        timing = self._record_control_stage(
            bot,
            "emergency_stop",
            close_stage_completed_at=iso_from_ts(close_stage_completed_at),
            close_total_ms=elapsed_ms(close_stage_started_at, close_stage_completed_at),
            close_result=close_res,
            flat_confirmed=bool(flat_confirm.get("flat")),
            flat_confirmed_at=flat_confirm.get("flat_confirmed_at"),
            stop_to_flat_ms=flat_confirm.get("stop_to_flat_ms"),
            control_action_ack_at=iso_from_ts(close_stage_completed_at),
            control_action_to_ack_ms=elapsed_ms(action_started_at, close_stage_completed_at),
        )
        cleanup_confirmed = bool(cancel_res.get("success")) and bool(
            flat_confirm.get("flat")
        )
        if cleanup_confirmed:
            bot = self._finalize_bot_stop_cleanup_state(
                bot,
                scope="emergency_stop",
                final_status="stopped",
            )
        else:
            self.bot_storage.save_bot(bot)
        timing = ensure_bot_timing_scope(bot, "emergency_stop")

        overall_success = cleanup_confirmed
        cleanup_pending = not cleanup_confirmed
        if not overall_success:
            logger.error(
                "[%s] emergency_stop: cancel_res=%s close_res=%s",
                symbol,
                cancel_res,
                close_res,
            )

        return {
            "success": overall_success,
            "cancel": cancel_res,
            "close": close_res,
            "flat_confirm": flat_confirm,
            "timing": timing,
            "cleanup_pending": cleanup_pending,
        }

    def _cancel_neutral_bot_orders(
        self,
        bot: Dict[str, Any],
        symbol: str,
        cancel_all: bool = False,
    ) -> Dict[str, Any]:
        if not self._is_tradeable_symbol(symbol):
            return {"success": True, "cancelled": 0, "skipped": True}

        bot_id = bot.get("id", "")
        bot_id_16 = bot_id.replace("-", "")[:16]
        cancelled = 0

        orders_result = self.client.get_open_orders(
            symbol=symbol,
            limit=200,
            skip_cache=True,
        )
        if not orders_result.get("success"):
            return {"success": False, "error": orders_result.get("error", "open_orders_failed")}

        orders = orders_result.get("data", {})
        if isinstance(orders, dict):
            orders = orders.get("list", [])
        orders = orders or []

        for order in orders:
            link_id = order.get("orderLinkId")
            parsed = self._parse_neutral_order_link_id(link_id)
            if not parsed or parsed.get("bot_id") != bot_id_16:
                continue
            if not cancel_all and parsed.get("state") != "E":
                continue
            order_id = order.get("orderId")
            try:
                self.client.cancel_order(symbol=symbol, order_id=order_id, order_link_id=link_id)
                cancelled += 1
            except Exception as exc:
                logger.warning("[%s] Failed to cancel neutral bot order %s: %s", symbol, link_id, exc)

        return {"success": True, "cancelled": cancelled}

    def _cancel_neutral_entry_orders(self, bot: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        return self._cancel_neutral_bot_orders(bot, symbol, cancel_all=False)

    def _parse_neutral_order_link_id(self, order_link_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not order_link_id or not isinstance(order_link_id, str):
            return None
        if not order_link_id.startswith("bv2:"):
            return None
        parts = order_link_id.split(":")
        if len(parts) != 5:
            return None
        _, bot_id_16, _seq, _slot, state = parts
        if state not in ("E", "X"):
            return None
        return {"bot_id": bot_id_16, "state": state}

    def _check_hedge_mode_required(self, bot: Dict[str, Any], client: BybitClient) -> Optional[str]:
        symbol = bot.get("symbol")
        if not self._is_tradeable_symbol(symbol):
            return "HEDGE_MODE_REQUIRED: missing symbol"

        mode_result = client.get_position_mode(symbol=symbol)
        if mode_result.get("success"):
            if mode_result.get("mode") == "hedge":
                return None
            if mode_result.get("mode") == "one_way":
                return "HEDGE_MODE_REQUIRED: position mode is one-way for symbol"

        return "HEDGE_MODE_REQUIRED: unable to confirm hedge mode"

    def _compute_min_notional_requirement(
        self,
        bot_data: Dict[str, Any],
        client: Optional[BybitClient] = None,
        default_min_notional: float = 5.1,
    ) -> Optional[Dict[str, float]]:
        """
        Best-effort compute per-order notional and required investment for minNotionalValue.

        Falls back to default_min_notional when instrument info is missing.
        Returns None only if symbol is missing or no client provided.
        """
        symbol = bot_data.get("symbol")
        if not self._is_tradeable_symbol(symbol):
            return None

        use_client = client or self.client
        if use_client is None:
            return None

        try:
            inst = use_client.get_instruments_info(symbol)
            min_notional_value = None
            if not inst.get("success"):
                logger.warning(f"[{symbol}] Cannot fetch instrument info for min-notional check: {inst.get('error')}")
            else:
                lst = (inst.get("data", {}) or {}).get("list", []) or []
                if lst:
                    lot = lst[0].get("lotSizeFilter", {}) or {}
                    min_notional_value = lot.get("minNotionalValue") or lot.get("minOrderAmt") or 0
            try:
                min_notional_value = float(min_notional_value)
            except (TypeError, ValueError):
                min_notional_value = 0.0
            if min_notional_value is None or min_notional_value <= 0:
                min_notional_value = default_min_notional

            levels = bot_data.get("grid_levels_total") or bot_data.get("grid_count") or DEFAULT_GRID_COUNT
            try:
                levels = int(levels)
            except (TypeError, ValueError):
                levels = DEFAULT_GRID_COUNT
            runtime_grid_cap = bot_data.get("runtime_grid_count_cap")
            try:
                runtime_grid_cap = int(runtime_grid_cap)
            except (TypeError, ValueError):
                runtime_grid_cap = 0
            if runtime_grid_cap > 0:
                levels = min(levels, runtime_grid_cap)

            leverage = bot_data.get("leverage", DEFAULT_LEVERAGE) or DEFAULT_LEVERAGE
            try:
                leverage = float(leverage)
            except (TypeError, ValueError):
                leverage = DEFAULT_LEVERAGE
            leverage = max(leverage, 1.0)

            investment = bot_data.get("investment", 0) or 0
            try:
                investment = float(investment)
            except (TypeError, ValueError):
                investment = 0.0
            min_leverage_needed = None
            if investment > 0:
                min_leverage_needed = (min_notional_value * max(levels, 1)) / investment
                if min_leverage_needed < 1.0:
                    min_leverage_needed = 1.0
                # Round up to 2 decimals for display
                min_leverage_needed = math.ceil(min_leverage_needed * 100) / 100.0

            per_order_notional = (investment * leverage) / max(levels, 1)
            required_investment = (min_notional_value * max(levels, 1)) / leverage

            return {
                "min_notional_value": float(min_notional_value),
                "per_order_notional": float(per_order_notional),
                "required_investment": float(required_investment),
                "levels": float(levels),
                "leverage": float(leverage),
                "min_leverage_needed": float(min_leverage_needed) if min_leverage_needed is not None else None,
            }
        except Exception as exc:
            logger.warning(f"[{symbol}] Min-notional requirement check failed: {exc}")
            return None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _round_up_leverage(value: float) -> int:
        if value <= 1:
            return 1
        return int(math.ceil(value - 1e-9))

    @staticmethod
    def _requested_grid_count(bot: Dict[str, Any]) -> int:
        raw = (
            bot.get("target_grid_count")
            or bot.get("grid_levels_total")
            or bot.get("grid_count")
            or DEFAULT_GRID_COUNT
        )
        try:
            return max(3, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_GRID_COUNT

    def _get_account_snapshot(self) -> Dict[str, float]:
        overview = {}
        if self.account_service:
            try:
                overview = self.account_service.get_overview() or {}
            except Exception as exc:
                logger.warning("Failed to fetch account overview: %s", exc)
        equity = self._safe_float(
            overview.get("equity")
            or overview.get("wallet_balance")
            or overview.get("available_balance"),
            0.0,
        )
        available_balance = self._safe_float(overview.get("available_balance"), 0.0)
        if available_balance <= 0 and equity > 0:
            available_balance = equity
        return {
            "equity": equity,
            "available_balance": available_balance,
        }

    def _get_symbol_launch_constraints(self, symbol: str) -> Dict[str, float]:
        constraints = {"max_leverage": 0.0, "min_notional_value": 5.1}
        if not self._is_tradeable_symbol(symbol):
            return constraints
        try:
            inst = self.client.get_instruments_info(symbol)
            if not inst.get("success"):
                return constraints
            inst_list = (inst.get("data", {}) or {}).get("list", []) or []
            if not inst_list:
                return constraints
            row = inst_list[0]
            leverage_filter = row.get("leverageFilter", {}) or {}
            lot_filter = row.get("lotSizeFilter", {}) or {}
            constraints["max_leverage"] = self._safe_float(
                leverage_filter.get("maxLeverage"), 0.0
            )
            min_notional = lot_filter.get("minNotionalValue") or lot_filter.get(
                "minOrderAmt"
            )
            constraints["min_notional_value"] = self._safe_float(min_notional, 5.1) or 5.1
        except Exception as exc:
            logger.warning("[%s] Failed to fetch launch constraints: %s", symbol, exc)
        return constraints

    def _compute_capital_partition(
        self,
        bot: Dict[str, Any],
        available_balance: float,
        existing_bots: Optional[List[Dict[str, Any]]] = None,
        exclude_bot_id: Optional[str] = None,
    ) -> float:
        requested = max(self._safe_float(bot.get("investment"), DEFAULT_INVESTMENT_USDT), 0.0)
        if not CAPITAL_PARTITION_ENABLED or available_balance <= 0:
            return requested

        existing_bots = existing_bots or []
        running_peers = [
            candidate
            for candidate in existing_bots
            if candidate.get("status") == "running"
            and candidate.get("id") != exclude_bot_id
        ]
        total_requested = requested + sum(
            max(self._safe_float(peer.get("investment"), 0.0), 0.0) for peer in running_peers
        )
        if total_requested <= 0:
            return min(requested, available_balance)
        partition = available_balance * (requested / total_requested)
        return max(0.0, min(requested, partition))

    def _compute_fee_aware_min_step_pct(self) -> float:
        return max(
            GRID_STEP_PCT,
            (2 * FAST_EXEC_TAKER_FEE_RATE)
            + FAST_EXEC_SLIPPAGE_BUFFER_PCT
            + FEE_AWARE_MIN_STEP_BUFFER_PCT,
        )

    def analyze_launch(self, bot: Dict[str, Any], existing_bots: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        symbol = (bot.get("symbol") or "").upper()
        requested_grid_count = self._requested_grid_count(bot)
        mode = (bot.get("mode") or "neutral").lower()
        leverage = max(self._safe_float(bot.get("leverage"), DEFAULT_LEVERAGE), 1.0)
        requested_investment = max(
            self._safe_float(bot.get("investment"), DEFAULT_INVESTMENT_USDT), 0.0
        )
        snapshot = self._get_account_snapshot()
        available_balance = snapshot.get("available_balance", 0.0)
        capital_partition = self._compute_capital_partition(
            bot,
            available_balance=available_balance,
            existing_bots=existing_bots,
            exclude_bot_id=bot.get("id"),
        )
        effective_investment = capital_partition if capital_partition > 0 else requested_investment

        reserve_pct = 0.15
        reserve_usd = effective_investment * reserve_pct
        usable_investment = max(0.0, effective_investment - reserve_usd)
        symbol_constraints = self._get_symbol_launch_constraints(symbol)
        safe_min_notional = max(
            self._safe_float(symbol_constraints.get("min_notional_value"), 5.1) * 1.1,
            0.0,
        )
        max_leverage = max(
            self._safe_float(symbol_constraints.get("max_leverage"), 0.0),
            leverage,
        )
        min_leverage_needed = None
        if usable_investment > 0 and requested_grid_count > 0:
            min_leverage_needed = self._round_up_leverage(
                (safe_min_notional * requested_grid_count) / usable_investment
            )
        effective_leverage = leverage
        auto_raise_applied = False
        if (
            LAUNCH_AFFORDABILITY_ENABLED
            and LAUNCH_AUTO_RAISE_LEVERAGE
            and min_leverage_needed
            and min_leverage_needed > leverage
        ):
            effective_leverage = float(min(min_leverage_needed, max_leverage))
            if effective_leverage > leverage:
                auto_raise_applied = True

        effective_grid_count = requested_grid_count
        notional_budget = usable_investment * max(effective_leverage, 1.0)
        max_grid_count_at_effective_lev = (
            int(notional_budget // safe_min_notional) if safe_min_notional > 0 else requested_grid_count
        )
        runtime_grid_cap_applied = False
        if (
            LAUNCH_AFFORDABILITY_ENABLED
            and LAUNCH_AUTO_CAP_RUNTIME_GRIDS
            and max_grid_count_at_effective_lev > 0
            and max_grid_count_at_effective_lev < effective_grid_count
        ):
            effective_grid_count = max(3, max_grid_count_at_effective_lev)
            runtime_grid_cap_applied = True

        if mode in ("scalp_pnl", "scalp_market"):
            max_active_open_orders = max(
                LAUNCH_MIN_ACTIVE_OPEN_ORDERS,
                effective_grid_count,
            )
        else:
            base_open_cap = PROXIMITY_DEFAULT_OPEN_ORDER_CAP_TOTAL
            if requested_investment <= PROXIMITY_LOW_BALANCE_INVESTMENT_THRESHOLD:
                base_open_cap = min(base_open_cap, PROXIMITY_LOW_BALANCE_OPEN_ORDER_CAP_TOTAL)
            max_active_open_orders = max(
                LAUNCH_MIN_ACTIVE_OPEN_ORDERS,
                min(effective_grid_count, base_open_cap),
            )
        manual_open_cap_override = int(
            self._safe_float(bot.get("manual_runtime_open_order_cap_total"), 0.0) or 0.0
        )
        if manual_open_cap_override > 0:
            max_active_open_orders = max(
                LAUNCH_MIN_ACTIVE_OPEN_ORDERS,
                min(max_active_open_orders, manual_open_cap_override),
            )

        reasons: List[str] = []
        notes: List[str] = []
        affordable = True
        if requested_investment > 0 and capital_partition > 0 and capital_partition + 0.01 < requested_investment:
            notes.append(
                f"capital partition limited this session to ${capital_partition:.2f} of ${requested_investment:.2f}"
            )
        # If we pushed to max_leverage but STILL can't afford the grids, let the grid cap handle it.
        # But if the grid cap pushes us below 3, we still fail.
        if min_leverage_needed and min_leverage_needed > max_leverage and effective_grid_count >= requested_grid_count:
            # We only block on leverage if the runtime grid cap feature is disabled or failed to reduce grids
            affordable = False
            reasons.append(
                f"needs {min_leverage_needed}x leverage for {requested_grid_count} grids but symbol max is {max_leverage:.0f}x"
            )
        if effective_grid_count < 3:
            affordable = False
            reasons.append(
                f"free balance only supports {max_grid_count_at_effective_lev} grids above min notional"
            )
        if usable_investment <= 0:
            affordable = False
            reasons.append("usable capital is zero after reserve")
        if auto_raise_applied:
            notes.append(f"auto-raised leverage to {effective_leverage:.0f}x")
        if runtime_grid_cap_applied:
            notes.append(
                f"runtime grid cap {requested_grid_count} -> {effective_grid_count} to satisfy min notional"
            )
        if manual_open_cap_override > 0:
            notes.append(
                f"manual open-order cap override applied: {max_active_open_orders}"
            )

        return {
            "affordable": affordable,
            "reasons": reasons,
            "notes": notes,
            "requested_investment": requested_investment,
            "capital_partition_usdt": round(capital_partition, 4),
            "usable_investment": round(usable_investment, 4),
            "reserve_usdt": round(reserve_usd, 4),
            "available_balance": round(available_balance, 4),
            "requested_grid_count": requested_grid_count,
            "effective_grid_count": effective_grid_count,
            "safe_min_notional": round(safe_min_notional, 4),
            "requested_leverage": leverage,
            "effective_leverage": effective_leverage,
            "max_leverage": max_leverage,
            "min_leverage_needed": min_leverage_needed,
            "max_grid_count_at_effective_leverage": max_grid_count_at_effective_lev,
            "max_active_open_orders": max_active_open_orders,
            "manual_runtime_open_order_cap_total": (
                manual_open_cap_override if manual_open_cap_override > 0 else None
            ),
            "fee_aware_min_step_pct": self._compute_fee_aware_min_step_pct(),
            "auto_raise_applied": auto_raise_applied,
            "runtime_grid_cap_applied": runtime_grid_cap_applied,
        }

    def _validate_and_prepare_launch(
        self,
        bot: Dict[str, Any],
        action: str,
    ) -> Dict[str, Any]:
        account_snapshot = self._get_account_snapshot()
        account_equity = account_snapshot.get("equity", 0.0)
        all_bots = self.bot_storage.list_bots()

        if self.risk_manager and self.account_service and not bot.get("auto_pilot"):
            validation = self.risk_manager.validate_new_bot(
                symbol=bot.get("symbol"),
                planned_investment=bot.get("investment", 0),
                planned_leverage=bot.get("leverage", 1),
                account_equity=account_equity,
                existing_bots=all_bots,
                max_risk_per_bot_pct=MAX_RISK_PER_BOT_PCT,
                max_capital_per_symbol_pct=MAX_CAPITAL_PER_SYMBOL_PCT,
                max_capital_per_symbol_usdt=MAX_CAPITAL_PER_SYMBOL_USDT,
                max_bots_per_symbol=MAX_BOTS_PER_SYMBOL,
                max_symbol_share_pct=MAX_SYMBOL_SHARE_OF_BOTS_PCT,
                max_concurrent_symbols=MAX_CONCURRENT_SYMBOLS,
                max_concurrent_bots=MAX_CONCURRENT_BOTS,
                exclude_bot_id=bot.get("id"),
                enforce_single_symbol=ENFORCE_SINGLE_RUNNING_BOT_PER_SYMBOL,
            )
            if not validation["allowed"]:
                reasons_str = "; ".join(validation["reasons"])
                bot["last_error"] = f"Pre-launch validation failed: {reasons_str}"
                bot["status"] = "stopped"
                self.bot_storage.save_bot(bot)
                raise ValueError(f"Pre-launch validation failed: {reasons_str}")

        launch_analysis = self.analyze_launch(bot, existing_bots=all_bots)
        if self.risk_manager and SYMBOL_DAILY_KILL_SWITCH_ENABLED:
            launch_investment = self._safe_float(
                launch_analysis.get("capital_partition_usdt"),
                self._safe_float(bot.get("investment"), DEFAULT_INVESTMENT_USDT),
            )
            symbol_daily_limit = launch_investment * SYMBOL_DAILY_KILL_SWITCH_LOSS_PCT_OF_INVESTMENT
            symbol_daily_limit = max(
                SYMBOL_DAILY_KILL_SWITCH_MIN_USDT,
                min(SYMBOL_DAILY_KILL_SWITCH_MAX_USDT, symbol_daily_limit),
            )
            symbol_daily_state = self.risk_manager.check_symbol_daily_loss(
                bot.get("symbol"), symbol_daily_limit
            )
            if symbol_daily_state.get("triggered"):
                realized_pnl = float(symbol_daily_state.get("realized_pnl", 0.0) or 0.0)
                reasons_str = (
                    f"symbol daily loss stop already triggered: "
                    f"${realized_pnl:.2f} <= -${symbol_daily_limit:.2f}"
                )
                bot["last_error"] = f"{action} blocked: {reasons_str}"
                bot["status"] = "stopped"
                self.bot_storage.save_bot(bot)
                raise ValueError(f"{action} blocked: {reasons_str}")
        bot["launch_affordability"] = launch_analysis
        bot["capital_partition_usdt"] = launch_analysis.get("capital_partition_usdt")
        bot["runtime_open_order_cap_total"] = int(
            launch_analysis.get("max_active_open_orders") or 0
        )
        bot["runtime_grid_count_cap"] = int(
            launch_analysis.get("effective_grid_count")
            or launch_analysis.get("requested_grid_count")
            or 0
        )
        bot["runtime_fee_aware_min_step_pct"] = float(
            launch_analysis.get("fee_aware_min_step_pct") or 0.0
        )
        self._emit_capital_compression_snapshot(
            bot,
            launch_analysis,
            symbol=(bot.get("symbol") or "").upper(),
            mode=(bot.get("mode") or "neutral").lower(),
        )

        if not launch_analysis.get("affordable", True):
            reasons_str = "; ".join(launch_analysis.get("reasons") or ["launch sizing failed"])
            bot["last_error"] = f"{action} blocked: {reasons_str}"
            bot["status"] = "stopped"
            self.bot_storage.save_bot(bot)
            raise ValueError(f"{action} blocked: {reasons_str}")

        target_leverage = self._safe_float(
            launch_analysis.get("effective_leverage"),
            self._safe_float(bot.get("leverage"), DEFAULT_LEVERAGE),
        )
        if target_leverage > self._safe_float(bot.get("leverage"), DEFAULT_LEVERAGE):
            bot["leverage"] = target_leverage
            bot["last_warning"] = (
                f"Launch sizing auto-raised leverage to {target_leverage:.0f}x"
            )

        return launch_analysis

    def create_or_update_bot(self, bot_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize and save a bot configuration.

        Args:
            bot_data: Bot configuration dictionary

        Returns:
            Saved bot dictionary with defaults applied
        """
        bot_id = str(bot_data.get("id") or "").strip()
        existing_bot = None
        if bot_id:
            existing_bot = self.bot_storage.get_bot(bot_id)
            if existing_bot:
                merged_bot = copy.deepcopy(existing_bot)
                merged_bot.update(bot_data)
                merged_bot["id"] = bot_id
                bot_data = merged_bot

        # Ensure required fields
        is_auto_pilot = bool(bot_data.get("auto_pilot"))
        if not bot_data.get("symbol") and not is_auto_pilot:
            raise ValueError("Bot requires a symbol")
        if is_auto_pilot and not bot_data.get("symbol"):
            bot_data["symbol"] = "Auto-Pilot"

        # M6: Block creating a NEW bot on a symbol that already has an active bot.
        # Updates to existing bots are allowed (they keep the same symbol).
        symbol = str(bot_data.get("symbol") or "").strip().upper()
        if (
            not existing_bot
            and not is_auto_pilot
            and self._is_tradeable_symbol(symbol)
        ):
            siblings = self._get_other_active_bots_for_symbol(
                symbol=symbol,
                exclude_bot_id=bot_id or None,
            )
            if siblings:
                sibling_ids = [s.get("id") for s in siblings if s.get("id")]
                raise ValueError(
                    f"Cannot create bot: {symbol} already has an active bot "
                    f"({', '.join(str(s)[:8] for s in sibling_ids)}). "
                    f"Stop the existing bot first."
                )

        incoming_mode = (bot_data.get("mode") or "neutral").lower()
        if not is_auto_pilot:
            if incoming_mode == "neutral_classic_bybit":
                grid_lower = bot_data.get("grid_lower_price") or bot_data.get(
                    "lower_price"
                )
                grid_upper = bot_data.get("grid_upper_price") or bot_data.get(
                    "upper_price"
                )
                if not grid_lower or not grid_upper:
                    raise ValueError(
                        "Bot requires grid_lower_price and grid_upper_price for neutral classic mode"
                    )
            elif not bot_data.get("lower_price") or not bot_data.get("upper_price"):
                raise ValueError("Bot requires lower_price and upper_price")

        # Apply defaults for missing fields
        from config.config import DEFAULT_TRADING_ENV

        defaults = {
            "mode": "neutral",
            "configured_mode": None,
            "configured_range_mode": None,
            "mode_policy": None,
            "effective_runtime_mode": None,
            "effective_runtime_range_mode": None,
            "runtime_mode_source": None,
            "runtime_mode_non_persistent": False,
            "runtime_mode_updated_at": None,
            "status": "stopped",
            "leverage": DEFAULT_LEVERAGE,
            "investment": DEFAULT_INVESTMENT_USDT,
            "trailing": False,
            "auto_stop": None,
            # Auto-stop on balance target (Smart Feature #19)
            "auto_stop_target_usdt": 0.0,  # 0 = disabled, >0 = stop when balance reaches this
            "auto_stop_triggered": False,  # Track if auto-stop was triggered
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            # Session baseline for TP% checks (prevents immediate re-trigger on restart)
            "tp_session_realized_baseline": 0.0,
            "grid_count": 10,
            "grid_distribution": DEFAULT_GRID_DISTRIBUTION,
            "control_version": 0,
            "control_updated_at": None,
            "settings_version": 0,
            "settings_updated_at": None,
            "last_error": None,
            "last_warning": None,
            "trading_env": DEFAULT_TRADING_ENV,  # Mainnet only
            "paper_trading": False,  # Paper trading disabled
            "capital_partition_usdt": None,
            "launch_affordability": None,
            "runtime_grid_count_cap": None,
            "runtime_open_order_cap_total": None,
            "runtime_fee_aware_min_step_pct": None,
            "scalp_learned_opening_order_cap": None,
            "scalp_learned_opening_cap_at": None,
            "scalp_learned_opening_cap_reason": None,
            # Neutral classic Bybit settings
            "grid_lower_price": None,
            "grid_upper_price": None,
            "grid_levels_total": None,
            "neutral_post_only": False,
            "neutral_recenter_enabled": False,
            "neutral_recenter_threshold_pct": 2.0,
            # Smart auto-margin (defaults from strategy_config preset)
            "auto_margin": get_auto_margin_defaults(),
            "auto_margin_profile": AUTO_MARGIN_PRESET_NAME,
            "auto_margin_state": {},
            # Initial entry: Place market order at current price when bot starts
            "initial_entry": False,
            "initial_entry_done": False,  # Track if initial entry was placed
            "initial_entry_auto_trend": True,  # Auto-enable on strong trend
            # Quick profit settings for long dynamic mode
            "quick_profit_enabled": LONG_QUICK_PROFIT_ENABLED,
            "quick_profit_target": LONG_QUICK_PROFIT_TARGET,
            "quick_profit_close_pct": LONG_QUICK_PROFIT_CLOSE_PCT,
            "quick_profit_cooldown": LONG_QUICK_PROFIT_COOLDOWN_SEC,
            # Trailing stop-loss settings (Smart Feature #14) - enabled by default
            "trailing_sl_enabled": True,  # Enable trailing SL by default per user preference
            "recovery_enabled": True,     # Enable Smart Recovery by default
            "neutral_volatility_gate_enabled": True, 
            "neutral_volatility_gate_threshold_pct": 5.0,
            # AI Advisor Layer v1 (read-only)
            "ai_advisor_enabled": False,
            "ai_advisor_interval_seconds": 300,
            "ai_advisor_model": "",
            "ai_advisor_confidence_threshold": 0.60,
            "ai_advisor_apply": False,
            # Per-bot safety toggles
            "auto_stop_loss_enabled": True,
            "auto_take_profit_enabled": True,
            "trend_protection_enabled": True,
            "danger_zone_enabled": True,
            "auto_neutral_mode_enabled": True,
            "session_timer_enabled": False,
            "session_start_at": None,
            "session_stop_at": None,
            "session_no_new_entries_before_stop_min": 15,
            "session_end_mode": "hard_stop",
            "session_green_grace_min": 5,
            "session_force_close_max_loss_pct": None,
            "session_cancel_pending_orders_on_end": True,
            "session_reduce_only_on_end": False,
            "session_timer_state": "inactive",
            "session_timer_started_at": None,
            "session_timer_pre_stop_at": None,
            "session_timer_end_triggered_at": None,
            "session_timer_grace_started_at": None,
            "session_timer_grace_expires_at": None,
            "session_timer_completed_at": None,
            "session_timer_completed_reason": None,
            "session_timer_last_event": None,
            "session_timer_no_new_entries_active": False,
            "session_timer_reduce_only_active": False,
            "trailing_sl_activation_pct": None,  # Use global default (0.5%)
            "trailing_sl_distance_pct": None,  # Use global default (0.3%)
            "trailing_sl_price": None,  # Runtime state - current trailing SL price
            "trailing_sl_activated": False,  # Runtime state - has trailing activated
            # Mode hysteresis tracking (Smart Feature #13)
            "mode_entered_at": None,  # ISO timestamp when current mode was entered
            "mode_change_count": 0,  # Counter for monitoring mode changes
            # =============================================================================
            # UPnL Stop-Loss Configuration (NEW - Part 7)
            # =============================================================================
            # Per-bot unrealized PnL stop-loss with soft/hard thresholds
            "upnl_stoploss_enabled": False,  # Disabled by default (user request)
            "upnl_stoploss_soft_pct": None,  # Soft threshold % (None = use symbol default)
            "upnl_stoploss_hard_pct": None,  # Hard threshold % (None = use symbol default)
            "upnl_stoploss_basis": "used_margin",  # "used_margin" or "equity"
            "upnl_stoploss_cooldown_seconds": None,  # Cooldown after hard trigger (None = use default)
            "upnl_stoploss_close_mode": "reduce_only_market",  # How to close position
            "upnl_stoploss_close_on_soft": False,  # Also close on soft trigger?
            # UPnL SL runtime state (not user-configurable)
            "upnl_stoploss_cooldown_until": None,  # ISO timestamp when cooldown expires
            "upnl_stoploss_last_trigger": None,  # Last trigger timestamp
            "upnl_stoploss_trigger_count": 0,  # Total triggers for this bot
            "funding_protection_enabled": False,
            "funding_protection_reason": "",
            "funding_protection_active": False,
            "auto_pilot_universe_mode": AUTO_PILOT_UNIVERSE_MODE,
        }

        for key, default_value in defaults.items():
            if key not in bot_data or bot_data[key] is None:
                bot_data[key] = default_value

        # Normalize mode
        mode = (bot_data.get("mode") or "neutral").lower()
        # Validate mode - includes scalp_market for market order scalping
        if mode not in SUPPORTED_BOT_MODES:
            raise ValueError(
                f"Unsupported mode '{mode}'. Supported modes: {', '.join(SUPPORTED_BOT_MODES)}"
            )
        bot_data["mode"] = mode

        # Normalize numeric fields
        bot_data["investment"] = float(bot_data["investment"])
        bot_data["leverage"] = float(bot_data["leverage"])

        if mode == "neutral_classic_bybit":
            grid_lower = bot_data.get("grid_lower_price") or bot_data.get(
                "lower_price"
            )
            grid_upper = bot_data.get("grid_upper_price") or bot_data.get(
                "upper_price"
            )
            if is_auto_pilot:
                grid_lower = self._safe_float(grid_lower, 0.0)
                grid_upper = self._safe_float(grid_upper, 0.0)
                bot_data["grid_lower_price"] = grid_lower
                bot_data["grid_upper_price"] = grid_upper
                bot_data["lower_price"] = self._safe_float(
                    bot_data.get("lower_price"), grid_lower
                )
                bot_data["upper_price"] = self._safe_float(
                    bot_data.get("upper_price"), grid_upper
                )
            else:
                bot_data["grid_lower_price"] = float(grid_lower)
                bot_data["grid_upper_price"] = float(grid_upper)
                bot_data["lower_price"] = bot_data["grid_lower_price"]
                bot_data["upper_price"] = bot_data["grid_upper_price"]
            grid_levels_total = bot_data.get("grid_levels_total") or bot_data.get("grid_count", 10)
            bot_data["grid_levels_total"] = max(2, min(500, int(grid_levels_total)))
            bot_data["grid_count"] = bot_data["grid_levels_total"]
            bot_data["target_grid_count"] = bot_data["grid_levels_total"]
            bot_data["neutral_post_only"] = bool(bot_data.get("neutral_post_only", False))
            bot_data["neutral_recenter_enabled"] = bool(bot_data.get("neutral_recenter_enabled", False))
            try:
                bot_data["neutral_recenter_threshold_pct"] = float(
                    bot_data.get("neutral_recenter_threshold_pct", 2.0)
                )
            except (TypeError, ValueError):
                bot_data["neutral_recenter_threshold_pct"] = 2.0
        else:
            if is_auto_pilot:
                # Auto-Pilot sets prices dynamically at runtime
                bot_data["lower_price"] = float(bot_data.get("lower_price") or 0)
                bot_data["upper_price"] = float(bot_data.get("upper_price") or 0)
            else:
                bot_data["lower_price"] = float(bot_data["lower_price"])
                bot_data["upper_price"] = float(bot_data["upper_price"])
            bot_data["grid_count"] = max(3, min(500, int(bot_data.get("grid_count", 10))))
            # Store user's original grid_count as target_grid_count (grid_count gets overwritten during cycles)
            bot_data["target_grid_count"] = bot_data["grid_count"]

        self._normalize_mode_range_state(bot_data)

        previous_mode = str((existing_bot or {}).get("mode") or "").strip().lower()
        previous_range_mode = str((existing_bot or {}).get("range_mode") or "").strip().lower()
        if previous_mode and (
            previous_mode != mode or previous_range_mode != bot_data.get("range_mode")
        ):
            self._clear_entry_gate_runtime_state(bot_data)

        # Normalize profile and auto_direction fields
        profile = (bot_data.get("profile") or "normal").lower()
        auto_direction = bool(bot_data.get("auto_direction", False))
        bot_data["profile"] = profile
        bot_data["auto_direction"] = auto_direction
        bot_data["auto_pilot_universe_mode"] = normalize_auto_pilot_universe_mode(
            bot_data.get("auto_pilot_universe_mode")
        )

        # Normalize range_mode field
        range_mode = (bot_data.get("range_mode") or "fixed").lower()
        if range_mode not in ("fixed", "dynamic", "trailing"):
            range_mode = "fixed"
        bot_data["range_mode"] = range_mode
        bot_data["configured_mode"] = resolve_configured_mode(
            {"configured_mode": mode, "mode": mode}
        )
        bot_data["configured_range_mode"] = resolve_configured_range_mode(
            {
                "configured_range_mode": range_mode,
                "range_mode": range_mode,
            }
        )
        bot_data["mode_policy"] = normalize_mode_policy(
            bot_data.get("mode_policy"),
            bot_data,
        )
        bot_data["effective_runtime_mode"] = None
        bot_data["effective_runtime_range_mode"] = None
        bot_data["runtime_mode_source"] = None
        bot_data["runtime_mode_non_persistent"] = False
        bot_data["runtime_mode_updated_at"] = None

        grid_distribution = (
            bot_data.get("grid_distribution") or DEFAULT_GRID_DISTRIBUTION
        ).lower()
        if grid_distribution not in (
            "balanced",
            "buy_heavy",
            "sell_heavy",
            "clustered",
        ):
            grid_distribution = DEFAULT_GRID_DISTRIBUTION
        bot_data["grid_distribution"] = grid_distribution

        bot_data["session_timer_enabled"] = bool(
            bot_data.get("session_timer_enabled", False)
        )
        bot_data["session_start_at"] = self._normalize_session_datetime_input(
            bot_data.get("session_start_at")
        )
        bot_data["session_stop_at"] = self._normalize_session_datetime_input(
            bot_data.get("session_stop_at")
        )
        try:
            bot_data["session_no_new_entries_before_stop_min"] = max(
                0,
                int(bot_data.get("session_no_new_entries_before_stop_min", 15) or 0),
            )
        except (TypeError, ValueError):
            bot_data["session_no_new_entries_before_stop_min"] = 15
        session_end_mode = str(
            bot_data.get("session_end_mode") or "hard_stop"
        ).strip().lower()
        if session_end_mode not in SESSION_TIMER_END_MODES:
            session_end_mode = "hard_stop"
        bot_data["session_end_mode"] = session_end_mode
        try:
            bot_data["session_green_grace_min"] = max(
                0,
                int(bot_data.get("session_green_grace_min", 5) or 0),
            )
        except (TypeError, ValueError):
            bot_data["session_green_grace_min"] = 5
        force_close_cap_raw = bot_data.get("session_force_close_max_loss_pct")
        if force_close_cap_raw in (None, ""):
            bot_data["session_force_close_max_loss_pct"] = None
        else:
            try:
                bot_data["session_force_close_max_loss_pct"] = max(
                    0.0,
                    float(force_close_cap_raw),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "session_force_close_max_loss_pct must be numeric"
                ) from exc
        bot_data["session_cancel_pending_orders_on_end"] = bool(
            bot_data.get("session_cancel_pending_orders_on_end", True)
        )
        bot_data["session_reduce_only_on_end"] = bool(
            bot_data.get("session_reduce_only_on_end", False)
        )
        if bot_data["session_timer_enabled"] and not bot_data["session_stop_at"]:
            raise ValueError("session_stop_at is required when session timer is enabled")

        # For scalp modes, force dynamic range since we follow price
        if mode in ("scalp_pnl", "scalp_market"):
            bot_data["range_mode"] = "dynamic"

        # Runtime sizing/session fields are recomputed on start/resume.
        bot_data["capital_partition_usdt"] = None
        bot_data["launch_affordability"] = None
        bot_data["runtime_grid_count_cap"] = None
        bot_data["runtime_open_order_cap_total"] = None
        bot_data["runtime_fee_aware_min_step_pct"] = None
        bot_data["scalp_learned_opening_order_cap"] = None
        bot_data["scalp_learned_opening_cap_at"] = None
        bot_data["scalp_learned_opening_cap_reason"] = None

        # Best-effort min-notional/leverage guard at creation time using the unified launch analyzer
        # This handles dynamic grid capping safely without aggressive hard-fails.
        analysis = self.analyze_launch(bot_data)
        if not analysis.get("affordable"):
            reasons = " | ".join(analysis.get("reasons") or ["Insufficient investment"])
            bot_data["last_error"] = f"Launch configuration unviable: {reasons}"
            bot_data["status"] = "stopped"
            raise ValueError(bot_data["last_error"])

        # Normalize trading_env field
        trading_env = (bot_data.get("trading_env") or DEFAULT_TRADING_ENV).lower()
        if trading_env != "mainnet":
            raise ValueError("Testnet disabled. Mainnet only.")
        bot_data["trading_env"] = "mainnet"

        # Normalize paper_trading field
        paper_trading = bool(bot_data.get("paper_trading", False))
        if paper_trading:
            raise ValueError("paper_trading disabled. Mainnet only.")
        bot_data["paper_trading"] = False

        # Normalize Volatility Gate / ATR Guard fields
        bot_data["neutral_volatility_gate_enabled"] = bool(bot_data.get("neutral_volatility_gate_enabled", False))
        try:
            bot_data["neutral_volatility_gate_threshold_pct"] = float(
                bot_data.get("neutral_volatility_gate_threshold_pct", 5.0)
            )
        except (TypeError, ValueError):
            bot_data["neutral_volatility_gate_threshold_pct"] = 5.0

        # Preserve last_range_width_pct if provided
        if "last_range_width_pct" in bot_data:
            pass # Keep existing if already set

        # Normalize Trailing Stop-Loss Settings (Smart Feature #14)
        bot_data["trailing_sl_enabled"] = bool(bot_data.get("trailing_sl_enabled", True))
        bot_data["quick_profit_enabled"] = bool(
            bot_data.get("quick_profit_enabled", LONG_QUICK_PROFIT_ENABLED)
        )
        bot_data["recovery_enabled"] = bool(bot_data.get("recovery_enabled", True))
        # Per-bot Entry Gate toggle (Feature #19)
        bot_data["entry_gate_enabled"] = bool(bot_data.get("entry_gate_enabled", True))
        bot_data["btc_correlation_filter_enabled"] = bool(
            bot_data.get("btc_correlation_filter_enabled", True)
        )
        bot_data["auto_stop_loss_enabled"] = bool(
            bot_data.get("auto_stop_loss_enabled", True)
        )
        bot_data["auto_take_profit_enabled"] = bool(
            bot_data.get("auto_take_profit_enabled", True)
        )
        bot_data["trend_protection_enabled"] = bool(
            bot_data.get("trend_protection_enabled", True)
        )
        bot_data["danger_zone_enabled"] = bool(
            bot_data.get("danger_zone_enabled", True)
        )
        bot_data["auto_neutral_mode_enabled"] = bool(
            bot_data.get("auto_neutral_mode_enabled", True)
        )
        bot_data["breakout_confirmed_entry"] = bool(
            bot_data.get("breakout_confirmed_entry", False)
        )
        try:
            val = bot_data.get("trailing_sl_activation_pct")
            bot_data["trailing_sl_activation_pct"] = float(val) if val is not None else None
        except (TypeError, ValueError):
            bot_data["trailing_sl_activation_pct"] = None

        try:
            val = bot_data.get("trailing_sl_distance_pct")
            bot_data["trailing_sl_distance_pct"] = float(val) if val is not None else None
        except (TypeError, ValueError):
            bot_data["trailing_sl_distance_pct"] = None

        self._normalize_mode_scoped_settings(bot_data)

        # =============================================================================
        # Handle per-bot TP% (take profit percentage)
        # =============================================================================
        raw_tp = bot_data.get("tp_pct")
        try:
            tp_pct = float(raw_tp) if raw_tp is not None else None
        except (TypeError, ValueError):
            tp_pct = None

        # Keep Global TP empty/disabled unless the user explicitly sets it.
        if tp_pct is not None and tp_pct <= 0:
            tp_pct = None

        bot_data["tp_pct"] = tp_pct

        # Validate price range (skip for auto_pilot - prices set at runtime)
        if not is_auto_pilot:
            if bot_data["lower_price"] >= bot_data["upper_price"]:
                raise ValueError("lower_price must be less than upper_price")

            if bot_data["lower_price"] <= 0:
                raise ValueError("lower_price must be positive")

        # Save and return
        self._mark_settings_state_change(bot_data)
        saved_bot = self.bot_storage.save_bot(bot_data)
        logger.info(
            f"Bot saved: {saved_bot.get('id')} for {saved_bot.get('symbol')} "
            f"(profile={profile}, auto_direction={auto_direction}, range_mode={range_mode}, "
            f"grid_distribution={grid_distribution}, "
            f"auto_pilot_universe_mode={saved_bot.get('auto_pilot_universe_mode')}, "
            f"tp_pct={tp_pct if tp_pct is not None else 'None'}, "
            f"trading_env={trading_env}, paper_trading={paper_trading})"
        )

        # Log warning if mainnet is selected
        if trading_env == "mainnet":
            logger.warning(
                f"⚠️ Bot {saved_bot.get('id')} configured for MAINNET environment - REAL MONEY at risk!"
            )

        return saved_bot

    def start_bot(
        self,
        bot_id: str,
        *,
        action_received_at_ts: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Start a bot by setting its status to running.
        Performs pre-launch risk validation if risk_manager and account_service are available.

        Args:
            bot_id: Unique bot identifier

        Returns:
            Updated bot dictionary or None if not found

        Raises:
            ValueError: If pre-launch validation fails (includes rejection reasons)
        """
        control_started_at = self._safe_float(action_received_at_ts, 0.0) or now_ts()
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            logger.warning(f"Bot not found: {bot_id}")
            return None

        bot_env = (bot.get("trading_env") or "mainnet").lower()
        if bot_env != "mainnet":
            bot["last_error"] = "Testnet disabled. Mainnet only."
            bot["status"] = "stopped"
            self.bot_storage.save_bot(bot)
            raise ValueError("Testnet disabled. Mainnet only.")

        if bot.get("paper_trading"):
            bot["last_error"] = "paper_trading disabled. Mainnet only."
            bot["status"] = "stopped"
            self.bot_storage.save_bot(bot)
            raise ValueError("paper_trading disabled. Mainnet only.")

        account_snapshot = self._get_account_snapshot()
        account_equity = account_snapshot.get("equity", 0.0)

        try:
            launch_analysis = self._validate_and_prepare_launch(bot, "Start")
            notes = launch_analysis.get("notes") or []
            if notes:
                logger.info(
                    "[%s] Start sizing notes: %s",
                    bot.get("symbol"),
                    "; ".join(str(note) for note in notes),
                )
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            logger.error(f"Error during pre-launch validation: {e}")
            bot["last_error"] = f"Pre-launch validation error: {e}"
            bot["status"] = "stopped"
            self.bot_storage.save_bot(bot)
            raise ValueError(f"Pre-launch validation error: {e}")

        # Validation passed or not configured - start the bot

        # Set leverage on Bybit before starting
        symbol = bot.get("symbol")
        leverage = bot.get("leverage", DEFAULT_LEVERAGE)
        bot_env = "mainnet"

        # Auto-Pilot bots skip all exchange operations - runner handles when actual coin is picked
        _skip_exchange_setup = bot.get("auto_pilot") and (not symbol or symbol == "Auto-Pilot")
        if _skip_exchange_setup:
            logger.info(f"[Auto-Pilot] Skipping exchange setup for auto_pilot bot {bot_id}")

        indicator_service_for_gates = None
        try:
          if not _skip_exchange_setup:
            from services.client_factory import create_bybit_client
            from services.indicator_service import IndicatorService
            env_client = create_bybit_client(trading_env=bot_env, paper_trading=False)
            indicator_service_for_gates = IndicatorService(env_client)

            # =================================================================
            # RECENTER NEUTRAL CLASSIC BOT
            # =================================================================
            if bot.get("mode") == "neutral_classic_bybit":
                logger.info(f"[{symbol}] Recentering neutral classic bot on start...")
                try:
                    tickers = env_client.get_tickers(symbol)
                    if tickers.get("success"):
                        tick_list = (tickers.get("data") or {}).get("list") or []
                        if tick_list:
                            last_price = float(tick_list[0].get("lastPrice", 0) or 0)
                            if last_price > 0:
                                lower = float(bot.get("grid_lower_price") or bot.get("lower_price") or 0)
                                upper = float(bot.get("grid_upper_price") or bot.get("upper_price") or 0)
                                if lower > 0 and upper > lower:
                                    width = upper - lower
                                    new_lower = max(last_price - width / 2.0, 0.0000001)
                                    new_upper = last_price + width / 2.0
                                    bot["grid_lower_price"] = new_lower
                                    bot["grid_upper_price"] = new_upper
                                    bot["lower_price"] = new_lower
                                    bot["upper_price"] = new_upper
                                    bot["neutral_grid"] = {}
                                    bot["neutral_grid_initialized"] = False
                                    logger.info(f"[{symbol}] Recentered to {new_lower:.4f}-{new_upper:.4f} (price={last_price})")
                except Exception as e:
                    logger.warning(f"[{symbol}] Failed to recenter: {e}")

            # (The legacy min-notional preflight check here was removed because _validate_and_prepare_launch 
            # already performed a comprehensive, grid-cap-aware affordability check at the beginning of start_bot)

            # =================================================================
            # FORCE ISOLATED MARGIN MODE (NEW - Part 4)
            # =================================================================
            # Must set ISOLATED mode before trading for safety
            margin_result = env_client.set_margin_mode(symbol, "ISOLATED")
            if margin_result.get("success"):
                logger.info(f"[{symbol}] margin_mode_set=ISOLATED leverage_set={leverage}")
            elif margin_result.get("retCode") == 110026:
                # Already isolated - not an error
                logger.debug(f"[{symbol}] Margin mode already ISOLATED")
            else:
                error_msg = margin_result.get("error", margin_result.get("retMsg", "unknown"))
                error_lower = error_msg.lower()
                # Check for "already isolated" variants
                if "isolated" in error_lower and ("already" in error_lower or "same" in error_lower):
                    logger.debug(f"[{symbol}] Margin mode already ISOLATED")
                # Unified accounts don't support margin mode switching - that's OK, they handle it differently
                elif "unified" in error_lower or "forbidden" in error_lower:
                    logger.info(f"[{symbol}] Unified account detected - margin mode managed by exchange")
                else:
                    logger.error(f"[{symbol}] Failed to set ISOLATED margin: {error_msg}")
                    # Fail safe: do NOT start bot if we can't ensure isolated margin
                    bot["last_error"] = f"Margin setup failed: {error_msg}"
                    bot["status"] = "stopped"
                    self.bot_storage.save_bot(bot)
                    raise ValueError(
                        f"Cannot set ISOLATED margin: {error_msg}. Trading blocked for safety."
                    )

            # Clamp leverage to instrument limits (min/max/step)
            leverage_to_set = leverage
            try:
                inst = env_client.get_instruments_info(symbol)
                if inst.get("success"):
                    lst = (inst.get("data", {}) or {}).get("list", []) or []
                    if lst:
                        filt = (lst[0].get("leverageFilter") or {})
                        min_leverage = float(filt.get("minLeverage", leverage_to_set))
                        max_leverage = float(filt.get("maxLeverage", leverage_to_set))
                        step = float(filt.get("leverageStep", 0.01))
                        leverage_to_set = max(min(leverage_to_set, max_leverage), min_leverage)
                        # round to step
                        leverage_to_set = round(leverage_to_set / step) * step
                        bot["leverage"] = leverage_to_set
                else:
                    logger.warning(f"[{symbol}] Could not fetch instrument info for leverage clamp: {inst.get('error')}")
            except Exception as e:
                logger.warning(f"[{symbol}] Leverage clamp failed (non-fatal): {e}")

            # Set leverage on Bybit
            leverage_result = env_client.set_leverage(symbol, leverage_to_set)

            if leverage_result.get("success"):
                logger.info(f"✅ Set leverage to {leverage_to_set}x for {symbol} on Bybit ({bot_env})")
            else:
                # Bybit returns error if leverage is already set to same value - not a real error
                error_msg = leverage_result.get("error", "Unknown error")
                if "leverage not modified" in error_msg.lower() or leverage_result.get("retCode") == 110043:
                    logger.info(f"Leverage already set to {leverage_to_set}x for {symbol}")
                else:
                    logger.error(f"Failed to set leverage for {symbol}: {error_msg}")
                    bot["last_error"] = f"Leverage setup failed: {error_msg}"
                    bot["status"] = "stopped"
                    self.bot_storage.save_bot(bot)
                    raise ValueError(f"Failed to set leverage for {symbol}: {error_msg}")

            if bot.get("mode") == "neutral_classic_bybit":
                hedge_error = self._check_hedge_mode_required(bot, env_client)
                if hedge_error:
                    bot["status"] = "error"
                    bot["error_code"] = "HEDGE_MODE_REQUIRED"
                    bot["last_error"] = hedge_error
                    self.bot_storage.save_bot(bot)
                    raise ValueError(hedge_error)

                # Auto-detect preset if not set
                if not bot.get("neutral_preset"):
                    bot["neutral_preset"] = (
                        "MAJOR" if symbol in NEUTRAL_MAJOR_SYMBOLS else "MEME"
                    )
                    logger.info(f"[{symbol}] Auto-detected neutral preset: {bot['neutral_preset']}")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            logger.error(f"Could not set leverage/margin for {symbol}: {e}")
            bot["last_error"] = f"Leverage/margin setup failed: {e}"
            bot["status"] = "stopped"
            self.bot_storage.save_bot(bot)
            raise ValueError(f"Failed to configure leverage/margin for {symbol}: {e}")

        self._mark_control_state_change(bot)
        bot["status"] = "running"
        bot["last_error"] = None
        bot["error_code"] = None
        bot["last_run_at"] = None  # Clear cooldown on fresh start
        bot["last_trade_price"] = None  # Clear price tracking on fresh start
        bot["initial_entry_done"] = False  # Re-arm initial entry on every start
        self._clear_pause_runtime_state(bot)
        self._clear_stale_stop_cleanup_restart_state(bot)
        self._reset_session_runtime_state(bot)
        self._suppress_expired_absolute_session_window_on_manual_start(bot)
        self._clear_entry_gate_runtime_state(bot)
        if _skip_exchange_setup:
            self._reset_auto_pilot_placeholder_runtime_state(bot)
        else:
            self._refresh_activation_gate_state(
                bot,
                symbol,
                indicator_service_for_gates,
            )
        # Re-arm TP session from current realized baseline on each start
        bot["tp_session_realized_baseline"] = float(bot.get("realized_pnl", 0.0) or 0.0)
        # Re-arm balance target for this session. After a hit, the next run
        # targets current_balance + configured_target instead of the stale old threshold.
        self._arm_auto_stop_target_for_session(bot, account_equity)
        bot["started_at"] = datetime.now(timezone.utc).isoformat()  # Track when bot started
        self._record_control_stage(
            bot,
            "start",
            control_action_kind="start",
            control_action_received_at=iso_from_ts(control_started_at),
            start_state_persisted_at=bot["started_at"],
            control_action_ack_at=bot["started_at"],
            control_action_to_state_persist_ms=elapsed_ms(
                control_started_at,
                datetime.fromisoformat(bot["started_at"]).timestamp(),
            ),
            control_action_to_ack_ms=elapsed_ms(
                control_started_at,
                datetime.fromisoformat(bot["started_at"]).timestamp(),
            ),
            runner_pickup_at=None,
            control_action_to_runner_pickup_ms=None,
            start_to_runtime_active_ms=None,
            first_order_submitted_at=None,
            start_to_first_order_ms=None,
            pending_runner_pickup=True,
        )
        
        # Ensure accumulated runtime exists
        if "accumulated_runtime_hours" not in bot:
            bot["accumulated_runtime_hours"] = 0.0

        # Log critical warning if starting on mainnet
        trading_env = "mainnet"
        paper_trading = False

        logger.warning(
            f"🚨 Bot {bot_id} starting on BYBIT MAINNET environment - REAL MONEY at risk! "
            f"(paper_trading={paper_trading})"
        )

        saved_bot = self.bot_storage.save_bot(bot)
        logger.info(f"✅ Bot started: {bot_id} ({saved_bot.get('symbol')})")

        return saved_bot

    def _update_accumulated_runtime(self, bot: Dict[str, Any]):
        """Helper to update accumulated runtime hours."""
        if not bot.get("started_at"):
            return
        try:
            started_dt = datetime.fromisoformat(str(bot["started_at"]).replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            duration_sec = (now_dt - started_dt).total_seconds()
            if duration_sec > 0:
                hours = duration_sec / 3600.0
                current = float(bot.get("accumulated_runtime_hours") or 0.0)
                bot["accumulated_runtime_hours"] = current + hours
        except Exception as e:
            logger.warning(f"Failed to update runtime: {e}")

    @staticmethod
    def _clear_pause_runtime_state(bot: Dict[str, Any]) -> None:
        """Clear pause/recovery markers before a fresh start or resume."""
        for key in (
            "pause_reason",
            "pause_reason_type",
            "paused_at",
            "pause_unrealized_pnl",
            "recovery_entry_pnl",
            "_last_pause_recovery_check",
            "_last_recovery_check",
            "_neutral_trend_exit",
            "flash_crash_paused_at",
        ):
            bot.pop(key, None)

    @classmethod
    def _clear_stale_stop_cleanup_restart_state(cls, bot: Dict[str, Any]) -> None:
        """Drop stale cleanup truth before a fresh start or resume."""
        cls._clear_stop_cleanup_pending_fields(bot)
        bot["reduce_only_mode"] = False
        bot["auto_stop_paused"] = False

    def _cancel_opening_orders_preserve_exits(
        self, bot: Dict[str, Any], symbol: str
    ) -> Dict[str, Any]:
        """Cancel only bot-owned entry orders while preserving reduce-only exits."""
        return self._cancel_bot_owned_orders(
            bot,
            symbol,
            include_reduce_only=False,
        )

    def _cancel_all_bot_orders(
        self, bot: Dict[str, Any], symbol: str
    ) -> Dict[str, Any]:
        """Cancel all bot-owned orders without touching sibling bots."""
        return self._cancel_bot_owned_orders(
            bot,
            symbol,
            include_reduce_only=True,
        )

    def _cancel_bot_owned_orders(
        self,
        bot: Dict[str, Any],
        symbol: str,
        *,
        include_reduce_only: bool,
    ) -> Dict[str, Any]:
        """Cancel bot-owned orders only; optionally preserve reduce-only exits."""
        if not self.client or not symbol:
            return {"success": False, "error": "missing_client_or_symbol"}

        mode = (bot.get("mode") or "").lower()
        if mode == "neutral_classic_bybit":
            if include_reduce_only:
                return self._cancel_neutral_bot_orders(
                    bot,
                    symbol,
                    cancel_all=True,
                )
            return self._cancel_neutral_entry_orders(bot, symbol)

        from services.grid_bot_service import GridBotService

        orders_result = self.client.get_open_orders(
            symbol=symbol,
            limit=200,
            skip_cache=True,
        )
        if not orders_result.get("success"):
            return {
                "success": False,
                "error": orders_result.get("error", "open_orders_failed"),
            }

        orders = orders_result.get("data", {})
        if isinstance(orders, dict):
            orders = orders.get("list", [])
        orders = orders or []

        bot_id = bot.get("id")
        cancelled = 0
        failures = 0

        for order in orders:
            order_id = order.get("orderId")
            order_link_id = order.get("orderLinkId")
            parsed = GridBotService._parse_order_link_id(order_link_id)
            if not GridBotService._bot_id_matches_order_bot_id(
                bot_id, parsed.get("bot_id")
            ):
                continue

            reduce_only = order.get("reduceOnly")
            if reduce_only is None and parsed.get("intent") == "close":
                reduce_only = True
            if not include_reduce_only and bool(reduce_only):
                continue
            if not order_id:
                continue

            try:
                cancel_result = self.client.cancel_order(
                    symbol=symbol,
                    order_id=order_id,
                    order_link_id=order_link_id,
                )
                if cancel_result and not cancel_result.get("success", True):
                    failures += 1
                    logger.warning(
                        "[%s] Exchange rejected cancel for bot-owned order %s on bot %s: %s",
                        symbol,
                        order_id,
                        bot_id,
                        cancel_result.get("error", "unknown_error"),
                    )
                    continue
                cancelled += 1
            except Exception as exc:
                failures += 1
                logger.warning(
                    "[%s] Failed to cancel bot-owned order %s while cancelling bot %s: %s",
                    symbol,
                    order_id,
                    bot_id,
                    exc,
                )

        result = {"success": failures == 0, "cancelled": cancelled}
        if failures:
            result["error"] = "cancel_failed"
            result["failures"] = failures
        return result

    def _close_bot_position_market(
        self, bot: Dict[str, Any], symbol: str
    ) -> Dict[str, Any]:
        """Close symbol positions with bot-attributable reduce-only market orders."""
        if not self.client or not symbol:
            return {
                "success": False,
                "error": "missing_client_or_symbol",
                "retCode": -1,
            }

        try:
            overall_started_at = now_ts()
            positions_resp = self.client.get_positions(skip_cache=True)
            if not positions_resp.get("success"):
                return {
                    "success": False,
                    "error": positions_resp.get("error", "positions_fetch_failed"),
                    "retCode": positions_resp.get("retCode", -1),
                }

            positions = positions_resp.get("data", {}).get("list", []) or []
            bot_short = ((bot or {}).get("id") or "manual")[:8]
            closed_any = False
            last_order_timing = None

            for pos in positions:
                if pos.get("symbol") != symbol:
                    continue

                side = pos.get("side")
                size = float(pos.get("size", 0) or 0)
                if not side or size <= 0:
                    continue

                close_side = "Sell" if str(side).lower() == "buy" else "Buy"
                try:
                    position_idx = int(pos.get("positionIdx", 0) or 0)
                except (TypeError, ValueError):
                    position_idx = 0

                result = self.client.create_order(
                    symbol=symbol,
                    side=close_side,
                    qty=size,
                    order_type="Market",
                    price=None,
                    reduce_only=True,
                    time_in_force="GTC",
                    order_link_id=(
                        f"close_{bot_short}_{int(time.time() * 1000)}_{position_idx}"
                    ),
                    position_idx=position_idx,
                    ownership_snapshot=build_order_ownership_snapshot(
                        bot,
                        source="bot_manager_service",
                        action="emergency_close",
                        close_reason="EMRG",
                    ),
                )
                last_order_timing = dict((result or {}).get("timing") or {})
                if result.get("position_empty"):
                    logger.info(
                        "[%s] Bot-aware emergency close skipped for bot %s idx=%s: position already flat",
                        symbol,
                        bot.get("id"),
                        position_idx,
                    )
                    continue
                if not result.get("success"):
                    logger.error(
                        "[%s] Bot-aware emergency close failed for bot %s: %s",
                        symbol,
                        bot.get("id"),
                        result.get("error"),
                    )
                    return result
                closed_any = True

            if not closed_any:
                return {
                    "success": True,
                    "message": "no_position",
                    "retCode": 0,
                    "timing": {
                        "close_total_ms": elapsed_ms(overall_started_at, now_ts()),
                    },
                }

            return {
                "success": True,
                "message": "position_closed",
                "retCode": 0,
                "timing": {
                    **(last_order_timing or {}),
                    "close_total_ms": elapsed_ms(overall_started_at, now_ts()),
                },
            }
        except Exception as exc:
            logger.error("[%s] Bot-aware emergency close exception: %s", symbol, exc)
            return {"success": False, "error": str(exc), "retCode": -1}

    def _confirm_symbol_flat(self, symbol: str) -> Dict[str, Any]:
        check_started_at = now_ts()
        try:
            positions_resp = self.client.get_positions(skip_cache=True)
            if not positions_resp.get("success"):
                return {
                    "success": False,
                    "error": positions_resp.get("error", "positions_fetch_failed"),
                    "flat": False,
                }
            positions = positions_resp.get("data", {}).get("list", []) or []
            for pos in positions:
                if pos.get("symbol") != symbol:
                    continue
                try:
                    if float(pos.get("size", 0) or 0) > 0:
                        return {
                            "success": True,
                            "flat": False,
                            "flat_confirmed_at": None,
                            "stop_to_flat_ms": None,
                        }
                except (TypeError, ValueError):
                    continue
            confirmed_at = now_ts()
            return {
                "success": True,
                "flat": True,
                "flat_confirmed_at": iso_from_ts(confirmed_at),
                "stop_to_flat_ms": elapsed_ms(check_started_at, confirmed_at),
            }
        except Exception as exc:
            logger.warning("[%s] Flat confirmation failed: %s", symbol, exc)
            return {"success": False, "error": str(exc), "flat": False}

    def pause_bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """
        Pause a bot, cancel new-entry orders, and preserve reduce-only exits.

        Args:
            bot_id: Unique bot identifier

        Returns:
            Updated bot dictionary or None if not found
        """
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            logger.warning(f"Bot not found: {bot_id}")
            return None

        # Update runtime before pausing if the bot is actively ticking
        if bot.get("status") in ("running", "recovering"):
            self._update_accumulated_runtime(bot)
            bot["started_at"] = None

        symbol = bot.get("symbol")
        pause_ts = (
            self.client._get_now_ts()
            if self.client and hasattr(self.client, "_get_now_ts")
            else datetime.now(timezone.utc).timestamp()
        )
        self._mark_control_state_change(bot)
        self._clear_pause_runtime_state(bot)
        bot["status"] = "paused"
        bot["pause_reason"] = "Manual pause"
        bot["pause_reason_type"] = "manual"
        bot["paused_at"] = pause_ts
        bot["last_error"] = "Manual pause"

        cancel_result = None
        if self._is_tradeable_symbol(symbol):
            try:
                cancel_result = self._cancel_opening_orders_preserve_exits(bot, symbol)
            except Exception as exc:
                logger.warning(
                    "[%s] Failed to cancel opening orders during pause for %s: %s",
                    symbol,
                    bot_id,
                    exc,
                )

        saved_bot = self.bot_storage.save_bot(bot)
        if cancel_result and cancel_result.get("success"):
            logger.info(
                "Bot paused: %s (cancelled %d opening orders)",
                bot_id,
                int(cancel_result.get("cancelled", 0) or 0),
            )
        else:
            logger.info(f"Bot paused: {bot_id}")

        return saved_bot

    def resume_bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """
        Resume a paused-like bot.

        Args:
            bot_id: Unique bot identifier

        Returns:
            Updated bot dictionary or None if not found
        """
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            logger.warning(f"Bot not found: {bot_id}")
            return None

        original_status = bot.get("status")
        resumable_statuses = {"paused", "recovering", "flash_crash_paused"}
        if original_status in resumable_statuses:
            bot_env = (bot.get("trading_env") or "mainnet").lower()
            if bot_env != "mainnet":
                bot["last_error"] = "Testnet disabled. Mainnet only."
                bot["status"] = "stopped"
                self.bot_storage.save_bot(bot)
                raise ValueError("Testnet disabled. Mainnet only.")

            if bot.get("paper_trading"):
                bot["last_error"] = "paper_trading disabled. Mainnet only."
                bot["status"] = "stopped"
                self.bot_storage.save_bot(bot)
                raise ValueError("paper_trading disabled. Mainnet only.")

            account_snapshot = self._get_account_snapshot()
            account_equity = account_snapshot.get("equity", 0.0)

            try:
                launch_analysis = self._validate_and_prepare_launch(bot, "Resume")
                notes = launch_analysis.get("notes") or []
                if notes:
                    logger.info(
                        "[%s] Resume sizing notes: %s",
                        bot.get("symbol"),
                        "; ".join(str(note) for note in notes),
                    )
            except Exception as e:
                if isinstance(e, ValueError):
                    raise
                logger.error(f"Error during resume validation: {e}")
                bot["last_error"] = f"Resume validation error: {e}"
                bot["status"] = "stopped"
                self.bot_storage.save_bot(bot)
                raise ValueError(f"Resume validation error: {e}")

            self._mark_control_state_change(bot)
            bot["status"] = "running"
            bot["last_error"] = None
            bot["last_run_at"] = None  # Clear cooldown on resume
            self._clear_pause_runtime_state(bot)
            self._clear_stale_stop_cleanup_restart_state(bot)
            self._reset_session_runtime_state(bot)
            self._suppress_expired_absolute_session_window_on_manual_start(bot)
            self._clear_entry_gate_runtime_state(bot)
            if self._is_tradeable_symbol(bot.get("symbol")):
                from services.indicator_service import IndicatorService

                self._refresh_activation_gate_state(
                    bot,
                    str(bot.get("symbol") or "").strip(),
                    IndicatorService(self.client),
                )
            bot["tp_session_realized_baseline"] = float(
                bot.get("realized_pnl", 0.0) or 0.0
            )
            self._arm_auto_stop_target_for_session(bot, account_equity)
            bot["started_at"] = datetime.now(timezone.utc).isoformat()
            if original_status == "flash_crash_paused":
                bot["flash_crash_resumed_at"] = datetime.now(timezone.utc).isoformat()

            saved_bot = self.bot_storage.save_bot(bot)
            logger.info(f"Bot resumed: {bot_id}")
            return saved_bot

        # If not paused, just return current state
        logger.info(
            "Bot %s is not resumable (status: %s)", bot_id, bot.get("status")
        )
        return bot

    def soft_stop_bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """Stop a bot WITHOUT cancelling orders or closing positions.

        Orders stay on exchange. Restarting the bot will adopt them.
        Use this for temporary pauses where you want to resume later
        with the same grid state.
        """
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            logger.warning(f"Bot not found: {bot_id}")
            return None
        if bot.get("status") in ("running", "paused", "recovering"):
            self._update_accumulated_runtime(bot)
        self._mark_control_state_change(bot)
        bot["status"] = "stopped"
        bot["started_at"] = None
        bot["last_run_at"] = datetime.now(timezone.utc).isoformat()
        bot["last_error"] = "Soft stop (orders preserved)"

        # Auto-Pilot: reset symbol so it picks a fresh coin on next start
        if bot.get("auto_pilot"):
            reset_from_symbol = bot.get("symbol")
            if not self._is_auto_pilot_placeholder_symbol(reset_from_symbol):
                logger.info(
                    f"[Auto-Pilot] Resetting bot {bot_id} symbol from {reset_from_symbol} back to Auto-Pilot"
                )
                bot["symbol"] = "Auto-Pilot"
                self._reset_auto_pilot_placeholder_runtime_state(bot)
                self._mark_control_state_change(bot)

        saved = self.bot_storage.save_bot(bot)
        logger.info(f"Bot soft-stopped (orders preserved): {bot_id}")
        return saved

    def stop_bot(
        self,
        bot_id: str,
        *,
        action_received_at_ts: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Stop a bot and forcefully cancel all its open orders with verification.

        Args:
            bot_id: Unique bot identifier

        Returns:
            Updated bot dictionary or None if not found
        """
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            logger.warning(f"Bot not found: {bot_id}")
            return None

        bot = self._mark_bot_stopped_state(
            bot,
            scope="stop",
            action_received_at_ts=action_received_at_ts,
            cancel_orders=True,
        )
        self._normalize_mode_range_state(bot)

        # Auto-Pilot: reset symbol so it picks a fresh coin on next start.
        # Bump the control version again when reverting a traded symbol back to
        # the placeholder so a late stale save from the same stop sequence
        # cannot restore the old live symbol.
        if bot.get("auto_pilot"):
            reset_from_symbol = bot.get("symbol")
            if not self._is_auto_pilot_placeholder_symbol(reset_from_symbol):
                logger.info(
                    f"[Auto-Pilot] Resetting bot {bot_id} symbol from {reset_from_symbol} back to Auto-Pilot"
                )
                bot["symbol"] = "Auto-Pilot"
                self._reset_auto_pilot_placeholder_runtime_state(bot)
                self._mark_control_state_change(bot)
            else:
                self._reset_auto_pilot_placeholder_runtime_state(bot)

        saved_bot = self.bot_storage.save_bot(bot)
        logger.info(f"Bot stopped: {bot_id}")

        return saved_bot

    def delete_bot(self, bot_id: str) -> bool:
        """
        Delete a bot and forcefully cancel its orders with verification.

        C2: Requires bot to be stopped (or risk_stopped/error/tp_hit) and
        verifies no open position on the exchange before deleting.
        Raises ValueError if the bot is still active or has open positions.

        Args:
            bot_id: Unique bot identifier

        Returns:
            True if deleted, False otherwise

        Raises:
            ValueError: If bot is in an active status or has an open position.
        """
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            logger.warning(f"Bot not found for deletion: {bot_id}")
            return False

        symbol = bot.get("symbol")
        status = str(bot.get("status") or "").strip().lower()

        # C2: Block deletion of bots that are actively trading or cleaning up.
        # Paused-like bots are allowed because they don't place new orders,
        # but running/stop_cleanup_pending bots must be stopped first.
        non_deletable_statuses = {
            "running",
            "stop_cleanup_pending",
            "out_of_range",
        }
        if status in non_deletable_statuses:
            raise ValueError(
                f"Cannot delete bot in '{status}' state. Stop the bot first."
            )

        # C2: Verify the bot has no open position on the exchange.
        if self._is_tradeable_symbol(symbol):
            try:
                positions_resp = self.client.get_positions(skip_cache=True)
                if positions_resp.get("success"):
                    for pos in positions_resp.get("data", {}).get("list", []) or []:
                        if pos.get("symbol") != symbol:
                            continue
                        size = float(pos.get("size") or 0)
                        if size > 0:
                            raise ValueError(
                                f"Cannot delete bot: open {symbol} position "
                                f"(size={size}). Close the position first."
                            )
            except ValueError:
                raise
            except Exception as exc:
                logger.warning(
                    "[%s] Position check failed during delete, proceeding cautiously: %s",
                    symbol,
                    exc,
                )

        # Forcefully cancel orders before deleting
        if self._is_tradeable_symbol(symbol):
            if bot.get("mode") == "neutral_classic_bybit":
                cancel_result = self._cancel_neutral_bot_orders(
                    bot,
                    symbol,
                    cancel_all=True,
                )
                if not cancel_result.get("success"):
                    logger.error(f"[{symbol}] Failed to cancel neutral bot orders before deletion! {cancel_result.get('error')}")
            else:
                cancel_result = self._cancel_all_bot_orders(bot, symbol)
                if not cancel_result.get("success"):
                    logger.error(f"[{symbol}] Failed to cancel all bot-owned orders before deletion! {cancel_result.get('remaining', 0)} orders may still be open")

        deleted = self.bot_storage.delete_bot(bot_id)
        if deleted:
            logger.info(f"Bot deleted: {bot_id}")
        else:
            logger.warning(f"Failed to delete bot: {bot_id}")

        return deleted

    def list_bots(self) -> List[Dict[str, Any]]:
        """
        Get all bots with UPnL SL fields ensured (migration).

        Returns:
            List of all bot dictionaries
        """
        bots = self.bot_storage.list_bots()
        # Ensure all bots have UPnL SL fields (migration for existing bots)
        migrated_any = False
        for bot in bots:
            if "upnl_stoploss_enabled" not in bot:
                self._ensure_upnl_stoploss_fields(bot)
                migrated_any = True
        # Save migrated bots
        if migrated_any:
            for bot in bots:
                self.bot_storage.save_bot(bot)
        return bots

    def get_bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific bot by ID with UPnL SL fields ensured (migration).

        Args:
            bot_id: Unique bot identifier

        Returns:
            Bot dictionary or None if not found
        """
        bot = self.bot_storage.get_bot(bot_id)
        if bot:
            # Ensure bot has UPnL SL fields (migration for existing bots)
            if "upnl_stoploss_enabled" not in bot:
                self._ensure_upnl_stoploss_fields(bot)
                self.bot_storage.save_bot(bot)
        return bot
