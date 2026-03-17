import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.grid_bot_service import GridBotService


MAX_SCALP_ORDERS = 25


class _FakeBotStorage:
    def __init__(self):
        self.saved_bots = []

    def save_bot(self, bot):
        self.saved_bots.append(dict(bot))
        return bot


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.bot_storage = _FakeBotStorage()
    service.scalp_pnl_service = Mock()
    service.orderbook_service = Mock()
    service.orderbook_service.calculate_imbalance.return_value = {"success": False}
    service.micro_bias_service = None
    service.trend_protection_service = None
    service.take_profit_service = None
    service.stop_loss_service = None
    service.pnl_service = Mock()
    return service


def _configure_cycle_to_resolve_levels(
    service,
    *,
    condition: str,
    momentum_direction: str,
    should_follow_trend: bool,
):
    service.client.get_positions.return_value = {"success": True, "data": {"list": []}}
    service.client.get_open_orders.return_value = {"success": True, "data": {"list": []}}
    service.scalp_pnl_service.update_price_history = Mock()
    service.scalp_pnl_service.get_price_history.return_value = [100.0, 99.8, 99.6]
    service.scalp_pnl_service.analyze_market_condition.return_value = (
        SimpleNamespace(value=condition),
        {
            "recommended_grid_distance": 0.01,
            "momentum_direction": momentum_direction,
            "momentum_strength": 0.8,
            "volatility_level": "normal",
            "is_choppy": not should_follow_trend,
            "recommended_profit_target": 0.5,
            "should_follow_trend": should_follow_trend,
        },
    )
    service.scalp_pnl_service.calculate_adaptive_min_profit.return_value = 0.1
    service._ai_block_opening_orders = Mock(return_value=False)
    service._failure_breaker_skip_opening_orders = Mock(return_value=(False, None))
    service._get_instrument_info = Mock(
        return_value={
            "tick_size": 0.1,
            "qty_step": 0.1,
            "min_order_qty": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_fee_aware_min_step_pct = Mock(return_value=0.0)
    service._get_scalp_effective_opening_order_cap = Mock(
        return_value=MAX_SCALP_ORDERS
    )
    service._trim_opening_orders_to_cap = Mock(return_value=set())
    service._cancel_duplicate_bot_orders = Mock(
        return_value={"cancelled_count": 0, "order_list": []}
    )
    service._cleanup_stale_scalp_orders = Mock(
        return_value={
            "orders_cancelled": 0,
            "order_list": [],
            "order_snapshot": {
                "existing_order_prices": set(),
                "existing_order_prices_list": [],
                "existing_orders_with_ids": [],
                "current_order_count": 0,
                "current_opening_order_count": 0,
                "current_opening_buy_count": 0,
                "current_opening_sell_count": 0,
            },
            "available_slots": MAX_SCALP_ORDERS,
        }
    )
    service._resolve_locked_scalp_grid_levels = Mock(
        side_effect=RuntimeError("STOP_AFTER_RESOLVE")
    )


def test_grid_levels_cached_across_cycles():
    service = _make_service()
    service.scalp_pnl_service.get_scalp_grid_levels.return_value = (
        [99.0, 98.0],
        [101.0, 102.0],
    )
    bot = {
        "_scalp_fill_seq": 0,
        "_scalp_grid_state": {
            "locked_center": 100.0,
            "buy_levels": [99.0, 98.0],
            "sell_levels": [101.0, 102.0],
            "last_fill_seq": 0,
        },
    }

    buy_levels, sell_levels = service._resolve_locked_scalp_grid_levels(
        bot=bot,
        symbol="BTCUSDT",
        scalp_center=100.0,
        market_analysis={"momentum_direction": "down", "recommended_grid_distance": 0.003},
        tick_size=0.1,
        grid_count=MAX_SCALP_ORDERS,
        force_balanced=False,
        now_iso="2026-03-07T00:00:00+00:00",
    )

    assert buy_levels == [99.0, 98.0]
    assert sell_levels == [101.0, 102.0]
    service.scalp_pnl_service.get_scalp_grid_levels.assert_not_called()


def test_grid_levels_refresh_on_fill():
    service = _make_service()
    service.scalp_pnl_service.get_scalp_grid_levels.return_value = (
        [99.5, 99.0],
        [100.5, 101.0],
    )
    bot = {
        "_scalp_fill_seq": 2,
        "_scalp_grid_state": {
            "locked_center": 100.0,
            "buy_levels": [99.0, 98.0],
            "sell_levels": [101.0, 102.0],
            "last_fill_seq": 1,
        },
    }

    buy_levels, sell_levels = service._resolve_locked_scalp_grid_levels(
        bot=bot,
        symbol="BTCUSDT",
        scalp_center=100.0,
        market_analysis={"momentum_direction": "neutral", "recommended_grid_distance": 0.003},
        tick_size=0.1,
        grid_count=MAX_SCALP_ORDERS,
        force_balanced=False,
        now_iso="2026-03-07T00:00:00+00:00",
    )

    assert buy_levels == [99.5, 99.0]
    assert sell_levels == [100.5, 101.0]
    service.scalp_pnl_service.get_scalp_grid_levels.assert_called_once()
    assert bot["_scalp_grid_state"]["last_fill_seq"] == 2


def test_grid_levels_refresh_on_center_change():
    service = _make_service()
    service.scalp_pnl_service.get_scalp_grid_levels.return_value = (
        [100.2, 100.1],
        [100.4, 100.5],
    )
    bot = {
        "_scalp_fill_seq": 0,
        "_scalp_grid_state": {
            "locked_center": 100.0,
            "buy_levels": [99.0, 98.0],
            "sell_levels": [101.0, 102.0],
            "last_fill_seq": 0,
        },
    }

    buy_levels, sell_levels = service._resolve_locked_scalp_grid_levels(
        bot=bot,
        symbol="BTCUSDT",
        scalp_center=100.3,
        market_analysis={"momentum_direction": "neutral", "recommended_grid_distance": 0.003},
        tick_size=0.1,
        grid_count=MAX_SCALP_ORDERS,
        force_balanced=False,
        now_iso="2026-03-07T00:00:00+00:00",
    )

    assert buy_levels == [100.2, 100.1]
    assert sell_levels == [100.4, 100.5]
    service.scalp_pnl_service.get_scalp_grid_levels.assert_called_once()
    assert bot["_scalp_grid_state"]["locked_center"] == pytest.approx(100.3)


def test_tolerance_scales_with_grid_distance():
    service = _make_service()

    assert service._get_scalp_order_tolerance_pct(0.003) == pytest.approx(0.0012)
    assert service._get_scalp_order_tolerance_pct(0.001) == pytest.approx(0.0004)
    assert service._get_scalp_order_tolerance_pct(0.02) == pytest.approx(0.005)


def test_stale_cleanup_runs_before_placement():
    service = _make_service()
    call_order = []
    stale_order = {
        "orderId": "stale-1",
        "price": "130",
        "side": "Buy",
        "reduceOnly": False,
    }

    service.client.get_positions.return_value = {"success": True, "data": {"list": []}}
    service.client.get_open_orders.side_effect = [
        {"success": True, "data": {"list": [stale_order]}},
        {"success": True, "data": {"list": [stale_order]}},
        {"success": True, "data": {"list": []}},
    ]
    service.client.cancel_order.side_effect = (
        lambda *args, **kwargs: (call_order.append("cancel"), {"success": True})[1]
    )

    service.scalp_pnl_service.update_price_history = Mock()
    service.scalp_pnl_service.get_price_history.return_value = [100.0]
    service.scalp_pnl_service.analyze_market_condition.return_value = (
        SimpleNamespace(value="neutral"),
        {
            "recommended_grid_distance": 0.01,
            "momentum_direction": "neutral",
            "volatility_level": "calm",
            "is_choppy": True,
            "recommended_profit_target": 0.5,
        },
    )
    service.scalp_pnl_service.calculate_adaptive_min_profit.return_value = 0.1
    service.scalp_pnl_service.get_recommended_side.return_value = "Buy"

    service._get_effective_investment = Mock(side_effect=lambda bot, fallback: fallback)
    service._ai_block_opening_orders = Mock(return_value=False)
    service._failure_breaker_skip_opening_orders = Mock(return_value=(False, None))
    service._get_instrument_info = Mock(
        return_value={
            "tick_size": 0.1,
            "qty_step": 0.1,
            "min_order_qty": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_fee_aware_min_step_pct = Mock(return_value=0.0)
    service._get_scalp_effective_opening_order_cap = Mock(
        return_value=MAX_SCALP_ORDERS
    )
    service._trim_opening_orders_to_cap = Mock(return_value=set())
    service._resolve_locked_scalp_grid_levels = Mock(
        return_value=([99.0], [101.0])
    )
    service._cap_levels_by_proximity = Mock(
        side_effect=lambda buy_levels, sell_levels, last_price, max_total: (
            buy_levels,
            sell_levels,
        )
    )
    service._calculate_auto_margin_reserve = Mock(return_value=(0.0, 100.0))
    service._get_usdt_available_balance = Mock(return_value=1000.0)
    service._normalize_order_qty = Mock(return_value=1.0)
    service._register_failure_breaker_event = Mock()
    service._cancel_opening_orders_only = Mock(return_value=0)
    service._build_order_link_id = Mock(
        side_effect=lambda **kwargs: f"{kwargs['side']}-{kwargs['seq']}"
    )
    service._round_price_for_order = Mock(side_effect=lambda value, tick_size, side: value)
    service._create_order_checked = Mock(
        side_effect=lambda **kwargs: (call_order.append("place"), {"success": True})[1]
    )
    service._maybe_relax_scalp_opening_order_cap = Mock(
        return_value=MAX_SCALP_ORDERS
    )
    service._clear_failure_breaker = Mock()

    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "scalp_pnl",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_count": 12,
        "scalp_grid_center": 100.0,
        "status": "running",
    }

    with patch("services.grid_bot_service.time.sleep") as sleep_mock:
        result = service._run_scalp_pnl_cycle(
            bot=bot,
            symbol="BTCUSDT",
            last_price=100.0,
            fast_indicators={},
            now_iso="2026-03-07T00:00:00+00:00",
            fast_refill_tick=True,
        )

    assert result is bot
    assert call_order[0] == "cancel"
    assert "place" in call_order[1:]
    sleep_mock.assert_called_once_with(0.3)


def test_flat_scalp_grid_uses_trend_skew_when_market_should_follow_trend():
    service = _make_service()
    _configure_cycle_to_resolve_levels(
        service,
        condition="trending_down",
        momentum_direction="down",
        should_follow_trend=True,
    )
    bot = {
        "id": "bot-trend",
        "symbol": "BTCUSDT",
        "mode": "scalp_pnl",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_count": 12,
        "scalp_grid_center": 100.0,
        "status": "running",
    }

    with pytest.raises(RuntimeError, match="STOP_AFTER_RESOLVE"):
        service._run_scalp_pnl_cycle(
            bot=bot,
            symbol="BTCUSDT",
            last_price=100.0,
            fast_indicators={},
            now_iso="2026-03-07T00:00:00+00:00",
            fast_refill_tick=True,
        )

    assert (
        service._resolve_locked_scalp_grid_levels.call_args.kwargs["force_balanced"]
        is False
    )


def test_flat_scalp_grid_stays_balanced_when_market_is_choppy():
    service = _make_service()
    _configure_cycle_to_resolve_levels(
        service,
        condition="choppy",
        momentum_direction="neutral",
        should_follow_trend=False,
    )
    bot = {
        "id": "bot-chop",
        "symbol": "BTCUSDT",
        "mode": "scalp_pnl",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_count": 12,
        "scalp_grid_center": 100.0,
        "status": "running",
    }

    with pytest.raises(RuntimeError, match="STOP_AFTER_RESOLVE"):
        service._run_scalp_pnl_cycle(
            bot=bot,
            symbol="BTCUSDT",
            last_price=100.0,
            fast_indicators={},
            now_iso="2026-03-07T00:00:00+00:00",
            fast_refill_tick=True,
        )

    assert (
        service._resolve_locked_scalp_grid_levels.call_args.kwargs["force_balanced"]
        is True
    )


def test_scalp_qty_below_min_becomes_waiting_state_without_extra_warning(caplog):
    service = _make_service()

    service.client.get_positions.return_value = {"success": True, "data": {"list": []}}
    service.client.get_open_orders.return_value = {"success": True, "data": {"list": []}}
    service.scalp_pnl_service.update_price_history = Mock()
    service.scalp_pnl_service.get_price_history.return_value = [100.0]
    service.scalp_pnl_service.analyze_market_condition.return_value = (
        SimpleNamespace(value="neutral"),
        {
            "recommended_grid_distance": 0.01,
            "momentum_direction": "neutral",
            "momentum_strength": 0.2,
            "volatility_level": "normal",
            "is_choppy": True,
            "recommended_profit_target": 0.5,
            "should_follow_trend": False,
        },
    )
    service.scalp_pnl_service.calculate_adaptive_min_profit.return_value = 0.1
    service.scalp_pnl_service.get_recommended_side.return_value = "Buy"
    service._get_effective_investment = Mock(side_effect=lambda bot, fallback: fallback)
    service._ai_block_opening_orders = Mock(return_value=False)
    service._failure_breaker_skip_opening_orders = Mock(return_value=(False, None))
    service._get_instrument_info = Mock(
        return_value={
            "tick_size": 0.1,
            "qty_step": 0.1,
            "min_order_qty": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_fee_aware_min_step_pct = Mock(return_value=0.0)
    service._get_scalp_effective_opening_order_cap = Mock(
        return_value=MAX_SCALP_ORDERS
    )
    service._trim_opening_orders_to_cap = Mock(return_value=set())
    service._cancel_duplicate_bot_orders = Mock(
        return_value={"cancelled_count": 0, "order_list": []}
    )
    service._cleanup_stale_scalp_orders = Mock(
        return_value={
            "orders_cancelled": 0,
            "order_list": [],
            "order_snapshot": {
                "existing_order_prices": set(),
                "existing_order_prices_list": [],
                "existing_orders_with_ids": [],
                "current_order_count": 0,
                "current_opening_order_count": 0,
                "current_opening_buy_count": 0,
                "current_opening_sell_count": 0,
            },
            "available_slots": MAX_SCALP_ORDERS,
        }
    )
    service._resolve_locked_scalp_grid_levels = Mock(
        return_value=([99.0], [101.0])
    )
    service._cap_levels_by_proximity = Mock(
        side_effect=lambda buy_levels, sell_levels, last_price, max_total: (
            buy_levels,
            sell_levels,
        )
    )
    service._evaluate_structure_entry_blocks = Mock(
        return_value={
            "skip_buy": False,
            "skip_sell": False,
            "buy_reason": "",
            "sell_reason": "",
        }
    )
    service._calculate_auto_margin_reserve = Mock(return_value=(0.0, 0.05))
    service._get_usdt_available_balance = Mock(return_value=1000.0)
    service._normalize_order_qty = Mock(return_value=None)

    bot = {
        "id": "bot-small",
        "symbol": "BTCUSDT",
        "mode": "scalp_pnl",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_count": 12,
        "scalp_grid_center": 100.0,
        "status": "running",
    }

    with caplog.at_level(logging.WARNING):
        result = service._run_scalp_pnl_cycle(
            bot=bot,
            symbol="BTCUSDT",
            last_price=100.0,
            fast_indicators={},
            now_iso="2026-03-08T08:46:54+00:00",
            fast_refill_tick=True,
        )

    assert result is bot
    assert bot["last_error"] is None
    assert bot["last_skip_reason"] == "qty_below_min"
    assert bot["last_warning"] == "Capital starved: qty 0.000125 below min 0.100000"
    assert bot["scalp_status"] == "Waiting: qty 0.000125 < min 0.100000"
    assert service.bot_storage.saved_bots[-1]["symbol"] == "BTCUSDT"
    assert "Scalp position size below minimum after normalization" not in caplog.text


def test_scalp_tp_zero_position_does_not_hard_fail_or_book_pnl():
    service = _make_service()
    service._hard_fail_close = Mock()
    service._mark_scalp_fill_event = Mock()
    service._get_effective_investment = Mock(side_effect=lambda bot, fallback: fallback)
    service._ai_block_opening_orders = Mock(return_value=True)
    service._failure_breaker_skip_opening_orders = Mock(return_value=(False, None))
    service._get_instrument_info = Mock(
        return_value={
            "tick_size": 0.1,
            "qty_step": 0.1,
            "min_order_qty": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_fee_aware_min_step_pct = Mock(return_value=0.0)
    service._cancel_duplicate_bot_orders = Mock(
        return_value={"cancelled_count": 0, "order_list": []}
    )
    service._resolve_position_idx = Mock(return_value=1)
    service.client._get_now_ts.return_value = 1000.0
    service._create_order_checked = Mock(
        return_value={
            "success": False,
            "position_empty": True,
            "error": "current position is zero, cannot fix reduce-only order qty",
            "retCode": 110017,
        }
    )
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "1",
                    "positionIdx": 1,
                    "unrealisedPnl": "0.8",
                    "positionValue": "100",
                    "markPrice": "100",
                }
            ]
        },
    }
    service.scalp_pnl_service.update_price_history = Mock()
    service.scalp_pnl_service.get_price_history.return_value = [100.0]
    service.scalp_pnl_service.analyze_market_condition.return_value = (
        SimpleNamespace(value="neutral"),
        {
            "recommended_grid_distance": 0.01,
            "momentum_direction": "neutral",
            "momentum_strength": 0.2,
            "volatility_level": "normal",
            "is_choppy": True,
            "recommended_profit_target": 0.5,
            "should_follow_trend": False,
        },
    )
    service.scalp_pnl_service.calculate_adaptive_min_profit.return_value = 0.1
    service.scalp_pnl_service.calculate_position_scaled_targets.return_value = {
        "recommended_target": 0.5,
        "quick_profit": 0.2,
        "min_profit": 0.1,
    }
    service.scalp_pnl_service.should_take_profit.return_value = (True, "quick tp")
    service.scalp_pnl_service.record_close = Mock()

    bot = {
        "id": "bot-flat",
        "symbol": "BTCUSDT",
        "mode": "scalp_pnl",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_count": 12,
        "status": "running",
        "realized_pnl": 0.0,
        "position_entries": {"BTCUSDT_Buy": 900.0},
    }

    result = service._run_scalp_pnl_cycle(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={},
        now_iso="2026-03-09T03:09:00+00:00",
        fast_refill_tick=True,
    )

    assert result is bot
    assert bot["realized_pnl"] == 0.0
    assert bot["position_entries"] == {}
    assert bot["status"] == "running"
    assert bot["last_error"] is None
    assert bot["last_warning"] == "Opening guard active"
    service._hard_fail_close.assert_not_called()
    service.scalp_pnl_service.record_close.assert_called_once_with("BTCUSDT")
