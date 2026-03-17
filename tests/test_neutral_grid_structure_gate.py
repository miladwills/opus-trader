from unittest.mock import Mock

from services.neutral_grid_service import NeutralGridService


def test_neutral_grid_skips_buy_entry_when_structure_gate_blocks():
    bot_storage = Mock()
    bot_storage.get_bot.return_value = {"status": "running"}
    service = NeutralGridService(bot_storage=bot_storage, adaptive_config_service=Mock())
    service._get_instrument_info = Mock(
        return_value={"tick_size": 0.1, "qty_step": 0.001, "min_order_qty": 0.001}
    )

    bot = {
        "id": "bot-1",
        "entry_gate_enabled": True,
        "_entry_structure_skip_buy": True,
        "_entry_structure_buy_reason": "Resistance 0.25% away @ 100.2500 (strength=7)",
    }
    neutral_state = {"per_order_qty": 1.0}
    slot = {"leg": "LONG", "state": "ENTRY", "entry_price": 99.5}
    client = Mock()

    result = service._place_slot_order(
        bot=bot,
        symbol="BTCUSDT",
        client=client,
        neutral_state=neutral_state,
        slot_id="L01",
        slot=slot,
    )

    assert result["skipped"] is True
    assert result["error"] == "structure_entry_skip"
    assert "Resistance 0.25% away" in result["skip_reason"]
    client.create_order.assert_not_called()


def test_neutral_grid_reduce_only_exit_is_not_blocked_by_structure_gate():
    bot_storage = Mock()
    bot_storage.get_bot.return_value = {"status": "running"}
    service = NeutralGridService(bot_storage=bot_storage, adaptive_config_service=Mock())
    service._get_instrument_info = Mock(
        return_value={"tick_size": 0.1, "qty_step": 0.001, "min_order_qty": 0.001}
    )
    service._get_last_price = Mock(return_value=100.0)
    service._can_open_side = Mock(return_value=True)
    service._preflight_qty = Mock(return_value=(1.0, None))
    service._next_order_link_id = Mock(return_value="link-1")
    service._mark_slot_order_submitted = Mock()

    bot = {
        "id": "bot-1",
        "entry_gate_enabled": True,
        "_entry_structure_skip_sell": True,
        "_entry_structure_sell_reason": "Support 0.20% away @ 99.8000 (strength=6)",
    }
    neutral_state = {"per_order_qty": 1.0}
    slot = {"leg": "LONG", "state": "EXIT", "exit_price": 100.5}
    client = Mock()
    client.create_order.return_value = {"success": True, "data": {"orderId": "abc"}}
    client._get_now_ts.return_value = 1234567890.0

    result = service._place_slot_order(
        bot=bot,
        symbol="BTCUSDT",
        client=client,
        neutral_state=neutral_state,
        slot_id="L01",
        slot=slot,
    )

    assert result == {"success": True}
    client.create_order.assert_called_once()


def test_neutral_grid_auto_pilot_loss_budget_blocks_entry_but_not_exit():
    bot_storage = Mock()
    bot_storage.get_bot.return_value = {"status": "running"}
    service = NeutralGridService(bot_storage=bot_storage, adaptive_config_service=Mock())
    service._get_instrument_info = Mock(
        return_value={"tick_size": 0.1, "qty_step": 0.001, "min_order_qty": 0.001}
    )
    service._get_last_price = Mock(return_value=100.0)
    service._can_open_side = Mock(return_value=True)
    service._preflight_qty = Mock(return_value=(1.0, None))
    service._next_order_link_id = Mock(return_value="link-1")
    service._mark_slot_order_submitted = Mock()

    bot = {
        "id": "bot-1",
        "auto_pilot": True,
        "_auto_pilot_loss_budget_block_openings": True,
    }
    neutral_state = {"per_order_qty": 1.0}
    client = Mock()
    client.create_order.return_value = {"success": True, "data": {"orderId": "abc"}}
    client._get_now_ts.return_value = 1234567890.0

    entry_result = service._place_slot_order(
        bot=bot,
        symbol="BTCUSDT",
        client=client,
        neutral_state=neutral_state,
        slot_id="L01",
        slot={"leg": "LONG", "state": "ENTRY", "entry_price": 99.5},
    )
    exit_result = service._place_slot_order(
        bot=bot,
        symbol="BTCUSDT",
        client=client,
        neutral_state=neutral_state,
        slot_id="L01",
        slot={"leg": "LONG", "state": "EXIT", "exit_price": 100.5},
    )

    assert entry_result["skip_reason"] == "auto_pilot_loss_budget_blocked"
    assert exit_result == {"success": True}
    client.create_order.assert_called_once()
