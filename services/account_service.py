"""
Bybit Control Center - Account Service

Provides account overview including equity, balance, and PnL information.
"""

import logging
from services.bybit_client import BybitClient
from typing import Dict, Any, Optional


class AccountService:
    """
    Service for retrieving account information from Bybit.
    """

    def __init__(self, client: BybitClient):
        """
        Initialize the account service.

        Args:
            client: Initialized BybitClient instance
        """
        self.client = client

    def get_overview(self) -> Dict[str, Any]:
        """
        Get account overview with equity, balance, and PnL.

        Returns:
            Dict with:
            - equity: Total equity in USDT
            - available_balance: Available balance for trading
            - realized_pnl: Realized PnL
            - unrealized_pnl: Unrealized PnL
            - error: Error message if any, None otherwise
        """
        result = {
            "equity": 0.0,
            "available_balance": 0.0,
            "funding_balance": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "error": None,
        }

        # 1. Fetch Unified Account Balance
        response = self.client.get_wallet_balance(account_type="UNIFIED")

        if not response.get("success"):
            result["error"] = response.get(
                "error", "Unknown error fetching wallet balance"
            )
            return result

        try:
            data = response.get("data", {})
            account_list = data.get("list", [])

            if not account_list:
                result["error"] = "No account data returned"
            else:
                # Find USDT coin in the unified account
                account = account_list[0]  # Unified account
                coins = account.get("coin", [])

                usdt_coin = None
                for coin in coins:
                    if coin.get("coin") == "USDT":
                        usdt_coin = coin
                        break

                if usdt_coin:
                    result["equity"] = float(usdt_coin.get("equity", 0) or 0)
                    # Calculate trading-available balance (not withdrawal balance)
                    # available = walletBalance - position margin - order margin
                    wallet_balance = float(usdt_coin.get("walletBalance", 0) or 0)
                    position_im = float(usdt_coin.get("totalPositionIM", 0) or 0)
                    order_im = float(usdt_coin.get("totalOrderIM", 0) or 0)
                    result["available_balance"] = (
                        wallet_balance - position_im - order_im
                    )

                    # FALLBACK: If available balance is 0 but account total has margin, use that.
                    # This happens for UTA users where coin-level available balance might be 0.
                    account_available = float(
                        account.get("totalAvailableBalance", 0) or 0
                    )
                    if result["available_balance"] <= 0 and account_available > 0:
                        result["available_balance"] = account_available

                    result["realized_pnl"] = float(
                        usdt_coin.get("cumRealisedPnl", 0) or 0
                    )

                    result["unrealized_pnl"] = float(
                        usdt_coin.get("unrealisedPnl", 0) or 0
                    )
                else:
                    # Try account-level fields if no USDT coin found
                    result["equity"] = float(account.get("totalEquity", 0) or 0)
                    result["available_balance"] = float(
                        account.get("totalAvailableBalance", 0) or 0
                    )
                    result["unrealized_pnl"] = float(
                        account.get("totalPerpUPL", 0) or 0
                    )

            # 2. Fetch Funding Account Balance (USDT)
            # Use Asset endpoint for Funding account (get_wallet_balance fails for UTA)
            fund_response = self.client.get_coins_balance(
                account_type="FUND", coin="USDT"
            )

            if fund_response.get("success"):
                fund_data = fund_response.get("data", {})
                # Asset endpoint returns 'balance' list
                fund_list = fund_data.get("balance", [])

                if fund_list:
                    # Try to find USDT specifically
                    found_usdt = False
                    for coin in fund_list:
                        if coin.get("coin") == "USDT":
                            result["funding_balance"] = float(
                                coin.get("walletBalance", 0) or 0
                            )
                            found_usdt = True
                            break

                    # If USDT not explicitly found, log warning
                    if not found_usdt:
                        logging.warning(
                            f"USDT not found in funding coins: {[c.get('coin') for c in fund_list]}"
                        )

        except (KeyError, TypeError, ValueError) as e:
            result["error"] = f"Error parsing wallet data: {str(e)}"

        return result
