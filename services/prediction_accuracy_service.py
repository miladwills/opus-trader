"""
Prediction Accuracy Ledger Service

Logs every prediction vs actual outcome.
Tracks rolling accuracy per signal and score bucket.
Foundation for future calibration of all prediction signals.
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.strategy_config import (
    PREDICTION_ACCURACY_LEDGER_ENABLED,
    PREDICTION_ACCURACY_LEDGER_FILE,
)

logger = logging.getLogger(__name__)

_RECORD_TYPE_PREDICTION = "prediction"
_RECORD_TYPE_CLOSING = "closing"


class PredictionAccuracyService:
    """
    Append-only ledger for tracking prediction accuracy over time.

    Each prediction is recorded when made, then closed when the outcome is known.
    Accuracy statistics are computed by matching predictions to closings by prediction_id.
    """

    def __init__(self, file_path: Optional[str] = None) -> None:
        self.file_path = Path(file_path or PREDICTION_ACCURACY_LEDGER_FILE)
        self.lock_path = Path(str(self.file_path) + ".lock")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self.file_path.touch()

    @staticmethod
    def enabled() -> bool:
        return bool(PREDICTION_ACCURACY_LEDGER_ENABLED)

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
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

    def _append_line(self, record: Dict[str, Any]) -> bool:
        """Append a single JSON record to the ledger file."""
        try:
            from services.lock_service import file_lock

            with file_lock(self.lock_path, exclusive=True):
                with open(self.file_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except ImportError:
            # Fallback without lock if lock_service unavailable
            try:
                with open(self.file_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                return True
            except Exception as exc:
                logger.warning("Prediction accuracy ledger write failed: %s", exc)
                return False
        except Exception as exc:
            logger.warning("Prediction accuracy ledger write failed: %s", exc)
            return False

    def record_prediction(
        self,
        symbol: str,
        direction: str,
        score: float,
        confidence: float,
        top_components: List[str],
        prediction_id: str,
        signal_name: Optional[str] = None,
        score_bucket: Optional[str] = None,
    ) -> bool:
        """
        Record a new prediction entry.

        Args:
            symbol: Trading symbol (e.g. "BTCUSDT")
            direction: Predicted direction ("long", "short", "neutral")
            score: Numeric prediction score
            confidence: Confidence level 0.0-1.0
            top_components: List of top contributing signal components
            prediction_id: Unique ID for matching to closing record
            signal_name: Optional signal category name for grouped stats
            score_bucket: Optional score bucket label (e.g. "high", "medium", "low")

        Returns:
            True if successfully written, False otherwise
        """
        if not self.enabled():
            return False

        record: Dict[str, Any] = {
            "record_type": _RECORD_TYPE_PREDICTION,
            "prediction_id": str(prediction_id or "").strip(),
            "symbol": str(symbol or "").strip().upper(),
            "timestamp": self._utc_now_iso(),
            "direction": str(direction or "").strip().lower(),
            "score": round(self._safe_float(score), 6),
            "confidence": round(self._safe_float(confidence), 6),
            "top_components": list(top_components or [])[:10],
        }

        if signal_name:
            record["signal_name"] = str(signal_name).strip()
        if score_bucket:
            record["score_bucket"] = str(score_bucket).strip()

        if not record["prediction_id"]:
            logger.warning("record_prediction called with empty prediction_id — skipping")
            return False

        ok = self._append_line(record)
        if ok:
            logger.debug(
                "[%s] Prediction recorded: id=%s dir=%s score=%.3f confidence=%.3f",
                record["symbol"],
                prediction_id,
                direction,
                score,
                confidence,
            )
        return ok

    def close_prediction(
        self,
        prediction_id: str,
        actual_pnl: float,
        actual_direction: str,
        predicted_direction: Optional[str] = None,
    ) -> bool:
        """
        Record the actual outcome of a prediction.

        Args:
            prediction_id: Matches the ID from record_prediction
            actual_pnl: Realized PnL from the trade
            actual_direction: Actual direction of price move ("long", "short")
            predicted_direction: If provided, used to compute was_correct directly.
                                  Otherwise was_correct is derived from actual_pnl > 0.

        Returns:
            True if successfully written, False otherwise
        """
        if not self.enabled():
            return False

        prediction_id = str(prediction_id or "").strip()
        if not prediction_id:
            logger.warning("close_prediction called with empty prediction_id — skipping")
            return False

        actual_direction_norm = str(actual_direction or "").strip().lower()
        actual_pnl_float = self._safe_float(actual_pnl)

        if predicted_direction is not None:
            was_correct = str(predicted_direction).strip().lower() == actual_direction_norm
        else:
            was_correct = actual_pnl_float > 0

        record: Dict[str, Any] = {
            "record_type": _RECORD_TYPE_CLOSING,
            "prediction_id": prediction_id,
            "actual_pnl": round(actual_pnl_float, 8),
            "actual_direction": actual_direction_norm,
            "was_correct": was_correct,
            "closed_at": self._utc_now_iso(),
        }

        ok = self._append_line(record)
        if ok:
            logger.debug(
                "Prediction closed: id=%s pnl=%.4f correct=%s",
                prediction_id,
                actual_pnl_float,
                was_correct,
            )
        return ok

    def _read_all_records(self) -> List[Dict[str, Any]]:
        """Read all records from the ledger file."""
        records: List[Dict[str, Any]] = []
        if not self.file_path.exists():
            return records
        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    raw = str(line or "").strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                        records.append(record)
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning("Prediction accuracy ledger read failed: %s", exc)
        return records

    def get_accuracy_stats(
        self,
        signal_name: Optional[str] = None,
        score_bucket: Optional[str] = None,
        lookback_hours: int = 168,
    ) -> Dict[str, Any]:
        """
        Compute rolling accuracy statistics from the ledger.

        Args:
            signal_name: Filter by signal name (optional)
            score_bucket: Filter by score bucket label (optional)
            lookback_hours: Only include predictions from this many hours ago (default 168 = 7 days)

        Returns:
            Dict with:
              total_predictions: int
              closed_predictions: int
              correct_count: int
              accuracy_pct: float (0-100)
              avg_pnl_when_correct: float
              avg_pnl_when_wrong: float
              filters_applied: dict
        """
        if not self.enabled():
            return {
                "total_predictions": 0,
                "closed_predictions": 0,
                "correct_count": 0,
                "accuracy_pct": 0.0,
                "avg_pnl_when_correct": 0.0,
                "avg_pnl_when_wrong": 0.0,
                "filters_applied": {},
                "disabled": True,
            }

        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))
        all_records = self._read_all_records()

        # Separate predictions and closings
        predictions: Dict[str, Dict[str, Any]] = {}
        closings: Dict[str, Dict[str, Any]] = {}

        for record in all_records:
            record_type = record.get("record_type")
            pred_id = str(record.get("prediction_id") or "").strip()
            if not pred_id:
                continue

            if record_type == _RECORD_TYPE_PREDICTION:
                # Apply lookback filter on prediction timestamp
                ts = self._parse_iso(record.get("timestamp"))
                if ts is None or ts < cutoff_dt:
                    continue

                # Apply optional signal_name filter
                if signal_name and record.get("signal_name") != signal_name:
                    continue

                # Apply optional score_bucket filter
                if score_bucket and record.get("score_bucket") != score_bucket:
                    continue

                # Latest prediction for an ID wins
                predictions[pred_id] = record

            elif record_type == _RECORD_TYPE_CLOSING:
                # Latest closing for an ID wins
                closings[pred_id] = record

        # Match predictions to closings
        total_predictions = len(predictions)
        pnl_correct: List[float] = []
        pnl_wrong: List[float] = []
        correct_count = 0

        for pred_id, prediction in predictions.items():
            closing = closings.get(pred_id)
            if closing is None:
                continue

            pnl = self._safe_float(closing.get("actual_pnl"))
            was_correct = bool(closing.get("was_correct"))

            if was_correct:
                correct_count += 1
                pnl_correct.append(pnl)
            else:
                pnl_wrong.append(pnl)

        closed_predictions = len(pnl_correct) + len(pnl_wrong)
        accuracy_pct = (correct_count / closed_predictions * 100.0) if closed_predictions > 0 else 0.0
        avg_pnl_correct = (sum(pnl_correct) / len(pnl_correct)) if pnl_correct else 0.0
        avg_pnl_wrong = (sum(pnl_wrong) / len(pnl_wrong)) if pnl_wrong else 0.0

        filters_applied: Dict[str, Any] = {"lookback_hours": lookback_hours}
        if signal_name:
            filters_applied["signal_name"] = signal_name
        if score_bucket:
            filters_applied["score_bucket"] = score_bucket

        return {
            "total_predictions": total_predictions,
            "closed_predictions": closed_predictions,
            "correct_count": correct_count,
            "accuracy_pct": round(accuracy_pct, 4),
            "avg_pnl_when_correct": round(avg_pnl_correct, 8),
            "avg_pnl_when_wrong": round(avg_pnl_wrong, 8),
            "filters_applied": filters_applied,
        }
