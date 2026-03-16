import logging

import pytest

from services.margin_monitor_service import MarginMonitorService


class FakeClient:
    def __init__(self, positions_resp):
        self.positions_resp = positions_resp
        self.margin_adds = []

    def get_positions(self):
        return self.positions_resp

    def get_wallet_balance(self):
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "coin": [
                            {
                                "coin": "USDT",
                                "availableToWithdraw": "20",
                                "walletBalance": "20",
                                "totalPositionIM": "0",
                                "totalOrderIM": "0",
                            }
                        ],
                        "totalAvailableBalance": "20",
                    }
                ]
            },
        }

    def add_or_reduce_margin(self, symbol, margin, position_idx=0):
        self.margin_adds.append(
            {"symbol": symbol, "margin": float(margin), "position_idx": int(position_idx)}
        )
        return {"success": True}


class FakeBotStorage:
    def __init__(self, bots):
        self._bots = list(bots)

    def list_bots(self):
        return [dict(bot) for bot in self._bots]


def make_service(*, bots, liq_price):
    positions_resp = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "RIVERUSDT",
                    "size": "1",
                    "side": "Buy",
                    "markPrice": "100",
                    "liqPrice": str(liq_price),
                    "positionIdx": 1,
                    "positionIM": "5",
                    "positionValue": "100",
                }
            ]
        },
    }
    client = FakeClient(positions_resp)
    service = MarginMonitorService(client, FakeBotStorage(bots))
    service.state = {}
    service._save_state = lambda: None
    return service, client


def test_margin_monitor_allows_add_when_only_stopped_reduce_only_bot_matches_symbol(caplog):
    service, client = make_service(
        bots=[
            {
                "id": "stopped-bot",
                "symbol": "RIVERUSDT",
                "status": "stopped",
                "reduce_only_mode": True,
            }
        ],
        liq_price=94,
    )

    with caplog.at_level(logging.WARNING):
        result = service.check_all_positions()

    assert result["actions"]
    assert client.margin_adds
    assert "skip add margin due to reduce_only_mode" not in caplog.text


def test_margin_monitor_blocks_active_reduce_only_bot_when_add_is_needed(caplog):
    service, client = make_service(
        bots=[
            {
                "id": "active-bot",
                "symbol": "RIVERUSDT",
                "status": "paused",
                "reduce_only_mode": True,
            }
        ],
        liq_price=94,
    )

    with caplog.at_level(logging.WARNING):
        result = service.check_all_positions()

    assert result["actions"] == []
    assert client.margin_adds == []
    assert "skip add margin due to reduce_only_mode" in caplog.text


def test_margin_monitor_skips_block_warning_when_position_is_above_trigger(caplog):
    service, client = make_service(
        bots=[
            {
                "id": "active-bot",
                "symbol": "RIVERUSDT",
                "status": "paused",
                "reduce_only_mode": True,
            }
        ],
        liq_price=90,
    )

    with caplog.at_level(logging.WARNING):
        result = service.check_all_positions()

    assert result["skipped"] == 1
    assert result["actions"] == []
    assert client.margin_adds == []
    assert "skip add margin due to reduce_only_mode" not in caplog.text


def make_service_custom_position(*, bots, mark_price, liq_price, position_im, position_value, available="20"):
    """
    Build a MarginMonitorService with a position whose mark/liq/margin values are
    set precisely so callers can control the 'needed_amount' calculation.
    """
    positions_resp = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "RIVERUSDT",
                    "size": "1",
                    "side": "Buy",
                    "markPrice": str(mark_price),
                    "liqPrice": str(liq_price),
                    "positionIdx": 0,
                    "positionIM": str(position_im),
                    "positionValue": str(position_value),
                }
            ]
        },
    }

    class _FakeClient:
        def __init__(self):
            self.margin_adds = []

        def get_positions(self):
            return positions_resp

        def get_wallet_balance(self):
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "coin": [
                                {
                                    "coin": "USDT",
                                    "availableToWithdraw": available,
                                    "walletBalance": available,
                                    "totalPositionIM": "0",
                                    "totalOrderIM": "0",
                                }
                            ],
                            "totalAvailableBalance": available,
                        }
                    ]
                },
            }

        def add_or_reduce_margin(self, symbol, margin, position_idx=0):
            self.margin_adds.append({"symbol": symbol, "margin": float(margin)})
            return {"success": True}

    client = _FakeClient()
    service = MarginMonitorService(client, FakeBotStorage(bots))
    service.state = {}
    service._save_state = lambda: None
    return service, client


def test_margin_monitor_clamps_to_minimum_when_needed_amount_is_tiny(caplog):
    """
    When the calculated add amount is driven below the configured minimum by the
    needed_amount cap (position is almost at the target liq distance already),
    the service should clamp to effective_min and execute the add rather than
    silently skipping.

    Setup: mark=100, liq=92.04 (7.96% away — inside the 8% trigger).
    target_liq = 100 * 0.92 = 92.0
    needed = 1 * (92.04 - 92.0) = 0.04  <  effective_min (0.1)
    available_for_margin = 20 - max(5.0, 0.02*20)=5.0 = 15  >=  0.1
    => should clamp to 0.1 and proceed.
    """
    service, client = make_service_custom_position(
        bots=[],
        mark_price=100,
        liq_price=92.04,
        position_im=5,
        position_value=100,
        available="20",
    )

    with caplog.at_level(logging.WARNING):
        result = service.check_all_positions()

    # The add must have been executed (not skipped)
    assert result["actions"], "Expected a margin add action, got none"
    assert client.margin_adds, "Expected add_or_reduce_margin to be called"
    # The clamped amount should be at least the configured minimum (0.1)
    from config.strategy_config import MARGIN_MONITOR_MIN_ADD_USDT
    assert client.margin_adds[0]["margin"] >= MARGIN_MONITOR_MIN_ADD_USDT
    # Operator-visible warning should appear
    assert "clamping to minimum" in caplog.text


def test_margin_monitor_skips_when_amount_tiny_and_balance_insufficient(caplog):
    """
    When the calculated amount is below effective_min AND available balance is
    also below effective_min, the service must skip (no add, no exception).
    """
    # Available = 5.1 USDT. keep_free = max(5.0, 0.02*5.1=0.102) = 5.0
    # available_for_margin = 5.1 - 5.0 = 0.1
    # base_budget = min(0.1 * 0.35, 10.0) = 0.035 < effective_min(0.1) -> skip at line 411
    # This test verifies the pre-existing "Budget below minimum" guard still works.
    service, client = make_service_custom_position(
        bots=[],
        mark_price=100,
        liq_price=92.04,
        position_im=5,
        position_value=100,
        available="5.1",
    )

    with caplog.at_level(logging.WARNING):
        result = service.check_all_positions()

    assert result["actions"] == [], "Expected no action when balance is insufficient"
    assert client.margin_adds == [], "Expected no add_or_reduce_margin call"
