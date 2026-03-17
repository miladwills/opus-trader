"""
Symbol Training Service

Learns conservative per-symbol adaptations from closed-trade history.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional

from config.strategy_config import (
    SYMBOL_TRAINING_ANALYSIS_INTERVAL_SEC,
    SYMBOL_TRAINING_DECAY_FACTOR,
    SYMBOL_TRAINING_FULL_CONFIDENCE_TRADES,
    SYMBOL_TRAINING_MAX_BLEND,
    SYMBOL_TRAINING_MAX_PROCESSED_IDS,
    SYMBOL_TRAINING_MAX_RECENT_OUTCOMES,
    SYMBOL_TRAINING_MIN_TRADES,
    SYMBOL_TRAINING_OPEN_CAP_MAX_MULT,
    SYMBOL_TRAINING_OPEN_CAP_MIN_MULT,
    SYMBOL_TRAINING_OUTLIER_STDDEV,
    SYMBOL_TRAINING_STEP_MAX_MULT,
    SYMBOL_TRAINING_STEP_MIN_MULT,
)
from services.lock_service import file_lock
from services.session_service import SessionService

logger = logging.getLogger(__name__)


class SymbolTrainingService:
    """
    Persist and analyze conservative per-symbol runtime training data.
    """

    VERSION = 1

    def __init__(
        self,
        data_dir: str = "storage/training",
        session_service: Optional[SessionService] = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_service = session_service or SessionService()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _file_path(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol.upper()}.json"

    def _lock_path(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol.upper()}.json.lock"

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
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

    @classmethod
    def _phase_for_trade_count(cls, total_trades: int) -> str:
        if total_trades < SYMBOL_TRAINING_MIN_TRADES:
            return "collecting"
        if total_trades < SYMBOL_TRAINING_FULL_CONFIDENCE_TRADES:
            return "learning"
        return "active"

    @staticmethod
    def _ensure_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            dt_value = value
        elif isinstance(value, str) and value:
            try:
                dt_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                dt_value = SymbolTrainingService._utc_now()
        else:
            dt_value = SymbolTrainingService._utc_now()

        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(timezone.utc)

    @classmethod
    def _normalize_symbol(cls, symbol: Any) -> str:
        return str(symbol or "").strip().upper()

    def _default_training(
        self, symbol: str, created_at: Optional[str] = None
    ) -> Dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        now_iso = created_at or self._utc_now().isoformat()
        return {
            "symbol": symbol,
            "version": self.VERSION,
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_analysis_at": None,
            "total_trades": 0,
            "training_hours": 0.0,
            "phase": "collecting",
            "confidence_score": 0.0,
            "processed_trade_ids": [],
            "recent_outcomes": [],
            "trade_outcomes": {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "avg_return": 0.0,
                "avg_win_pnl": 0.0,
                "avg_loss_pnl": 0.0,
                "profit_factor": 0.0,
            },
            "mode_performance": {},
            "session_performance": {},
            "day_of_week": {},
            "step_analysis": {
                "samples": 0,
                "buckets": [],
                "optimal_step_pct": None,
                "confidence": 0.0,
            },
            "open_cap_analysis": {
                "samples": 0,
                "buckets": [],
                "optimal_open_cap": None,
                "confidence": 0.0,
            },
            "rolling_windows": {
                "7d": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "avg_pnl": 0.0,
                    "avg_return": 0.0,
                },
                "30d": {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "avg_pnl": 0.0,
                    "avg_return": 0.0,
                },
            },
            "learned_parameters": {},
        }

    def _read_training(self, symbol: str) -> Dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        if not symbol:
            return self._default_training(symbol)

        file_path = self._file_path(symbol)
        lock_path = self._lock_path(symbol)
        if not lock_path.exists():
            lock_path.touch()

        if not file_path.exists():
            return self._default_training(symbol)

        try:
            with file_lock(lock_path, exclusive=False):
                with open(file_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                    if isinstance(data, dict):
                        data.setdefault("symbol", symbol)
                        return data
        except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
            logger.debug("[%s] Failed to read training data, using defaults", symbol)

        return self._default_training(symbol)

    def _write_training(self, symbol: str, data: Dict[str, Any]) -> None:
        symbol = self._normalize_symbol(symbol)
        if not symbol:
            return

        file_path = self._file_path(symbol)
        lock_path = self._lock_path(symbol)
        if not lock_path.exists():
            lock_path.touch()

        data = dict(data or {})
        data["symbol"] = symbol
        data["version"] = self.VERSION
        data["updated_at"] = self._utc_now().isoformat()

        try:
            with file_lock(lock_path, exclusive=True):
                fd, temp_path = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(data, handle, indent=2, ensure_ascii=False)
                    os.replace(temp_path, file_path)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
        except (IOError, OSError) as exc:
            logger.warning("[%s] Failed to write training data: %s", symbol, exc)

    def _session_key_for_trade(self, trade_dt: datetime) -> str:
        session_info = self.session_service.get_current_session(now=trade_dt)
        if not session_info.get("success"):
            return "unknown"

        overlap = session_info.get("overlap") or {}
        primary = session_info.get("primary_session") or {}
        return str(overlap.get("key") or primary.get("key") or "unknown")

    def _build_outcome(self, symbol: str, trade: Dict[str, Any]) -> Dict[str, Any]:
        trade_time = self._parse_datetime(trade.get("time"))
        realized_pnl = self._safe_float(trade.get("realized_pnl"), 0.0)
        bot_investment = self._safe_float(trade.get("bot_investment"), 0.0)
        effective_step_pct = self._safe_float(
            trade.get("effective_step_pct", trade.get("grid_step_pct")), 0.0
        )
        runtime_open_cap = self._safe_int(trade.get("runtime_open_order_cap_total"), 0)

        return {
            "id": str(
                trade.get("id")
                or f"{symbol}:{trade_time.isoformat()}:{self._safe_float(realized_pnl, 0.0)}"
            ),
            "time": trade_time.isoformat(),
            "realized_pnl": realized_pnl,
            "bot_investment": bot_investment,
            "mode": str(trade.get("bot_mode") or trade.get("mode") or "unknown").lower(),
            "range_mode": str(
                trade.get("bot_range_mode") or trade.get("range_mode") or "unknown"
            ).lower(),
            "bot_profile": str(
                trade.get("bot_profile") or trade.get("profile") or "unknown"
            ).lower(),
            "effective_step_pct": effective_step_pct if effective_step_pct > 0 else None,
            "runtime_open_order_cap_total": (
                runtime_open_cap if runtime_open_cap > 0 else None
            ),
            "fee_aware_min_step_pct": self._safe_float(
                trade.get("fee_aware_min_step_pct"), 0.0
            )
            or None,
            "atr_5m_pct": self._safe_float(trade.get("atr_5m_pct"), 0.0) or None,
            "atr_15m_pct": self._safe_float(trade.get("atr_15m_pct"), 0.0) or None,
            "regime_effective": str(trade.get("regime_effective") or "unknown").lower(),
            "session_key": self._session_key_for_trade(trade_time),
            "day_of_week": trade_time.weekday(),
            "is_weekend": trade_time.weekday() >= 5,
            "is_win": realized_pnl > 0,
        }

    def _record_trade_into_data(
        self, data: Dict[str, Any], symbol: str, trade: Dict[str, Any]
    ) -> bool:
        outcome = self._build_outcome(symbol, trade)
        trade_id = outcome["id"]

        processed_ids = self._ensure_list(data.get("processed_trade_ids"))
        if trade_id in processed_ids:
            return False

        recent_outcomes = self._ensure_list(data.get("recent_outcomes"))
        recent_outcomes.append(outcome)
        recent_outcomes = recent_outcomes[-SYMBOL_TRAINING_MAX_RECENT_OUTCOMES :]

        processed_ids.append(trade_id)
        processed_ids = processed_ids[-SYMBOL_TRAINING_MAX_PROCESSED_IDS :]

        trade_count = self._safe_int(data.get("total_trades"), 0) + 1
        data["total_trades"] = trade_count
        data["phase"] = self._phase_for_trade_count(trade_count)
        data["processed_trade_ids"] = processed_ids
        data["recent_outcomes"] = recent_outcomes
        data["updated_at"] = self._utc_now().isoformat()
        return True

    @classmethod
    def _normalized_return(cls, outcome: Dict[str, Any]) -> float:
        pnl_value = cls._safe_float(outcome.get("realized_pnl"), 0.0)
        investment = cls._safe_float(outcome.get("bot_investment"), 0.0)
        if investment > 0:
            return pnl_value / investment
        return pnl_value

    def _outlier_filtered_outcomes(
        self, outcomes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if len(outcomes) < 5:
            return list(outcomes)

        returns = [self._normalized_return(outcome) for outcome in outcomes]
        sigma = pstdev(returns)
        if sigma <= 0:
            return list(outcomes)

        center = mean(returns)
        threshold = SYMBOL_TRAINING_OUTLIER_STDDEV * sigma
        filtered = [
            outcome
            for outcome, return_value in zip(outcomes, returns)
            if abs(return_value - center) <= threshold
        ]
        return filtered or list(outcomes)

    def _age_weight(self, timestamp: Any, now: datetime) -> float:
        trade_dt = self._parse_datetime(timestamp)
        age_days = max(0.0, (now - trade_dt).total_seconds() / 86400.0)
        return SYMBOL_TRAINING_DECAY_FACTOR ** age_days

    @classmethod
    def _round_dict(cls, data: Dict[str, Any], digits: int = 6) -> Dict[str, Any]:
        rounded: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, float):
                rounded[key] = round(value, digits)
            else:
                rounded[key] = value
        return rounded

    def _aggregate_stats(self, outcomes: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        items = list(outcomes)
        if not items:
            return {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "avg_return": 0.0,
                "avg_win_pnl": 0.0,
                "avg_loss_pnl": 0.0,
                "profit_factor": 0.0,
            }

        pnls = [self._safe_float(item.get("realized_pnl"), 0.0) for item in items]
        returns = [self._normalized_return(item) for item in items]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [abs(pnl) for pnl in pnls if pnl < 0]
        total_profit = sum(wins)
        total_loss = sum(losses)
        trades = len(items)

        stats = {
            "trades": trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / trades) if trades else 0.0,
            "avg_pnl": mean(pnls) if pnls else 0.0,
            "avg_return": mean(returns) if returns else 0.0,
            "avg_win_pnl": mean(wins) if wins else 0.0,
            "avg_loss_pnl": -mean(losses) if losses else 0.0,
            "profit_factor": (
                (total_profit / total_loss)
                if total_loss > 0
                else (total_profit if total_profit > 0 else 0.0)
            ),
        }
        return self._round_dict(stats, digits=6)

    def _aggregate_grouped(
        self, outcomes: Iterable[Dict[str, Any]], key_name: str
    ) -> Dict[str, Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for outcome in outcomes:
            group_key = str(outcome.get(key_name) or "unknown")
            grouped[group_key].append(outcome)

        results = {
            key: self._aggregate_stats(group_outcomes)
            for key, group_outcomes in grouped.items()
        }
        return dict(sorted(results.items(), key=lambda item: item[0]))

    def _window_stats(
        self, outcomes: List[Dict[str, Any]], now: datetime, days: int
    ) -> Dict[str, Any]:
        cutoff = now - timedelta(days=days)
        subset = [
            outcome
            for outcome in outcomes
            if self._parse_datetime(outcome.get("time")) >= cutoff
        ]
        return self._aggregate_stats(subset)

    def _training_hours(self, outcomes: List[Dict[str, Any]]) -> float:
        if len(outcomes) < 2:
            return 0.0

        timestamps = [self._parse_datetime(outcome.get("time")) for outcome in outcomes]
        return round(
            max(timestamps).timestamp() - min(timestamps).timestamp(), 2
        ) / 3600.0

    def _stability_factor(
        self, seven_day: Dict[str, Any], thirty_day: Dict[str, Any]
    ) -> float:
        trades_30 = self._safe_int(thirty_day.get("trades"), 0)
        trades_7 = self._safe_int(seven_day.get("trades"), 0)
        if trades_30 < 10 or trades_7 < 5:
            return 0.75

        win_rate_delta = abs(
            self._safe_float(seven_day.get("win_rate"), 0.0)
            - self._safe_float(thirty_day.get("win_rate"), 0.0)
        )
        avg_return_7 = self._safe_float(seven_day.get("avg_return"), 0.0)
        avg_return_30 = self._safe_float(thirty_day.get("avg_return"), 0.0)
        return_delta = abs(avg_return_7 - avg_return_30)
        relative_return_delta = return_delta / max(abs(avg_return_30), 0.01)

        penalty = min(0.6, win_rate_delta * 1.25 + relative_return_delta * 0.20)
        return round(max(0.4, 1.0 - penalty), 6)

    def _bucket_summary(
        self,
        outcomes: List[Dict[str, Any]],
        value_key: str,
        ranges: List[Dict[str, Any]],
        output_key: str,
    ) -> Dict[str, Any]:
        now = self._utc_now()
        bucket_results: List[Dict[str, Any]] = []
        best_score: Optional[float] = None
        best_value: Optional[float] = None
        best_trades = 0

        for bucket in ranges:
            lower = bucket["min"]
            upper = bucket.get("max")
            bucket_outcomes = []
            for outcome in outcomes:
                raw_value = outcome.get(value_key)
                if raw_value is None:
                    continue
                value = self._safe_float(raw_value, 0.0)
                if value <= 0:
                    continue
                if value < lower:
                    continue
                if upper is not None and value >= upper:
                    continue
                bucket_outcomes.append(outcome)

            stats = self._aggregate_stats(bucket_outcomes)
            bucket_entry = {
                "label": bucket["label"],
                "trades": stats["trades"],
                "win_rate": stats["win_rate"],
                "avg_pnl": stats["avg_pnl"],
                output_key: None,
            }

            if bucket_outcomes:
                values = [
                    self._safe_float(outcome.get(value_key), 0.0)
                    for outcome in bucket_outcomes
                ]
                bucket_entry[output_key] = round(mean(values), 8)

            bucket_results.append(self._round_dict(bucket_entry, digits=8))

            if len(bucket_outcomes) < 5:
                continue

            weights = [
                self._age_weight(outcome.get("time"), now) for outcome in bucket_outcomes
            ]
            weighted_return = 0.0
            weighted_win_rate = 0.0
            freshness = 0.0
            total_weight = sum(weights)
            if total_weight > 0:
                weighted_return = sum(
                    self._normalized_return(outcome) * weight
                    for outcome, weight in zip(bucket_outcomes, weights)
                ) / total_weight
                weighted_win_rate = sum(
                    (1.0 if outcome.get("is_win") else 0.0) * weight
                    for outcome, weight in zip(bucket_outcomes, weights)
                ) / total_weight
                freshness = total_weight / len(weights)

            score = (
                weighted_return
                * (0.5 + weighted_win_rate)
                * freshness
                * math.log1p(len(bucket_outcomes))
            )
            if best_score is None or score > best_score:
                best_score = score
                best_trades = len(bucket_outcomes)
                best_value = bucket_entry.get(output_key)

        confidence = 0.0
        sample_count = sum(
            1
            for outcome in outcomes
            if self._safe_float(outcome.get(value_key), 0.0) > 0
        )
        if sample_count > 0 and best_value:
            confidence = min(1.0, sample_count / SYMBOL_TRAINING_FULL_CONFIDENCE_TRADES)
            confidence *= min(1.0, best_trades / max(10, SYMBOL_TRAINING_MIN_TRADES // 2))

        return {
            "samples": sample_count,
            "buckets": bucket_results,
            "optimal_value": best_value,
            "confidence": round(confidence, 6),
        }

    def _step_analysis(self, outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = self._bucket_summary(
            outcomes=outcomes,
            value_key="effective_step_pct",
            ranges=[
                {"label": "0.0000-0.0030", "min": 0.0, "max": 0.003},
                {"label": "0.0030-0.0050", "min": 0.003, "max": 0.005},
                {"label": "0.0050-0.0080", "min": 0.005, "max": 0.008},
                {"label": "0.0080-0.0120", "min": 0.008, "max": 0.012},
                {"label": "0.0120+", "min": 0.012, "max": None},
            ],
            output_key="avg_step_pct",
        )
        return {
            "samples": result["samples"],
            "buckets": result["buckets"],
            "optimal_step_pct": result["optimal_value"],
            "confidence": result["confidence"],
        }

    def _open_cap_analysis(self, outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = self._bucket_summary(
            outcomes=outcomes,
            value_key="runtime_open_order_cap_total",
            ranges=[
                {"label": "2-4", "min": 2, "max": 5},
                {"label": "5-6", "min": 5, "max": 7},
                {"label": "7-8", "min": 7, "max": 9},
                {"label": "9-10", "min": 9, "max": 11},
                {"label": "11+", "min": 11, "max": None},
            ],
            output_key="avg_open_cap",
        )
        optimal_open_cap = result["optimal_value"]
        if optimal_open_cap is not None:
            optimal_open_cap = int(round(optimal_open_cap))
        return {
            "samples": result["samples"],
            "buckets": result["buckets"],
            "optimal_open_cap": optimal_open_cap,
            "confidence": result["confidence"],
        }

    def _is_analysis_due(self, data: Dict[str, Any]) -> bool:
        last_analysis_at = data.get("last_analysis_at")
        if not last_analysis_at:
            return True

        last_analysis_dt = self._parse_datetime(last_analysis_at)
        return (
            self._utc_now() - last_analysis_dt
        ).total_seconds() >= SYMBOL_TRAINING_ANALYSIS_INTERVAL_SEC

    def record_trade_outcome(self, symbol: str, trade: Dict[str, Any]) -> None:
        symbol = self._normalize_symbol(symbol)
        if not symbol:
            return

        data = self._read_training(symbol)
        if self._record_trade_into_data(data, symbol, trade):
            self._write_training(symbol, data)
            logger.debug(
                "[%s] Training trade recorded: total_trades=%d phase=%s",
                symbol,
                self._safe_int(data.get("total_trades"), 0),
                data.get("phase"),
            )

    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        data = self._read_training(symbol)
        outcomes = self._ensure_list(data.get("recent_outcomes"))
        total_trades = self._safe_int(data.get("total_trades"), len(outcomes))
        phase = self._phase_for_trade_count(total_trades)
        now = self._utc_now()

        trade_outcomes = self._aggregate_stats(outcomes)
        mode_performance = self._aggregate_grouped(outcomes, "mode")
        session_performance = self._aggregate_grouped(outcomes, "session_key")
        day_of_week = self._aggregate_grouped(outcomes, "day_of_week")
        rolling_windows = {
            "7d": self._window_stats(outcomes, now, 7),
            "30d": self._window_stats(outcomes, now, 30),
        }

        filtered_outcomes = self._outlier_filtered_outcomes(outcomes)
        step_analysis = self._step_analysis(filtered_outcomes)
        open_cap_analysis = self._open_cap_analysis(filtered_outcomes)
        training_hours = round(self._training_hours(outcomes), 4)
        stability_factor = self._stability_factor(
            rolling_windows["7d"], rolling_windows["30d"]
        )

        sample_confidence = 0.0
        if total_trades >= SYMBOL_TRAINING_MIN_TRADES:
            sample_confidence = min(
                1.0, total_trades / SYMBOL_TRAINING_FULL_CONFIDENCE_TRADES
            )
        feature_confidence = max(
            step_analysis["confidence"],
            open_cap_analysis["confidence"],
            0.5 if total_trades >= SYMBOL_TRAINING_MIN_TRADES else 0.0,
        )
        confidence_score = 0.0
        if sample_confidence > 0:
            confidence_score = min(
                1.0,
                sample_confidence
                * (0.70 + 0.30 * stability_factor)
                * (0.75 + 0.25 * feature_confidence),
            )

        learned_parameters: Dict[str, Any] = {}
        if step_analysis["optimal_step_pct"]:
            learned_parameters["effective_step_pct"] = round(
                self._safe_float(step_analysis["optimal_step_pct"], 0.0), 8
            )
        if open_cap_analysis["optimal_open_cap"]:
            learned_parameters["runtime_open_order_cap_total"] = int(
                open_cap_analysis["optimal_open_cap"]
            )

        data.update(
            {
                "last_analysis_at": now.isoformat(),
                "phase": phase,
                "confidence_score": round(confidence_score, 6),
                "training_hours": training_hours,
                "trade_outcomes": trade_outcomes,
                "mode_performance": mode_performance,
                "session_performance": session_performance,
                "day_of_week": day_of_week,
                "step_analysis": step_analysis,
                "open_cap_analysis": open_cap_analysis,
                "rolling_windows": rolling_windows,
                "learned_parameters": learned_parameters,
            }
        )
        self._write_training(symbol, data)
        logger.info(
            "[%s] Training analysis: phase=%s trades=%d confidence=%.2f",
            symbol,
            phase,
            total_trades,
            confidence_score,
        )
        return data

    def get_adapted_parameters(
        self,
        symbol: str,
        base_config: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        context = context or {}
        if not symbol:
            return {
                "training_status": "disabled",
                "confidence": 0.0,
                "adaptations_applied": [],
                "total_trades": 0,
            }

        data = self._read_training(symbol)
        if self._is_analysis_due(data) and self._safe_int(data.get("total_trades"), 0) > 0:
            data = self.analyze_symbol(symbol)

        phase = str(data.get("phase") or "collecting")
        total_trades = self._safe_int(data.get("total_trades"), 0)
        confidence = self._safe_float(data.get("confidence_score"), 0.0)
        result: Dict[str, Any] = {
            "training_status": phase,
            "confidence": round(confidence, 6),
            "adaptations_applied": [],
            "total_trades": total_trades,
        }

        if total_trades < SYMBOL_TRAINING_MIN_TRADES or confidence <= 0:
            return result

        guard_flags = [
            "small_capital_active",
            "_small_capital_block_opening_orders",
            "_volatility_block_opening_orders",
        ]
        if any(bool(context.get(flag)) for flag in guard_flags):
            return result

        if phase == "learning":
            blend_factor = min(SYMBOL_TRAINING_MAX_BLEND, confidence * 0.30)
        elif phase == "active":
            blend_factor = min(SYMBOL_TRAINING_MAX_BLEND, confidence * SYMBOL_TRAINING_MAX_BLEND)
        else:
            blend_factor = 0.0

        if blend_factor <= 0:
            return result

        learned_parameters = data.get("learned_parameters") or {}
        base_step = self._safe_float(base_config.get("effective_step_pct"), 0.0)
        learned_step = self._safe_float(learned_parameters.get("effective_step_pct"), 0.0)
        fee_floor = self._safe_float(context.get("fee_aware_min_step_pct"), 0.0)

        if base_step > 0 and learned_step > 0:
            min_step = base_step * SYMBOL_TRAINING_STEP_MIN_MULT
            max_step = base_step * SYMBOL_TRAINING_STEP_MAX_MULT
            learned_step = max(min_step, min(max_step, learned_step))
            adapted_step = base_step + (learned_step - base_step) * blend_factor
            if fee_floor > 0:
                adapted_step = max(adapted_step, fee_floor)
            adapted_step = max(min_step, min(max_step, adapted_step))
            if abs(adapted_step - base_step) > 1e-9:
                result["effective_step_pct"] = round(adapted_step, 8)
                result["adaptations_applied"].append(
                    "effective_step_pct: "
                    f"{base_step:.6f} -> {adapted_step:.6f} "
                    f"(confidence={confidence:.2f}, blend={blend_factor:.2f})"
                )

        base_open_cap = self._safe_int(base_config.get("runtime_open_order_cap_total"), 0)
        learned_open_cap = self._safe_int(
            learned_parameters.get("runtime_open_order_cap_total"), 0
        )
        if base_open_cap > 0 and learned_open_cap > 0:
            min_cap = max(2, int(math.floor(base_open_cap * SYMBOL_TRAINING_OPEN_CAP_MIN_MULT)))
            max_cap = max(
                min_cap, int(math.ceil(base_open_cap * SYMBOL_TRAINING_OPEN_CAP_MAX_MULT))
            )
            learned_open_cap = max(min_cap, min(max_cap, learned_open_cap))
            adapted_open_cap = int(
                round(base_open_cap + (learned_open_cap - base_open_cap) * blend_factor)
            )
            adapted_open_cap = max(min_cap, min(max_cap, adapted_open_cap))
            if adapted_open_cap != base_open_cap:
                result["runtime_open_order_cap_total"] = adapted_open_cap
                result["adaptations_applied"].append(
                    "runtime_open_order_cap_total: "
                    f"{base_open_cap} -> {adapted_open_cap} "
                    f"(confidence={confidence:.2f}, blend={blend_factor:.2f})"
                )

        return result

    def get_training_data(self, symbol: str) -> Dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        data = self._read_training(symbol)
        if self._is_analysis_due(data) and self._safe_int(data.get("total_trades"), 0) > 0:
            return self.analyze_symbol(symbol)
        return data

    def get_all_training_summary(self) -> Dict[str, Any]:
        summaries: Dict[str, Any] = {}
        for file_path in sorted(self.data_dir.glob("*.json")):
            if file_path.name.endswith(".lock"):
                continue
            symbol = file_path.stem.upper()
            data = self.get_training_data(symbol)
            summaries[symbol] = {
                "symbol": symbol,
                "phase": data.get("phase"),
                "total_trades": self._safe_int(data.get("total_trades"), 0),
                "training_hours": self._safe_float(data.get("training_hours"), 0.0),
                "confidence_score": self._safe_float(data.get("confidence_score"), 0.0),
                "last_analysis_at": data.get("last_analysis_at"),
                "updated_at": data.get("updated_at"),
                "learned_parameters": data.get("learned_parameters") or {},
            }
        return summaries

    def rebuild_from_trade_logs(self, trade_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        symbol_data: Dict[str, Dict[str, Any]] = {}
        sorted_logs = sorted(
            trade_logs or [],
            key=lambda entry: str(entry.get("time") or ""),
        )

        for trade in sorted_logs:
            symbol = self._normalize_symbol(trade.get("symbol"))
            if not symbol:
                continue
            if symbol not in symbol_data:
                created_at = self._parse_datetime(trade.get("time")).isoformat()
                symbol_data[symbol] = self._default_training(symbol, created_at=created_at)
            self._record_trade_into_data(symbol_data[symbol], symbol, trade)

        for symbol, data in symbol_data.items():
            self._write_training(symbol, data)
            self.analyze_symbol(symbol)

        logger.info(
            "Training rebuild complete for %d symbols from %d trades",
            len(symbol_data),
            len(sorted_logs),
        )
        return {
            symbol: {
                "symbol": symbol,
                "total_trades": self._safe_int(data.get("total_trades"), 0),
                "phase": data.get("phase"),
            }
            for symbol, data in symbol_data.items()
        }
