from unittest.mock import Mock

from services.grid_bot_service import GridBotService


class _StubStorage:
    def __init__(self):
        self.saved = []

    def get_bot(self, bot_id):
        return None

    def save_bot(self, bot):
        saved = dict(bot)
        self.saved.append(saved)
        return saved


def test_run_bot_cycle_dispatches_trend_exit_maintenance_for_paused_bots():
    service = GridBotService.__new__(GridBotService)
    service._try_acquire_bot_run_lock = Mock(return_value=(True, None))
    service.bot_storage = Mock()
    service.bot_storage.get_bot.return_value = {
        "id": "bot-1",
        "status": "paused",
        "_neutral_trend_exit": {"waiting_for_green": True},
    }
    service._check_trend_exit_pause = Mock(return_value={"id": "bot-1", "status": "paused"})

    result = GridBotService.run_bot_cycle(
        service,
        {"id": "bot-1", "status": "paused"},
    )

    assert result["status"] == "paused"
    service._check_trend_exit_pause.assert_called_once()


def test_trend_exit_guard_resume_condition_clears_pause_state():
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = _StubStorage()
    service._refresh_multi_tf_regime_snapshot = Mock(
        side_effect=lambda bot, symbol, force=False: bot.update(
            {"regime_effective": "SIDEWAYS", "regime_confidence": "low"}
        )
    )

    bot = {
        "id": "bot-2",
        "symbol": "BTCUSDT",
        "status": "paused",
        "pause_reason": "Trend exit guard",
        "pause_reason_type": "trend_exit_guard",
        "paused_at": 123.0,
        "_neutral_trend_exit": {"waiting_for_green": False},
    }

    updated = GridBotService._check_resume_conditions(service, bot)

    assert updated["status"] == "running"
    assert updated["last_error"] is None
    assert "pause_reason" not in updated
    assert "pause_reason_type" not in updated
    assert "paused_at" not in updated
    assert "_neutral_trend_exit" not in updated
