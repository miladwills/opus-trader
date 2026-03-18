from unittest.mock import Mock

import pytest

from services.grid_bot_service import GridBotService


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service._check_quick_profit = Mock()
    service._trigger_quick_profit_recenter = Mock(return_value={"success": True})
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    return service


def _make_profit_speed_service(now_ts=1000.0):
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client._get_now_ts.return_value = now_ts
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._get_cycle_now_ts = GridBotService._get_cycle_now_ts.__get__(
        service, GridBotService
    )
    service._track_position_timing = GridBotService._track_position_timing.__get__(
        service, GridBotService
    )
    service._get_quick_profit_speed_adjustment = (
        GridBotService._get_quick_profit_speed_adjustment.__get__(
            service, GridBotService
        )
    )
    service._get_scaled_quick_profit_targets = (
        GridBotService._get_scaled_quick_profit_targets.__get__(
            service, GridBotService
        )
    )
    service._get_effective_min_profit_pct = (
        GridBotService._get_effective_min_profit_pct.__get__(
            service, GridBotService
        )
    )
    service.scalp_pnl_service = None
    service._build_order_link_id = Mock(return_value="qp-fast")
    service._cancel_bot_reduce_only_orders = Mock(return_value=0)
    service._hard_fail_close = Mock()
    service._create_order_checked = Mock(
        return_value={"success": True, "normalized_qty": 2.4}
    )
    return service


def test_run_quick_profit_check_uses_fresh_positions_and_selects_long_buy_leg():
    service = _make_service()
    bot = {
        "mode": "long",
        "range_mode": "dynamic",
        "realized_pnl": 1.0,
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {"symbol": "BTCUSDT", "side": "Sell", "size": "3", "positionIdx": 2},
                {"symbol": "BTCUSDT", "side": "Buy", "size": "5", "positionIdx": 1},
                {"symbol": "BTCUSDT", "side": "Buy", "size": "0", "positionIdx": 1},
            ]
        },
    }
    service._check_quick_profit.return_value = {
        "success": True,
        "profit_taken": 0.25,
        "recenter_needed": False,
        "remaining_size": 2.5,
    }

    service._run_quick_profit_check(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={"rsi": 55},
    )

    service.client.get_positions.assert_called_once_with(skip_cache=True)
    service._check_quick_profit.assert_called_once()
    selected_position = service._check_quick_profit.call_args.kwargs["position"]
    assert selected_position["side"] == "Buy"
    assert selected_position["size"] == "5"
    assert bot["realized_pnl"] == 1.25
    service._trigger_quick_profit_recenter.assert_not_called()


def test_run_quick_profit_check_recenters_after_success():
    service = _make_service()
    bot = {
        "mode": "long",
        "range_mode": "dynamic",
        "realized_pnl": 0.0,
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {"symbol": "BTCUSDT", "side": "Buy", "size": "2", "positionIdx": 1},
            ]
        },
    }
    service._check_quick_profit.return_value = {
        "success": True,
        "profit_taken": 0.1,
        "recenter_needed": True,
        "remaining_size": 1.0,
    }

    service._run_quick_profit_check(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={},
    )

    service._trigger_quick_profit_recenter.assert_called_once_with(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        remaining_position_size=1.0,
    )


def test_maybe_run_dynamic_quick_profit_calls_shared_check_for_long_mode():
    service = GridBotService.__new__(GridBotService)
    service._run_quick_profit_check = Mock()

    GridBotService._maybe_run_dynamic_quick_profit(
        service,
        bot={"mode": "long", "range_mode": "dynamic"},
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={"rsi": 55},
    )

    service._run_quick_profit_check.assert_called_once_with(
        bot={"mode": "long", "range_mode": "dynamic"},
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={"rsi": 55},
    )


def test_maybe_run_dynamic_quick_profit_skips_fixed_range():
    service = GridBotService.__new__(GridBotService)
    service._run_quick_profit_check = Mock()

    GridBotService._maybe_run_dynamic_quick_profit(
        service,
        bot={"mode": "long", "range_mode": "fixed"},
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={},
    )

    service._run_quick_profit_check.assert_not_called()


def test_check_quick_profit_tolerates_null_storage_fields():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service.scalp_pnl_service = None
    service._get_scaled_quick_profit_targets = (
        GridBotService._get_scaled_quick_profit_targets.__get__(
            service, GridBotService
        )
    )
    service._build_order_link_id = Mock(return_value="qp-close-1")
    service._cancel_bot_reduce_only_orders = Mock(return_value=1)
    service._hard_fail_close = Mock()
    service._create_order_checked = Mock(
        return_value={"success": True, "normalized_qty": 2.0}
    )

    bot = {
        "id": "bot-qp-1",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_min": None,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "quick_profit_cooldown": 60,
        "quick_profit_count": None,
        "quick_profit_total": None,
        "last_quick_profit_at": None,
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "4",
        "unrealisedPnl": "0.2",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={},
        position=position,
    )

    assert result["success"] is True
    assert result["close_qty"] == 2.0
    assert bot["quick_profit_count"] == 1
    assert bot["quick_profit_total"] == 0.1
    service._cancel_bot_reduce_only_orders.assert_called_once_with(
        bot=bot,
        symbol="BTCUSDT",
        side="Sell",
    )
    service._hard_fail_close.assert_not_called()
    service._create_order_checked.assert_called_once_with(
        bot=bot,
        symbol="BTCUSDT",
        side="Sell",
        qty=2.0,
        order_type="Market",
        price=10.0,
        reduce_only=True,
        time_in_force="GTC",
        order_link_id="qp-close-1",
        full_close_qty=4.0,
    )


def test_check_quick_profit_respects_fee_floor_before_closing():
    service = _make_profit_speed_service(now_ts=1000.0)
    bot = {
        "id": "bot-qp-fee",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_min": 0.1,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "quick_profit_cooldown": 60,
        "fee_rate": 0.00055,
        "fast_exec_slippage_buffer_pct": 0.001,
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "10",
        "unrealisedPnl": "0.18",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={},
        position=position,
    )

    assert result is None
    service._create_order_checked.assert_not_called()


def test_check_quick_profit_skips_after_recent_fast_partial_exit():
    service = _make_profit_speed_service(now_ts=1000.0)
    bot = {
        "id": "bot-qp-fast",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_min": 0.1,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "quick_profit_cooldown": 60,
        "fast_partial_tp_state": {"last_close_ts": 980.0},
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "10",
        "unrealisedPnl": "0.35",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={},
        position=position,
    )

    assert result is None
    service._create_order_checked.assert_not_called()


def test_check_quick_profit_skip_does_not_hard_fail():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service.scalp_pnl_service = None
    service._get_scaled_quick_profit_targets = (
        GridBotService._get_scaled_quick_profit_targets.__get__(
            service, GridBotService
        )
    )
    service._build_order_link_id = Mock(return_value="qp-close-skip")
    service._cancel_bot_reduce_only_orders = Mock(return_value=0)
    service._hard_fail_close = Mock()
    service._create_order_checked = Mock(
        return_value={"success": False, "skipped": True, "error": "qty_below_min"}
    )

    bot = {
        "id": "bot-qp-2",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "0.1",
        "unrealisedPnl": "0.2",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={},
        position=position,
    )

    assert result == {
        "success": False,
        "action": "quick_profit",
        "error": "qty_below_min",
        "skipped": True,
    }
    service._hard_fail_close.assert_not_called()


def test_scaled_quick_profit_targets_grow_with_live_position_notional():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)

    min_profit, target_profit, position_notional, scale = (
        service._get_scaled_quick_profit_targets(
            bot={},
            last_price=100.0,
            pos_size=3.0,
            min_profit=0.10,
            target_profit=0.15,
        )
    )

    assert position_notional == 300.0
    assert scale == 3.0
    assert round(min_profit, 2) == 0.30
    assert round(target_profit, 2) == 0.45


def test_check_quick_profit_waits_for_scaled_target_on_larger_position():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service.scalp_pnl_service = None
    service._get_scaled_quick_profit_targets = (
        GridBotService._get_scaled_quick_profit_targets.__get__(
            service, GridBotService
        )
    )
    service._build_order_link_id = Mock(return_value="qp-close-3")
    service._cancel_bot_reduce_only_orders = Mock(return_value=0)
    service._hard_fail_close = Mock()
    service._create_order_checked = Mock(
        return_value={"success": True, "normalized_qty": 1.5}
    )

    bot = {
        "id": "bot-qp-3",
        "mode": "short",
        "range_mode": "trailing",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Sell",
        "size": "3",
        "unrealisedPnl": "0.30",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={},
        position=position,
    )

    assert result is None
    service._create_order_checked.assert_not_called()
    assert bot["quick_profit_live_target"] == 0.45


def test_check_quick_profit_fast_burst_profit_lowers_target_and_increases_close_pct():
    service = _make_profit_speed_service()

    bot = {
        "id": "bot-qp-fast",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.20,
        "quick_profit_close_pct": 0.5,
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 940.0,
                "last_seen_ts": 995.0,
            }
        },
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "4",
        "avgPrice": "10",
        "unrealisedPnl": "0.18",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={"atr_pct": 0.04, "price_velocity": 0.015},
        position=position,
    )

    assert result["success"] is True
    assert round(result["target_threshold"], 2) == 0.17
    assert bot["quick_profit_fast_profit_active"] is True
    assert service._create_order_checked.call_args.kwargs["qty"] == 2.4


def test_check_quick_profit_fast_burst_protection_skips_slow_profit():
    service = _make_profit_speed_service()

    bot = {
        "id": "bot-qp-slow",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.20,
        "quick_profit_close_pct": 0.5,
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 500.0,
                "last_seen_ts": 995.0,
            }
        },
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "4",
        "avgPrice": "10",
        "unrealisedPnl": "0.18",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={"atr_pct": 0.04, "price_velocity": 0.015},
        position=position,
    )

    assert result is None
    assert bot["quick_profit_fast_profit_active"] is False
    service._create_order_checked.assert_not_called()


def test_check_quick_profit_fast_burst_protection_ignores_tiny_profit_noise():
    service = _make_profit_speed_service()

    bot = {
        "id": "bot-qp-noise",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 940.0,
                "last_seen_ts": 995.0,
            }
        },
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "4",
        "avgPrice": "10",
        "unrealisedPnl": "0.11",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={"atr_pct": 0.04, "price_velocity": 0.015},
        position=position,
    )

    assert result is None
    assert bot["quick_profit_fast_profit_active"] is False
    service._create_order_checked.assert_not_called()


def test_check_quick_profit_profit_speed_flag_preserves_existing_thresholds_when_disabled():
    service = _make_profit_speed_service()

    bot = {
        "id": "bot-qp-disabled",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_profit_speed_enabled": False,
        "quick_profit_target": 0.20,
        "quick_profit_close_pct": 0.5,
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 940.0,
                "last_seen_ts": 995.0,
            }
        },
    }
    position = {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "size": "4",
        "avgPrice": "10",
        "unrealisedPnl": "0.18",
    }

    result = service._check_quick_profit(
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={"atr_pct": 0.04, "price_velocity": 0.015},
        position=position,
    )

    assert result is None
    assert bot["quick_profit_fast_profit_active"] is False
    service._create_order_checked.assert_not_called()


def test_cancel_bot_reduce_only_orders_only_cancels_matching_side_and_bot():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service._is_reduce_only_order = GridBotService._is_reduce_only_order.__get__(
        service, GridBotService
    )
    service._parse_order_link_id = GridBotService._parse_order_link_id
    service._bot_id_matches_order_bot_id = (
        GridBotService._bot_id_matches_order_bot_id.__get__(service, GridBotService)
    )
    service._extract_order_list_from_response = (
        GridBotService._extract_order_list_from_response
    )

    bot = {"id": "7fe5dc76-0f86-4233-a74d-581ccfb8fead"}
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "orderId": "close-1",
                    "side": "Sell",
                    "reduceOnly": True,
                    "orderLinkId": "bv2:7fe5dc760f864233:12345678S0C",
                },
                {
                    "orderId": "close-other-bot",
                    "side": "Sell",
                    "reduceOnly": True,
                    "orderLinkId": "bv2:aaaaaaaaaaaaaaaa:12345678S0C",
                },
                {
                    "orderId": "open-1",
                    "side": "Sell",
                    "reduceOnly": False,
                    "orderLinkId": "bv2:7fe5dc760f864233:12345678S0O",
                },
                {
                    "orderId": "close-buy",
                    "side": "Buy",
                    "reduceOnly": True,
                    "orderLinkId": "bv2:7fe5dc760f864233:12345678B0C",
                },
            ]
        },
    }
    service.client.cancel_order.return_value = {"success": True}

    cancelled = GridBotService._cancel_bot_reduce_only_orders(
        service,
        bot=bot,
        symbol="RIVERUSDT",
        side="Sell",
    )

    assert cancelled == 1
    service.client.get_open_orders.assert_called_once_with(
        symbol="RIVERUSDT",
        limit=200,
        skip_cache=True,
    )
    service.client.cancel_order.assert_called_once_with(
        symbol="RIVERUSDT",
        order_id="close-1",
    )


def test_quick_profit_recenter_keeps_default_width_without_override():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._is_quick_profit_recenter_width_subset_bot = (
        GridBotService._is_quick_profit_recenter_width_subset_bot.__get__(
            service, GridBotService
        )
    )
    service._resolve_quick_profit_recenter_width_policy = (
        GridBotService._resolve_quick_profit_recenter_width_policy.__get__(
            service, GridBotService
        )
    )
    service._force_cancel_all_orders = Mock(return_value={"success": True, "cancelled": 0})
    service._last_grid_center = {}

    bot = {
        "id": "bot-qp-default",
        "range_mode": "dynamic",
        "last_range_width_pct": 0.045,
    }

    result = GridBotService._trigger_quick_profit_recenter(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=0.3903,
        remaining_position_size=10.0,
    )

    assert result["success"] is True
    assert bot["lower_price"] == pytest.approx(0.38151825)
    assert bot["upper_price"] == pytest.approx(0.39908175)
    assert bot["quick_profit_recenter_width_mult_applied"] == 1.0
    assert bot["quick_profit_recenter_width_source"] == "default"
    assert bot["quick_profit_recenter_width_pct_applied"] == pytest.approx(0.045)


def test_quick_profit_recenter_honors_manual_width_override():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._is_quick_profit_recenter_width_subset_bot = (
        GridBotService._is_quick_profit_recenter_width_subset_bot.__get__(
            service, GridBotService
        )
    )
    service._resolve_quick_profit_recenter_width_policy = (
        GridBotService._resolve_quick_profit_recenter_width_policy.__get__(
            service, GridBotService
        )
    )
    service._force_cancel_all_orders = Mock(return_value={"success": True, "cancelled": 0})
    service._last_grid_center = {}

    bot = {
        "id": "bot-qp-pippin",
        "range_mode": "dynamic",
        "last_range_width_pct": 0.045,
        "manual_quick_profit_recenter_width_mult": 0.75,
    }

    result = GridBotService._trigger_quick_profit_recenter(
        service,
        bot=bot,
        symbol="PIPPINUSDT",
        last_price=0.3903,
        remaining_position_size=10.0,
    )

    assert result["success"] is True
    assert bot["lower_price"] == pytest.approx(0.3837136875)
    assert bot["upper_price"] == pytest.approx(0.3968863125)
    assert bot["quick_profit_recenter_width_mult_applied"] == 0.75
    assert bot["quick_profit_recenter_width_source"] == "manual_override"
    assert bot["quick_profit_recenter_width_pct_applied"] == pytest.approx(0.03375)


def test_quick_profit_recenter_non_matching_bot_keeps_default_width():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._is_quick_profit_recenter_width_subset_bot = (
        GridBotService._is_quick_profit_recenter_width_subset_bot.__get__(
            service, GridBotService
        )
    )
    service._resolve_quick_profit_recenter_width_policy = (
        GridBotService._resolve_quick_profit_recenter_width_policy.__get__(
            service, GridBotService
        )
    )
    service._force_cancel_all_orders = Mock(return_value={"success": True, "cancelled": 0})
    service._last_grid_center = {}

    bot = {
        "id": "bot-qp-trailing",
        "mode": "long",
        "range_mode": "trailing",
        "grid_distribution": "clustered",
        "last_range_width_pct": 0.045,
    }

    result = GridBotService._trigger_quick_profit_recenter(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=0.3903,
        remaining_position_size=10.0,
    )

    assert result["success"] is True
    assert bot["lower_price"] == pytest.approx(0.38151825)
    assert bot["upper_price"] == pytest.approx(0.39908175)
    assert bot["quick_profit_recenter_width_mult_applied"] == 1.0
    assert bot["quick_profit_recenter_width_source"] == "default"
    assert bot["quick_profit_recenter_width_pct_applied"] == pytest.approx(0.045)


# ---------------------------------------------------------------------------
# Trailing TP first-close tests
# ---------------------------------------------------------------------------

def _make_trailing_tp_service(close_success=True):
    """Build service mock suitable for _check_quick_profit trailing TP path."""
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client._get_now_ts.return_value = 1000.0
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._get_cycle_now_ts = GridBotService._get_cycle_now_ts.__get__(
        service, GridBotService
    )
    service._track_position_timing = GridBotService._track_position_timing.__get__(
        service, GridBotService
    )
    service._get_quick_profit_speed_adjustment = (
        GridBotService._get_quick_profit_speed_adjustment.__get__(
            service, GridBotService
        )
    )
    service._get_scaled_quick_profit_targets = (
        GridBotService._get_scaled_quick_profit_targets.__get__(
            service, GridBotService
        )
    )
    service._get_effective_min_profit_pct = (
        GridBotService._get_effective_min_profit_pct.__get__(
            service, GridBotService
        )
    )
    service.scalp_pnl_service = None
    service._build_order_link_id = Mock(return_value="qp-trail-first")
    service._cancel_bot_reduce_only_orders = Mock(return_value=0)
    service._hard_fail_close = Mock()
    service._record_exit_reason = Mock()
    service._is_position_empty_close_result = staticmethod(GridBotService._is_position_empty_close_result)
    service._is_ambiguous_order_result = Mock(return_value=False)
    if close_success:
        service._create_order_checked = Mock(
            return_value={"success": True, "normalized_qty": 2.0}
        )
    else:
        service._create_order_checked = Mock(
            return_value={"success": False, "error": "insufficient_margin"}
        )
    return service


def _make_trailing_tp_bot(**overrides):
    """Bot dict with flow confirmation strong enough for trailing TP."""
    bot = {
        "id": "bot-trail-001",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "flow_score": 20,  # Above TRAILING_TP_FLOW_THRESHOLD (15)
        "flow_confidence": 0.50,  # Above TRAILING_TP_FLOW_CONFIDENCE (0.35)
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 500.0,
                "last_seen_ts": 995.0,
            }
        },
    }
    bot.update(overrides)
    return bot


def test_trailing_tp_first_close_executes_partial_before_trailing():
    """When flow confirms direction at target, first close happens then trailing activates."""
    import config.strategy_config as cfg
    original = cfg.TRAILING_TP_FIRST_CLOSE_ENABLED
    try:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = True
        service = _make_trailing_tp_service(close_success=True)
        bot = _make_trailing_tp_bot()
        position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "4",
            "avgPrice": "10",
            "unrealisedPnl": "0.20",
        }

        result = service._check_quick_profit(
            bot=bot,
            symbol="BTCUSDT",
            last_price=10.0,
            fast_indicators={"atr_pct": 0.04},
            position=position,
        )

        assert result is not None
        assert result["success"] is True
        assert result["action"] == "trailing_tp_first_close"
        assert result["recenter_needed"] is True
        # First close executed
        service._create_order_checked.assert_called_once()
        assert service._create_order_checked.call_args.kwargs["reduce_only"] is True
        # Trailing activated on remainder
        assert bot["_trailing_tp_active"] is True
        assert bot.get("_trailing_tp_peak_pnl") is not None
        # Exit reason recorded
        service._record_exit_reason.assert_called_once()
        assert service._record_exit_reason.call_args.kwargs["reason"] == "trailing_tp_first_close"
    finally:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = original


def test_trailing_tp_first_close_disabled_skips_close():
    """With TRAILING_TP_FIRST_CLOSE_ENABLED=False, original behavior (no close, trailing only)."""
    import config.strategy_config as cfg
    original = cfg.TRAILING_TP_FIRST_CLOSE_ENABLED
    try:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = False
        service = _make_trailing_tp_service(close_success=True)
        bot = _make_trailing_tp_bot()
        position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "4",
            "avgPrice": "10",
            "unrealisedPnl": "0.20",
        }

        result = service._check_quick_profit(
            bot=bot,
            symbol="BTCUSDT",
            last_price=10.0,
            fast_indicators={"atr_pct": 0.04},
            position=position,
        )

        # Original behavior: return None, trailing activated with no close
        assert result is None
        assert bot["_trailing_tp_active"] is True
        service._create_order_checked.assert_not_called()
    finally:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = original


def test_trailing_tp_first_close_uses_configured_pct():
    """TRAILING_TP_FIRST_CLOSE_PCT controls the close fraction, not LONG_QUICK_PROFIT_CLOSE_PCT."""
    import config.strategy_config as cfg
    orig_enabled = cfg.TRAILING_TP_FIRST_CLOSE_ENABLED
    orig_pct = cfg.TRAILING_TP_FIRST_CLOSE_PCT
    try:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = True
        cfg.TRAILING_TP_FIRST_CLOSE_PCT = 0.30  # 30% instead of default 50%
        service = _make_trailing_tp_service(close_success=True)
        bot = _make_trailing_tp_bot(quick_profit_close_pct=0.5)
        position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "10",
            "avgPrice": "10",
            "unrealisedPnl": "0.50",  # Must exceed fee floor for notional=$100
        }

        result = service._check_quick_profit(
            bot=bot,
            symbol="BTCUSDT",
            last_price=10.0,
            fast_indicators={"atr_pct": 0.04},
            position=position,
        )

        assert result["success"] is True
        # Close qty should be 10 * 0.30 = 3.0, not 10 * 0.50
        assert service._create_order_checked.call_args.kwargs["qty"] == 3.0
    finally:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = orig_enabled
        cfg.TRAILING_TP_FIRST_CLOSE_PCT = orig_pct


def test_trailing_tp_first_close_failure_does_not_activate_trailing():
    """If the first close order fails, trailing TP must NOT be activated."""
    import config.strategy_config as cfg
    original = cfg.TRAILING_TP_FIRST_CLOSE_ENABLED
    try:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = True
        service = _make_trailing_tp_service(close_success=False)
        bot = _make_trailing_tp_bot()
        position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "4",
            "avgPrice": "10",
            "unrealisedPnl": "0.20",
        }

        result = service._check_quick_profit(
            bot=bot,
            symbol="BTCUSDT",
            last_price=10.0,
            fast_indicators={"atr_pct": 0.04},
            position=position,
        )

        # Failed close — trailing NOT activated, return None for retry next cycle
        assert result is None
        assert bot.get("_trailing_tp_active") is not True
        assert bot.get("_trailing_tp_peak_pnl") is None
    finally:
        cfg.TRAILING_TP_FIRST_CLOSE_ENABLED = original
