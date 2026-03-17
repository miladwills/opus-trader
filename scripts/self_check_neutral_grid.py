#!/usr/bin/env python3
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.neutral_grid_service import NeutralGridService


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class DummyStorage:
    def __init__(self):
        self.saved = None

    def save_bot(self, bot):
        self.saved = bot
        return bot


class DummyClient:
    def __init__(self):
        self.orders = []
        self.next_order_id = 1
        self.min_notional = 5.0
        self.min_qty = 0.01
        self.qty_step = 0.01
        self.last_price = 150.0
        self.positions = [
            {"symbol": "BTCUSDT", "positionIdx": 1, "size": 0},
            {"symbol": "BTCUSDT", "positionIdx": 2, "size": 0},
        ]

    def get_positions(self, skip_cache=False):
        return {"success": True, "data": {"list": self.positions}}

    def get_instruments_info(self, symbol=None):
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "lotSizeFilter": {
                            "minOrderQty": str(self.min_qty),
                            "qtyStep": str(self.qty_step),
                            "minNotionalValue": str(self.min_notional),
                        },
                        "priceFilter": {"tickSize": "0.5"},
                    }
                ]
            },
        }

    def normalize_qty(self, _symbol, qty, log_skip=True):
        if qty is None or qty <= 0:
            return None
        if qty < self.min_qty:
            return None
        step = self.qty_step
        return (qty // step) * step

    def create_order(
        self,
        symbol,
        side,
        qty,
        order_type="Limit",
        price=None,
        reduce_only=False,
        time_in_force="GTC",
        order_link_id = f"close_{bot_id}_{int(time.time()*1000)}",
        position_idx=None,
        qty_is_normalized=False,
    ):
        order_id = f"order_{self.next_order_id}"
        self.next_order_id += 1
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "reduceOnly": reduce_only,
                "orderId": order_id,
                "orderLinkId": order_link_id,
                "positionIdx": position_idx,
            }
        )
        return {"success": True, "data": {"orderId": order_id}}

    def get_open_orders(self, symbol=None, limit=None, skip_cache=False):
        orders = [o for o in self.orders if o.get("symbol") == symbol]
        return {"success": True, "data": {"list": orders}}

    def get_tickers(self, symbol=None, skip_cache=False):
        return {"success": True, "data": {"list": [{"lastPrice": str(self.last_price)}]}}

    def get_executions(self, symbol=None, limit=50, skip_cache=False):
        return {"success": True, "data": {"list": []}}


def check_seed_counts() -> None:
    storage = DummyStorage()
    client = DummyClient()
    service = NeutralGridService(bot_storage=storage)

    bot = {
        "id": "bot-1234-5678-9012-abcdefabcdef",
        "symbol": "BTCUSDT",
        "investment": 100,
        "leverage": 1,
        "grid_lower_price": 100,
        "grid_upper_price": 200,
        "grid_levels_total": 4,
        "neutral_post_only": False,
    }

    bot = service.reconcile_on_start(bot, "BTCUSDT", client)
    _assert(bot.get("neutral_grid_initialized") is True, "Expected neutral grid to initialize")
    _assert(len(client.orders) == 4, "Expected 4 entry orders seeded for 4 slots")


def check_entry_to_exit_replacement() -> None:
    storage = DummyStorage()
    client = DummyClient()
    service = NeutralGridService(bot_storage=storage)

    bot = {
        "id": "bot-1234-5678-9012-abcdefabcdef",
        "symbol": "BTCUSDT",
        "investment": 100,
        "leverage": 1,
        "grid_lower_price": 100,
        "grid_upper_price": 200,
        "grid_levels_total": 4,
        "neutral_post_only": False,
    }

    bot = service.reconcile_on_start(bot, "BTCUSDT", client)
    entry_order = client.orders[0]
    fill_event = {
        "execId": "exec_1",
        "orderLinkId": entry_order.get("orderLinkId"),
        "orderStatus": "Filled",
        "leavesQty": 0,
    }

    bot = service.on_order_filled(bot, "BTCUSDT", fill_event, client)
    _assert(len(client.orders) == 5, "Expected exit order to be placed after entry fill")
    exit_order = client.orders[-1]
    _assert(exit_order["reduceOnly"] is True, "Expected reduceOnly exit order")


def check_exit_to_entry_replacement() -> None:
    storage = DummyStorage()
    client = DummyClient()
    service = NeutralGridService(bot_storage=storage)

    bot = {
        "id": "bot-1234-5678-9012-abcdefabcdef",
        "symbol": "BTCUSDT",
        "investment": 100,
        "leverage": 1,
        "grid_lower_price": 100,
        "grid_upper_price": 200,
        "grid_levels_total": 4,
        "neutral_post_only": False,
    }

    bot = service.reconcile_on_start(bot, "BTCUSDT", client)
    entry_order = client.orders[0]
    entry_fill = {
        "execId": "exec_2",
        "orderLinkId": entry_order.get("orderLinkId"),
        "orderStatus": "Filled",
        "leavesQty": 0,
    }
    bot = service.on_order_filled(bot, "BTCUSDT", entry_fill, client)

    exit_order = client.orders[-1]
    exit_fill = {
        "execId": "exec_3",
        "orderLinkId": exit_order.get("orderLinkId"),
        "orderStatus": "Filled",
        "leavesQty": 0,
    }
    bot = service.on_order_filled(bot, "BTCUSDT", exit_fill, client)
    _assert(len(client.orders) == 6, "Expected entry order to be replaced after exit fill")
    new_entry = client.orders[-1]
    _assert(new_entry["reduceOnly"] is False, "Expected new entry order after exit fill")


def check_order_link_parsing() -> None:
    storage = DummyStorage()
    service = NeutralGridService(bot_storage=storage)
    link_id = "bv2:abcd1234efgh5678:000123:L03:E"
    parsed = service._parse_order_link_id(link_id)
    _assert(parsed and parsed.get("slot") == "L03", "Expected slot parsing to succeed")
    _assert(parsed.get("state") == "E", "Expected state parsing to succeed")


def check_skip_small_qty() -> None:
    storage = DummyStorage()
    client = DummyClient()
    client.min_notional = 10000.0
    service = NeutralGridService(bot_storage=storage)

    bot = {
        "id": "bot-1234-5678-9012-abcdefabcdef",
        "symbol": "BTCUSDT",
        "investment": 1,
        "leverage": 1,
        "grid_lower_price": 100,
        "grid_upper_price": 200,
        "grid_levels_total": 4,
        "neutral_post_only": False,
    }

    bot = service.reconcile_on_start(bot, "BTCUSDT", client)
    _assert(len(client.orders) == 0, "Expected no orders when qty/notional below minimum")


if __name__ == "__main__":
    check_seed_counts()
    check_entry_to_exit_replacement()
    check_exit_to_entry_replacement()
    check_order_link_parsing()
    check_skip_small_qty()
    print("self_check_neutral_grid: OK")
