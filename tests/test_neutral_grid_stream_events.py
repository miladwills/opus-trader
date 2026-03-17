from unittest.mock import Mock

from services.neutral_grid_service import NeutralGridService


class _FakeBotStorage:
    def save_runtime_bot(self, bot):
        return bot

    def save_bot(self, bot):
        return bot


def test_process_execution_events_uses_provided_stream_events_without_rest_poll():
    service = NeutralGridService(bot_storage=_FakeBotStorage(), adaptive_config_service=Mock())
    service._update_status_fields = Mock()
    service.on_order_filled = Mock(side_effect=lambda bot, symbol, event, client, persist=False: bot)
    client = Mock()

    bot = {
        "id": "bot-1",
        "neutral_grid": {
            "slots": {
                "s1": {
                    "state": "ENTRY",
                }
            }
        },
    }

    result = service.process_execution_events(
        bot,
        "BTCUSDT",
        client,
        execution_events=[{"execId": "exec-1"}],
    )

    assert result is bot
    client.get_executions.assert_not_called()
    service.on_order_filled.assert_called_once_with(
        bot,
        "BTCUSDT",
        {"execId": "exec-1"},
        client,
        persist=False,
    )


def test_reconcile_preserves_recent_slot_when_open_order_snapshot_is_temporarily_empty():
    service = NeutralGridService(bot_storage=_FakeBotStorage(), adaptive_config_service=Mock())
    service.ensure_hedge_mode = Mock(side_effect=lambda bot, symbol, client: bot)
    service._get_instrument_info = Mock(
        return_value={
            "min_order_qty": 0.1,
            "qty_step": 0.1,
            "tick_size": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_usdt_available_balance = Mock(return_value=100.0)
    service._compute_per_order_qty = Mock(return_value=1.0)
    service._get_open_orders = Mock(return_value=[])
    service._get_position_sizes = Mock(return_value={1: 0.0, 2: 0.0})
    service._place_slot_order = Mock(return_value={"success": True})
    client = Mock()
    client._get_now_ts.return_value = 1000.0

    bot = {
        "id": "29c36d6e-d066-4450-a320-63dcd88fec51",
        "status": "running",
        "symbol": "BTCUSDT",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_lower_price": 10.0,
        "grid_upper_price": 11.0,
        "grid_count": 1,
        "neutral_grid": {
            "levels": [10.0, 11.0],
            "lower_price": 10.0,
            "upper_price": 11.0,
            "total_levels": 1,
            "mid_index": 1,
            "slots": {
                "L00": {
                    "leg": "LONG",
                    "level": 0,
                    "state": "ENTRY",
                    "entry_price": 10.0,
                    "exit_price": 11.0,
                    "order_id": "order-1",
                    "order_link_id": "bv2:29c36d6ed0664450:000001:L00:E",
                    "last_order_submit_ts": 995.0,
                }
            },
            "seq": 1,
            "processed_exec_ids": [],
            "slot_width": 2,
        },
    }

    result = service.reconcile_on_start(bot, "BTCUSDT", client)

    slot = result["neutral_grid"]["slots"]["L00"]
    assert slot["order_id"] == "order-1"
    assert slot["order_link_id"] == "bv2:29c36d6ed0664450:000001:L00:E"
    service._place_slot_order.assert_not_called()


def test_reconcile_cancels_duplicate_orders_for_same_slot():
    service = NeutralGridService(bot_storage=_FakeBotStorage(), adaptive_config_service=Mock())
    service.ensure_hedge_mode = Mock(side_effect=lambda bot, symbol, client: bot)
    service._get_instrument_info = Mock(
        return_value={
            "min_order_qty": 0.1,
            "qty_step": 0.1,
            "tick_size": 0.1,
            "min_notional_value": 5.0,
        }
    )
    service._get_usdt_available_balance = Mock(return_value=100.0)
    service._compute_per_order_qty = Mock(return_value=1.0)
    service._get_position_sizes = Mock(return_value={1: 0.0, 2: 0.0})
    service._place_slot_order = Mock(return_value={"success": True})
    service._get_open_orders = Mock(
        return_value=[
            {
                "orderId": "order-1",
                "orderLinkId": "bv2:29c36d6ed0664450:000001:L00:E",
                "price": "10",
            },
            {
                "orderId": "order-2",
                "orderLinkId": "bv2:29c36d6ed0664450:000002:L00:E",
                "price": "10",
            },
        ]
    )
    client = Mock()
    client._get_now_ts.return_value = 1000.0

    bot = {
        "id": "29c36d6e-d066-4450-a320-63dcd88fec51",
        "status": "running",
        "symbol": "BTCUSDT",
        "investment": 100.0,
        "leverage": 1.0,
        "grid_lower_price": 10.0,
        "grid_upper_price": 11.0,
        "grid_count": 1,
        "neutral_grid": {
            "levels": [10.0, 11.0],
            "lower_price": 10.0,
            "upper_price": 11.0,
            "total_levels": 1,
            "mid_index": 1,
            "slots": {
                "L00": {
                    "leg": "LONG",
                    "level": 0,
                    "state": "ENTRY",
                    "entry_price": 10.0,
                    "exit_price": 11.0,
                    "order_id": None,
                    "order_link_id": None,
                }
            },
            "seq": 0,
            "processed_exec_ids": [],
            "slot_width": 2,
        },
    }

    result = service.reconcile_on_start(bot, "BTCUSDT", client)

    slot = result["neutral_grid"]["slots"]["L00"]
    assert slot["order_id"] == "order-1"
    assert slot["order_link_id"] == "bv2:29c36d6ed0664450:000001:L00:E"
    client.cancel_order.assert_called_once_with(
        symbol="BTCUSDT",
        order_id="order-2",
        order_link_id="bv2:29c36d6ed0664450:000002:L00:E",
    )
