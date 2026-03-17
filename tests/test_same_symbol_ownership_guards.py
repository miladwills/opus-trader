from unittest.mock import Mock

from services.grid_bot_service import GridBotService


def test_close_position_market_refuses_shared_symbol_active_bots():
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.bot_storage.list_bots.return_value = [
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
        {"id": "bot-2", "symbol": "BTCUSDT", "status": "paused"},
    ]
    service.client = Mock()

    result = GridBotService._close_position_market(
        service,
        "BTCUSDT",
        bot={"id": "bot-1", "symbol": "BTCUSDT"},
    )

    assert result is False
    service.client.get_positions.assert_not_called()


def test_force_cancel_all_orders_refuses_shared_symbol_active_bots():
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.bot_storage.list_bots.return_value = [
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
        {"id": "bot-2", "symbol": "BTCUSDT", "status": "recovering"},
    ]
    service.client = Mock()

    result = GridBotService._force_cancel_all_orders(
        service,
        "BTCUSDT",
        max_retries=2,
        bot={"id": "bot-1", "symbol": "BTCUSDT"},
    )

    assert result["success"] is False
    assert result["error"] == "shared_symbol_active_bots"
    assert result["other_bot_ids"] == ["bot-2"]
    service.client.cancel_all_orders.assert_not_called()
