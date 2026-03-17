"""
Bybit Control Center - Open Interest Analysis Service

Analyzes Open Interest changes to confirm trend strength:
- Rising OI + Rising Price = Strong uptrend (new money entering longs)
- Rising OI + Falling Price = Strong downtrend (new money entering shorts)
- Falling OI + Rising Price = Weak rally (short covering)
- Falling OI + Falling Price = Weak selloff (long liquidations)

OI analysis helps distinguish between genuine trends and fakeouts.
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class OpenInterestService:
    """
    Service for analyzing Open Interest data from Bybit.
    """

    def __init__(self, bybit_client: Any):
        """
        Initialize Open Interest service.

        Args:
            bybit_client: BybitClient for API calls
        """
        self.client = bybit_client
        self._cache: Dict[str, Dict[str, Any]] = {}  # symbol -> {data, timestamp}

    def get_open_interest(
        self,
        symbol: str,
        interval: str = "5min",
        limit: int = 12,
        cache_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        Get Open Interest history for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: OI interval (5min, 15min, 30min, 1h, 4h, 1d)
            limit: Number of data points
            cache_seconds: Cache duration

        Returns:
            Dict with OI history and changes
        """
        now = time.time()
        cache_key = f"{symbol}_{interval}"

        # Check cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if now - cached.get("timestamp", 0) < cache_seconds:
                return {
                    "success": True,
                    "data": cached.get("data", []),
                    "cached": True,
                }

        try:
            # Bybit Open Interest endpoint
            # GET /v5/market/open-interest
            params = {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": interval,
                "limit": limit,
            }

            response = self.client._request("GET", "/v5/market/open-interest", params=params)

            if not response.get("success"):
                return {
                    "success": False,
                    "error": response.get("error", "API error"),
                    "data": [],
                }

            oi_list = response.get("data", {}).get("list", [])

            if not oi_list:
                return {
                    "success": False,
                    "error": "No OI data available",
                    "data": [],
                }

            # Parse OI data (newest first)
            parsed_data = []
            for item in oi_list:
                parsed_data.append({
                    "timestamp": int(item.get("timestamp", 0)),
                    "open_interest": float(item.get("openInterest", 0)),
                })

            # Cache result
            self._cache[cache_key] = {
                "data": parsed_data,
                "timestamp": now,
            }

            return {
                "success": True,
                "data": parsed_data,
                "cached": False,
            }

        except Exception as e:
            logger.warning(f"Failed to get OI for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": [],
            }

    def analyze_oi_trend(
        self,
        symbol: str,
        current_price: float,
        price_change_pct: float,
        lookback_periods: int = 12,
        change_threshold: float = 0.02,
        strong_threshold: float = 0.05,
        max_score: float = 20,
    ) -> Dict[str, Any]:
        """
        Analyze OI trend and generate trading signal.

        Logic:
        - Rising OI + Rising Price = BULLISH (strong uptrend, new longs)
        - Rising OI + Falling Price = BEARISH (strong downtrend, new shorts)
        - Falling OI + Rising Price = WEAK_BULLISH (short covering rally)
        - Falling OI + Falling Price = WEAK_BEARISH (long liquidation selloff)

        Args:
            symbol: Trading pair
            current_price: Current market price
            price_change_pct: Price change as decimal (e.g., 0.02 = 2%)
            lookback_periods: Number of periods to analyze
            change_threshold: Min OI change to trigger signal (2%)
            strong_threshold: OI change for strong signal (5%)
            max_score: Maximum score contribution

        Returns:
            Dict with score, signal, and analysis
        """
        oi_data = self.get_open_interest(symbol, limit=lookback_periods + 1)

        if not oi_data.get("success") or len(oi_data.get("data", [])) < 2:
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": f"OI data unavailable: {oi_data.get('error', 'insufficient data')}",
                "oi_change_pct": 0,
            }

        data = oi_data.get("data", [])

        # Calculate OI change (newest vs oldest in range)
        newest_oi = data[0]["open_interest"]
        oldest_oi = data[-1]["open_interest"] if len(data) > 1 else newest_oi

        if oldest_oi <= 0:
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "reason": "Invalid OI data",
                "oi_change_pct": 0,
            }

        oi_change_pct = (newest_oi - oldest_oi) / oldest_oi

        # Determine signal based on OI and price relationship
        score = 0
        signal = "NEUTRAL"
        reason = ""

        oi_rising = oi_change_pct > change_threshold
        oi_falling = oi_change_pct < -change_threshold
        oi_strong_rise = oi_change_pct > strong_threshold
        oi_strong_fall = oi_change_pct < -strong_threshold

        price_rising = price_change_pct > 0.005  # 0.5% threshold
        price_falling = price_change_pct < -0.005

        if oi_rising and price_rising:
            # Strong uptrend - new money entering longs
            if oi_strong_rise:
                score = max_score
                signal = "STRONG_BULLISH"
                reason = f"Strong uptrend: OI +{oi_change_pct*100:.2f}%, Price +{price_change_pct*100:.2f}%"
            else:
                score = max_score * 0.6
                signal = "BULLISH"
                reason = f"Uptrend confirmed: OI +{oi_change_pct*100:.2f}%, Price +{price_change_pct*100:.2f}%"

        elif oi_rising and price_falling:
            # Strong downtrend - new money entering shorts
            if oi_strong_rise:
                score = -max_score
                signal = "STRONG_BEARISH"
                reason = f"Strong downtrend: OI +{oi_change_pct*100:.2f}%, Price {price_change_pct*100:.2f}%"
            else:
                score = -max_score * 0.6
                signal = "BEARISH"
                reason = f"Downtrend confirmed: OI +{oi_change_pct*100:.2f}%, Price {price_change_pct*100:.2f}%"

        elif oi_falling and price_rising:
            # Weak rally - short covering, not sustainable
            score = max_score * 0.3  # Slight bullish but weak
            signal = "WEAK_BULLISH"
            reason = f"Short covering rally: OI {oi_change_pct*100:.2f}%, Price +{price_change_pct*100:.2f}%"

        elif oi_falling and price_falling:
            # Weak selloff - long liquidations, may reverse
            score = -max_score * 0.3  # Slight bearish but weak
            signal = "WEAK_BEARISH"
            reason = f"Long liquidation: OI {oi_change_pct*100:.2f}%, Price {price_change_pct*100:.2f}%"

        else:
            # No significant OI change
            signal = "NEUTRAL"
            reason = f"OI stable: {oi_change_pct*100:.2f}%"

        return {
            "score": score,
            "signal": signal,
            "reason": reason,
            "oi_change_pct": oi_change_pct,
            "current_oi": newest_oi,
            "oi_direction": "rising" if oi_rising else "falling" if oi_falling else "stable",
        }

    def get_oi_levels(
        self,
        symbol: str,
        lookback: int = 24,
    ) -> Dict[str, Any]:
        """
        Get OI statistics for dashboard display.

        Returns:
            Dict with current OI, change, and trend
        """
        oi_data = self.get_open_interest(symbol, limit=lookback)

        if not oi_data.get("success"):
            return {
                "success": False,
                "error": oi_data.get("error"),
            }

        data = oi_data.get("data", [])
        if not data:
            return {"success": False, "error": "No data"}

        current_oi = data[0]["open_interest"]
        oldest_oi = data[-1]["open_interest"] if len(data) > 1 else current_oi

        change_pct = ((current_oi - oldest_oi) / oldest_oi * 100) if oldest_oi > 0 else 0

        # Find max and min OI in period
        all_oi = [d["open_interest"] for d in data]
        max_oi = max(all_oi)
        min_oi = min(all_oi)

        return {
            "success": True,
            "current_oi": current_oi,
            "change_pct": change_pct,
            "max_oi": max_oi,
            "min_oi": min_oi,
            "trend": "rising" if change_pct > 2 else "falling" if change_pct < -2 else "stable",
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear OI cache."""
        if symbol:
            keys_to_remove = [k for k in self._cache if k.startswith(symbol)]
            for k in keys_to_remove:
                del self._cache[k]
        else:
            self._cache.clear()
