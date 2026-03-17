from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from services.bot_manager_service import BotManagerService
from services.bot_storage_service import BotStorageService
from services.grid_bot_service import GridBotService


def _base_bot(**overrides):
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "investment": 100.0,
        "leverage": 3.0,
        "control_version": 0,
        "session_timer_enabled": True,
        "session_start_at": None,
        "session_stop_at": None,
        "session_no_new_entries_before_stop_min": 15,
        "session_end_mode": "hard_stop",
        "session_green_grace_min": 5,
        "session_force_close_max_loss_pct": None,
        "session_cancel_pending_orders_on_end": True,
        "session_reduce_only_on_end": False,
        "session_timer_state": "inactive",
        "session_timer_started_at": None,
        "session_timer_pre_stop_at": None,
        "session_timer_end_triggered_at": None,
        "session_timer_grace_started_at": None,
        "session_timer_grace_expires_at": None,
        "session_timer_completed_at": None,
        "session_timer_completed_reason": None,
        "session_timer_no_new_entries_active": False,
        "session_timer_reduce_only_active": False,
        "reduce_only_mode": False,
        "auto_stop_paused": False,
    }
    bot.update(overrides)
    return bot


def _make_grid_service():
    saved_runtime = []
    saved_control = []

    def _save_runtime(bot):
        snapshot = dict(bot)
        saved_runtime.append(snapshot)
        return snapshot

    def _save_bot(bot):
        snapshot = dict(bot)
        saved_control.append(snapshot)
        return snapshot

    service = GridBotService.__new__(GridBotService)
    service.bot_storage = SimpleNamespace(
        save_runtime_bot=_save_runtime,
        save_bot=_save_bot,
    )
    service._emit_audit_event = Mock(return_value=True)
    service._cancel_opening_orders_only = Mock(return_value=0)
    service._cancel_bot_orders = Mock(return_value=0)
    service._close_position_market = Mock(return_value=True)
    service._save_runtime_bot = _save_runtime
    service._get_session_timer_exposure_snapshot = Mock(
        return_value={
            "has_position": False,
            "position_count": 0,
            "opening_order_count": 0,
            "exit_order_count": 0,
            "position_unrealized_pnl": 0.0,
            "has_any_exposure": False,
        }
    )
    service._extract_order_list_from_response = (
        GridBotService._extract_order_list_from_response.__get__(
            service, GridBotService
        )
    )
    # H2 audit: mock cleanup state check (defaults to flat/clean)
    service._confirm_symbol_cleanup_state = Mock(return_value={
        "success": True,
        "flat": True,
        "orders_cleared": True,
        "cleanup_confirmed": True,
    })
    return service, saved_runtime, saved_control


def test_session_timer_disabled_keeps_bot_inactive_and_unblocked():
    service, saved_runtime, _ = _make_grid_service()
    bot = _base_bot(session_timer_enabled=False)

    result = service._apply_session_timer_control(
        bot,
        "BTCUSDT",
        now_dt=datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    assert result is None
    assert bot["session_timer_state"] == "inactive"
    assert bot["_session_timer_block_opening_orders"] is False
    assert bot["session_timer_no_new_entries_active"] is False
    assert saved_runtime


def test_session_timer_skip_expired_absolute_window_clears_runtime_blockers():
    service, saved_runtime, _ = _make_grid_service()
    bot = _base_bot(
        _session_timer_skip_expired_absolute_window=True,
        session_timer_state="completed",
        session_timer_reduce_only_active=True,
        _session_timer_block_opening_orders=True,
        reduce_only_mode=True,
        auto_stop_paused=True,
    )

    result = service._apply_session_timer_control(
        bot,
        "BTCUSDT",
        now_dt=datetime(2026, 3, 13, 5, 12, tzinfo=timezone.utc),
    )

    assert result is None
    assert bot["session_timer_state"] == "inactive"
    assert bot["session_timer_reduce_only_active"] is False
    assert bot["_session_timer_block_opening_orders"] is False
    assert saved_runtime[-1]["session_timer_state"] == "inactive"


def test_session_timer_future_start_blocks_entries_until_window_opens():
    service, saved_runtime, _ = _make_grid_service()
    now_dt = datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc)
    bot = _base_bot(
        session_start_at=(now_dt + timedelta(minutes=30)).isoformat(),
        session_stop_at=(now_dt + timedelta(hours=3)).isoformat(),
        session_end_mode="soft_stop",
    )

    result = service._apply_session_timer_control(bot, "BTCUSDT", now_dt=now_dt)

    assert result is None
    assert bot["session_timer_state"] == "scheduled_not_started"
    assert bot["_session_timer_block_opening_orders"] is True
    assert bot["session_timer_no_new_entries_active"] is True
    assert saved_runtime[-1]["session_timer_state"] == "scheduled_not_started"


def test_session_timer_pre_stop_blocks_new_entries_without_forcing_close():
    service, saved_runtime, _ = _make_grid_service()
    now_dt = datetime(2026, 3, 12, 13, 50, tzinfo=timezone.utc)
    bot = _base_bot(
        session_start_at=datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc).isoformat(),
        session_stop_at=datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc).isoformat(),
        session_no_new_entries_before_stop_min=15,
    )

    result = service._apply_session_timer_control(bot, "BTCUSDT", now_dt=now_dt)

    assert result is None
    assert bot["session_timer_state"] == "pre_stop_no_new_entries"
    assert bot["_session_timer_block_opening_orders"] is True
    assert bot["session_timer_no_new_entries_active"] is True
    service._cancel_opening_orders_only.assert_not_called()
    service._close_position_market.assert_not_called()
    assert saved_runtime[-1]["session_timer_state"] == "pre_stop_no_new_entries"


def test_session_timer_hard_stop_cancels_opening_orders_closes_position_and_completes():
    service, _, saved_control = _make_grid_service()
    now_dt = datetime(2026, 3, 12, 14, 5, tzinfo=timezone.utc)
    bot = _base_bot(
        session_stop_at=datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc).isoformat(),
        session_end_mode="hard_stop",
    )
    service._get_session_timer_exposure_snapshot.return_value = {
        "has_position": True,
        "position_count": 1,
        "opening_order_count": 2,
        "exit_order_count": 0,
        "position_unrealized_pnl": -1.0,
        "has_any_exposure": True,
    }

    result = service._apply_session_timer_control(bot, "BTCUSDT", now_dt=now_dt)

    assert result["status"] == "stopped"
    assert result["session_timer_state"] == "completed"
    assert result["session_timer_completed_reason"] == "hard_stop"
    service._cancel_opening_orders_only.assert_called_once_with(bot, "BTCUSDT")
    service._close_position_market.assert_called_once_with("BTCUSDT", bot=bot)
    assert saved_control[-1]["session_timer_state"] == "completed"


def test_session_timer_soft_stop_waits_for_flat_then_completes():
    service, saved_runtime, saved_control = _make_grid_service()
    now_dt = datetime(2026, 3, 12, 14, 5, tzinfo=timezone.utc)
    bot = _base_bot(
        session_stop_at=datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc).isoformat(),
        session_end_mode="soft_stop",
    )
    service._get_session_timer_exposure_snapshot.return_value = {
        "has_position": True,
        "position_count": 1,
        "opening_order_count": 0,
        "exit_order_count": 1,
        "position_unrealized_pnl": 0.4,
        "has_any_exposure": True,
    }

    first_result = service._apply_session_timer_control(bot, "BTCUSDT", now_dt=now_dt)

    assert first_result is None
    assert bot["status"] == "running"
    assert bot["session_timer_state"] == "pre_stop_no_new_entries"
    assert bot["_session_timer_block_opening_orders"] is True
    assert saved_runtime[-1]["session_timer_state"] == "pre_stop_no_new_entries"

    service._get_session_timer_exposure_snapshot.return_value = {
        "has_position": False,
        "position_count": 0,
        "opening_order_count": 0,
        "exit_order_count": 0,
        "position_unrealized_pnl": 0.0,
        "has_any_exposure": False,
    }
    second_result = service._apply_session_timer_control(
        bot,
        "BTCUSDT",
        now_dt=now_dt + timedelta(minutes=1),
    )

    assert second_result["status"] == "stopped"
    assert second_result["session_timer_state"] == "completed"
    assert second_result["session_timer_completed_reason"] == "soft_stop_flat"
    assert saved_control[-1]["status"] == "stopped"


def test_session_timer_green_grace_sets_reduce_only_and_force_closes_when_bounded():
    service, _, saved_control = _make_grid_service()
    stop_dt = datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc)
    bot = _base_bot(
        session_stop_at=stop_dt.isoformat(),
        session_end_mode="green_grace_then_stop",
        session_green_grace_min=5,
        session_force_close_max_loss_pct=2.0,
        session_reduce_only_on_end=True,
    )
    service._get_session_timer_exposure_snapshot.return_value = {
        "has_position": True,
        "position_count": 1,
        "opening_order_count": 1,
        "exit_order_count": 0,
        "position_unrealized_pnl": -1.0,
        "has_any_exposure": True,
    }

    first_result = service._apply_session_timer_control(
        bot,
        "BTCUSDT",
        now_dt=stop_dt + timedelta(seconds=10),
    )

    assert first_result["session_timer_state"] == "grace_active"
    assert first_result["reduce_only_mode"] is True
    assert first_result["session_timer_reduce_only_active"] is True
    assert first_result["status"] == "running"

    service._get_session_timer_exposure_snapshot.return_value = {
        "has_position": True,
        "position_count": 1,
        "opening_order_count": 0,
        "exit_order_count": 0,
        "position_unrealized_pnl": -3.0,
        "has_any_exposure": True,
    }
    second_result = service._apply_session_timer_control(
        bot,
        "BTCUSDT",
        now_dt=stop_dt + timedelta(minutes=6),
    )

    assert second_result["status"] == "stopped"
    assert second_result["session_timer_state"] == "completed"
    assert second_result["session_timer_completed_reason"] == "green_grace_forced_close"
    assert second_result["reduce_only_mode"] is False
    service._close_position_market.assert_called_with("BTCUSDT", bot=bot)
    assert saved_control[-1]["session_timer_completed_reason"] == "green_grace_forced_close"


def test_session_timer_config_persistence_round_trip(tmp_path):
    storage = BotStorageService(str(tmp_path / "bots.json"))
    service = BotManagerService.__new__(BotManagerService)
    service.bot_storage = storage
    service.client = None
    service.risk_manager = None
    service.account_service = None
    service._compute_min_notional_requirement = lambda bot_data: None
    service.analyze_launch = lambda bot_data: {
        "affordable": True,
        "effective_leverage": float(bot_data.get("leverage") or 3.0),
        "reasons": [],
    }

    saved = service.create_or_update_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "long",
            "range_mode": "fixed",
            "lower_price": 90000.0,
            "upper_price": 100000.0,
            "investment": 100.0,
            "leverage": 3.0,
            "session_timer_enabled": True,
            "session_start_at": "2026-03-12T14:00:00+00:00",
            "session_stop_at": "2026-03-12T17:00:00+00:00",
            "session_no_new_entries_before_stop_min": 20,
            "session_end_mode": "green_grace_then_stop",
            "session_green_grace_min": 7,
            "session_force_close_max_loss_pct": 2.5,
            "session_cancel_pending_orders_on_end": False,
            "session_reduce_only_on_end": True,
        }
    )

    persisted = storage.get_bot(saved["id"])

    assert persisted["session_timer_enabled"] is True
    assert persisted["session_start_at"] == "2026-03-12T14:00:00+00:00"
    assert persisted["session_stop_at"] == "2026-03-12T17:00:00+00:00"
    assert persisted["session_no_new_entries_before_stop_min"] == 20
    assert persisted["session_end_mode"] == "green_grace_then_stop"
    assert persisted["session_green_grace_min"] == 7
    assert persisted["session_force_close_max_loss_pct"] == 2.5
    assert persisted["session_cancel_pending_orders_on_end"] is False
    assert persisted["session_reduce_only_on_end"] is True
