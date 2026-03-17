"""
Runtime dashboard/runner settings persisted under storage/.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from services.lock_service import file_lock


class RuntimeSettingsService:
    """Persist lightweight server-side dashboard/runtime toggles."""

    DEFAULTS: Dict[str, Any] = {
        "auto_stop_on_direction_change": False,
        "bot_triage_overrides": {},
        "bot_config_advisor_queued_applies": {},
        "updated_at": None,
    }

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.lock_path = Path(f"{file_path}.lock")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_locked(dict(self.DEFAULTS))

    def get_settings(self) -> Dict[str, Any]:
        with self._file_lock(exclusive=False):
            return self._normalize(self._read_unlocked())

    def get_auto_stop_on_direction_change(self) -> bool:
        settings = self.get_settings()
        return bool(settings.get("auto_stop_on_direction_change"))

    def set_auto_stop_on_direction_change(self, enabled: Any) -> Dict[str, Any]:
        with self._file_lock(exclusive=True):
            settings = self._normalize(self._read_unlocked())
            settings["auto_stop_on_direction_change"] = bool(enabled)
            settings["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_unlocked(settings)
            return copy.deepcopy(settings)

    def get_bot_triage_overrides(self) -> Dict[str, Dict[str, Any]]:
        settings = self.get_settings()
        return copy.deepcopy(dict(settings.get("bot_triage_overrides") or {}))

    def set_bot_triage_override(
        self,
        bot_id: Any,
        *,
        mode: str,
        verdict: Any,
        snooze_until: Any = None,
    ) -> Dict[str, Any]:
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id:
            return self.get_settings()
        normalized_mode = str(mode or "").strip().lower() or "dismissed"
        normalized_verdict = str(verdict or "").strip().upper() or None
        with self._file_lock(exclusive=True):
            settings = self._normalize(self._read_unlocked())
            overrides = dict(settings.get("bot_triage_overrides") or {})
            entry = {
                "mode": normalized_mode,
                "verdict": normalized_verdict,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if normalized_mode == "snoozed" and snooze_until:
                entry["snooze_until"] = str(snooze_until)
            overrides[normalized_bot_id] = entry
            settings["bot_triage_overrides"] = overrides
            settings["updated_at"] = entry["updated_at"]
            self._write_unlocked(settings)
            return copy.deepcopy(settings)

    def clear_bot_triage_override(self, bot_id: Any) -> Dict[str, Any]:
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id:
            return self.get_settings()
        with self._file_lock(exclusive=True):
            settings = self._normalize(self._read_unlocked())
            overrides = dict(settings.get("bot_triage_overrides") or {})
            overrides.pop(normalized_bot_id, None)
            settings["bot_triage_overrides"] = overrides
            settings["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_unlocked(settings)
            return copy.deepcopy(settings)

    def get_bot_config_advisor_queued_applies(self) -> Dict[str, Dict[str, Any]]:
        settings = self.get_settings()
        return copy.deepcopy(dict(settings.get("bot_config_advisor_queued_applies") or {}))

    def get_bot_config_advisor_queued_apply(self, bot_id: Any) -> Dict[str, Any] | None:
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id:
            return None
        settings = self.get_settings()
        entry = dict(settings.get("bot_config_advisor_queued_applies") or {}).get(normalized_bot_id)
        if not isinstance(entry, dict):
            return None
        return copy.deepcopy(entry)

    def set_bot_config_advisor_queued_apply(
        self,
        bot_id: Any,
        entry: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id or not isinstance(entry, dict):
            return self.get_settings()
        with self._file_lock(exclusive=True):
            settings = self._normalize(self._read_unlocked())
            queued = dict(settings.get("bot_config_advisor_queued_applies") or {})
            cleaned = self._normalize_queued_apply_entry(entry)
            cleaned["updated_at"] = datetime.now(timezone.utc).isoformat()
            queued[normalized_bot_id] = cleaned
            settings["bot_config_advisor_queued_applies"] = queued
            settings["updated_at"] = cleaned["updated_at"]
            self._write_unlocked(settings)
            return copy.deepcopy(settings)

    def clear_bot_config_advisor_queued_apply(self, bot_id: Any) -> Dict[str, Any]:
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id:
            return self.get_settings()
        with self._file_lock(exclusive=True):
            settings = self._normalize(self._read_unlocked())
            queued = dict(settings.get("bot_config_advisor_queued_applies") or {})
            queued.pop(normalized_bot_id, None)
            settings["bot_config_advisor_queued_applies"] = queued
            settings["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_unlocked(settings)
            return copy.deepcopy(settings)

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

    def _write_locked(self, settings: Dict[str, Any]) -> None:
        with self._file_lock(exclusive=True):
            self._write_unlocked(settings)

    def _write_unlocked(self, settings: Dict[str, Any]) -> None:
        self.file_path.write_text(
            json.dumps(settings, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _normalize(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(self.DEFAULTS)
        if isinstance(settings, dict):
            normalized.update(settings)
        normalized["auto_stop_on_direction_change"] = bool(
            normalized.get("auto_stop_on_direction_change")
        )
        overrides: Dict[str, Dict[str, Any]] = {}
        for bot_id, entry in dict(normalized.get("bot_triage_overrides") or {}).items():
            normalized_bot_id = str(bot_id or "").strip()
            if not normalized_bot_id or not isinstance(entry, dict):
                continue
            cleaned = {
                "mode": str(entry.get("mode") or "dismissed").strip().lower() or "dismissed",
                "verdict": str(entry.get("verdict") or "").strip().upper() or None,
                "updated_at": entry.get("updated_at"),
            }
            if entry.get("snooze_until"):
                cleaned["snooze_until"] = str(entry.get("snooze_until"))
            overrides[normalized_bot_id] = cleaned
        normalized["bot_triage_overrides"] = overrides
        queued_applies: Dict[str, Dict[str, Any]] = {}
        for bot_id, entry in dict(normalized.get("bot_config_advisor_queued_applies") or {}).items():
            normalized_bot_id = str(bot_id or "").strip()
            if not normalized_bot_id or not isinstance(entry, dict):
                continue
            queued_applies[normalized_bot_id] = self._normalize_queued_apply_entry(entry)
        normalized["bot_config_advisor_queued_applies"] = queued_applies
        return copy.deepcopy(normalized)

    @staticmethod
    def _normalize_queued_apply_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
        try:
            base_settings_version = int(entry.get("base_settings_version") or 0)
        except (TypeError, ValueError):
            base_settings_version = 0
        applicable_changes = []
        for item in list(entry.get("applicable_changes") or []):
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            if not field:
                continue
            applicable_changes.append(
                {
                    "field": field,
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "label": str(item.get("label") or field.replace("_", " ")),
                }
            )
        advisory_only_changes = []
        for item in list(entry.get("advisory_only_changes") or []):
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            if not field:
                continue
            advisory_only_changes.append(
                {
                    "field": field,
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "label": str(item.get("label") or field.replace("_", " ")),
                }
            )
        queued_fields = [item["field"] for item in applicable_changes]
        advisory_only_fields = [item["field"] for item in advisory_only_changes]
        return {
            "state": str(entry.get("state") or "waiting_for_flat").strip().lower() or "waiting_for_flat",
            "recommendation_type": str(entry.get("recommendation_type") or "").strip().upper() or None,
            "base_settings_version": base_settings_version,
            "applicable_changes": applicable_changes,
            "advisory_only_changes": advisory_only_changes,
            "queued_fields": queued_fields,
            "advisory_only_fields": advisory_only_fields,
            "blocked_reason": str(entry.get("blocked_reason") or "").strip().lower() or None,
            "queued_at": entry.get("queued_at"),
            "updated_at": entry.get("updated_at"),
            "applied_at": entry.get("applied_at"),
            "failed_at": entry.get("failed_at"),
            "generated_at": entry.get("generated_at"),
            "symbol": str(entry.get("symbol") or "").strip().upper() or None,
        }

    def _file_lock(self, exclusive: bool = False):
        return file_lock(self.lock_path, exclusive=exclusive)
