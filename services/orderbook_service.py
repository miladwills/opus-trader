"""
Bybit Control Center - Order Book Imbalance Service

Analyzes order book depth to detect buying/selling pressure:
- Heavy bids (buy orders) = Bullish pressure, support below
- Heavy asks (sell orders) = Bearish pressure, resistance above

Order book imbalance is a leading indicator - it shows where
liquidity is positioned before price moves there.
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class OrderBookService:
    """
    Service for analyzing order book depth and imbalance.
    """

    def __init__(self, bybit_client: Any):
        """
        Initialize Order Book service.

        Args:
            bybit_client: BybitClient for API calls
        """
        self.client = bybit_client
        self._cache: Dict[str, Dict[str, Any]] = {}  # symbol -> {data, timestamp}

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
            limit: Number of price levels (1-200)
            cache_seconds: Cache duration (order book changes fast)

        Returns:
            Dict with bids, asks, and metadata
        """
        now = time.time()
        cache_key = f"{symbol}_{limit}"
        stream_service = getattr(self.client, "stream_service", None)
        if stream_service:
            try:
                stream_service.ensure_symbol(symbol, include_orderbook=True)
                snapshot = stream_service.get_orderbook_snapshot(symbol, limit=limit)
                if snapshot:
                    return {
                        "success": True,
                        "data": snapshot,
                        "cached": False,
                        "from_stream": True,
                    }
            except Exception as exc:
                logger.debug("Orderbook stream fallback for %s failed: %s", symbol, exc)

        # Check cache (short TTL for order book)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if now - cached.get("timestamp", 0) < cache_seconds:
                return {
                    "success": True,
                    "data": cached.get("data", {}),
                    "cached": True,
                }

        try:
            # Bybit Order Book endpoint
            # GET /v5/market/orderbook
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
                    "data": {},
                }

            result = response.get("data", {})

            # Parse bids and asks
            # Format: [[price, size], [price, size], ...]
            bids_raw = result.get("b", [])  # Bids (buy orders)
            asks_raw = result.get("a", [])  # Asks (sell orders)

            bids = []
            for item in bids_raw:
                if len(item) >= 2:
                    bids.append({
                        "price": float(item[0]),
                        "size": float(item[1]),
                    })

            asks = []
            for item in asks_raw:
                if len(item) >= 2:
                    asks.append({
                        "price": float(item[0]),
                        "size": float(item[1]),
                    })

            data = {
                "bids": bids,
                "asks": asks,
                "timestamp": int(result.get("ts", 0)),
                "update_id": result.get("u", 0),
            }

            # Cache result
            self._cache[cache_key] = {
                "data": data,
                "timestamp": now,
            }

            return {
                "success": True,
                "data": data,
                "cached": False,
            }

        except Exception as e:
            logger.warning(f"Failed to get order book for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": {},
            }

    def calculate_imbalance(
        self,
        symbol: str,
        depth_levels: int = 20,
        depth_pct: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Calculate order book imbalance ratio.

        Imbalance = (Bid Volume - Ask Volume) / (Bid Volume + Ask Volume)
        - Positive = More bids (bullish)
        - Negative = More asks (bearish)

        Args:
            symbol: Trading pair
            depth_levels: Number of price levels to analyze
            depth_pct: Alternative: analyze orders within X% of mid price

        Returns:
            Dict with imbalance ratio and analysis
        """
        ob_data = self.get_orderbook(symbol, limit=depth_levels)

        if not ob_data.get("success"):
            return {
                "success": False,
                "error": ob_data.get("error"),
                "imbalance": 0,
            }

        data = ob_data.get("data", {})
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return {
                "success": False,
                "error": "Empty order book",
                "imbalance": 0,
            }

        # Calculate total volume on each side
        bid_volume = sum(b["size"] for b in bids)
        ask_volume = sum(a["size"] for a in asks)

        total_volume = bid_volume + ask_volume
        if total_volume <= 0:
            return {
                "success": False,
                "error": "No volume in order book",
                "imbalance": 0,
            }

        # Imbalance ratio: -1 (all asks) to +1 (all bids)
        imbalance = (bid_volume - ask_volume) / total_volume

        # Calculate bid/ask ratio (alternative metric)
        bid_ask_ratio = bid_volume / ask_volume if ask_volume > 0 else float('inf')

        # Get best bid/ask for spread calculation
        best_bid = bids[0]["price"] if bids else 0
        best_ask = asks[0]["price"] if asks else 0
        mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
        spread_pct = ((best_ask - best_bid) / mid_price * 100) if mid_price > 0 else 0

        # Calculate volume-weighted average prices
        bid_vwap = sum(b["price"] * b["size"] for b in bids) / bid_volume if bid_volume > 0 else 0
        ask_vwap = sum(a["price"] * a["size"] for a in asks) / ask_volume if ask_volume > 0 else 0

        return {
            "success": True,
            "imbalance": imbalance,  # -1 to +1
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "bid_ask_ratio": bid_ask_ratio,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
            "spread_pct": spread_pct,
            "bid_vwap": bid_vwap,
            "ask_vwap": ask_vwap,
            "levels_analyzed": min(len(bids), len(asks)),
        }

    def get_imbalance_signal(
        self,
        symbol: str,
        depth_levels: int = 20,
        weak_threshold: float = 0.15,
        strong_threshold: float = 0.35,
        extreme_threshold: float = 0.55,
        max_score: float = 15,
    ) -> Dict[str, Any]:
        """
        Get trading signal based on order book imbalance.

        Logic:
        - Strong bid imbalance (>0.35) = BULLISH (buyers dominating)
        - Strong ask imbalance (<-0.35) = BEARISH (sellers dominating)
        - Extreme imbalance (>0.55) = STRONG signal
        - Weak imbalance = NEUTRAL

        Args:
            symbol: Trading pair
            depth_levels: Order book depth to analyze
            weak_threshold: Min imbalance for weak signal (0.15 = 15%)
            strong_threshold: Imbalance for strong signal (0.35 = 35%)
            extreme_threshold: Imbalance for extreme signal (0.55 = 55%)
            max_score: Maximum score contribution

        Returns:
            Dict with score, signal, and analysis
        """
        imbalance_data = self.calculate_imbalance(symbol, depth_levels=depth_levels)

        if not imbalance_data.get("success"):
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": f"Order book unavailable: {imbalance_data.get('error')}",
                "imbalance": 0,
            }

        imbalance = imbalance_data.get("imbalance", 0)
        bid_ask_ratio = imbalance_data.get("bid_ask_ratio", 1)
        spread_pct = imbalance_data.get("spread_pct", 0)

        score = 0
        signal = "NEUTRAL"
        reason = ""

        # Check for wide spread (illiquid market) - reduce confidence
        spread_penalty = 1.0
        if spread_pct > 0.1:  # >0.1% spread
            spread_penalty = 0.5
            reason = f"Wide spread ({spread_pct:.3f}%), "

        abs_imbalance = abs(imbalance)

        if abs_imbalance >= extreme_threshold:
            # Extreme imbalance
            if imbalance > 0:
                score = max_score * spread_penalty
                signal = "STRONG_BULLISH"
                reason += f"Extreme bid pressure: {imbalance*100:.1f}% imbalance (ratio {bid_ask_ratio:.2f}x)"
            else:
                score = -max_score * spread_penalty
                signal = "STRONG_BEARISH"
                reason += f"Extreme ask pressure: {imbalance*100:.1f}% imbalance (ratio {1/bid_ask_ratio:.2f}x)"

        elif abs_imbalance >= strong_threshold:
            # Strong imbalance
            if imbalance > 0:
                score = max_score * 0.7 * spread_penalty
                signal = "BULLISH"
                reason += f"Strong bid pressure: {imbalance*100:.1f}% imbalance"
            else:
                score = -max_score * 0.7 * spread_penalty
                signal = "BEARISH"
                reason += f"Strong ask pressure: {imbalance*100:.1f}% imbalance"

        elif abs_imbalance >= weak_threshold:
            # Weak imbalance
            if imbalance > 0:
                score = max_score * 0.3 * spread_penalty
                signal = "WEAK_BULLISH"
                reason += f"Mild bid pressure: {imbalance*100:.1f}% imbalance"
            else:
                score = -max_score * 0.3 * spread_penalty
                signal = "WEAK_BEARISH"
                reason += f"Mild ask pressure: {imbalance*100:.1f}% imbalance"

        else:
            signal = "NEUTRAL"
            reason += f"Balanced order book: {imbalance*100:.1f}% imbalance"

        return {
            "score": score,
            "signal": signal,
            "reason": reason,
            "imbalance": imbalance,
            "imbalance_pct": imbalance * 100,
            "bid_ask_ratio": bid_ask_ratio,
            "bid_volume": imbalance_data.get("bid_volume", 0),
            "ask_volume": imbalance_data.get("ask_volume", 0),
            "spread_pct": spread_pct,
            "mid_price": imbalance_data.get("mid_price", 0),
        }

    def get_wall_detection(
        self,
        symbol: str,
        depth_levels: int = 50,
        wall_multiplier: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Detect large "walls" in the order book (big orders that act as S/R).

        A wall is a price level with significantly more volume than average.

        Args:
            symbol: Trading pair
            depth_levels: Order book depth to analyze
            wall_multiplier: Volume must be X times average to be a wall

        Returns:
            Dict with detected bid/ask walls
        """
        ob_data = self.get_orderbook(symbol, limit=depth_levels)

        if not ob_data.get("success"):
            return {
                "success": False,
                "error": ob_data.get("error"),
                "bid_walls": [],
                "ask_walls": [],
            }

        data = ob_data.get("data", {})
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        # Calculate average volume per level
        bid_volumes = [b["size"] for b in bids]
        ask_volumes = [a["size"] for a in asks]

        avg_bid_vol = sum(bid_volumes) / len(bid_volumes) if bid_volumes else 0
        avg_ask_vol = sum(ask_volumes) / len(ask_volumes) if ask_volumes else 0

        # Find walls (levels with volume > multiplier * average)
        bid_walls = []
        for b in bids:
            if b["size"] >= avg_bid_vol * wall_multiplier:
                bid_walls.append({
                    "price": b["price"],
                    "size": b["size"],
                    "multiplier": b["size"] / avg_bid_vol if avg_bid_vol > 0 else 0,
                })

        ask_walls = []
        for a in asks:
            if a["size"] >= avg_ask_vol * wall_multiplier:
                ask_walls.append({
                    "price": a["price"],
                    "size": a["size"],
                    "multiplier": a["size"] / avg_ask_vol if avg_ask_vol > 0 else 0,
                })

        return {
            "success": True,
            "bid_walls": bid_walls,  # Support levels
            "ask_walls": ask_walls,  # Resistance levels
            "avg_bid_volume": avg_bid_vol,
            "avg_ask_volume": avg_ask_vol,
            "nearest_bid_wall": bid_walls[0]["price"] if bid_walls else None,
            "nearest_ask_wall": ask_walls[0]["price"] if ask_walls else None,
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear order book cache."""
        if symbol:
            keys_to_remove = [k for k in self._cache if k.startswith(symbol)]
            for k in keys_to_remove:
                del self._cache[k]
        else:
            self._cache.clear()
