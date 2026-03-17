import logging

from services.grid_bot_service import GridBotService


def test_persist_auto_margin_state_logs_save_failure(caplog):
    service = GridBotService.__new__(GridBotService)

    def _raise_save(_bot):
        raise RuntimeError("disk full")

    service._save_runtime_bot = _raise_save
    bot = {"id": "bot-1"}
    state = {"last_add_ts": 123.0}

    with caplog.at_level(logging.WARNING):
        persisted = GridBotService._persist_auto_margin_state(
            service,
            bot,
            state,
            "BTCUSDT",
        )

    assert persisted is False
    assert bot["auto_margin_state"] == state
    assert "Failed to persist auto-margin state for bot bot-1: disk full" in caplog.text
