"""
Bybit Control Center - Danger Zone Detection Service

Detects extreme market conditions that signal high risk:
- Extreme RSI (overbought/oversold)
- Extreme volatility (BBW%/ATR% spikes)
- Volume anomalies
- Price at range extremes
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class DangerZoneService:
    """
    Service for detecting dangerous market conditions.
    """

    def __init__(
        self,
        extreme_rsi_upper: float = 80.0,
        extreme_rsi_lower: float = 20.0,
        extreme_volatility_multiplier: float = 3.0,
        volume_spike_multiplier: float = 5.0,
        range_extreme_threshold_pct: float = 0.95,
    ):
        """
        Initialize danger zone detection service.

        Args:
            extreme_rsi_upper: RSI above this = overbought danger zone
            extreme_rsi_lower: RSI below this = oversold danger zone
            extreme_volatility_multiplier: Volatility spike threshold (e.g., 3x normal)
            volume_spike_multiplier: Volume spike threshold (e.g., 5x average)
            range_extreme_threshold_pct: Position in range >= this = at extreme (0.95 = 95%)
        """
        self.extreme_rsi_upper = extreme_rsi_upper
        self.extreme_rsi_lower = extreme_rsi_lower
        self.extreme_volatility_multiplier = extreme_volatility_multiplier
        self.volume_spike_multiplier = volume_spike_multiplier
        self.range_extreme_threshold_pct = range_extreme_threshold_pct

    def detect_danger_zones(
        self,
        symbol: str,
        indicators: Dict[str, Any],
        grid_lower: Optional[float] = None,
        grid_upper: Optional[float] = None,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Detect all danger zones with severity scoring.

        Args:
            symbol: Trading symbol
            indicators: Dict with RSI, ATR%, BBW%, volume, etc.
            grid_lower: Grid lower boundary (for range extreme check)
            grid_upper: Grid upper boundary (for range extreme check)
            current_price: Current price (for range extreme check)

        Returns:
            Dict with:
            - in_danger_zone: bool (True if any danger detected)
            - danger_level: str ("none", "low", "medium", "high", "extreme")
            - danger_score: int (0-100, cumulative danger score)
            - warnings: List[str] (all warnings)
            - zones: Dict with individual zone detection results
        """
        rsi = indicators.get("rsi")
        atr_pct = indicators.get("atr_pct")
        bbw_pct = indicators.get("bbw_pct")
        volume = indicators.get("volume")
        volume_sma = indicators.get("volume_sma")

        warnings = []
        danger_score = 0
        zones = {}

        # =================================================================
        # ZONE 1: Extreme RSI (Overbought/Oversold)
        # =================================================================
        if rsi is not None:
            if rsi >= self.extreme_rsi_upper:
                danger_points = min(30, int((rsi - self.extreme_rsi_upper) / 5) * 10)  # Max 30 points
                danger_score += danger_points
                warnings.append(f"OVERBOUGHT: RSI={rsi:.1f} >= {self.extreme_rsi_upper} (+{danger_points} danger)")
                zones["rsi"] = {
                    "danger": True,
                    "type": "overbought",
                    "value": rsi,
                    "threshold": self.extreme_rsi_upper,
                    "points": danger_points,
                }
            elif rsi <= self.extreme_rsi_lower:
                danger_points = min(30, int((self.extreme_rsi_lower - rsi) / 5) * 10)  # Max 30 points
                danger_score += danger_points
                warnings.append(f"OVERSOLD: RSI={rsi:.1f} <= {self.extreme_rsi_lower} (+{danger_points} danger)")
                zones["rsi"] = {
                    "danger": True,
                    "type": "oversold",
                    "value": rsi,
                    "threshold": self.extreme_rsi_lower,
                    "points": danger_points,
                }
            else:
                zones["rsi"] = {"danger": False, "value": rsi}
        else:
            zones["rsi"] = {"danger": False, "value": None, "missing": True}

        # =================================================================
        # ZONE 2: Extreme Volatility Spike
        # =================================================================
        # Check if current volatility is significantly higher than normal
        # (Requires historical average - simplified check here)
        if bbw_pct is not None:
            # Simplified: BBW% > 8% is considered extreme
            extreme_bbw_threshold = 0.08  # 8%
            if bbw_pct >= extreme_bbw_threshold:
                danger_points = min(25, int((bbw_pct / extreme_bbw_threshold) * 10))  # Max 25 points
                danger_score += danger_points
                warnings.append(f"EXTREME VOLATILITY: BBW={bbw_pct*100:.2f}% >= {extreme_bbw_threshold*100}% (+{danger_points} danger)")
                zones["volatility"] = {
                    "danger": True,
                    "type": "extreme_bbw",
                    "value": bbw_pct,
                    "threshold": extreme_bbw_threshold,
                    "points": danger_points,
                }
            else:
                zones["volatility"] = {"danger": False, "value": bbw_pct}
        elif atr_pct is not None:
            # Fallback to ATR%
            extreme_atr_threshold = 0.06  # 6%
            if atr_pct >= extreme_atr_threshold:
                danger_points = min(25, int((atr_pct / extreme_atr_threshold) * 10))  # Max 25 points
                danger_score += danger_points
                warnings.append(f"EXTREME VOLATILITY: ATR={atr_pct*100:.2f}% >= {extreme_atr_threshold*100}% (+{danger_points} danger)")
                zones["volatility"] = {
                    "danger": True,
                    "type": "extreme_atr",
                    "value": atr_pct,
                    "threshold": extreme_atr_threshold,
                    "points": danger_points,
                }
            else:
                zones["volatility"] = {"danger": False, "value": atr_pct}
        else:
            zones["volatility"] = {"danger": False, "value": None, "missing": True}

        # =================================================================
        # ZONE 3: Volume Spike Anomaly
        # =================================================================
        if volume is not None and volume_sma is not None and volume_sma > 0:
            volume_ratio = volume / volume_sma
            if volume_ratio >= self.volume_spike_multiplier:
                danger_points = min(20, int(volume_ratio / self.volume_spike_multiplier) * 10)  # Max 20 points
                danger_score += danger_points
                warnings.append(f"VOLUME SPIKE: {volume_ratio:.1f}x average volume (+{danger_points} danger)")
                zones["volume"] = {
                    "danger": True,
                    "type": "volume_spike",
                    "value": volume,
                    "average": volume_sma,
                    "ratio": volume_ratio,
                    "threshold": self.volume_spike_multiplier,
                    "points": danger_points,
                }
            else:
                zones["volume"] = {"danger": False, "ratio": volume_ratio}
        else:
            zones["volume"] = {"danger": False, "value": volume, "missing": True}

        # =================================================================
        # ZONE 4: Price at Range Extremes
        # =================================================================
        if grid_lower is not None and grid_upper is not None and current_price is not None:
            if grid_upper > grid_lower and current_price > 0:
                range_width = grid_upper - grid_lower
                price_from_lower = current_price - grid_lower
                position_in_range = price_from_lower / range_width

                # Check if at upper extreme (>= 95%)
                if position_in_range >= self.range_extreme_threshold_pct:
                    danger_points = 15
                    danger_score += danger_points
                    warnings.append(f"AT UPPER RANGE EXTREME: {position_in_range*100:.1f}% (+{danger_points} danger)")
                    zones["range"] = {
                        "danger": True,
                        "type": "upper_extreme",
                        "position": position_in_range,
                        "threshold": self.range_extreme_threshold_pct,
                        "points": danger_points,
                    }
                # Check if at lower extreme (<= 5%)
                elif position_in_range <= (1 - self.range_extreme_threshold_pct):
                    danger_points = 15
                    danger_score += danger_points
                    warnings.append(f"AT LOWER RANGE EXTREME: {position_in_range*100:.1f}% (+{danger_points} danger)")
                    zones["range"] = {
                        "danger": True,
                        "type": "lower_extreme",
                        "position": position_in_range,
                        "threshold": 1 - self.range_extreme_threshold_pct,
                        "points": danger_points,
                    }
                else:
                    zones["range"] = {"danger": False, "position": position_in_range}
            else:
                zones["range"] = {"danger": False, "invalid": True}
        else:
            zones["range"] = {"danger": False, "value": None, "missing": True}

        # =================================================================
        # FINAL: Determine danger level and recommendation
        # =================================================================
        in_danger_zone = danger_score > 0

        if danger_score >= 70:
            danger_level = "extreme"
            recommendation = "HALT ALL TRADING - Extreme danger detected"
        elif danger_score >= 50:
            danger_level = "high"
            recommendation = "Close positions, pause new entries"
        elif danger_score >= 30:
            danger_level = "medium"
            recommendation = "Reduce position size, tighten SL"
        elif danger_score >= 10:
            danger_level = "low"
            recommendation = "Proceed with caution"
        else:
            danger_level = "none"
            recommendation = "Normal conditions"

        return {
            "in_danger_zone": in_danger_zone,
            "danger_level": danger_level,
            "danger_score": danger_score,
            "warnings": warnings,
            "recommendation": recommendation,
            "zones": zones,
        }

    def should_pause_trading(
        self,
        danger_result: Dict[str, Any],
        pause_threshold_score: int = 50,
    ) -> Dict[str, Any]:
        """
        Determine if trading should be paused based on danger detection.

        Args:
            danger_result: Result from detect_danger_zones()
            pause_threshold_score: Danger score above this pauses trading

        Returns:
            Dict with:
            - should_pause: bool
            - reason: str
            - danger_level: str
            - score: int
        """
        danger_score = danger_result.get("danger_score", 0)
        danger_level = danger_result.get("danger_level", "none")

        if danger_score >= pause_threshold_score:
            warnings_str = "; ".join(danger_result.get("warnings", []))
            return {
                "should_pause": True,
                "reason": f"Danger score {danger_score}/100 >= {pause_threshold_score} threshold - {warnings_str}",
                "danger_level": danger_level,
                "score": danger_score,
            }

        return {
            "should_pause": False,
            "reason": f"Danger score {danger_score}/100 < {pause_threshold_score} threshold",
            "danger_level": danger_level,
            "score": danger_score,
        }
