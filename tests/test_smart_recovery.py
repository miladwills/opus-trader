from unittest.mock import Mock

from services.grid_bot_service import GridBotService, RECOVERY_SCALE_OUT_FRACTION


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service._create_order_checked = Mock()
    service._last_grid_center = {}
    return service


def test_handle_smart_recovery_scale_out_does_not_mutate_state_on_order_failure():
    service = _make_service()
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "10",
                    "positionIdx": 1,
                }
            ]
        },
    }
    service._create_order_checked.return_value = {
        "success": False,
        "error": "simulated_failure",
    }
    bot = {
        "id": "bot-1",
        "recovery_enabled": True,
        "_computed_upnl_pct": -12.0,
        "scale_out_count": 0,
    }

    handled = service._handle_smart_recovery(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        indicators={"rsi": 90.0},
        now_iso="2026-03-08T12:00:00+00:00",
    )

    assert handled is False
    assert bot.get("last_scale_out_at") is None
    assert bot["scale_out_count"] == 0
    kwargs = service._create_order_checked.call_args.kwargs
    assert kwargs["symbol"] == "BTCUSDT"
    assert kwargs["side"] == "Sell"
    assert kwargs["qty"] == 10.0 * RECOVERY_SCALE_OUT_FRACTION
    assert kwargs["reduce_only"] is True
    assert kwargs["position_idx"] == 1
    assert kwargs["order_link_id"].startswith("recovery_so_bot-1_")


def test_handle_smart_recovery_scale_out_updates_state_on_confirmed_order():
    service = _make_service()
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Sell",
                    "size": "8",
                    "positionIdx": 2,
                }
            ]
        },
    }
    service._create_order_checked.return_value = {"success": True}
    bot = {
        "id": "bot-1",
        "recovery_enabled": True,
        "_computed_upnl_pct": -20.0,
        "scale_out_count": 1,
    }

    handled = service._handle_smart_recovery(
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        indicators={"rsi": 10.0},
        now_iso="2026-03-08T12:00:00+00:00",
    )

    assert handled is True
    assert bot["last_scale_out_at"] == "2026-03-08T12:00:00+00:00"
    assert bot["scale_out_count"] == 2
    kwargs = service._create_order_checked.call_args.kwargs
    assert kwargs["side"] == "Buy"
    assert kwargs["position_idx"] == 2
