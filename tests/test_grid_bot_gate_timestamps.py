from services.grid_bot_service import GridBotService


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    return service


def test_blocked_until_ts_defaults_none_after_flag_reset():
    service = _make_service()
    bot = {
        "_gate_blocked_until": 123.0,
        "_entry_gate_blocked_until": 456.0,
    }

    GridBotService._clear_opening_block_flags(bot)

    assert service._get_blocked_until_ts(bot, "_gate_blocked_until") == 0.0
    assert service._get_blocked_until_ts(bot, "_entry_gate_blocked_until") == 0.0


def test_blocked_until_ts_clamps_invalid_or_negative_values():
    service = _make_service()
    bot = {
        "_gate_blocked_until": "not-a-timestamp",
        "_entry_gate_blocked_until": -15,
    }

    assert service._get_blocked_until_ts(bot, "_gate_blocked_until") == 0.0
    assert service._get_blocked_until_ts(bot, "_entry_gate_blocked_until") == 0.0
