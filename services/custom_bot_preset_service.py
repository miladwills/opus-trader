from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.lock_service import file_lock


SUPPORTED_CUSTOM_BOT_PRESET_FIELDS = (
    "range_mode",
    "leverage",
    "grid_count",
    "target_grid_count",
    "grid_distribution",
    "neutral_volatility_gate_threshold_pct",
    "session_timer_enabled",
    "session_start_at",
    "session_stop_at",
    "session_no_new_entries_before_stop_min",
    "session_end_mode",
    "session_green_grace_min",
    "session_cancel_pending_orders_on_end",
    "session_reduce_only_on_end",
    "session_duration_min",
    "session_time_selection_required",
)


class CustomBotPresetService:
    """Persist user-owned bot presets for reuse during new bot creation."""

    DEFAULTS: Dict[str, Any] = {
        "items": [],
        "updated_at": None,
    }

    def __init__(
        self,
        file_path: str,
        *,
        bot_storage: Optional[Any] = None,
        audit_diagnostics_service: Optional[Any] = None,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.file_path = Path(file_path)
        self.lock_path = Path(f"{file_path}.lock")
        self.bot_storage = bot_storage
        self.audit_diagnostics_service = audit_diagnostics_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_locked(dict(self.DEFAULTS))

    def list_presets(self) -> List[Dict[str, Any]]:
        with self._file_lock(exclusive=False):
            data = self._normalize(self._read_unlocked())
        return copy.deepcopy(list(data.get("items") or []))

    def get_preset(self, preset_id: str) -> Dict[str, Any] | None:
        normalized_preset_id = self._normalize_preset_id(preset_id)
        if not normalized_preset_id:
            return None
        for item in self.list_presets():
            if str(item.get("preset_id") or "") == normalized_preset_id:
                return copy.deepcopy(item)
        return None

    def create_preset(
        self,
        *,
        preset_name: str,
        fields: Dict[str, Any],
        source_bot_id: Any = None,
        symbol_hint: Any = None,
        mode_hint: Any = None,
    ) -> Dict[str, Any]:
        normalized_name = self._normalize_preset_name(preset_name)
        if not normalized_name:
            raise ValueError("preset_name_required")
        normalized_fields, session_sanitized = self._prepare_fields_for_storage(fields)
        if not normalized_fields:
            raise ValueError("no_supported_fields")
        now_iso = self.now_fn().isoformat()
        preset = {
            "preset_id": f"custom:{uuid.uuid4().hex}",
            "preset_name": normalized_name,
            "preset_type": "custom",
            "source_bot_id": str(source_bot_id or "").strip() or None,
            "symbol_hint": str(symbol_hint or "").strip().upper() or None,
            "mode_hint": str(mode_hint or "").strip().lower() or None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "fields": normalized_fields,
        }
        with self._file_lock(exclusive=True):
            data = self._normalize(self._read_unlocked())
            items = list(data.get("items") or [])
            items.append(preset)
            data["items"] = items
            data["updated_at"] = now_iso
            self._write_unlocked(data)
        if session_sanitized:
            self._record_event(
                event_type="custom_bot_preset_session_sanitized",
                preset=preset,
                metadata={
                    "session_duration_min": normalized_fields.get("session_duration_min"),
                    "requires_time_selection": bool(normalized_fields.get("session_time_selection_required")),
                },
            )
        self._record_event(
            event_type="custom_bot_preset_created",
            preset=preset,
            metadata={"key_fields": list(normalized_fields.keys())},
        )
        return copy.deepcopy(preset)

    def update_preset(
        self,
        preset_id: str,
        *,
        preset_name: Any = None,
        symbol_hint: Any = None,
        mode_hint: Any = None,
    ) -> Dict[str, Any]:
        normalized_preset_id = self._normalize_preset_id(preset_id)
        if not normalized_preset_id:
            raise ValueError("preset_not_found")

        updated = None
        with self._file_lock(exclusive=True):
            data = self._normalize(self._read_unlocked())
            items = list(data.get("items") or [])
            for index, item in enumerate(items):
                if str(item.get("preset_id") or "") != normalized_preset_id:
                    continue
                next_item = dict(item)
                if preset_name is not None:
                    normalized_name = self._normalize_preset_name(preset_name)
                    if not normalized_name:
                        raise ValueError("preset_name_required")
                    next_item["preset_name"] = normalized_name
                if symbol_hint is not None:
                    next_item["symbol_hint"] = str(symbol_hint or "").strip().upper() or None
                if mode_hint is not None:
                    next_item["mode_hint"] = str(mode_hint or "").strip().lower() or None
                next_item["updated_at"] = self.now_fn().isoformat()
                items[index] = next_item
                updated = next_item
                break
            if updated is None:
                raise ValueError("preset_not_found")
            data["items"] = items
            data["updated_at"] = self.now_fn().isoformat()
            self._write_unlocked(data)

        self._record_event(
            event_type="custom_bot_preset_rename",
            preset=updated,
            metadata={
                "symbol_hint": updated.get("symbol_hint"),
                "mode_hint": updated.get("mode_hint"),
            },
        )
        return copy.deepcopy(updated)

    def create_from_bot(self, bot_id: str, *, preset_name: str) -> Dict[str, Any]:
        if self.bot_storage is None or not hasattr(self.bot_storage, "get_bot"):
            raise ValueError("bot_storage_unavailable")
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            raise ValueError("bot_not_found")
        preset = self.create_preset(
            preset_name=preset_name,
            fields=dict(bot),
            source_bot_id=bot_id,
            symbol_hint=bot.get("symbol"),
            mode_hint=bot.get("mode"),
        )
        self._record_event(
            event_type="custom_bot_preset_created_from_bot",
            preset=preset,
            metadata={"source_bot_id": str(bot_id or "").strip() or None},
        )
        return preset

    def delete_preset(self, preset_id: str) -> bool:
        normalized_preset_id = self._normalize_preset_id(preset_id)
        if not normalized_preset_id:
            return False
        deleted = None
        with self._file_lock(exclusive=True):
            data = self._normalize(self._read_unlocked())
            items = list(data.get("items") or [])
            kept = []
            for item in items:
                if str(item.get("preset_id") or "") == normalized_preset_id and deleted is None:
                    deleted = dict(item)
                    continue
                kept.append(item)
            if deleted is None:
                return False
            data["items"] = kept
            data["updated_at"] = self.now_fn().isoformat()
            self._write_unlocked(data)
        self._record_event(
            event_type="custom_bot_preset_deleted",
            preset=deleted,
            metadata={"key_fields": list(dict(deleted.get("fields") or {}).keys())},
        )
        return True

    def _prepare_fields_for_storage(self, fields: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        extracted = self.extract_supported_fields(fields)
        return self._sanitize_session_fields(extracted)

    @classmethod
    def extract_supported_fields(cls, source: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(source or {})
        extracted: Dict[str, Any] = {}

        range_mode = str(payload.get("range_mode") or "").strip().lower()
        if range_mode in {"fixed", "dynamic", "trailing"}:
            extracted["range_mode"] = range_mode

        leverage = cls._safe_float(payload.get("leverage"), None)
        if leverage is not None and leverage > 0:
            extracted["leverage"] = round(leverage, 4)

        target_grid_count = cls._safe_int(payload.get("target_grid_count"), None)
        grid_count = cls._safe_int(payload.get("grid_count"), None)
        if target_grid_count is not None and target_grid_count > 0:
            extracted["target_grid_count"] = target_grid_count
            extracted["grid_count"] = target_grid_count
        elif grid_count is not None and grid_count > 0:
            extracted["grid_count"] = grid_count

        grid_distribution = str(payload.get("grid_distribution") or "").strip().lower()
        if grid_distribution in {"clustered", "balanced", "buy_heavy", "sell_heavy"}:
            extracted["grid_distribution"] = grid_distribution

        volatility_gate = cls._safe_float(payload.get("neutral_volatility_gate_threshold_pct"), None)
        if volatility_gate is not None and volatility_gate > 0:
            extracted["neutral_volatility_gate_threshold_pct"] = volatility_gate

        session_timer_enabled = payload.get("session_timer_enabled")
        if session_timer_enabled is not None:
            extracted["session_timer_enabled"] = bool(session_timer_enabled)
        for field in (
            "session_start_at",
            "session_stop_at",
        ):
            if payload.get(field):
                extracted[field] = str(payload.get(field))
        session_no_new = cls._safe_int(payload.get("session_no_new_entries_before_stop_min"), None)
        if session_no_new is not None and session_no_new >= 0:
            extracted["session_no_new_entries_before_stop_min"] = session_no_new
        session_end_mode = str(payload.get("session_end_mode") or "").strip().lower()
        if session_end_mode in {"hard_stop", "soft_stop", "green_grace_then_stop"}:
            extracted["session_end_mode"] = session_end_mode
        session_grace = cls._safe_int(payload.get("session_green_grace_min"), None)
        if session_grace is not None and session_grace >= 0:
            extracted["session_green_grace_min"] = session_grace
        for field in (
            "session_cancel_pending_orders_on_end",
            "session_reduce_only_on_end",
        ):
            if field in payload:
                extracted[field] = bool(payload.get(field))
        session_duration_min = cls._safe_int(payload.get("session_duration_min"), None)
        if session_duration_min is not None and session_duration_min > 0:
            extracted["session_duration_min"] = session_duration_min
        if "session_time_selection_required" in payload:
            extracted["session_time_selection_required"] = bool(payload.get("session_time_selection_required"))

        return {
            field: extracted[field]
            for field in SUPPORTED_CUSTOM_BOT_PRESET_FIELDS
            if field in extracted
        }

    def _sanitize_session_fields(self, extracted: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
        fields = dict(extracted or {})
        session_enabled = bool(fields.get("session_timer_enabled"))
        if not session_enabled:
            fields.pop("session_start_at", None)
            fields.pop("session_stop_at", None)
            fields.pop("session_duration_min", None)
            fields.pop("session_time_selection_required", None)
            return fields, False

        raw_start = fields.pop("session_start_at", None)
        raw_stop = fields.pop("session_stop_at", None)
        sanitized = bool(raw_start or raw_stop)
        session_duration_min = self._derive_session_duration_minutes(raw_start, raw_stop)
        if session_duration_min is not None:
            fields["session_duration_min"] = session_duration_min
            fields["session_time_selection_required"] = False
        else:
            fields.pop("session_duration_min", None)
            fields["session_time_selection_required"] = True
        return fields, sanitized

    @staticmethod
    def _derive_session_duration_minutes(start_value: Any, stop_value: Any) -> int | None:
        if not start_value or not stop_value:
            return None
        try:
            started_at = datetime.fromisoformat(str(start_value))
            stopped_at = datetime.fromisoformat(str(stop_value))
            duration_seconds = (stopped_at - started_at).total_seconds()
        except (TypeError, ValueError):
            return None
        if duration_seconds < 1800:
            return None
        duration_minutes = int(round(duration_seconds / 60.0))
        return max(30, min(duration_minutes, 720))

    @classmethod
    def build_key_fields(cls, fields: Dict[str, Any]) -> List[Dict[str, Any]]:
        summary_fields = (
            "leverage",
            "grid_count",
            "grid_distribution",
            "session_timer_enabled",
            "session_duration_min",
            "session_time_selection_required",
            "session_end_mode",
        )
        items: List[Dict[str, Any]] = []
        for field in summary_fields:
            if field not in fields:
                continue
            value = fields.get(field)
            if field == "session_end_mode" and not fields.get("session_timer_enabled"):
                continue
            if field == "session_duration_min" and not fields.get("session_timer_enabled"):
                continue
            if field == "session_time_selection_required" and not value:
                continue
            items.append(
                {
                    "field": field,
                    "label": cls._field_label(field),
                    "value": value,
                }
            )
        return items

    @staticmethod
    def _field_label(field: str) -> str:
        labels = {
            "range_mode": "Range mode",
            "leverage": "Leverage",
            "grid_count": "Grid count",
            "target_grid_count": "Target grid count",
            "grid_distribution": "Grid distribution",
            "neutral_volatility_gate_threshold_pct": "Volatility gate",
            "session_timer_enabled": "Session timer",
            "session_start_at": "Session start",
            "session_stop_at": "Session stop",
            "session_no_new_entries_before_stop_min": "No new entries before stop",
            "session_end_mode": "Session end mode",
            "session_green_grace_min": "Green grace minutes",
            "session_cancel_pending_orders_on_end": "Cancel pending on end",
            "session_reduce_only_on_end": "Reduce-only on end",
            "session_duration_min": "Session duration",
            "session_time_selection_required": "Fresh session time",
        }
        return labels.get(field, field.replace("_", " "))

    def _normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(self.DEFAULTS)
        if isinstance(data, dict):
            normalized.update(data)
        items: List[Dict[str, Any]] = []
        for raw_item in list(normalized.get("items") or []):
            if not isinstance(raw_item, dict):
                continue
            preset_id = self._normalize_preset_id(raw_item.get("preset_id"))
            if not preset_id:
                continue
            fields, _ = self._prepare_fields_for_storage(dict(raw_item.get("fields") or {}))
            if not fields:
                continue
            items.append(
                {
                    "preset_id": preset_id,
                    "preset_name": self._normalize_preset_name(raw_item.get("preset_name")) or "Custom Preset",
                    "preset_type": "custom",
                    "source_bot_id": str(raw_item.get("source_bot_id") or "").strip() or None,
                    "symbol_hint": str(raw_item.get("symbol_hint") or "").strip().upper() or None,
                    "mode_hint": str(raw_item.get("mode_hint") or "").strip().lower() or None,
                    "created_at": raw_item.get("created_at"),
                    "updated_at": raw_item.get("updated_at"),
                    "fields": fields,
                }
            )
        items.sort(
            key=lambda item: (
                0 if dict(item.get("fields") or {}).get("session_timer_enabled") else 1,
                str(item.get("symbol_hint") or "ZZZZZZ"),
                str(item.get("mode_hint") or "zzzzzz"),
                str(item.get("preset_name") or "").lower(),
                str(item.get("updated_at") or ""),
            )
        )
        normalized["items"] = items
        return copy.deepcopy(normalized)

    def _read_unlocked(self) -> Dict[str, Any]:
        try:
            raw = self.file_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return dict(self.DEFAULTS)
        if not raw:
            return dict(self.DEFAULTS)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return dict(self.DEFAULTS)
        return data if isinstance(data, dict) else dict(self.DEFAULTS)

    def _write_locked(self, data: Dict[str, Any]) -> None:
        with self._file_lock(exclusive=True):
            self._write_unlocked(data)

    def _write_unlocked(self, data: Dict[str, Any]) -> None:
        self.file_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _file_lock(self, exclusive: bool = False):
        return file_lock(self.lock_path, exclusive=exclusive)

    @staticmethod
    def _normalize_preset_id(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        return raw if raw.startswith("custom:") else f"custom:{raw}"

    @staticmethod
    def _normalize_preset_name(value: Any) -> str:
        return str(value or "").strip()[:80]

    @staticmethod
    def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int | None = 0) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _record_event(
        self,
        *,
        event_type: str,
        preset: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        diagnostics_service = self.audit_diagnostics_service
        enabled_check = getattr(diagnostics_service, "enabled", None)
        is_enabled = enabled_check() if callable(enabled_check) else True
        if diagnostics_service is None or not is_enabled:
            return
        payload = {
            "event_type": event_type,
            "severity": "INFO",
            "timestamp": self.now_fn().isoformat(),
            "preset_id": str(preset.get("preset_id") or "") or None,
            "preset_name": str(preset.get("preset_name") or "") or None,
            "source_bot_id": str(preset.get("source_bot_id") or "") or None,
        }
        payload.update(dict(metadata or {}))
        diagnostics_service.record_event(payload, throttle_sec=0.0)
