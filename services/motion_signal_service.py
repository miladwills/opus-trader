"""
Motion Signal Service — Market Activity Quality Signal

Computes a composite motion quality score (0-100) for each symbol,
combining activity intensity, micro velocity, movement continuity,
and a chaos penalty.  This is a display-only signal for the operator
dashboard.  It does NOT influence entry readiness or trading logic.

Two-tier access pattern (matches PriceActionSignalService):
  - get_motion(symbol)    — cache-only read, zero I/O, safe for light path
  - compute_motion(symbol) — full computation, call from background/full path

Scoring model:
  Phase 1 — raw_activity (0-100): How much is the symbol moving?
             Based on ATR% and micro velocity.
  Phase 2 — quality (0-1): Is the movement clean or chaotic?
             Based on continuity (efficiency ratio) and chaos (reversals/spikes).
  Final   — motion_score = raw_activity * (0.3 + 0.7 * quality)
             Quality=1 → full credit.  Quality=0 → score reduced by 70%.

Label logic:
  - raw_activity < dead_threshold → Dead (nothing happening)
  - raw_activity < slow_threshold → Slow
  - quality < chaos_quality_threshold → Chaotic (active but noisy)
  - motion_score < fast_threshold → Healthy
  - else → Fast
"""

import math
import time
import logging
from typing import Any, Dict, List, Optional

from config.strategy_config import (
    MOTION_EMA_ALPHA,
    MOTION_CACHE_TTL,
)

logger = logging.getLogger(__name__)

# Activity normalization: linear ramp between these ATR% values
_ATR_DEAD = 0.0005   # Below this → activity ≈ 0
_ATR_FULL = 0.012     # Above this → activity ≈ 100

# Velocity normalization: linear ramp between these values (%/hr)
_VEL_DEAD = 0.0005
_VEL_FULL = 0.020

# Raw activity thresholds for Dead/Slow labels
_RAW_DEAD = 8.0
_RAW_SLOW = 22.0

# Quality threshold below which label becomes Chaotic
_CHAOS_QUALITY = 0.35

# Score threshold for Fast vs Healthy
_FAST_SCORE = 65.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _linear_norm(value: float, lo: float, hi: float) -> float:
    """Linearly map *value* from [lo, hi] to [0, 100], clamped."""
    if hi <= lo:
        return 0.0
    return _clamp((value - lo) / (hi - lo) * 100.0, 0.0, 100.0)


class MotionSignalService:
    """Computes and caches market motion quality signals per symbol."""

    def __init__(self, indicator_service: Any):
        self.indicator_service = indicator_service
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ema: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_motion(self, symbol: str) -> Dict[str, Any]:
        """Return last cached motion signal.  Pure dict lookup, no I/O."""
        entry = self._cache.get(symbol)
        if entry is None:
            return {}
        if time.time() - entry.get("motion_computed_at", 0) > MOTION_CACHE_TTL * 3:
            return {}
        return entry

    def compute_motion(self, symbol: str) -> Dict[str, Any]:
        """Full computation.  Uses indicator caches internally."""
        cached = self._cache.get(symbol)
        if cached and time.time() - cached.get("motion_computed_at", 0) < MOTION_CACHE_TTL:
            return cached

        try:
            result = self._compute(symbol)
        except Exception:
            logger.debug("motion_signal: computation failed for %s", symbol, exc_info=True)
            result = self._empty_result()

        self._cache[symbol] = result
        return result

    # ------------------------------------------------------------------
    # Internal computation
    # ------------------------------------------------------------------

    def _compute(self, symbol: str) -> Dict[str, Any]:
        indicators_5m = self.indicator_service.compute_indicators(symbol, "5", 200)
        indicators_1m = self.indicator_service.compute_indicators(symbol, "1", 30)
        candles_1m = self._get_candles(symbol, "1", 30)

        # Phase 1: raw activity level (0-100)
        activity = self._score_activity(indicators_5m)
        velocity = self._score_velocity(indicators_1m)
        raw_activity = activity * 0.55 + velocity * 0.45

        # Phase 2: movement quality (0-1)
        continuity = self._score_continuity(candles_1m)
        chaos_inv = self._score_chaos_inverse(candles_1m)
        quality = (continuity * 0.55 + chaos_inv * 0.45) / 100.0

        # Combine: quality scales the effective score
        raw_score = raw_activity * (0.3 + 0.7 * quality)

        # EMA smoothing
        prev = self._ema.get(symbol)
        alpha = MOTION_EMA_ALPHA
        smoothed = raw_score if prev is None else prev * (1 - alpha) + raw_score * alpha
        self._ema[symbol] = smoothed

        score = int(round(_clamp(smoothed, 0, 100)))
        label, tint = self._assign_label(score, raw_activity, quality)

        return {
            "motion_score": score,
            "motion_label": label,
            "motion_tint": tint,
            "motion_computed_at": time.time(),
        }

    # ------------------------------------------------------------------
    # Component scorers
    # ------------------------------------------------------------------

    def _score_activity(self, ind: Optional[Dict[str, Any]]) -> float:
        """Activity (0-100) from 5m ATR% amplified by volume ratio."""
        if not ind:
            return 0.0
        atr_pct = float(ind.get("atr_pct") or 0)
        vol_ratio = _clamp(float(ind.get("volume_ratio") or 1.0), 0.3, 3.0)
        base = _linear_norm(atr_pct, _ATR_DEAD, _ATR_FULL)
        vol_amp = 0.7 + 0.3 * _clamp((vol_ratio - 0.3) / 2.7, 0, 1)
        return _clamp(base * vol_amp, 0, 100)

    def _score_velocity(self, ind: Optional[Dict[str, Any]]) -> float:
        """Micro velocity (0-100) from absolute 1m price speed."""
        if not ind:
            return 0.0
        vel = abs(float(ind.get("price_velocity") or 0))
        return _linear_norm(vel, _VEL_DEAD, _VEL_FULL)

    def _score_continuity(self, candles: List[Dict[str, Any]]) -> float:
        """Efficiency ratio (0-100) over last 12 1m candles.
        High = sustained directional movement. Low = random chop.
        """
        closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
        if len(closes) < 4:
            return 0.0
        net = abs(closes[-1] - closes[0])
        path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
        if path == 0:
            return 0.0
        efficiency = net / path
        return _clamp(efficiency * 120, 0, 100)

    def _score_chaos_inverse(self, candles: List[Dict[str, Any]]) -> float:
        """Inverse chaos (0-100).  High = calm, low = chaotic.
        Penalises frequent reversals and extreme spikes.
        """
        closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
        if len(closes) < 4:
            return 50.0

        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        nonzero_changes = [ch for ch in changes if ch != 0]
        if len(nonzero_changes) < 2:
            return 50.0

        reversals = sum(
            1 for i in range(1, len(nonzero_changes))
            if nonzero_changes[i] * nonzero_changes[i - 1] < 0
        )
        reversal_rate = reversals / max(len(nonzero_changes) - 1, 1)

        ranges = []
        for c in candles:
            h = float(c.get("high", 0))
            lo = float(c.get("low", 0))
            if h > 0 and lo > 0:
                ranges.append(h - lo)
        if not ranges or len(ranges) < 3:
            return 50.0

        sorted_r = sorted(ranges)
        median_range = sorted_r[len(sorted_r) // 2]
        max_range = sorted_r[-1]
        spike_ratio = max_range / median_range if median_range > 0 else 1.0

        chaos_raw = reversal_rate * 60 + _clamp(spike_ratio - 1.5, 0, 5) * 8
        return _clamp(100 - chaos_raw, 0, 100)

    # ------------------------------------------------------------------
    # Label assignment
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_label(score: int, raw_activity: float, quality: float):
        """Assign label using both score and underlying components."""
        if raw_activity < _RAW_DEAD:
            return "Dead", "dead"
        if raw_activity < _RAW_SLOW:
            return "Slow", "slow"
        if quality < _CHAOS_QUALITY:
            return "Chaotic", "chaotic"
        if score >= _FAST_SCORE:
            return "Fast", "fast"
        return "Healthy", "healthy"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_candles(self, symbol: str, interval: str, limit: int) -> List[Dict[str, Any]]:
        """Fetch OHLCV candles via the indicator service cache."""
        try:
            raw = self.indicator_service.get_ohlcv(symbol, interval, limit)
            if raw and isinstance(raw, list):
                return raw[-12:]
            return []
        except Exception:
            return []

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "motion_score": None,
            "motion_label": None,
            "motion_tint": None,
            "motion_computed_at": time.time(),
        }
