"""
Bybit Control Center - Micro-Bias Detection Service

Detects slight directional drift in the market to help neutral mode
avoid accumulating inventory against the prevailing micro-trend.

Combines fast-moving signals:
- Order book imbalance (40%) - Leading indicator
- Price velocity (30%) - Short-term drift direction
- EMA9 slope (20%) - Smoothed momentum
- RSI distance from 50 (10%) - Momentum confirmation

Output: Score from -1.0 (bearish) to +1.0 (bullish)
- Score > threshold -> Bullish micro-bias (skip some Sell ENTRY orders)
- Score < -threshold -> Bearish micro-bias (skip some Buy ENTRY orders)
- Score in neutral zone -> No skipping
"""

import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MicroBiasService:
    """
    Service for detecting micro-directional bias in neutral mode.
    """

    def __init__(
        self,
        indicator_service,
        orderbook_service,
    ):
        """
        Initialize Micro-Bias service.

        Args:
            indicator_service: IndicatorService for price/technical data
            orderbook_service: OrderBookService for order book imbalance
        """
        self.indicator_service = indicator_service
        self.orderbook_service = orderbook_service
        self._cache: Dict[str, Dict[str, Any]] = {}  # symbol -> {data, timestamp}
        self._hysteresis: Dict[str, list] = {}  # symbol -> list of recent scores

    def calculate_bias(
        self,
        bot: Dict[str, Any],
        symbol: str,
        threshold: float = 0.30,
        strong_threshold: float = 0.50,
        skip_pct_moderate: float = 0.40,
        skip_pct_strong: float = 0.70,
        hysteresis_checks: int = 2,
        cache_seconds: int = 10,
    ) -> Dict[str, Any]:
        """
        Calculate micro-bias for a symbol.

        Args:
            bot: Bot configuration dict
            symbol: Trading pair (e.g., "BTCUSDT")
            threshold: Score threshold to trigger bias (default 0.30)
            strong_threshold: Score threshold for strong bias (default 0.50)
            skip_pct_moderate: Skip probability for moderate bias (default 0.40)
            skip_pct_strong: Skip probability for strong bias (default 0.70)
            hysteresis_checks: Consecutive readings required (default 2)
            cache_seconds: Cache duration (default 10s)

        Returns:
            Dict with:
                score: float (-1.0 to +1.0)
                direction: "BULLISH" | "BEARISH" | "NEUTRAL"
                skip_probability: float (0.0 to 1.0)
                components: Dict with individual signal contributions
                hysteresis_met: bool - whether hysteresis requirement is satisfied
        """
        now = time.time()

        # Check cache
        cache_key = symbol
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if now - cached.get("timestamp", 0) < cache_seconds:
                return cached.get("data", self._neutral_result())

        # Calculate component signals
        components = {}

        # 1. Order Book Imbalance (40% weight)
        ob_score = self._get_orderbook_signal(symbol)
        components["orderbook"] = {
            "raw": ob_score,
            "weighted": ob_score * 0.40,
            "weight": 0.40,
        }

        # 2. Price Velocity (30% weight) - use 1m data for fast response
        velocity_score = self._get_velocity_signal(symbol)
        components["velocity"] = {
            "raw": velocity_score,
            "weighted": velocity_score * 0.30,
            "weight": 0.30,
        }

        # 3. EMA9 Slope (20% weight)
        ema_score = self._get_ema_slope_signal(symbol)
        components["ema_slope"] = {
            "raw": ema_score,
            "weighted": ema_score * 0.20,
            "weight": 0.20,
        }

        # 4. RSI Distance from 50 (10% weight)
        rsi_score = self._get_rsi_signal(symbol)
        components["rsi"] = {
            "raw": rsi_score,
            "weighted": rsi_score * 0.10,
            "weight": 0.10,
        }

        # Calculate composite score
        raw_score = sum(c["weighted"] for c in components.values())

        # Clamp to [-1.0, +1.0]
        score = max(-1.0, min(1.0, raw_score))

        # Update hysteresis buffer
        if symbol not in self._hysteresis:
            self._hysteresis[symbol] = []
        self._hysteresis[symbol].append(score)
        # Keep only recent readings
        if len(self._hysteresis[symbol]) > hysteresis_checks + 2:
            self._hysteresis[symbol] = self._hysteresis[symbol][-(hysteresis_checks + 2):]

        # Check hysteresis requirement
        hysteresis_met = self._check_hysteresis(
            symbol, threshold, hysteresis_checks
        )

        # Determine direction and skip probability
        direction = "NEUTRAL"
        skip_probability = 0.0

        if hysteresis_met:
            if score >= strong_threshold:
                direction = "BULLISH"
                skip_probability = skip_pct_strong
            elif score >= threshold:
                direction = "BULLISH"
                skip_probability = skip_pct_moderate
            elif score <= -strong_threshold:
                direction = "BEARISH"
                skip_probability = skip_pct_strong
            elif score <= -threshold:
                direction = "BEARISH"
                skip_probability = skip_pct_moderate

        result = {
            "score": round(score, 4),
            "direction": direction,
            "skip_probability": skip_probability,
            "components": components,
            "hysteresis_met": hysteresis_met,
            "threshold": threshold,
            "strong_threshold": strong_threshold,
            "timestamp": now,
        }

        # Cache result
        self._cache[cache_key] = {
            "data": result,
            "timestamp": now,
        }

        # Log if significant bias detected
        if direction != "NEUTRAL":
            logger.debug(
                "[%s] MICRO_BIAS detected: direction=%s score=%.3f skip_prob=%.0f%% "
                "components=(ob=%.2f vel=%.2f ema=%.2f rsi=%.2f)",
                symbol,
                direction,
                score,
                skip_probability * 100,
                components["orderbook"]["raw"],
                components["velocity"]["raw"],
                components["ema_slope"]["raw"],
                components["rsi"]["raw"],
            )

        return result

    def _get_orderbook_signal(self, symbol: str) -> float:
        """
        Get order book imbalance signal normalized to [-1, +1].

        Positive = more bids (bullish)
        Negative = more asks (bearish)
        """
        try:
            imbalance_data = self.orderbook_service.calculate_imbalance(
                symbol, depth_levels=20
            )

            if not imbalance_data.get("success"):
                return 0.0

            # Imbalance is already in [-1, +1] range
            imbalance = imbalance_data.get("imbalance", 0)

            # Apply a slight amplification for stronger imbalances
            # but keep within bounds
            amplified = imbalance * 1.2
            return max(-1.0, min(1.0, amplified))

        except Exception as e:
            logger.debug("[%s] Orderbook signal error: %s", symbol, e)
            return 0.0

    def _get_velocity_signal(self, symbol: str) -> float:
        """
        Get price velocity signal normalized to [-1, +1].

        Uses 1-minute candles for fast response.
        Positive velocity = price rising (bullish)
        Negative velocity = price falling (bearish)
        """
        try:
            # Get 1-minute indicators for fast response
            indicators = self.indicator_service.compute_indicators(
                symbol, interval="1", limit=20
            )

            velocity = indicators.get("price_velocity")
            if velocity is None:
                return 0.0

            # Normalize: typical range is -0.02 to +0.02 per hour
            # Scale so 1%/hr = 0.5 score
            normalized = velocity * 50  # 0.02 * 50 = 1.0

            return max(-1.0, min(1.0, normalized))

        except Exception as e:
            logger.debug("[%s] Velocity signal error: %s", symbol, e)
            return 0.0

    def _get_ema_slope_signal(self, symbol: str) -> float:
        """
        Get EMA9 slope signal normalized to [-1, +1].

        Positive slope = upward momentum (bullish)
        Negative slope = downward momentum (bearish)
        """
        try:
            # Use 5-minute candles for EMA to smooth out noise
            indicators = self.indicator_service.compute_indicators(
                symbol, interval="5", limit=30
            )

            ema_slope = indicators.get("ema_slope")
            if ema_slope is None:
                return 0.0

            # Normalize: typical slope is -0.001 to +0.001 per candle
            # Scale so 0.1% change = 0.5 score
            normalized = ema_slope * 500  # 0.001 * 500 = 0.5

            return max(-1.0, min(1.0, normalized))

        except Exception as e:
            logger.debug("[%s] EMA slope signal error: %s", symbol, e)
            return 0.0

    def _get_rsi_signal(self, symbol: str) -> float:
        """
        Get RSI distance from 50 as signal normalized to [-1, +1].

        RSI > 50 = bullish momentum
        RSI < 50 = bearish momentum
        Distance from 50 indicates strength
        """
        try:
            # Use 5-minute candles
            indicators = self.indicator_service.compute_indicators(
                symbol, interval="5", limit=30
            )

            rsi = indicators.get("rsi")
            if rsi is None:
                return 0.0

            # Distance from 50: RSI 70 = +20, RSI 30 = -20
            distance = rsi - 50

            # Normalize: max distance is 50, scale to [-1, +1]
            # Use 20 points = 0.5 score (not max 50 to avoid extreme values)
            normalized = distance / 40  # 20/40 = 0.5

            return max(-1.0, min(1.0, normalized))

        except Exception as e:
            logger.debug("[%s] RSI signal error: %s", symbol, e)
            return 0.0

    def _check_hysteresis(
        self,
        symbol: str,
        threshold: float,
        required_checks: int,
    ) -> bool:
        """
        Check if hysteresis requirement is met.

        Requires `required_checks` consecutive readings in the same direction
        (all above threshold or all below -threshold).
        """
        if symbol not in self._hysteresis:
            return False

        history = self._hysteresis[symbol]
        if len(history) < required_checks:
            return False

        recent = history[-required_checks:]

        # Check if all recent readings are consistently bullish
        all_bullish = all(s >= threshold for s in recent)
        if all_bullish:
            return True

        # Check if all recent readings are consistently bearish
        all_bearish = all(s <= -threshold for s in recent)
        if all_bearish:
            return True

        return False

    def _neutral_result(self) -> Dict[str, Any]:
        """Return a neutral/default result."""
        return {
            "score": 0.0,
            "direction": "NEUTRAL",
            "skip_probability": 0.0,
            "components": {},
            "hysteresis_met": False,
            "threshold": 0.30,
            "strong_threshold": 0.50,
            "timestamp": time.time(),
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear cache and hysteresis for a symbol or all symbols."""
        if symbol:
            self._cache.pop(symbol, None)
            self._hysteresis.pop(symbol, None)
        else:
            self._cache.clear()
            self._hysteresis.clear()

    def get_cached_bias(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached bias without recalculating."""
        if symbol in self._cache:
            return self._cache[symbol].get("data")
        return None
