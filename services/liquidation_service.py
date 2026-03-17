"""
Bybit Control Center - Liquidation Level Awareness Service

Estimates liquidation price clusters based on:
- Common leverage levels (10x, 20x, 50x, 100x)
- Recent price action (swing highs/lows where positions likely opened)
- Open Interest changes to detect liquidation events

Liquidation cascades create strong price moves - knowing where they cluster
helps predict bounce/dump zones and avoid dangerous price levels.
"""

import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LiquidationService:
    """
    Service for estimating liquidation levels and detecting liquidation events.
    """

    # Common leverage levels used by traders
    LEVERAGE_LEVELS = [10, 20, 25, 50, 75, 100]

    # Maintenance margin rate (approximate for most symbols)
    MAINTENANCE_MARGIN_RATE = 0.005  # 0.5%

    def __init__(self, bybit_client: Any, indicator_service: Any = None):
        """
        Initialize Liquidation service.

        Args:
            bybit_client: BybitClient for API calls
            indicator_service: IndicatorService for price data
        """
        self.client = bybit_client
        self.indicator_service = indicator_service
        self._cache: Dict[str, Dict[str, Any]] = {}

    def estimate_liquidation_levels(
        self,
        symbol: str,
        current_price: float,
        lookback_candles: int = 50,
    ) -> Dict[str, Any]:
        """
        Estimate where liquidation clusters likely exist.

        Logic:
        - Find recent swing highs/lows (likely entry points)
        - Calculate liquidation prices for common leverage levels
        - Identify clusters of liquidation levels

        Args:
            symbol: Trading pair
            current_price: Current market price
            lookback_candles: Candles to analyze for swing points

        Returns:
            Dict with liquidation level estimates
        """
        try:
            # Get recent price data
            if self.indicator_service:
                candles = self.indicator_service.get_ohlcv(symbol, "15", limit=lookback_candles)
            else:
                kline_resp = self.client.get_kline(symbol=symbol, interval="15", limit=lookback_candles)
                if not kline_resp.get("success"):
                    return {"success": False, "error": kline_resp.get("error")}
                raw = kline_resp.get("data", {}).get("list", [])
                candles = [{"high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in raw]

            if not candles or len(candles) < 10:
                return {"success": False, "error": "Insufficient price data"}

            # Find swing highs and lows (potential entry zones)
            swing_highs = []
            swing_lows = []

            for i in range(2, len(candles) - 2):
                high = candles[i]["high"]
                low = candles[i]["low"]

                # Swing high: higher than 2 candles before and after
                if (high > candles[i-1]["high"] and high > candles[i-2]["high"] and
                    high > candles[i+1]["high"] and high > candles[i+2]["high"]):
                    swing_highs.append(high)

                # Swing low: lower than 2 candles before and after
                if (low < candles[i-1]["low"] and low < candles[i-2]["low"] and
                    low < candles[i+1]["low"] and low < candles[i+2]["low"]):
                    swing_lows.append(low)

            # Calculate liquidation levels for each entry point and leverage
            long_liquidations = []  # Prices where longs get liquidated (below entry)
            short_liquidations = []  # Prices where shorts get liquidated (above entry)

            for entry in swing_lows[-5:]:  # Recent swing lows = long entries
                for leverage in self.LEVERAGE_LEVELS:
                    liq_price = self._calculate_long_liquidation(entry, leverage)
                    if liq_price > 0:
                        long_liquidations.append({
                            "price": liq_price,
                            "entry": entry,
                            "leverage": leverage,
                            "distance_pct": (current_price - liq_price) / current_price * 100,
                        })

            for entry in swing_highs[-5:]:  # Recent swing highs = short entries
                for leverage in self.LEVERAGE_LEVELS:
                    liq_price = self._calculate_short_liquidation(entry, leverage)
                    if liq_price > 0:
                        short_liquidations.append({
                            "price": liq_price,
                            "entry": entry,
                            "leverage": leverage,
                            "distance_pct": (liq_price - current_price) / current_price * 100,
                        })

            # Find clusters (multiple liquidation levels near each other)
            long_clusters = self._find_clusters(long_liquidations, current_price, threshold_pct=0.5)
            short_clusters = self._find_clusters(short_liquidations, current_price, threshold_pct=0.5)

            # Find nearest significant levels
            nearest_long_liq = min(long_liquidations, key=lambda x: abs(x["distance_pct"])) if long_liquidations else None
            nearest_short_liq = min(short_liquidations, key=lambda x: abs(x["distance_pct"])) if short_liquidations else None

            return {
                "success": True,
                "current_price": current_price,
                "long_liquidations": sorted(long_liquidations, key=lambda x: x["price"], reverse=True)[:10],
                "short_liquidations": sorted(short_liquidations, key=lambda x: x["price"])[:10],
                "long_clusters": long_clusters,
                "short_clusters": short_clusters,
                "nearest_long_liq": nearest_long_liq,
                "nearest_short_liq": nearest_short_liq,
                "swing_highs": swing_highs[-5:],
                "swing_lows": swing_lows[-5:],
            }

        except Exception as e:
            logger.warning(f"Failed to estimate liquidation levels for {symbol}: {e}")
            return {"success": False, "error": str(e)}

    def _calculate_long_liquidation(self, entry_price: float, leverage: int) -> float:
        """Calculate liquidation price for a long position."""
        # Liq Price (Long) = Entry * (1 - 1/Leverage + MMR)
        # Simplified: Entry * (1 - 1/Leverage)
        if leverage <= 0:
            return 0
        return entry_price * (1 - 1/leverage + self.MAINTENANCE_MARGIN_RATE)

    def _calculate_short_liquidation(self, entry_price: float, leverage: int) -> float:
        """Calculate liquidation price for a short position."""
        # Liq Price (Short) = Entry * (1 + 1/Leverage - MMR)
        if leverage <= 0:
            return 0
        return entry_price * (1 + 1/leverage - self.MAINTENANCE_MARGIN_RATE)

    def _find_clusters(
        self,
        liquidations: List[Dict],
        current_price: float,
        threshold_pct: float = 0.5,
    ) -> List[Dict]:
        """Find clusters of liquidation levels (multiple levels within threshold)."""
        if not liquidations:
            return []

        clusters = []
        sorted_liqs = sorted(liquidations, key=lambda x: x["price"])

        i = 0
        while i < len(sorted_liqs):
            cluster_start = sorted_liqs[i]["price"]
            cluster_items = [sorted_liqs[i]]

            j = i + 1
            while j < len(sorted_liqs):
                if cluster_start <= 0:
                    break
                price_diff_pct = abs(sorted_liqs[j]["price"] - cluster_start) / cluster_start * 100
                if price_diff_pct <= threshold_pct:
                    cluster_items.append(sorted_liqs[j])
                    j += 1
                else:
                    break

            if len(cluster_items) >= 2:  # At least 2 levels to be a cluster
                avg_price = sum(item["price"] for item in cluster_items) / len(cluster_items)
                clusters.append({
                    "price": avg_price,
                    "count": len(cluster_items),
                    "leverages": list(set(item["leverage"] for item in cluster_items)),
                    "distance_pct": (avg_price - current_price) / current_price * 100 if current_price > 0 else 0,
                })

            i = j

        return sorted(clusters, key=lambda x: x["count"], reverse=True)[:3]

    def get_liquidation_signal(
        self,
        symbol: str,
        current_price: float,
        danger_zone_pct: float = 2.0,
        target_zone_pct: float = 5.0,
        max_score: float = 15,
    ) -> Dict[str, Any]:
        """
        Get trading signal based on liquidation level proximity.

        Logic:
        - Price near long liquidation cluster = potential bounce (bullish)
        - Price near short liquidation cluster = potential dump (bearish)
        - If we're IN a danger zone, signal caution

        Args:
            symbol: Trading pair
            current_price: Current price
            danger_zone_pct: Distance to be considered "in danger zone"
            target_zone_pct: Distance for liquidation clusters to be relevant
            max_score: Maximum score contribution

        Returns:
            Dict with score, signal, and analysis
        """
        liq_data = self.estimate_liquidation_levels(symbol, current_price)

        if not liq_data.get("success"):
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": f"Liquidation data unavailable: {liq_data.get('error')}",
            }

        score = 0
        signals = []

        # Check proximity to long liquidation clusters (support - bullish)
        long_clusters = liq_data.get("long_clusters", [])
        for cluster in long_clusters:
            distance = cluster["distance_pct"]
            if 0 < distance <= target_zone_pct:  # Cluster below current price
                # Closer = stronger signal
                strength = (target_zone_pct - distance) / target_zone_pct
                cluster_score = max_score * 0.5 * strength * (cluster["count"] / 3)
                score += cluster_score
                signals.append(f"Long liq cluster {distance:.1f}% below ({cluster['count']} levels)")

        # Check proximity to short liquidation clusters (resistance - bearish)
        short_clusters = liq_data.get("short_clusters", [])
        for cluster in short_clusters:
            distance = abs(cluster["distance_pct"])
            if 0 < distance <= target_zone_pct:  # Cluster above current price
                strength = (target_zone_pct - distance) / target_zone_pct
                cluster_score = -max_score * 0.5 * strength * (cluster["count"] / 3)
                score += cluster_score
                signals.append(f"Short liq cluster {distance:.1f}% above ({cluster['count']} levels)")

        # Check for nearest liquidation levels
        nearest_long = liq_data.get("nearest_long_liq")
        nearest_short = liq_data.get("nearest_short_liq")

        if nearest_long and 0 < nearest_long["distance_pct"] <= danger_zone_pct:
            # Very close to long liquidations - could cascade down then bounce
            signals.append(f"⚠️ Near long liq zone ({nearest_long['distance_pct']:.1f}%)")

        if nearest_short and 0 < abs(nearest_short["distance_pct"]) <= danger_zone_pct:
            # Very close to short liquidations - could cascade up then dump
            signals.append(f"⚠️ Near short liq zone ({abs(nearest_short['distance_pct']):.1f}%)")

        # Determine overall signal
        if score > max_score * 0.3:
            signal = "BULLISH"
        elif score < -max_score * 0.3:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        return {
            "score": score,
            "signal": signal,
            "reason": ", ".join(signals) if signals else "No significant liquidation levels nearby",
            "long_clusters": long_clusters,
            "short_clusters": short_clusters,
            "nearest_long_liq": nearest_long,
            "nearest_short_liq": nearest_short,
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear cache."""
        if symbol:
            keys_to_remove = [k for k in self._cache if k.startswith(symbol)]
            for k in keys_to_remove:
                del self._cache[k]
        else:
            self._cache.clear()
