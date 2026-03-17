"""
Bybit Control Center - Funding Rate Intelligence Service

Analyzes perpetual funding rates to detect crowded positions.
High positive funding = longs crowded (contrarian bearish signal)
High negative funding = shorts crowded (contrarian bullish signal)

Also provides pre-funding payment protection to avoid entering
positions right before funding time (every 8 hours).
"""

import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Bybit funding times in UTC (every 8 hours)
FUNDING_HOURS_UTC = [0, 8, 16]


class FundingRateService:
    """
    Service for fetching and analyzing perpetual funding rates.
    """

    def __init__(self, bybit_client: Any):
        """
        Initialize funding rate service.

        Args:
            bybit_client: BybitClient for API calls
        """
        self.client = bybit_client
        self._cache: Dict[str, Dict[str, Any]] = {}  # symbol -> {rate, timestamp}

    def get_funding_rate(
        self,
        symbol: str,
        cache_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Get current funding rate for a symbol with caching.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            cache_seconds: How long to cache the rate (default 5 min)

        Returns:
            Dict with:
            - success: bool
            - funding_rate: float (e.g., 0.0001 = 0.01%)
            - funding_rate_pct: float (as percentage, e.g., 0.01)
            - next_funding_time: str
            - cached: bool
        """
        now = time.time()

        # Check cache
        if symbol in self._cache:
            cached = self._cache[symbol]
            if now - cached.get("timestamp", 0) < cache_seconds:
                return {
                    "success": True,
                    "funding_rate": cached["rate"],
                    "funding_rate_pct": cached["rate"] * 100,
                    "next_funding_time": cached.get("next_funding_time"),
                    "cached": True,
                }

        # Fetch from API
        try:
            response = self.client.get_funding_rate(symbol)

            if not response.get("success"):
                return {
                    "success": False,
                    "error": response.get("error", "API error"),
                    "funding_rate": 0,
                    "funding_rate_pct": 0,
                }

            # Parse response
            data = response.get("data", {})
            records = data.get("list", [])

            if not records:
                return {
                    "success": False,
                    "error": "No funding rate data",
                    "funding_rate": 0,
                    "funding_rate_pct": 0,
                }

            # Get most recent funding rate
            latest = records[0]
            rate = float(latest.get("fundingRate", 0))
            next_time = latest.get("fundingRateTimestamp", "")

            # Cache the result
            self._cache[symbol] = {
                "rate": rate,
                "next_funding_time": next_time,
                "timestamp": now,
            }

            return {
                "success": True,
                "funding_rate": rate,
                "funding_rate_pct": rate * 100,
                "next_funding_time": next_time,
                "cached": False,
            }

        except Exception as e:
            logger.warning(f"Failed to fetch funding rate for {symbol}: {e}")
            return {
                "success": False,
                "error": str(e),
                "funding_rate": 0,
                "funding_rate_pct": 0,
            }

    def get_funding_signal(
        self,
        symbol: str,
        extreme_positive: float = 0.0005,
        high_positive: float = 0.0003,
        extreme_negative: float = -0.0005,
        high_negative: float = -0.0003,
        max_score: float = 15,
    ) -> Dict[str, Any]:
        """
        Get trading signal based on funding rate.

        Contrarian logic:
        - Extreme positive funding = longs very crowded = BEARISH signal
        - High positive funding = longs crowded = mild bearish
        - Extreme negative funding = shorts very crowded = BULLISH signal
        - High negative funding = shorts crowded = mild bullish
        - Neutral funding = no signal

        Args:
            symbol: Trading pair
            extreme_positive: Threshold for extreme positive (default 0.05%)
            high_positive: Threshold for high positive (default 0.03%)
            extreme_negative: Threshold for extreme negative (default -0.05%)
            high_negative: Threshold for high negative (default -0.03%)
            max_score: Maximum score points (default 15)

        Returns:
            Dict with:
            - score: float (-max_score to +max_score)
            - signal: str (STRONG_BULLISH, BULLISH, NEUTRAL, BEARISH, STRONG_BEARISH)
            - funding_rate: float
            - reason: str
        """
        result = self.get_funding_rate(symbol)

        if not result.get("success"):
            return {
                "score": 0,
                "signal": "NEUTRAL",
                "funding_rate": 0,
                "reason": f"Failed to get funding: {result.get('error')}",
            }

        rate = result.get("funding_rate", 0)
        rate_pct = result.get("funding_rate_pct", 0)

        # Calculate signal and score
        score = 0
        signal = "NEUTRAL"
        reason = ""

        if rate >= extreme_positive:
            # Extreme positive = longs very crowded = strong bearish signal
            score = -max_score
            signal = "STRONG_BEARISH"
            reason = f"Funding {rate_pct:.4f}% (extreme positive) - longs crowded"

        elif rate >= high_positive:
            # High positive = longs crowded = mild bearish
            score = -max_score * 0.6
            signal = "BEARISH"
            reason = f"Funding {rate_pct:.4f}% (high positive) - longs crowded"

        elif rate <= extreme_negative:
            # Extreme negative = shorts very crowded = strong bullish signal
            score = max_score
            signal = "STRONG_BULLISH"
            reason = f"Funding {rate_pct:.4f}% (extreme negative) - shorts crowded"

        elif rate <= high_negative:
            # High negative = shorts crowded = mild bullish
            score = max_score * 0.6
            signal = "BULLISH"
            reason = f"Funding {rate_pct:.4f}% (high negative) - shorts crowded"

        else:
            # Neutral funding
            signal = "NEUTRAL"
            reason = f"Funding {rate_pct:.4f}% (neutral range)"

        return {
            "score": score,
            "signal": signal,
            "funding_rate": rate,
            "funding_rate_pct": rate_pct,
            "reason": reason,
            "cached": result.get("cached", False),
        }

    def clear_cache(self, symbol: Optional[str] = None):
        """Clear cached funding rates."""
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()

    def get_minutes_to_funding(self) -> int:
        """
        Get minutes until next funding time.
        Bybit funding is at 00:00, 08:00, 16:00 UTC.

        Returns:
            Minutes until next funding (0-480)
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        current_minute = now.minute

        # Find next funding hour
        for funding_hour in FUNDING_HOURS_UTC:
            if current_hour < funding_hour:
                hours_until = funding_hour - current_hour
                minutes_until = hours_until * 60 - current_minute
                return minutes_until

        # Next funding is at 00:00 tomorrow
        hours_until = 24 - current_hour + FUNDING_HOURS_UTC[0]
        minutes_until = hours_until * 60 - current_minute
        return minutes_until

    def should_skip_new_orders(
        self,
        symbol: str,
        position_side: Optional[str] = None,
        protection_minutes: int = 15,
        skip_unfavorable: bool = True,
    ) -> Dict[str, Any]:
        """
        Check if new orders should be skipped due to funding protection.

        Args:
            symbol: Trading pair
            position_side: Current position side ("long" or "short") or None
            protection_minutes: Minutes before funding to pause (default 15)
            skip_unfavorable: Also skip if funding would be unfavorable

        Returns:
            Dict with:
            - skip: bool (True if should skip new orders)
            - reason: str (explanation)
            - minutes_to_funding: int
            - funding_rate_pct: float
        """
        minutes_to_funding = self.get_minutes_to_funding()

        result = {
            "skip": False,
            "reason": "",
            "minutes_to_funding": minutes_to_funding,
            "funding_rate_pct": 0,
        }

        # Check if within protection window
        if minutes_to_funding <= protection_minutes:
            result["skip"] = True
            result["reason"] = f"Within {protection_minutes}min of funding ({minutes_to_funding}min left)"
            logger.info(f"[{symbol}] Funding protection: {result['reason']}")
            return result

        # Check if funding would be unfavorable for current position
        if skip_unfavorable and position_side:
            funding = self.get_funding_rate(symbol)
            rate = funding.get("funding_rate", 0)
            rate_pct = funding.get("funding_rate_pct", 0)
            result["funding_rate_pct"] = rate_pct

            # Positive funding = longs pay shorts
            # Negative funding = shorts pay longs
            if position_side == "long" and rate > 0.0003:  # >0.03%
                result["skip"] = True
                result["reason"] = f"High funding {rate_pct:.3f}% unfavorable for LONG"
                logger.info(f"[{symbol}] Funding protection: {result['reason']}")
            elif position_side == "short" and rate < -0.0003:  # <-0.03%
                result["skip"] = True
                result["reason"] = f"High funding {rate_pct:.3f}% unfavorable for SHORT"
                logger.info(f"[{symbol}] Funding protection: {result['reason']}")

        return result

    def get_funding_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get comprehensive funding info for display.

        Returns:
            Dict with funding rate, signal, time to next funding, protection status
        """
        funding = self.get_funding_rate(symbol)
        signal = self.get_funding_signal(symbol)
        minutes_to_funding = self.get_minutes_to_funding()

        return {
            "funding_rate": funding.get("funding_rate", 0),
            "funding_rate_pct": funding.get("funding_rate_pct", 0),
            "signal": signal.get("signal", "NEUTRAL"),
            "score": signal.get("score", 0),
            "minutes_to_funding": minutes_to_funding,
            "next_funding_in": f"{minutes_to_funding // 60}h {minutes_to_funding % 60}m",
        }
