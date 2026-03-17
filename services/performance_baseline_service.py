from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from services.lock_service import file_lock


class PerformanceBaselineService:
    """Manage global and per-bot performance baselines without mutating raw history."""

    def __init__(
        self,
        *,
        file_path: str = "storage/performance_baselines.json",
        diagnostics_export_service: Optional[Any] = None,
    ) -> None:
        self.file_path = Path(file_path)
        self.lock_path = Path(str(self.file_path) + ".lock")
        self.diagnostics_export_service = diagnostics_export_service
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_state(self._default_state())

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "global": {},
            "bots": {},
        }

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _utc_now_iso(cls) -> str:
        return cls._utc_now().isoformat()

    @staticmethod
    def _parse_iso(value: Any) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _epoch_id(prefix: str) -> str:
        token = uuid.uuid4().hex[:10]
        return f"{prefix}:{token}"

    def _read_state_unlocked(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            return self._default_state()
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return self._default_state()
        if not isinstance(payload, dict):
            return self._default_state()
        state = self._default_state()
        state.update(payload)
        state["global"] = dict(state.get("global") or {})
        state["bots"] = {
            str(key): dict(value)
            for key, value in dict(state.get("bots") or {}).items()
            if isinstance(value, dict)
        }
        return state

    def _read_state(self) -> Dict[str, Any]:
        try:
            with file_lock(self.lock_path, exclusive=False):
                return self._read_state_unlocked()
        except Exception:
            return self._default_state()

    def _write_state(self, state: Dict[str, Any]) -> None:
        payload = dict(self._default_state())
        payload.update(state or {})
        payload["global"] = dict(payload.get("global") or {})
        payload["bots"] = dict(payload.get("bots") or {})
        fd, temp_path = tempfile.mkstemp(dir=self.file_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temp_path, self.file_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def get_state(self) -> Dict[str, Any]:
        return self._read_state()

    def get_global_baseline(self) -> Dict[str, Any]:
        return dict(self._read_state().get("global") or {})

    def get_bot_baseline(self, bot_id: str) -> Dict[str, Any]:
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id:
            return {}
        return dict((self._read_state().get("bots") or {}).get(normalized_bot_id) or {})

    def get_global_started_at(self) -> Optional[datetime]:
        return self._parse_iso(self.get_global_baseline().get("baseline_started_at"))

    def get_effective_started_at(self, *, bot_id: Optional[str] = None) -> Optional[datetime]:
        global_dt = self.get_global_started_at()
        normalized_bot_id = str(bot_id or "").strip()
        if not normalized_bot_id:
            return global_dt
        bot_dt = self._parse_iso(self.get_bot_baseline(normalized_bot_id).get("baseline_started_at"))
        if global_dt is None:
            return bot_dt
        if bot_dt is None:
            return global_dt
        return max(global_dt, bot_dt)

    def build_metadata(self, *, bot_id: Optional[str] = None) -> Dict[str, Any]:
        state = self._read_state()
        global_meta = dict(state.get("global") or {})
        payload = {
            "version": int(state.get("version") or 1),
            "updated_at": state.get("updated_at"),
            "global": {
                "baseline_started_at": global_meta.get("baseline_started_at"),
                "epoch_id": global_meta.get("epoch_id"),
                "last_reset_at": global_meta.get("last_reset_at"),
                "last_archive_path": global_meta.get("last_archive_path"),
                "last_note": global_meta.get("last_note"),
            },
            "bot": None,
            "effective": {
                "scope": "global",
                "baseline_started_at": global_meta.get("baseline_started_at"),
                "epoch_id": global_meta.get("epoch_id"),
            },
            "bot_override_count": len(dict(state.get("bots") or {})),
        }
        normalized_bot_id = str(bot_id or "").strip()
        if normalized_bot_id:
            bot_meta = dict((state.get("bots") or {}).get(normalized_bot_id) or {})
            payload["bot"] = {
                "bot_id": normalized_bot_id,
                "baseline_started_at": bot_meta.get("baseline_started_at"),
                "epoch_id": bot_meta.get("epoch_id"),
                "last_reset_at": bot_meta.get("last_reset_at"),
                "last_archive_path": bot_meta.get("last_archive_path"),
                "last_note": bot_meta.get("last_note"),
            }
            effective_dt = self.get_effective_started_at(bot_id=normalized_bot_id)
            bot_dt = self._parse_iso(bot_meta.get("baseline_started_at"))
            global_dt = self._parse_iso(global_meta.get("baseline_started_at"))
            effective_scope = "legacy"
            if effective_dt is not None:
                effective_scope = "bot" if bot_dt is not None and (global_dt is None or bot_dt >= global_dt) else "global"
            payload["effective"] = {
                "scope": effective_scope,
                "baseline_started_at": effective_dt.isoformat() if effective_dt else None,
                "epoch_id": (
                    bot_meta.get("epoch_id")
                    if effective_scope == "bot"
                    else global_meta.get("epoch_id")
                ),
            }
        elif not payload["effective"]["baseline_started_at"]:
            payload["effective"]["scope"] = "legacy"
        return payload

    def _archive_reset(
        self,
        *,
        scope: str,
        bot_id: Optional[str],
        reset_at: str,
        epoch_id: str,
        note: Optional[str],
        previous_baseline: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "generated_at": reset_at,
            "export_type": "performance_reset",
            "app_name": "Opus Trader",
            "source": "baseline_reset",
            "data": {
                "scope": scope,
                "bot_id": bot_id,
                "reset_at": reset_at,
                "epoch_id": epoch_id,
                "note": str(note or "").strip() or None,
                "previous_baseline": previous_baseline,
                "snapshot": snapshot,
            },
        }
        service = getattr(self, "diagnostics_export_service", None)
        if service is None:
            return {"archive_path": None, "latest_path": None, "export_type": "performance_reset"}
        return service.write_export(
            "performance_reset",
            payload,
            generated_at=reset_at,
        )

    def reset(
        self,
        *,
        scope: str,
        bot_id: Optional[str] = None,
        note: Optional[str] = None,
        snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_scope = str(scope or "").strip().lower()
        normalized_bot_id = str(bot_id or "").strip() or None
        if normalized_scope not in {"global", "bot"}:
            raise ValueError("scope must be global or bot")
        if normalized_scope == "bot" and not normalized_bot_id:
            raise ValueError("bot_id is required for bot scope")

        reset_at = self._utc_now_iso()
        epoch_id = self._epoch_id(normalized_scope)
        archive_metadata: Dict[str, Any]
        with file_lock(self.lock_path, exclusive=True):
            state = self._read_state_unlocked()
            if normalized_scope == "global":
                previous_baseline = dict(state.get("global") or {})
            else:
                previous_baseline = dict((state.get("bots") or {}).get(normalized_bot_id) or {})
            archive_metadata = self._archive_reset(
                scope=normalized_scope,
                bot_id=normalized_bot_id,
                reset_at=reset_at,
                epoch_id=epoch_id,
                note=note,
                previous_baseline=previous_baseline,
                snapshot=dict(snapshot or {}),
            )
            baseline_payload = {
                "baseline_started_at": reset_at,
                "epoch_id": epoch_id,
                "last_reset_at": reset_at,
                "last_archive_path": archive_metadata.get("archive_path"),
                "last_note": str(note or "").strip() or None,
            }
            if normalized_scope == "global":
                state["global"] = baseline_payload
            else:
                state.setdefault("bots", {})[normalized_bot_id] = baseline_payload
            state["updated_at"] = reset_at
            self._write_state(state)

        metadata = self.build_metadata(bot_id=normalized_bot_id)
        effective = dict(metadata.get("effective") or {})
        return {
            "ok": True,
            "scope": normalized_scope,
            "bot_id": normalized_bot_id,
            "reset_at": reset_at,
            "baseline_started_at": effective.get("baseline_started_at") or reset_at,
            "epoch_id": effective.get("epoch_id") or epoch_id,
            "archive_path": archive_metadata.get("archive_path"),
            "archive_latest_path": archive_metadata.get("latest_path"),
            "performance_baseline": metadata,
        }
