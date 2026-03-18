"""
Bybit Control Center - Price Prediction Service

Advanced price prediction using:
- Chart pattern recognition (double top/bottom, H&S, triangles, flags, channels)
- Support/Resistance detection with strength scoring
- RSI/MACD divergence detection (regular + hidden)
- Price action analysis (HH/HL, LH/LL trend structure)
- Multi-timeframe alignment scoring
"""

from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math

from services.indicator_service import IndicatorService
from services.bybit_client import BybitClient
from config.strategy_config import (
    PATTERN_LOOKBACK_CANDLES,
    PATTERN_MIN_CONFIDENCE,
    DOUBLE_TOP_BOTTOM_TOLERANCE,
    TRIANGLE_SLOPE_THRESHOLD,
    SR_TOUCH_THRESHOLD_PCT,
    SR_MIN_TOUCHES,
    SR_LOOKBACK_CANDLES,
    SR_PROXIMITY_THRESHOLD,
    DIVERGENCE_LOOKBACK,
    DIVERGENCE_MIN_SWING_SIZE,
    MTF_TIMEFRAMES,
    MTF_WEIGHTS,
    STRONG_LONG_THRESHOLD,
    LONG_THRESHOLD,
    NEUTRAL_BAND,
    SHORT_THRESHOLD,
    STRONG_SHORT_THRESHOLD,
    # New deep analysis settings
    PREDICTION_CANDLE_LIMIT,
    PREDICTION_DEEP_ANALYSIS,
    LONG_TERM_LOOKBACK,
    LONG_TERM_TREND_WEIGHT,
    TREND_DURATION_WEIGHT,
    HIGHER_TF_BIAS_WEIGHT,
    HIGHER_TF_INTERVALS,
    HIGHER_TF_CANDLE_LIMIT,
    # Score normalization & confidence calibration (2026-01-10)
    PREDICTION_MAX_POSSIBLE_ABS,
    PREDICTION_NORM_STRONG_THRESHOLD,
    PREDICTION_NORM_MODERATE_THRESHOLD,
    PREDICTION_CONFIDENCE_MAGNITUDE_WEIGHT,
    PREDICTION_CONFIDENCE_AGREEMENT_WEIGHT,
    PREDICTION_NEUTRAL_CONFIDENCE_CAP,
    PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES,
    PREDICTION_LABEL_HYSTERESIS,
    # Strong signal safeguards (2026-01-10)
    MIN_STRONG_SIGNAL_CONSENSUS,
    PREDICTION_HYSTERESIS_LONG_EXIT,
    PREDICTION_HYSTERESIS_SHORT_EXIT,
    PREDICTION_HYSTERESIS_STRONG_LONG_EXIT,
    PREDICTION_HYSTERESIS_STRONG_SHORT_EXIT,
    STRONG_CONFIRMATION_TIMEFRAMES,
    STRONG_CONFIRMATION_REQUIRED_COUNT,
    MIN_STRONG_VOLUME_USDT,
    # Feature 3D: S/R Strength Decay
    SR_STRENGTH_DECAY_ENABLED,
    SR_RECENCY_HALF_LIFE_CANDLES,
    SR_BREAK_PENALTY_FACTOR,
    # Feature 3B: Divergence Duration Tracking
    DIVERGENCE_DURATION_TRACKING_ENABLED,
    DIVERGENCE_FRESH_MAX_CANDLES,
    DIVERGENCE_AGED_CANDLES,
    DIVERGENCE_AGED_WEIGHT_MULT,
    # Feature 3C: MTF Confluence Scoring
    MTF_CONFLUENCE_SCORING_ENABLED,
    MTF_CONFLUENCE_MAX_SCORE,
    # Feature 3A: Pattern Context Weighting
    PATTERN_CONTEXT_WEIGHTING_ENABLED,
    PATTERN_CHOP_CONFIDENCE_MULT,
    PATTERN_HVN_CONFIDENCE_BOOST,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Signal:
    """Individual signal contribution to prediction."""
    name: str
    direction: str  # "bullish", "bearish", "neutral"
    strength: int  # 1-10
    timeframe: str
    description: str


@dataclass
class Zone:
    """Entry/Exit zone recommendation based on S/R."""
    price_low: float
    price_high: float
    zone_type: str  # "support", "resistance", "entry", "take_profit"
    strength: int  # 1-10


@dataclass
class PredictionResult:
    """Unified prediction output with deep historical analysis."""
    direction: str  # STRONG_LONG, LONG, NEUTRAL, SHORT, STRONG_SHORT
    confidence: int  # 0-100
    score: float  # Normalized score (range: -100 to +100) for label decisions
    signals: List[Signal] = field(default_factory=list)
    entry_zones: List[Zone] = field(default_factory=list)
    pattern_signals: Dict[str, Any] = field(default_factory=dict)
    divergence_signals: Dict[str, Any] = field(default_factory=dict)
    sr_levels: Dict[str, Any] = field(default_factory=dict)
    trend_structure: Dict[str, Any] = field(default_factory=dict)
    # NEW: Deep analysis fields
    long_term_analysis: Dict[str, Any] = field(default_factory=dict)
    trend_duration: Dict[str, Any] = field(default_factory=dict)
    higher_tf_bias: Dict[str, Any] = field(default_factory=dict)
    candles_analyzed: int = 0
    timeframe_alignment: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Score normalization & confidence debug fields (2026-01-10)
    score_raw: float = 0.0  # Original unbounded sum (for debugging)
    score_norm: float = 0.0  # Normalized score [-100, +100]
    magnitude_conf: float = 0.0  # Confidence from score magnitude
    agreement_conf: float = 0.0  # Confidence from signal agreement
    top_components: List[Tuple[str, float]] = field(default_factory=list)  # Top 3 by |score|


# =============================================================================
# Pattern Detector
# =============================================================================

class PatternDetector:
    """Detect chart patterns from candle data."""

    def __init__(
        self,
        lookback: int = 50,
        min_confidence: float = 0.60,
        double_top_tolerance: float = 0.015,
        triangle_slope_threshold: float = 0.0002,
    ):
        self.lookback = lookback
        self.min_confidence = min_confidence
        self.double_top_tolerance = double_top_tolerance
        self.triangle_slope_threshold = triangle_slope_threshold

    def detect_all_patterns(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect all chart patterns and return findings."""
        if len(candles) < 20:
            return {}

        patterns = {}

        # Detect double top/bottom
        double_top = self._detect_double_top(candles)
        if double_top:
            patterns["double_top"] = double_top

        double_bottom = self._detect_double_bottom(candles)
        if double_bottom:
            patterns["double_bottom"] = double_bottom

        # Detect head and shoulders
        hs = self._detect_head_and_shoulders(candles)
        if hs:
            patterns["head_and_shoulders"] = hs

        ihs = self._detect_inverse_head_and_shoulders(candles)
        if ihs:
            patterns["inverse_head_and_shoulders"] = ihs

        # Detect triangles
        triangle = self._detect_triangles(candles)
        if triangle:
            patterns[triangle["pattern"]] = triangle

        # Detect flag/pennant
        flag = self._detect_flag_pennant(candles)
        if flag:
            patterns[flag["pattern"]] = flag

        # Detect channel breakout
        channel = self._detect_channel_breakout(candles)
        if channel:
            patterns[channel["pattern"]] = channel

        return patterns

    def _find_swing_highs(
        self,
        candles: List[Dict[str, Any]],
        threshold: int = 3,
    ) -> List[Tuple[int, float]]:
        """Find swing highs (local maxima)."""
        swings = []
        for i in range(threshold, len(candles) - threshold):
            is_high = True
            current_high = candles[i]["high"]
            for j in range(1, threshold + 1):
                if (candles[i - j]["high"] >= current_high or
                    candles[i + j]["high"] >= current_high):
                    is_high = False
                    break
            if is_high:
                swings.append((i, current_high))
        return swings

    def _find_swing_lows(
        self,
        candles: List[Dict[str, Any]],
        threshold: int = 3,
    ) -> List[Tuple[int, float]]:
        """Find swing lows (local minima)."""
        swings = []
        for i in range(threshold, len(candles) - threshold):
            is_low = True
            current_low = candles[i]["low"]
            for j in range(1, threshold + 1):
                if (candles[i - j]["low"] <= current_low or
                    candles[i + j]["low"] <= current_low):
                    is_low = False
                    break
            if is_low:
                swings.append((i, current_low))
        return swings

    def _calculate_slope(self, points: List[Tuple[int, float]]) -> float:
        """Calculate slope using linear regression."""
        if len(points) < 2:
            return 0.0
        n = len(points)
        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)
        sum_xx = sum(p[0] * p[0] for p in points)

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    def _detect_double_top(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect double top reversal pattern."""
        recent = candles[-self.lookback:] if len(candles) >= self.lookback else candles
        peaks = self._find_swing_highs(recent, threshold=2)

        if len(peaks) < 2:
            return None

        # Check last two peaks
        for i in range(len(peaks) - 1):
            peak1_idx, peak1_price = peaks[i]
            peak2_idx, peak2_price = peaks[i + 1]

            # Check if peaks are similar height
            price_diff_pct = abs(peak2_price - peak1_price) / peak1_price
            if price_diff_pct > self.double_top_tolerance:
                continue

            # Check minimum separation
            if peak2_idx - peak1_idx < 5:
                continue

            # Find trough between peaks
            trough_low = min(recent[j]["low"] for j in range(peak1_idx, peak2_idx + 1))
            trough_depth = (peak1_price - trough_low) / peak1_price

            # Trough must be meaningful (2-8% below peaks)
            if trough_depth < 0.02 or trough_depth > 0.08:
                continue

            # Second peak shouldn't exceed first
            if peak2_price <= peak1_price * 1.005:
                confidence = 0.7 + (0.3 * (1 - price_diff_pct / self.double_top_tolerance))
                if confidence >= self.min_confidence:
                    return {
                        "pattern": "double_top",
                        "signal": "bearish",
                        "peak1": peak1_price,
                        "peak2": peak2_price,
                        "neckline": trough_low,
                        "target": trough_low - (peak1_price - trough_low),
                        "confidence": round(confidence, 2),
                    }

        return None

    def _detect_double_bottom(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect double bottom reversal pattern."""
        recent = candles[-self.lookback:] if len(candles) >= self.lookback else candles
        troughs = self._find_swing_lows(recent, threshold=2)

        if len(troughs) < 2:
            return None

        for i in range(len(troughs) - 1):
            trough1_idx, trough1_price = troughs[i]
            trough2_idx, trough2_price = troughs[i + 1]

            # Check if troughs are similar depth
            price_diff_pct = abs(trough2_price - trough1_price) / trough1_price
            if price_diff_pct > self.double_top_tolerance:
                continue

            # Check minimum separation
            if trough2_idx - trough1_idx < 5:
                continue

            # Find peak between troughs
            peak_high = max(recent[j]["high"] for j in range(trough1_idx, trough2_idx + 1))
            peak_height = (peak_high - trough1_price) / trough1_price

            # Peak must be meaningful
            if peak_height < 0.02 or peak_height > 0.08:
                continue

            # Second trough shouldn't go lower than first
            if trough2_price >= trough1_price * 0.995:
                confidence = 0.7 + (0.3 * (1 - price_diff_pct / self.double_top_tolerance))
                if confidence >= self.min_confidence:
                    return {
                        "pattern": "double_bottom",
                        "signal": "bullish",
                        "trough1": trough1_price,
                        "trough2": trough2_price,
                        "neckline": peak_high,
                        "target": peak_high + (peak_high - trough1_price),
                        "confidence": round(confidence, 2),
                    }

        return None

    def _detect_head_and_shoulders(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect head and shoulders reversal pattern."""
        recent = candles[-60:] if len(candles) >= 60 else candles
        peaks = self._find_swing_highs(recent, threshold=2)

        if len(peaks) < 3:
            return None

        # Check last 3 peaks for H&S pattern
        for i in range(len(peaks) - 2):
            left_shoulder = peaks[i]
            head = peaks[i + 1]
            right_shoulder = peaks[i + 2]

            # Head must be highest
            if not (head[1] > left_shoulder[1] and head[1] > right_shoulder[1]):
                continue

            # Shoulders should be similar (within 5%)
            shoulder_diff = abs(left_shoulder[1] - right_shoulder[1]) / left_shoulder[1]
            if shoulder_diff > 0.05:
                continue

            # Find neckline (troughs between shoulders and head)
            trough1_low = min(recent[j]["low"] for j in range(left_shoulder[0], head[0] + 1))
            trough2_low = min(recent[j]["low"] for j in range(head[0], right_shoulder[0] + 1))
            neckline = (trough1_low + trough2_low) / 2

            head_height = head[1] - neckline
            if head_height <= 0:
                continue

            return {
                "pattern": "head_and_shoulders",
                "signal": "bearish",
                "left_shoulder": left_shoulder[1],
                "head": head[1],
                "right_shoulder": right_shoulder[1],
                "neckline": neckline,
                "target": neckline - head_height,
                "confidence": 0.75,
            }

        return None

    def _detect_inverse_head_and_shoulders(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect inverse head and shoulders reversal pattern (bullish)."""
        recent = candles[-60:] if len(candles) >= 60 else candles
        troughs = self._find_swing_lows(recent, threshold=2)

        if len(troughs) < 3:
            return None

        for i in range(len(troughs) - 2):
            left_shoulder = troughs[i]
            head = troughs[i + 1]
            right_shoulder = troughs[i + 2]

            # Head must be lowest
            if not (head[1] < left_shoulder[1] and head[1] < right_shoulder[1]):
                continue

            # Shoulders should be similar
            shoulder_diff = abs(left_shoulder[1] - right_shoulder[1]) / left_shoulder[1]
            if shoulder_diff > 0.05:
                continue

            # Find neckline (peaks between shoulders and head)
            peak1_high = max(recent[j]["high"] for j in range(left_shoulder[0], head[0] + 1))
            peak2_high = max(recent[j]["high"] for j in range(head[0], right_shoulder[0] + 1))
            neckline = (peak1_high + peak2_high) / 2

            head_depth = neckline - head[1]
            if head_depth <= 0:
                continue

            return {
                "pattern": "inverse_head_and_shoulders",
                "signal": "bullish",
                "left_shoulder": left_shoulder[1],
                "head": head[1],
                "right_shoulder": right_shoulder[1],
                "neckline": neckline,
                "target": neckline + head_depth,
                "confidence": 0.75,
            }

        return None

    def _detect_triangles(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect ascending, descending, and symmetrical triangles."""
        recent = candles[-40:] if len(candles) >= 40 else candles
        if len(recent) < 20:
            return None

        swing_highs = self._find_swing_highs(recent, threshold=2)
        swing_lows = self._find_swing_lows(recent, threshold=2)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        high_slope = self._calculate_slope(swing_highs)
        low_slope = self._calculate_slope(swing_lows)

        # Normalize slopes by average price
        avg_price = sum(c["close"] for c in recent) / len(recent)
        high_slope_norm = high_slope / avg_price if avg_price > 0 else 0
        low_slope_norm = low_slope / avg_price if avg_price > 0 else 0

        flat_threshold = self.triangle_slope_threshold

        # Ascending triangle: flat resistance, rising support
        if abs(high_slope_norm) < flat_threshold and low_slope_norm > flat_threshold:
            return {
                "pattern": "ascending_triangle",
                "signal": "bullish",
                "resistance_slope": high_slope_norm,
                "support_slope": low_slope_norm,
                "breakout_level": max(h[1] for h in swing_highs),
                "confidence": 0.70,
            }

        # Descending triangle: falling resistance, flat support
        if high_slope_norm < -flat_threshold and abs(low_slope_norm) < flat_threshold:
            return {
                "pattern": "descending_triangle",
                "signal": "bearish",
                "resistance_slope": high_slope_norm,
                "support_slope": low_slope_norm,
                "breakout_level": min(l[1] for l in swing_lows),
                "confidence": 0.70,
            }

        # Symmetrical triangle: converging lines
        if high_slope_norm < -flat_threshold and low_slope_norm > flat_threshold:
            return {
                "pattern": "symmetrical_triangle",
                "signal": "neutral",  # Wait for breakout
                "resistance_slope": high_slope_norm,
                "support_slope": low_slope_norm,
                "confidence": 0.65,
            }

        return None

    def _detect_flag_pennant(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect flag and pennant continuation patterns."""
        if len(candles) < 30:
            return None

        # Look for strong prior move (flagpole)
        pole_end = len(candles) - 20  # Consolidation is last 20 candles
        pole_start = max(0, pole_end - 10)

        if pole_end <= pole_start:
            return None

        pole_move = (candles[pole_end]["close"] - candles[pole_start]["close"]) / candles[pole_start]["close"]

        # Need 5%+ move for flagpole
        if abs(pole_move) < 0.05:
            return None

        is_bullish = pole_move > 0

        # Analyze consolidation (last 20 candles)
        consolidation = candles[-20:]
        highs = [(i, c["high"]) for i, c in enumerate(consolidation)]
        lows = [(i, c["low"]) for i, c in enumerate(consolidation)]

        high_slope = self._calculate_slope(highs)
        low_slope = self._calculate_slope(lows)

        avg_price = sum(c["close"] for c in consolidation) / len(consolidation)
        high_slope_norm = high_slope / avg_price if avg_price > 0 else 0
        low_slope_norm = low_slope / avg_price if avg_price > 0 else 0

        # Flag: parallel retracement (both slopes similar and against trend)
        slope_diff = abs(high_slope_norm - low_slope_norm)
        if slope_diff < 0.0001:
            pattern = "bull_flag" if is_bullish else "bear_flag"
        # Pennant: converging
        elif ((is_bullish and high_slope_norm < 0 and low_slope_norm > 0) or
              (not is_bullish and high_slope_norm > 0 and low_slope_norm < 0)):
            pattern = "bull_pennant" if is_bullish else "bear_pennant"
        else:
            return None

        # Calculate target (flagpole extension)
        target = candles[-1]["close"] + pole_move * candles[-1]["close"]

        return {
            "pattern": pattern,
            "signal": "bullish" if is_bullish else "bearish",
            "pole_height_pct": abs(pole_move),
            "target": target,
            "confidence": 0.70,
        }

    def _detect_channel_breakout(self, candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Detect price channel and breakouts."""
        recent = candles[-40:] if len(candles) >= 40 else candles
        if len(recent) < 20:
            return None

        swing_highs = self._find_swing_highs(recent, threshold=2)
        swing_lows = self._find_swing_lows(recent, threshold=2)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        high_slope = self._calculate_slope(swing_highs)
        low_slope = self._calculate_slope(swing_lows)

        avg_price = sum(c["close"] for c in recent) / len(recent)
        high_slope_norm = high_slope / avg_price if avg_price > 0 else 0
        low_slope_norm = low_slope / avg_price if avg_price > 0 else 0

        # Check if parallel (channel)
        slope_diff = abs(high_slope_norm - low_slope_norm)
        if slope_diff > 0.0003:
            return None

        # Project channel bounds to current position
        last_idx = len(recent) - 1

        # Simple linear projection
        if swing_highs:
            last_high_idx, last_high_val = swing_highs[-1]
            current_upper = last_high_val + high_slope * (last_idx - last_high_idx)
        else:
            current_upper = max(c["high"] for c in recent[-5:])

        if swing_lows:
            last_low_idx, last_low_val = swing_lows[-1]
            current_lower = last_low_val + low_slope * (last_idx - last_low_idx)
        else:
            current_lower = min(c["low"] for c in recent[-5:])

        current_price = recent[-1]["close"]

        # Check for breakout
        if current_price > current_upper * 1.005:
            return {
                "pattern": "channel_breakout_up",
                "signal": "bullish",
                "channel_upper": current_upper,
                "channel_lower": current_lower,
                "breakout_pct": (current_price - current_upper) / current_upper,
                "channel_slope": high_slope_norm,
                "confidence": 0.65,
            }
        elif current_price < current_lower * 0.995:
            return {
                "pattern": "channel_breakout_down",
                "signal": "bearish",
                "channel_upper": current_upper,
                "channel_lower": current_lower,
                "breakout_pct": (current_lower - current_price) / current_lower,
                "channel_slope": low_slope_norm,
                "confidence": 0.65,
            }

        return None


# =============================================================================
# Support/Resistance Detector
# =============================================================================

class SupportResistanceDetector:
    """Detect key S/R levels from price action."""

    def __init__(
        self,
        touch_threshold_pct: float = 0.003,
        min_touches: int = 2,
        lookback: int = 100,
    ):
        self.touch_threshold_pct = touch_threshold_pct
        self.min_touches = min_touches
        self.lookback = lookback

    def detect_levels(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect S/R levels and their strength."""
        if len(candles) < 10:
            return {"support": [], "resistance": []}

        recent = candles[-self.lookback:] if len(candles) >= self.lookback else candles

        # Find swing points
        swing_highs = self._find_swing_highs(recent)
        swing_lows = self._find_swing_lows(recent)

        # Combine all pivots
        all_pivots = []
        for idx, price in swing_highs:
            all_pivots.append({"idx": idx, "price": price, "type": "high"})
        for idx, price in swing_lows:
            all_pivots.append({"idx": idx, "price": price, "type": "low"})

        # Cluster pivots into levels
        levels = self._cluster_pivots(all_pivots)

        # Score each level
        current_price = recent[-1]["close"]
        scored_levels = []

        for level in levels:
            # Feature 3D: count price breaks through this level when decay is enabled
            if SR_STRENGTH_DECAY_ENABLED:
                level["break_count"] = self._count_level_breaks(level["price"], recent)
            strength = self._calculate_level_strength(level, len(recent))
            distance_pct = abs(level["price"] - current_price) / current_price

            scored_levels.append({
                "price": level["price"],
                "type": "support" if level["price"] < current_price else "resistance",
                "touches": level["touches"],
                "strength": strength,
                "distance_pct": round(distance_pct, 4),
                "last_touch_age": len(recent) - level["last_touch_idx"],
            })

        # Sort by strength
        scored_levels.sort(key=lambda x: x["strength"], reverse=True)

        # Separate support and resistance
        support_levels = [l for l in scored_levels if l["type"] == "support"][:5]
        resistance_levels = [l for l in scored_levels if l["type"] == "resistance"][:5]

        return {
            "support": support_levels,
            "resistance": resistance_levels,
            "nearest_support": support_levels[0] if support_levels else None,
            "nearest_resistance": resistance_levels[0] if resistance_levels else None,
        }

    def _find_swing_highs(self, candles: List[Dict[str, Any]], threshold: int = 2) -> List[Tuple[int, float]]:
        """Find swing highs."""
        swings = []
        for i in range(threshold, len(candles) - threshold):
            is_high = True
            current_high = candles[i]["high"]
            for j in range(1, threshold + 1):
                if (candles[i - j]["high"] >= current_high or
                    candles[i + j]["high"] >= current_high):
                    is_high = False
                    break
            if is_high:
                swings.append((i, current_high))
        return swings

    def _find_swing_lows(self, candles: List[Dict[str, Any]], threshold: int = 2) -> List[Tuple[int, float]]:
        """Find swing lows."""
        swings = []
        for i in range(threshold, len(candles) - threshold):
            is_low = True
            current_low = candles[i]["low"]
            for j in range(1, threshold + 1):
                if (candles[i - j]["low"] <= current_low or
                    candles[i + j]["low"] <= current_low):
                    is_low = False
                    break
            if is_low:
                swings.append((i, current_low))
        return swings

    def _cluster_pivots(self, pivots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Cluster nearby pivot points into levels."""
        if not pivots:
            return []

        # Sort by price
        sorted_pivots = sorted(pivots, key=lambda x: x["price"])

        clusters = []
        current_cluster = [sorted_pivots[0]]

        for pivot in sorted_pivots[1:]:
            cluster_avg = sum(p["price"] for p in current_cluster) / len(current_cluster)
            if abs(pivot["price"] - cluster_avg) / cluster_avg <= self.touch_threshold_pct:
                current_cluster.append(pivot)
            else:
                if len(current_cluster) >= self.min_touches:
                    clusters.append(self._finalize_cluster(current_cluster))
                current_cluster = [pivot]

        if len(current_cluster) >= self.min_touches:
            clusters.append(self._finalize_cluster(current_cluster))

        return clusters

    def _finalize_cluster(self, cluster: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Convert cluster of pivots into a level."""
        prices = [p["price"] for p in cluster]
        indices = [p["idx"] for p in cluster]
        return {
            "price": sum(prices) / len(prices),
            "touches": len(cluster),
            "touch_indices": indices,  # individual touch positions for recency weighting
            "first_touch_idx": min(indices),
            "last_touch_idx": max(indices),
        }

    def _count_level_breaks(
        self,
        level_price: float,
        candles: List[Dict[str, Any]],
    ) -> int:
        """Count times price crossed through the level (break count)."""
        break_count = 0
        threshold = level_price * self.touch_threshold_pct
        above = candles[0]["close"] > level_price
        for candle in candles[1:]:
            close = candle["close"]
            if above and close < level_price - threshold:
                break_count += 1
                above = False
            elif not above and close > level_price + threshold:
                break_count += 1
                above = True
        return break_count

    def _calculate_level_strength(self, level: Dict[str, Any], total_candles: int) -> float:
        """Calculate level strength (1-10), with optional recency/break-penalty decay."""
        if SR_STRENGTH_DECAY_ENABLED:
            # Recency-weighted touch count: weight = 0.5 ^ (candles_since_touch / half_life)
            touch_indices = level.get("touch_indices", [])
            if touch_indices:
                weighted_touches = 0.0
                for idx in touch_indices:
                    candles_since = total_candles - 1 - idx
                    weight = 0.5 ** (candles_since / max(1, SR_RECENCY_HALF_LIFE_CANDLES))
                    weighted_touches += weight
            else:
                weighted_touches = float(level["touches"])

            # Map weighted touches to base score (0–5 range)
            base_score = min(5.0, weighted_touches)

            # Break penalty: stored during detect_levels; default 0 if not set
            break_count = level.get("break_count", 0)
            strength = base_score * ((1.0 - SR_BREAK_PENALTY_FACTOR) ** break_count)

            # Duration bonus still applies (max +2)
            duration = level["last_touch_idx"] - level["first_touch_idx"]
            duration_bonus = min(2.0, duration / 20.0)

            return min(10.0, strength + duration_bonus)
        else:
            # Legacy path
            base_score = min(5, level["touches"])
            recency_pct = level["last_touch_idx"] / total_candles if total_candles > 0 else 0
            recency_bonus = min(3, int(recency_pct * 4))
            duration = level["last_touch_idx"] - level["first_touch_idx"]
            duration_bonus = min(2, int(duration / 20))
            return min(10, base_score + recency_bonus + duration_bonus)

    def is_near_level(
        self,
        price: float,
        levels: Dict[str, Any],
        threshold_pct: float = 0.01,
    ) -> Dict[str, Any]:
        """Check if price is near a significant S/R level."""
        result = {"near_support": False, "near_resistance": False}

        for s in levels.get("support", []):
            if abs(price - s["price"]) / price <= threshold_pct:
                result["near_support"] = True
                result["support_level"] = s
                break

        for r in levels.get("resistance", []):
            if abs(price - r["price"]) / price <= threshold_pct:
                result["near_resistance"] = True
                result["resistance_level"] = r
                break

        return result


# =============================================================================
# Divergence Detector
# =============================================================================

class DivergenceDetector:
    """Detect RSI and MACD divergences."""

    def __init__(self, lookback: int = 30, min_swing_size: float = 0.005):
        self.lookback = lookback
        self.min_swing_size = min_swing_size

    def detect_rsi_divergence(
        self,
        candles: List[Dict[str, Any]],
        rsi_values: List[float],
    ) -> Optional[Dict[str, Any]]:
        """Detect RSI divergence."""
        if len(candles) < self.lookback or len(rsi_values) < self.lookback:
            return None

        recent_candles = candles[-self.lookback:]
        recent_rsi = rsi_values[-self.lookback:]

        # Find swing points
        price_highs = self._find_swing_highs_simple([c["high"] for c in recent_candles])
        price_lows = self._find_swing_lows_simple([c["low"] for c in recent_candles])
        rsi_highs = self._find_swing_highs_simple(recent_rsi)
        rsi_lows = self._find_swing_lows_simple(recent_rsi)

        # Regular bullish: Price lower low + RSI higher low
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if price_lows[-1][1] < price_lows[-2][1]:
                if rsi_lows[-1][1] > rsi_lows[-2][1]:
                    return {
                        "type": "regular_bullish",
                        "signal": "bullish",
                        "strength": self._calculate_divergence_strength(
                            price_lows[-2][1], price_lows[-1][1],
                            rsi_lows[-2][1], rsi_lows[-1][1]
                        ),
                        "description": "Price lower low + RSI higher low (reversal)",
                    }

        # Regular bearish: Price higher high + RSI lower high
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if price_highs[-1][1] > price_highs[-2][1]:
                if rsi_highs[-1][1] < rsi_highs[-2][1]:
                    return {
                        "type": "regular_bearish",
                        "signal": "bearish",
                        "strength": self._calculate_divergence_strength(
                            price_highs[-2][1], price_highs[-1][1],
                            rsi_highs[-2][1], rsi_highs[-1][1]
                        ),
                        "description": "Price higher high + RSI lower high (reversal)",
                    }

        # Hidden bullish: Price higher low + RSI lower low (continuation)
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if price_lows[-1][1] > price_lows[-2][1]:
                if rsi_lows[-1][1] < rsi_lows[-2][1]:
                    return {
                        "type": "hidden_bullish",
                        "signal": "bullish",
                        "strength": self._calculate_divergence_strength(
                            price_lows[-2][1], price_lows[-1][1],
                            rsi_lows[-2][1], rsi_lows[-1][1]
                        ),
                        "description": "Price higher low + RSI lower low (continuation)",
                    }

        # Hidden bearish: Price lower high + RSI higher high (continuation)
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if price_highs[-1][1] < price_highs[-2][1]:
                if rsi_highs[-1][1] > rsi_highs[-2][1]:
                    return {
                        "type": "hidden_bearish",
                        "signal": "bearish",
                        "strength": self._calculate_divergence_strength(
                            price_highs[-2][1], price_highs[-1][1],
                            rsi_highs[-2][1], rsi_highs[-1][1]
                        ),
                        "description": "Price lower high + RSI higher high (continuation)",
                    }

        return None

    def detect_macd_divergence(
        self,
        candles: List[Dict[str, Any]],
        macd_histogram: List[float],
    ) -> Optional[Dict[str, Any]]:
        """Detect MACD histogram divergence."""
        if len(candles) < self.lookback or len(macd_histogram) < self.lookback:
            return None

        recent_candles = candles[-self.lookback:]
        recent_macd = macd_histogram[-self.lookback:]

        price_highs = self._find_swing_highs_simple([c["high"] for c in recent_candles])
        price_lows = self._find_swing_lows_simple([c["low"] for c in recent_candles])
        macd_highs = self._find_swing_highs_simple(recent_macd)
        macd_lows = self._find_swing_lows_simple(recent_macd)

        # Regular bullish
        if len(price_lows) >= 2 and len(macd_lows) >= 2:
            if price_lows[-1][1] < price_lows[-2][1]:
                if macd_lows[-1][1] > macd_lows[-2][1]:
                    return {
                        "type": "regular_bullish",
                        "signal": "bullish",
                        "indicator": "macd",
                        "strength": 7,
                        "description": "Price lower low + MACD higher low",
                    }

        # Regular bearish
        if len(price_highs) >= 2 and len(macd_highs) >= 2:
            if price_highs[-1][1] > price_highs[-2][1]:
                if macd_highs[-1][1] < macd_highs[-2][1]:
                    return {
                        "type": "regular_bearish",
                        "signal": "bearish",
                        "indicator": "macd",
                        "strength": 7,
                        "description": "Price higher high + MACD lower high",
                    }

        return None

    def _find_swing_highs_simple(self, data: List[float], threshold: int = 2) -> List[Tuple[int, float]]:
        """Find swing highs in a data series."""
        swings = []
        for i in range(threshold, len(data) - threshold):
            is_high = True
            for j in range(1, threshold + 1):
                if data[i - j] >= data[i] or data[i + j] >= data[i]:
                    is_high = False
                    break
            if is_high:
                swings.append((i, data[i]))
        return swings

    def _find_swing_lows_simple(self, data: List[float], threshold: int = 2) -> List[Tuple[int, float]]:
        """Find swing lows in a data series."""
        swings = []
        for i in range(threshold, len(data) - threshold):
            is_low = True
            for j in range(1, threshold + 1):
                if data[i - j] <= data[i] or data[i + j] <= data[i]:
                    is_low = False
                    break
            if is_low:
                swings.append((i, data[i]))
        return swings

    def _calculate_divergence_strength(
        self,
        price1: float,
        price2: float,
        indicator1: float,
        indicator2: float,
    ) -> int:
        """Calculate divergence strength (1-10)."""
        if price1 == 0:
            return 5
        price_change_pct = abs(price2 - price1) / price1
        indicator_change_pct = abs(indicator2 - indicator1) / max(abs(indicator1), 1)
        strength = min(10, int((price_change_pct + indicator_change_pct) * 50))
        return max(1, strength)


# =============================================================================
# Price Action Analyzer
# =============================================================================

class PriceActionAnalyzer:
    """Analyze price structure for HH/HL and LH/LL patterns."""

    def __init__(self, swing_threshold: int = 3):
        self.swing_threshold = swing_threshold

    def analyze_trend_structure(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze trend structure using swing points."""
        if len(candles) < 10:
            return {"structure": "insufficient_data", "trend": "neutral", "strength": 0}

        swing_highs = self._find_swing_highs(candles)
        swing_lows = self._find_swing_lows(candles)

        # Count patterns
        hh_count = 0  # Higher highs
        lh_count = 0  # Lower highs
        hl_count = 0  # Higher lows
        ll_count = 0  # Lower lows

        for i in range(1, len(swing_highs)):
            if swing_highs[i][1] > swing_highs[i - 1][1]:
                hh_count += 1
            else:
                lh_count += 1

        for i in range(1, len(swing_lows)):
            if swing_lows[i][1] > swing_lows[i - 1][1]:
                hl_count += 1
            else:
                ll_count += 1

        # Determine structure
        total_swings = len(swing_highs) + len(swing_lows)
        if total_swings < 4:
            structure = "insufficient_data"
            trend = "neutral"
            strength = 0
        elif hh_count >= 2 and hl_count >= 2:
            structure = "uptrend"
            trend = "bullish"
            strength = min(10, (hh_count + hl_count) * 2)
        elif lh_count >= 2 and ll_count >= 2:
            structure = "downtrend"
            trend = "bearish"
            strength = min(10, (lh_count + ll_count) * 2)
        elif hh_count >= 2 and ll_count >= 1:
            structure = "expanding"
            trend = "neutral"
            strength = 3
        elif lh_count >= 2 and hl_count >= 1:
            structure = "contracting"
            trend = "neutral"
            strength = 3
        else:
            structure = "mixed"
            trend = "neutral"
            strength = 2

        return {
            "structure": structure,
            "trend": trend,
            "strength": strength,
            "higher_highs": hh_count,
            "lower_highs": lh_count,
            "higher_lows": hl_count,
            "lower_lows": ll_count,
            "last_swing_high": swing_highs[-1] if swing_highs else None,
            "last_swing_low": swing_lows[-1] if swing_lows else None,
        }

    def _find_swing_highs(self, candles: List[Dict[str, Any]]) -> List[Tuple[int, float]]:
        """Find swing highs."""
        swings = []
        for i in range(self.swing_threshold, len(candles) - self.swing_threshold):
            is_high = True
            current_high = candles[i]["high"]
            for j in range(1, self.swing_threshold + 1):
                if (candles[i - j]["high"] >= current_high or
                    candles[i + j]["high"] >= current_high):
                    is_high = False
                    break
            if is_high:
                swings.append((i, current_high))
        return swings

    def _find_swing_lows(self, candles: List[Dict[str, Any]]) -> List[Tuple[int, float]]:
        """Find swing lows."""
        swings = []
        for i in range(self.swing_threshold, len(candles) - self.swing_threshold):
            is_low = True
            current_low = candles[i]["low"]
            for j in range(1, self.swing_threshold + 1):
                if (candles[i - j]["low"] <= current_low or
                    candles[i + j]["low"] <= current_low):
                    is_low = False
                    break
            if is_low:
                swings.append((i, current_low))
        return swings


# =============================================================================
# Long-Term Trend Analyzer (NEW - Deep Historical Analysis)
# =============================================================================

class LongTermTrendAnalyzer:
    """
    Analyze long-term trends using 1000+ candles of historical data.
    Identifies macro trend direction, key swing levels, and trend maturity.
    """

    def __init__(self, lookback: int = 1000):
        self.lookback = lookback

    def analyze(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Perform deep historical analysis on candle data.

        Returns:
            Dict with macro_trend, trend_strength, key_levels, trend_age, etc.
        """
        if len(candles) < 50:
            return {
                "macro_trend": "neutral",
                "trend_strength": 0,
                "trend_score": 0,
                "analysis": "insufficient_data",
            }

        # Use all available candles up to lookback limit
        data = candles[-self.lookback:] if len(candles) >= self.lookback else candles

        # 1. Calculate long-term moving averages
        closes = [c["close"] for c in data]
        ema_50 = self._ema(closes, 50)
        ema_200 = self._ema(closes, 200)
        ema_500 = self._ema(closes, min(500, len(closes) - 1)) if len(closes) > 500 else None

        current_price = closes[-1]

        # 2. Determine macro trend from MA alignment
        ma_score = 0
        ma_signals = []

        if ema_50 and ema_200:
            if current_price > ema_50 > ema_200:
                ma_score += 30
                ma_signals.append("Price > EMA50 > EMA200 (strong uptrend)")
            elif current_price < ema_50 < ema_200:
                ma_score -= 30
                ma_signals.append("Price < EMA50 < EMA200 (strong downtrend)")
            elif current_price > ema_200:
                ma_score += 15
                ma_signals.append("Price above EMA200 (bullish bias)")
            elif current_price < ema_200:
                ma_score -= 15
                ma_signals.append("Price below EMA200 (bearish bias)")

        if ema_500:
            if current_price > ema_500:
                ma_score += 10
                ma_signals.append("Price above EMA500 (macro bullish)")
            else:
                ma_score -= 10
                ma_signals.append("Price below EMA500 (macro bearish)")

        # 3. Find major swing highs and lows (using larger threshold for macro swings)
        major_highs = self._find_major_swings(data, "high", threshold=10)
        major_lows = self._find_major_swings(data, "low", threshold=10)

        # 4. Analyze swing structure for trend
        structure_score = 0
        hh_count, lh_count, hl_count, ll_count = 0, 0, 0, 0

        for i in range(1, len(major_highs)):
            if major_highs[i][1] > major_highs[i-1][1]:
                hh_count += 1
            else:
                lh_count += 1

        for i in range(1, len(major_lows)):
            if major_lows[i][1] > major_lows[i-1][1]:
                hl_count += 1
            else:
                ll_count += 1

        if hh_count > lh_count and hl_count > ll_count:
            structure_score = min(25, (hh_count + hl_count) * 5)
            structure = "uptrend"
        elif lh_count > hh_count and ll_count > hl_count:
            structure_score = -min(25, (lh_count + ll_count) * 5)
            structure = "downtrend"
        else:
            structure = "ranging"

        # 5. Calculate price position in historical range
        all_highs = [c["high"] for c in data]
        all_lows = [c["low"] for c in data]
        range_high = max(all_highs)
        range_low = min(all_lows)
        range_size = range_high - range_low

        if range_size > 0:
            position_in_range = (current_price - range_low) / range_size
        else:
            position_in_range = 0.5

        # Position score: bullish if in lower half, bearish if in upper half
        # (contrarian - room to move)
        position_score = 0
        if position_in_range < 0.3:
            position_score = 10  # Near lows, bullish potential
        elif position_in_range > 0.7:
            position_score = -10  # Near highs, bearish potential

        # 6. Calculate trend momentum (recent vs historical performance)
        if len(closes) >= 100 and closes[-50] != 0 and closes[-100] != 0:
            recent_return = (closes[-1] - closes[-50]) / closes[-50] * 100
            historical_return = (closes[-50] - closes[-100]) / closes[-100] * 100

            if recent_return > 0 and recent_return > historical_return:
                momentum_score = 10  # Accelerating uptrend
            elif recent_return < 0 and recent_return < historical_return:
                momentum_score = -10  # Accelerating downtrend
            elif recent_return > 0:
                momentum_score = 5  # Slowing uptrend
            elif recent_return < 0:
                momentum_score = -5  # Slowing downtrend
            else:
                momentum_score = 0
        else:
            momentum_score = 0
            recent_return = 0
            historical_return = 0

        # 7. Calculate total score
        total_score = ma_score + structure_score + position_score + momentum_score

        # Determine macro trend
        if total_score >= 40:
            macro_trend = "STRONG_BULLISH"
        elif total_score >= 20:
            macro_trend = "BULLISH"
        elif total_score <= -40:
            macro_trend = "STRONG_BEARISH"
        elif total_score <= -20:
            macro_trend = "BEARISH"
        else:
            macro_trend = "NEUTRAL"

        return {
            "macro_trend": macro_trend,
            "trend_strength": abs(total_score),
            "trend_score": total_score,
            "structure": structure,
            "ma_alignment": {
                "ema_50": round(ema_50, 4) if ema_50 else None,
                "ema_200": round(ema_200, 4) if ema_200 else None,
                "ema_500": round(ema_500, 4) if ema_500 else None,
                "signals": ma_signals,
            },
            "swing_analysis": {
                "higher_highs": hh_count,
                "lower_highs": lh_count,
                "higher_lows": hl_count,
                "lower_lows": ll_count,
            },
            "range_analysis": {
                "range_high": round(range_high, 4),
                "range_low": round(range_low, 4),
                "position_in_range": round(position_in_range, 2),
            },
            "momentum": {
                "recent_return_pct": round(recent_return, 2) if recent_return else 0,
                "historical_return_pct": round(historical_return, 2) if historical_return else 0,
                "momentum_score": momentum_score,
            },
            "candles_analyzed": len(data),
        }

    def _ema(self, data: List[float], period: int) -> Optional[float]:
        """Calculate EMA for the last value."""
        if len(data) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period

        for price in data[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _find_major_swings(
        self,
        candles: List[Dict[str, Any]],
        price_type: str,
        threshold: int = 10,
    ) -> List[Tuple[int, float]]:
        """Find major swing points using larger threshold."""
        swings = []
        for i in range(threshold, len(candles) - threshold):
            is_swing = True
            current = candles[i][price_type]

            if price_type == "high":
                for j in range(1, threshold + 1):
                    if candles[i - j]["high"] >= current or candles[i + j]["high"] >= current:
                        is_swing = False
                        break
            else:  # low
                for j in range(1, threshold + 1):
                    if candles[i - j]["low"] <= current or candles[i + j]["low"] <= current:
                        is_swing = False
                        break

            if is_swing:
                swings.append((i, current))

        return swings


# =============================================================================
# Trend Duration Tracker (NEW - Momentum Persistence)
# =============================================================================

class TrendDurationTracker:
    """
    Track how long the current trend has been running.
    Longer trends have more momentum but may be exhausted.
    """

    def __init__(self):
        pass

    def analyze(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze trend duration and momentum persistence.

        Returns:
            Dict with trend_duration, trend_phase, exhaustion signals, etc.
        """
        if len(candles) < 50:
            return {
                "trend_duration_candles": 0,
                "trend_phase": "unknown",
                "score": 0,
            }

        closes = [c["close"] for c in candles]

        # Find trend start by looking for the last significant reversal
        ema_20 = self._ema_series(closes, 20)
        ema_50 = self._ema_series(closes, 50)

        if not ema_20 or not ema_50:
            return {
                "trend_duration_candles": 0,
                "trend_phase": "unknown",
                "score": 0,
            }

        # Determine current trend direction
        current_bullish = ema_20[-1] > ema_50[-1]

        # Count candles since trend started (last EMA cross)
        trend_duration = 0
        for i in range(len(ema_20) - 1, 0, -1):
            was_bullish = ema_20[i-1] > ema_50[i-1]
            if was_bullish != current_bullish:
                trend_duration = len(ema_20) - i
                break
        else:
            trend_duration = len(ema_20)  # Trend for entire period

        # Calculate trend phase
        if trend_duration < 20:
            trend_phase = "early"
            phase_score = 15  # Early trend = strong signal
        elif trend_duration < 50:
            trend_phase = "developing"
            phase_score = 10  # Developing = moderate signal
        elif trend_duration < 100:
            trend_phase = "mature"
            phase_score = 5  # Mature = weaker signal, possible reversal
        else:
            trend_phase = "extended"
            phase_score = -5  # Extended = exhaustion likely

        # Check for trend exhaustion signals
        exhaustion_signals = []

        # 1. Decreasing momentum (smaller moves)
        if len(closes) >= 30:
            recent_volatility = self._calculate_volatility(closes[-15:])
            older_volatility = self._calculate_volatility(closes[-30:-15])
            if older_volatility > 0 and recent_volatility < older_volatility * 0.6:
                exhaustion_signals.append("decreasing_volatility")
                phase_score -= 5

        # 2. Price diverging from trend (pulling back)
        if len(closes) >= 10:
            if current_bullish and closes[-1] < closes[-5]:
                exhaustion_signals.append("pullback_in_uptrend")
            elif not current_bullish and closes[-1] > closes[-5]:
                exhaustion_signals.append("pullback_in_downtrend")

        # Adjust score based on trend direction
        if current_bullish:
            final_score = phase_score
        else:
            final_score = -phase_score

        return {
            "trend_duration_candles": trend_duration,
            "trend_direction": "bullish" if current_bullish else "bearish",
            "trend_phase": trend_phase,
            "exhaustion_signals": exhaustion_signals,
            "score": final_score,
            "description": f"{trend_phase.capitalize()} {('uptrend' if current_bullish else 'downtrend')} ({trend_duration} candles)",
        }

    def _ema_series(self, data: List[float], period: int) -> List[float]:
        """Calculate EMA series."""
        if len(data) < period:
            return []

        multiplier = 2 / (period + 1)
        ema_values = []
        ema = sum(data[:period]) / period

        for i, price in enumerate(data):
            if i < period:
                ema_values.append(sum(data[:i+1]) / (i+1))
            else:
                ema = (price - ema) * multiplier + ema
                ema_values.append(ema)

        return ema_values

    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate simple volatility (standard deviation of returns)."""
        if len(prices) < 2:
            return 0.0

        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)


# =============================================================================
# Higher Timeframe Bias Analyzer (NEW)
# =============================================================================

class HigherTimeframeBias:
    """
    Analyze higher timeframes (4h, Daily) for macro bias.
    """

    def __init__(self, indicator_service: IndicatorService):
        self.indicator_service = indicator_service

    def get_bias(self, symbol: str) -> Dict[str, Any]:
        """
        Get bias from higher timeframes.

        Returns:
            Dict with daily_bias, h4_bias, combined_score, etc.
        """
        biases = {}
        total_score = 0
        weights = {"60": 0.2, "240": 0.35, "D": 0.45}

        for interval in HIGHER_TF_INTERVALS:
            try:
                indicators = self.indicator_service.compute_indicators(
                    symbol=symbol,
                    interval=interval,
                    limit=HIGHER_TF_CANDLE_LIMIT,
                )

                bias_score = self._calculate_bias(indicators)
                biases[interval] = {
                    "score": bias_score,
                    "rsi": indicators.get("rsi"),
                    "adx": indicators.get("adx"),
                    "ema_cross": indicators.get("ema_cross"),
                    "price_vs_ema": indicators.get("price_vs_ema"),
                }

                weight = weights.get(interval, 0.25)
                total_score += bias_score * weight

            except Exception as e:
                logger.warning(f"Failed to get {interval} indicators for {symbol}: {e}")
                biases[interval] = {"score": 0, "error": str(e)}

        # Determine overall bias
        if total_score >= 30:
            overall_bias = "STRONG_BULLISH"
        elif total_score >= 15:
            overall_bias = "BULLISH"
        elif total_score <= -30:
            overall_bias = "STRONG_BEARISH"
        elif total_score <= -15:
            overall_bias = "BEARISH"
        else:
            overall_bias = "NEUTRAL"

        return {
            "overall_bias": overall_bias,
            "combined_score": round(total_score, 2),
            "timeframe_biases": biases,
        }

    def _calculate_bias(self, indicators: Dict[str, Any]) -> float:
        """Calculate bias score from indicators."""
        score = 0.0

        # RSI contribution
        rsi = indicators.get("rsi")
        if rsi is not None:
            if rsi >= 55:
                score += min(20, (rsi - 50) * 0.8)
            elif rsi <= 45:
                score -= min(20, (50 - rsi) * 0.8)

        # EMA relationship
        price_vs_ema = indicators.get("price_vs_ema")
        if price_vs_ema == "above":
            score += 15
        elif price_vs_ema == "below":
            score -= 15

        # EMA cross
        ema_cross = indicators.get("ema_cross")
        if ema_cross == "bullish":
            score += 20
        elif ema_cross == "bearish":
            score -= 20

        # ADX amplifier (trend strength)
        adx = indicators.get("adx")
        if adx is not None and adx >= 25:
            score *= 1.25

        return max(-50, min(50, score))


# =============================================================================
# Multi-Timeframe Aligner
# =============================================================================

class TimeframeAligner:
    """Score alignment across multiple timeframes."""

    def __init__(
        self,
        indicator_service: IndicatorService,
        timeframes: List[str] = None,
        weights: Dict[str, float] = None,
    ):
        self.indicator_service = indicator_service
        self.timeframes = timeframes or ["5", "15", "60"]
        self.weights = weights or {"5": 0.15, "15": 0.25, "60": 0.35, "D": 0.25}

    def calculate_alignment(self, symbol: str) -> Dict[str, Any]:
        """Calculate multi-timeframe alignment score."""
        tf_scores = {}
        total_weight = 0
        weighted_score = 0

        for tf in self.timeframes:
            try:
                indicators = self.indicator_service.compute_indicators(
                    symbol=symbol,
                    interval=tf,
                    limit=200,
                )

                score = self._score_timeframe(indicators)
                tf_scores[tf] = {
                    "score": score,
                    "rsi": indicators.get("rsi"),
                    "adx": indicators.get("adx"),
                    "macd_cross": indicators.get("macd_cross"),
                    "ema_cross": indicators.get("ema_cross"),
                    "price_vs_ema": indicators.get("price_vs_ema"),
                }

                weight = self.weights.get(tf, 0.20)
                weighted_score += score * weight
                total_weight += weight

            except Exception as e:
                logger.warning(f"Failed to get indicators for {symbol} {tf}: {e}")
                tf_scores[tf] = {"score": 0, "error": str(e)}

        # Feature 3C: MTF Confluence Scoring — magnitude-aware weighted sum
        if MTF_CONFLUENCE_SCORING_ENABLED:
            mtf_raw_score = 0.0
            raw_tf_contributions = []
            for tf in self.timeframes:
                if tf in tf_scores and "error" not in tf_scores[tf]:
                    try:
                        indicators = self.indicator_service.compute_indicators(
                            symbol=symbol, interval=tf, limit=200
                        )
                        ema9 = indicators.get("ema_9")
                        ema21 = indicators.get("ema_21")
                        price = indicators.get("close")
                        weight = self.weights.get(tf, 0.20)
                        if ema9 and ema21 and price and price > 0:
                            magnitude = abs(ema9 - ema21) / price * 100
                            direction = 1 if ema9 > ema21 else -1
                            tf_contribution = direction * magnitude * weight
                            raw_tf_contributions.append((direction, tf_contribution))
                            mtf_raw_score += tf_contribution
                    except Exception:
                        pass

            # Confluence bonus: all TFs agree in direction
            if raw_tf_contributions:
                directions = [d for d, _ in raw_tf_contributions]
                if all(d == 1 for d in directions) or all(d == -1 for d in directions):
                    mtf_raw_score *= 1.3

            # Cap at ±MTF_CONFLUENCE_MAX_SCORE
            mtf_confluence_score = max(-MTF_CONFLUENCE_MAX_SCORE, min(MTF_CONFLUENCE_MAX_SCORE, mtf_raw_score))
            # Blend confluence score into final_score (replace weighted_score path)
            if total_weight > 0:
                legacy_score = weighted_score / total_weight
            else:
                legacy_score = 0
            # Use confluence score as the primary weighted_score for alignment
            final_score = mtf_confluence_score
        else:
            # Legacy path
            if total_weight > 0:
                final_score = weighted_score / total_weight
            else:
                final_score = 0

        # Determine alignment quality
        all_scores = [s["score"] for s in tf_scores.values() if "error" not in s]

        if all_scores:
            all_bullish = all(s > 20 for s in all_scores)
            all_bearish = all(s < -20 for s in all_scores)

            if all_bullish:
                alignment = "STRONG_BULLISH"
                alignment_strength = 10
            elif all_bearish:
                alignment = "STRONG_BEARISH"
                alignment_strength = 10
            elif all(s > 0 for s in all_scores):
                alignment = "BULLISH"
                alignment_strength = 7
            elif all(s < 0 for s in all_scores):
                alignment = "BEARISH"
                alignment_strength = 7
            else:
                alignment = "MIXED"
                alignment_strength = 3
        else:
            alignment = "UNKNOWN"
            alignment_strength = 0

        return {
            "alignment": alignment,
            "alignment_strength": alignment_strength,
            "weighted_score": round(final_score, 2),
            "timeframe_scores": tf_scores,
            "higher_tf_trend": self._get_higher_tf_trend(tf_scores),
        }

    def _score_timeframe(self, indicators: Dict[str, Any]) -> float:
        """Score a single timeframe's bias (-100 to +100)."""
        score = 0.0

        # RSI contribution (max +/- 25)
        rsi = indicators.get("rsi")
        if rsi is not None:
            if rsi >= 60:
                score += min(25, (rsi - 50) * 0.5)
            elif rsi <= 40:
                score -= min(25, (50 - rsi) * 0.5)

        # EMA relationship (max +/- 20)
        price_vs_ema = indicators.get("price_vs_ema")
        if price_vs_ema == "above":
            score += 20
        elif price_vs_ema == "below":
            score -= 20

        # EMA cross (max +/- 25)
        ema_cross = indicators.get("ema_cross")
        if ema_cross == "bullish":
            score += 25
        elif ema_cross == "bearish":
            score -= 25

        # MACD cross (max +/- 20)
        macd_cross = indicators.get("macd_cross")
        if macd_cross == "bullish":
            score += 20
        elif macd_cross == "bearish":
            score -= 20

        # ADX amplifier
        adx = indicators.get("adx")
        if adx is not None and adx >= 25:
            score *= 1.2

        return max(-100, min(100, score))

    def _get_higher_tf_trend(self, tf_scores: Dict[str, Any]) -> str:
        """Determine the dominant trend from higher timeframes."""
        for tf in ["60", "15", "5"]:
            if tf in tf_scores and "error" not in tf_scores[tf]:
                score = tf_scores[tf]["score"]
                if score >= 30:
                    return "BULLISH"
                elif score <= -30:
                    return "BEARISH"
        return "NEUTRAL"


# =============================================================================
# Main Price Prediction Service
# =============================================================================

class PricePredictionService:
    """Main orchestrator for price prediction."""

    def __init__(
        self,
        indicator_service: IndicatorService,
        client: BybitClient,
    ):
        self.indicator_service = indicator_service
        self.client = client

        # Initialize sub-detectors
        self.pattern_detector = PatternDetector(
            lookback=PATTERN_LOOKBACK_CANDLES,
            min_confidence=PATTERN_MIN_CONFIDENCE,
            double_top_tolerance=DOUBLE_TOP_BOTTOM_TOLERANCE,
            triangle_slope_threshold=TRIANGLE_SLOPE_THRESHOLD,
        )
        self.sr_detector = SupportResistanceDetector(
            touch_threshold_pct=SR_TOUCH_THRESHOLD_PCT,
            min_touches=SR_MIN_TOUCHES,
            lookback=SR_LOOKBACK_CANDLES,
        )
        self.divergence_detector = DivergenceDetector(
            lookback=DIVERGENCE_LOOKBACK,
            min_swing_size=DIVERGENCE_MIN_SWING_SIZE,
        )
        self.price_action_analyzer = PriceActionAnalyzer()
        self.timeframe_aligner = TimeframeAligner(
            indicator_service=indicator_service,
            timeframes=MTF_TIMEFRAMES,
            weights=MTF_WEIGHTS,
        )

        # NEW: Deep analysis components
        self.long_term_analyzer = LongTermTrendAnalyzer(lookback=LONG_TERM_LOOKBACK)
        self.trend_duration_tracker = TrendDurationTracker()
        self.higher_tf_bias = HigherTimeframeBias(indicator_service=indicator_service)

        # Cache for RSI/MACD values needed for divergence
        self._rsi_cache: Dict[str, List[float]] = {}
        self._macd_cache: Dict[str, List[float]] = {}

        # State tracking for safeguards (2026-01-10)
        # Hysteresis: track previous labels to prevent rapid flipping
        # Key: (symbol, timeframe) -> previous direction label
        self._previous_labels: Dict[Tuple[str, str], str] = {}

        # Timeframe confirmation: track consecutive STRONG signals
        # Key: (symbol, timeframe, direction) -> consecutive count
        self._strong_confirmation_state: Dict[Tuple[str, str, str], int] = {}

        # Feature 3B: Divergence duration tracking
        # Key: (symbol, div_type) -> {"first_candle_idx": int}
        self._divergence_state: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # Feature 3A: VolumeProfileService (lazy-initialized)
        self._volume_profile_service: Optional[Any] = None


    def predict(
        self,
        symbol: str,
        timeframe: str = "15",
    ) -> PredictionResult:
        """
        Generate comprehensive price prediction using DEEP historical analysis.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            timeframe: Primary timeframe for analysis

        Returns:
            PredictionResult with direction, confidence, and detailed signals
        """
        signals: List[Signal] = []
        score = 0.0
        # Track component contributions for top_components
        component_scores: Dict[str, float] = {}

        # Fetch candle data - NOW USES 1000 CANDLES for deep analysis
        candle_limit = PREDICTION_CANDLE_LIMIT if PREDICTION_DEEP_ANALYSIS else 200
        candles = self.indicator_service.get_ohlcv(symbol, timeframe, limit=candle_limit)
        if not candles:
            return PredictionResult(
                direction="NEUTRAL",
                confidence=0,
                score=0,
            )

        # Filter out incomplete (still-forming) candle if enabled
        candles_used = len(candles)
        if PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES and len(candles) > 1:
            # Drop the last candle (currently forming)
            candles = candles[:-1]
            candles_used = len(candles)

        current_price = candles[-1]["close"]

        # Feature 3A: pre-fetch primary timeframe indicators for pattern context weighting
        _primary_indicators: Dict[str, Any] = {}
        _vp_data: Dict[str, Any] = {}
        if PATTERN_CONTEXT_WEIGHTING_ENABLED:
            try:
                _primary_indicators = self.indicator_service.compute_indicators(
                    symbol=symbol, interval=timeframe, limit=200
                )
            except Exception:
                pass
            try:
                if self._volume_profile_service is None:
                    from services.volume_profile_service import VolumeProfileService
                    self._volume_profile_service = VolumeProfileService(
                        bybit_client=self.client,
                        indicator_service=self.indicator_service,
                    )
                _vp_data = self._volume_profile_service.calculate_volume_profile(
                    symbol=symbol, timeframe=timeframe, lookback=100
                )
            except Exception:
                pass

        # 1. Pattern Detection (max +/- 30 points)
        pattern_signals = self.pattern_detector.detect_all_patterns(candles)
        pattern_score = 0
        for pattern_name, pattern_data in pattern_signals.items():
            signal_dir = pattern_data.get("signal", "neutral")
            confidence = pattern_data.get("confidence", 0.5)

            # Feature 3A: Pattern Context Weighting
            if PATTERN_CONTEXT_WEIGHTING_ENABLED:
                adx = _primary_indicators.get("adx")
                hvn_levels = _vp_data.get("hvn_levels", [])
                lvn_levels = _vp_data.get("lvn_levels", [])
                poc = _vp_data.get("poc")
                price_range = _vp_data.get("price_high", 0) - _vp_data.get("price_low", 0)
                proximity_thr = price_range * 0.02 if price_range > 0 else 0

                # Chop market: ADX < 15 → reduce confidence
                if adx is not None and adx < 15:
                    confidence *= PATTERN_CHOP_CONFIDENCE_MULT

                # Near HVN or POC → boost confidence
                near_hvn = any(
                    abs(current_price - h) < proximity_thr
                    for h in hvn_levels
                ) if hvn_levels and proximity_thr > 0 else False
                near_poc = (
                    poc is not None and proximity_thr > 0
                    and abs(current_price - poc) < proximity_thr
                )
                if near_hvn or near_poc:
                    confidence *= PATTERN_HVN_CONFIDENCE_BOOST

                # In LVN and ADX < 20 → penalize confidence
                in_lvn = any(
                    abs(current_price - lv) < proximity_thr
                    for lv in lvn_levels
                ) if lvn_levels and proximity_thr > 0 else False
                if in_lvn and adx is not None and adx < 20:
                    confidence *= 0.60

            points = int(confidence * 30)

            if signal_dir == "bullish":
                pattern_score += points
                signals.append(Signal(
                    name=pattern_name,
                    direction="bullish",
                    strength=int(confidence * 10),
                    timeframe=timeframe,
                    description=f"{pattern_name} pattern detected",
                ))
            elif signal_dir == "bearish":
                pattern_score -= points
                signals.append(Signal(
                    name=pattern_name,
                    direction="bearish",
                    strength=int(confidence * 10),
                    timeframe=timeframe,
                    description=f"{pattern_name} pattern detected",
                ))

        pattern_clamped = max(-30, min(30, pattern_score))
        score += pattern_clamped
        component_scores["pattern"] = pattern_clamped

        # 2. Support/Resistance Detection
        sr_levels = self.sr_detector.detect_levels(candles)
        sr_proximity = self.sr_detector.is_near_level(
            current_price, sr_levels, SR_PROXIMITY_THRESHOLD
        )

        sr_score = 0
        if sr_proximity.get("near_support"):
            sr_score += 15
            signals.append(Signal(
                name="near_support",
                direction="bullish",
                strength=sr_proximity.get("support_level", {}).get("strength", 5),
                timeframe=timeframe,
                description=f"Near support at {sr_proximity.get('support_level', {}).get('price', 0):.2f}",
            ))
        if sr_proximity.get("near_resistance"):
            sr_score -= 15
            signals.append(Signal(
                name="near_resistance",
                direction="bearish",
                strength=sr_proximity.get("resistance_level", {}).get("strength", 5),
                timeframe=timeframe,
                description=f"Near resistance at {sr_proximity.get('resistance_level', {}).get('price', 0):.2f}",
            ))

        score += sr_score
        component_scores["sr_proximity"] = sr_score

        # 3. Divergence Detection (max +/- 25 points)
        # Build RSI history for divergence
        rsi_values = self._compute_rsi_series(candles)
        rsi_divergence = self.divergence_detector.detect_rsi_divergence(candles, rsi_values)
        divergence_score = 0
        current_candle_idx = len(candles) - 1

        if rsi_divergence:
            div_type = rsi_divergence.get("type", "")
            div_signal = rsi_divergence.get("signal", "neutral")
            div_strength = rsi_divergence.get("strength", 5)

            if "regular" in div_type:
                points = 25
            else:  # hidden
                points = 15

            # Feature 3B: Divergence Duration Tracking — age-based weight decay
            if DIVERGENCE_DURATION_TRACKING_ENABLED and div_type:
                state_key = (symbol, div_type)
                if state_key not in self._divergence_state:
                    self._divergence_state[state_key] = {"first_candle_idx": current_candle_idx}
                age = current_candle_idx - self._divergence_state[state_key]["first_candle_idx"]
                if age <= DIVERGENCE_FRESH_MAX_CANDLES:
                    div_weight = 1.0
                elif age >= DIVERGENCE_AGED_CANDLES:
                    div_weight = DIVERGENCE_AGED_WEIGHT_MULT
                else:
                    span = DIVERGENCE_AGED_CANDLES - DIVERGENCE_FRESH_MAX_CANDLES
                    progress = (age - DIVERGENCE_FRESH_MAX_CANDLES) / span
                    div_weight = 1.0 - progress * (1.0 - DIVERGENCE_AGED_WEIGHT_MULT)
                points = int(points * div_weight)

            if div_signal == "bullish":
                divergence_score = points
                score += points
                signals.append(Signal(
                    name=f"rsi_{div_type}",
                    direction="bullish",
                    strength=div_strength,
                    timeframe=timeframe,
                    description=rsi_divergence.get("description", "RSI divergence"),
                ))
            elif div_signal == "bearish":
                divergence_score = -points
                score -= points
                signals.append(Signal(
                    name=f"rsi_{div_type}",
                    direction="bearish",
                    strength=div_strength,
                    timeframe=timeframe,
                    description=rsi_divergence.get("description", "RSI divergence"),
                ))
        else:
            # Feature 3B: Clear stale divergence state when divergence disappears
            if DIVERGENCE_DURATION_TRACKING_ENABLED:
                keys_to_clear = [k for k in self._divergence_state if k[0] == symbol]
                for k in keys_to_clear:
                    del self._divergence_state[k]

        component_scores["divergence"] = divergence_score

        # 4. Price Action Analysis (max +/- 15 points)
        trend_structure = self.price_action_analyzer.analyze_trend_structure(candles)
        structure_trend = trend_structure.get("trend", "neutral")
        structure_strength = trend_structure.get("strength", 0)
        structure_score = 0

        if structure_trend == "bullish":
            structure_score = min(15, structure_strength * 2)
            score += structure_score
            signals.append(Signal(
                name="trend_structure",
                direction="bullish",
                strength=structure_strength,
                timeframe=timeframe,
                description=f"Uptrend structure: {trend_structure.get('higher_highs', 0)} HH, {trend_structure.get('higher_lows', 0)} HL",
            ))
        elif structure_trend == "bearish":
            structure_score = -min(15, structure_strength * 2)
            score += structure_score
            signals.append(Signal(
                name="trend_structure",
                direction="bearish",
                strength=structure_strength,
                timeframe=timeframe,
                description=f"Downtrend structure: {trend_structure.get('lower_highs', 0)} LH, {trend_structure.get('lower_lows', 0)} LL",
            ))

        component_scores["structure"] = structure_score

        # 5. Multi-Timeframe Alignment (max +/- 20 points)
        mtf_alignment = self.timeframe_aligner.calculate_alignment(symbol)
        alignment = mtf_alignment.get("alignment", "MIXED")
        alignment_strength = mtf_alignment.get("alignment_strength", 0)
        mtf_score = 0

        if alignment == "STRONG_BULLISH":
            mtf_score = 20
            score += mtf_score
            signals.append(Signal(
                name="mtf_alignment",
                direction="bullish",
                strength=10,
                timeframe="multi",
                description="All timeframes aligned bullish",
            ))
        elif alignment == "BULLISH":
            mtf_score = 10
            score += mtf_score
            signals.append(Signal(
                name="mtf_alignment",
                direction="bullish",
                strength=7,
                timeframe="multi",
                description="Timeframes mostly bullish",
            ))
        elif alignment == "STRONG_BEARISH":
            mtf_score = -20
            score += mtf_score
            signals.append(Signal(
                name="mtf_alignment",
                direction="bearish",
                strength=10,
                timeframe="multi",
                description="All timeframes aligned bearish",
            ))
        elif alignment == "BEARISH":
            mtf_score = -10
            score += mtf_score
            signals.append(Signal(
                name="mtf_alignment",
                direction="bearish",
                strength=7,
                timeframe="multi",
                description="Timeframes mostly bearish",
            ))

        component_scores["mtf_alignment"] = mtf_score

        # =====================================================================
        # NEW: DEEP HISTORICAL ANALYSIS (uses 1000 candles)
        # =====================================================================

        long_term_analysis = {}
        trend_duration_analysis = {}
        higher_tf_analysis = {}
        lt_contribution_signed = 0
        td_contribution_signed = 0
        htf_contribution_signed = 0

        if PREDICTION_DEEP_ANALYSIS and len(candles) >= 100:

            # 6. Long-Term Trend Analysis (max +/- 25 points)
            try:
                long_term_analysis = self.long_term_analyzer.analyze(candles)
                lt_score = long_term_analysis.get("trend_score", 0)
                lt_trend = long_term_analysis.get("macro_trend", "NEUTRAL")

                # Scale to max weight
                lt_contribution = min(LONG_TERM_TREND_WEIGHT, abs(lt_score) * 0.5)
                if lt_score > 0:
                    lt_contribution_signed = lt_contribution
                    score += lt_contribution
                elif lt_score < 0:
                    lt_contribution_signed = -lt_contribution
                    score -= lt_contribution

                if lt_trend in ["STRONG_BULLISH", "BULLISH"]:
                    signals.append(Signal(
                        name="long_term_trend",
                        direction="bullish",
                        strength=min(10, abs(lt_score) // 5),
                        timeframe="long_term",
                        description=f"Macro trend: {lt_trend} ({long_term_analysis.get('candles_analyzed', 0)} candles)",
                    ))
                elif lt_trend in ["STRONG_BEARISH", "BEARISH"]:
                    signals.append(Signal(
                        name="long_term_trend",
                        direction="bearish",
                        strength=min(10, abs(lt_score) // 5),
                        timeframe="long_term",
                        description=f"Macro trend: {lt_trend} ({long_term_analysis.get('candles_analyzed', 0)} candles)",
                    ))
            except Exception as e:
                logger.warning(f"Long-term analysis failed for {symbol}: {e}")

            # 7. Trend Duration Analysis (max +/- 15 points)
            try:
                trend_duration_analysis = self.trend_duration_tracker.analyze(candles)
                td_score = trend_duration_analysis.get("score", 0)
                td_phase = trend_duration_analysis.get("trend_phase", "unknown")

                # Scale to max weight
                td_contribution = min(TREND_DURATION_WEIGHT, abs(td_score))
                if td_score > 0:
                    td_contribution_signed = td_contribution
                    score += td_contribution
                elif td_score < 0:
                    td_contribution_signed = -td_contribution
                    score -= td_contribution

                if td_phase in ["early", "developing"]:
                    direction_str = trend_duration_analysis.get("trend_direction", "neutral")
                    signals.append(Signal(
                        name="trend_duration",
                        direction=direction_str if direction_str in ["bullish", "bearish"] else "neutral",
                        strength=8 if td_phase == "early" else 6,
                        timeframe="duration",
                        description=trend_duration_analysis.get("description", f"{td_phase} trend"),
                    ))
                elif td_phase == "extended":
                    # Extended trend = potential exhaustion
                    exhaustion = trend_duration_analysis.get("exhaustion_signals", [])
                    if exhaustion:
                        signals.append(Signal(
                            name="trend_exhaustion",
                            direction="neutral",
                            strength=5,
                            timeframe="duration",
                            description=f"Extended trend with exhaustion: {', '.join(exhaustion)}",
                        ))
            except Exception as e:
                logger.warning(f"Trend duration analysis failed for {symbol}: {e}")

            # 8. Higher Timeframe Bias (max +/- 20 points)
            try:
                higher_tf_analysis = self.higher_tf_bias.get_bias(symbol)
                htf_score = higher_tf_analysis.get("combined_score", 0)
                htf_bias = higher_tf_analysis.get("overall_bias", "NEUTRAL")

                # Scale to max weight
                htf_contribution = min(HIGHER_TF_BIAS_WEIGHT, abs(htf_score) * 0.5)
                if htf_score > 0:
                    htf_contribution_signed = htf_contribution
                    score += htf_contribution
                elif htf_score < 0:
                    htf_contribution_signed = -htf_contribution
                    score -= htf_contribution

                if htf_bias in ["STRONG_BULLISH", "BULLISH"]:
                    signals.append(Signal(
                        name="higher_tf_bias",
                        direction="bullish",
                        strength=10 if htf_bias == "STRONG_BULLISH" else 7,
                        timeframe="higher",
                        description=f"4H/Daily bias: {htf_bias}",
                    ))
                elif htf_bias in ["STRONG_BEARISH", "BEARISH"]:
                    signals.append(Signal(
                        name="higher_tf_bias",
                        direction="bearish",
                        strength=10 if htf_bias == "STRONG_BEARISH" else 7,
                        timeframe="higher",
                        description=f"4H/Daily bias: {htf_bias}",
                    ))
            except Exception as e:
                logger.warning(f"Higher TF bias analysis failed for {symbol}: {e}")

        # Track deep analysis component scores
        component_scores["long_term"] = lt_contribution_signed
        component_scores["trend_duration"] = td_contribution_signed
        component_scores["higher_tf"] = htf_contribution_signed

        # =============================================================================
        # SCORE NORMALIZATION (2026-01-10 Upgrade)
        # =============================================================================
        # score_raw = original unbounded sum (for debugging)
        # score_norm = normalized to [-100, +100] range for label decisions
        score_raw = score
        score_norm = max(-100.0, min(100.0, (score / PREDICTION_MAX_POSSIBLE_ABS) * 100.0))

        # Get top 3 components by absolute value
        sorted_components = sorted(component_scores.items(), key=lambda x: abs(x[1]), reverse=True)
        top_components = sorted_components[:3]

        # Determine initial direction using NORMALIZED score (score_norm)
        initial_direction = self._score_to_direction_normalized(score_norm)

        # Calculate candle volume for volume filter
        # Use last closed candle's volume (before we filtered incomplete candles)
        candle_volume_usdt = 0.0
        if candles:
            last_candle = candles[-1]
            candle_volume = float(last_candle.get("volume", 0))
            candle_price = float(last_candle.get("close", 0))
            candle_volume_usdt = candle_volume * candle_price

        # Apply all safeguards (consensus gate, volume filter, TF confirmation, hysteresis)
        direction, downgrades = self._apply_safeguards(
            symbol=symbol,
            timeframe=timeframe,
            direction=initial_direction,
            score_norm=score_norm,
            signals=signals,
            candle_volume_usdt=candle_volume_usdt,
        )

        # Calculate redesigned confidence (magnitude + agreement)
        confidence, magnitude_conf, agreement_conf = self._calculate_confidence_v2(
            score_norm, signals, direction
        )

        # Compact prediction logging
        top_comp_str = ", ".join([f"{k}:{v:+.1f}" for k, v in top_components])
        log_parts = [
            f"[{symbol}] Prediction: tf={timeframe}, raw={score_raw:.1f}, norm={score_norm:.1f}",
            f"label={direction}, conf={confidence}, top3=[{top_comp_str}]"
        ]
        if downgrades:
            log_parts.append(f"downgrades={downgrades}")
        logger.debug(" ".join(log_parts))

        # Build entry zones from S/R
        entry_zones = []
        if sr_levels.get("nearest_support"):
            s = sr_levels["nearest_support"]
            entry_zones.append(Zone(
                price_low=s["price"] * 0.998,
                price_high=s["price"] * 1.002,
                zone_type="support",
                strength=s.get("strength", 5),
            ))
        if sr_levels.get("nearest_resistance"):
            r = sr_levels["nearest_resistance"]
            entry_zones.append(Zone(
                price_low=r["price"] * 0.998,
                price_high=r["price"] * 1.002,
                zone_type="resistance",
                strength=r.get("strength", 5),
            ))

        return PredictionResult(
            direction=direction,
            confidence=confidence,
            score=round(score_norm, 2),  # Use normalized score for API consistency
            signals=signals,
            entry_zones=entry_zones,
            pattern_signals=pattern_signals,
            divergence_signals=rsi_divergence or {},
            sr_levels=sr_levels,
            trend_structure=trend_structure,
            timeframe_alignment=mtf_alignment,
            # NEW: Deep analysis results
            long_term_analysis=long_term_analysis,
            trend_duration=trend_duration_analysis,
            higher_tf_bias=higher_tf_analysis,
            candles_analyzed=candles_used,
            # Score normalization & confidence debug fields (2026-01-10)
            score_raw=round(score_raw, 2),
            score_norm=round(score_norm, 2),
            magnitude_conf=round(magnitude_conf, 2),
            agreement_conf=round(agreement_conf, 2),
            top_components=top_components,
        )

    def _score_to_direction(self, score: float) -> str:
        """Convert RAW score to direction label (legacy - kept for backward compat)."""
        if score >= STRONG_LONG_THRESHOLD:
            return "STRONG_LONG"
        elif score >= LONG_THRESHOLD:
            return "LONG"
        elif score <= STRONG_SHORT_THRESHOLD:
            return "STRONG_SHORT"
        elif score <= SHORT_THRESHOLD:
            return "SHORT"
        else:
            return "NEUTRAL"

    def _score_to_direction_normalized(self, score_norm: float) -> str:
        """Convert NORMALIZED score (-100 to +100) to direction label.
        
        Thresholds (configurable in strategy_config.py):
        - STRONG_LONG:  score_norm >= +70
        - LONG:         score_norm >= +40
        - NEUTRAL:      -40 < score_norm < +40
        - SHORT:        score_norm <= -40
        - STRONG_SHORT: score_norm <= -70
        """
        if score_norm >= PREDICTION_NORM_STRONG_THRESHOLD:
            return "STRONG_LONG"
        elif score_norm >= PREDICTION_NORM_MODERATE_THRESHOLD:
            return "LONG"
        elif score_norm <= -PREDICTION_NORM_STRONG_THRESHOLD:
            return "STRONG_SHORT"
        elif score_norm <= -PREDICTION_NORM_MODERATE_THRESHOLD:
            return "SHORT"
        else:
            return "NEUTRAL"

    def _calculate_confidence(self, score: float, signals: List[Signal]) -> int:
        """Calculate confidence based on score (legacy - kept for backward compat)."""
        base_confidence = min(100, abs(score))
        bullish_count = sum(1 for s in signals if s.direction == "bullish")
        bearish_count = sum(1 for s in signals if s.direction == "bearish")
        if score > 0 and bullish_count >= 3:
            base_confidence = min(100, base_confidence + 10)
        elif score < 0 and bearish_count >= 3:
            base_confidence = min(100, base_confidence + 10)
        return int(base_confidence)

    def _calculate_confidence_v2(
        self,
        score_norm: float,
        signals: List[Signal],
        direction: str,
    ) -> Tuple[int, float, float]:
        """Calculate confidence using magnitude + agreement formula.
        
        Returns:
            Tuple of (confidence, magnitude_conf, agreement_conf)
        
        Formula:
            confidence = 0.6 * magnitude_conf + 0.4 * agreement_conf
        
        Where:
            magnitude_conf = min(100, abs(score_norm))
            agreement_conf = % of signals aligned with direction (0-100)
        """
        # Magnitude confidence: how strong is the normalized score?
        magnitude_conf = min(100.0, abs(score_norm))
        
        # Agreement confidence: what % of signals agree with the direction?
        bullish_count = sum(1 for s in signals if s.direction == "bullish")
        bearish_count = sum(1 for s in signals if s.direction == "bearish")
        neutral_count = sum(1 for s in signals if s.direction == "neutral")
        total_signals = bullish_count + bearish_count + neutral_count
        
        if total_signals == 0:
            agreement_conf = 0.0
        elif direction in ("STRONG_LONG", "LONG"):
            agreement_conf = (bullish_count / total_signals) * 100.0
        elif direction in ("STRONG_SHORT", "SHORT"):
            agreement_conf = (bearish_count / total_signals) * 100.0
        else:  # NEUTRAL
            # For neutral, agreement = low directional bias
            max_directional = max(bullish_count, bearish_count)
            if total_signals > 0:
                # Higher agreement if signals are balanced
                agreement_conf = 100.0 - ((max_directional / total_signals) * 100.0)
            else:
                agreement_conf = 50.0
        
        # Combined confidence
        raw_confidence = (
            PREDICTION_CONFIDENCE_MAGNITUDE_WEIGHT * magnitude_conf +
            PREDICTION_CONFIDENCE_AGREEMENT_WEIGHT * agreement_conf
        )
        
        # Neutral cap: don't let NEUTRAL predictions have high confidence
        # unless agreement is very high (signals are truly balanced)
        if direction == "NEUTRAL":
            if agreement_conf < 70:  # Signals aren't balanced enough
                raw_confidence = min(raw_confidence, PREDICTION_NEUTRAL_CONFIDENCE_CAP)
        
        confidence = int(round(raw_confidence))
        return confidence, magnitude_conf, agreement_conf

    def _compute_rsi_series(self, candles: List[Dict[str, Any]], period: int = 14) -> List[float]:
        """Compute RSI for each candle in the series."""
        closes = [c["close"] for c in candles]
        if len(closes) < period + 1:
            return []

        rsi_values = []
        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(0, c) for c in changes]
        losses = [abs(min(0, c)) for c in changes]

        # Initialize with SMA
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period):
            rsi_values.append(50.0)  # Placeholder for early values

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

        return rsi_values

    # =========================================================================
    # STRONG SIGNAL SAFEGUARDS (2026-01-10)
    # =========================================================================

    def _apply_safeguards(
        self,
        symbol: str,
        timeframe: str,
        direction: str,
        score_norm: float,
        signals: List[Signal],
        candle_volume_usdt: float,
    ) -> Tuple[str, List[str]]:
        """
        Apply all 4 safeguards to the predicted direction.

        Args:
            symbol: Trading pair
            timeframe: Prediction timeframe
            direction: Initial direction from _score_to_direction_normalized
            score_norm: Normalized score (-100 to +100)
            signals: List of contributing signals
            candle_volume_usdt: Volume of the last candle in USDT

        Returns:
            Tuple of (final_direction, list_of_downgrade_reasons)
        """
        downgrades: List[str] = []
        final_direction = direction

        # 1. Consensus Gate (check first, may downgrade STRONG)
        final_direction, reason = self._apply_consensus_gate(
            final_direction, score_norm, signals
        )
        if reason:
            downgrades.append(reason)

        # 2. Volume Filter (block STRONG on low volume)
        final_direction, reason = self._apply_volume_filter(
            final_direction, candle_volume_usdt
        )
        if reason:
            downgrades.append(reason)

        # 3. Timeframe Confirmation (require consecutive STRONG on low TFs)
        final_direction, reason = self._apply_timeframe_confirmation(
            symbol, timeframe, final_direction
        )
        if reason:
            downgrades.append(reason)

        # 4. Hysteresis (anti-flapping, applied last)
        final_direction, reason = self._apply_hysteresis(
            symbol, timeframe, final_direction, score_norm
        )
        if reason:
            downgrades.append(reason)

        # Update previous label for next cycle
        self._previous_labels[(symbol, timeframe)] = final_direction

        return final_direction, downgrades

    def _apply_consensus_gate(
        self,
        direction: str,
        score_norm: float,
        signals: List[Signal],
    ) -> Tuple[str, Optional[str]]:
        """
        Gate: STRONG labels require 60% signal agreement.

        Rules:
        - STRONG_LONG only if bullish_count / total >= 60%
        - STRONG_SHORT only if bearish_count / total >= 60%
        - Otherwise downgrade to LONG/SHORT
        """
        if direction not in ("STRONG_LONG", "STRONG_SHORT"):
            return direction, None

        bullish_count = sum(1 for s in signals if s.direction == "bullish")
        bearish_count = sum(1 for s in signals if s.direction == "bearish")
        total_signals = len(signals)

        if total_signals == 0:
            # No signals = downgrade
            new_direction = "LONG" if direction == "STRONG_LONG" else "SHORT"
            return new_direction, f"consensus gate: no signals ({direction} → {new_direction})"

        if direction == "STRONG_LONG":
            consensus = bullish_count / total_signals
            if consensus < MIN_STRONG_SIGNAL_CONSENSUS:
                return "LONG", f"consensus gate: {consensus:.0%} bullish < {MIN_STRONG_SIGNAL_CONSENSUS:.0%} (STRONG_LONG → LONG)"

        elif direction == "STRONG_SHORT":
            consensus = bearish_count / total_signals
            if consensus < MIN_STRONG_SIGNAL_CONSENSUS:
                return "SHORT", f"consensus gate: {consensus:.0%} bearish < {MIN_STRONG_SIGNAL_CONSENSUS:.0%} (STRONG_SHORT → SHORT)"

        return direction, None

    def _apply_volume_filter(
        self,
        direction: str,
        candle_volume_usdt: float,
    ) -> Tuple[str, Optional[str]]:
        """
        Filter: Block STRONG labels when volume is insufficient.

        Rules:
        - If candle volume < MIN_STRONG_VOLUME_USDT, downgrade STRONG → normal
        """
        if direction not in ("STRONG_LONG", "STRONG_SHORT"):
            return direction, None

        if candle_volume_usdt < MIN_STRONG_VOLUME_USDT:
            new_direction = "LONG" if direction == "STRONG_LONG" else "SHORT"
            return new_direction, f"volume filter: ${candle_volume_usdt:,.0f} < ${MIN_STRONG_VOLUME_USDT:,.0f} ({direction} → {new_direction})"

        return direction, None

    def _apply_timeframe_confirmation(
        self,
        symbol: str,
        timeframe: str,
        direction: str,
    ) -> Tuple[str, Optional[str]]:
        """
        Confirmation: Require consecutive STRONG signals on low timeframes.

        Rules:
        - On 1m, 3m, 5m: STRONG requires 2 consecutive confirmations
        - On 15m+: No confirmation required
        """
        if direction not in ("STRONG_LONG", "STRONG_SHORT"):
            # Not STRONG - reset confirmation counter
            key_long = (symbol, timeframe, "STRONG_LONG")
            key_short = (symbol, timeframe, "STRONG_SHORT")
            self._strong_confirmation_state.pop(key_long, None)
            self._strong_confirmation_state.pop(key_short, None)
            return direction, None

        # Only apply to low timeframes
        if timeframe not in STRONG_CONFIRMATION_TIMEFRAMES:
            return direction, None

        key = (symbol, timeframe, direction)
        current_count = self._strong_confirmation_state.get(key, 0) + 1
        self._strong_confirmation_state[key] = current_count

        # Reset opposite direction counter
        opposite = "STRONG_SHORT" if direction == "STRONG_LONG" else "STRONG_LONG"
        self._strong_confirmation_state.pop((symbol, timeframe, opposite), None)

        if current_count < STRONG_CONFIRMATION_REQUIRED_COUNT:
            new_direction = "LONG" if direction == "STRONG_LONG" else "SHORT"
            return new_direction, f"TF confirmation: {current_count}/{STRONG_CONFIRMATION_REQUIRED_COUNT} on {timeframe}m ({direction} → {new_direction})"

        return direction, None

    def _apply_hysteresis(
        self,
        symbol: str,
        timeframe: str,
        direction: str,
        score_norm: float,
    ) -> Tuple[str, Optional[str]]:
        """
        Hysteresis: Prevent rapid label flipping (anti-whipsaw).

        Rules:
        - LONG → NEUTRAL requires score < 30
        - SHORT → NEUTRAL requires score > -30
        - STRONG_LONG → LONG requires score < 60
        - STRONG_SHORT → SHORT requires score > -60
        """
        key = (symbol, timeframe)
        prev_direction = self._previous_labels.get(key)

        if prev_direction is None:
            # First prediction for this (symbol, timeframe)
            return direction, None

        # Check if we're trying to change label
        if direction == prev_direction:
            return direction, None

        # Apply hysteresis rules
        # STRONG_LONG → LONG (downgrade)
        if prev_direction == "STRONG_LONG" and direction == "LONG":
            if score_norm >= PREDICTION_HYSTERESIS_STRONG_LONG_EXIT:
                return "STRONG_LONG", f"hysteresis: score {score_norm:.1f} >= {PREDICTION_HYSTERESIS_STRONG_LONG_EXIT} (keeping STRONG_LONG)"

        # STRONG_SHORT → SHORT (downgrade)
        if prev_direction == "STRONG_SHORT" and direction == "SHORT":
            if score_norm <= PREDICTION_HYSTERESIS_STRONG_SHORT_EXIT:
                return "STRONG_SHORT", f"hysteresis: score {score_norm:.1f} <= {PREDICTION_HYSTERESIS_STRONG_SHORT_EXIT} (keeping STRONG_SHORT)"

        # LONG → NEUTRAL (exit)
        if prev_direction == "LONG" and direction == "NEUTRAL":
            if score_norm >= PREDICTION_HYSTERESIS_LONG_EXIT:
                return "LONG", f"hysteresis: score {score_norm:.1f} >= {PREDICTION_HYSTERESIS_LONG_EXIT} (keeping LONG)"

        # SHORT → NEUTRAL (exit)
        if prev_direction == "SHORT" and direction == "NEUTRAL":
            if score_norm <= PREDICTION_HYSTERESIS_SHORT_EXIT:
                return "SHORT", f"hysteresis: score {score_norm:.1f} <= {PREDICTION_HYSTERESIS_SHORT_EXIT} (keeping SHORT)"

        return direction, None

