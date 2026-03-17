"""
Bybit Control Center - Whale Order Detection Service

Detects unusually large orders on the order book that may act as:
- Support walls (large bid orders below price)
- Resistance walls (large ask orders above price)

Whale orders often indicate institutional intent and can:
- Act as strong support/resistance levels
- Signal upcoming price moves when pulled
- Create liquidity traps for retail traders
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class WhaleDetectionService:
    """
    Service for detecting whale orders on the order book.
    """

    def __init__(self, bybit_client: Any):
        """
        Initialize Whale Detection service.

        Args:
            bybit_client: BybitClient for API calls
        """
        self.client = bybit_client
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_orderbook(
        self,
        symbol: str,
        limit: int = 50,
        cache_seconds: int = 5,
    ) -> Dict[str, Any]:
        """
        Get order book data for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            limit: Number of levels to fetch (max 200)
            cache_seconds: Cache duration

        Returns:
            Dict with bids and asks
        """
        now = time.time()
        cache_key = f"{symbol}_ob"

        # Check cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if now - cached.get("timestamp", 0) < cache_seconds:
                return {
                    "success": True,
                    "bids": cached.get("bids", []),
                    "asks": cached.get("asks", []),
                    "cached": True,
                }

        try:
            # Bybit Order Book endpoint
            params = {
                "category": "linear",
                "symbol": symbol,
                "limit": limit,
            }

            response = self.client._request("GET", "/v5/market/orderbook", params=params)

            if not response.get("success"):
                return {
                    "success": False,
                    "error": response.get("error", "API error"),
                    "bids": [],
                    "asks": [],
                }

            result = response.get("data", {})

            # Parse bids and asks: [[price, size], ...]
            bids = []
            for b in result.get("b", []):
                bids.append({
                    "price": float(b[0]),
                    "size": float(b[1]),
                    "value": float(b[0]) * float(b[1]),  # USD value
                })

            asks = []
            for a in result.get("a", []):
                asks.append({
                    "price": float(a[0]),
                    "size": float(a[1]),
                    "value": float(a[0]) * float(a[1]),  # USD value
                })

            # Cache result
            self._cache[cache_key] = {
                "bids": bids,
                "asks": asks,
                "timestamp": now,
            }

            return {
                "success": True,
                "bids": bids,
                "asks": asks,
                "cached": False,
            }

        except Exception as e:
            logger.warning(f"Failed to get orderbook for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "bids": [],
                "asks": [],
            }

    def detect_whale_orders(
        self,
        symbol: str,
        current_price: float,
        whale_threshold_usd: float = 50000,
        proximity_pct: float = 2.0,
        max_score: float = 20,
    ) -> Dict[str, Any]:
        """
        Detect whale orders near current price.

        Args:
            symbol: Trading pair
            current_price: Current market price
            whale_threshold_usd: Minimum USD value to consider "whale" order
            proximity_pct: Max distance from price to consider (%)
            max_score: Maximum score contribution

        Returns:
            Dict with whale analysis and score
        """
        ob_data = self.get_orderbook(symbol, limit=50)

        if not ob_data.get("success"):
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": f"Order book unavailable: {ob_data.get('error', 'unknown')}",
                "bid_walls": [],
                "ask_walls": [],
            }

        bids = ob_data.get("bids", [])
        asks = ob_data.get("asks", [])

        if not bids or not asks:
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": "No order book data",
                "bid_walls": [],
                "ask_walls": [],
            }

        # Calculate average order size for comparison
        all_values = [b["value"] for b in bids] + [a["value"] for a in asks]
        avg_value = sum(all_values) / len(all_values) if all_values else 0

        # Dynamic whale threshold: max of fixed threshold or 10x average
        effective_threshold = max(whale_threshold_usd, avg_value * 10)

        # Find bid walls (large buy orders below price)
        bid_walls = []
        for bid in bids:
            if current_price <= 0:
                continue
            distance_pct = ((current_price - bid["price"]) / current_price) * 100
            if distance_pct <= proximity_pct and bid["value"] >= effective_threshold:
                bid_walls.append({
                    "price": bid["price"],
                    "size": bid["size"],
                    "value": bid["value"],
                    "distance_pct": distance_pct,
                    "multiplier": bid["value"] / avg_value if avg_value > 0 else 1,
                })

        # Find ask walls (large sell orders above price)
        ask_walls = []
        for ask in asks:
            if current_price <= 0:
                continue
            distance_pct = ((ask["price"] - current_price) / current_price) * 100
            if distance_pct <= proximity_pct and ask["value"] >= effective_threshold:
                ask_walls.append({
                    "price": ask["price"],
                    "size": ask["size"],
                    "value": ask["value"],
                    "distance_pct": distance_pct,
                    "multiplier": ask["value"] / avg_value if avg_value > 0 else 1,
                })

        # Sort by value (largest first)
        bid_walls.sort(key=lambda x: x["value"], reverse=True)
        ask_walls.sort(key=lambda x: x["value"], reverse=True)

        # Calculate score based on wall imbalance
        total_bid_wall_value = sum(w["value"] for w in bid_walls)
        total_ask_wall_value = sum(w["value"] for w in ask_walls)

        score = 0
        signal = "NEUTRAL"
        reasons = []

        if total_bid_wall_value > 0 or total_ask_wall_value > 0:
            total_wall_value = total_bid_wall_value + total_ask_wall_value

            if total_wall_value > 0:
                # Imbalance: positive = more bid walls (bullish), negative = more ask walls (bearish)
                imbalance = (total_bid_wall_value - total_ask_wall_value) / total_wall_value

                # Scale score by imbalance
                score = imbalance * max_score

                # Boost score if walls are very close to price
                closest_bid_dist = min([w["distance_pct"] for w in bid_walls]) if bid_walls else 999
                closest_ask_dist = min([w["distance_pct"] for w in ask_walls]) if ask_walls else 999

                # Proximity boost (closer = stronger signal)
                if closest_bid_dist < 0.5 and score > 0:
                    score *= 1.3  # 30% boost for very close bid wall
                if closest_ask_dist < 0.5 and score < 0:
                    score *= 1.3  # 30% boost for very close ask wall

                # Cap score
                score = max(-max_score, min(max_score, score))

                # Determine signal
                if score >= max_score * 0.6:
                    signal = "STRONG_BULLISH"
                elif score >= max_score * 0.3:
                    signal = "BULLISH"
                elif score <= -max_score * 0.6:
                    signal = "STRONG_BEARISH"
                elif score <= -max_score * 0.3:
                    signal = "BEARISH"

        # Build reason string
        if bid_walls:
            largest_bid = bid_walls[0]
            reasons.append(f"Bid wall ${largest_bid['value']/1000:.0f}K @ {largest_bid['price']:.4f} ({largest_bid['distance_pct']:.1f}% below)")
        if ask_walls:
            largest_ask = ask_walls[0]
            reasons.append(f"Ask wall ${largest_ask['value']/1000:.0f}K @ {largest_ask['price']:.4f} ({largest_ask['distance_pct']:.1f}% above)")

        if not reasons:
            reasons.append("No whale orders detected nearby")

        return {
            "score": score,
            "signal": signal,
            "reason": " | ".join(reasons),
            "bid_walls": bid_walls[:3],  # Top 3 bid walls
            "ask_walls": ask_walls[:3],  # Top 3 ask walls
            "total_bid_wall_value": total_bid_wall_value,
            "total_ask_wall_value": total_ask_wall_value,
            "whale_threshold": effective_threshold,
            "avg_order_value": avg_value,
        }

    def get_whale_summary(
        self,
        symbol: str,
        current_price: float,
    ) -> Dict[str, Any]:
        """
        Get a summary of whale activity for dashboard display.

        Returns:
            Dict with whale detection summary
        """
        from config.strategy_config import (
            WHALE_THRESHOLD_USD,
            WHALE_PROXIMITY_PCT,
            WHALE_MAX_SCORE,
        )

        result = self.detect_whale_orders(
            symbol=symbol,
            current_price=current_price,
            whale_threshold_usd=WHALE_THRESHOLD_USD,
            proximity_pct=WHALE_PROXIMITY_PCT,
            max_score=WHALE_MAX_SCORE,
        )

        return {
            "success": True,
            "symbol": symbol,
            "score": result["score"],
            "signal": result["signal"],
            "reason": result["reason"],
            "bid_walls_count": len(result["bid_walls"]),
            "ask_walls_count": len(result["ask_walls"]),
            "total_bid_value": result["total_bid_wall_value"],
            "total_ask_value": result["total_ask_wall_value"],
            "largest_bid_wall": result["bid_walls"][0] if result["bid_walls"] else None,
            "largest_ask_wall": result["ask_walls"][0] if result["ask_walls"] else None,
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear orderbook cache."""
        if symbol:
            cache_key = f"{symbol}_ob"
            if cache_key in self._cache:
                del self._cache[cache_key]
        else:
            self._cache.clear()
