from unittest.mock import Mock

from services.grid_bot_service import GridBotService


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    return service


def test_cancel_duplicate_bot_orders_matches_legacy_bot_prefixes():
    service = _make_service()
    bot = {
        "id": "12345678-90ab-cdef-1234-567890abcdef",
    }
    order_list = [
        {
            "orderId": "old-1",
            "orderLinkId": "bot:12345678:1700000000:01",
            "side": "Buy",
            "price": "100.0",
            "reduceOnly": False,
            "createdTime": "1",
        },
        {
            "orderId": "old-2",
            "orderLinkId": "bot:12345678:1700000000:02",
            "side": "Buy",
            "price": "100.0",
            "reduceOnly": False,
            "createdTime": "2",
        },
    ]
    service.client.cancel_order.return_value = {"success": True}
    service.client.get_open_orders.return_value = {"success": True, "data": {"list": []}}

    result = service._cancel_duplicate_bot_orders(
        bot=bot,
        symbol="BTCUSDT",
        order_list=order_list,
    )

    assert result["cancelled_count"] == 1
    service.client.cancel_order.assert_called_once_with(
        symbol="BTCUSDT",
        order_id="old-2",
        order_link_id="bot:12345678:1700000000:02",
    )
    service.client.get_open_orders.assert_called_once_with(
        symbol="BTCUSDT",
        limit=200,
        skip_cache=True,
    )


def test_place_initial_entry_skips_when_fresh_position_exists():
    service = _make_service()
    service._calculate_auto_margin_reserve = Mock(return_value=(0.0, 100.0))
    service._get_usdt_available_balance = Mock(return_value=100.0)
    service._normalize_order_qty = Mock(return_value=1.0)
    service._create_order_checked = Mock(return_value={"success": True})
    service.client.get_instruments_info.return_value = {
        "data": {
            "list": [
                {
                    "lotSizeFilter": {
                        "qtyStep": "0.1",
                        "minOrderQty": "0.1",
                        "minNotionalValue": "5",
                    }
                }
            ]
        }
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "size": "1.0",
                    "side": "Buy",
                }
            ]
        },
    }

    result = service._place_initial_entry(
        bot={"id": "bot-1", "investment": 100.0, "leverage": 1.0},
        symbol="BTCUSDT",
        last_price=100.0,
        mode="long",
        now_iso="2026-03-07T00:00:00+00:00",
    )

    assert result is False
    service.client.get_positions.assert_called_once_with(skip_cache=True)
    service._create_order_checked.assert_not_called()
