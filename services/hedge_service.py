
import logging
import time
from typing import List, Dict, Any, Optional
from services.bybit_client import BybitClient

logger = logging.getLogger(__name__)


class HedgeService:
    """
    Delta Neutral Hedge Service.
    Monitors total portfolio exposure and manages a short hedge position
    to neutralize market risk.
    """

    def __init__(self, client: BybitClient):
        self.client = client
        self.hedge_symbol = "BTCUSDT"
        self.beta_weight = 1.0  # Simple 1:1 hedge for now
        self.min_hedge_size = 100.0  # Don't hedge tiny amounts
        self.last_check = 0
        self.check_interval = 300  # 5 minutes

    def check_and_hedge(self, active_bots: List[Dict]):
        if time.time() - self.last_check < self.check_interval:
            return

        self.last_check = time.time()

        # 1) Avoid conflicting with BTC bot
        for bot in active_bots:
            if bot.get("symbol") == self.hedge_symbol:
                logger.info("BTC bot running; skip hedge to avoid conflict.")
                return

        # 2) Fetch positions (normalized client response)
        resp = self.client.get_positions(skip_cache=True)
        if not resp.get("success"):
            logger.error("Failed to fetch positions for hedge check: %s", resp.get("error"))
            return

        positions = resp.get("data", {}).get("list", []) or []

        # 3) Calculate net long exposure (USDT) and current hedge short (USDT)
        total_long_usdt = 0.0
        current_hedge_short_usdt = 0.0

        for p in positions:
            symbol = p.get("symbol")
            side = p.get("side")
            pos_value = float(p.get("positionValue", 0) or 0)

            if symbol == self.hedge_symbol and side == "Sell":
                current_hedge_short_usdt = pos_value
            else:
                if side == "Buy":
                    total_long_usdt += pos_value
                elif side == "Sell":
                    total_long_usdt -= pos_value

        # 4) Compute target hedge
        target_hedge = total_long_usdt * self.beta_weight
        diff = target_hedge - current_hedge_short_usdt

        logger.info(
            "Hedge Check: Long=${:.2f}, Current Hedge=${:.2f}, Target=${:.2f}, Diff=${:.2f}".format(
                total_long_usdt, current_hedge_short_usdt, target_hedge, diff
            )
        )

        # Close hedge if portfolio is effectively flat
        if target_hedge < self.min_hedge_size and current_hedge_short_usdt > 0:
            logger.info("Closing hedge (portfolio near-flat)")
            self._execute_hedge(symbol=self.hedge_symbol, side="Buy", usdt_amount=current_hedge_short_usdt)
            return

        # Adjust only if difference is meaningful
        if abs(diff) <= 50:
            return

        if diff > 0:
            # Need more short
            logger.info("Increasing hedge by ${:.2f}".format(diff))
            self._execute_hedge(symbol=self.hedge_symbol, side="Sell", usdt_amount=diff)
        else:
            # Need less short (reduce-only unwind preferred)
            reduce_amt = abs(diff)
            logger.info("Reducing hedge by ${:.2f}".format(reduce_amt))
            self._execute_hedge(symbol=self.hedge_symbol, side="Buy", usdt_amount=reduce_amt)

    def _get_last_price(self, symbol: str) -> Optional[float]:
        """Fetch a recent price with normalized client response."""
        ticker = self.client.get_tickers(symbol, skip_cache=True)
        if ticker.get("success"):
            tickers = ticker.get("data", {}).get("list", []) or []
            if tickers:
                try:
                    return float(tickers[0].get("lastPrice", 0) or 0)
                except Exception:
                    pass

        # Fallback to kline if ticker missing
        kline = self.client.get_kline(symbol, interval="1", limit=1)
        if kline.get("success"):
            kline_list = kline.get("data", {}).get("list", []) or []
            if kline_list:
                try:
                    # Bybit kline: [start, open, high, low, close, volume, ...]
                    return float(kline_list[0][4])
                except Exception:
                    return None
        return None

    def _execute_hedge(self, symbol: str, side: str, usdt_amount: float):
        """Place hedge order with proper normalization and hedge position_idx (short=2)."""
        price = self._get_last_price(symbol)
        if not price or price <= 0:
            logger.error("Hedge skipped: failed to fetch price for %s", symbol)
            return

        raw_qty = usdt_amount / price
        normalized_qty = self.client.normalize_qty(symbol, raw_qty, log_skip=False)
        if not normalized_qty:
            logger.warning("Hedge skipped: qty below min after normalization (raw=%.6f)", raw_qty)
            return

        # Hedge mode: short leg uses positionIdx=2
        position_idx = 2
        reduce_only = side.lower() == "buy"  # reduce-only unwind preference

        logger.info(
            "Executing Hedge Order: %s %.6f %s @ %.4f (reduce_only=%s)",
            side,
            normalized_qty,
            symbol,
            price,
            reduce_only,
        )

        order_res = self.client.create_order(
            symbol=symbol,
            side=side,
            qty=normalized_qty,
            order_type="Market",
            price=None,
            reduce_only=reduce_only,
            time_in_force="GTC",
            position_idx=position_idx,
            qty_is_normalized=True,
        )

        if not order_res.get("success"):
            logger.error("Hedge order failed: %s", order_res.get("error"))
        else:
            logger.info("Hedge order placed successfully")
