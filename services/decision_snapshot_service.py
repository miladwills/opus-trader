import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config.strategy_config as strategy_cfg
from services.lock_service import file_lock
from services.trade_forensics_service import TradeForensicsService

logger = logging.getLogger(__name__)


class DecisionSnapshotService:
    """Derived canonical decision snapshots built from forensic lifecycle events."""

    INITIALIZER_EVENTS = {"decision", "skip_blocked"}

    def __init__(
        self,
        *,
        trade_forensics_service: Optional[TradeForensicsService] = None,
        file_path: str = "storage/decision_snapshots.json",
        now_fn: Optional[Any] = None,
        lookback_seconds: Optional[int] = None,
    ) -> None:
        self.trade_forensics_service = trade_forensics_service or TradeForensicsService()
        self.file_path = Path(file_path)
        self.lock_path = Path(str(self.file_path) + ".lock")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_snapshot(self._default_snapshot())
        self.now_fn = now_fn or time.time
        self.lookback_seconds_override = (
            max(self._safe_int(lookback_seconds, 0), 0) if lookback_seconds is not None else None
        )

    @staticmethod
    def enabled() -> bool:
        return bool(getattr(strategy_cfg, "DECISION_SNAPSHOT_ENABLED", True))

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
    def _default_snapshot() -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "metadata": {},
            "snapshots": [],
            "summary": {},
            "error": None,
        }

    def _read_snapshot(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            return self._default_snapshot()
        try:
            with file_lock(self.lock_path, exclusive=False):
                with open(self.file_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return self._default_snapshot()
        if not isinstance(payload, dict):
            return self._default_snapshot()
        snapshot = self._default_snapshot()
        snapshot.update(payload)
        snapshot["metadata"] = dict(snapshot.get("metadata") or {})
        snapshot["snapshots"] = list(snapshot.get("snapshots") or [])
        snapshot["summary"] = dict(snapshot.get("summary") or {})
        return snapshot

    def _write_snapshot(self, snapshot: Dict[str, Any]) -> None:
        payload = dict(self._default_snapshot())
        payload.update(snapshot or {})
        try:
            with file_lock(self.lock_path, exclusive=True):
                dir_path = self.file_path.parent
                fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    os.replace(temp_path, self.file_path)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
        except Exception as exc:
            logger.warning("Decision snapshot write failed: %s", exc)

    def _snapshot_ttl_seconds(self) -> int:
        return max(
            self._safe_int(getattr(strategy_cfg, "DECISION_SNAPSHOT_TTL_SECONDS", 30), 30),
            5,
        )

    def _lookback_seconds(self) -> int:
        if self.lookback_seconds_override is not None:
            return max(int(self.lookback_seconds_override), 3600)
        return max(
            self._safe_int(
                getattr(strategy_cfg, "DECISION_SNAPSHOT_LOOKBACK_SECONDS", 604800),
                604800,
            ),
            3600,
        )

    def _event_limit(self) -> int:
        return max(
            self._safe_int(
                getattr(strategy_cfg, "DECISION_SNAPSHOT_EVENT_LIMIT", 3000),
                3000,
            ),
            200,
        )

    def _recent_limit(self) -> int:
        return max(
            self._safe_int(
                getattr(strategy_cfg, "DECISION_SNAPSHOT_RECENT_LIMIT", 200),
                200,
            ),
            20,
        )

    def _load_events(self) -> List[Dict[str, Any]]:
        events = self.trade_forensics_service.get_recent_events(
            since_seconds=float(self._lookback_seconds()),
            limit=self._event_limit(),
        )
        normalized = []
        for event in events:
            record = dict(event or {})
            event_dt = self._parse_iso(record.get("timestamp"))
            if event_dt is None:
                continue
            record["_event_dt"] = event_dt
            normalized.append(record)
        normalized.sort(key=lambda item: item["_event_dt"])
        return normalized

    @staticmethod
    def _status_rank(snapshot: Dict[str, Any]) -> Tuple[int, str]:
        lifecycle = dict(snapshot.get("lifecycle") or {})
        if lifecycle.get("closed"):
            return (5, str(snapshot.get("last_updated_at") or ""))
        if lifecycle.get("opened"):
            return (4, str(snapshot.get("last_updated_at") or ""))
        if lifecycle.get("submitted"):
            return (3, str(snapshot.get("last_updated_at") or ""))
        if lifecycle.get("blocked"):
            return (2, str(snapshot.get("last_updated_at") or ""))
        return (1, str(snapshot.get("last_updated_at") or ""))

    @classmethod
    def _new_snapshot(cls, event: Dict[str, Any], *, orphaned: bool = False) -> Dict[str, Any]:
        return {
            "snapshot_id": (
                str(event.get("forensic_decision_id") or "").strip()
                or str(event.get("trade_context_id") or "").strip()
                or str(event.get("event_id") or "").strip()
            ),
            "forensic_decision_id": event.get("forensic_decision_id"),
            "trade_context_id": event.get("trade_context_id"),
            "bot_id": event.get("bot_id"),
            "symbol": event.get("symbol"),
            "side": event.get("side"),
            "mode": event.get("mode"),
            "profile": event.get("profile"),
            "decision_type": event.get("decision_type"),
            "decision_at": event.get("timestamp"),
            "last_updated_at": event.get("timestamp"),
            "initialized_from": event.get("event_type"),
            "orphaned": bool(orphaned),
            "identity": {
                "forensic_decision_id": event.get("forensic_decision_id"),
                "trade_context_id": event.get("trade_context_id"),
                "bot_id": event.get("bot_id"),
                "symbol": event.get("symbol"),
                "side": event.get("side"),
                "mode": event.get("mode"),
                "profile": event.get("profile"),
                "decision_type": event.get("decision_type"),
            },
            "decision": {
                "reason_summary": [],
                "setup_quality": {},
                "entry_signal": {},
                "gate": {},
                "blockers": [],
            },
            "market_runtime": {},
            "watchdogs": {},
            "advisor": {},
            "lifecycle": {
                "blocked": False,
                "skip_reason": None,
                "submitted": False,
                "submitted_at": None,
                "opened": False,
                "opened_at": None,
                "exit_decision_seen": False,
                "exit_reason": None,
                "closed": False,
                "closed_at": None,
                "realized_pnl": None,
                "outcome_status": "awaiting",
                "linkage_method": event.get("linkage_method"),
                "attribution_status": event.get("attribution_status"),
            },
        }

    @classmethod
    def _compact_reason_list(cls, values: Any, *, limit: int = 3) -> List[str]:
        items = []
        for value in list(values or [])[:limit]:
            trimmed = cls._trim_text(value, 120)
            if trimmed:
                items.append(trimmed)
        return items

    @classmethod
    def _compact_blockers(cls, values: Any) -> List[Dict[str, Any]]:
        blockers = []
        for item in list(values or [])[:4]:
            if not isinstance(item, dict):
                continue
            payload = {
                "code": cls._trim_text(item.get("code"), 48),
                "reason": cls._trim_text(item.get("reason"), 120),
                "phase": cls._trim_text(item.get("phase"), 32),
                "side": cls._trim_text(item.get("side"), 24),
            }
            payload = {key: value for key, value in payload.items() if value not in (None, "")}
            if payload:
                blockers.append(payload)
        return blockers

    @classmethod
    def _apply_decision_context(cls, snapshot: Dict[str, Any], event: Dict[str, Any]) -> None:
        decision_context = dict(event.get("decision_context") or {})
        local_decision = dict(decision_context.get("local_decision") or {})
        setup_quality = dict(local_decision.get("setup_quality") or {})
        entry_signal = dict(local_decision.get("entry_signal") or {})
        gate = dict(local_decision.get("gate") or {})
        snapshot["decision"] = {
            "candidate_ready": local_decision.get("candidate_ready"),
            "reason_summary": cls._compact_reason_list(
                local_decision.get("reason_to_enter"),
                limit=3,
            ),
            "setup_quality": {
                "score": cls._safe_float(setup_quality.get("score"), None),
                "band": setup_quality.get("band"),
                "entry_allowed": setup_quality.get("entry_allowed"),
                "breakout_ready": setup_quality.get("breakout_ready"),
                "summary": cls._trim_text(setup_quality.get("summary"), 120),
            },
            "entry_signal": {
                "code": entry_signal.get("code"),
                "phase": entry_signal.get("phase"),
                "preferred": entry_signal.get("preferred"),
                "late": entry_signal.get("late"),
                "executable": entry_signal.get("executable"),
            },
            "gate": {
                "blocked": gate.get("blocked"),
                "reason": cls._trim_text(gate.get("reason"), 140),
                "blocked_by": cls._compact_reason_list(gate.get("blocked_by"), limit=4),
            },
            "blockers": cls._compact_blockers(local_decision.get("blockers")),
            "entry_story": {
                key: value
                for key, value in dict(decision_context.get("entry_story") or {}).items()
                if value not in (None, "", [], {})
            },
        }
        market = dict(decision_context.get("market") or {})
        position = dict(decision_context.get("position") or {})
        risk = dict(decision_context.get("risk") or {})
        snapshot["market_runtime"] = {
            "last_price": cls._safe_float(market.get("last_price"), None),
            "regime_effective": market.get("regime_effective"),
            "regime_confidence": market.get("regime_confidence"),
            "atr_5m_pct": cls._safe_float(market.get("atr_5m_pct"), None),
            "atr_15m_pct": cls._safe_float(market.get("atr_15m_pct"), None),
            "bbw_pct": cls._safe_float(market.get("bbw_pct"), None),
            "rsi": cls._safe_float(market.get("rsi"), None),
            "adx": cls._safe_float(market.get("adx"), None),
            "price_velocity": cls._safe_float(market.get("price_velocity"), None),
            "position": {
                "side": position.get("side"),
                "size": cls._safe_float(position.get("size"), None),
                "has_position": position.get("has_position"),
            },
            "risk": {
                "reduce_only_mode": risk.get("reduce_only_mode"),
                "capital_starved": risk.get("capital_starved"),
                "volatility_block_opening_orders": risk.get(
                    "volatility_block_opening_orders"
                ),
                "entry_gate_enabled": risk.get("entry_gate_enabled"),
                "entry_gate_bot_enabled": risk.get("entry_gate_bot_enabled"),
                "entry_gate_global_master_applicable": risk.get(
                    "entry_gate_global_master_applicable"
                ),
                "entry_gate_global_master_enabled": risk.get(
                    "entry_gate_global_master_enabled"
                ),
                "entry_gate_contract_active": risk.get("entry_gate_contract_active"),
            },
        }
        snapshot["watchdogs"] = dict(decision_context.get("watchdogs") or {})
        advisor = dict(event.get("advisor") or {})
        if not advisor:
            advisor = dict(decision_context.get("advisor") or {})
        snapshot["advisor"] = {
            "status": advisor.get("status"),
            "verdict": advisor.get("verdict"),
            "confidence": cls._safe_float(advisor.get("confidence"), None),
            "model": advisor.get("model"),
            "escalated": advisor.get("escalated"),
            "summary": cls._trim_text(advisor.get("summary"), 160),
            "risk_note": cls._trim_text(advisor.get("risk_note"), 160),
        }

    @classmethod
    def _update_identity_from_event(cls, snapshot: Dict[str, Any], event: Dict[str, Any]) -> None:
        snapshot["forensic_decision_id"] = snapshot.get("forensic_decision_id") or event.get(
            "forensic_decision_id"
        )
        snapshot["trade_context_id"] = snapshot.get("trade_context_id") or event.get(
            "trade_context_id"
        )
        snapshot["bot_id"] = snapshot.get("bot_id") or event.get("bot_id")
        snapshot["symbol"] = snapshot.get("symbol") or event.get("symbol")
        snapshot["side"] = snapshot.get("side") or event.get("side")
        snapshot["mode"] = snapshot.get("mode") or event.get("mode")
        snapshot["profile"] = snapshot.get("profile") or event.get("profile")
        snapshot["decision_type"] = snapshot.get("decision_type") or event.get(
            "decision_type"
        )
        snapshot["last_updated_at"] = event.get("timestamp") or snapshot.get("last_updated_at")
        snapshot["identity"] = {
            "forensic_decision_id": snapshot.get("forensic_decision_id"),
            "trade_context_id": snapshot.get("trade_context_id"),
            "bot_id": snapshot.get("bot_id"),
            "symbol": snapshot.get("symbol"),
            "side": snapshot.get("side"),
            "mode": snapshot.get("mode"),
            "profile": snapshot.get("profile"),
            "decision_type": snapshot.get("decision_type"),
        }

    @classmethod
    def _apply_event(cls, snapshot: Dict[str, Any], event: Dict[str, Any]) -> None:
        cls._update_identity_from_event(snapshot, event)
        lifecycle = dict(snapshot.get("lifecycle") or {})
        lifecycle["linkage_method"] = lifecycle.get("linkage_method") or event.get("linkage_method")
        lifecycle["attribution_status"] = (
            event.get("attribution_status") or lifecycle.get("attribution_status")
        )

        event_type = str(event.get("event_type") or "").strip()
        if event_type in cls.INITIALIZER_EVENTS or (
            event_type == "decision" and not snapshot.get("decision", {}).get("reason_summary")
        ):
            cls._apply_decision_context(snapshot, event)
        if event_type == "skip_blocked":
            lifecycle["blocked"] = True
            lifecycle["outcome_status"] = "blocked"
            lifecycle["skip_reason"] = cls._trim_text(
                ((event.get("exit") or {}).get("skip_reason")),
                160,
            )
        elif event_type == "order_submitted":
            lifecycle["submitted"] = True
            lifecycle["submitted_at"] = event.get("timestamp")
            lifecycle["order"] = dict(event.get("order") or {})
            if lifecycle.get("outcome_status") in (None, "", "awaiting", "blocked"):
                lifecycle["outcome_status"] = "submitted"
        elif event_type == "position_opened":
            lifecycle["opened"] = True
            lifecycle["opened_at"] = event.get("timestamp")
            lifecycle["position_opened_order"] = dict(event.get("order") or {})
            lifecycle["outcome_status"] = "opened"
        elif event_type == "exit_decision":
            lifecycle["exit_decision_seen"] = True
            lifecycle["exit_reason"] = cls._trim_text(
                ((event.get("exit") or {}).get("close_reason")),
                120,
            ) or cls._trim_text(((event.get("exit") or {}).get("action")), 120)
        elif event_type == "position_closed":
            lifecycle["closed"] = True
            lifecycle["closed_at"] = event.get("timestamp")
            if lifecycle.get("outcome_status") != "resolved":
                lifecycle["outcome_status"] = "closed"
            if not lifecycle.get("exit_reason"):
                lifecycle["exit_reason"] = cls._trim_text(
                    ((event.get("exit") or {}).get("close_reason")),
                    120,
                )
        elif event_type == "realized_outcome":
            outcome = dict(event.get("outcome") or {})
            lifecycle["closed"] = True
            lifecycle["closed_at"] = event.get("timestamp")
            lifecycle["realized_pnl"] = cls._safe_float(outcome.get("realized_pnl"), None)
            lifecycle["balance_after"] = cls._safe_float(outcome.get("balance_after"), None)
            lifecycle["win"] = outcome.get("win")
            lifecycle["order_id"] = outcome.get("order_id")
            lifecycle["exec_id"] = outcome.get("exec_id")
            lifecycle["order_link_id"] = outcome.get("order_link_id")
            lifecycle["position_idx"] = outcome.get("position_idx")
            lifecycle["outcome_attribution_source"] = outcome.get("attribution_source")
            lifecycle["total_fee"] = cls._safe_float(outcome.get("total_fee"), None)
            lifecycle["funding_fee"] = cls._safe_float(outcome.get("funding_fee"), None)
            lifecycle["outcome_status"] = "resolved"
            if not lifecycle.get("exit_reason"):
                lifecycle["exit_reason"] = cls._trim_text(
                    ((event.get("exit") or {}).get("close_reason")),
                    120,
                )

        snapshot["lifecycle"] = lifecycle
        snapshot["status"] = {
            "blocked": bool(lifecycle.get("blocked")),
            "submitted": bool(lifecycle.get("submitted")),
            "opened": bool(lifecycle.get("opened")),
            "closed": bool(lifecycle.get("closed")),
            "outcome_status": lifecycle.get("outcome_status") or "awaiting",
            "review_state": cls._review_state(snapshot),
        }

    @staticmethod
    def _review_state(snapshot: Dict[str, Any]) -> str:
        lifecycle = dict(snapshot.get("lifecycle") or {})
        if lifecycle.get("outcome_status") == "resolved":
            return "complete"
        if lifecycle.get("blocked"):
            return "blocked_complete"
        if lifecycle.get("closed"):
            return "awaiting_realized_outcome"
        if lifecycle.get("opened") or lifecycle.get("submitted"):
            return "awaiting_outcome"
        if snapshot.get("orphaned"):
            return "partial_orphaned"
        return "decision_only"

    def _build_snapshots(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        snapshots: Dict[str, Dict[str, Any]] = {}
        context_index: Dict[str, str] = {}

        for event in events:
            forensic_decision_id = str(event.get("forensic_decision_id") or "").strip()
            trade_context_id = str(event.get("trade_context_id") or "").strip()

            snapshot_id = forensic_decision_id or context_index.get(trade_context_id)
            if not snapshot_id and trade_context_id:
                snapshot_id = context_index.get(trade_context_id)

            if not snapshot_id and event.get("event_type") in self.INITIALIZER_EVENTS:
                snapshot_id = forensic_decision_id or trade_context_id or str(event.get("event_id"))
            elif not snapshot_id:
                snapshot_id = forensic_decision_id or trade_context_id or str(event.get("event_id"))

            snapshot = snapshots.get(snapshot_id)
            if snapshot is None:
                snapshot = self._new_snapshot(
                    event,
                    orphaned=event.get("event_type") not in self.INITIALIZER_EVENTS,
                )
                snapshots[snapshot_id] = snapshot

            if forensic_decision_id:
                context_index[forensic_decision_id] = snapshot_id
            if trade_context_id:
                context_index[trade_context_id] = snapshot_id

            self._apply_event(snapshot, event)

        results = list(snapshots.values())
        results.sort(key=lambda item: str(item.get("last_updated_at") or ""), reverse=True)
        return results

    @classmethod
    def _filtered_snapshots(
        cls,
        snapshots: List[Dict[str, Any]],
        *,
        since_seconds: Optional[float],
        now_fn,
        bot_id: Optional[str],
        symbol: Optional[str],
        status_filter: Optional[str],
    ) -> List[Dict[str, Any]]:
        normalized_bot_id = str(bot_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_status = str(status_filter or "").strip().lower()
        cutoff_ts = None
        if since_seconds is not None:
            try:
                cutoff_ts = now_fn() - max(float(since_seconds), 0.0)
            except Exception:
                cutoff_ts = None

        filtered = []
        for snapshot in snapshots:
            if normalized_bot_id and str(snapshot.get("bot_id") or "").strip() != normalized_bot_id:
                continue
            if normalized_symbol and str(snapshot.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            decision_dt = cls._parse_iso(snapshot.get("decision_at"))
            if cutoff_ts is not None and decision_dt is not None and decision_dt.timestamp() < cutoff_ts:
                continue
            review_state = str(((snapshot.get("status") or {}).get("review_state")) or "").lower()
            if normalized_status and normalized_status not in {
                "all",
                review_state,
                str(((snapshot.get("lifecycle") or {}).get("outcome_status")) or "").lower(),
            }:
                if normalized_status == "blocked" and not ((snapshot.get("status") or {}).get("blocked")):
                    continue
                if normalized_status == "executed" and not (
                    (snapshot.get("status") or {}).get("submitted")
                    or (snapshot.get("status") or {}).get("opened")
                ):
                    continue
                if normalized_status == "resolved" and (
                    str(((snapshot.get("lifecycle") or {}).get("outcome_status")) or "").lower()
                    != "resolved"
                ):
                    continue
                if normalized_status == "unresolved" and (
                    str(((snapshot.get("lifecycle") or {}).get("outcome_status")) or "").lower()
                    == "resolved"
                ):
                    continue
            filtered.append(snapshot)
        return filtered

    @classmethod
    def _build_summary(cls, snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary = {
            "total_snapshots": len(snapshots),
            "blocked_count": 0,
            "executed_count": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "orphaned_count": 0,
            "by_symbol": [],
            "by_bot": [],
        }
        by_symbol: Dict[str, int] = {}
        by_bot: Dict[str, int] = {}
        for snapshot in snapshots:
            status = dict(snapshot.get("status") or {})
            lifecycle = dict(snapshot.get("lifecycle") or {})
            if status.get("blocked"):
                summary["blocked_count"] += 1
            if status.get("submitted") or status.get("opened"):
                summary["executed_count"] += 1
            if lifecycle.get("outcome_status") == "resolved":
                summary["resolved_count"] += 1
            else:
                summary["unresolved_count"] += 1
            if snapshot.get("orphaned"):
                summary["orphaned_count"] += 1
            symbol = str(snapshot.get("symbol") or "").strip().upper()
            bot_id = str(snapshot.get("bot_id") or "").strip()
            if symbol:
                by_symbol[symbol] = int(by_symbol.get(symbol, 0) or 0) + 1
            if bot_id:
                by_bot[bot_id] = int(by_bot.get(bot_id, 0) or 0) + 1

        summary["by_symbol"] = [
            {"symbol": key, "count": value}
            for key, value in sorted(by_symbol.items(), key=lambda item: (-item[1], item[0]))[:8]
        ]
        summary["by_bot"] = [
            {"bot_id": key, "count": value}
            for key, value in sorted(by_bot.items(), key=lambda item: (-item[1], item[0]))[:8]
        ]
        return summary

    def refresh_snapshot(self, force: bool = False) -> Dict[str, Any]:
        current = self._read_snapshot()
        if not self.enabled():
            return current
        if not force:
            updated_at = self._parse_iso(current.get("updated_at"))
            if updated_at is not None and (self.now_fn() - updated_at.timestamp()) < self._snapshot_ttl_seconds():
                return current

        metadata = {
            "lookback_seconds": self._lookback_seconds(),
            "event_limit": self._event_limit(),
            "recent_limit": self._recent_limit(),
            "canonical_unit": "forensic_decision_id",
            "trade_context_join": "trade_context_id",
            "initializer_events": ["decision", "skip_blocked"],
            "correlational_only": True,
        }
        try:
            snapshots = self._build_snapshots(self._load_events())
            snapshot = {
                "version": 1,
                "updated_at": self._utc_now_iso(),
                "metadata": metadata,
                "snapshots": snapshots,
                "summary": self._build_summary(snapshots),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Decision snapshot refresh failed: %s", exc)
            snapshot = dict(current)
            snapshot["metadata"] = dict(current.get("metadata") or metadata)
            snapshot["error"] = str(exc)
        self._write_snapshot(snapshot)
        return snapshot

    def get_recent_snapshots(
        self,
        *,
        limit: int = 50,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status_filter: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        snapshots = self._filtered_snapshots(
            list(snapshot.get("snapshots") or []),
            since_seconds=since_seconds,
            now_fn=self.now_fn,
            bot_id=bot_id,
            symbol=symbol,
            status_filter=status_filter,
        )
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "snapshots": snapshots[: max(int(limit or 0), 0)],
        }

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot_store = self.refresh_snapshot(force=force_refresh)
        target = str(snapshot_id or "").strip()
        for snapshot in list(snapshot_store.get("snapshots") or []):
            if target in {
                str(snapshot.get("snapshot_id") or "").strip(),
                str(snapshot.get("forensic_decision_id") or "").strip(),
                str(snapshot.get("trade_context_id") or "").strip(),
            }:
                return {
                    "updated_at": snapshot_store.get("updated_at"),
                    "metadata": dict(snapshot_store.get("metadata") or {}),
                    "error": snapshot_store.get("error"),
                    "snapshot": snapshot,
                }
        return {
            "updated_at": snapshot_store.get("updated_at"),
            "metadata": dict(snapshot_store.get("metadata") or {}),
            "error": snapshot_store.get("error"),
            "snapshot": None,
        }

    def get_summary(
        self,
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status_filter: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot_store = self.refresh_snapshot(force=force_refresh)
        snapshots = self._filtered_snapshots(
            list(snapshot_store.get("snapshots") or []),
            since_seconds=since_seconds,
            now_fn=self.now_fn,
            bot_id=bot_id,
            symbol=symbol,
            status_filter=status_filter,
        )
        return {
            "updated_at": snapshot_store.get("updated_at"),
            "metadata": dict(snapshot_store.get("metadata") or {}),
            "error": snapshot_store.get("error"),
            "summary": self._build_summary(snapshots),
        }
