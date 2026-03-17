#!/usr/bin/env python3
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.grid_bot_service import GridBotService


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class DummyClient:
    def __init__(self):
        self.orders = []
        self.positions = []

    def get_positions(self):
        return {"success": True, "data": {"list": self.positions}}

    def get_qty_filters(self, _symbol):
        return {"min_qty": 1.0, "qty_step": 1.0, "max_qty": None}

    def normalize_qty(self, _symbol, qty, log_skip=True):
        return qty if qty and qty >= 1.0 else None

    def create_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"success": True, "retCode": 0}

    def get_instruments_info(self, _symbol):
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "lotSizeFilter": {
                            "minOrderQty": "1",
                            "qtyStep": "1",
                            "minNotionalValue": "5",
                        },
                        "priceFilter": {"tickSize": "0.01"},
                    }
                ]
            },
        }


def _build_service(client: DummyClient) -> GridBotService:
    service = GridBotService.__new__(GridBotService)
    service.client = client
    service.bot_storage = type("DummyStorage", (), {"save_bot": lambda _self, _bot: None})()
    service._instrument_cache = {
        "TESTUSDT": {
            "min_order_qty": 1.0,
            "qty_step": 1.0,
            "tick_size": 0.01,
            "min_notional_value": 5.0,
        }
    }
    return service


def check_partial_tp_cooldown() -> None:
    client = DummyClient()
    service = _build_service(client)

    bot = {
        "id": "bot_partial",
        "symbol": "TESTUSDT",
        "partial_tp_enabled": True,
        "partial_tp_fractions": [0.5],
        "partial_tp_cooldown_sec": 999,
        "profit_lock_enabled": False,
    }

    client.positions = [
        {"symbol": "TESTUSDT", "side": "Buy", "size": 10, "avgPrice": 100}
    ]

    indicators = {"atr_pct": 0.001, "close": 101}
    service._run_fast_execution_layer(bot, "TESTUSDT", 101, indicators)
    _assert(len(client.orders) == 1, "Expected partial TP to place a close order")
    _assert(bot.get("partial_tp_executed_count") == 1, "Expected partial TP count increment")

    service._run_fast_execution_layer(bot, "TESTUSDT", 101, indicators)
    _assert(len(client.orders) == 1, "Cooldown should prevent repeated partial TP")


def check_profit_lock_giveback() -> None:
    client = DummyClient()
    service = _build_service(client)

    bot = {
        "id": "bot_profit_lock",
        "symbol": "TESTUSDT",
        "partial_tp_enabled": False,
        "profit_lock_enabled": True,
        "profit_lock_cooldown_sec": 0,
    }

    client.positions = [
        {"symbol": "TESTUSDT", "side": "Buy", "size": 10, "avgPrice": 100}
    ]

    indicators = {"atr_pct": 0.001, "close": 101}
    service._run_fast_execution_layer(bot, "TESTUSDT", 101, indicators)

    indicators = {"atr_pct": 0.001, "close": 100.6}
    service._run_fast_execution_layer(bot, "TESTUSDT", 100.6, indicators)

    _assert(len(client.orders) == 1, "Expected profit lock to place a close order")
    _assert(bot.get("profit_lock_executed_count") == 1, "Expected profit lock count increment")


def check_fee_guard_skip() -> None:
    client = DummyClient()
    service = _build_service(client)

    bot = {
        "id": "bot_fee_guard",
        "symbol": "TESTUSDT",
        "partial_tp_enabled": False,
        "profit_lock_enabled": True,
        "profit_lock_cooldown_sec": 0,
        "profit_lock_state": {"position_side": "Buy", "peak_pct": 0.01, "last_close_ts": 0},
    }

    client.positions = [
        {"symbol": "TESTUSDT", "side": "Buy", "size": 10, "avgPrice": 100}
    ]

    indicators = {"atr_pct": 0.001, "close": 100.1}
    service._run_fast_execution_layer(bot, "TESTUSDT", 100.1, indicators)

    _assert(len(client.orders) == 0, "Fee guard should prevent profit lock close")
    _assert(
        bot.get("profit_lock_skipped_fee_guard_count") == 1,
        "Expected fee guard skip counter increment",
    )


def check_small_qty_skip() -> None:
    client = DummyClient()
    service = _build_service(client)

    bot = {
        "id": "bot_small_qty",
        "symbol": "TESTUSDT",
        "partial_tp_enabled": True,
        "partial_tp_fractions": [0.5],
        "partial_tp_cooldown_sec": 0,
        "profit_lock_enabled": False,
    }

    client.positions = [
        {"symbol": "TESTUSDT", "side": "Buy", "size": 0.5, "avgPrice": 100}
    ]

    indicators = {"atr_pct": 0.001, "close": 101}
    service._run_fast_execution_layer(bot, "TESTUSDT", 101, indicators)

    _assert(len(client.orders) == 0, "Expected small-qty partial TP to skip order")
    _assert(
        bot.get("partial_tp_skipped_small_qty_count") == 1,
        "Expected small-qty skip counter increment",
    )


if __name__ == "__main__":
    check_partial_tp_cooldown()
    check_profit_lock_giveback()
    check_fee_guard_skip()
    check_small_qty_skip()
    print("Fast execution self-checks passed")
