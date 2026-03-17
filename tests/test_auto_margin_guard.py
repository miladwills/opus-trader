import time as time_module

import pytest

from config.strategy_config import (
    AUTO_MARGIN_RESERVE_PCT,
    OPENING_MARGIN_VIABILITY_RESERVE_CAP_USDT,
    OPENING_MARGIN_VIABILITY_RESERVE_PCT,
)
from services.grid_bot_service import GridBotService


class FakeClient:
    def __init__(self):
        self.margin_adds = []
        self.positions_resp = {"success": True, "data": {"list": []}}

    def _get_now_ts(self):
        return 1000.0

    def add_or_reduce_margin(self, symbol, margin, position_idx=0):
        self.margin_adds.append(
            {"symbol": symbol, "margin": float(margin), "position_idx": position_idx}
        )
        return {"success": True}

    def get_positions(self):
        return self.positions_resp


class FakeStorage:
    def __init__(self):
        self.saved = []

    def save_bot(self, bot):
        self.saved.append(dict(bot))
        return bot


def make_service():
    service = GridBotService.__new__(GridBotService)
    service.client = FakeClient()
    service.bot_storage = FakeStorage()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    return service


def test_auto_margin_guard_cancels_and_adds_margin_same_cycle(monkeypatch):
    service = make_service()
    balances = iter([0.4, 0.4, 3.0])
    cancel_calls = []

    monkeypatch.setattr(time_module, "sleep", lambda *_args, **_kwargs: None)
    service._get_usdt_available_balance = lambda: next(balances)

    def fake_cancel(symbol, last_price, min_orders_to_cancel, max_orders_to_cancel, force=False):
        cancel_calls.append(
            {
                "symbol": symbol,
                "min_orders_to_cancel": min_orders_to_cancel,
                "max_orders_to_cancel": max_orders_to_cancel,
                "force": force,
            }
        )
        return 2

    service._emergency_cancel_far_orders = fake_cancel
    service._emergency_partial_close = lambda **_kwargs: False
    service._calculate_needed_margin = lambda **_kwargs: 1.6

    bot = {
        "id": "bot-1",
        "symbol": "RIVERUSDT",
        "leverage": 10,
        "investment": 100.0,
        "auto_margin": {
            "enabled": True,
            "min_trigger_pct": 4.0,
            "target_liq_pct": 8.0,
            "cooldown_sec": 8,
            "max_add_ratio": 0.35,
            "min_add_usdt": 0.1,
            "max_add_usdt": 10.0,
            "max_total_add_usdt": 50.0,
            "position_idx": 0,
            "critical_pct": 2.5,
        },
        "auto_margin_state": {"last_add_ts": 1.0, "total_added_usdt": 0.0},
    }
    positions_resp = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "RIVERUSDT",
                    "size": "1",
                    "side": "Buy",
                    "markPrice": "100",
                    "liqPrice": "97.15",
                    "positionIM": "10",
                    "positionIdx": 0,
                }
            ]
        },
    }

    service._auto_margin_guard(bot, "RIVERUSDT", positions_resp=positions_resp)

    assert cancel_calls
    assert cancel_calls[0]["force"] is True
    assert bot["_skip_new_orders_for_margin"] is True
    assert service.client.margin_adds
    assert service.client.margin_adds[0]["margin"] == pytest.approx(1.6)


def test_auto_margin_guard_first_run_uses_available_balance_to_restore_floor():
    service = make_service()
    service._get_usdt_available_balance = lambda: 5.0
    service._emergency_cancel_far_orders = lambda *args, **kwargs: 0
    service._emergency_partial_close = lambda **_kwargs: False
    service._calculate_needed_margin = lambda **_kwargs: 2.0

    bot = {
        "id": "bot-2",
        "symbol": "RIVERUSDT",
        "leverage": 10,
        "investment": 100.0,
        "auto_margin": {
            "enabled": True,
            "min_trigger_pct": 8.0,
            "target_liq_pct": 8.0,
            "cooldown_sec": 8,
            "max_add_ratio": 0.35,
            "min_add_usdt": 0.1,
            "max_add_usdt": 10.0,
            "max_total_add_usdt": 50.0,
            "position_idx": 0,
            "critical_pct": 2.5,
        },
        "auto_margin_state": {},
    }
    positions_resp = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "RIVERUSDT",
                    "size": "1",
                    "side": "Buy",
                    "markPrice": "100",
                    "liqPrice": "93.0",
                    "positionIM": "10",
                    "positionIdx": 0,
                }
            ]
        },
    }

    service._auto_margin_guard(bot, "RIVERUSDT", positions_resp=positions_resp)

    assert service.client.margin_adds
    assert service.client.margin_adds[0]["margin"] == pytest.approx(2.0)


def test_auto_margin_guard_partial_closes_when_no_balance_or_orders(monkeypatch):
    service = make_service()
    balances = iter([0.2, 0.2, 1.8])
    partial_close_calls = []

    monkeypatch.setattr(time_module, "sleep", lambda *_args, **_kwargs: None)
    service._get_usdt_available_balance = lambda: next(balances)
    service._emergency_cancel_far_orders = lambda *args, **kwargs: 0

    def fake_partial_close(**kwargs):
        partial_close_calls.append(kwargs)
        return True

    service._emergency_partial_close = fake_partial_close
    service._trigger_quick_profit_recenter = lambda **_kwargs: {"success": False}
    service._calculate_needed_margin = lambda **_kwargs: 1.5

    bot = {
        "id": "bot-3",
        "symbol": "RIVERUSDT",
        "leverage": 10,
        "investment": 100.0,
        "auto_margin": {
            "enabled": True,
            "min_trigger_pct": 8.0,
            "target_liq_pct": 8.0,
            "cooldown_sec": 8,
            "max_add_ratio": 0.35,
            "min_add_usdt": 0.1,
            "max_add_usdt": 10.0,
            "max_total_add_usdt": 50.0,
            "position_idx": 0,
            "critical_pct": 2.5,
        },
        "auto_margin_state": {"last_add_ts": 1.0, "total_added_usdt": 0.0},
    }
    positions_resp = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "RIVERUSDT",
                    "size": "1",
                    "side": "Buy",
                    "markPrice": "100",
                    "liqPrice": "93.0",
                    "positionIM": "10",
                    "positionIdx": 0,
                }
            ]
        },
    }
    service.client.positions_resp = positions_resp

    service._auto_margin_guard(bot, "RIVERUSDT", positions_resp=positions_resp)

    assert partial_close_calls
    assert service.client.margin_adds
    assert service.client.margin_adds[0]["margin"] == pytest.approx(1.5)


def test_auto_margin_reserve_keeps_buffer_without_reducing_usable_investment():
    service = make_service()
    bot = {
        "symbol": "RIVERUSDT",
        "investment": 100.0,
        "capital_partition_usdt": None,
        "auto_margin": {"enabled": True},
        "auto_margin_state": {"last_add_ts": 1.0, "total_added_usdt": 5.0},
    }

    reserve_usd, usable_investment = service._calculate_auto_margin_reserve(
        bot, 100.0, available_equity=100.0
    )

    assert reserve_usd == pytest.approx(
        min(
            100.0 * AUTO_MARGIN_RESERVE_PCT,
            100.0 * OPENING_MARGIN_VIABILITY_RESERVE_PCT,
            OPENING_MARGIN_VIABILITY_RESERVE_CAP_USDT,
        )
    )
    assert usable_investment == pytest.approx(100.0)


def test_opening_viability_reserve_relaxes_previous_false_margin_block():
    service = make_service()
    bot = {
        "symbol": "RIVERUSDT",
        "investment": 100.0,
        "capital_partition_usdt": None,
        "auto_margin": {"enabled": True},
        "auto_margin_state": {"last_add_ts": 1.0, "total_added_usdt": 5.0},
    }

    reserve_usd, _ = service._calculate_auto_margin_reserve(
        bot, 100.0, available_equity=12.5
    )

    required_margin = 2.4
    available_opening_margin = 12.5 - reserve_usd
    old_available_opening_margin = 12.5 - min(12.5, 100.0 * AUTO_MARGIN_RESERVE_PCT)

    assert available_opening_margin == pytest.approx(2.5)
    assert available_opening_margin >= required_margin
    assert old_available_opening_margin < required_margin


def test_opening_margin_guard_reason_distinguishes_reserve_limit_from_true_insufficiency():
    service = make_service()

    assert (
        service._get_opening_margin_guard_reason(
            available_balance=12.5,
            reserve_usd=10.0,
            required_margin=2.6,
        )
        == "opening_margin_reserve"
    )
    assert (
        service._get_opening_margin_guard_reason(
            available_balance=2.0,
            reserve_usd=1.0,
            required_margin=2.6,
        )
        == "insufficient_margin_guard"
    )


def test_auto_margin_reserve_stays_zero_when_auto_margin_disabled():
    service = make_service()
    bot = {
        "symbol": "RIVERUSDT",
        "investment": 100.0,
        "capital_partition_usdt": None,
        "auto_margin": {"enabled": False},
    }

    reserve_usd, usable_investment = service._calculate_auto_margin_reserve(
        bot, 100.0, available_equity=100.0
    )

    assert reserve_usd == pytest.approx(0.0)
    assert usable_investment == pytest.approx(100.0)


def test_auto_margin_guard_clears_stale_margin_skip_flags_without_position():
    service = make_service()
    bot = {
        "id": "bot-4",
        "symbol": "RIVERUSDT",
        "auto_margin": {"enabled": True},
        "_skip_new_orders_for_margin": True,
        "_skip_opening_orders_for_margin": True,
        "last_warning": "Preserving margin for auto-margin",
    }
    positions_resp = {"success": True, "data": {"list": []}}

    service._auto_margin_guard(bot, "RIVERUSDT", positions_resp=positions_resp)

    assert "_skip_new_orders_for_margin" not in bot
    assert "_skip_opening_orders_for_margin" not in bot
    assert bot["last_warning"] is None
