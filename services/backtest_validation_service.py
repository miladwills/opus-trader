import json
import logging
import os
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.decision_snapshot_service import DecisionSnapshotService
from services.pnl_service import PnlService
from services.trade_forensics_service import TradeForensicsService

logger = logging.getLogger(__name__)


class BacktestValidationService:
    """Compare replay outputs against live historical artifacts conservatively."""

    DECISION_BUCKET_SECONDS = 900

    def __init__(
        self,
        *,
        runs_root: str = "storage/backtest_runs",
        live_trade_logs_path: str = "storage/trade_logs.json",
        live_trade_forensics_path: str = "storage/trade_forensics.jsonl",
    ) -> None:
        self.runs_root = Path(runs_root)
        self.live_trade_logs_path = Path(live_trade_logs_path)
        self.live_trade_forensics_path = Path(live_trade_forensics_path)

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

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    @staticmethod
    def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
        events = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    raw = str(line or "").strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        events.append(payload)
        except (FileNotFoundError, OSError):
            return []
        return events

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temp_path, path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _resolve_run_dir(
        self,
        *,
        run_id: Optional[str],
        run_dir: Optional[str],
    ) -> Path:
        if str(run_dir or "").strip():
            return Path(str(run_dir).strip())
        if not str(run_id or "").strip():
            raise ValueError("run_id or run_dir is required")
        return self.runs_root / str(run_id).strip()

    def _derive_snapshots(
        self,
        *,
        forensics_path: Path,
        snapshot_path: Path,
    ) -> List[Dict[str, Any]]:
        service = DecisionSnapshotService(
            trade_forensics_service=TradeForensicsService(str(forensics_path)),
            file_path=str(snapshot_path),
            lookback_seconds=315360000,
        )
        payload = service.refresh_snapshot(force=True)
        return list(payload.get("snapshots") or [])

    def _load_snapshots(
        self,
        *,
        forensics_path: Path,
        snapshot_path: Path,
    ) -> List[Dict[str, Any]]:
        payload = self._read_json(snapshot_path, {})
        snapshots = list((payload or {}).get("snapshots") or [])
        if snapshots:
            return snapshots
        return self._derive_snapshots(forensics_path=forensics_path, snapshot_path=snapshot_path)

    def _infer_window(
        self,
        *,
        results: Dict[str, Any],
        replay_snapshots: List[Dict[str, Any]],
        replay_trades: List[Dict[str, Any]],
        start_time: Optional[str],
        end_time: Optional[str],
    ) -> Dict[str, Optional[str]]:
        explicit_start = self._parse_iso(start_time)
        explicit_end = self._parse_iso(end_time)
        if explicit_start or explicit_end:
            return {
                "start_time": explicit_start.isoformat() if explicit_start else None,
                "end_time": explicit_end.isoformat() if explicit_end else None,
            }

        result_start = self._parse_iso(results.get("start_time"))
        result_end = self._parse_iso(results.get("end_time"))
        if result_start or result_end:
            return {
                "start_time": result_start.isoformat() if result_start else None,
                "end_time": result_end.isoformat() if result_end else None,
            }

        timestamps = []
        for snapshot in replay_snapshots:
            dt = self._parse_iso(snapshot.get("decision_at"))
            if dt is not None:
                timestamps.append(dt)
        for trade in replay_trades:
            dt = self._parse_iso(trade.get("time"))
            if dt is not None:
                timestamps.append(dt)
        if not timestamps:
            return {"start_time": None, "end_time": None}
        timestamps.sort()
        return {
            "start_time": timestamps[0].isoformat(),
            "end_time": timestamps[-1].isoformat(),
        }

    def _filter_trades(
        self,
        trades: List[Dict[str, Any]],
        *,
        symbol: Optional[str],
        mode: Optional[str],
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_mode = str(mode or "").strip().lower()
        filtered = []
        for trade in list(trades or []):
            trade_symbol = str(trade.get("symbol") or "").strip().upper()
            if normalized_symbol and trade_symbol != normalized_symbol:
                continue
            trade_mode = str(trade.get("bot_mode") or "").strip().lower()
            if normalized_mode:
                if not trade_mode or trade_mode != normalized_mode:
                    continue
            trade_dt = self._parse_iso(trade.get("time"))
            if start_dt and (trade_dt is None or trade_dt < start_dt):
                continue
            if end_dt and (trade_dt is None or trade_dt > end_dt):
                continue
            filtered.append(dict(trade))
        filtered.sort(key=lambda item: str(item.get("time") or ""))
        return filtered

    def _filter_snapshots(
        self,
        snapshots: List[Dict[str, Any]],
        *,
        symbol: Optional[str],
        mode: Optional[str],
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_mode = str(mode or "").strip().lower()
        filtered = []
        for snapshot in list(snapshots or []):
            snapshot_symbol = str(snapshot.get("symbol") or "").strip().upper()
            if normalized_symbol and snapshot_symbol != normalized_symbol:
                continue
            snapshot_mode = str(snapshot.get("mode") or "").strip().lower()
            if normalized_mode and snapshot_mode and snapshot_mode != normalized_mode:
                continue
            snapshot_dt = self._parse_iso(snapshot.get("decision_at") or snapshot.get("last_updated_at"))
            if start_dt and (snapshot_dt is None or snapshot_dt < start_dt):
                continue
            if end_dt and (snapshot_dt is None or snapshot_dt > end_dt):
                continue
            filtered.append(dict(snapshot))
        filtered.sort(key=lambda item: str(item.get("decision_at") or item.get("last_updated_at") or ""))
        return filtered

    def _filter_outcome_events(
        self,
        events: List[Dict[str, Any]],
        *,
        symbol: Optional[str],
        mode: Optional[str],
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_mode = str(mode or "").strip().lower()
        filtered = []
        for event in list(events or []):
            if str(event.get("event_type") or "").strip() != "realized_outcome":
                continue
            event_symbol = str(event.get("symbol") or "").strip().upper()
            if normalized_symbol and event_symbol != normalized_symbol:
                continue
            event_mode = str(event.get("mode") or "").strip().lower()
            if normalized_mode and event_mode and event_mode != normalized_mode:
                continue
            event_dt = self._parse_iso(event.get("timestamp"))
            if start_dt and (event_dt is None or event_dt < start_dt):
                continue
            if end_dt and (event_dt is None or event_dt > end_dt):
                continue
            filtered.append(dict(event))
        filtered.sort(key=lambda item: str(item.get("timestamp") or ""))
        return filtered

    @staticmethod
    def _decision_bucket_key(snapshot: Dict[str, Any]) -> Optional[str]:
        decision_at = BacktestValidationService._parse_iso(snapshot.get("decision_at"))
        if decision_at is None:
            return None
        bucket = int(decision_at.timestamp()) // BacktestValidationService.DECISION_BUCKET_SECONDS
        lifecycle = dict(snapshot.get("lifecycle") or {})
        if lifecycle.get("blocked"):
            status = "blocked"
        elif lifecycle.get("submitted"):
            status = "executed"
        else:
            status = "candidate"
        return "|".join(
            [
                str(snapshot.get("symbol") or ""),
                str(snapshot.get("mode") or ""),
                str(snapshot.get("decision_type") or ""),
                status,
                str(bucket),
            ]
        )

    def _decision_alignment(self, replay_snapshots: List[Dict[str, Any]], live_snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        replay_counts = Counter()
        live_counts = Counter()
        for snapshot in replay_snapshots:
            key = self._decision_bucket_key(snapshot)
            if key:
                replay_counts[key] += 1
        for snapshot in live_snapshots:
            key = self._decision_bucket_key(snapshot)
            if key:
                live_counts[key] += 1
        matched = 0
        for key in set(replay_counts) | set(live_counts):
            matched += min(replay_counts.get(key, 0), live_counts.get(key, 0))
        replay_total = sum(replay_counts.values())
        live_total = sum(live_counts.values())
        denominator = max(replay_total, live_total, 1)
        return {
            "replay_bucketed_decisions": replay_total,
            "live_bucketed_decisions": live_total,
            "matched_bucket_events": matched,
            "alignment_rate": round(matched / denominator, 4),
        }

    @staticmethod
    def _median_pnl(trades: List[Dict[str, Any]]) -> Optional[float]:
        values = [
            float(trade.get("realized_pnl") or 0.0)
            for trade in list(trades or [])
        ]
        if not values:
            return None
        return round(statistics.median(values), 8)

    @staticmethod
    def _avg_pnl(trades: List[Dict[str, Any]]) -> Optional[float]:
        if not trades:
            return None
        total = sum(float(trade.get("realized_pnl") or 0.0) for trade in trades)
        return round(total / len(trades), 8)

    @staticmethod
    def _hold_time_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
        values = []
        for event in list(events or []):
            hold_time = BacktestValidationService._safe_float(
                (event.get("exit") or {}).get("hold_time_sec"),
                None,
            )
            if hold_time is not None:
                values.append(float(hold_time))
        if not values:
            return {"count": 0, "avg_hold_time_sec": None, "median_hold_time_sec": None}
        return {
            "count": len(values),
            "avg_hold_time_sec": round(sum(values) / len(values), 4),
            "median_hold_time_sec": round(statistics.median(values), 4),
        }

    @staticmethod
    def _exit_reason_mix(events: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {}
        for event in list(events or []):
            reason = str((event.get("exit") or {}).get("close_reason") or "unknown").strip() or "unknown"
            counts[reason] = int(counts.get(reason, 0) or 0) + 1
        return counts

    @staticmethod
    def _mix_distance(left: Dict[str, int], right: Dict[str, int]) -> Dict[str, Any]:
        categories = sorted(set(left) | set(right))
        total_gap = 0
        by_reason = {}
        for reason in categories:
            gap = abs(int(left.get(reason, 0) or 0) - int(right.get(reason, 0) or 0))
            total_gap += gap
            by_reason[reason] = gap
        return {"total_gap": total_gap, "by_reason_gap": by_reason}

    @staticmethod
    def _diff(left: Optional[float], right: Optional[float]) -> Optional[float]:
        if left is None or right is None:
            return None
        return round(left - right, 8)

    def _mismatch_categories(
        self,
        *,
        decision_count_diff: int,
        trade_count_diff: int,
        blocked_count_diff: int,
        exit_reason_gap: int,
        avg_hold_time_diff_sec: Optional[float],
        avg_pnl_diff: Optional[float],
        insufficient_live_data: bool,
    ) -> List[Dict[str, Any]]:
        categories = []
        if insufficient_live_data:
            categories.append(
                {
                    "type": "insufficient_live_reference",
                    "severity": "high",
                    "summary": "Live comparison data is too sparse for a strong realism claim.",
                }
            )
        if trade_count_diff != 0:
            categories.append(
                {
                    "type": "entry_count_mismatch",
                    "severity": "medium" if abs(trade_count_diff) <= 1 else "high",
                    "summary": f"Replay/live closed trade counts differ by {trade_count_diff}.",
                }
            )
        if decision_count_diff != 0:
            categories.append(
                {
                    "type": "decision_count_mismatch",
                    "severity": "medium",
                    "summary": f"Replay/live decision counts differ by {decision_count_diff}.",
                }
            )
        if blocked_count_diff != 0:
            categories.append(
                {
                    "type": "blocked_skip_mismatch",
                    "severity": "medium",
                    "summary": f"Replay/live blocked decision counts differ by {blocked_count_diff}.",
                }
            )
        if exit_reason_gap > 0:
            categories.append(
                {
                    "type": "exit_reason_mismatch",
                    "severity": "medium",
                    "summary": f"Replay/live exit-reason mix gap is {exit_reason_gap}.",
                }
            )
        if avg_hold_time_diff_sec is not None and abs(avg_hold_time_diff_sec) > 900:
            categories.append(
                {
                    "type": "hold_time_mismatch",
                    "severity": "medium",
                    "summary": f"Average hold time differs by {round(avg_hold_time_diff_sec, 2)} seconds.",
                }
            )
        if avg_pnl_diff is not None and abs(avg_pnl_diff) > 0.0:
            categories.append(
                {
                    "type": "pnl_distribution_mismatch",
                    "severity": "low",
                    "summary": f"Average realized PnL differs by {round(avg_pnl_diff, 8)} per trade.",
                }
            )
        return categories

    def _realism_grade(
        self,
        *,
        replay_trade_count: int,
        live_trade_count: int,
        replay_decision_count: int,
        live_decision_count: int,
        replay_blocked_count: int,
        live_blocked_count: int,
        win_rate_diff: Optional[float],
        profit_factor_diff: Optional[float],
        alignment_rate: float,
        insufficient_live_data: bool,
    ) -> Dict[str, Any]:
        if insufficient_live_data:
            return {
                "score": None,
                "grade": "INSUFFICIENT_DATA",
                "label": "reference_limited",
            }
        penalty = 0.0
        penalty += min(25.0, 25.0 * abs(replay_trade_count - live_trade_count) / max(live_trade_count, 1))
        penalty += min(20.0, 20.0 * abs(replay_decision_count - live_decision_count) / max(live_decision_count, 1))
        penalty += min(10.0, 10.0 * abs(replay_blocked_count - live_blocked_count) / max(live_blocked_count or live_decision_count or 1, 1))
        if win_rate_diff is not None:
            penalty += min(15.0, abs(win_rate_diff) / 2.0)
        if profit_factor_diff is not None:
            penalty += min(15.0, abs(profit_factor_diff) * 5.0)
        penalty += min(15.0, (1.0 - max(min(alignment_rate, 1.0), 0.0)) * 15.0)
        score = max(0.0, round(100.0 - penalty, 2))
        if score >= 85.0:
            grade = "A"
        elif score >= 70.0:
            grade = "B"
        elif score >= 55.0:
            grade = "C"
        else:
            grade = "D"
        return {"score": score, "grade": grade, "label": "approximation_quality"}

    def _assumption_sensitivity(
        self,
        *,
        replay_trades: List[Dict[str, Any]],
        results: Dict[str, Any],
    ) -> Dict[str, Any]:
        assumptions = dict(results.get("assumptions") or {})
        fees = dict(assumptions.get("fees") or {})
        taker_fee_bps = self._safe_float(fees.get("taker_fee_bps"), None)
        scenarios = [
            {"name": "baseline", "extra_fee_bps": 0.0, "extra_slippage_bps": 0.0},
            {"name": "slippage_plus_2_5bps", "extra_fee_bps": 0.0, "extra_slippage_bps": 2.5},
            {"name": "conservative_costs", "extra_fee_bps": 1.0, "extra_slippage_bps": 5.0},
        ]
        net_pnl = sum(float(trade.get("realized_pnl") or 0.0) for trade in replay_trades)
        sensitivity_rows = []
        unresolved_trades = 0
        for scenario in scenarios:
            extra_cost = 0.0
            for trade in replay_trades:
                total_fee = self._safe_float(trade.get("total_fee"), None)
                if total_fee is None or taker_fee_bps in (None, 0.0):
                    unresolved_trades += 1
                    continue
                turnover = abs(float(total_fee)) / (float(taker_fee_bps) / 10000.0)
                extra_bps = float(scenario["extra_fee_bps"]) + float(scenario["extra_slippage_bps"])
                extra_cost += turnover * (extra_bps / 10000.0)
            sensitivity_rows.append(
                {
                    **scenario,
                    "adjusted_net_pnl": round(net_pnl - extra_cost, 8),
                    "delta_vs_baseline": round(-extra_cost, 8),
                }
            )
        return {
            "base_net_pnl": round(net_pnl, 8),
            "taker_fee_bps_reference": taker_fee_bps,
            "scenarios": sensitivity_rows,
            "unresolved_trade_count": unresolved_trades,
            "note": (
                "Sensitivity is approximate and derived from replay turnover implied by recorded fees, "
                "not from a full rerun."
            ),
        }

    def validate_run(
        self,
        *,
        run_id: Optional[str] = None,
        run_dir: Optional[str] = None,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        target_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        results_path = target_run_dir / "results.json"
        if not results_path.exists():
            raise FileNotFoundError(f"results.json not found under {target_run_dir}")

        results = self._read_json(results_path, {})
        if not isinstance(results, dict) or not results:
            raise ValueError(f"results.json is empty or invalid under {target_run_dir}")
        replay_trade_logs = self._read_json(target_run_dir / "trade_logs.json", [])
        replay_forensics = self._read_jsonl(target_run_dir / "trade_forensics.jsonl")
        replay_snapshots = self._load_snapshots(
            forensics_path=target_run_dir / "trade_forensics.jsonl",
            snapshot_path=target_run_dir / "decision_snapshots.json",
        )

        comparison_symbol = str(symbol or results.get("symbol") or "").strip().upper() or None
        comparison_mode = str(mode or results.get("mode") or "").strip().lower() or None
        window = self._infer_window(
            results=results,
            replay_snapshots=replay_snapshots,
            replay_trades=replay_trade_logs,
            start_time=start_time,
            end_time=end_time,
        )
        start_dt = self._parse_iso(window.get("start_time"))
        end_dt = self._parse_iso(window.get("end_time"))

        live_trade_logs = self._read_json(self.live_trade_logs_path, [])
        live_forensics = self._read_jsonl(self.live_trade_forensics_path)
        live_snapshot_path = target_run_dir / "validation_live_decision_snapshots.json"
        live_snapshots = self._load_snapshots(
            forensics_path=self.live_trade_forensics_path,
            snapshot_path=live_snapshot_path,
        )

        replay_trades = self._filter_trades(
            replay_trade_logs,
            symbol=comparison_symbol,
            mode=comparison_mode,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        live_trades = self._filter_trades(
            live_trade_logs,
            symbol=comparison_symbol,
            mode=comparison_mode,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        replay_decisions = self._filter_snapshots(
            replay_snapshots,
            symbol=comparison_symbol,
            mode=comparison_mode,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        live_decisions = self._filter_snapshots(
            live_snapshots,
            symbol=comparison_symbol,
            mode=comparison_mode,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        replay_outcomes = self._filter_outcome_events(
            replay_forensics,
            symbol=comparison_symbol,
            mode=comparison_mode,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        live_outcomes = self._filter_outcome_events(
            live_forensics,
            symbol=comparison_symbol,
            mode=comparison_mode,
            start_dt=start_dt,
            end_dt=end_dt,
        )

        replay_trade_stats = PnlService._build_trade_window_stats(replay_trades)
        live_trade_stats = PnlService._build_trade_window_stats(live_trades)
        replay_hold = self._hold_time_summary(replay_outcomes)
        live_hold = self._hold_time_summary(live_outcomes)
        replay_exit_mix = self._exit_reason_mix(replay_outcomes)
        live_exit_mix = self._exit_reason_mix(live_outcomes)
        exit_gap = self._mix_distance(replay_exit_mix, live_exit_mix)
        alignment = self._decision_alignment(replay_decisions, live_decisions)

        replay_blocked = sum(
            1 for snapshot in replay_decisions if (snapshot.get("lifecycle") or {}).get("blocked")
        )
        live_blocked = sum(
            1 for snapshot in live_decisions if (snapshot.get("lifecycle") or {}).get("blocked")
        )
        replay_executed = sum(
            1 for snapshot in replay_decisions if (snapshot.get("lifecycle") or {}).get("submitted")
        )
        live_executed = sum(
            1 for snapshot in live_decisions if (snapshot.get("lifecycle") or {}).get("submitted")
        )
        replay_avg_pnl = self._avg_pnl(replay_trades)
        live_avg_pnl = self._avg_pnl(live_trades)
        replay_median_pnl = self._median_pnl(replay_trades)
        live_median_pnl = self._median_pnl(live_trades)
        avg_hold_diff = self._diff(
            replay_hold.get("avg_hold_time_sec"),
            live_hold.get("avg_hold_time_sec"),
        )
        insufficient_live_data = len(live_trades) == 0 and len(live_decisions) == 0

        comparison = {
            "window": window,
            "symbol": comparison_symbol,
            "mode": comparison_mode,
            "comparison_unit": (
                "aggregate trades plus 15m bucketed decision/status alignment within the same symbol/mode/time window"
            ),
            "count_metrics": {
                "replay_trade_count": len(replay_trades),
                "live_trade_count": len(live_trades),
                "trade_count_diff": len(replay_trades) - len(live_trades),
                "replay_decision_count": len(replay_decisions),
                "live_decision_count": len(live_decisions),
                "decision_count_diff": len(replay_decisions) - len(live_decisions),
                "replay_blocked_count": replay_blocked,
                "live_blocked_count": live_blocked,
                "blocked_count_diff": replay_blocked - live_blocked,
                "replay_executed_decision_count": replay_executed,
                "live_executed_decision_count": live_executed,
                "executed_decision_diff": replay_executed - live_executed,
            },
            "trade_metrics": {
                "replay": {
                    **replay_trade_stats,
                    "avg_pnl": replay_avg_pnl,
                    "median_pnl": replay_median_pnl,
                },
                "live": {
                    **live_trade_stats,
                    "avg_pnl": live_avg_pnl,
                    "median_pnl": live_median_pnl,
                },
                "diff": {
                    "win_rate": self._diff(
                        self._safe_float(replay_trade_stats.get("win_rate"), None),
                        self._safe_float(live_trade_stats.get("win_rate"), None),
                    ),
                    "profit_factor": self._diff(
                        self._safe_float(replay_trade_stats.get("profit_factor"), None),
                        self._safe_float(live_trade_stats.get("profit_factor"), None),
                    ),
                    "payoff_ratio": self._diff(
                        self._safe_float(replay_trade_stats.get("payoff_ratio"), None),
                        self._safe_float(live_trade_stats.get("payoff_ratio"), None),
                    ),
                    "avg_pnl": self._diff(replay_avg_pnl, live_avg_pnl),
                    "median_pnl": self._diff(replay_median_pnl, live_median_pnl),
                },
            },
            "hold_time_metrics": {
                "replay": replay_hold,
                "live": live_hold,
                "diff": {
                    "avg_hold_time_sec": avg_hold_diff,
                    "median_hold_time_sec": self._diff(
                        replay_hold.get("median_hold_time_sec"),
                        live_hold.get("median_hold_time_sec"),
                    ),
                },
            },
            "exit_reason_metrics": {
                "replay": replay_exit_mix,
                "live": live_exit_mix,
                "diff": exit_gap,
            },
            "decision_alignment": alignment,
            "reference_quality": {
                "insufficient_live_data": insufficient_live_data,
                "live_trade_count": len(live_trades),
                "live_decision_count": len(live_decisions),
                "live_outcome_events": len(live_outcomes),
                "unresolved_live_trade_count": sum(
                    1
                    for trade in live_trades
                    if str(trade.get("attribution_source") or "").strip().lower()
                    in {
                        "unattributed",
                        "ambiguous_symbol",
                        "explicit_order_link_id_unmapped",
                        "order_link_id_unresolved",
                    }
                ),
            },
        }
        comparison["mismatch_categories"] = self._mismatch_categories(
            decision_count_diff=comparison["count_metrics"]["decision_count_diff"],
            trade_count_diff=comparison["count_metrics"]["trade_count_diff"],
            blocked_count_diff=comparison["count_metrics"]["blocked_count_diff"],
            exit_reason_gap=exit_gap["total_gap"],
            avg_hold_time_diff_sec=avg_hold_diff,
            avg_pnl_diff=comparison["trade_metrics"]["diff"]["avg_pnl"],
            insufficient_live_data=insufficient_live_data,
        )
        comparison["realism"] = self._realism_grade(
            replay_trade_count=len(replay_trades),
            live_trade_count=len(live_trades),
            replay_decision_count=len(replay_decisions),
            live_decision_count=len(live_decisions),
            replay_blocked_count=replay_blocked,
            live_blocked_count=live_blocked,
            win_rate_diff=comparison["trade_metrics"]["diff"]["win_rate"],
            profit_factor_diff=comparison["trade_metrics"]["diff"]["profit_factor"],
            alignment_rate=alignment["alignment_rate"],
            insufficient_live_data=insufficient_live_data,
        )

        payload = {
            "validated_at": self._utc_now_iso(),
            "run_id": str(results.get("run_id") or target_run_dir.name),
            "run_dir": str(target_run_dir),
            "status": "ok",
            "comparison": comparison,
            "sensitivity": self._assumption_sensitivity(
                replay_trades=replay_trades,
                results=results,
            ),
            "limitations": [
                "validation is correlational and window-based, not a one-to-one trade truth match",
                "decision timing is bucketed to 15m to avoid overclaiming exact timestamp parity",
                "live data gaps or ambiguous attribution lower confidence instead of forcing a match",
            ],
            "artifacts": {
                "replay_results": str(results_path),
                "replay_trade_logs": str(target_run_dir / "trade_logs.json"),
                "replay_forensics": str(target_run_dir / "trade_forensics.jsonl"),
                "replay_decision_snapshots": str(target_run_dir / "decision_snapshots.json"),
                "live_trade_logs": str(self.live_trade_logs_path),
                "live_trade_forensics": str(self.live_trade_forensics_path),
                "validation": str(target_run_dir / "validation.json"),
            },
        }
        if persist:
            self._write_json(target_run_dir / "validation.json", payload)
        return payload

    def get_recent_validations(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        validations = []
        if not self.runs_root.exists():
            return []
        for path in sorted(self.runs_root.glob("*/validation.json"), reverse=True):
            payload = self._read_json(path, {})
            if not payload:
                continue
            comparison = dict(payload.get("comparison") or {})
            validations.append(
                {
                    "run_id": payload.get("run_id") or path.parent.name,
                    "validated_at": payload.get("validated_at"),
                    "symbol": comparison.get("symbol"),
                    "mode": comparison.get("mode"),
                    "grade": ((comparison.get("realism") or {}).get("grade")),
                    "score": ((comparison.get("realism") or {}).get("score")),
                    "trade_count_diff": ((comparison.get("count_metrics") or {}).get("trade_count_diff")),
                    "decision_count_diff": ((comparison.get("count_metrics") or {}).get("decision_count_diff")),
                    "path": str(path),
                }
            )
        validations.sort(key=lambda item: str(item.get("validated_at") or ""), reverse=True)
        return validations[: max(int(limit or 0), 0)]

    def get_validation_summary(self, *, limit: int = 50) -> Dict[str, Any]:
        recent = self.get_recent_validations(limit=limit)
        grades = Counter()
        scores = []
        for item in recent:
            grade = str(item.get("grade") or "").strip()
            if grade:
                grades[grade] += 1
            score = self._safe_float(item.get("score"), None)
            if score is not None:
                scores.append(float(score))
        return {
            "total_validation_runs": len(recent),
            "grade_counts": dict(grades),
            "average_realism_score": round(sum(scores) / len(scores), 4) if scores else None,
            "recent": recent[:10],
        }
