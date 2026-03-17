from unittest.mock import Mock

import services.grid_bot_service as grid_bot_module
from services.grid_bot_service import GridBotService


class _StubStorage:
    def __init__(self):
        self.saved = []

    def save_bot(self, bot):
        self.saved.append(dict(bot))
        return dict(bot)


def _make_service() -> GridBotService:
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = _StubStorage()
    service.client = Mock()
    service._clear_pause_runtime_state = GridBotService._clear_pause_runtime_state
    service._clear_stop_cleanup_pending_fields = (
        GridBotService._clear_stop_cleanup_pending_fields
    )
    service._mark_stop_cleanup_pending_state = (
        GridBotService._mark_stop_cleanup_pending_state.__get__(
            service, GridBotService
        )
    )
    service._finalize_stop_cleanup_state = (
        GridBotService._finalize_stop_cleanup_state.__get__(
            service, GridBotService
        )
    )
    service._apply_nlp_max_loss_stop_state = (
        GridBotService._apply_nlp_max_loss_stop_state.__get__(
            service, GridBotService
        )
    )
    service._maybe_trigger_symbol_daily_kill_switch = (
        GridBotService._maybe_trigger_symbol_daily_kill_switch.__get__(
            service, GridBotService
        )
    )
    service._transition_to_stop_cleanup_state = (
        GridBotService._transition_to_stop_cleanup_state.__get__(
            service, GridBotService
        )
    )
    service._monitor_stop_cleanup_pending = GridBotService._monitor_stop_cleanup_pending.__get__(
        service, GridBotService
    )
    return service


def test_transition_to_stop_cleanup_state_enters_pending_until_cleanup_confirmed():
    service = _make_service()
    service._close_bot_symbol = Mock(return_value=False)
    service._confirm_symbol_cleanup_state = Mock(
        return_value={"cleanup_confirmed": False, "error": None}
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }

    updated = service._transition_to_stop_cleanup_state(
        bot,
        "BTCUSDT",
        target_status="risk_stopped",
        cleanup_reason="max_bot_loss_limit",
        final_last_error="Bot hit max loss limit",
        now_iso="2026-03-13T12:00:00+00:00",
    )

    service._close_bot_symbol.assert_called_once()
    assert updated["status"] == "stop_cleanup_pending"
    assert updated["stop_cleanup_target_status"] == "risk_stopped"
    assert updated["reduce_only_mode"] is True
    assert "cleanup pending" in updated["last_error"]


def test_transition_to_stop_cleanup_state_finalizes_when_cleanup_is_confirmed():
    service = _make_service()
    service._close_bot_symbol = Mock(return_value=True)
    service._confirm_symbol_cleanup_state = Mock(
        return_value={"cleanup_confirmed": True, "error": None}
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }

    updated = service._transition_to_stop_cleanup_state(
        bot,
        "BTCUSDT",
        target_status="risk_stopped",
        cleanup_reason="max_bot_loss_limit",
        final_last_error="Bot hit max loss limit",
        now_iso="2026-03-13T12:00:00+00:00",
    )

    assert updated["status"] == "risk_stopped"
    assert updated["last_error"] == "Bot hit max loss limit"
    assert "stop_cleanup_pending" not in updated


def test_monitor_stop_cleanup_pending_finalizes_when_symbol_is_flat():
    service = _make_service()
    service._confirm_symbol_cleanup_state = Mock(
        return_value={"cleanup_confirmed": True, "error": None}
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "stop_cleanup_pending",
        "stop_cleanup_pending": True,
        "stop_cleanup_target_status": "stopped",
        "stop_cleanup_final_last_error": None,
    }

    updated = service._monitor_stop_cleanup_pending(bot)

    assert updated["status"] == "stopped"
    assert "stop_cleanup_pending" not in updated


def test_apply_nlp_max_loss_stop_state_finalizes_when_cleanup_was_confirmed():
    service = _make_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "stopped",
        "last_error": "MAX_LOSS_STOP: uPnL $-8.00 < $-5.00",
    }

    updated = service._apply_nlp_max_loss_stop_state(
        bot,
        action="max_loss_stop",
        last_price=42000.0,
        now_iso="2026-03-13T12:00:00+00:00",
    )

    assert updated["status"] == "risk_stopped"
    assert updated["last_error"] == "MAX_LOSS_STOP: uPnL $-8.00 < $-5.00"
    assert "stop_cleanup_pending" not in updated


def test_apply_nlp_max_loss_stop_state_marks_pending_when_cleanup_not_confirmed():
    service = _make_service()
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
        "last_error": "MAX_LOSS_STOP pending: flatten/cancel not confirmed (orders=1, positions=1)",
    }

    updated = service._apply_nlp_max_loss_stop_state(
        bot,
        action="max_loss_stop_failed",
        last_price=42000.0,
        now_iso="2026-03-13T12:00:00+00:00",
    )

    assert updated["status"] == "stop_cleanup_pending"
    assert updated["stop_cleanup_target_status"] == "risk_stopped"
    assert updated["last_error"].startswith("MAX_LOSS_STOP pending:")
    assert updated["stop_cleanup_final_last_error"].startswith(
        "NLP Max Loss Stop triggered at"
    )


def test_confirm_symbol_cleanup_state_skips_non_tradeable_placeholder_symbol():
    service = _make_service()

    result = service._confirm_symbol_cleanup_state("Auto-Pilot")

    assert result["success"] is True
    assert result["cleanup_confirmed"] is True
    assert result["message"] == "skipped_non_tradeable_symbol"
    service.client.get_positions.assert_not_called()


def test_symbol_daily_kill_switch_enters_cleanup_pending_until_cleanup_is_confirmed(
    monkeypatch,
):
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_ENABLED", True)
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_CLOSE_POSITION", True)
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_CANCEL_ORDERS", True)
    monkeypatch.setattr(
        grid_bot_module,
        "SYMBOL_DAILY_KILL_SWITCH_LOSS_PCT_OF_INVESTMENT",
        0.05,
    )
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_MIN_USDT", 1.0)
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_MAX_USDT", 1000.0)

    service = _make_service()
    service.risk_manager = Mock()
    service.risk_manager.check_symbol_daily_loss.return_value = {
        "triggered": True,
        "realized_pnl": -12.5,
    }
    service._get_effective_investment = Mock(return_value=100.0)
    service._last_close_position_result = {
        "success": None,
        "status": "in_flight",
        "error": "close_in_flight",
    }
    service._close_position_market = Mock(return_value=False)
    service._force_cancel_all_orders = Mock(
        return_value={
            "success": None,
            "status": "unknown_outcome",
            "error": "cancel_ambiguous",
        }
    )
    service._confirm_symbol_cleanup_state = Mock(
        return_value={"cleanup_confirmed": False, "error": None}
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }

    updated = service._maybe_trigger_symbol_daily_kill_switch(
        bot=bot,
        symbol="BTCUSDT",
        now_iso="2026-03-14T00:30:00+00:00",
        investment=100.0,
    )

    assert updated["status"] == "stop_cleanup_pending"
    assert updated["stop_cleanup_target_status"] == "stopped"
    assert updated["stop_cleanup_reason"] == "symbol_daily_kill_switch"
    assert updated["reduce_only_mode"] is True
    assert updated["_block_opening_orders"] is True
    assert updated["symbol_daily_loss_limit_usdt"] == 5.0
    assert updated["symbol_daily_loss_triggered_at"] == "2026-03-14T00:30:00+00:00"
    assert updated["last_error"].startswith(
        "Symbol daily loss stop triggered: $-12.50 <= -$5.00"
    )
    assert "cleanup pending" in updated["last_error"]
    assert "close_in_flight" in updated["last_error"]
    assert "cancel_ambiguous" in updated["last_error"]


def test_symbol_daily_kill_switch_finalizes_when_cleanup_is_confirmed(monkeypatch):
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_ENABLED", True)
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_CLOSE_POSITION", True)
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_CANCEL_ORDERS", True)
    monkeypatch.setattr(
        grid_bot_module,
        "SYMBOL_DAILY_KILL_SWITCH_LOSS_PCT_OF_INVESTMENT",
        0.05,
    )
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_MIN_USDT", 1.0)
    monkeypatch.setattr(grid_bot_module, "SYMBOL_DAILY_KILL_SWITCH_MAX_USDT", 1000.0)

    service = _make_service()
    service.risk_manager = Mock()
    service.risk_manager.check_symbol_daily_loss.return_value = {
        "triggered": True,
        "realized_pnl": -12.5,
    }
    service._get_effective_investment = Mock(return_value=100.0)
    service._close_position_market = Mock(return_value=True)
    service._force_cancel_all_orders = Mock(
        return_value={"success": True, "cancelled": 2}
    )
    service._confirm_symbol_cleanup_state = Mock(
        return_value={"cleanup_confirmed": True, "error": None}
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }

    updated = service._maybe_trigger_symbol_daily_kill_switch(
        bot=bot,
        symbol="BTCUSDT",
        now_iso="2026-03-14T00:30:00+00:00",
        investment=100.0,
    )

    assert updated["status"] == "stopped"
    assert updated["last_error"] == "Symbol daily loss stop triggered: $-12.50 <= -$5.00"
    assert updated["symbol_daily_loss_limit_usdt"] == 5.0
    assert updated["symbol_daily_loss_triggered_at"] == "2026-03-14T00:30:00+00:00"
    assert updated.get("stop_cleanup_pending") is None
    assert updated["reduce_only_mode"] is False


def test_monitor_stop_cleanup_pending_finalizes_symbol_daily_kill_switch_bot():
    service = _make_service()
    service._confirm_symbol_cleanup_state = Mock(
        return_value={"cleanup_confirmed": True, "error": None}
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "stop_cleanup_pending",
        "stop_cleanup_pending": True,
        "stop_cleanup_target_status": "stopped",
        "stop_cleanup_reason": "symbol_daily_kill_switch",
        "stop_cleanup_final_last_error": "Symbol daily loss stop triggered: $-12.50 <= -$5.00",
        "symbol_daily_loss_limit_usdt": 5.0,
        "symbol_daily_loss_triggered_at": "2026-03-14T00:30:00+00:00",
        "reduce_only_mode": True,
    }

    updated = service._monitor_stop_cleanup_pending(bot)

    assert updated["status"] == "stopped"
    assert updated["last_error"] == "Symbol daily loss stop triggered: $-12.50 <= -$5.00"
    assert updated["symbol_daily_loss_limit_usdt"] == 5.0
    assert updated["symbol_daily_loss_triggered_at"] == "2026-03-14T00:30:00+00:00"
    assert updated.get("stop_cleanup_pending") is None
    assert updated["reduce_only_mode"] is False


def test_run_bot_cycle_short_circuits_symbol_daily_cleanup_pending_before_trading():
    service = GridBotService.__new__(GridBotService)
    lock = Mock()
    pending_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "stop_cleanup_pending",
        "stop_cleanup_pending": True,
        "stop_cleanup_reason": "symbol_daily_kill_switch",
    }
    monitored_bot = dict(pending_bot, last_error="still pending")

    service._try_acquire_bot_run_lock = Mock(return_value=(True, lock))
    service._release_bot_run_lock = GridBotService._release_bot_run_lock
    service.bot_storage = Mock(get_bot=Mock(return_value=dict(pending_bot)))
    service._merge_cycle_runtime_context = Mock(return_value=dict(pending_bot))
    service._monitor_stop_cleanup_pending = Mock(return_value=monitored_bot)

    updated = GridBotService.run_bot_cycle(service, dict(pending_bot))

    service._monitor_stop_cleanup_pending.assert_called_once()
    assert updated["status"] == "stop_cleanup_pending"
    lock.release.assert_called_once()


def test_run_bot_cycle_does_not_reenter_cleanup_for_clean_running_restart_state():
    service = GridBotService.__new__(GridBotService)
    lock = Mock()
    running_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
        "trading_env": "mainnet",
        "paper_trading": False,
        "reduce_only_mode": False,
        "auto_stop_paused": False,
    }
    continued_bot = dict(running_bot, cycle_continued=True)

    service._try_acquire_bot_run_lock = Mock(return_value=(True, lock))
    service._release_bot_run_lock = GridBotService._release_bot_run_lock
    service.bot_storage = Mock(get_bot=Mock(return_value=dict(running_bot)))
    service._merge_cycle_runtime_context = Mock(return_value=dict(running_bot))
    service._monitor_stop_cleanup_pending = Mock(
        side_effect=AssertionError("cleanup monitor should not run")
    )
    service._mark_runner_pickup = Mock()
    service._get_client_for_bot = Mock(return_value=Mock())
    service.client = Mock()
    service._run_bot_cycle_impl = Mock(return_value=continued_bot)

    updated = GridBotService.run_bot_cycle(service, dict(running_bot))

    service._monitor_stop_cleanup_pending.assert_not_called()
    service._run_bot_cycle_impl.assert_called_once()
    assert updated["cycle_continued"] is True
    lock.release.assert_called_once()


def test_handle_upnl_hard_stoploss_uses_stop_cleanup_transition():
    service = _make_service()
    service._transition_to_stop_cleanup_state = Mock(
        return_value={
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "status": "stop_cleanup_pending",
            "upnl_stoploss_trigger_count": 1,
        }
    )
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
        "upnl_stoploss_trigger_count": 0,
    }

    updated = GridBotService._handle_upnl_hard_stoploss(
        service,
        bot,
        "BTCUSDT",
        {"reason": "hard_limit", "upnl_pct": -0.12},
    )

    service._transition_to_stop_cleanup_state.assert_called_once()
    assert updated["status"] == "stop_cleanup_pending"
