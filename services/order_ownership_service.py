import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from services.lock_service import file_lock

logger = logging.getLogger(__name__)

OWNER_SNAPSHOT_RETENTION_DAYS = 30

BOT_SNAPSHOT_FIELDS = (
    ("bot_id", "id"),
    ("bot_investment", "investment"),
    ("bot_leverage", "leverage"),
    ("bot_mode", "mode"),
    ("bot_range_mode", "range_mode"),
    ("bot_started_at", "started_at"),
    ("bot_profile", "small_capital_profile"),
    ("bot_profile_fallback", "profile"),
    ("effective_step_pct", "effective_step_pct"),
    ("fee_aware_min_step_pct", "fee_aware_min_step_pct"),
    ("runtime_open_order_cap_total", "runtime_open_order_cap_total"),
    ("atr_5m_pct", "atr_5m_pct"),
    ("atr_15m_pct", "atr_15m_pct"),
    ("regime_effective", "regime_effective"),
)


def build_order_ownership_snapshot(
    bot: Optional[Dict[str, Any]] = None,
    *,
    owner_state: str = "owned",
    source: Optional[str] = None,
    action: Optional[str] = None,
    close_reason: Optional[str] = None,
    forensic_decision_id: Optional[str] = None,
    forensic_trade_context_id: Optional[str] = None,
    forensic_decision_type: Optional[str] = None,
    forensic_side: Optional[str] = None,
    forensic_lifecycle_started_at: Optional[str] = None,
) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "owner_state": str(owner_state or "owned").strip().lower() or "owned",
        "source": str(source or "").strip() or None,
        "action": str(action or "").strip() or None,
        "close_reason": str(close_reason or "").strip() or None,
        "forensic_decision_id": str(forensic_decision_id or "").strip() or None,
        "forensic_trade_context_id": (
            str(forensic_trade_context_id or "").strip() or None
        ),
        "forensic_decision_type": str(forensic_decision_type or "").strip() or None,
        "forensic_side": str(forensic_side or "").strip() or None,
        "forensic_lifecycle_started_at": (
            str(forensic_lifecycle_started_at or "").strip() or None
        ),
        "bot_id": None,
        "bot_investment": None,
        "bot_leverage": None,
        "bot_mode": None,
        "bot_range_mode": None,
        "bot_started_at": None,
        "bot_profile": None,
        "effective_step_pct": None,
        "fee_aware_min_step_pct": None,
        "runtime_open_order_cap_total": None,
        "atr_5m_pct": None,
        "atr_15m_pct": None,
        "regime_effective": None,
    }
    if not bot:
        return snapshot

    for target_field, source_field in BOT_SNAPSHOT_FIELDS:
        value = bot.get(source_field)
        if target_field == "bot_profile" and not value:
            value = bot.get("profile")
        snapshot[target_field] = value
    return snapshot


class OrderOwnershipService:
    """Persist durable ownership breadcrumbs for later trade attribution."""

    def __init__(self, file_path: str = "storage/order_ownership.json"):
        self.file_path = Path(file_path)
        self.lock_path = Path(str(file_path) + ".lock")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_state({"version": 1, "by_order_id": {}, "by_order_link_id": {}})

    @contextmanager
    def _file_lock(self, exclusive: bool = False):
        with file_lock(self.lock_path, exclusive=exclusive) as lock_fd:
            yield lock_fd

    def _read_state(self) -> Dict[str, Any]:
        try:
            with self._file_lock(exclusive=False):
                return self._read_state_unlocked()
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            pass
        return {"version": 1, "by_order_id": {}, "by_order_link_id": {}}

    def _read_state_unlocked(self) -> Dict[str, Any]:
        with open(self.file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("version", 1)
                data.setdefault("by_order_id", {})
                data.setdefault("by_order_link_id", {})
                return data
        return {"version": 1, "by_order_id": {}, "by_order_link_id": {}}

    def _write_state(self, state: Dict[str, Any]) -> None:
        try:
            with self._file_lock(exclusive=True):
                self._write_state_unlocked(state)
        except (OSError, IOError) as exc:
            logger.warning("Failed to write order ownership state: %s", exc)

    def _write_state_unlocked(self, state: Dict[str, Any]) -> None:
        dir_path = self.file_path.parent
        fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.file_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    @staticmethod
    def _parse_iso(raw_value: Any) -> Optional[datetime]:
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            return None
        normalized = raw_text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _prune_state(self, state: Dict[str, Any]) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=OWNER_SNAPSHOT_RETENTION_DAYS)
        for index_name in ("by_order_id", "by_order_link_id"):
            index = state.get(index_name)
            if not isinstance(index, dict):
                state[index_name] = {}
                continue
            stale_keys = []
            for key, record in index.items():
                recorded_at = self._parse_iso((record or {}).get("recorded_at"))
                if recorded_at and recorded_at < cutoff:
                    stale_keys.append(key)
            for key in stale_keys:
                index.pop(key, None)

    @staticmethod
    def _normalized_record(record: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(record or {})
        normalized["order_id"] = str(normalized.get("order_id") or "").strip() or None
        normalized["order_link_id"] = (
            str(normalized.get("order_link_id") or "").strip() or None
        )
        normalized["symbol"] = str(normalized.get("symbol") or "").strip().upper() or None
        normalized["side"] = str(normalized.get("side") or "").strip() or None
        owner_state = str(normalized.get("owner_state") or "owned").strip().lower()
        normalized["owner_state"] = owner_state or "owned"
        normalized["source"] = str(normalized.get("source") or "").strip() or None
        normalized["action"] = str(normalized.get("action") or "").strip() or None
        normalized["close_reason"] = (
            str(normalized.get("close_reason") or "").strip() or None
        )
        normalized["forensic_decision_id"] = (
            str(normalized.get("forensic_decision_id") or "").strip() or None
        )
        normalized["forensic_trade_context_id"] = (
            str(normalized.get("forensic_trade_context_id") or "").strip() or None
        )
        normalized["forensic_decision_type"] = (
            str(normalized.get("forensic_decision_type") or "").strip() or None
        )
        normalized["forensic_side"] = (
            str(normalized.get("forensic_side") or "").strip() or None
        )
        normalized["forensic_lifecycle_started_at"] = (
            str(normalized.get("forensic_lifecycle_started_at") or "").strip() or None
        )
        try:
            raw_position_idx = normalized.get("position_idx")
            normalized["position_idx"] = (
                int(raw_position_idx) if raw_position_idx is not None else None
            )
        except (TypeError, ValueError):
            normalized["position_idx"] = None
        if "reduce_only" in normalized:
            normalized["reduce_only"] = bool(normalized.get("reduce_only"))
        normalized["recorded_at"] = (
            str(normalized.get("recorded_at") or "").strip()
            or datetime.now(timezone.utc).isoformat()
        )
        return normalized

    def record_order(self, record: Dict[str, Any]) -> None:
        normalized = self._normalized_record(record)
        order_id = normalized.get("order_id")
        order_link_id = normalized.get("order_link_id")
        if not order_id and not order_link_id:
            return

        try:
            with self._file_lock(exclusive=True):
                try:
                    state = self._read_state_unlocked()
                except (json.JSONDecodeError, FileNotFoundError, OSError):
                    state = {
                        "version": 1,
                        "by_order_id": {},
                        "by_order_link_id": {},
                    }
                by_order_id = state.setdefault("by_order_id", {})
                by_order_link_id = state.setdefault("by_order_link_id", {})
                existing = None
                if order_id:
                    existing = by_order_id.get(order_id)
                if not existing and order_link_id:
                    existing = by_order_link_id.get(order_link_id)
                if isinstance(existing, dict):
                    merged = dict(existing)
                    merged.update({k: v for k, v in normalized.items() if v is not None})
                    normalized = merged

                if order_id:
                    by_order_id[order_id] = dict(normalized)
                if order_link_id:
                    by_order_link_id[order_link_id] = dict(normalized)

                self._prune_state(state)
                self._write_state_unlocked(state)
        except (OSError, IOError) as exc:
            logger.warning("Failed to record order ownership state: %s", exc)

    def get_order_ownership(
        self,
        *,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        order_id_text = str(order_id or "").strip()
        order_link_text = str(order_link_id or "").strip()
        if not order_id_text and not order_link_text:
            return None

        state = self._read_state()
        if order_id_text:
            record = state.get("by_order_id", {}).get(order_id_text)
            if isinstance(record, dict):
                return dict(record)
        if order_link_text:
            record = state.get("by_order_link_id", {}).get(order_link_text)
            if isinstance(record, dict):
                return dict(record)
        return None
