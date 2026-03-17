"""
Bybit Control Center - BTC Correlation Guard Service

Monitors BTC price action and pauses altcoin bots during BTC dumps.
Altcoins typically dump 2-3x harder than BTC during corrections.

When BTC drops >2.5% in 1 hour, altcoin bots pause new orders to avoid
catching falling knives. Resume when BTC stabilizes.
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class BTCGuardService:
    """
    Service for monitoring BTC price and protecting altcoin bots during dumps.
    """

    def __init__(self, bybit_client: Any):
        """
        Initialize BTC Guard service.

        Args:
            bybit_client: BybitClient for API calls
        """
        self.client = bybit_client
        self._price_cache: Dict[str, Any] = {}  # {price, timestamp, change_pct}
        self._guard_active = False
        self._guard_reason = ""

    def get_btc_price_change(
        self,
        lookback_minutes: int = 60,
        cache_seconds: int = 30,
    ) -> Dict[str, Any]:
        """
        Get BTC price change over lookback period.

        Args:
            lookback_minutes: Period to measure change (default 60 min)
            cache_seconds: Cache duration (default 30 sec)

        Returns:
            Dict with:
            - success: bool
            - current_price: float
            - change_pct: float (e.g., -0.025 = -2.5%)
            - cached: bool
        """
        now = time.time()

        # Check cache
        if self._price_cache:
            cached_time = self._price_cache.get("timestamp", 0)
            if now - cached_time < cache_seconds:
                return {
                    "success": True,
                    "current_price": self._price_cache.get("current_price", 0),
                    "change_pct": self._price_cache.get("change_pct", 0),
                    "cached": True,
                }

        try:
            # Get current BTC price
            ticker_resp = self.client.get_tickers(symbol="BTCUSDT")
            if not ticker_resp.get("success"):
                return {
                    "success": False,
                    "error": ticker_resp.get("error", "Failed to get ticker"),
                    "change_pct": 0,
                }

            tickers = ticker_resp.get("data", {}).get("list", [])
            if not tickers:
                return {
                    "success": False,
                    "error": "No BTC ticker data",
                    "change_pct": 0,
                }

            current_price = float(tickers[0].get("lastPrice", 0))
            price_24h_ago = float(tickers[0].get("prevPrice24h", 0))

            # Get kline data for more accurate lookback
            # Convert lookback to appropriate interval
            if lookback_minutes <= 60:
                interval = "5"  # 5-minute candles
                limit = lookback_minutes // 5 + 1
            else:
                interval = "15"  # 15-minute candles
                limit = lookback_minutes // 15 + 1

            kline_resp = self.client.get_kline(
                symbol="BTCUSDT",
                interval=interval,
                limit=min(limit, 200),
            )

            if kline_resp.get("success"):
                klines = kline_resp.get("data", {}).get("list", [])
                if klines and len(klines) >= 2:
                    # Klines are newest first, so last item is oldest
                    oldest_close = float(klines[-1][4])  # Close price
                    if oldest_close > 0:
                        change_pct = (current_price - oldest_close) / oldest_close
                    else:
                        # Fallback to 24h change
                        change_pct = (current_price - price_24h_ago) / price_24h_ago if price_24h_ago > 0 else 0
                else:
                    # Fallback to 24h change
                    change_pct = (current_price - price_24h_ago) / price_24h_ago if price_24h_ago > 0 else 0
            else:
                # Fallback to 24h change
                change_pct = (current_price - price_24h_ago) / price_24h_ago if price_24h_ago > 0 else 0

            # Cache result
            self._price_cache = {
                "current_price": current_price,
                "change_pct": change_pct,
                "timestamp": now,
            }

            return {
                "success": True,
                "current_price": current_price,
                "change_pct": change_pct,
                "cached": False,
            }

        except Exception as e:
            logger.warning(f"Failed to get BTC price change: {e}")
            return {
                "success": False,
                "error": str(e),
                "change_pct": 0,
            }

    def should_pause_altcoin(
        self,
        symbol: str,
        dump_threshold: float = -0.025,
        recovery_threshold: float = -0.015,
        lookback_minutes: int = 60,
        exclude_symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Check if altcoin bot should pause due to BTC dump.

        Args:
            symbol: Trading symbol to check
            dump_threshold: BTC change to trigger pause (e.g., -0.025 = -2.5%)
            recovery_threshold: BTC change to resume (e.g., -0.015 = -1.5%)
            lookback_minutes: Period for BTC change calculation
            exclude_symbols: Symbols to exclude from guard (e.g., ["BTCUSDT"])

        Returns:
            Dict with:
            - pause: bool (True if should pause new orders)
            - reason: str
            - btc_change_pct: float
            - guard_active: bool
        """
        # Check exclusions
        exclude_symbols = exclude_symbols or ["BTCUSDT"]
        if symbol in exclude_symbols:
            return {
                "pause": False,
                "reason": f"{symbol} excluded from BTC guard",
                "btc_change_pct": 0,
                "guard_active": False,
            }

        # Get BTC price change
        btc_data = self.get_btc_price_change(lookback_minutes=lookback_minutes)

        if not btc_data.get("success"):
            # If we can't get BTC data, don't pause (fail-open)
            return {
                "pause": False,
                "reason": f"BTC data unavailable: {btc_data.get('error')}",
                "btc_change_pct": 0,
                "guard_active": False,
            }

        btc_change = btc_data.get("change_pct", 0)
        btc_price = btc_data.get("current_price", 0)

        # Hysteresis logic: use different thresholds for activating vs deactivating
        if not self._guard_active:
            # Not currently paused - check if we should activate
            if btc_change <= dump_threshold:
                self._guard_active = True
                self._guard_reason = f"BTC dumping {btc_change*100:.2f}% (threshold: {dump_threshold*100:.1f}%)"
                logger.warning(
                    f"🚨 BTC GUARD ACTIVATED: BTC at ${btc_price:.0f}, "
                    f"change: {btc_change*100:.2f}% - Pausing altcoin orders"
                )
        else:
            # Currently paused - check if we should deactivate
            if btc_change > recovery_threshold:
                self._guard_active = False
                self._guard_reason = ""
                logger.info(
                    f"✅ BTC GUARD DEACTIVATED: BTC recovered to {btc_change*100:.2f}% "
                    f"(recovery threshold: {recovery_threshold*100:.1f}%)"
                )

        return {
            "pause": self._guard_active,
            "reason": self._guard_reason if self._guard_active else "BTC stable",
            "btc_change_pct": btc_change,
            "btc_price": btc_price,
            "guard_active": self._guard_active,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current BTC guard status for dashboard."""
        btc_data = self.get_btc_price_change()

        return {
            "guard_active": self._guard_active,
            "guard_reason": self._guard_reason,
            "btc_price": btc_data.get("current_price", 0),
            "btc_change_pct": btc_data.get("change_pct", 0),
            "btc_change_display": f"{btc_data.get('change_pct', 0)*100:.2f}%",
        }

    def clear_cache(self):
        """Clear price cache."""
        self._price_cache = {}
