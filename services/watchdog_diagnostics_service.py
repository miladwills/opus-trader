from __future__ import annotations

from typing import Any, Dict, Optional

from config.strategy_config import (
    AUDIT_DIAGNOSTICS_ENABLED,
    EXIT_STACK_WATCHDOG_COOLDOWN_SEC,
    EXIT_STACK_WATCHDOG_ENABLED,
    FILL_SLIPPAGE_WATCHDOG_COOLDOWN_SEC,
    FILL_SLIPPAGE_WATCHDOG_ENABLED,
    LOSS_ASYMMETRY_WATCHDOG_COOLDOWN_SEC,
    LOSS_ASYMMETRY_WATCHDOG_ENABLED,
    ORDER_STARVATION_WATCHDOG_COOLDOWN_SEC,
    ORDER_STARVATION_WATCHDOG_ENABLED,
    PNL_ATTRIBUTION_WATCHDOG_COOLDOWN_SEC,
    PNL_ATTRIBUTION_WATCHDOG_ENABLED,
    POSITION_DIVERGENCE_WATCHDOG_COOLDOWN_SEC,
    POSITION_DIVERGENCE_WATCHDOG_ENABLED,
    PROFIT_PROTECTION_WATCHDOG_COOLDOWN_SEC,
    PROFIT_PROTECTION_WATCHDOG_ENABLED,
    SIGNAL_DRIFT_WATCHDOG_COOLDOWN_SEC,
    SIGNAL_DRIFT_WATCHDOG_ENABLED,
    SL_FAILURE_WATCHDOG_COOLDOWN_SEC,
    SL_FAILURE_WATCHDOG_ENABLED,
    SMALL_BOT_SIZING_WATCHDOG_COOLDOWN_SEC,
    SMALL_BOT_SIZING_WATCHDOG_ENABLED,
    STATE_FLAPPING_WATCHDOG_COOLDOWN_SEC,
    STATE_FLAPPING_WATCHDOG_ENABLED,
    WATCHDOG_DIAGNOSTICS_ENABLED,
)
from services.watchdog_hub_service import WatchdogHubService


class WatchdogDiagnosticsService:
    """Shared passive watchdog emitter backed by audit diagnostics."""

    _KNOWN_WATCHDOGS = {
        "loss_asymmetry": {
            "enabled": LOSS_ASYMMETRY_WATCHDOG_ENABLED,
            "cooldown_sec": LOSS_ASYMMETRY_WATCHDOG_COOLDOWN_SEC,
        },
        "exit_stack": {
            "enabled": EXIT_STACK_WATCHDOG_ENABLED,
            "cooldown_sec": EXIT_STACK_WATCHDOG_COOLDOWN_SEC,
        },
        "small_bot_sizing": {
            "enabled": SMALL_BOT_SIZING_WATCHDOG_ENABLED,
            "cooldown_sec": SMALL_BOT_SIZING_WATCHDOG_COOLDOWN_SEC,
        },
        "signal_drift": {
            "enabled": SIGNAL_DRIFT_WATCHDOG_ENABLED,
            "cooldown_sec": SIGNAL_DRIFT_WATCHDOG_COOLDOWN_SEC,
        },
        "state_flapping": {
            "enabled": STATE_FLAPPING_WATCHDOG_ENABLED,
            "cooldown_sec": STATE_FLAPPING_WATCHDOG_COOLDOWN_SEC,
        },
        "pnl_attribution": {
            "enabled": PNL_ATTRIBUTION_WATCHDOG_ENABLED,
            "cooldown_sec": PNL_ATTRIBUTION_WATCHDOG_COOLDOWN_SEC,
        },
        "profit_protection": {
            "enabled": PROFIT_PROTECTION_WATCHDOG_ENABLED,
            "cooldown_sec": PROFIT_PROTECTION_WATCHDOG_COOLDOWN_SEC,
        },
        "order_starvation": {
            "enabled": ORDER_STARVATION_WATCHDOG_ENABLED,
            "cooldown_sec": ORDER_STARVATION_WATCHDOG_COOLDOWN_SEC,
        },
        "position_divergence": {
            "enabled": POSITION_DIVERGENCE_WATCHDOG_ENABLED,
            "cooldown_sec": POSITION_DIVERGENCE_WATCHDOG_COOLDOWN_SEC,
        },
        "sl_failure": {
            "enabled": SL_FAILURE_WATCHDOG_ENABLED,
            "cooldown_sec": SL_FAILURE_WATCHDOG_COOLDOWN_SEC,
        },
        "fill_slippage": {
            "enabled": FILL_SLIPPAGE_WATCHDOG_ENABLED,
            "cooldown_sec": FILL_SLIPPAGE_WATCHDOG_COOLDOWN_SEC,
        },
    }

    def __init__(self, audit_diagnostics_service: Optional[Any]) -> None:
        self.audit_diagnostics_service = audit_diagnostics_service

    def _get_watchdog_hub_service(self) -> Optional[WatchdogHubService]:
        audit_service = getattr(self, "audit_diagnostics_service", None)
        if getattr(audit_service, "file_path", None) is None:
            return None
        service = getattr(self, "_watchdog_hub_service", None)
        if service is None:
            service = WatchdogHubService(audit_service)
            self._watchdog_hub_service = service
        return service

    @classmethod
    def enabled(cls, watchdog_type: Optional[str] = None) -> bool:
        if not AUDIT_DIAGNOSTICS_ENABLED or not WATCHDOG_DIAGNOSTICS_ENABLED:
            return False
        if watchdog_type is None:
            return True
        settings = cls._KNOWN_WATCHDOGS.get(str(watchdog_type or "").strip().lower())
        return bool(settings and settings.get("enabled"))

    @staticmethod
    def _normalize_severity(value: Any) -> str:
        normalized = str(value or "INFO").strip().upper()
        if normalized not in {"INFO", "WARN", "ERROR", "CRITICAL"}:
            return "INFO"
        return normalized

    @staticmethod
    def _sanitize_scalar(value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        return str(value)

    @classmethod
    def _sanitize_mapping(cls, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in dict(payload or {}).items():
            if value is None:
                continue
            if isinstance(value, dict):
                nested = {
                    str(nested_key): cls._sanitize_scalar(nested_value)
                    for nested_key, nested_value in value.items()
                    if nested_value is not None
                }
                if nested:
                    cleaned[str(key)] = nested
            elif isinstance(value, (list, tuple)):
                items = [cls._sanitize_scalar(item) for item in value if item is not None]
                if items:
                    cleaned[str(key)] = items[:12]
            else:
                cleaned[str(key)] = cls._sanitize_scalar(value)
        return cleaned

    @classmethod
    def default_cooldown_sec(cls, watchdog_type: str) -> float:
        settings = cls._KNOWN_WATCHDOGS.get(str(watchdog_type or "").strip().lower()) or {}
        try:
            return max(float(settings.get("cooldown_sec") or 0.0), 0.0)
        except Exception:
            return 0.0

    def emit(
        self,
        *,
        watchdog_type: str,
        severity: str,
        reason: str,
        bot: Optional[Dict[str, Any]] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        compact_metrics: Optional[Dict[str, Any]] = None,
        suggested_action: Optional[str] = None,
        source_context: Optional[Dict[str, Any]] = None,
        throttle_key: Optional[str] = None,
        throttle_sec: Optional[float] = None,
    ) -> bool:
        normalized_type = str(watchdog_type or "").strip().lower()
        if not normalized_type or not self.enabled(normalized_type):
            return False
        diagnostics_service = getattr(self, "audit_diagnostics_service", None)
        if diagnostics_service is None or not diagnostics_service.enabled():
            return False
        resolved_bot_id = str(
            bot_id if bot_id is not None else ((bot or {}).get("id") if isinstance(bot, dict) else "")
        ).strip() or None
        resolved_symbol = str(
            symbol if symbol is not None else ((bot or {}).get("symbol") if isinstance(bot, dict) else "")
        ).strip().upper() or None
        resolved_mode = str(
            mode if mode is not None else ((bot or {}).get("mode") if isinstance(bot, dict) else "")
        ).strip().lower() or None
        normalized_reason = str(reason or "watch").strip().lower() or "watch"
        payload = {
            "event_type": "watchdog_event",
            "watchdog_type": normalized_type,
            "severity": self._normalize_severity(severity),
            "bot_id": resolved_bot_id,
            "symbol": resolved_symbol,
            "mode": resolved_mode,
            "reason": normalized_reason,
            "compact_metrics": self._sanitize_mapping(compact_metrics),
            "suggested_action": str(suggested_action or "").strip() or None,
            "source_context": self._sanitize_mapping(source_context),
        }
        if not payload["compact_metrics"]:
            payload.pop("compact_metrics")
        if not payload["source_context"]:
            payload.pop("source_context")
        resolved_key = (
            throttle_key
            or f"watchdog:{normalized_type}:{resolved_bot_id or 'na'}:{resolved_symbol or 'na'}:{normalized_reason}"
        )
        resolved_cooldown = (
            self.default_cooldown_sec(normalized_type)
            if throttle_sec is None
            else max(float(throttle_sec), 0.0)
        )
        recorded = diagnostics_service.record_event(
            payload,
            throttle_key=resolved_key,
            throttle_sec=resolved_cooldown,
        )
        if recorded:
            hub_service = self._get_watchdog_hub_service()
            if hub_service is not None:
                hub_service.record_watchdog_event(payload)
        return recorded
