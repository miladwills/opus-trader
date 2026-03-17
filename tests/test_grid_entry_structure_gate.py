from unittest.mock import Mock

from services.grid_bot_service import GridBotService


def test_structure_entry_blocks_are_recorded_on_bot():
    service = GridBotService.__new__(GridBotService)
    fake_gate = Mock()
    fake_gate.check_side_open.side_effect = [
        {
            "suitable": False,
            "reason": "Resistance 0.30% away @ 100.3000 (strength=7)",
        },
        {
            "suitable": True,
            "reason": "Side entry conditions favorable",
        },
    ]
    service._build_entry_gate_service = Mock(return_value=fake_gate)

    bot = {"entry_gate_enabled": True}
    result = GridBotService._evaluate_structure_entry_blocks(
        service,
        bot=bot,
        symbol="BTCUSDT",
        last_price=100.0,
        fast_indicators={"close": 100.0},
        allow_buy=True,
        allow_sell=True,
    )

    assert result["skip_buy"] is True
    assert result["skip_sell"] is False
    assert bot["_entry_structure_skip_buy"] is True
    assert bot["_entry_structure_skip_sell"] is False
    assert "Resistance 0.30% away" in bot["_entry_structure_buy_reason"]
    assert "_entry_structure_sell_reason" not in bot


def test_structure_entry_blocks_clear_when_entry_gate_disabled():
    service = GridBotService.__new__(GridBotService)
    service._build_entry_gate_service = Mock()

    bot = {
        "entry_gate_enabled": False,
        "_entry_structure_skip_buy": True,
        "_entry_structure_skip_sell": True,
        "_entry_structure_buy_reason": "stale buy",
        "_entry_structure_sell_reason": "stale sell",
    }
    result = GridBotService._evaluate_structure_entry_blocks(
        service,
        bot=bot,
        symbol="ETHUSDT",
        last_price=100.0,
        fast_indicators={"close": 100.0},
        allow_buy=True,
        allow_sell=True,
    )

    assert result == {
        "skip_buy": False,
        "skip_sell": False,
        "buy_reason": "",
        "sell_reason": "",
    }
    assert bot["_entry_structure_skip_buy"] is False
    assert bot["_entry_structure_skip_sell"] is False
    assert "_entry_structure_buy_reason" not in bot
    assert "_entry_structure_sell_reason" not in bot
