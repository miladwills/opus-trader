import logging
from types import SimpleNamespace
from unittest.mock import Mock

from services.grid_bot_service import (
    DEFAULT_GRID_STABILITY_THRESHOLD_PCT,
    GridBotService,
)


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service._round_to_step = GridBotService._round_to_step.__get__(
        service, GridBotService
    )
    return service


class _FakeBotStorage:
    def __init__(self, bot):
        self.current = dict(bot)

    def save_bot(self, bot):
        self.current = dict(bot)
        return bot

    def get_bot(self, bot_id):
        if self.current.get("id") == bot_id:
            return dict(self.current)
        return None


def _make_cycle_bot(*, investment, grid_count, lower_price, upper_price):
    return {
        "id": "bot-1",
        "symbol": "TESTUSDT",
        "status": "running",
        "mode": "neutral",
        "range_mode": "fixed",
        "investment": investment,
        "leverage": 1.0,
        "grid_count": grid_count,
        "target_grid_count": grid_count,
        "lower_price": lower_price,
        "upper_price": upper_price,
        "entry_gate_enabled": False,
        "upnl_stoploss_enabled": False,
    }


def _make_position(*, size, side="Buy"):
    return {
        "symbol": "TESTUSDT",
        "size": str(size),
        "side": side,
        "unrealisedPnl": "0",
    }


def _make_reduce_only_sell(*, order_id, qty, price):
    return {
        "orderId": order_id,
        "side": "Sell",
        "reduceOnly": True,
        "qty": str(qty),
        "price": str(price),
    }


def _make_cycle_service(
    bot,
    *,
    last_price,
    levels,
    instrument,
    open_orders,
    positions,
    usable_investment,
    create_order_results,
):
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client.set_leverage.return_value = {"success": True}
    service.client.get_positions.return_value = {
        "success": True,
        "data": {"list": positions},
    }
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {"list": open_orders},
    }
    service.client.cancel_order.return_value = {"success": True}

    service.bot_storage = _FakeBotStorage(bot)
    service.indicator_service = Mock()
    service.indicator_service.compute_indicators.return_value = {
        "atr_pct": None,
        "bbw_pct": None,
    }
    service.grid_engine = SimpleNamespace(
        build_levels_with_distribution=Mock(
            return_value={
                "levels": levels,
                "total_count": len(levels),
                "buy_count": sum(1 for level in levels if level < last_price),
                "sell_count": sum(1 for level in levels if level > last_price),
            }
        )
    )
    service.range_engine = SimpleNamespace(default_width_pct=0.1)
    service.risk_manager = SimpleNamespace(
        check_bot_limits=Mock(return_value={"risk_stopped": False}),
        max_bot_loss_pct=0.05,
    )
    service.pnl_service = SimpleNamespace(sync_closed_pnl=Mock())
    service.session_service = SimpleNamespace(
        get_volatility_adjustment=Mock(return_value={})
    )
    service.entry_filter = None
    service.funding_rate_service = None
    service.micro_bias_service = None
    service.symbol_training_service = None
    service.scalp_pnl_service = None
    service.price_prediction_service = None
    service.stop_loss_service = None
    service.trend_protection_service = None
    service.take_profit_service = None
    service.danger_zone_service = None
    service.btc_guard_service = None
    service.adaptive_config_service = Mock()
    service._last_grid_center = {}
    service.GRID_STABILITY_THRESHOLD_PCT = DEFAULT_GRID_STABILITY_THRESHOLD_PCT

    for name in (
        "_safe_float",
        "_round_to_step",
        "_compute_reduce_only_budget",
        "_snapshot_open_orders",
        "_is_reduce_only_order",
        "_round_price_for_order",
        "_build_biased_levels",
        "_cap_levels_by_proximity",
        "_build_order_link_id",
        "_get_blocked_until_ts",
    ):
        setattr(service, name, getattr(GridBotService, name).__get__(service, GridBotService))

    service._ensure_stream_symbol = Mock()
    service._get_position_mode = Mock(return_value="hedge")
    service._auto_margin_guard = Mock()
    service._get_volatility_derisk_profile = Mock(
        return_value={
            "tier": "normal",
            "step_mult": 1.0,
            "size_mult": 1.0,
            "open_cap_total": None,
            "block_opening_orders": False,
        }
    )
    service._refresh_multi_tf_regime_snapshot = Mock()
    service._maybe_auto_select_neutral_mode = Mock(return_value=(bot, False))
    service._ai_block_opening_orders = Mock(return_value=False)
    service._close_opposite_positions = Mock()
    service._maybe_trigger_symbol_daily_kill_switch = Mock(return_value=None)
    service._failure_breaker_skip_opening_orders = Mock(return_value=(False, None))
    service._get_last_price = Mock(return_value=last_price)
    service._get_effective_investment = Mock(
        side_effect=lambda _bot, investment: investment
    )
    service._maybe_trigger_auto_stop_loss = Mock(return_value=None)
    service._get_instrument_info = Mock(return_value=instrument)
    service._calculate_effective_capital = Mock(return_value=1000.0)
    service._get_usdt_available_balance = Mock(return_value=5000.0)
    service._trim_opening_orders_to_cap = Mock(return_value=set())
    service._cancel_duplicate_bot_orders = Mock(
        return_value={"cancelled_count": 0, "order_list": open_orders}
    )
    service._get_fee_aware_min_step_pct = Mock(return_value=0.0)
    service._evaluate_structure_entry_blocks = Mock(
        return_value={
            "skip_buy": False,
            "skip_sell": False,
            "buy_reason": "",
            "sell_reason": "",
        }
    )
    service._calculate_auto_margin_reserve = Mock(
        return_value=(0.0, usable_investment)
    )
    service._maybe_run_dynamic_quick_profit = Mock()
    service._register_failure_breaker_event = Mock()
    service._clear_failure_breaker = Mock()
    service._is_insufficient_margin_result = Mock(return_value=False)
    service._prune_far_orders_for_margin = Mock(return_value=(0, 0))
    service._has_order_near_level = Mock(return_value=False)
    service._detect_candle_color = Mock(return_value="neutral")
    service._create_order_checked = Mock(side_effect=create_order_results)
    return service


def _placed_order_kwargs(service):
    return [call.kwargs for call in service._create_order_checked.call_args_list]


def test_reduce_only_budget_preserves_full_uncovered_position_qty():
    service = _make_service()

    available_total, per_order_qty = service._compute_reduce_only_budget(
        current_position_size=930.0,
        existing_reduce_only_qty=0.0,
        position_size_per_level=232.0,
        qty_step=1.0,
        min_order_qty=1.0,
        min_notional_value=5.0,
        last_price=0.093,
    )

    assert available_total == 930.0
    assert per_order_qty == 232.0


def test_reduce_only_budget_respects_existing_reserved_qty():
    service = _make_service()

    available_total, per_order_qty = service._compute_reduce_only_budget(
        current_position_size=462.0,
        existing_reduce_only_qty=231.0,
        position_size_per_level=231.0,
        qty_step=1.0,
        min_order_qty=1.0,
        min_notional_value=5.0,
        last_price=0.093,
    )

    assert available_total == 231.0
    assert per_order_qty == 231.0


def test_reduce_only_budget_exhausts_when_reserved_or_remaining_notional_too_small():
    service = _make_service()

    available_total, per_order_qty = service._compute_reduce_only_budget(
        current_position_size=1400.0,
        existing_reduce_only_qty=1398.0,
        position_size_per_level=233.0,
        qty_step=1.0,
        min_order_qty=1.0,
        min_notional_value=5.0,
        last_price=0.093,
    )

    assert available_total == 0.0
    assert per_order_qty == 0.0


def test_reduce_only_cycle_seeds_multiple_exit_levels_after_partial_reservation(
    caplog,
):
    bot = _make_cycle_bot(
        investment=1564.0,
        grid_count=4,
        lower_price=0.6,
        upper_price=1.4,
    )
    service = _make_cycle_service(
        bot,
        last_price=1.0,
        levels=[1.1, 1.2, 1.3, 1.4],
        instrument={
            "tick_size": 0.01,
            "qty_step": 1.0,
            "min_order_qty": 1.0,
            "min_notional_value": 5.0,
        },
        open_orders=[
            _make_reduce_only_sell(order_id="ro-1", qty=65, price=1.05),
        ],
        positions=[_make_position(size=1237)],
        usable_investment=1564.0,
        create_order_results=[{"success": True} for _ in range(3)],
    )

    caplog.set_level(logging.INFO, logger="services.grid_bot_service")
    result = GridBotService._run_bot_cycle_impl(service, dict(bot))
    placed_orders = _placed_order_kwargs(service)

    assert result["orders_placed"] == 3
    assert [order["side"] for order in placed_orders] == ["Sell", "Sell", "Sell"]
    assert [order["reduce_only"] for order in placed_orders] == [True, True, True]
    assert [order["qty"] for order in placed_orders] == [391.0, 391.0, 390.0]
    assert [order["price"] for order in placed_orders] == [1.1, 1.2, 1.3]
    assert "reduce_only_exhausted:1" in caplog.text
    assert "Placed 3 new orders, 0 failed" in caplog.text


def test_reduce_only_cycle_skips_new_exits_when_position_is_fully_reserved(caplog):
    bot = _make_cycle_bot(
        investment=1200.0,
        grid_count=3,
        lower_price=0.7,
        upper_price=1.3,
    )
    service = _make_cycle_service(
        bot,
        last_price=1.0,
        levels=[1.1, 1.2, 1.3],
        instrument={
            "tick_size": 0.01,
            "qty_step": 1.0,
            "min_order_qty": 1.0,
            "min_notional_value": 5.0,
        },
        open_orders=[
            _make_reduce_only_sell(order_id="ro-1", qty=300, price=1.05),
            _make_reduce_only_sell(order_id="ro-2", qty=300, price=1.15),
            _make_reduce_only_sell(order_id="ro-3", qty=300, price=1.25),
        ],
        positions=[_make_position(size=900)],
        usable_investment=1200.0,
        create_order_results=[],
    )

    caplog.set_level(logging.INFO, logger="services.grid_bot_service")
    result = GridBotService._run_bot_cycle_impl(service, dict(bot))

    assert result["orders_placed"] == 0
    assert service._create_order_checked.call_count == 0
    assert "reduce_only_exhausted:3" in caplog.text
    assert "Placed 0 new orders, 0 failed" in caplog.text


def test_reduce_only_cycle_decrements_budget_only_after_success(caplog):
    bot = _make_cycle_bot(
        investment=1200.0,
        grid_count=3,
        lower_price=0.7,
        upper_price=1.3,
    )
    service = _make_cycle_service(
        bot,
        last_price=1.0,
        levels=[1.1, 1.2, 1.3],
        instrument={
            "tick_size": 0.01,
            "qty_step": 1.0,
            "min_order_qty": 1.0,
            "min_notional_value": 5.0,
        },
        open_orders=[
            _make_reduce_only_sell(order_id="ro-1", qty=100, price=1.05),
        ],
        positions=[_make_position(size=900)],
        usable_investment=1200.0,
        create_order_results=[
            {"success": True},
            {"success": False, "error": "boom", "retCode": 123},
            {"success": True},
        ],
    )

    caplog.set_level(logging.INFO, logger="services.grid_bot_service")
    result = GridBotService._run_bot_cycle_impl(service, dict(bot))
    placed_orders = _placed_order_kwargs(service)

    assert result["orders_placed"] == 2
    assert [order["qty"] for order in placed_orders] == [400.0, 400.0, 400.0]
    assert [order["reduce_only"] for order in placed_orders] == [True, True, True]
    assert "FAILED Sell at 1.2: boom" in caplog.text
    assert "Placed 2 new orders, 1 failed" in caplog.text


def test_reduce_only_cycle_exhausts_tiny_remaining_budget_without_invalid_order(
    caplog,
):
    bot = _make_cycle_bot(
        investment=200.0,
        grid_count=2,
        lower_price=0.09,
        upper_price=0.096,
    )
    service = _make_cycle_service(
        bot,
        last_price=0.093,
        levels=[0.094, 0.095],
        instrument={
            "tick_size": 0.001,
            "qty_step": 1.0,
            "min_order_qty": 1.0,
            "min_notional_value": 5.0,
        },
        open_orders=[
            _make_reduce_only_sell(order_id="ro-1", qty=1398, price=0.096),
        ],
        positions=[_make_position(size=1400)],
        usable_investment=200.0,
        create_order_results=[],
    )

    caplog.set_level(logging.INFO, logger="services.grid_bot_service")
    result = GridBotService._run_bot_cycle_impl(service, dict(bot))

    assert result["orders_placed"] == 0
    assert service._create_order_checked.call_count == 0
    assert "reduce_only_exhausted:2" in caplog.text
    assert "Placed 0 new orders, 0 failed" in caplog.text
