import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import config.strategy_config as strategy_cfg
from services.audit_diagnostics_service import AuditDiagnosticsService
from services.lock_service import file_lock
from services.performance_baseline_service import PerformanceBaselineService

logger = logging.getLogger(__name__)


class AIAdvisorAnalyticsService:
    """Compact read-only analytics for advisor calibration and review."""

    ADVISOR_EVENT_TYPE = "ai_advisor_decision"
    EXECUTION_EVENT_TYPES = ("actual_entry", "opening_orders_placed")

    def __init__(
        self,
        *,
        audit_diagnostics_service: Optional[AuditDiagnosticsService] = None,
        pnl_service: Optional[Any] = None,
        file_path: str = "storage/ai_advisor_review.json",
        now_fn: Optional[Any] = None,
        performance_baseline_service: Optional[PerformanceBaselineService] = None,
    ) -> None:
        self.audit_diagnostics_service = (
            audit_diagnostics_service or AuditDiagnosticsService()
        )
        self.pnl_service = pnl_service
        self.file_path = Path(file_path)
        self.lock_path = Path(str(self.file_path) + ".lock")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_snapshot(self._default_snapshot())
        self.now_fn = now_fn or time.time
        self.performance_baseline_service = performance_baseline_service

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None:
            return default
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

    @classmethod
    def _get_record_dt(cls, record: Dict[str, Any]) -> Optional[datetime]:
        return cls._parse_iso(record.get("timestamp")) or cls._parse_iso(
            record.get("recorded_at")
        )

    @staticmethod
    def _default_snapshot() -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "metadata": {},
            "reviews": [],
            "recent": [],
            "summary": {},
            "calibration": {},
            "error": None,
        }

    @classmethod
    def _decision_sort_key(cls, review: Dict[str, Any]) -> str:
        return str(review.get("decision_at") or "")

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
        snapshot["reviews"] = list(snapshot.get("reviews") or [])
        snapshot["recent"] = list(snapshot.get("recent") or [])
        snapshot["metadata"] = dict(snapshot.get("metadata") or {})
        snapshot["summary"] = dict(snapshot.get("summary") or {})
        snapshot["calibration"] = dict(snapshot.get("calibration") or {})
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
        except (OSError, IOError) as exc:
            logger.warning("Failed to write AI advisor analytics snapshot: %s", exc)

    def _snapshot_ttl_seconds(self) -> int:
        return max(
            self._safe_int(
                getattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_SNAPSHOT_TTL_SECONDS", 30),
                30,
            ),
            5,
        )

    def _decision_limit(self) -> int:
        return max(
            self._safe_int(
                getattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_DECISION_LIMIT", 1200),
                1200,
            ),
            100,
        )

    def _recent_limit(self) -> int:
        return max(
            self._safe_int(
                getattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_RECENT_LIMIT", 200),
                200,
            ),
            20,
        )

    def _lookback_seconds(self) -> int:
        return max(
            self._safe_int(
                getattr(strategy_cfg, "AI_ADVISOR_ANALYTICS_LOOKBACK_SECONDS", 604800),
                604800,
            ),
            3600,
        )

    def _execution_window_seconds(self) -> int:
        return max(
            self._safe_int(
                getattr(
                    strategy_cfg,
                    "AI_ADVISOR_ANALYTICS_EXECUTION_WINDOW_SECONDS",
                    1800,
                ),
                1800,
            ),
            60,
        )

    def _outcome_window_seconds(self) -> int:
        return max(
            self._safe_int(
                getattr(
                    strategy_cfg,
                    "AI_ADVISOR_ANALYTICS_OUTCOME_WINDOW_SECONDS",
                    86400,
                ),
                86400,
            ),
            300,
        )

    def _load_decisions(self) -> List[Dict[str, Any]]:
        events = self.audit_diagnostics_service.get_recent_events(
            event_type=self.ADVISOR_EVENT_TYPE,
            since_seconds=float(self._lookback_seconds()),
            limit=self._decision_limit(),
        )
        decisions: List[Dict[str, Any]] = []
        for event in events:
            record = dict(event or {})
            event_dt = self._get_record_dt(record)
            if event_dt is None:
                continue
            verdict = str(record.get("verdict") or "").strip().upper() or None
            compact_context = dict(record.get("compact_context") or {})
            decision_id = str(record.get("decision_id") or "").strip()
            if not decision_id:
                fingerprint = str(record.get("fingerprint") or "").strip()
                bot_token = str(record.get("bot_id") or "na").replace("-", "")[:8] or "na"
                decision_id = (
                    f"adv:{bot_token}:{int(event_dt.timestamp() * 1000)}:{fingerprint[:10]}"
                )
            decisions.append(
                {
                    "decision_id": decision_id,
                    "decision_at": event_dt.isoformat(),
                    "_decision_dt": event_dt,
                    "bot_id": str(record.get("bot_id") or "").strip() or None,
                    "symbol": str(record.get("symbol") or "").strip().upper() or None,
                    "mode": str(record.get("mode") or "").strip().lower() or None,
                    "decision_type": str(record.get("decision_type") or "").strip().lower() or None,
                    "status": str(record.get("status") or "").strip().lower() or None,
                    "verdict": verdict,
                    "confidence": self._safe_float(record.get("confidence"), None),
                    "reasons": list(record.get("reasons") or [])[:3],
                    "risk_note": record.get("risk_note"),
                    "summary": record.get("summary"),
                    "model": str(record.get("model") or "").strip() or None,
                    "escalated": bool(record.get("escalated", False)),
                    "latency_ms": self._safe_int(record.get("latency_ms"), 0) or None,
                    "usage": dict(record.get("usage") or {}),
                    "error": record.get("error"),
                    "error_code": str(record.get("error_code") or "").strip() or None,
                    "raw_response_excerpt": record.get("raw_response_excerpt"),
                    "fingerprint": str(record.get("fingerprint") or "").strip() or None,
                    "compact_context": compact_context,
                    "local_alignment": self._classify_alignment(verdict, compact_context),
                }
            )
        decisions.sort(key=lambda item: item["_decision_dt"])
        return decisions

    def _load_execution_events(self) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for event_type in self.EXECUTION_EVENT_TYPES:
            events = self.audit_diagnostics_service.get_recent_events(
                event_type=event_type,
                since_seconds=float(self._lookback_seconds()),
                limit=max(self._decision_limit() * 2, 400),
            )
            for event in events:
                record = dict(event or {})
                event_dt = self._get_record_dt(record)
                bot_id = str(record.get("bot_id") or "").strip()
                symbol = str(record.get("symbol") or "").strip().upper()
                if event_dt is None or not bot_id or not symbol:
                    continue
                key = (bot_id, symbol)
                grouped.setdefault(key, []).append(
                    {
                        "event_type": event_type,
                        "event_at": event_dt.isoformat(),
                        "_event_dt": event_dt,
                    }
                )
        for events in grouped.values():
            events.sort(key=lambda item: item["_event_dt"])
        return grouped

    def _load_trade_logs(self) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
        pnl_service = getattr(self, "pnl_service", None)
        if pnl_service is None:
            return {}
        try:
            logs = list(pnl_service.get_log() or [])
        except Exception as exc:
            logger.warning("Failed to load trade logs for AI advisor analytics: %s", exc)
            return {}

        cutoff_ts = self.now_fn() - float(self._lookback_seconds() + self._outcome_window_seconds())
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for log in logs:
            record = dict(log or {})
            trade_dt = self._parse_iso(record.get("time"))
            bot_id = str(record.get("bot_id") or "").strip()
            symbol = str(record.get("symbol") or "").strip().upper()
            if trade_dt is None or not bot_id or not symbol:
                continue
            if trade_dt.timestamp() < cutoff_ts:
                continue
            key = (bot_id, symbol)
            grouped.setdefault(key, []).append(
                {
                    "trade_time": trade_dt.isoformat(),
                    "_trade_dt": trade_dt,
                    "symbol": symbol,
                    "bot_id": bot_id,
                    "realized_pnl": round(
                        self._safe_float(record.get("realized_pnl"), 0.0) or 0.0,
                        8,
                    ),
                    "side": record.get("side"),
                    "order_link_id": record.get("order_link_id"),
                    "position_idx": record.get("position_idx"),
                    "attribution_source": record.get("attribution_source"),
                    "order_id": record.get("order_id"),
                }
            )
        for trades in grouped.values():
            trades.sort(key=lambda item: item["_trade_dt"])
        return grouped

    @staticmethod
    def _classify_alignment(
        verdict: Optional[str],
        compact_context: Optional[Dict[str, Any]],
    ) -> str:
        normalized_verdict = str(verdict or "").strip().upper()
        context = dict(compact_context or {})
        gate_blocked = bool(context.get("gate_blocked"))
        entry_allowed = context.get("entry_allowed")
        setup_quality_score = AIAdvisorAnalyticsService._safe_float(
            context.get("setup_quality_score"),
            None,
        )
        if gate_blocked or entry_allowed is False:
            return "aligned" if normalized_verdict in {"CAUTION", "REJECT"} else "disagreed"
        if setup_quality_score is not None and setup_quality_score >= 70.0:
            return "aligned" if normalized_verdict == "APPROVE" else (
                "disagreed" if normalized_verdict == "REJECT" else "mixed"
            )
        if setup_quality_score is not None and setup_quality_score <= 45.0:
            return "aligned" if normalized_verdict == "REJECT" else (
                "disagreed" if normalized_verdict == "APPROVE" else "mixed"
            )
        if normalized_verdict == "CAUTION":
            return "aligned"
        return "mixed"

    def _match_execution_event(
        self,
        review: Dict[str, Any],
        *,
        events: List[Dict[str, Any]],
        next_decision_dt: Optional[datetime],
    ) -> Tuple[str, Optional[str], Optional[str]]:
        decision_dt = review["_decision_dt"]
        if decision_dt is None:
            return ("unresolved", None, None)
        window_end = decision_dt.timestamp() + float(self._execution_window_seconds())
        if next_decision_dt is not None:
            window_end = min(window_end, next_decision_dt.timestamp())
        for event in events:
            event_dt = event.get("_event_dt")
            if event_dt is None:
                continue
            if event_dt < decision_dt:
                continue
            if event_dt.timestamp() > window_end:
                break
            return ("entry_action_seen", event.get("event_at"), event.get("event_type"))
        return ("no_entry_action_seen", None, None)

    def _attach_linked_outcomes(
        self,
        reviews: List[Dict[str, Any]],
        execution_events: Dict[Tuple[str, str], List[Dict[str, Any]]],
        trades_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        grouped_reviews: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for review in reviews:
            bot_id = str(review.get("bot_id") or "").strip()
            symbol = str(review.get("symbol") or "").strip().upper()
            if not bot_id or not symbol:
                review["entry_follow_through_status"] = "unresolved"
                review["entry_follow_through_at"] = None
                review["entry_follow_through_event_type"] = None
                review["outcome_status"] = "unresolved"
                review["outcome"] = None
                review["outcome_attribution_note"] = "missing_bot_or_symbol"
                continue
            grouped_reviews.setdefault((bot_id, symbol), []).append(review)

        for key, bucket in grouped_reviews.items():
            bucket.sort(key=lambda item: item["_decision_dt"])
            related_events = list(execution_events.get(key) or [])
            related_trades = list(trades_by_key.get(key) or [])
            trade_index = 0
            for index, review in enumerate(bucket):
                next_decision_dt = None
                if index + 1 < len(bucket):
                    next_decision_dt = bucket[index + 1]["_decision_dt"]
                follow_status, follow_at, follow_type = self._match_execution_event(
                    review,
                    events=related_events,
                    next_decision_dt=next_decision_dt,
                )
                review["entry_follow_through_status"] = follow_status
                review["entry_follow_through_at"] = follow_at
                review["entry_follow_through_event_type"] = follow_type

                decision_dt = review["_decision_dt"]
                window_end_ts = decision_dt.timestamp() + float(self._outcome_window_seconds())
                if next_decision_dt is not None:
                    window_end_ts = min(window_end_ts, next_decision_dt.timestamp())

                while trade_index < len(related_trades):
                    trade_dt = related_trades[trade_index]["_trade_dt"]
                    if trade_dt is None:
                        trade_index += 1
                        continue
                    if trade_dt < decision_dt:
                        trade_index += 1
                        continue
                    break

                linked_trade = None
                probe_index = trade_index
                while probe_index < len(related_trades):
                    trade = related_trades[probe_index]
                    trade_dt = trade.get("_trade_dt")
                    if trade_dt is None:
                        probe_index += 1
                        continue
                    if trade_dt.timestamp() > window_end_ts:
                        break
                    linked_trade = trade
                    trade_index = probe_index + 1
                    break

                if linked_trade is None:
                    review["outcome_status"] = (
                        "not_executed"
                        if follow_status == "no_entry_action_seen"
                        else "unresolved"
                    )
                    review["outcome"] = None
                    review["outcome_attribution_note"] = (
                        "no_linked_trade_before_next_decision"
                    )
                    continue

                pnl_value = self._safe_float(linked_trade.get("realized_pnl"), 0.0) or 0.0
                review["outcome_status"] = "linked"
                review["outcome"] = {
                    "trade_time": linked_trade.get("trade_time"),
                    "realized_pnl": round(pnl_value, 8),
                    "win": pnl_value > 0,
                    "attribution_source": linked_trade.get("attribution_source"),
                    "order_link_id": linked_trade.get("order_link_id"),
                    "position_idx": linked_trade.get("position_idx"),
                    "order_id": linked_trade.get("order_id"),
                }
                review["outcome_attribution_note"] = (
                    "same_bot_symbol_first_trade_before_next_decision"
                )
        return reviews

    @staticmethod
    def _confidence_bucket(confidence: Optional[float]) -> str:
        if confidence is None:
            return "unknown"
        if confidence < 0.45:
            return "low"
        if confidence < 0.70:
            return "mid"
        return "high"

    @staticmethod
    def _avg(values: List[float]) -> Optional[float]:
        if not values:
            return None
        return round(sum(values) / len(values), 8)

    @staticmethod
    def _median(values: List[float]) -> Optional[float]:
        if not values:
            return None
        return round(float(median(values)), 8)

    @classmethod
    def _build_bucket_metrics(cls, reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        verdict_buckets = {"APPROVE": [], "CAUTION": [], "REJECT": []}
        for review in reviews:
            verdict = str(review.get("verdict") or "").strip().upper()
            if verdict in verdict_buckets:
                verdict_buckets[verdict].append(review)

        verdict_counts = {key.lower(): len(value) for key, value in verdict_buckets.items()}
        calibration: Dict[str, Any] = {
            "approve_count": verdict_counts["approve"],
            "caution_count": verdict_counts["caution"],
            "reject_count": verdict_counts["reject"],
            "executed_after_approve_count": 0,
            "executed_after_caution_count": 0,
            "executed_after_reject_count": 0,
            "linked_outcome_count": 0,
            "linked_outcome_by_verdict": {},
            "avg_pnl_by_verdict": {},
            "median_pnl_by_verdict": {},
            "win_rate_by_verdict": {},
            "confidence_buckets": {},
        }

        for verdict, bucket in verdict_buckets.items():
            verdict_key = verdict.lower()
            follow_count = sum(
                1
                for review in bucket
                if review.get("entry_follow_through_status") == "entry_action_seen"
            )
            calibration[f"executed_after_{verdict_key}_count"] = follow_count
            linked = [review for review in bucket if review.get("outcome_status") == "linked"]
            calibration["linked_outcome_by_verdict"][verdict_key] = len(linked)
            calibration["linked_outcome_count"] += len(linked)
            pnls = [
                cls._safe_float(((review.get("outcome") or {}).get("realized_pnl")), 0.0)
                or 0.0
                for review in linked
            ]
            wins = sum(1 for pnl in pnls if pnl > 0)
            calibration["avg_pnl_by_verdict"][verdict_key] = cls._avg(pnls)
            calibration["median_pnl_by_verdict"][verdict_key] = cls._median(pnls)
            calibration["win_rate_by_verdict"][verdict_key] = (
                round(wins / len(pnls), 4) if pnls else None
            )

        confidence_buckets: Dict[str, List[Dict[str, Any]]] = {}
        for review in reviews:
            confidence_buckets.setdefault(
                cls._confidence_bucket(review.get("confidence")),
                [],
            ).append(review)
        for bucket_name, bucket_reviews in confidence_buckets.items():
            linked = [
                review for review in bucket_reviews if review.get("outcome_status") == "linked"
            ]
            pnls = [
                cls._safe_float(((review.get("outcome") or {}).get("realized_pnl")), 0.0)
                or 0.0
                for review in linked
            ]
            calibration["confidence_buckets"][bucket_name] = {
                "count": len(bucket_reviews),
                "linked_outcome_count": len(linked),
                "avg_pnl": cls._avg(pnls),
                "win_rate": (
                    round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4)
                    if pnls
                    else None
                ),
            }
        return calibration

    @classmethod
    def _build_slice_summaries(
        cls,
        reviews: List[Dict[str, Any]],
        *,
        key_name: str,
        top_n: int = 8,
    ) -> List[Dict[str, Any]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for review in reviews:
            key = str(review.get(key_name) or "").strip()
            if not key:
                continue
            buckets.setdefault(key, []).append(review)
        summary_rows: List[Dict[str, Any]] = []
        for key, bucket in buckets.items():
            linked = [review for review in bucket if review.get("outcome_status") == "linked"]
            pnls = [
                cls._safe_float(((review.get("outcome") or {}).get("realized_pnl")), 0.0)
                or 0.0
                for review in linked
            ]
            summary_rows.append(
                {
                    key_name: key,
                    "decision_count": len(bucket),
                    "approve_count": sum(
                        1 for review in bucket if review.get("verdict") == "APPROVE"
                    ),
                    "caution_count": sum(
                        1 for review in bucket if review.get("verdict") == "CAUTION"
                    ),
                    "reject_count": sum(
                        1 for review in bucket if review.get("verdict") == "REJECT"
                    ),
                    "follow_through_count": sum(
                        1
                        for review in bucket
                        if review.get("entry_follow_through_status") == "entry_action_seen"
                    ),
                    "linked_outcome_count": len(linked),
                    "avg_pnl": cls._avg(pnls),
                    "win_rate": (
                        round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4)
                        if pnls
                        else None
                    ),
                }
            )
        summary_rows.sort(
            key=lambda row: (
                -int(row.get("linked_outcome_count") or 0),
                -int(row.get("decision_count") or 0),
                str(row.get(key_name) or ""),
            )
        )
        return summary_rows[:top_n]

    @classmethod
    def _build_symbol_usefulness(
        cls,
        reviews: List[Dict[str, Any]],
        *,
        top_n: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for review in reviews:
            symbol = str(review.get("symbol") or "").strip().upper()
            if symbol:
                by_symbol.setdefault(symbol, []).append(review)

        scored: List[Dict[str, Any]] = []
        for symbol, bucket in by_symbol.items():
            approve_pnls = [
                cls._safe_float(((review.get("outcome") or {}).get("realized_pnl")), 0.0)
                or 0.0
                for review in bucket
                if review.get("verdict") == "APPROVE" and review.get("outcome_status") == "linked"
            ]
            reject_pnls = [
                cls._safe_float(((review.get("outcome") or {}).get("realized_pnl")), 0.0)
                or 0.0
                for review in bucket
                if review.get("verdict") == "REJECT" and review.get("outcome_status") == "linked"
            ]
            if not approve_pnls or not reject_pnls:
                continue
            approve_avg = cls._avg(approve_pnls)
            reject_avg = cls._avg(reject_pnls)
            if approve_avg is None or reject_avg is None:
                continue
            scored.append(
                {
                    "symbol": symbol,
                    "approve_linked_count": len(approve_pnls),
                    "reject_linked_count": len(reject_pnls),
                    "approve_avg_pnl": approve_avg,
                    "reject_avg_pnl": reject_avg,
                    "correlation_gap": round(approve_avg - reject_avg, 8),
                }
            )

        scored.sort(key=lambda row: (-row["correlation_gap"], row["symbol"]))
        strongest = scored[:top_n]
        weakest = sorted(scored, key=lambda row: (row["correlation_gap"], row["symbol"]))[:top_n]
        return {"strongest": strongest, "weakest": weakest}

    @classmethod
    def _build_summary(cls, reviews: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        ok_reviews = [review for review in reviews if review.get("status") == "ok"]
        summary = {
            "total_decisions": len(reviews),
            "ok_decisions": len(ok_reviews),
            "error_count": sum(1 for review in reviews if review.get("status") == "error"),
            "timeout_count": sum(
                1
                for review in reviews
                if str(review.get("error") or "").lower().find("timed out") >= 0
            ),
            "escalation_count": sum(1 for review in reviews if review.get("escalated")),
            "model_usage_counts": {},
            "error_code_counts": {},
            "local_alignment_counts": {},
            "follow_through_counts": {},
            "outcome_status_counts": {},
            "by_symbol": cls._build_slice_summaries(reviews, key_name="symbol"),
            "by_bot": cls._build_slice_summaries(reviews, key_name="bot_id"),
            "by_decision_type": cls._build_slice_summaries(
                reviews,
                key_name="decision_type",
                top_n=6,
            ),
            "symbol_usefulness": cls._build_symbol_usefulness(reviews),
            "correlational_only": True,
            "attribution_policy": metadata.get("attribution_policy"),
        }
        for review in reviews:
            model = str(review.get("model") or "").strip()
            if model:
                summary["model_usage_counts"][model] = (
                    int(summary["model_usage_counts"].get(model, 0) or 0) + 1
                )
            error_code = str(review.get("error_code") or "").strip()
            if error_code:
                summary["error_code_counts"][error_code] = (
                    int(summary["error_code_counts"].get(error_code, 0) or 0) + 1
                )
            local_alignment = str(review.get("local_alignment") or "").strip()
            if local_alignment:
                summary["local_alignment_counts"][local_alignment] = (
                    int(summary["local_alignment_counts"].get(local_alignment, 0) or 0) + 1
                )
            follow_through = str(review.get("entry_follow_through_status") or "").strip()
            if follow_through:
                summary["follow_through_counts"][follow_through] = (
                    int(summary["follow_through_counts"].get(follow_through, 0) or 0) + 1
                )
            outcome_status = str(review.get("outcome_status") or "").strip()
            if outcome_status:
                summary["outcome_status_counts"][outcome_status] = (
                    int(summary["outcome_status_counts"].get(outcome_status, 0) or 0) + 1
                )
        return summary

    def _filtered_reviews(
        self,
        reviews: List[Dict[str, Any]],
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_bot_id = str(bot_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        cutoff_ts = None
        if since_seconds is not None:
            try:
                cutoff_ts = self.now_fn() - max(float(since_seconds), 0.0)
            except (TypeError, ValueError):
                cutoff_ts = None
        baseline_dt = None
        service = getattr(self, "performance_baseline_service", None)
        if service is not None:
            baseline_dt = (
                service.get_effective_started_at(bot_id=normalized_bot_id)
                if normalized_bot_id
                else service.get_global_started_at()
            )

        filtered: List[Dict[str, Any]] = []
        for review in reviews:
            if normalized_bot_id and str(review.get("bot_id") or "").strip() != normalized_bot_id:
                continue
            if normalized_symbol and str(review.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            decision_dt = review.get("_decision_dt")
            if cutoff_ts is not None and decision_dt is not None and decision_dt.timestamp() < cutoff_ts:
                continue
            if baseline_dt is not None and (decision_dt is None or decision_dt < baseline_dt):
                continue
            filtered.append(review)
        return filtered

    def refresh_snapshot(self, force: bool = False) -> Dict[str, Any]:
        current = self._read_snapshot()
        if not force:
            updated_at = self._parse_iso(current.get("updated_at"))
            if updated_at is not None and (self.now_fn() - updated_at.timestamp()) < self._snapshot_ttl_seconds():
                return current

        metadata = {
            "lookback_seconds": self._lookback_seconds(),
            "decision_limit": self._decision_limit(),
            "recent_limit": self._recent_limit(),
            "execution_window_seconds": self._execution_window_seconds(),
            "outcome_window_seconds": self._outcome_window_seconds(),
            "global_baseline_started_at": (
                self.performance_baseline_service.get_global_started_at().isoformat()
                if self.performance_baseline_service is not None
                and self.performance_baseline_service.get_global_started_at() is not None
                else None
            ),
            "attribution_policy": (
                "advisor_decision -> same bot/symbol follow-through audit event within "
                "execution window; realized outcome links to the first same bot/symbol "
                "closed trade before the next advisor decision or outcome-window cutoff"
            ),
        }
        try:
            reviews = self._load_decisions()
            reviews = self._attach_linked_outcomes(
                reviews,
                self._load_execution_events(),
                self._load_trade_logs(),
            )
            for review in reviews:
                review.pop("_decision_dt", None)
                compact_context = dict(review.get("compact_context") or {})
                review["confidence_bucket"] = self._confidence_bucket(review.get("confidence"))
                review["compact_context"] = compact_context
            reviews.sort(key=self._decision_sort_key)
            recent_reviews = reviews[-self._recent_limit():]
            recent_reviews.reverse()
            snapshot = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata,
                "reviews": reviews,
                "recent": recent_reviews,
                "summary": self._build_summary(reviews, metadata),
                "calibration": self._build_bucket_metrics(
                    [review for review in reviews if review.get("status") == "ok"]
                ),
                "error": None,
            }
        except Exception as exc:
            logger.warning("Failed to refresh AI advisor analytics: %s", exc)
            snapshot = dict(current)
            snapshot["updated_at"] = current.get("updated_at")
            snapshot["metadata"] = dict(current.get("metadata") or metadata)
            snapshot["error"] = str(exc)
        self._write_snapshot(snapshot)
        return snapshot

    def get_recent_reviews(
        self,
        *,
        limit: int = 50,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        recent = self._filtered_reviews(
            self._load_snapshot_reviews(snapshot),
            since_seconds=since_seconds,
            bot_id=bot_id,
            symbol=symbol,
        )
        recent.sort(key=self._decision_sort_key, reverse=True)
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "decisions": recent[: max(int(limit or 0), 0)],
        }

    def get_summary(
        self,
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        filtered_reviews = self._filtered_reviews(
            self._load_snapshot_reviews(snapshot),
            since_seconds=since_seconds,
            bot_id=bot_id,
            symbol=symbol,
        )
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "summary": self._build_summary(filtered_reviews, dict(snapshot.get("metadata") or {})),
        }

    def get_calibration(
        self,
        *,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        filtered_reviews = [
            review
            for review in self._filtered_reviews(
                self._load_snapshot_reviews(snapshot),
                since_seconds=since_seconds,
                bot_id=bot_id,
                symbol=symbol,
            )
            if review.get("status") == "ok"
        ]
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "calibration": self._build_bucket_metrics(filtered_reviews),
        }

    @classmethod
    def _load_snapshot_reviews(cls, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        reviews = list(snapshot.get("reviews") or [])
        if reviews:
            hydrated = []
            for review in reviews:
                item = dict(review or {})
                item["_decision_dt"] = cls._parse_iso(item.get("decision_at"))
                hydrated.append(item)
            return hydrated
        return []
