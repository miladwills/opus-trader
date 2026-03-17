import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Dict, List, Optional

import config.strategy_config as strategy_cfg
from services.lock_service import file_lock

logger = logging.getLogger(__name__)


class TradeForensicsService:
    """Append-only, bounded forensic event trail for trade lifecycle review."""

    def __init__(self, file_path: str = "storage/trade_forensics.jsonl") -> None:
        self.file_path = Path(file_path)
        self.lock_path = Path(str(self.file_path) + ".lock")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self.file_path.touch()
        self._recent_events: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def enabled() -> bool:
        return bool(getattr(strategy_cfg, "TRADE_FORENSICS_ENABLED", True))

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _trim_text(value: Any, max_len: int = 160) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    @staticmethod
    def _parse_iso(value: Any) -> Optional[datetime]:
        raw_text = str(value or "").strip()
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

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _top_level_fields() -> set:
        return {
            "event_id",
            "event_type",
            "timestamp",
            "recorded_at",
            "forensic_decision_id",
            "trade_context_id",
            "bot_id",
            "symbol",
            "mode",
            "profile",
            "side",
            "decision_type",
            "decision_fingerprint",
            "event_status",
            "linkage_method",
            "attribution_status",
            "decision_context",
            "advisor",
            "order",
            "exit",
            "outcome",
        }

    def create_lifecycle_ids(
        self,
        *,
        bot_id: Optional[str],
        symbol: Optional[str],
        decision_type: Optional[str],
        side: Optional[str],
        fingerprint: Optional[str] = None,
    ) -> Dict[str, str]:
        now_ms = int(time.time() * 1000)
        bot_token = str(bot_id or "na").replace("-", "")[:8] or "na"
        symbol_token = str(symbol or "na").strip().upper()[:8] or "na"
        decision_token = str(decision_type or "entry").strip().lower()[:8] or "entry"
        side_token = str(side or "na").strip().lower()[:4] or "na"
        salt = (fingerprint or sha1(f"{now_ms}:{bot_token}".encode("utf-8")).hexdigest())[:10]
        return {
            "forensic_decision_id": (
                f"fdc:{bot_token}:{symbol_token}:{decision_token}:{salt}"
            ),
            "trade_context_id": (
                f"ftc:{bot_token}:{side_token}:{now_ms}:{salt[:6]}"
            ),
        }

    def record_event(
        self,
        payload: Optional[Dict[str, Any]],
        *,
        dedupe_key: Optional[str] = None,
        dedupe_ttl: Optional[float] = None,
    ) -> bool:
        if not self.enabled() or not payload:
            return False
        record = self._normalize_payload(payload)
        if not record:
            return False

        if dedupe_key:
            if self._should_dedupe(
                dedupe_key,
                record,
                ttl=(
                    dedupe_ttl
                    if dedupe_ttl is not None
                    else float(
                        getattr(
                            strategy_cfg,
                            "TRADE_FORENSICS_DECISION_DEDUPE_TTL_SECONDS",
                            300,
                        )
                    )
                ),
            ):
                return False

        try:
            with file_lock(self.lock_path, exclusive=True):
                with open(self.file_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception as exc:
            logger.warning("Trade forensics write failed: %s", exc)
            return False

    def _should_dedupe(
        self,
        key: str,
        record: Dict[str, Any],
        *,
        ttl: float,
    ) -> bool:
        now_ts = time.monotonic()
        fingerprint_payload = dict(record)
        fingerprint_payload.pop("event_id", None)
        fingerprint_payload.pop("timestamp", None)
        fingerprint_payload.pop("recorded_at", None)
        fingerprint = json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        previous = self._recent_events.get(key)
        if (
            previous
            and previous.get("fingerprint") == fingerprint
            and (now_ts - float(previous.get("ts") or 0.0)) < max(float(ttl), 0.0)
        ):
            return True
        self._recent_events[key] = {"fingerprint": fingerprint, "ts": now_ts}
        return False

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            key: payload.get(key)
            for key in self._top_level_fields()
            if key in payload
        }
        event_type = self._trim_text(payload.get("event_type"), 48)
        if not event_type:
            return {}
        record["event_type"] = event_type
        record.setdefault("timestamp", self._utc_now_iso())
        record.setdefault("recorded_at", self._utc_now_iso())
        if not record.get("event_id"):
            event_hash = sha1(
                json.dumps(
                    {
                        "event_type": event_type,
                        "timestamp": record.get("timestamp"),
                        "trade_context_id": record.get("trade_context_id"),
                        "forensic_decision_id": record.get("forensic_decision_id"),
                        "bot_id": record.get("bot_id"),
                        "symbol": record.get("symbol"),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()[:12]
            record["event_id"] = f"tfe:{event_hash}"

        record["bot_id"] = self._trim_text(record.get("bot_id"), 64)
        symbol = str(record.get("symbol") or "").strip().upper()
        record["symbol"] = symbol or None
        record["mode"] = self._trim_text(record.get("mode"), 24)
        record["profile"] = self._trim_text(record.get("profile"), 24)
        record["side"] = self._trim_text(record.get("side"), 16)
        record["decision_type"] = self._trim_text(record.get("decision_type"), 32)
        record["decision_fingerprint"] = self._trim_text(
            record.get("decision_fingerprint"),
            64,
        )
        record["event_status"] = self._trim_text(record.get("event_status"), 24)
        record["linkage_method"] = self._trim_text(record.get("linkage_method"), 48)
        record["attribution_status"] = self._trim_text(
            record.get("attribution_status"),
            32,
        )
        record["forensic_decision_id"] = self._trim_text(
            record.get("forensic_decision_id"),
            96,
        )
        record["trade_context_id"] = self._trim_text(record.get("trade_context_id"), 96)
        record["decision_context"] = self._compact_mapping(
            record.get("decision_context"),
            max_depth=3,
        )
        record["advisor"] = self._compact_mapping(record.get("advisor"), max_depth=2)
        record["order"] = self._compact_mapping(record.get("order"), max_depth=2)
        record["exit"] = self._compact_mapping(record.get("exit"), max_depth=2)
        record["outcome"] = self._compact_mapping(record.get("outcome"), max_depth=2)
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _compact_mapping(
        self,
        value: Any,
        *,
        max_depth: int,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(value, dict) or max_depth <= 0:
            return None
        compact: Dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = self._trim_text(key, 48)
            if not normalized_key:
                continue
            if isinstance(item, dict):
                nested = self._compact_mapping(item, max_depth=max_depth - 1)
                if nested:
                    compact[normalized_key] = nested
                continue
            if isinstance(item, list):
                values = []
                for list_item in item[:4]:
                    if isinstance(list_item, dict):
                        nested = self._compact_mapping(
                            list_item,
                            max_depth=max_depth - 1,
                        )
                        if nested:
                            values.append(nested)
                    else:
                        trimmed = self._trim_text(list_item, 120)
                        if trimmed is not None:
                            values.append(trimmed)
                if values:
                    compact[normalized_key] = values
                continue
            if isinstance(item, float):
                compact[normalized_key] = round(item, 8)
                continue
            if isinstance(item, int) or isinstance(item, bool):
                compact[normalized_key] = item
                continue
            trimmed = self._trim_text(item, 160)
            if trimmed is not None:
                compact[normalized_key] = trimmed
        return compact or None

    def get_recent_events(
        self,
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if limit <= 0 or not self.file_path.exists():
            return []
        cutoff_ts = None
        if since_seconds is not None:
            try:
                cutoff_ts = time.time() - max(float(since_seconds), 0.0)
            except Exception:
                cutoff_ts = None

        normalized_bot_id = str(bot_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_event_type = str(event_type or "").strip()
        matched: List[Dict[str, Any]] = []
        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    raw = str(line or "").strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except Exception:
                        continue
                    if normalized_event_type and record.get("event_type") != normalized_event_type:
                        continue
                    if normalized_bot_id and str(record.get("bot_id") or "").strip() != normalized_bot_id:
                        continue
                    if normalized_symbol and str(record.get("symbol") or "").strip().upper() != normalized_symbol:
                        continue
                    if cutoff_ts is not None:
                        event_dt = self._parse_iso(record.get("timestamp"))
                        if event_dt is None or event_dt.timestamp() < cutoff_ts:
                            continue
                    matched.append(record)
        except Exception as exc:
            logger.warning("Trade forensics read failed: %s", exc)
            return []
        if len(matched) > limit:
            matched = matched[-limit:]
        return matched

    def get_recent_lifecycles(
        self,
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        events = self.get_recent_events(
            since_seconds=since_seconds,
            bot_id=bot_id,
            symbol=symbol,
            limit=max(limit * 20, 200),
        )
        grouped: Dict[str, Dict[str, Any]] = {}
        for event in events:
            lifecycle_id = (
                str(event.get("trade_context_id") or "").strip()
                or str(event.get("forensic_decision_id") or "").strip()
            )
            if not lifecycle_id:
                lifecycle_id = f"unlinked:{event.get('event_id')}"
            bucket = grouped.setdefault(
                lifecycle_id,
                {
                    "lifecycle_id": lifecycle_id,
                    "trade_context_id": event.get("trade_context_id"),
                    "forensic_decision_id": event.get("forensic_decision_id"),
                    "bot_id": event.get("bot_id"),
                    "symbol": event.get("symbol"),
                    "mode": event.get("mode"),
                    "side": event.get("side"),
                    "decision_type": event.get("decision_type"),
                    "first_event_at": event.get("timestamp"),
                    "last_event_at": event.get("timestamp"),
                    "event_types": [],
                    "event_count": 0,
                    "decision": None,
                    "latest_order": None,
                    "latest_exit": None,
                    "latest_outcome": None,
                    "events": [],
                },
            )
            bucket["event_count"] = int(bucket.get("event_count") or 0) + 1
            bucket["event_types"].append(event.get("event_type"))
            event_ts = str(event.get("timestamp") or "")
            if event_ts < str(bucket.get("first_event_at") or event_ts):
                bucket["first_event_at"] = event_ts
            if event_ts > str(bucket.get("last_event_at") or event_ts):
                bucket["last_event_at"] = event_ts
            if event.get("event_type") == "decision":
                bucket["decision"] = {
                    "event_status": event.get("event_status"),
                    "decision_context": event.get("decision_context"),
                    "advisor": event.get("advisor"),
                }
            elif event.get("event_type") == "order_submitted":
                bucket["latest_order"] = event.get("order")
            elif event.get("event_type") == "exit_decision":
                bucket["latest_exit"] = event.get("exit")
            elif event.get("event_type") == "realized_outcome":
                bucket["latest_outcome"] = event.get("outcome")
            bucket["events"].append(
                {
                    "event_type": event.get("event_type"),
                    "timestamp": event.get("timestamp"),
                    "event_status": event.get("event_status"),
                    "order": event.get("order"),
                    "exit": event.get("exit"),
                    "outcome": event.get("outcome"),
                }
            )
        lifecycles = list(grouped.values())
        for lifecycle in lifecycles:
            lifecycle["event_types"] = list(dict.fromkeys(lifecycle["event_types"]))
            lifecycle["events"] = sorted(
                lifecycle["events"],
                key=lambda item: str(item.get("timestamp") or ""),
            )[-8:]
        lifecycles.sort(key=lambda item: str(item.get("last_event_at") or ""), reverse=True)
        return lifecycles[:limit]

    def get_summary(
        self,
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        events = self.get_recent_events(
            since_seconds=since_seconds,
            bot_id=bot_id,
            symbol=symbol,
            limit=max(
                self._safe_int(
                    getattr(strategy_cfg, "TRADE_FORENSICS_RECENT_EVENT_LIMIT", 500),
                    500,
                ),
                100,
            ),
        )
        summary = {
            "total_events": len(events),
            "event_counts": {},
            "linked_event_count": 0,
            "unresolved_event_count": 0,
            "recent_window_seconds": since_seconds,
        }
        for event in events:
            event_type = str(event.get("event_type") or "").strip()
            if event_type:
                summary["event_counts"][event_type] = (
                    int(summary["event_counts"].get(event_type, 0) or 0) + 1
                )
            if event.get("trade_context_id") or event.get("forensic_decision_id"):
                summary["linked_event_count"] += 1
            else:
                summary["unresolved_event_count"] += 1
        return summary
