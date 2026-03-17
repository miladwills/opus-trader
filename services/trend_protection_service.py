"""
Bybit Control Center - Trend Protection Service

Detects strong trends and closes opposite-direction positions to prevent losses.
Uses multi-indicator confirmation (ADX, +DI/-DI, EMA slope, RSI) for trend detection.
"""

from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class TrendProtectionService:
    """
    Service for detecting trends and protecting against opposite positions.
    """

    def __init__(
        self,
        adx_trend_threshold: float = 25.0,
        di_dominance_threshold: float = 5.0,
        rsi_trend_threshold: float = 10.0,
        min_confidence_score: int = 60,
    ):
        """
        Initialize trend protection service.

        Args:
            adx_trend_threshold: ADX above this indicates strong trend
            di_dominance_threshold: +DI/-DI difference for trend confirmation
            rsi_trend_threshold: RSI distance from 50 for trend confirmation
            min_confidence_score: Minimum confidence score (0-100) to act
        """
        self.adx_trend_threshold = adx_trend_threshold
        self.di_dominance_threshold = di_dominance_threshold
        self.rsi_trend_threshold = rsi_trend_threshold
        self.min_confidence_score = min_confidence_score

    def detect_trend(
        self,
        symbol: str,
        indicators: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Detect trend direction and strength with confidence score.

        Strategy:
        1. ADX check - is there a trend at all?
        2. Directional Indicators (+DI, -DI) - which direction?
        3. EMA slope - is price moving with momentum?
        4. RSI - is there momentum?
        5. Combine signals into confidence score (0-100)

        Args:
            symbol: Trading symbol
            indicators: Dict containing adx, plus_di, minus_di, ema_20, ema_50, rsi, close

        Returns:
            Dict with:
            - trend_direction: str ("up", "down", "neutral")
            - confidence_score: int (0-100)
            - should_act: bool (True if confidence >= threshold)
            - reasons: List[str] (explanation of detection)
            - signals: Dict with individual signal scores
        """
        adx = indicators.get("adx")
        plus_di = indicators.get("plus_di")
        minus_di = indicators.get("minus_di")
        ema_20 = indicators.get("ema_20")
        ema_50 = indicators.get("ema_50")
        rsi = indicators.get("rsi")
        close = indicators.get("close")

        reasons = []
        signals = {}
        confidence_score = 0
        trend_direction = "neutral"

        # =====================================================================
        # SIGNAL 1: ADX - Is there a trend?
        # =====================================================================
        # Max 30 points for strong ADX
        if adx is None:
            reasons.append("No ADX data - cannot detect trend")
            return {
                "trend_direction": "neutral",
                "confidence_score": 0,
                "should_act": False,
                "reasons": reasons,
                "signals": {},
            }

        if adx >= self.adx_trend_threshold:
            adx_score = min(30, int((adx / 40.0) * 30))  # Scale: ADX 25-40+ = 0-30 points
            confidence_score += adx_score
            signals["adx"] = adx_score
            reasons.append(f"Strong trend detected: ADX={adx:.1f} >= {self.adx_trend_threshold}")
        else:
            signals["adx"] = 0
            reasons.append(f"Weak trend: ADX={adx:.1f} < {self.adx_trend_threshold}")
            # Return early if no trend detected by ADX
            return {
                "trend_direction": "neutral",
                "confidence_score": 0,
                "should_act": False,
                "reasons": reasons,
                "signals": signals,
            }

        # =====================================================================
        # SIGNAL 2: Directional Indicators (+DI, -DI) - Which direction?
        # =====================================================================
        # Max 25 points for strong directional dominance
        if plus_di is not None and minus_di is not None:
            di_diff = plus_di - minus_di
            di_abs_diff = abs(di_diff)

            if di_abs_diff >= self.di_dominance_threshold:
                # Determine direction
                if di_diff > 0:
                    trend_direction = "up"
                    reasons.append(f"Uptrend confirmed: +DI={plus_di:.1f} > -DI={minus_di:.1f} (diff={di_diff:.1f})")
                else:
                    trend_direction = "down"
                    reasons.append(f"Downtrend confirmed: -DI={minus_di:.1f} > +DI={plus_di:.1f} (diff={di_diff:.1f})")

                # Scale: DI diff 5-20+ = 0-25 points
                di_score = min(25, int((di_abs_diff / 20.0) * 25))
                confidence_score += di_score
                signals["di"] = di_score
            else:
                signals["di"] = 0
                reasons.append(f"Weak directional bias: +DI={plus_di:.1f}, -DI={minus_di:.1f} (diff={di_abs_diff:.1f} < {self.di_dominance_threshold})")
        else:
            signals["di"] = 0
            reasons.append("No DI data available")

        # =====================================================================
        # SIGNAL 3: EMA Slope - Is price moving with momentum?
        # =====================================================================
        # Max 20 points for strong EMA alignment
        if ema_20 is not None and ema_50 is not None and close is not None:
            if trend_direction == "up":
                # Check if price > EMA20 > EMA50 (bullish alignment)
                if close > ema_20 > ema_50:
                    ema_score = 20
                    confidence_score += ema_score
                    signals["ema"] = ema_score
                    reasons.append(f"EMA bullish alignment: Price={close:.8f} > EMA20={ema_20:.8f} > EMA50={ema_50:.8f}")
                elif close > ema_20:
                    ema_score = 10  # Partial credit
                    confidence_score += ema_score
                    signals["ema"] = ema_score
                    reasons.append(f"EMA partial bullish: Price={close:.8f} > EMA20={ema_20:.8f}")
                else:
                    signals["ema"] = 0
                    reasons.append("EMA not aligned with uptrend")

            elif trend_direction == "down":
                # Check if price < EMA20 < EMA50 (bearish alignment)
                if close < ema_20 < ema_50:
                    ema_score = 20
                    confidence_score += ema_score
                    signals["ema"] = ema_score
                    reasons.append(f"EMA bearish alignment: Price={close:.8f} < EMA20={ema_20:.8f} < EMA50={ema_50:.8f}")
                elif close < ema_20:
                    ema_score = 10  # Partial credit
                    confidence_score += ema_score
                    signals["ema"] = ema_score
                    reasons.append(f"EMA partial bearish: Price={close:.8f} < EMA20={ema_20:.8f}")
                else:
                    signals["ema"] = 0
                    reasons.append("EMA not aligned with downtrend")
        else:
            signals["ema"] = 0
            reasons.append("No EMA data available")

        # =====================================================================
        # SIGNAL 4: RSI - Is there momentum?
        # =====================================================================
        # Max 25 points for strong RSI momentum
        if rsi is not None:
            rsi_distance_from_50 = abs(rsi - 50)

            if trend_direction == "up" and rsi > 50:
                if rsi_distance_from_50 >= self.rsi_trend_threshold:
                    # Scale: RSI 60-80+ = 0-25 points
                    rsi_score = min(25, int(((rsi - 50) / 30.0) * 25))
                    confidence_score += rsi_score
                    signals["rsi"] = rsi_score
                    reasons.append(f"RSI bullish momentum: RSI={rsi:.1f} > 50 (distance={rsi_distance_from_50:.1f})")
                else:
                    signals["rsi"] = 0
                    reasons.append(f"RSI weak bullish: RSI={rsi:.1f} (distance={rsi_distance_from_50:.1f} < {self.rsi_trend_threshold})")

            elif trend_direction == "down" and rsi < 50:
                if rsi_distance_from_50 >= self.rsi_trend_threshold:
                    # Scale: RSI 20-40 = 0-25 points
                    rsi_score = min(25, int(((50 - rsi) / 30.0) * 25))
                    confidence_score += rsi_score
                    signals["rsi"] = rsi_score
                    reasons.append(f"RSI bearish momentum: RSI={rsi:.1f} < 50 (distance={rsi_distance_from_50:.1f})")
                else:
                    signals["rsi"] = 0
                    reasons.append(f"RSI weak bearish: RSI={rsi:.1f} (distance={rsi_distance_from_50:.1f} < {self.rsi_trend_threshold})")
            else:
                signals["rsi"] = 0
                reasons.append(f"RSI not aligned with {trend_direction}trend: RSI={rsi:.1f}")
        else:
            signals["rsi"] = 0
            reasons.append("No RSI data available")

        # =====================================================================
        # FINAL: Calculate confidence and determine if should act
        # =====================================================================
        should_act = confidence_score >= self.min_confidence_score

        if should_act:
            reasons.append(
                f"✅ HIGH CONFIDENCE TREND: {trend_direction.upper()} "
                f"(score={confidence_score}/100 >= {self.min_confidence_score})"
            )
        else:
            reasons.append(
                f"⚠️ LOW CONFIDENCE: {trend_direction} "
                f"(score={confidence_score}/100 < {self.min_confidence_score})"
            )

        return {
            "trend_direction": trend_direction,
            "confidence_score": confidence_score,
            "should_act": should_act,
            "reasons": reasons,
            "signals": signals,
        }

    def should_close_position(
        self,
        trend_result: Dict[str, Any],
        position_side: str,
        position_unrealized_pnl: float = 0,
    ) -> Dict[str, Any]:
        """
        Determine if a position should be closed based on trend detection.

        Args:
            trend_result: Result dict from detect_trend()
            position_side: Position side ("Buy" for long, "Sell" for short)
            position_unrealized_pnl: Current unrealized PnL (optional, for logging)

        Returns:
            Dict with:
            - should_close: bool (True if position opposes trend)
            - reason: str (explanation)
            - action: str ("close_long" or "close_short" or "hold")
        """
        trend_direction = trend_result.get("trend_direction")
        should_act = trend_result.get("should_act", False)
        confidence_score = trend_result.get("confidence_score", 0)

        if not should_act:
            return {
                "should_close": False,
                "reason": f"Trend confidence too low (score={confidence_score})",
                "action": "hold",
            }

        # Long position in downtrend = CLOSE
        if position_side == "Buy" and trend_direction == "down":
            return {
                "should_close": True,
                "reason": (
                    f"Long position against strong downtrend "
                    f"(confidence={confidence_score}/100, PnL=${position_unrealized_pnl:.2f})"
                ),
                "action": "close_long",
            }

        # Short position in uptrend = CLOSE
        if position_side == "Sell" and trend_direction == "up":
            return {
                "should_close": True,
                "reason": (
                    f"Short position against strong uptrend "
                    f"(confidence={confidence_score}/100, PnL=${position_unrealized_pnl:.2f})"
                ),
                "action": "close_short",
            }

        # Position aligned with trend = HOLD
        return {
            "should_close": False,
            "reason": f"Position aligned with {trend_direction}trend (confidence={confidence_score}/100)",
            "action": "hold",
        }
