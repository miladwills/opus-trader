"""
Bybit Control Center - Mean Reversion Detector Service

Identifies when price has deviated significantly from its mean (moving averages)
and is likely to revert back:

- Price far above EMAs = Overextended, likely to pull back (bearish signal)
- Price far below EMAs = Oversold, likely to bounce (bullish signal)

Combined with RSI extremes and Bollinger Band position for stronger signals.
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class MeanReversionService:
    """
    Service for detecting mean reversion opportunities.

    Mean reversion assumes prices tend to return to average levels after
    significant deviations. This is especially useful for grid trading.
    """

    # Default EMA periods for mean calculation
    DEFAULT_EMA_PERIODS = [20, 50, 100, 200]

    # Deviation thresholds (percentage from mean)
    DEVIATION_THRESHOLDS = {
        "extreme": 3.0,    # 3% deviation = extreme
        "strong": 2.0,     # 2% deviation = strong
        "moderate": 1.0,   # 1% deviation = moderate
        "weak": 0.5,       # 0.5% deviation = weak
    }

    def __init__(self, indicator_service: Any = None, bybit_client: Any = None):
        """
        Initialize Mean Reversion service.

        Args:
            indicator_service: IndicatorService for technical calculations
            bybit_client: BybitClient for API calls (fallback)
        """
        self.indicator_service = indicator_service
        self.client = bybit_client

    def calculate_deviation_from_ema(
        self,
        symbol: str,
        current_price: float,
        ema_period: int = 20,
    ) -> Dict[str, Any]:
        """
        Calculate price deviation from a specific EMA.

        Args:
            symbol: Trading pair
            current_price: Current market price
            ema_period: EMA period to use

        Returns:
            Dict with deviation data
        """
        try:
            if not self.indicator_service:
                return {
                    "success": False,
                    "error": "Indicator service not available",
                    "deviation_pct": 0,
                }

            # Get EMA value
            ema_data = self.indicator_service.get_ema(
                symbol=symbol,
                interval="15",
                period=ema_period,
            )

            if not ema_data.get("success") or not ema_data.get("ema"):
                return {
                    "success": False,
                    "error": f"Failed to get EMA{ema_period}",
                    "deviation_pct": 0,
                }

            ema_value = ema_data["ema"]
            if ema_value <= 0:
                return {
                    "success": False,
                    "error": "Invalid EMA value",
                    "ema_period": ema_period,
                    "deviation_pct": 0,
                }

            # Calculate deviation percentage
            deviation_pct = ((current_price - ema_value) / ema_value) * 100

            return {
                "success": True,
                "ema_period": ema_period,
                "ema_value": ema_value,
                "current_price": current_price,
                "deviation_pct": deviation_pct,
                "deviation_abs": abs(deviation_pct),
                "above_ema": current_price > ema_value,
            }

        except Exception as e:
            logger.warning(f"Failed to calculate EMA deviation for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "deviation_pct": 0,
            }

    def analyze_mean_reversion(
        self,
        symbol: str,
        current_price: float,
        ema_periods: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze mean reversion across multiple EMAs.

        Logic:
        - Calculate deviation from each EMA
        - Aggregate deviations for overall assessment
        - Identify if price is overextended

        Args:
            symbol: Trading pair
            current_price: Current price
            ema_periods: List of EMA periods to analyze

        Returns:
            Dict with comprehensive mean reversion analysis
        """
        if ema_periods is None:
            ema_periods = self.DEFAULT_EMA_PERIODS

        try:
            deviations = []
            total_deviation = 0
            ema_positions = {"above": 0, "below": 0}

            for period in ema_periods:
                dev_data = self.calculate_deviation_from_ema(
                    symbol=symbol,
                    current_price=current_price,
                    ema_period=period,
                )

                if dev_data.get("success"):
                    deviations.append({
                        "period": period,
                        "ema_value": dev_data["ema_value"],
                        "deviation_pct": dev_data["deviation_pct"],
                        "above_ema": dev_data["above_ema"],
                    })
                    total_deviation += dev_data["deviation_pct"]

                    if dev_data["above_ema"]:
                        ema_positions["above"] += 1
                    else:
                        ema_positions["below"] += 1

            if not deviations:
                return {
                    "success": False,
                    "error": "No EMA data available",
                }

            # Calculate average deviation
            avg_deviation = total_deviation / len(deviations)

            # Determine overextension level
            abs_avg = abs(avg_deviation)
            if abs_avg >= self.DEVIATION_THRESHOLDS["extreme"]:
                extension_level = "extreme"
            elif abs_avg >= self.DEVIATION_THRESHOLDS["strong"]:
                extension_level = "strong"
            elif abs_avg >= self.DEVIATION_THRESHOLDS["moderate"]:
                extension_level = "moderate"
            elif abs_avg >= self.DEVIATION_THRESHOLDS["weak"]:
                extension_level = "weak"
            else:
                extension_level = "normal"

            # Determine position relative to EMAs
            if ema_positions["above"] == len(deviations):
                ema_position = "above_all"
            elif ema_positions["below"] == len(deviations):
                ema_position = "below_all"
            else:
                ema_position = "mixed"

            return {
                "success": True,
                "current_price": current_price,
                "deviations": deviations,
                "avg_deviation_pct": avg_deviation,
                "extension_level": extension_level,
                "ema_position": ema_position,
                "emas_above": ema_positions["above"],
                "emas_below": ema_positions["below"],
                "is_overextended": extension_level in ["strong", "extreme"],
            }

        except Exception as e:
            logger.warning(f"Failed to analyze mean reversion for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_bollinger_deviation(
        self,
        symbol: str,
        current_price: float,
    ) -> Dict[str, Any]:
        """
        Calculate price position within Bollinger Bands.

        Returns position as percentage:
        - 100% = at upper band
        - 50% = at middle (SMA)
        - 0% = at lower band
        - >100% or <0% = outside bands (extreme)

        Args:
            symbol: Trading pair
            current_price: Current price

        Returns:
            Dict with BB position data
        """
        try:
            if not self.indicator_service:
                return {
                    "success": False,
                    "error": "Indicator service not available",
                }

            # Get Bollinger Bands
            bb_data = self.indicator_service.get_bbands(
                symbol=symbol,
                interval="15",
                period=20,
                std_dev=2.0,
            )

            if not bb_data.get("success"):
                return {
                    "success": False,
                    "error": "Failed to get Bollinger Bands",
                }

            upper = bb_data.get("upper_band", 0)
            middle = bb_data.get("middle_band", 0)
            lower = bb_data.get("lower_band", 0)

            if upper == lower:
                return {
                    "success": False,
                    "error": "Invalid Bollinger Bands",
                }

            # Calculate position as percentage
            bb_width = upper - lower
            position_pct = ((current_price - lower) / bb_width) * 100

            # Determine zone
            if position_pct > 100:
                zone = "above_upper"
            elif position_pct > 80:
                zone = "upper_zone"
            elif position_pct > 60:
                zone = "upper_mid"
            elif position_pct > 40:
                zone = "middle"
            elif position_pct > 20:
                zone = "lower_mid"
            elif position_pct > 0:
                zone = "lower_zone"
            else:
                zone = "below_lower"

            return {
                "success": True,
                "position_pct": position_pct,
                "zone": zone,
                "upper_band": upper,
                "middle_band": middle,
                "lower_band": lower,
                "bb_width": bb_width,
                "bb_width_pct": (bb_width / middle) * 100 if middle > 0 else 0,
                "is_outside_bands": position_pct > 100 or position_pct < 0,
            }

        except Exception as e:
            logger.warning(f"Failed to get BB deviation for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_mean_reversion_signal(
        self,
        symbol: str,
        current_price: float,
        max_score: float = 15,
    ) -> Dict[str, Any]:
        """
        Get trading signal based on mean reversion analysis.

        Logic:
        - Price far above mean + overbought = BEARISH (expect pullback)
        - Price far below mean + oversold = BULLISH (expect bounce)
        - Normal deviation = NEUTRAL

        Args:
            symbol: Trading pair
            current_price: Current price
            max_score: Maximum score contribution

        Returns:
            Dict with score, signal, and analysis
        """
        try:
            # Get EMA deviation analysis
            ema_analysis = self.analyze_mean_reversion(
                symbol=symbol,
                current_price=current_price,
            )

            if not ema_analysis.get("success"):
                return {
                    "score": 0,
                    "signal": "NEUTRAL",
                    "reason": f"Mean reversion data unavailable: {ema_analysis.get('error')}",
                }

            # Get Bollinger Band position
            bb_analysis = self.get_bollinger_deviation(
                symbol=symbol,
                current_price=current_price,
            )

            # Get RSI for confirmation
            rsi_value = None
            if self.indicator_service:
                rsi_data = self.indicator_service.get_rsi(symbol=symbol, interval="15")
                if rsi_data.get("success"):
                    rsi_value = rsi_data.get("rsi")

            score = 0
            signals = []

            avg_deviation = ema_analysis.get("avg_deviation_pct", 0)
            extension_level = ema_analysis.get("extension_level", "normal")

            # EMA deviation scoring
            # Positive deviation = above mean = bearish reversion
            # Negative deviation = below mean = bullish reversion
            if extension_level == "extreme":
                # Strong reversion expected
                if avg_deviation > 0:
                    score = -max_score * 0.6  # Bearish
                    signals.append(f"Extreme overextension ({avg_deviation:.1f}% above mean)")
                else:
                    score = max_score * 0.6  # Bullish
                    signals.append(f"Extreme oversold ({avg_deviation:.1f}% below mean)")

            elif extension_level == "strong":
                if avg_deviation > 0:
                    score = -max_score * 0.4
                    signals.append(f"Strong overextension ({avg_deviation:.1f}% above mean)")
                else:
                    score = max_score * 0.4
                    signals.append(f"Strong oversold ({avg_deviation:.1f}% below mean)")

            elif extension_level == "moderate":
                if avg_deviation > 0:
                    score = -max_score * 0.2
                    signals.append(f"Moderate deviation above mean ({avg_deviation:.1f}%)")
                else:
                    score = max_score * 0.2
                    signals.append(f"Moderate deviation below mean ({avg_deviation:.1f}%)")

            # Bollinger Band confirmation
            if bb_analysis.get("success"):
                bb_pos = bb_analysis.get("position_pct", 50)

                if bb_pos > 100 and avg_deviation > 0:
                    score *= 1.3  # Strengthen bearish signal
                    signals.append(f"Outside upper BB ({bb_pos:.0f}%)")
                elif bb_pos < 0 and avg_deviation < 0:
                    score *= 1.3  # Strengthen bullish signal
                    signals.append(f"Outside lower BB ({bb_pos:.0f}%)")
                elif bb_pos > 90:
                    signals.append(f"Near upper BB ({bb_pos:.0f}%)")
                elif bb_pos < 10:
                    signals.append(f"Near lower BB ({bb_pos:.0f}%)")

            # RSI confirmation
            if rsi_value is not None:
                if rsi_value > 70 and avg_deviation > 0:
                    score *= 1.2  # RSI confirms overbought
                    signals.append(f"RSI overbought ({rsi_value:.0f})")
                elif rsi_value < 30 and avg_deviation < 0:
                    score *= 1.2  # RSI confirms oversold
                    signals.append(f"RSI oversold ({rsi_value:.0f})")

            # Clamp score
            score = max(-max_score, min(max_score, score))

            # Determine signal
            if score > max_score * 0.3:
                signal = "BULLISH"  # Oversold, expect bounce
            elif score < -max_score * 0.3:
                signal = "BEARISH"  # Overbought, expect pullback
            else:
                signal = "NEUTRAL"

            return {
                "score": score,
                "signal": signal,
                "reason": ", ".join(signals) if signals else "Price near mean, no reversion signal",
                "avg_deviation_pct": avg_deviation,
                "extension_level": extension_level,
                "ema_position": ema_analysis.get("ema_position"),
                "bb_position_pct": bb_analysis.get("position_pct") if bb_analysis.get("success") else None,
                "bb_zone": bb_analysis.get("zone") if bb_analysis.get("success") else None,
                "rsi": rsi_value,
                "is_overextended": ema_analysis.get("is_overextended", False),
            }

        except Exception as e:
            logger.warning(f"Failed to get mean reversion signal for {symbol}: {e}")
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": f"Error: {str(e)}",
            }

    def get_reversion_target(
        self,
        symbol: str,
        current_price: float,
    ) -> Dict[str, Any]:
        """
        Estimate reversion targets based on EMA positions.

        Useful for setting take-profit levels in mean reversion trades.

        Args:
            symbol: Trading pair
            current_price: Current price

        Returns:
            Dict with potential reversion targets
        """
        try:
            ema_analysis = self.analyze_mean_reversion(
                symbol=symbol,
                current_price=current_price,
            )

            if not ema_analysis.get("success"):
                return {
                    "success": False,
                    "error": ema_analysis.get("error"),
                }

            deviations = ema_analysis.get("deviations", [])

            targets = []
            for dev in deviations:
                ema_value = dev["ema_value"]
                if current_price <= 0:
                    continue
                distance_pct = ((ema_value - current_price) / current_price) * 100

                targets.append({
                    "ema_period": dev["period"],
                    "target_price": ema_value,
                    "distance_pct": distance_pct,
                    "direction": "up" if ema_value > current_price else "down",
                })

            # Sort by distance (nearest first)
            targets.sort(key=lambda x: abs(x["distance_pct"]))

            return {
                "success": True,
                "current_price": current_price,
                "targets": targets,
                "nearest_target": targets[0] if targets else None,
            }

        except Exception as e:
            logger.warning(f"Failed to get reversion targets for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
            }
