import pytest

from services.bot_manager_service import BotManagerService


class _StubStorage:
    def save_bot(self, bot):
        saved = dict(bot)
        saved.setdefault("id", "bot-1")
        return saved


def make_service():
    service = BotManagerService.__new__(BotManagerService)
    service.bot_storage = _StubStorage()
    service.client = None
    service.risk_manager = None
    service.account_service = None
    service._compute_min_notional_requirement = lambda bot_data: None
    return service


def _base_bot_data(**overrides):
    data = {
        "symbol": "BTCUSDT",
        "lower_price": 90000,
        "upper_price": 100000,
        "investment": 100,
        "leverage": 3,
        "mode": "long",
        "range_mode": "dynamic",
    }
    data.update(overrides)
    return data


def test_dynamic_mode_is_rejected():
    service = make_service()

    with pytest.raises(ValueError, match="Unsupported mode 'dynamic'"):
        service.create_or_update_bot(_base_bot_data(mode="dynamic"))


def test_mode_scoped_flags_are_disabled_for_unsupported_mode():
    service = make_service()

    saved = service.create_or_update_bot(
        _base_bot_data(
            mode="scalp_pnl",
            auto_direction=True,
            breakout_confirmed_entry=True,
            trailing_sl_enabled=True,
            quick_profit_enabled=True,
            neutral_volatility_gate_enabled=True,
        )
    )

    assert saved["auto_direction"] is False
    assert saved["breakout_confirmed_entry"] is False
    assert saved["trailing_sl_enabled"] is False
    assert saved["quick_profit_enabled"] is False
    assert saved["neutral_volatility_gate_enabled"] is False


def test_quick_profit_is_disabled_for_fixed_range_even_in_supported_mode():
    service = make_service()

    saved = service.create_or_update_bot(
        _base_bot_data(
            mode="long",
            range_mode="fixed",
            quick_profit_enabled=True,
        )
    )

    assert saved["quick_profit_enabled"] is False


def test_breakout_confirmed_entry_is_preserved_for_directional_modes():
    service = make_service()

    saved = service.create_or_update_bot(
        _base_bot_data(
            mode="long",
            range_mode="dynamic",
            breakout_confirmed_entry=True,
        )
    )

    assert saved["breakout_confirmed_entry"] is True


def test_breakout_confirmed_entry_defaults_to_false_when_not_enabled():
    service = make_service()

    saved = service.create_or_update_bot(
        _base_bot_data(
            mode="short",
            range_mode="dynamic",
        )
    )

    assert saved["breakout_confirmed_entry"] is False


def test_breakout_confirmed_entry_is_cleared_when_mode_becomes_neutral():
    service = make_service()

    saved = service.create_or_update_bot(
        _base_bot_data(
            mode="neutral",
            range_mode="dynamic",
            breakout_confirmed_entry=True,
        )
    )

    assert saved["breakout_confirmed_entry"] is False
