from unittest.mock import Mock

from services.grid_bot_service import GridBotService


def _make_service(now_ts=1000.0):
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
    service._get_profit_lock_fast_arm_context = (
        GridBotService._get_profit_lock_fast_arm_context.__get__(
            service, GridBotService
        )
    )
    service._get_effective_min_profit_pct = (
        GridBotService._get_effective_min_profit_pct.__get__(
            service, GridBotService
        )
    )
    service._build_close_order_link_id = Mock(return_value="plock-fast")
    service._create_order_checked = Mock(return_value={"success": True})
    service._hard_fail_close = Mock()
    service._log_fast_exec_skip = Mock()
    return service


def test_profit_lock_fast_arm_executes_on_fast_volatile_giveback():
    service = _make_service()
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "4",
                    "avgPrice": "100",
                }
            ]
        },
    }

    bot = {
        "id": "bot-fast-lock",
        "mode": "long",
        "partial_tp_enabled": False,
        "profit_lock_enabled": True,
        "profit_lock_state": {
            "position_side": "Buy",
            "peak_pct": 0.0065,
            "last_close_ts": 0.0,
        },
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 910.0,
                "last_seen_ts": 995.0,
            }
        },
    }

    GridBotService._run_fast_execution_layer(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.4,
        exec_indicators={"atr_pct": 0.008, "price_velocity": 0.015},
    )

    assert bot["profit_lock_fast_arm_active"] is True
    assert bot["profit_lock_fast_arm_threshold"] < 0.008
    assert service._create_order_checked.call_args.kwargs["qty"] == 2.0


def test_profit_lock_fast_arm_disabled_preserves_existing_arm_threshold():
    service = _make_service()
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "4",
                    "avgPrice": "100",
                }
            ]
        },
    }

    bot = {
        "id": "bot-lock-disabled",
        "mode": "long",
        "partial_tp_enabled": False,
        "profit_lock_enabled": True,
        "profit_lock_fast_arm_enabled": False,
        "profit_lock_state": {
            "position_side": "Buy",
            "peak_pct": 0.0065,
            "last_close_ts": 0.0,
        },
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 910.0,
                "last_seen_ts": 995.0,
            }
        },
    }

    GridBotService._run_fast_execution_layer(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.4,
        exec_indicators={"atr_pct": 0.008, "price_velocity": 0.015},
    )

    assert bot["profit_lock_fast_arm_active"] is False
    assert bot["profit_lock_fast_arm_threshold"] == 0.008
    service._create_order_checked.assert_not_called()


def test_profit_lock_fast_arm_respects_mode_gating():
    service = _make_service()
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "4",
                    "avgPrice": "100",
                }
            ]
        },
    }

    bot = {
        "id": "bot-lock-neutral-classic",
        "mode": "neutral_classic_bybit",
        "partial_tp_enabled": False,
        "profit_lock_enabled": True,
        "profit_lock_state": {
            "position_side": "Buy",
            "peak_pct": 0.0065,
            "last_close_ts": 0.0,
        },
        "_position_timing_state": {
            "BTCUSDT:Buy:0": {
                "opened_at_ts": 910.0,
                "last_seen_ts": 995.0,
            }
        },
    }

    GridBotService._run_fast_execution_layer(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.4,
        exec_indicators={"atr_pct": 0.008, "price_velocity": 0.015},
    )

    service._create_order_checked.assert_not_called()
