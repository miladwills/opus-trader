import copy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


CONFIG_INTEGRITY_SHARED_BOOLEAN_FIELDS = (
    "auto_direction",
    "breakout_confirmed_entry",
    "auto_pilot",
    "trailing_sl_enabled",
    "quick_profit_enabled",
    "neutral_volatility_gate_enabled",
    "recovery_enabled",
    "entry_gate_enabled",
    "btc_correlation_filter_enabled",
)

CONFIG_INTEGRITY_MAIN_ONLY_BOOLEAN_FIELDS = (
    "auto_stop_loss_enabled",
    "auto_take_profit_enabled",
    "trend_protection_enabled",
    "danger_zone_enabled",
    "auto_neutral_mode_enabled",
)

CONFIG_INTEGRITY_UI_PATH_FIELDS = {
    "main": CONFIG_INTEGRITY_SHARED_BOOLEAN_FIELDS
    + CONFIG_INTEGRITY_MAIN_ONLY_BOOLEAN_FIELDS,
    "quick": CONFIG_INTEGRITY_SHARED_BOOLEAN_FIELDS,
}

CONFIG_INTEGRITY_CLIENT_EVENT_TYPES = {
    "config_runtime_mismatch",
    "config_ui_path_mismatch",
    "stale_render_after_save",
}


class ConfigIntegrityWatchdogService:
    """Build compact config round-trip truth blocks and emit watchdog events."""

    def __init__(self, bot_storage=None, audit_service=None):
        self.bot_storage = bot_storage
        self.audit_service = audit_service

    @staticmethod
    def _normalize_ui_path(ui_path: Any) -> str:
        normalized = str(ui_path or "").strip().lower()
        return normalized or "unknown"

    @classmethod
    def focus_boolean_fields(cls) -> tuple[str, ...]:
        return CONFIG_INTEGRITY_UI_PATH_FIELDS["main"]

    @classmethod
    def expected_fields_for_ui_path(cls, ui_path: Any) -> tuple[str, ...]:
        normalized = cls._normalize_ui_path(ui_path)
        return CONFIG_INTEGRITY_UI_PATH_FIELDS.get(normalized) or ()

    @staticmethod
    def _extract_boolean_values(source: Optional[Dict[str, Any]], fields: Iterable[str]) -> Dict[str, bool]:
        if not isinstance(source, dict):
            return {}
        payload: Dict[str, bool] = {}
        for field in fields:
            if field in source:
                payload[field] = bool(source.get(field))
        return payload

    @staticmethod
    def _filter_field_map(source: Dict[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
        return {field: copy.deepcopy(source[field]) for field in fields if field in source}

    @staticmethod
    def _subset_mismatches(
        requested: Dict[str, bool],
        observed: Dict[str, bool],
    ) -> list[Dict[str, Any]]:
        mismatches = []
        for field, requested_value in requested.items():
            if field not in observed:
                continue
            observed_value = bool(observed.get(field))
            if observed_value != requested_value:
                mismatches.append(
                    {
                        "field": field,
                        "requested": requested_value,
                        "observed": observed_value,
                    }
                )
        return mismatches

    @staticmethod
    def _event_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def build_roundtrip_audit(
        self,
        submitted_payload: Optional[Dict[str, Any]],
        saved_bot: Optional[Dict[str, Any]],
        *,
        persisted_bot: Optional[Dict[str, Any]] = None,
        previous_bot: Optional[Dict[str, Any]] = None,
        ui_path: Any = "unknown",
    ) -> Dict[str, Any]:
        submitted_payload = dict(submitted_payload or {})
        saved_bot = dict(saved_bot or {})
        persisted_bot = dict(persisted_bot or saved_bot or {})
        previous_bot = dict(previous_bot or {})

        normalized_ui_path = self._normalize_ui_path(ui_path)
        expected_fields = self.expected_fields_for_ui_path(normalized_ui_path)
        if not expected_fields:
            expected_fields = tuple(
                field for field in self.focus_boolean_fields() if field in submitted_payload
            )
        checked_fields = [field for field in expected_fields if field in submitted_payload]
        missing_expected_fields = [
            field for field in expected_fields if field not in submitted_payload
        ]

        requested_values = self._extract_boolean_values(submitted_payload, checked_fields)
        response_values = self._extract_boolean_values(saved_bot, checked_fields)
        persisted_values = self._extract_boolean_values(persisted_bot, checked_fields)
        previous_values = self._extract_boolean_values(previous_bot, checked_fields)

        missing_in_response = [field for field in checked_fields if field not in saved_bot]
        missing_in_persisted = [field for field in checked_fields if field not in persisted_bot]

        response_mismatches = self._subset_mismatches(requested_values, response_values)
        persisted_mismatches = self._subset_mismatches(requested_values, persisted_values)
        response_vs_persisted_mismatches = []
        for field in checked_fields:
            if field not in response_values or field not in persisted_values:
                continue
            if response_values[field] != persisted_values[field]:
                response_vs_persisted_mismatches.append(
                    {
                        "field": field,
                        "response": response_values[field],
                        "persisted": persisted_values[field],
                    }
                )

        changed_fields = []
        unchanged_requested_fields = []
        save_success_but_unchanged_fields = []
        for field in checked_fields:
            if field not in previous_values or field not in persisted_values:
                continue
            previous_value = previous_values[field]
            persisted_value = persisted_values[field]
            requested_value = requested_values.get(field)
            if previous_value != persisted_value:
                changed_fields.append(field)
            else:
                unchanged_requested_fields.append(field)
            if requested_value is not None and previous_value != requested_value and persisted_value == previous_value:
                save_success_but_unchanged_fields.append(field)

        normalized_fields = [
            {
                "field": item["field"],
                "requested": item["requested"],
                "persisted": item["observed"],
            }
            for item in persisted_mismatches
        ]

        persisted_matches_intent = (
            not missing_expected_fields
            and not missing_in_persisted
            and not persisted_mismatches
        )
        response_matches_intent = (
            not missing_expected_fields
            and not missing_in_response
            and not response_mismatches
        )

        return {
            "ui_path": normalized_ui_path,
            "bot_id": str(saved_bot.get("id") or submitted_payload.get("id") or "").strip() or None,
            "symbol": str(saved_bot.get("symbol") or submitted_payload.get("symbol") or "").strip().upper() or None,
            "checked_at": self._event_timestamp(),
            "expected_fields": list(expected_fields),
            "checked_fields": checked_fields,
            "missing_expected_fields": missing_expected_fields,
            "requested_values": requested_values,
            "previous_values": previous_values,
            "response_values": response_values,
            "persisted_values": persisted_values,
            "changed_fields": changed_fields,
            "unchanged_requested_fields": unchanged_requested_fields,
            "save_success_but_unchanged_fields": save_success_but_unchanged_fields,
            "missing_in_response": missing_in_response,
            "missing_in_persisted": missing_in_persisted,
            "response_mismatches": response_mismatches,
            "persisted_mismatches": persisted_mismatches,
            "response_vs_persisted_mismatches": response_vs_persisted_mismatches,
            "normalized_fields": normalized_fields,
            "response_matches_intent": response_matches_intent,
            "persisted_matches_intent": persisted_matches_intent,
        }

    def _record_event(
        self,
        payload: Dict[str, Any],
        *,
        throttle_key: Optional[str] = None,
        throttle_sec: Optional[float] = 0.0,
    ) -> bool:
        if not self.audit_service:
            return False
        return bool(
            self.audit_service.record_event(
                payload,
                throttle_key=throttle_key,
                throttle_sec=throttle_sec,
            )
        )

    def record_save_roundtrip(
        self,
        submitted_payload: Optional[Dict[str, Any]],
        saved_bot: Optional[Dict[str, Any]],
        *,
        persisted_bot: Optional[Dict[str, Any]] = None,
        previous_bot: Optional[Dict[str, Any]] = None,
        ui_path: Any = "unknown",
    ) -> Dict[str, Any]:
        audit = self.build_roundtrip_audit(
            submitted_payload,
            saved_bot,
            persisted_bot=persisted_bot,
            previous_bot=previous_bot,
            ui_path=ui_path,
        )
        bot_id = audit.get("bot_id")
        symbol = audit.get("symbol")
        normalized_fields = [item.get("field") for item in audit.get("normalized_fields") or []]
        dropped_fields = sorted(
            set(audit.get("missing_expected_fields") or [])
            | set(audit.get("missing_in_response") or [])
            | set(audit.get("missing_in_persisted") or [])
        )
        base_event = {
            "event_type": "config_save_roundtrip",
            "severity": "INFO" if audit.get("persisted_matches_intent") else "WARN",
            "bot_id": bot_id,
            "symbol": symbol,
            "ui_path": audit.get("ui_path"),
            "checked_fields": audit.get("checked_fields"),
            "changed_fields": audit.get("changed_fields"),
            "unchanged_requested_fields": audit.get("unchanged_requested_fields"),
            "normalized_fields": normalized_fields,
            "dropped_fields": dropped_fields,
            "save_success_but_unchanged_fields": audit.get("save_success_but_unchanged_fields"),
            "requested_values": audit.get("requested_values"),
            "previous_values": audit.get("previous_values"),
            "response_values": audit.get("response_values"),
            "persisted_values": audit.get("persisted_values"),
            "response_matches_intent": audit.get("response_matches_intent"),
            "persisted_matches_intent": audit.get("persisted_matches_intent"),
        }
        self._record_event(
            base_event,
            throttle_key=f"config_save_roundtrip:{bot_id}:{audit.get('ui_path')}",
            throttle_sec=0.0,
        )

        if dropped_fields:
            self._record_event(
                {
                    "event_type": "config_field_dropped",
                    "severity": "WARN",
                    "bot_id": bot_id,
                    "symbol": symbol,
                    "ui_path": audit.get("ui_path"),
                    "fields": dropped_fields,
                    "drop_stage": {
                        "payload": audit.get("missing_expected_fields"),
                        "response": audit.get("missing_in_response"),
                        "persisted": audit.get("missing_in_persisted"),
                    },
                },
                throttle_key=f"config_field_dropped:{bot_id}:{audit.get('ui_path')}:{','.join(dropped_fields)}",
                throttle_sec=0.0,
            )

        if audit.get("normalized_fields"):
            self._record_event(
                {
                    "event_type": "config_field_normalized_unexpectedly",
                    "severity": "WARN",
                    "bot_id": bot_id,
                    "symbol": symbol,
                    "ui_path": audit.get("ui_path"),
                    "fields": copy.deepcopy(audit.get("normalized_fields") or []),
                },
                throttle_key=f"config_field_normalized_unexpectedly:{bot_id}:{audit.get('ui_path')}:{','.join(normalized_fields)}",
                throttle_sec=0.0,
            )

        if audit.get("save_success_but_unchanged_fields"):
            self._record_event(
                {
                    "event_type": "save_success_but_unchanged",
                    "severity": "WARN",
                    "bot_id": bot_id,
                    "symbol": symbol,
                    "ui_path": audit.get("ui_path"),
                    "fields": list(audit.get("save_success_but_unchanged_fields") or []),
                    "requested_values": self._filter_field_map(
                        audit.get("requested_values") or {},
                        audit.get("save_success_but_unchanged_fields") or [],
                    ),
                    "persisted_values": self._filter_field_map(
                        audit.get("persisted_values") or {},
                        audit.get("save_success_but_unchanged_fields") or [],
                    ),
                },
                throttle_key=f"save_success_but_unchanged:{bot_id}:{audit.get('ui_path')}:{','.join(audit.get('save_success_but_unchanged_fields') or [])}",
                throttle_sec=0.0,
            )

        if (
            dropped_fields
            or audit.get("normalized_fields")
            or audit.get("response_vs_persisted_mismatches")
            or audit.get("response_mismatches")
            or audit.get("persisted_mismatches")
        ):
            self._record_event(
                {
                    "event_type": "config_roundtrip_mismatch",
                    "severity": "WARN",
                    "bot_id": bot_id,
                    "symbol": symbol,
                    "ui_path": audit.get("ui_path"),
                    "dropped_fields": dropped_fields,
                    "response_mismatches": copy.deepcopy(audit.get("response_mismatches") or []),
                    "persisted_mismatches": copy.deepcopy(audit.get("persisted_mismatches") or []),
                    "response_vs_persisted_mismatches": copy.deepcopy(
                        audit.get("response_vs_persisted_mismatches") or []
                    ),
                },
                throttle_key=f"config_roundtrip_mismatch:{bot_id}:{audit.get('ui_path')}",
                throttle_sec=0.0,
            )

        return audit

    def record_settings_version_conflict(
        self,
        submitted_payload: Optional[Dict[str, Any]],
        existing_bot: Optional[Dict[str, Any]],
        *,
        ui_path: Any = "unknown",
        conflict_reason: str,
        incoming_settings_version: Any,
        current_settings_version: Any,
    ) -> bool:
        submitted_payload = dict(submitted_payload or {})
        existing_bot = dict(existing_bot or {})
        normalized_ui_path = self._normalize_ui_path(ui_path)
        expected_fields = self.expected_fields_for_ui_path(normalized_ui_path)
        touched_fields = [
            field for field in expected_fields if field in submitted_payload
        ]
        record = {
            "event_type": "settings_version_conflict",
            "severity": "WARN",
            "bot_id": str(existing_bot.get("id") or submitted_payload.get("id") or "").strip() or None,
            "symbol": str(existing_bot.get("symbol") or submitted_payload.get("symbol") or "").strip().upper() or None,
            "mode": str(submitted_payload.get("mode") or existing_bot.get("mode") or "").strip().lower() or None,
            "ui_path": normalized_ui_path,
            "incoming_settings_version": incoming_settings_version,
            "current_settings_version": current_settings_version,
            "conflict_reason": str(conflict_reason or "").strip().lower() or "unknown",
            "fields": touched_fields,
        }
        return self._record_event(record, throttle_sec=0.0)

    def record_client_report(self, payload: Optional[Dict[str, Any]]) -> bool:
        payload = dict(payload or {})
        event_type = str(payload.get("event_type") or "").strip()
        if event_type not in CONFIG_INTEGRITY_CLIENT_EVENT_TYPES:
            return False
        bot_id = str(payload.get("bot_id") or "").strip() or None
        symbol = str(payload.get("symbol") or "").strip().upper() or None
        ui_path = self._normalize_ui_path(payload.get("ui_path"))
        fields = [str(field).strip() for field in (payload.get("fields") or []) if str(field).strip()]
        record = {
            "event_type": event_type,
            "severity": "WARN",
            "bot_id": bot_id,
            "symbol": symbol,
            "ui_path": ui_path,
            "fields": fields,
            "requested_values": dict(payload.get("requested_values") or {}),
            "response_values": dict(payload.get("response_values") or {}),
            "persisted_values": dict(payload.get("persisted_values") or {}),
            "runtime_values": dict(payload.get("runtime_values") or {}),
            "mismatch_count": len(fields),
            "details": dict(payload.get("details") or {}),
        }
        return self._record_event(
            record,
            throttle_key=f"{event_type}:{bot_id}:{ui_path}:{','.join(fields)}",
            throttle_sec=0.0,
        )
