from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


class BotTriageSettingsConflictError(ValueError):
    def __init__(
        self,
        *,
        bot_id: str,
        current_settings_version: int,
        incoming_settings_version: Any,
        conflict_reason: str,
    ) -> None:
        super().__init__("settings_version_conflict")
        self.bot_id = bot_id
        self.current_settings_version = current_settings_version
        self.incoming_settings_version = incoming_settings_version
        self.conflict_reason = conflict_reason


class BotTriageActionService:
    """Explicit, operator-triggered triage actions and preset helpers."""

    SUPPORTED_PRESETS = {"reduce_risk", "sleep_session"}
    DEFAULT_SLEEP_DURATION_HOURS = 2

    def __init__(
        self,
        *,
        bot_storage: Any,
        bot_manager: Any,
        runtime_settings_service: Optional[Any] = None,
        config_integrity_watchdog_service: Optional[Any] = None,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.bot_storage = bot_storage
        self.bot_manager = bot_manager
        self.runtime_settings_service = runtime_settings_service
        self.config_integrity_watchdog_service = config_integrity_watchdog_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def preview_preset(self, bot_id: str, preset: str) -> Dict[str, Any]:
        bot = self._require_bot(bot_id)
        normalized_preset = self._normalize_preset(preset)
        changes = self._build_preset_changes(bot, normalized_preset)
        return self._build_preview(bot, normalized_preset, changes)

    def apply_preset(
        self,
        bot_id: str,
        *,
        preset: str,
        incoming_settings_version: Any,
        ui_path: str = "triage",
    ) -> Dict[str, Any]:
        bot = self._require_bot(bot_id)
        normalized_preset = self._normalize_preset(preset)
        self._ensure_settings_version(bot, incoming_settings_version, ui_path=ui_path)
        changes = self._build_preset_changes(bot, normalized_preset)
        preview = self._build_preview(bot, normalized_preset, changes)
        if not changes:
            self._record_action(
                event_type=(
                    "triage_action_apply_reduce_preset"
                    if normalized_preset == "reduce_risk"
                    else "triage_action_apply_sleep_preset"
                ),
                bot=bot,
                changed_fields=[],
                metadata={"preset": normalized_preset, "no_changes": True},
            )
            return {
                "bot": bot,
                "preset": normalized_preset,
                "preview": preview,
                "changed_fields": [],
                "updated": False,
                "config_integrity_audit": None,
            }

        merged = copy.deepcopy(bot)
        merged.update(changes)
        saved_bot = self.bot_manager.create_or_update_bot(merged)
        persisted_bot = self.bot_storage.get_bot(str(saved_bot.get("id") or "").strip()) or saved_bot
        config_integrity_audit = None
        watchdog_service = self.config_integrity_watchdog_service
        if watchdog_service is not None:
            config_integrity_audit = watchdog_service.record_save_roundtrip(
                merged,
                saved_bot,
                persisted_bot=persisted_bot,
                previous_bot=bot,
                ui_path=ui_path,
            )
        self._record_action(
            event_type=(
                "triage_action_apply_reduce_preset"
                if normalized_preset == "reduce_risk"
                else "triage_action_apply_sleep_preset"
            ),
            bot=saved_bot,
            changed_fields=list(changes.keys()),
            metadata={"preset": normalized_preset},
        )
        return {
            "bot": saved_bot,
            "preset": normalized_preset,
            "preview": preview,
            "changed_fields": list(changes.keys()),
            "updated": True,
            "config_integrity_audit": config_integrity_audit,
        }

    def pause_action(
        self,
        bot_id: str,
        *,
        cancel_pending_requested: bool,
    ) -> Dict[str, Any]:
        bot = self.bot_manager.pause_bot(bot_id)
        if not bot:
            raise ValueError("bot_not_found")
        self._record_action(
            event_type=(
                "triage_action_pause_cancel_pending"
                if cancel_pending_requested
                else "triage_action_pause"
            ),
            bot=bot,
            changed_fields=["status", "pause_reason", "paused_at"],
            metadata={
                "cancel_pending_requested": bool(cancel_pending_requested),
                "cancel_scope": "opening_orders_only",
            },
        )
        return {
            "bot": bot,
            "cancel_scope": "opening_orders_only",
            "cancel_pending_requested": bool(cancel_pending_requested),
        }

    def dismiss(self, bot_id: str, *, verdict: Any) -> Dict[str, Any]:
        bot = self._require_bot(bot_id)
        if self.runtime_settings_service is not None:
            self.runtime_settings_service.set_bot_triage_override(
                bot_id,
                mode="dismissed",
                verdict=verdict,
            )
        self._record_action(
            event_type="triage_action_dismiss",
            bot=bot,
            changed_fields=[],
            metadata={"verdict": str(verdict or "").strip().upper() or None},
        )
        return {"bot_id": bot_id, "verdict": str(verdict or "").strip().upper() or None}

    def snooze(
        self,
        bot_id: str,
        *,
        verdict: Any,
        duration: str = "1h",
    ) -> Dict[str, Any]:
        bot = self._require_bot(bot_id)
        snooze_until = self._resolve_snooze_until(duration)
        if self.runtime_settings_service is not None:
            self.runtime_settings_service.set_bot_triage_override(
                bot_id,
                mode="snoozed",
                verdict=verdict,
                snooze_until=snooze_until,
            )
        self._record_action(
            event_type="triage_action_snooze",
            bot=bot,
            changed_fields=[],
            metadata={
                "verdict": str(verdict or "").strip().upper() or None,
                "duration": duration,
                "snooze_until": snooze_until,
            },
        )
        return {
            "bot_id": bot_id,
            "verdict": str(verdict or "").strip().upper() or None,
            "duration": duration,
            "snooze_until": snooze_until,
        }

    def _require_bot(self, bot_id: str) -> Dict[str, Any]:
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            raise ValueError("bot_not_found")
        return dict(bot)

    @classmethod
    def _normalize_preset(cls, preset: str) -> str:
        normalized = str(preset or "").strip().lower()
        if normalized not in cls.SUPPORTED_PRESETS:
            raise ValueError("unsupported_preset")
        return normalized

    def _build_preset_changes(self, bot: Dict[str, Any], preset: str) -> Dict[str, Any]:
        if preset == "reduce_risk":
            return self._build_reduce_risk_changes(bot)
        if preset == "sleep_session":
            return self._build_sleep_session_changes(bot)
        return {}

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _build_reduce_risk_changes(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        changes: Dict[str, Any] = {}
        leverage = max(self._safe_float(bot.get("leverage"), 1.0), 1.0)
        target_grid_count = max(
            self._safe_int(bot.get("target_grid_count"), 0),
            self._safe_int(bot.get("grid_count"), 0),
            3,
        )
        if leverage > 3.0:
            changes["leverage"] = 3.0
        if target_grid_count > 8:
            changes["grid_count"] = 8
            changes["target_grid_count"] = 8
        if str(bot.get("grid_distribution") or "").strip().lower() == "clustered":
            changes["grid_distribution"] = "balanced"
        return changes

    def _build_sleep_session_changes(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        now_dt = self.now_fn()
        stop_at = now_dt + timedelta(hours=self.DEFAULT_SLEEP_DURATION_HOURS)
        return {
            "session_timer_enabled": True,
            "session_start_at": bot.get("session_start_at"),
            "session_stop_at": stop_at.isoformat(),
            "session_no_new_entries_before_stop_min": 20,
            "session_end_mode": "green_grace_then_stop",
            "session_green_grace_min": 15,
            "session_cancel_pending_orders_on_end": True,
            "session_reduce_only_on_end": True,
        }

    def _build_preview(
        self,
        bot: Dict[str, Any],
        preset: str,
        changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        changed_fields = []
        for field, to_value in changes.items():
            from_value = bot.get(field)
            if from_value == to_value:
                continue
            changed_fields.append(
                {
                    "field": field,
                    "from": from_value,
                    "to": to_value,
                    "label": self._field_label(field),
                }
            )
        return {
            "preset": preset,
            "title": (
                "Reduce Risk Preset"
                if preset == "reduce_risk"
                else "Sleep Session Preset"
            ),
            "summary_lines": self._build_summary_lines(preset, changed_fields),
            "changed_fields": changed_fields,
            "no_changes": len(changed_fields) == 0,
        }

    def _build_summary_lines(
        self,
        preset: str,
        changed_fields: list[Dict[str, Any]],
    ) -> list[str]:
        if not changed_fields:
            return ["No config changes are needed for this preset."]
        lines = []
        for item in changed_fields:
            field = item.get("field")
            label = item.get("label")
            if field == "session_stop_at":
                lines.append(
                    f"{label} {self._format_value(item.get('from'))} -> {self._format_value(item.get('to'))}"
                )
            else:
                lines.append(
                    f"{label} {self._format_value(item.get('from'))} -> {self._format_value(item.get('to'))}"
                )
        if preset == "sleep_session":
            lines.insert(0, "Enable a 2h session timer with green grace stop.")
        return lines[:6]

    @staticmethod
    def _format_value(value: Any) -> str:
        if value in (None, ""):
            return "off"
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, float):
            return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _field_label(field: str) -> str:
        labels = {
            "leverage": "Leverage",
            "grid_count": "Grid count",
            "target_grid_count": "Target grid count",
            "grid_distribution": "Grid distribution",
            "session_timer_enabled": "Session timer",
            "session_start_at": "Session start",
            "session_stop_at": "Session stop",
            "session_no_new_entries_before_stop_min": "No new entries before stop",
            "session_end_mode": "Session end mode",
            "session_green_grace_min": "Green grace minutes",
            "session_cancel_pending_orders_on_end": "Cancel pending orders on end",
            "session_reduce_only_on_end": "Reduce-only on end",
        }
        return labels.get(field, field.replace("_", " "))

    def _ensure_settings_version(
        self,
        bot: Dict[str, Any],
        incoming_settings_version: Any,
        *,
        ui_path: str,
    ) -> None:
        current_settings_version = self._safe_int(bot.get("settings_version"), 0)
        try:
            normalized_incoming = int(incoming_settings_version)
        except (TypeError, ValueError):
            normalized_incoming = None
        if normalized_incoming is None or normalized_incoming != current_settings_version:
            conflict_reason = (
                "missing_incoming_version"
                if normalized_incoming is None
                else "stale_incoming_version"
            )
            watchdog_service = self.config_integrity_watchdog_service
            if watchdog_service is not None:
                watchdog_service.record_settings_version_conflict(
                    bot,
                    bot,
                    ui_path=ui_path,
                    conflict_reason=conflict_reason,
                    incoming_settings_version=normalized_incoming,
                    current_settings_version=current_settings_version,
                )
            raise BotTriageSettingsConflictError(
                bot_id=str(bot.get("id") or "").strip(),
                current_settings_version=current_settings_version,
                incoming_settings_version=normalized_incoming,
                conflict_reason=conflict_reason,
            )

    def _resolve_snooze_until(self, duration: str) -> str:
        normalized = str(duration or "").strip().lower() or "1h"
        now_dt = self.now_fn()
        if normalized == "today":
            end_of_day = now_dt.replace(hour=23, minute=59, second=59, microsecond=0)
            return end_of_day.isoformat()
        return (now_dt + timedelta(hours=1)).isoformat()

    def _record_action(
        self,
        *,
        event_type: str,
        bot: Dict[str, Any],
        changed_fields: list[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        diagnostics_service = getattr(self.bot_manager, "audit_diagnostics_service", None)
        enabled_check = getattr(diagnostics_service, "enabled", None)
        is_enabled = enabled_check() if callable(enabled_check) else True
        if diagnostics_service is None or not is_enabled:
            return
        payload = {
            "event_type": event_type,
            "severity": "INFO",
            "timestamp": self.now_fn().isoformat(),
            "bot_id": str(bot.get("id") or "").strip() or None,
            "symbol": str(bot.get("symbol") or "").strip().upper() or None,
            "action": event_type.replace("triage_action_", ""),
            "changed_fields": list(changed_fields or []),
        }
        payload.update(dict(metadata or {}))
        diagnostics_service.record_event(payload, throttle_sec=0.0)
