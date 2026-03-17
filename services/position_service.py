"""
Bybit Control Center - Position Service

Provides position information and summaries for linear USDT perpetuals.
"""

from services.bybit_client import BybitClient
from typing import Dict, Any, List, Optional


class PositionService:
    """
    Service for retrieving and normalizing position data from Bybit.
    """

    def __init__(self, client: BybitClient):
        """
        Initialize the position service.

        Args:
            client: Initialized BybitClient instance
        """
        self.client = client

    def _get_account_equity(self) -> float:
        """
        Get total account equity for leverage calculation.
        Uses equity field which includes unrealized PnL for accurate leverage display.

        Returns:
            Account equity in USDT, or 0 if unavailable
        """
        try:
            response = self.client.get_wallet_balance()
            if response.get("success"):
                data = response.get("data", {})
                account_list = data.get("list", [])

                if account_list:
                    account = account_list[0]  # Unified account
                    coins = account.get("coin", [])

                    # Find USDT
                    for coin in coins:
                        if coin.get("coin") == "USDT":
                            # Use equity (includes unrealized PnL) for accurate effective leverage
                            equity = float(coin.get("equity", 0) or 0)
                            if equity > 0:
                                return equity
                            # Fallback to walletBalance
                            wallet_balance = float(coin.get("walletBalance", 0) or 0)
                            if wallet_balance > 0:
                                return wallet_balance

                    # Fallback to account-level totalEquity
                    total_equity = float(account.get("totalEquity", 0) or 0)
                    if total_equity > 0:
                        return total_equity
        except Exception as e:
            import logging
            logging.warning(f"Failed to get account equity: {e}")
        return 0.0

    def normalize_position_row(
        self,
        pos: Dict[str, Any],
        *,
        account_equity: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        size = float(pos.get("size", 0) or 0)
        if size == 0:
            return None

        side = pos.get("side", "")
        entry_price = self._safe_float(pos.get("avgPrice"))
        mark_price = self._safe_float(pos.get("markPrice"))
        liq_price = self._safe_float(pos.get("liqPrice"))
        margin = self._safe_float(pos.get("positionIM"))
        leverage_raw = self._safe_float(pos.get("leverage"))
        unrealized_pnl = self._safe_float(pos.get("unrealisedPnl"))
        realized_pnl = self._safe_float(pos.get("curRealisedPnl"))
        take_profit = self._safe_float(pos.get("takeProfit"))
        stop_loss = self._safe_float(pos.get("stopLoss"))
        position_value = self._safe_float(pos.get("positionValue"))

        effective_leverage = None
        if account_equity > 0 and position_value > 0:
            effective_leverage = round(position_value / account_equity, 2)
        elif leverage_raw > 0:
            effective_leverage = leverage_raw

        pct_to_liq = None
        if liq_price > 0 and mark_price > 0:
            pct_to_liq = abs(mark_price - liq_price) / mark_price * 100

        return {
            "symbol": pos.get("symbol", ""),
            "side": side,
            "size": size,
            "position_idx": int(pos.get("positionIdx", 0) or 0),
            "entry_price": entry_price,
            "mark_price": mark_price,
            "liq_price": liq_price if liq_price != 0 else None,
            "pct_to_liq": round(pct_to_liq, 2) if pct_to_liq is not None else None,
            "margin": margin if margin != 0 else None,
            "leverage": round(effective_leverage, 2) if effective_leverage else None,
            "position_value": round(position_value, 2) if position_value > 0 else None,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "take_profit": take_profit if take_profit != 0 else None,
            "stop_loss": stop_loss if stop_loss != 0 else None,
        }

    def get_positions(self, skip_cache: bool = True) -> Dict[str, Any]:
        """
        Get all positions with normalized data and summary.

        Returns:
            Dict with:
            - positions: List of normalized position dicts
            - summary: Summary statistics
            - error: Error message if any
        """
        result = {
            "positions": [],
            "summary": {
                "total_positions": 0,
                "longs": 0,
                "shorts": 0,
                "total_unrealized_pnl": 0.0
            },
            "error": None
        }

        response = self.client.get_positions(skip_cache=skip_cache)

        if not response.get("success"):
            result["error"] = response.get("error", "Unknown error fetching positions")
            return result

        # Get account equity for effective leverage calculation
        account_equity = self._get_account_equity()

        try:
            data = response.get("data", {})
            position_list = data.get("list", [])

            positions = []
            total_unrealized_pnl = 0.0
            total_position_value = 0.0
            longs = 0
            shorts = 0

            for pos in position_list:
                normalized_pos = self.normalize_position_row(
                    pos,
                    account_equity=account_equity,
                )
                if not normalized_pos:
                    continue

                side = normalized_pos.get("side", "")
                if side == "Buy":
                    longs += 1
                elif side == "Sell":
                    shorts += 1

                unrealized_pnl = self._safe_float(normalized_pos.get("unrealized_pnl"))
                position_value = self._safe_float(normalized_pos.get("position_value"))
                total_unrealized_pnl += unrealized_pnl
                total_position_value += position_value
                positions.append(normalized_pos)

            # Calculate total effective leverage for all positions
            total_effective_leverage = None
            if account_equity > 0 and total_position_value > 0:
                total_effective_leverage = total_position_value / account_equity

            result["positions"] = positions
            result["summary"] = {
                "total_positions": len(positions),
                "longs": longs,
                "shorts": shorts,
                "total_unrealized_pnl": round(total_unrealized_pnl, 4),
                "total_position_value": round(total_position_value, 2),
                "account_equity": round(account_equity, 2),
                "total_effective_leverage": round(total_effective_leverage, 2) if total_effective_leverage else None,
            }

        except (KeyError, TypeError, ValueError) as e:
            result["error"] = f"Error parsing position data: {str(e)}"

        return result

    def _safe_float(self, value: Any) -> float:
        """
        Safely convert a value to float.

        Args:
            value: Value to convert

        Returns:
            Float value, or 0.0 if conversion fails
        """
        if value is None or value == "":
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
