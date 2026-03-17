from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from services.grid_bot_service import GridBotService


class _Settings:
    def __init__(self, enabled):
        self.enabled = enabled

    def get_auto_stop_on_direction_change(self):
        return self.enabled


def _make_service(*, enabled=True, trend_direction="up", should_act=True, score=82):
    service = GridBotService.__new__(GridBotService)
    service.runtime_settings_service = _Settings(enabled)
    service.trend_protection_service = Mock()
    service.trend_protection_service.detect_trend.return_value = {
        "trend_direction": trend_direction,
        "should_act": should_act,
        "confidence_score": score,
        "reasons": [f"trend={trend_direction}", f"score={score}"],
    }
    service.bot_storage = Mock()
    service.bot_storage.save_bot.side_effect = lambda bot: dict(bot)
    service._get_shared_symbol_conflict = Mock(return_value=None)
    service._cancel_opening_orders_only = Mock(return_value=2)
    service._close_position_or_hard_fail = Mock(return_value={"success": True})
    return service


def test_direction_change_auto_stop_sets_baseline_before_acting():
    service = _make_service(enabled=True, trend_direction="up")
    bot = {
        "id": "bot-1",
        "status": "running",
        "position_size": 0,
        "position_side": "",
        "unrealized_pnl": 0,
    }

    result = GridBotService._maybe_apply_direction_change_auto_stop(
        service,
        bot,
        "BTCUSDT",
        {"adx": 30},
        datetime.now(timezone.utc).isoformat(),
    )

    assert result is None
    assert bot["direction_change_guard_baseline_state"] == "long"
    service.bot_storage.save_bot.assert_not_called()


def test_direction_change_auto_stop_stops_after_confirmed_profitable_flip():
    service = _make_service(enabled=True, trend_direction="down")
    bot = {
        "id": "bot-1",
        "status": "running",
        "position_size": 1.25,
        "position_side": "Buy",
        "unrealized_pnl": 4.2,
        "direction_change_guard_baseline_state": "long",
        "direction_change_guard_pending_state": "short",
        "direction_change_guard_pending_since": (
            datetime.now(timezone.utc) - timedelta(seconds=25)
        ).isoformat(),
    }

    saved = GridBotService._maybe_apply_direction_change_auto_stop(
        service,
        bot,
        "BTCUSDT",
        {"adx": 33},
        datetime.now(timezone.utc).isoformat(),
    )

    assert saved["status"] == "stopped"
    assert saved["direction_change_guard_last_action"] == "stopped_after_close"
    assert saved["direction_change_guard_prev_state"] == "long"
    assert saved["direction_change_guard_state"] == "short"
    service._close_position_or_hard_fail.assert_called_once()
    service.bot_storage.save_bot.assert_called_once()


def test_direction_change_auto_stop_uses_reduce_only_for_losing_position():
    service = _make_service(enabled=True, trend_direction="down")
    bot = {
        "id": "bot-1",
        "status": "running",
        "position_size": 1.25,
        "position_side": "Buy",
        "unrealized_pnl": -2.8,
        "direction_change_guard_baseline_state": "long",
        "direction_change_guard_pending_state": "short",
        "direction_change_guard_pending_since": (
            datetime.now(timezone.utc) - timedelta(seconds=25)
        ).isoformat(),
    }

    saved = GridBotService._maybe_apply_direction_change_auto_stop(
        service,
        bot,
        "BTCUSDT",
        {"adx": 33},
        datetime.now(timezone.utc).isoformat(),
    )

    assert saved["status"] == "running"
    assert saved["reduce_only_mode"] is True
    assert saved["auto_stop_paused"] is True
    assert saved["direction_change_guard_last_action"] == "reduce_only"
    service._close_position_or_hard_fail.assert_not_called()
    service.bot_storage.save_bot.assert_called_once()
