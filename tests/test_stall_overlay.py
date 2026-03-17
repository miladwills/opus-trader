from unittest.mock import Mock

import pytest

from services.grid_bot_service import GridBotService


def _make_service(now_ts: float = 1_700_000_000.0) -> GridBotService:
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client._get_now_ts.return_value = now_ts
    service._get_cycle_now_ts = Mock(return_value=now_ts)
    service.scalp_pnl_service = None
    service.bot_storage = Mock()
    service._build_order_link_id = Mock(return_value="qp-close")
    service._build_close_order_link_id = Mock(return_value="stall-close")
    service._cancel_bot_reduce_only_orders = Mock(return_value=0)
    service._hard_fail_close = Mock()
    service._create_order_checked = Mock(
        return_value={"success": True, "normalized_qty": 2.0}
    )
    service._close_bot_symbol = Mock(return_value=True)
    return service


def _position(
    *,
    side: str = "Buy",
    size: float = 4.0,
    upnl: float = -0.4,
    avg_price: float = 10.0,
    position_idx: int = 1,
) -> dict:
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "size": str(size),
        "unrealisedPnl": str(upnl),
        "avgPrice": str(avg_price),
        "positionIdx": position_idx,
    }


def test_stall_overlay_does_not_trigger_on_profitable_trend():
    service = _make_service()
    bot = {
        "id": "bot-stall-1",
        "mode": "long",
        "entry_filter_regime": "too_strong",
        "stall_overlay_position_cap_hit": True,
        "orders_placed": 0,
        "orders_failed": 0,
        "_position_timing_state": {
            "BTCUSDT:Buy:1": {
                "opened_at_ts": 1_699_998_400.0,
                "last_seen_ts": 1_699_999_900.0,
            }
        },
    }

    GridBotService._handle_stall_overlay(
        service,
        bot,
        "BTCUSDT",
        _position(upnl=0.8),
        mode="long",
        last_price=10.1,
        profit_pct=0.01,
        partial_tp_ready=False,
        profit_lock_ready=False,
        heartbeat_action="no_action",
    )

    assert bot["stall_overlay_stage"] == 0
    assert bot["_stall_overlay_block_opening_orders"] is False
    service._create_order_checked.assert_not_called()


def test_stall_overlay_warning_tightens_management_and_quick_profit_thresholds():
    service = _make_service()
    bot = {
        "id": "bot-stall-2",
        "mode": "long",
        "range_mode": "dynamic",
        "quick_profit_enabled": True,
        "quick_profit_target": 0.20,
        "quick_profit_close_pct": 0.5,
        "entry_filter_regime": "too_strong",
        "stall_overlay_position_cap_hit": True,
        "orders_placed": 0,
        "orders_failed": 0,
        "_cycle_count": 10,
        "_position_timing_state": {
            "BTCUSDT:Buy:1": {
                "opened_at_ts": 1_699_998_400.0,
                "last_seen_ts": 1_699_999_900.0,
            }
        },
        "_stall_overlay_state": {
            "position_key": "BTCUSDT:Buy:1",
            "active_since_ts": 1_699_999_500.0,
            "no_action_cycles": 2,
            "worsening_cycles": 0,
            "last_profit_pct": -0.002,
            "last_unrealized_pnl": -0.2,
            "stage": 0,
        },
    }

    GridBotService._handle_stall_overlay(
        service,
        bot,
        "BTCUSDT",
        _position(upnl=-0.25),
        mode="long",
        last_price=10.0,
        profit_pct=-0.003,
        partial_tp_ready=False,
        profit_lock_ready=False,
        heartbeat_action="no_action",
    )

    assert bot["stall_overlay_stage"] == 1
    assert bot["_stall_overlay_block_opening_orders"] is True
    assert bot["_stall_overlay_quick_profit_mult"] == pytest.approx(0.85)
    assert bot["_stall_overlay_profit_lock_mult"] == pytest.approx(0.85)
    service._create_order_checked.reset_mock()

    quick_profit_result = GridBotService._check_quick_profit(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=10.0,
        fast_indicators={},
        position=_position(upnl=0.18),
    )

    assert quick_profit_result["success"] is True
    assert quick_profit_result["target_threshold"] == pytest.approx(0.17)


def test_worsening_stalled_state_executes_defensive_trim():
    service = _make_service(now_ts=1_700_000_000.0)
    bot = {
        "id": "bot-stall-3",
        "mode": "long",
        "entry_filter_regime": "too_strong",
        "stall_overlay_position_cap_hit": True,
        "orders_placed": 0,
        "orders_failed": 0,
        "_cycle_count": 10,
        "_position_timing_state": {
            "BTCUSDT:Buy:1": {
                "opened_at_ts": 1_699_998_000.0,
                "last_seen_ts": 1_699_999_900.0,
            }
        },
        "_stall_overlay_state": {
            "position_key": "BTCUSDT:Buy:1",
            "active_since_ts": 1_699_999_000.0,
            "no_action_cycles": 3,
            "worsening_cycles": 2,
            "last_profit_pct": -0.01,
            "last_unrealized_pnl": -0.6,
            "last_trim_stage": 1,
            "last_trim_ts": 0.0,
            "stage": 2,
        },
    }

    GridBotService._handle_stall_overlay(
        service,
        bot,
        "BTCUSDT",
        _position(upnl=-1.4),
        mode="long",
        last_price=10.0,
        profit_pct=-0.02,
        partial_tp_ready=False,
        profit_lock_ready=False,
        heartbeat_action="no_action",
    )

    assert bot["stall_overlay_stage"] == 3
    assert service._create_order_checked.call_args.kwargs["reduce_only"] is True
    assert service._create_order_checked.call_args.kwargs["qty"] == pytest.approx(0.96)
    assert bot["stall_overlay_last_trim_close_pct"] == pytest.approx(0.24)


def test_stall_overlay_blocks_only_openings_and_keeps_reduce_only_path():
    service = _make_service()
    bot = {
        "id": "bot-stall-4",
        "mode": "long",
        "entry_filter_regime": "too_strong",
        "stall_overlay_position_cap_hit": True,
        "orders_placed": 0,
        "orders_failed": 0,
        "_cycle_count": 10,
        "_position_timing_state": {
            "BTCUSDT:Buy:1": {
                "opened_at_ts": 1_699_998_400.0,
                "last_seen_ts": 1_699_999_900.0,
            }
        },
        "_stall_overlay_state": {
            "position_key": "BTCUSDT:Buy:1",
            "active_since_ts": 1_699_999_500.0,
            "no_action_cycles": 2,
            "worsening_cycles": 0,
            "last_profit_pct": -0.002,
            "last_unrealized_pnl": -0.2,
            "stage": 0,
        },
    }

    GridBotService._handle_stall_overlay(
        service,
        bot,
        "BTCUSDT",
        _position(upnl=-0.25),
        mode="long",
        last_price=10.0,
        profit_pct=-0.003,
        partial_tp_ready=False,
        profit_lock_ready=False,
        heartbeat_action="no_action",
    )

    assert bot["_stall_overlay_block_opening_orders"] is True
    assert bot.get("_block_opening_orders") is not True
    assert GridBotService._ai_block_opening_orders(service, bot) is True
    service._create_order_checked.assert_not_called()


def test_stall_overlay_does_not_change_hard_auto_stop_behavior():
    service = _make_service()
    bot = {
        "id": "bot-stall-5",
        "symbol": "BTCUSDT",
        "status": "running",
        "auto_stop": 5.0,
        "_stall_overlay_block_opening_orders": True,
        "stall_overlay_stage": 3,
    }

    result = GridBotService._maybe_trigger_auto_stop_loss(
        service,
        bot=bot,
        symbol="BTCUSDT",
        now_iso="2026-03-09T10:00:00+00:00",
        unrealized_pnl=-6.0,
        position_size=1.0,
    )

    assert result is bot
    assert bot["status"] == "stopped"
    assert "Auto-stop" in bot["last_error"]
    service._close_bot_symbol.assert_called_once()
