import json
import logging
import os
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.ai_advisor_analytics_service import AIAdvisorAnalyticsService
from services.backtest_validation_service import BacktestValidationService
from services.lock_service import file_lock
from services.pnl_service import PnlService
from services.performance_baseline_service import PerformanceBaselineService

logger = logging.getLogger(__name__)


class AdvisorReplayAnalysisService:
    """Correlational advisor usefulness analysis across live and validated replay windows."""

    VALID_VERDICTS = {"APPROVE", "CAUTION", "REJECT"}
    DECISION_BUCKET_SECONDS = 900

    def __init__(
        self,
        *,
        ai_advisor_analytics_service: Optional[AIAdvisorAnalyticsService] = None,
        validation_service: Optional[BacktestValidationService] = None,
        advisor_review_path: str = "storage/ai_advisor_review.json",
        runs_root: str = "storage/backtest_runs",
        file_path: str = "storage/advisor_replay_analysis.json",
        now_fn: Optional[Any] = None,
        performance_baseline_service: Optional[PerformanceBaselineService] = None,
    ) -> None:
        self.ai_advisor_analytics_service = ai_advisor_analytics_service
        self.validation_service = validation_service or BacktestValidationService(
            runs_root=runs_root
        )
        self.advisor_review_path = Path(advisor_review_path)
        self.runs_root = Path(runs_root)
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
    def _default_snapshot() -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "metadata": {},
            "recent": [],
            "summary": {},
            "by_symbol": [],
            "by_mode": [],
            "runs": [],
            "error": None,
        }

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
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _snapshot_ttl_seconds(self) -> int:
        return 30

    def _recent_limit(self) -> int:
        return 200

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _read_snapshot(self) -> Dict[str, Any]:
        payload = self._read_json(self.file_path, {})
        if not isinstance(payload, dict):
            return self._default_snapshot()
        snapshot = self._default_snapshot()
        snapshot.update(payload)
        snapshot["metadata"] = dict(snapshot.get("metadata") or {})
        snapshot["recent"] = list(snapshot.get("recent") or [])
        snapshot["summary"] = dict(snapshot.get("summary") or {})
        snapshot["by_symbol"] = list(snapshot.get("by_symbol") or [])
        snapshot["by_mode"] = list(snapshot.get("by_mode") or [])
        snapshot["runs"] = list(snapshot.get("runs") or [])
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
            logger.warning("Advisor replay analysis write failed: %s", exc)

    def _load_live_reviews(self, force: bool = False) -> List[Dict[str, Any]]:
        snapshot_payload = {}
        if self.ai_advisor_analytics_service is not None:
            try:
                snapshot_payload = self.ai_advisor_analytics_service.refresh_snapshot(
                    force=force
                )
            except Exception as exc:
                logger.warning("Advisor replay analysis refresh failed: %s", exc)
        if not snapshot_payload:
            snapshot_payload = self._read_json(self.advisor_review_path, {})
        reviews = list((snapshot_payload or {}).get("reviews") or [])
        normalized = []
        baseline_dt = (
            self.performance_baseline_service.get_global_started_at()
            if self.performance_baseline_service is not None
            else None
        )
        for review in reviews:
            record = dict(review or {})
            verdict = str(record.get("verdict") or "").strip().upper()
            decision_dt = self._parse_iso(record.get("decision_at"))
            if verdict not in self.VALID_VERDICTS or decision_dt is None:
                continue
            if baseline_dt is not None and decision_dt < baseline_dt:
                continue
            record["verdict"] = verdict
            record["_decision_dt"] = decision_dt
            record["symbol"] = str(record.get("symbol") or "").strip().upper() or None
            record["mode"] = str(record.get("mode") or "").strip().lower() or None
            record["decision_type"] = (
                str(record.get("decision_type") or "").strip().lower() or None
            )
            normalized.append(record)
        normalized.sort(key=lambda item: item["_decision_dt"])
        return normalized

    @staticmethod
    def _load_run_snapshots(run_dir: Path) -> List[Dict[str, Any]]:
        payload = AdvisorReplayAnalysisService._read_json(
            run_dir / "decision_snapshots.json",
            {},
        )
        snapshots = list((payload or {}).get("snapshots") or [])
        normalized = []
        for snapshot in snapshots:
            record = dict(snapshot or {})
            decision_dt = AdvisorReplayAnalysisService._parse_iso(
                record.get("decision_at") or record.get("last_updated_at")
            )
            if decision_dt is None:
                continue
            record["_decision_dt"] = decision_dt
            record["symbol"] = str(record.get("symbol") or "").strip().upper() or None
            record["mode"] = str(record.get("mode") or "").strip().lower() or None
            record["decision_type"] = (
                str(record.get("decision_type") or "").strip().lower() or None
            )
            normalized.append(record)
        normalized.sort(key=lambda item: item["_decision_dt"])
        return normalized

    def _load_validated_runs(self) -> List[Dict[str, Any]]:
        runs = []
        for validation_path in sorted(
            self.runs_root.glob("*/validation.json"),
            reverse=True,
        ):
            payload = self._read_json(validation_path, {})
            if not isinstance(payload, dict) or not payload:
                continue
            comparison = dict(payload.get("comparison") or {})
            realism = dict(comparison.get("realism") or {})
            grade = str(realism.get("grade") or "").strip().upper()
            if grade == "INSUFFICIENT_DATA":
                included = False
            else:
                included = True
            window = dict(comparison.get("window") or {})
            start_dt = self._parse_iso(window.get("start_time"))
            end_dt = self._parse_iso(window.get("end_time"))
            run_dir = Path(str(payload.get("run_dir") or validation_path.parent))
            runs.append(
                {
                    "run_id": str(payload.get("run_id") or validation_path.parent.name),
                    "run_dir": run_dir,
                    "validation_path": str(validation_path),
                    "symbol": str(comparison.get("symbol") or "").strip().upper() or None,
                    "mode": str(comparison.get("mode") or "").strip().lower() or None,
                    "start_time": start_dt.isoformat() if start_dt else None,
                    "end_time": end_dt.isoformat() if end_dt else None,
                    "_start_dt": start_dt,
                    "_end_dt": end_dt,
                    "validation_grade": grade or None,
                    "validation_score": self._safe_float(realism.get("score"), None),
                    "included": included,
                    "payload": payload,
                    "snapshots": self._load_run_snapshots(run_dir) if included else [],
                }
            )
        return runs

    @staticmethod
    def _bucket_for_dt(value: datetime) -> int:
        return int(value.timestamp()) // AdvisorReplayAnalysisService.DECISION_BUCKET_SECONDS

    @classmethod
    def _snapshot_status(cls, snapshot: Dict[str, Any]) -> str:
        lifecycle = dict(snapshot.get("lifecycle") or {})
        if lifecycle.get("closed"):
            return "closed"
        if lifecycle.get("opened"):
            return "opened"
        if lifecycle.get("submitted"):
            return "submitted"
        if lifecycle.get("blocked"):
            return "blocked"
        return "awaiting"

    @classmethod
    def _review_live_outcome_label(cls, review: Dict[str, Any]) -> str:
        if review.get("outcome_status") == "linked":
            pnl = cls._safe_float(((review.get("outcome") or {}).get("realized_pnl")), 0.0) or 0.0
            if pnl > 0:
                return "positive_outcome"
            if pnl < 0:
                return "negative_outcome"
            return "flat_outcome"
        if review.get("entry_follow_through_status") == "no_entry_action_seen":
            return "not_executed"
        return "unresolved"

    @classmethod
    def _snapshot_replay_outcome_label(cls, snapshot: Optional[Dict[str, Any]]) -> str:
        if not snapshot:
            return "unresolved"
        lifecycle = dict(snapshot.get("lifecycle") or {})
        if lifecycle.get("blocked"):
            return "blocked"
        pnl = cls._safe_float(lifecycle.get("realized_pnl"), None)
        if pnl is None:
            return "unresolved"
        if pnl > 0:
            return "positive_outcome"
        if pnl < 0:
            return "negative_outcome"
        return "flat_outcome"

    @staticmethod
    def _local_intent_label(review: Dict[str, Any]) -> str:
        compact_context = dict(review.get("compact_context") or {})
        if bool(compact_context.get("gate_blocked")) or compact_context.get("entry_allowed") is False:
            return "local_blocked"
        mode = str(review.get("mode") or "").strip().lower()
        if mode in {"long", "short"}:
            return f"local_{mode}"
        side_bias = str(compact_context.get("side_bias") or "").strip().lower()
        if side_bias:
            return f"local_{side_bias}"
        return "local_candidate"

    @classmethod
    def _build_agreement_bucket(cls, review: Dict[str, Any], *, source: str, snapshot: Optional[Dict[str, Any]] = None) -> str:
        verdict = str(review.get("verdict") or "").strip().lower()
        if source == "live":
            outcome_label = cls._review_live_outcome_label(review)
        else:
            outcome_label = cls._snapshot_replay_outcome_label(snapshot)
        return f"{cls._local_intent_label(review)}+advisor_{verdict}+{outcome_label}"

    @staticmethod
    def _bucket_key(symbol: str, mode: str, decision_type: str, bucket: int) -> str:
        return "|".join([symbol or "", mode or "", decision_type or "", str(bucket)])

    def _find_best_replay_match(
        self,
        review: Dict[str, Any],
        candidate_runs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        decision_dt = review["_decision_dt"]
        bucket = self._bucket_for_dt(decision_dt)
        best_match = None
        best_rank: Tuple[int, float] = (-1, -1.0)

        for run in candidate_runs:
            if not run.get("included"):
                continue
            start_dt = run.get("_start_dt")
            end_dt = run.get("_end_dt")
            if start_dt and decision_dt < start_dt:
                continue
            if end_dt and decision_dt > end_dt:
                continue
            if run.get("symbol") and run.get("symbol") != review.get("symbol"):
                continue
            if run.get("mode") and run.get("mode") != review.get("mode"):
                continue

            matching = []
            for snapshot in list(run.get("snapshots") or []):
                if snapshot.get("symbol") != review.get("symbol"):
                    continue
                if snapshot.get("mode") != review.get("mode"):
                    continue
                if snapshot.get("decision_type") != review.get("decision_type"):
                    continue
                snapshot_bucket = self._bucket_for_dt(snapshot["_decision_dt"])
                if snapshot_bucket != bucket:
                    continue
                matching.append(snapshot)

            if not matching:
                rank = (0, float(run.get("validation_score") or 0.0))
                if rank > best_rank:
                    best_rank = rank
                    best_match = {
                        "match_status": "no_replay_bucket_match",
                        "run": run,
                        "snapshot": None,
                    }
                continue

            preferred = matching
            live_follow = str(review.get("entry_follow_through_status") or "").strip()
            if live_follow == "entry_action_seen":
                submitted = [
                    snapshot
                    for snapshot in matching
                    if bool((snapshot.get("lifecycle") or {}).get("submitted"))
                ]
                if submitted:
                    preferred = submitted
            elif live_follow == "no_entry_action_seen":
                blocked = [
                    snapshot
                    for snapshot in matching
                    if bool((snapshot.get("lifecycle") or {}).get("blocked"))
                ]
                if blocked:
                    preferred = blocked

            if len(preferred) == 1:
                snapshot = preferred[0]
                rank = (3, float(run.get("validation_score") or 0.0))
                if rank > best_rank:
                    best_rank = rank
                    best_match = {
                        "match_status": "matched",
                        "run": run,
                        "snapshot": snapshot,
                    }
            else:
                rank = (1, float(run.get("validation_score") or 0.0))
                if rank > best_rank:
                    best_rank = rank
                    best_match = {
                        "match_status": "ambiguous_replay_bucket",
                        "run": run,
                        "snapshot": None,
                    }

        if best_match is None:
            return {"match_status": "no_validated_window", "run": None, "snapshot": None}
        return best_match

    def _build_recent_rows(
        self,
        live_reviews: List[Dict[str, Any]],
        runs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        recent_rows = []
        run_summary: Dict[str, Dict[str, Any]] = {}
        runs_by_symbol_mode: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for run in runs:
            key = (
                str(run.get("symbol") or "").strip().upper(),
                str(run.get("mode") or "").strip().lower(),
            )
            runs_by_symbol_mode.setdefault(key, []).append(run)
            run_summary.setdefault(
                str(run.get("run_id")),
                {
                    "run_id": run.get("run_id"),
                    "symbol": run.get("symbol"),
                    "mode": run.get("mode"),
                    "validation_grade": run.get("validation_grade"),
                    "validation_score": run.get("validation_score"),
                    "matched_review_count": 0,
                    "positive_replay_count": 0,
                    "negative_replay_count": 0,
                    "blocked_replay_count": 0,
                    "useful_signal_gap": None,
                    "included": bool(run.get("included")),
                },
            )

        for review in live_reviews:
            key = (
                str(review.get("symbol") or "").strip().upper(),
                str(review.get("mode") or "").strip().lower(),
            )
            match = self._find_best_replay_match(review, runs_by_symbol_mode.get(key, []))
            snapshot = match.get("snapshot")
            run = match.get("run")
            live_outcome = dict(review.get("outcome") or {})
            replay_lifecycle = dict((snapshot or {}).get("lifecycle") or {})
            row = {
                "decision_id": review.get("decision_id"),
                "decision_at": review.get("decision_at"),
                "symbol": review.get("symbol"),
                "mode": review.get("mode"),
                "decision_type": review.get("decision_type"),
                "verdict": review.get("verdict"),
                "confidence": review.get("confidence"),
                "model": review.get("model"),
                "local_alignment": review.get("local_alignment"),
                "local_intent": self._local_intent_label(review),
                "live_entry_follow_through_status": review.get("entry_follow_through_status"),
                "live_outcome_status": review.get("outcome_status"),
                "live_realized_pnl": live_outcome.get("realized_pnl"),
                "live_win": live_outcome.get("win"),
                "live_agreement_bucket": self._build_agreement_bucket(review, source="live"),
                "replay_match_status": match.get("match_status"),
                "replay_run_id": (run or {}).get("run_id"),
                "replay_validation_grade": (run or {}).get("validation_grade"),
                "replay_validation_score": (run or {}).get("validation_score"),
                "replay_snapshot_id": (snapshot or {}).get("snapshot_id"),
                "replay_status": self._snapshot_status(snapshot) if snapshot else None,
                "replay_realized_pnl": replay_lifecycle.get("realized_pnl"),
                "replay_win": (
                    None
                    if self._safe_float(replay_lifecycle.get("realized_pnl"), None) is None
                    else (self._safe_float(replay_lifecycle.get("realized_pnl"), 0.0) or 0.0) > 0
                ),
                "replay_exit_reason": replay_lifecycle.get("exit_reason"),
                "replay_blocked": bool(replay_lifecycle.get("blocked")) if snapshot else None,
                "replay_agreement_bucket": (
                    self._build_agreement_bucket(review, source="replay", snapshot=snapshot)
                    if snapshot
                    else None
                ),
            }
            recent_rows.append(row)
            if run and snapshot:
                run_bucket = run_summary[str(run.get("run_id"))]
                run_bucket["matched_review_count"] += 1
                replay_pnl = self._safe_float(replay_lifecycle.get("realized_pnl"), None)
                if replay_lifecycle.get("blocked"):
                    run_bucket["blocked_replay_count"] += 1
                elif replay_pnl is not None and replay_pnl > 0:
                    run_bucket["positive_replay_count"] += 1
                elif replay_pnl is not None and replay_pnl < 0:
                    run_bucket["negative_replay_count"] += 1

        recent_rows.sort(key=lambda item: str(item.get("decision_at") or ""), reverse=True)
        runs_list = list(run_summary.values())
        runs_list.sort(
            key=lambda item: (
                -int(item.get("matched_review_count") or 0),
                -float(item.get("validation_score") or 0.0),
                str(item.get("run_id") or ""),
            )
        )
        return recent_rows, runs_list

    @staticmethod
    def _trade_metric_rows_from_live(reviews: List[Dict[str, Any]], verdict: str) -> List[Dict[str, Any]]:
        rows = []
        for review in reviews:
            if review.get("verdict") != verdict or review.get("outcome_status") != "linked":
                continue
            pnl = AdvisorReplayAnalysisService._safe_float(
                ((review.get("outcome") or {}).get("realized_pnl")),
                None,
            )
            if pnl is None:
                continue
            rows.append({"realized_pnl": pnl})
        return rows

    @staticmethod
    def _trade_metric_rows_from_replay(rows: List[Dict[str, Any]], verdict: str) -> List[Dict[str, Any]]:
        trade_rows = []
        for row in rows:
            if row.get("verdict") != verdict:
                continue
            pnl = AdvisorReplayAnalysisService._safe_float(row.get("replay_realized_pnl"), None)
            if pnl is None:
                continue
            trade_rows.append({"realized_pnl": pnl})
        return trade_rows

    @classmethod
    def _metric_bundle(cls, trade_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        stats = PnlService._build_trade_window_stats(trade_rows)
        return {
            "count": len(trade_rows),
            "avg_pnl": round(
                sum(float(row.get("realized_pnl") or 0.0) for row in trade_rows) / len(trade_rows),
                8,
            )
            if trade_rows
            else None,
            "profit_factor": stats.get("profit_factor"),
            "payoff_ratio": stats.get("payoff_ratio"),
            "win_rate": stats.get("win_rate"),
            "net_pnl": stats.get("net_pnl"),
        }

    def _build_verdict_metrics(self, live_reviews: List[Dict[str, Any]], matched_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {
            "total_advisor_reviewed_decisions": len(live_reviews),
            "verdict_counts": {},
            "executed_after_verdict_counts": {},
            "blocked_or_skipped_counts": {},
            "live": {},
            "replay": {},
            "confidence_buckets": {},
        }
        for verdict in sorted(self.VALID_VERDICTS):
            verdict_key = verdict.lower()
            verdict_live = [review for review in live_reviews if review.get("verdict") == verdict]
            verdict_replay = [row for row in matched_rows if row.get("verdict") == verdict]
            payload["verdict_counts"][verdict_key] = len(verdict_live)
            payload["executed_after_verdict_counts"][verdict_key] = sum(
                1
                for review in verdict_live
                if review.get("live_entry_follow_through_status", review.get("entry_follow_through_status"))
                == "entry_action_seen"
            )
            payload["blocked_or_skipped_counts"][verdict_key] = sum(
                1
                for review in verdict_live
                if review.get("live_entry_follow_through_status", review.get("entry_follow_through_status"))
                == "no_entry_action_seen"
            )
            payload["live"][verdict_key] = self._metric_bundle(
                self._trade_metric_rows_from_live(verdict_live, verdict)
            )
            payload["replay"][verdict_key] = self._metric_bundle(
                self._trade_metric_rows_from_replay(verdict_replay, verdict)
            )

        confidence_buckets = {"low": [], "mid": [], "high": [], "unknown": []}
        for row in matched_rows:
            confidence = self._safe_float(row.get("confidence"), None)
            if confidence is None:
                bucket = "unknown"
            elif confidence < 0.45:
                bucket = "low"
            elif confidence < 0.70:
                bucket = "mid"
            else:
                bucket = "high"
            confidence_buckets[bucket].append(row)
        for bucket_name, rows in confidence_buckets.items():
            live_trades = []
            replay_trades = []
            for row in rows:
                live_pnl = self._safe_float(row.get("live_realized_pnl"), None)
                if live_pnl is not None:
                    live_trades.append({"realized_pnl": live_pnl})
                replay_pnl = self._safe_float(row.get("replay_realized_pnl"), None)
                if replay_pnl is not None:
                    replay_trades.append({"realized_pnl": replay_pnl})
            payload["confidence_buckets"][bucket_name] = {
                "count": len(rows),
                "live": self._metric_bundle(live_trades),
                "replay": self._metric_bundle(replay_trades),
            }
        return payload

    @staticmethod
    def _separation_gap(metric_payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
        approve = dict((metric_payload.get("approve") or {}))
        reject = dict((metric_payload.get("reject") or {}))
        return {
            "avg_pnl_gap": AdvisorReplayAnalysisService._diff(
                approve.get("avg_pnl"),
                reject.get("avg_pnl"),
            ),
            "win_rate_gap": AdvisorReplayAnalysisService._diff(
                approve.get("win_rate"),
                reject.get("win_rate"),
            ),
            "profit_factor_gap": AdvisorReplayAnalysisService._diff(
                approve.get("profit_factor"),
                reject.get("profit_factor"),
            ),
        }

    @staticmethod
    def _diff(left: Optional[float], right: Optional[float]) -> Optional[float]:
        if left is None or right is None:
            return None
        return round(float(left) - float(right), 8)

    def _usefulness_grade(
        self,
        *,
        live_metrics: Dict[str, Any],
        replay_metrics: Dict[str, Any],
        compared_count: int,
        validation_scores: List[float],
    ) -> Dict[str, Any]:
        live_approve = dict((live_metrics.get("approve") or {}))
        live_reject = dict((live_metrics.get("reject") or {}))
        replay_approve = dict((replay_metrics.get("approve") or {}))
        replay_reject = dict((replay_metrics.get("reject") or {}))
        live_gap = self._separation_gap(live_metrics)
        replay_gap = self._separation_gap(replay_metrics)
        avg_validation_score = (
            round(sum(validation_scores) / len(validation_scores), 4)
            if validation_scores
            else None
        )

        if (
            int(live_approve.get("count") or 0) < 2
            or int(live_reject.get("count") or 0) < 2
            or int(replay_approve.get("count") or 0) < 2
            or int(replay_reject.get("count") or 0) < 2
            or compared_count < 4
        ):
            return {
                "grade": "INSUFFICIENT_DATA",
                "reason": "not_enough_matched_live_replay_outcomes",
                "avg_validation_score": avg_validation_score,
                "live_gap": live_gap,
                "replay_gap": replay_gap,
            }

        if (
            (live_gap.get("avg_pnl_gap") or -999.0) > 0
            and (replay_gap.get("avg_pnl_gap") or -999.0) > 0
            and (live_gap.get("win_rate_gap") or -999.0) >= 0
            and (replay_gap.get("win_rate_gap") or -999.0) >= 0
            and (avg_validation_score is None or avg_validation_score >= 60.0)
        ):
            return {
                "grade": "USEFUL",
                "reason": "approve_outperforms_reject_in_live_and_replay",
                "avg_validation_score": avg_validation_score,
                "live_gap": live_gap,
                "replay_gap": replay_gap,
            }

        if (
            (live_gap.get("avg_pnl_gap") or 0.0) <= 0
            and (replay_gap.get("avg_pnl_gap") or 0.0) <= 0
        ):
            return {
                "grade": "NOT_PROVEN",
                "reason": "approve_does_not_separate_from_reject",
                "avg_validation_score": avg_validation_score,
                "live_gap": live_gap,
                "replay_gap": replay_gap,
            }

        return {
            "grade": "MIXED",
            "reason": "live_and_replay_signals_do_not_cleanly_agree",
            "avg_validation_score": avg_validation_score,
            "live_gap": live_gap,
            "replay_gap": replay_gap,
        }

    @staticmethod
    def _bucket_counts(rows: List[Dict[str, Any]], key_name: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in rows:
            key = str(row.get(key_name) or "").strip()
            if not key:
                continue
            counts[key] = int(counts.get(key, 0) or 0) + 1
        return counts

    def _build_slice_rows(self, matched_rows: List[Dict[str, Any]], *, key_name: str) -> List[Dict[str, Any]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for row in matched_rows:
            key = str(row.get(key_name) or "").strip()
            if key:
                buckets.setdefault(key, []).append(row)

        result_rows = []
        for key, bucket in buckets.items():
            live_reviews = []
            validation_scores = []
            for row in bucket:
                validation_score = self._safe_float(row.get("replay_validation_score"), None)
                if validation_score is not None:
                    validation_scores.append(float(validation_score))
                live_review = {
                    "verdict": row.get("verdict"),
                    "live_realized_pnl": row.get("live_realized_pnl"),
                    "entry_follow_through_status": row.get("live_entry_follow_through_status"),
                    "outcome_status": row.get("live_outcome_status"),
                    "outcome": {"realized_pnl": row.get("live_realized_pnl")},
                }
                if row.get("live_realized_pnl") is not None:
                    live_review["outcome_status"] = "linked"
                live_reviews.append(live_review)

            verdict_metrics = self._build_verdict_metrics(live_reviews, bucket)
            matched_count = sum(
                1 for row in bucket if str(row.get("replay_match_status") or "") == "matched"
            )
            usefulness = self._usefulness_grade(
                live_metrics=verdict_metrics["live"],
                replay_metrics=verdict_metrics["replay"],
                compared_count=matched_count,
                validation_scores=validation_scores,
            )
            result_rows.append(
                {
                    key_name: key,
                    "decision_count": len(bucket),
                    "live_linked_count": sum(1 for row in bucket if row.get("live_realized_pnl") is not None),
                    "replay_linked_count": sum(1 for row in bucket if row.get("replay_realized_pnl") is not None),
                    "verdict_counts": self._bucket_counts(bucket, "verdict"),
                    "live_approve_avg_pnl": ((verdict_metrics["live"].get("approve") or {}).get("avg_pnl")),
                    "live_reject_avg_pnl": ((verdict_metrics["live"].get("reject") or {}).get("avg_pnl")),
                    "replay_approve_avg_pnl": ((verdict_metrics["replay"].get("approve") or {}).get("avg_pnl")),
                    "replay_reject_avg_pnl": ((verdict_metrics["replay"].get("reject") or {}).get("avg_pnl")),
                    "usefulness": usefulness,
                }
            )
        result_rows.sort(
            key=lambda row: (
                -int(row.get("replay_linked_count") or 0),
                -int(row.get("decision_count") or 0),
                str(row.get(key_name) or ""),
            )
        )
        return result_rows

    def _build_summary(self, live_reviews: List[Dict[str, Any]], matched_rows: List[Dict[str, Any]], run_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        validation_scores = [
            float(row.get("replay_validation_score"))
            for row in matched_rows
            if self._safe_float(row.get("replay_validation_score"), None) is not None
        ]
        matched_count = sum(
            1
            for row in matched_rows
            if str(row.get("replay_match_status") or "") == "matched"
        )

        comparative_live_reviews = []
        for row in matched_rows:
            review = {
                "verdict": row.get("verdict"),
                "entry_follow_through_status": row.get("live_entry_follow_through_status"),
                "outcome_status": "linked" if row.get("live_realized_pnl") is not None else row.get("live_outcome_status"),
                "outcome": {"realized_pnl": row.get("live_realized_pnl")},
            }
            comparative_live_reviews.append(review)

        live_overall_metrics = self._build_verdict_metrics(live_reviews, [])
        comparative_metrics = self._build_verdict_metrics(comparative_live_reviews, matched_rows)
        usefulness = self._usefulness_grade(
            live_metrics=comparative_metrics["live"],
            replay_metrics=comparative_metrics["replay"],
            compared_count=matched_count,
            validation_scores=validation_scores,
        )

        posture = "balanced_or_unclear"
        comparative_live_gap = usefulness.get("live_gap") or {}
        if (comparative_live_gap.get("avg_pnl_gap") or 0.0) <= 0:
            posture = "too_permissive_or_not_separating"
        elif (
            self._safe_float(((comparative_metrics["live"].get("reject") or {}).get("avg_pnl")), None)
            is not None
            and (self._safe_float(((comparative_metrics["live"].get("reject") or {}).get("avg_pnl")), 0.0) or 0.0) > 0
        ):
            posture = "pessimism_risk"

        return {
            "comparison_unit": (
                "live advisor-reviewed decision matched to same symbol/mode/decision_type within a validated replay run and the same 15m decision bucket"
            ),
            "correlational_only": True,
            "live_overall": live_overall_metrics,
            "comparative_subset": {
                "matched_decision_count": matched_count,
                "matched_validation_run_count": sum(
                    1 for row in run_rows if int(row.get("matched_review_count") or 0) > 0
                ),
                "live": comparative_metrics["live"],
                "replay": comparative_metrics["replay"],
                "confidence_buckets": comparative_metrics["confidence_buckets"],
                "agreement_buckets": {
                    "live": self._bucket_counts(matched_rows, "live_agreement_bucket"),
                    "replay": self._bucket_counts(matched_rows, "replay_agreement_bucket"),
                },
            },
            "usefulness": usefulness,
            "posture_assessment": posture,
            "quality_flags": {
                "live_review_count": len(live_reviews),
                "matched_replay_count": matched_count,
                "unmatched_live_review_count": sum(
                    1
                    for row in matched_rows
                    if str(row.get("replay_match_status") or "") != "matched"
                ),
                "avg_validation_score": (
                    round(sum(validation_scores) / len(validation_scores), 4)
                    if validation_scores
                    else None
                ),
                "validation_grades": self._bucket_counts(run_rows, "validation_grade"),
                "replay_match_status_counts": self._bucket_counts(
                    matched_rows,
                    "replay_match_status",
                ),
            },
        }

    def refresh_snapshot(self, force: bool = False) -> Dict[str, Any]:
        current = self._read_snapshot()
        if not force:
            updated_at = self._parse_iso(current.get("updated_at"))
            if updated_at is not None and (self.now_fn() - updated_at.timestamp()) < self._snapshot_ttl_seconds():
                return current

        try:
            live_reviews = self._load_live_reviews(force=force)
            validated_runs = self._load_validated_runs()
            matched_rows, run_rows = self._build_recent_rows(live_reviews, validated_runs)
            snapshot = {
                "version": 1,
                "updated_at": self._utc_now_iso(),
                "metadata": {
                    "comparison_policy": "validated_replay_windows_only",
                    "replay_window_requirement": "validation grade must not be INSUFFICIENT_DATA",
                    "bucket_seconds": self.DECISION_BUCKET_SECONDS,
                    "live_review_source": str(self.advisor_review_path),
                    "runs_root": str(self.runs_root),
                    "global_baseline_started_at": (
                        self.performance_baseline_service.get_global_started_at().isoformat()
                        if self.performance_baseline_service is not None
                        and self.performance_baseline_service.get_global_started_at() is not None
                        else None
                    ),
                },
                "recent": matched_rows[: self._recent_limit()],
                "summary": self._build_summary(live_reviews, matched_rows, run_rows),
                "by_symbol": self._build_slice_rows(matched_rows, key_name="symbol"),
                "by_mode": self._build_slice_rows(matched_rows, key_name="mode"),
                "runs": run_rows,
                "error": None,
            }
        except Exception as exc:
            logger.warning("Advisor replay analysis refresh failed: %s", exc)
            snapshot = dict(current)
            snapshot["error"] = str(exc)
            snapshot["updated_at"] = self._utc_now_iso()
        self._write_snapshot(snapshot)
        return snapshot

    def _filtered_recent(
        self,
        rows: List[Dict[str, Any]],
        *,
        limit: int,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_mode = str(mode or "").strip().lower()
        filtered = []
        for row in rows:
            if normalized_symbol and str(row.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            if normalized_mode and str(row.get("mode") or "").strip().lower() != normalized_mode:
                continue
            filtered.append(row)
        return filtered[: max(int(limit or 0), 0)]

    def get_recent(
        self,
        *,
        limit: int = 50,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "recent": self._filtered_recent(
                list(snapshot.get("recent") or []),
                limit=limit,
                symbol=symbol,
                mode=mode,
            ),
        }

    def get_summary(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "summary": dict(snapshot.get("summary") or {}),
            "runs": list(snapshot.get("runs") or []),
        }

    def get_by_symbol(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "rows": list(snapshot.get("by_symbol") or []),
        }

    def get_by_mode(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        snapshot = self.refresh_snapshot(force=force_refresh)
        return {
            "updated_at": snapshot.get("updated_at"),
            "metadata": dict(snapshot.get("metadata") or {}),
            "error": snapshot.get("error"),
            "rows": list(snapshot.get("by_mode") or []),
        }
