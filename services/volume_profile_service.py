"""
Bybit Control Center - Volume Profile Service

Analyzes volume distribution across price levels to identify:
- High Volume Nodes (HVN) - Strong support/resistance zones
- Low Volume Nodes (LVN) - Price moves quickly through these
- Point of Control (POC) - Highest volume price level

High volume at a price level indicates strong buyer/seller interest,
making it likely to act as support or resistance.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class VolumeProfileService:
    """
    Service for analyzing volume distribution and identifying volume-based S/R levels.
    """

    def __init__(self, bybit_client: Any, indicator_service: Any = None):
        """
        Initialize Volume Profile service.

        Args:
            bybit_client: BybitClient for API calls
            indicator_service: IndicatorService for OHLCV data
        """
        self.client = bybit_client
        self.indicator_service = indicator_service
        self._cache: Dict[str, Dict[str, Any]] = {}

    def calculate_volume_profile(
        self,
        symbol: str,
        lookback: int = 100,
        num_bins: int = 20,
        timeframe: str = "15",
    ) -> Dict[str, Any]:
        """
        Calculate volume profile for a symbol.

        Args:
            symbol: Trading pair
            lookback: Number of candles to analyze
            num_bins: Number of price bins
            timeframe: Candle timeframe

        Returns:
            Dict with:
            - success: bool
            - profile: List of {price, volume, pct_of_total}
            - poc: float (Point of Control - highest volume price)
            - hvn_levels: List of high volume node prices
            - lvn_levels: List of low volume node prices
            - value_area_high: float
            - value_area_low: float
        """
        try:
            # Get OHLCV data
            if self.indicator_service:
                candles = self.indicator_service.get_ohlcv(symbol, timeframe, limit=lookback)
            else:
                # Fallback to direct API call
                kline_resp = self.client.get_kline(symbol=symbol, interval=timeframe, limit=lookback)
                if not kline_resp.get("success"):
                    return {"success": False, "error": kline_resp.get("error")}

                raw_klines = kline_resp.get("data", {}).get("list", [])
                candles = []
                for k in raw_klines:
                    candles.append({
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    })

            if not candles or len(candles) < 10:
                return {"success": False, "error": "Insufficient candle data"}

            # Find price range
            all_highs = [c["high"] for c in candles]
            all_lows = [c["low"] for c in candles]
            price_high = max(all_highs)
            price_low = min(all_lows)
            price_range = price_high - price_low

            if price_range <= 0:
                return {"success": False, "error": "Invalid price range"}

            # Create price bins
            bin_size = price_range / num_bins
            bins = defaultdict(float)  # price_bin -> total_volume

            # Distribute volume across price bins based on candle range
            for candle in candles:
                c_high = candle["high"]
                c_low = candle["low"]
                c_volume = candle["volume"]
                c_range = c_high - c_low

                if c_range <= 0:
                    # Flat candle - assign all volume to close price bin
                    bin_idx = int((candle["close"] - price_low) / bin_size)
                    bin_idx = min(bin_idx, num_bins - 1)
                    bin_price = price_low + (bin_idx + 0.5) * bin_size
                    bins[bin_price] += c_volume
                else:
                    # Distribute volume proportionally across touched bins
                    start_bin = int((c_low - price_low) / bin_size)
                    end_bin = int((c_high - price_low) / bin_size)
                    start_bin = max(0, start_bin)
                    end_bin = min(num_bins - 1, end_bin)

                    touched_bins = end_bin - start_bin + 1
                    if touched_bins <= 0:
                        continue
                    vol_per_bin = round(c_volume / touched_bins, 8)

                    for bin_idx in range(start_bin, end_bin + 1):
                        bin_price = price_low + (bin_idx + 0.5) * bin_size
                        bins[bin_price] += vol_per_bin

            # Convert to sorted list
            total_volume = sum(bins.values())
            profile = []
            for price, volume in sorted(bins.items()):
                profile.append({
                    "price": price,
                    "volume": volume,
                    "pct_of_total": round(volume / total_volume * 100, 4) if total_volume > 0 else 0,
                })

            # Find Point of Control (highest volume)
            poc_entry = max(profile, key=lambda x: x["volume"])
            poc = poc_entry["price"]

            # Calculate average volume per bin
            avg_volume = total_volume / len(profile) if profile else 0

            # Identify HVN (High Volume Nodes) - above average
            hvn_threshold = avg_volume * 1.5  # 50% above average
            hvn_levels = [p["price"] for p in profile if p["volume"] > hvn_threshold]

            # Identify LVN (Low Volume Nodes) - below average
            lvn_threshold = avg_volume * 0.5  # 50% below average
            lvn_levels = [p["price"] for p in profile if p["volume"] < lvn_threshold]

            # Calculate Value Area (70% of volume)
            sorted_by_vol = sorted(profile, key=lambda x: x["volume"], reverse=True)
            value_area_volume = 0
            value_area_target = total_volume * 0.7
            value_area_prices = []

            for entry in sorted_by_vol:
                if value_area_volume < value_area_target:
                    value_area_prices.append(entry["price"])
                    value_area_volume += entry["volume"]
                else:
                    break

            value_area_high = max(value_area_prices) if value_area_prices else price_high
            value_area_low = min(value_area_prices) if value_area_prices else price_low

            return {
                "success": True,
                "profile": profile,
                "poc": poc,
                "hvn_levels": hvn_levels,
                "lvn_levels": lvn_levels,
                "value_area_high": value_area_high,
                "value_area_low": value_area_low,
                "price_high": price_high,
                "price_low": price_low,
                "total_volume": total_volume,
            }

        except Exception as e:
            logger.warning(f"Failed to calculate volume profile for {symbol}: {e}")
            return {"success": False, "error": str(e)}

    def get_volume_signal(
        self,
        symbol: str,
        current_price: float,
        lookback: int = 100,
        hvn_threshold: float = 1.5,
        max_score: float = 15,
    ) -> Dict[str, Any]:
        """
        Get trading signal based on volume profile.

        Logic:
        - Price near HVN (support/resistance) = potential reversal zone
        - Price in LVN = likely to move quickly, follow trend
        - Price at POC = strong consolidation zone

        Args:
            symbol: Trading pair
            current_price: Current market price
            lookback: Candles to analyze
            hvn_threshold: Multiplier for HVN detection
            max_score: Maximum score contribution

        Returns:
            Dict with score, signal, and analysis
        """
        profile = self.calculate_volume_profile(symbol, lookback=lookback)

        if not profile.get("success"):
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": f"Volume profile unavailable: {profile.get('error')}",
            }

        poc = profile.get("poc", 0)
        hvn_levels = profile.get("hvn_levels", [])
        lvn_levels = profile.get("lvn_levels", [])
        value_area_high = profile.get("value_area_high", 0)
        value_area_low = profile.get("value_area_low", 0)
        price_range = profile.get("price_high", 0) - profile.get("price_low", 0)

        if price_range <= 0:
            return {"score": 0, "signal": "NEUTRAL", "reason": "Invalid price range"}

        score = 0
        signals = []
        proximity_threshold = price_range * 0.02  # 2% of range

        # Check proximity to POC (consolidation zone)
        if abs(current_price - poc) < proximity_threshold:
            signals.append(f"At POC ${poc:.4f}")
            # POC = consolidation, neutral signal

        # Check proximity to HVN levels (support/resistance)
        for hvn in hvn_levels:
            distance = current_price - hvn
            if abs(distance) < proximity_threshold:
                if distance > 0:
                    # Price just above HVN = support below
                    score += max_score * 0.4
                    signals.append(f"HVN support ${hvn:.4f}")
                else:
                    # Price just below HVN = resistance above
                    score -= max_score * 0.4
                    signals.append(f"HVN resistance ${hvn:.4f}")
                break  # Only count nearest HVN

        # Check if price in LVN (fast move zone)
        for lvn in lvn_levels:
            if abs(current_price - lvn) < proximity_threshold:
                signals.append(f"In LVN zone (fast move)")
                break

        # Check value area position
        if current_price > value_area_high:
            # Above value area = extended, potential pullback
            score -= max_score * 0.3
            signals.append("Above value area")
        elif current_price < value_area_low:
            # Below value area = undervalued, potential bounce
            score += max_score * 0.3
            signals.append("Below value area")

        # Determine signal direction
        if score > max_score * 0.3:
            signal = "BULLISH"
        elif score < -max_score * 0.3:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        return {
            "score": score,
            "signal": signal,
            "reason": ", ".join(signals) if signals else "No significant volume levels nearby",
            "poc": poc,
            "nearest_hvn": min(hvn_levels, key=lambda x: abs(x - current_price)) if hvn_levels else None,
            "value_area_high": value_area_high,
            "value_area_low": value_area_low,
        }

    def get_support_resistance_levels(
        self,
        symbol: str,
        lookback: int = 100,
    ) -> Dict[str, Any]:
        """
        Get volume-based support and resistance levels.

        Returns:
            Dict with support and resistance levels sorted by strength
        """
        profile = self.calculate_volume_profile(symbol, lookback=lookback)

        if not profile.get("success"):
            return {"success": False, "error": profile.get("error")}

        hvn_levels = profile.get("hvn_levels", [])
        poc = profile.get("poc", 0)

        # Sort HVN by volume (strongest first)
        profile_list = profile.get("profile", [])
        hvn_with_volume = []
        for hvn in hvn_levels:
            vol = next((p["volume"] for p in profile_list if abs(p["price"] - hvn) < 0.0001), 0)
            hvn_with_volume.append({"price": hvn, "volume": vol, "type": "HVN"})

        # Add POC as strongest level
        poc_vol = next((p["volume"] for p in profile_list if abs(p["price"] - poc) < 0.0001), 0)
        levels = [{"price": poc, "volume": poc_vol, "type": "POC"}] + hvn_with_volume

        # Sort by volume (strength)
        levels = sorted(levels, key=lambda x: x["volume"], reverse=True)

        return {
            "success": True,
            "levels": levels,
            "poc": poc,
            "value_area_high": profile.get("value_area_high"),
            "value_area_low": profile.get("value_area_low"),
        }
