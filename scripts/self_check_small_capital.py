#!/usr/bin/env python3
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from services.adaptive_config_service import AdaptiveConfigService
from services.grid_bot_service import GridBotService


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class DummyClient:
    def __init__(self):
        self.created = []

    def create_order(self, **kwargs):
        self.created.append(kwargs)
        return {"success": True, "retCode": 0}

    def get_qty_filters(self, _symbol):
        return {"min_qty": 1.0, "qty_step": 1.0, "max_qty": None}

    def normalize_qty(self, _symbol, qty, log_skip=True):
        return qty if qty and qty >= 1.0 else None

    def get_instruments_info(self, symbol):
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


def check_small_cap_levels() -> None:
    service = AdaptiveConfigService()
    instrument = {"min_notional_value": 5.0}
    target_levels = 20
    for invest in (10, 20, 30):
        cfg = service.compute_effective_config(
            symbol="WIFUSDT",
            invest_usdt=invest,
            leverage=3,
            target_levels=target_levels,
            instrument=instrument,
            atr_5m_pct=0.01,
            atr_15m_pct=0.02,
            liq_distance_pct=12.0,
        )
        _assert(cfg["effective_levels"] <= target_levels, "Expected levels to reduce or stay <= target")
        if not cfg["budget_too_small"]:
            _assert(
                cfg["per_order_notional"] >= cfg["per_order_notional_target"],
                "Per-order notional should meet target when budget allows",
            )

    eth_cfg = service.compute_effective_config(
        symbol="ETHUSDT",
        invest_usdt=20,
        leverage=3,
        target_levels=10,
        instrument=instrument,
        atr_5m_pct=0.01,
        atr_15m_pct=0.02,
        liq_distance_pct=12.0,
    )
    _assert(0.002 <= eth_cfg["effective_step_pct"] <= 0.008, "ETH step clamp failed")


def check_no_qty_zero_orders() -> None:
    client = DummyClient()
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

    bot = {"id": "bot_test", "symbol": "TESTUSDT", "status": "running"}

    result = service._create_order_checked(
        bot=bot,
        symbol="TESTUSDT",
        side="Buy",
        qty=0.5,
        order_type="Limit",
        price=1.0,
        reduce_only=False,
        time_in_force="GTC",
        order_link_id = f"close_{bot_id}_{int(time.time()*1000)}",
    )
    _assert(result.get("skipped") is True, "Expected below-min qty to skip")
    _assert(len(client.created) == 0, "No orders should be sent for qty below min")

    result = service._create_order_checked(
        bot=bot,
        symbol="TESTUSDT",
        side="Buy",
        qty=1.0,
        order_type="Limit",
        price=1.0,
        reduce_only=False,
        time_in_force="GTC",
        order_link_id = f"close_{bot_id}_{int(time.time()*1000)}",
    )
    _assert(result.get("skipped") is True, "Expected below-min notional to skip")
    _assert(len(client.created) == 0, "No orders should be sent for min-notional failure")
    _assert(bot.get("last_skip_reason") == "notional_below_min", "Expected notional_below_min reason")

    result = service._create_order_checked(
        bot=bot,
        symbol="TESTUSDT",
        side="Buy",
        qty=1.0,
        order_type="Limit",
        price=0.000001,
        reduce_only=False,
        time_in_force="GTC",
        order_link_id = f"close_{bot_id}_{int(time.time()*1000)}",
    )
    _assert(result.get("skipped") is True, "Expected low-price notional to skip")
    _assert(len(client.created) == 0, "No orders should be sent for low-price notional failure")
    _assert(bot.get("last_skip_reason") == "notional_below_min", "Expected notional_below_min reason")


def check_soft_and_hard_triggers() -> None:
    client = DummyClient()
    service = GridBotService.__new__(GridBotService)
    service.client = client
    service.bot_storage = type("DummyStorage", (), {"save_bot": lambda _self, _bot: None})()

    bot = {"symbol": "ETHUSDT", "upnl_stoploss_enabled": True}

    position = {
        "symbol": "ETHUSDT",
        "side": "Buy",
        "size": 1,
        "avgPrice": 100,
        "markPrice": 90,
        "liqPrice": 70,
        "positionIM": 10,
        "unrealisedPnl": -1,
    }
    soft = service._check_upnl_stoploss(bot, "ETHUSDT", position, atr_15m_pct=0.02)
    _assert(soft.get("soft_triggered") is True, "Expected soft trigger on drawdown vs ATR")

    position["markPrice"] = 100
    position["liqPrice"] = 95
    hard = service._check_upnl_stoploss(bot, "ETHUSDT", position, atr_15m_pct=0.02)
    _assert(hard.get("hard_triggered") is True, "Expected hard trigger on liq distance")

    position["markPrice"] = 100
    position["liqPrice"] = 40
    position["unrealisedPnl"] = -5
    hard_loss = service._check_upnl_stoploss(bot, "ETHUSDT", position, atr_15m_pct=0.02)
    _assert(hard_loss.get("hard_triggered") is True, "Expected hard trigger on deep loss")


if __name__ == "__main__":
    check_small_cap_levels()
    check_no_qty_zero_orders()
    check_soft_and_hard_triggers()
    print("Small capital self-checks passed")
