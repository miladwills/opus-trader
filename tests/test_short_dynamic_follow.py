from config.strategy_config import get_dynamic_range_settings
from services.grid_bot_service import GridBotService


def make_service():
    return GridBotService.__new__(GridBotService)


def test_short_dynamic_keeps_near_price_continuation_sell():
    service = make_service()
    levels = [98.8, 99.2, 99.7, 100.2, 100.7]

    buy_levels, sell_levels = service._build_biased_levels(
        levels=levels,
        last_price=100.0,
        mode="short",
        tick_size=0.001,
        existing_order_prices=None,
        fast_indicators=None,
        range_mode="dynamic",
    )

    assert 99.7 in sell_levels
    assert 100.2 in sell_levels
    assert 100.7 in sell_levels
    assert 98.8 in buy_levels
    assert 99.7 not in buy_levels


def test_short_trailing_keeps_rally_short_behavior():
    service = make_service()
    levels = [98.8, 99.2, 99.7, 100.2, 100.7]

    buy_levels, sell_levels = service._build_biased_levels(
        levels=levels,
        last_price=100.0,
        mode="short",
        tick_size=0.001,
        existing_order_prices=None,
        fast_indicators=None,
        range_mode="trailing",
    )

    assert 99.7 not in sell_levels
    assert sell_levels == [100.2, 100.7]
    assert 98.8 in buy_levels


def test_short_dynamic_range_recenters_faster_than_long():
    short_settings = get_dynamic_range_settings("short")
    long_settings = get_dynamic_range_settings("long")

    assert short_settings["recalc_threshold_pct"] == long_settings["recalc_threshold_pct"]
