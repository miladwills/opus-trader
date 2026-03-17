from datetime import datetime, timezone
from unittest.mock import Mock

from services.bot_manager_service import BotManagerService


def make_service():
    return BotManagerService.__new__(BotManagerService)


def test_reset_session_runtime_state_clears_failure_breaker_and_skip_markers():
    service = make_service()
    bot = {
        "_failure_breaker": {"counts": {"one_sided_grid_prevented": 2}},
        "_block_opening_orders": True,
        "_nlp_block_opening_orders": True,
        "_skip_new_orders_for_margin": True,
        "_skip_opening_orders_for_margin": True,
        "last_skip_reason": "min_notional_one_sided_guard",
        "last_warning": "cooldown active",
        "scalp_learned_opening_order_cap": 14,
        "scalp_learned_opening_cap_at": "2026-03-06T18:00:00+00:00",
        "scalp_learned_opening_cap_reason": "insufficient_margin",
    }

    service._reset_session_runtime_state(bot)

    assert bot["_failure_breaker"] is None
    assert bot["_block_opening_orders"] is False
    assert bot["_nlp_block_opening_orders"] is False
    assert bot["_skip_new_orders_for_margin"] is False
    assert bot["_skip_opening_orders_for_margin"] is False
    assert bot["last_skip_reason"] is None
    assert bot["last_warning"] is None
    assert bot["scalp_learned_opening_order_cap"] is None
    assert bot["scalp_learned_opening_cap_at"] is None
    assert bot["scalp_learned_opening_cap_reason"] is None


def test_manual_start_skips_expired_absolute_session_window_only():
    service = make_service()
    now_dt = datetime(2026, 3, 13, 5, 10, tzinfo=timezone.utc)
    bot = {
        "session_timer_enabled": True,
        "session_stop_at": "2026-03-12T18:21:00+00:00",
        "session_timer_state": "completed",
        "session_timer_completed_at": "2026-03-12T18:21:05+00:00",
        "session_timer_completed_reason": "green_grace_flat",
        "session_timer_last_event": "session_completed",
        "session_timer_no_new_entries_active": True,
        "_session_timer_block_opening_orders": True,
        "last_warning": "Old warning",
    }

    service._suppress_expired_absolute_session_window_on_manual_start(
        bot,
        now_dt=now_dt,
    )

    assert bot["_session_timer_skip_expired_absolute_window"] is True
    assert bot["session_timer_state"] == "inactive"
    assert bot["session_timer_completed_reason"] == "expired_window_skipped_on_manual_start"
    assert bot["session_timer_last_event"] == "expired_window_skipped_on_manual_start"
    assert bot["session_timer_no_new_entries_active"] is False
    assert bot["_session_timer_block_opening_orders"] is False
    assert bot["last_warning"] == "Expired session window skipped on manual start"


def test_manual_start_keeps_recurring_time_only_session_window_active():
    service = make_service()
    bot = {
        "session_timer_enabled": True,
        "session_stop_at": "18:21",
        "session_timer_state": "inactive",
    }

    service._suppress_expired_absolute_session_window_on_manual_start(
        bot,
        now_dt=datetime(2026, 3, 13, 5, 10, tzinfo=timezone.utc),
    )

    assert bot["_session_timer_skip_expired_absolute_window"] is False
    assert bot["session_timer_state"] == "inactive"


def test_start_bot_clears_stale_stop_cleanup_markers_before_running():
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "auto_pilot": True,
            "mode": "neutral_classic_bybit",
            "status": "stopped",
            "investment": 100,
            "leverage": 3,
            "lower_price": 0,
            "upper_price": 0,
            "grid_lower_price": 5040.4,
            "grid_upper_price": 5246.1,
            "grid_levels_total": 10,
            "paper_trading": False,
            "trading_env": "mainnet",
            "stop_cleanup_pending": True,
            "stop_cleanup_target_status": "stopped",
            "stop_cleanup_scope": "emergency_stop",
            "stop_cleanup_reason": "emergency_stop",
            "stop_cleanup_requested_at": "2026-03-14T04:22:19+00:00",
            "stop_cleanup_final_last_error": "cleanup pending",
            "reduce_only_mode": True,
            "auto_stop_paused": True,
        }
    )
    service = BotManagerService(client=Mock(), bot_storage=storage)

    saved = service.start_bot("bot-1")

    assert saved["status"] == "running"
    assert saved["reduce_only_mode"] is False
    assert saved["auto_stop_paused"] is False
    assert "stop_cleanup_pending" not in saved
    assert "stop_cleanup_target_status" not in saved
    assert "stop_cleanup_scope" not in saved
    assert "stop_cleanup_reason" not in saved
    assert "stop_cleanup_requested_at" not in saved
    assert "stop_cleanup_final_last_error" not in saved


class _StubStorage:
    def __init__(self, bot):
        self.bot = dict(bot)
        self.saved_bots = []
        self.deleted_ids = []

    def list_bots(self):
        return [dict(self.bot)]

    def get_bot(self, bot_id):
        if self.bot.get("id") == bot_id:
            return dict(self.bot)
        return None

    def save_bot(self, bot):
        self.bot = dict(bot)
        self.saved_bots.append(dict(bot))
        return dict(bot)

    def delete_bot(self, bot_id):
        if self.bot.get("id") != bot_id:
            return False
        self.deleted_ids.append(bot_id)
        self.bot = {}
        return True


def test_stop_bot_clears_started_at_and_sets_last_run_at():
    started_at = "2026-03-07T18:00:00+00:00"
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "status": "running",
            "started_at": started_at,
            "accumulated_runtime_hours": 0.0,
        }
    )
    service = BotManagerService(client=Mock(), bot_storage=storage)
    service._cancel_all_bot_orders = Mock(return_value={"success": True})

    saved = service.stop_bot("bot-1")

    assert saved["status"] == "stopped"
    assert saved["started_at"] is None
    assert saved["last_run_at"] is not None
    assert datetime.fromisoformat(
        str(saved["last_run_at"]).replace("Z", "+00:00")
    ) <= datetime.now(timezone.utc)


def test_stop_bot_cancels_only_bot_owned_orders():
    started_at = "2026-03-07T18:00:00+00:00"
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "running",
            "started_at": started_at,
            "accumulated_runtime_hours": 0.0,
        }
    )
    client = Mock()
    client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "orderId": "open-1",
                    "orderLinkId": "bv2:bot1:12345678BO",
                    "reduceOnly": False,
                },
                {
                    "orderId": "close-1",
                    "orderLinkId": "bv2:bot1:12345678BC",
                    "reduceOnly": True,
                },
                {
                    "orderId": "other-open-1",
                    "orderLinkId": "bv2:other1:12345678BO",
                    "reduceOnly": False,
                },
            ]
        },
    }
    service = BotManagerService(client=client, bot_storage=storage)

    saved = service.stop_bot("bot-1")

    assert saved["status"] == "stopped"
    assert client.cancel_order.call_count == 2
    cancelled_ids = [call.kwargs["order_id"] for call in client.cancel_order.call_args_list]
    assert cancelled_ids == ["open-1", "close-1"]


def test_delete_bot_cancels_only_bot_owned_orders():
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "paused",
        }
    )
    client = Mock()
    client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "orderId": "bot-open-1",
                    "orderLinkId": "bv2:bot1:12345678BO",
                    "reduceOnly": False,
                },
                {
                    "orderId": "bot-close-1",
                    "orderLinkId": "bv2:bot1:12345678BC",
                    "reduceOnly": True,
                },
                {
                    "orderId": "other-close-1",
                    "orderLinkId": "bv2:other1:12345678BC",
                    "reduceOnly": True,
                },
            ]
        },
    }
    service = BotManagerService(client=client, bot_storage=storage)

    deleted = service.delete_bot("bot-1")

    assert deleted is True
    assert client.cancel_order.call_count == 2
    cancelled_ids = [call.kwargs["order_id"] for call in client.cancel_order.call_args_list]
    assert cancelled_ids == ["bot-open-1", "bot-close-1"]
    assert storage.deleted_ids == ["bot-1"]


def test_pause_bot_cancels_opening_orders_but_preserves_exits():
    started_at = "2026-03-07T18:00:00+00:00"
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "running",
            "started_at": started_at,
            "accumulated_runtime_hours": 0.0,
        }
    )
    client = Mock()
    client._get_now_ts.return_value = 1234567890.0
    client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "orderId": "open-1",
                    "orderLinkId": "bv2:bot1:12345678BO",
                    "reduceOnly": False,
                },
                {
                    "orderId": "close-1",
                    "orderLinkId": "bv2:bot1:12345678BC",
                    "reduceOnly": True,
                },
                {
                    "orderId": "other-1",
                    "orderLinkId": "bv2:other1:12345678BO",
                    "reduceOnly": False,
                },
            ]
        },
    }
    service = BotManagerService(client=client, bot_storage=storage)

    saved = service.pause_bot("bot-1")

    assert saved["status"] == "paused"
    assert saved["pause_reason_type"] == "manual"
    assert saved["pause_reason"] == "Manual pause"
    assert saved["started_at"] is None
    client.cancel_order.assert_called_once_with(
        symbol="BTCUSDT",
        order_id="open-1",
        order_link_id="bv2:bot1:12345678BO",
    )


def test_resume_bot_allows_recovering_status_and_clears_pause_markers():
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "status": "recovering",
            "pause_reason": "Danger zone",
            "pause_reason_type": "danger_zone",
            "paused_at": 1234567000.0,
            "pause_unrealized_pnl": -12.5,
            "recovery_entry_pnl": -12.5,
            "_last_pause_recovery_check": 1234567010.0,
            "_last_recovery_check": 1234567020.0,
            "_neutral_trend_exit": {"waiting_for_green": True},
            "realized_pnl": 4.0,
        }
    )
    service = BotManagerService(client=Mock(), bot_storage=storage)
    service._get_account_snapshot = Mock(return_value={"equity": 1000.0})
    service._validate_and_prepare_launch = Mock(return_value={"notes": []})
    service._arm_auto_stop_target_for_session = Mock()

    saved = service.resume_bot("bot-1")

    assert saved["status"] == "running"
    assert saved["last_error"] is None
    assert saved["started_at"] is not None
    assert "pause_reason" not in saved
    assert "pause_reason_type" not in saved
    assert "paused_at" not in saved
    assert "pause_unrealized_pnl" not in saved
    assert "recovery_entry_pnl" not in saved
    assert "_last_pause_recovery_check" not in saved
    assert "_last_recovery_check" not in saved
    assert "_neutral_trend_exit" not in saved


def test_resume_bot_clears_stale_stop_cleanup_markers_before_running():
    storage = _StubStorage(
        {
            "id": "bot-1",
            "symbol": "Auto-Pilot",
            "auto_pilot": True,
            "mode": "neutral_classic_bybit",
            "status": "paused",
            "investment": 100,
            "leverage": 3,
            "paper_trading": False,
            "trading_env": "mainnet",
            "realized_pnl": 4.0,
            "stop_cleanup_pending": True,
            "stop_cleanup_target_status": "stopped",
            "stop_cleanup_scope": "emergency_stop",
            "stop_cleanup_reason": "emergency_stop",
            "stop_cleanup_requested_at": "2026-03-14T04:22:19+00:00",
            "stop_cleanup_final_last_error": "cleanup pending",
            "reduce_only_mode": True,
            "auto_stop_paused": True,
        }
    )
    service = BotManagerService(client=Mock(), bot_storage=storage)
    service._get_account_snapshot = Mock(return_value={"equity": 1000.0})
    service._validate_and_prepare_launch = Mock(return_value={"notes": []})
    service._arm_auto_stop_target_for_session = Mock()

    saved = service.resume_bot("bot-1")

    assert saved["status"] == "running"
    assert saved["reduce_only_mode"] is False
    assert saved["auto_stop_paused"] is False
    assert "stop_cleanup_pending" not in saved
    assert "stop_cleanup_target_status" not in saved
    assert "stop_cleanup_scope" not in saved
    assert "stop_cleanup_reason" not in saved
    assert "stop_cleanup_requested_at" not in saved
    assert "stop_cleanup_final_last_error" not in saved


def test_emergency_stop_refuses_shared_symbol_active_bots():
    primary_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }
    sibling_bot = {
        "id": "bot-2",
        "symbol": "BTCUSDT",
        "status": "paused",
    }

    class _SharedStorage(_StubStorage):
        def list_bots(self):
            return [dict(primary_bot), dict(sibling_bot)]

    storage = _SharedStorage(primary_bot)
    service = BotManagerService(client=Mock(), bot_storage=storage)
    service.stop_bot = Mock()

    result = service.emergency_stop("bot-1")

    assert result["success"] is False
    assert result["error"] == "shared_symbol_active_bots"
    service.stop_bot.assert_not_called()


def test_emergency_stop_uses_bot_attributable_reduce_only_close_orders():
    primary_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }
    storage = _StubStorage(primary_bot)
    client = Mock()
    client.get_positions.side_effect = [
        {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Sell",
                        "size": "1.25",
                        "positionIdx": 2,
                    }
                ]
            },
        },
        {"success": True, "data": {"list": []}},
    ]
    client.create_order.return_value = {"success": True}

    service = BotManagerService(client=client, bot_storage=storage)
    service.stop_bot = Mock(return_value=dict(primary_bot))
    service._force_cancel_all_orders = Mock(return_value={"success": True, "cancelled": 0})

    result = service.emergency_stop("bot-1")

    assert result["success"] is True
    client.create_order.assert_called_once()
    kwargs = client.create_order.call_args.kwargs
    assert kwargs["symbol"] == "BTCUSDT"
    assert kwargs["side"] == "Buy"
    assert kwargs["qty"] == 1.25
    assert kwargs["reduce_only"] is True
    assert kwargs["position_idx"] == 2
    assert kwargs["order_link_id"].startswith("close_bot-1_")
    assert kwargs["ownership_snapshot"]["bot_id"] == "bot-1"
    assert kwargs["ownership_snapshot"]["source"] == "bot_manager_service"
    assert kwargs["ownership_snapshot"]["action"] == "emergency_close"
    assert not client.close_position.called
    assert storage.bot["status"] == "stopped"
    assert storage.bot.get("stop_cleanup_pending") is None


def test_emergency_stop_keeps_cleanup_pending_until_flat_is_confirmed():
    primary_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
    }
    storage = _StubStorage(primary_bot)
    client = Mock()
    client.get_positions.side_effect = [
        {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "1.0",
                        "positionIdx": 1,
                    }
                ]
            },
        },
        {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "1.0",
                        "positionIdx": 1,
                    }
                ]
            },
        },
    ]
    client.create_order.return_value = {"success": True}

    service = BotManagerService(client=client, bot_storage=storage)
    service._force_cancel_all_orders = Mock(return_value={"success": True, "cancelled": 1})

    result = service.emergency_stop("bot-1")

    assert result["success"] is False
    assert result["cleanup_pending"] is True
    assert storage.bot["status"] == "stop_cleanup_pending"
    assert storage.bot["stop_cleanup_target_status"] == "stopped"
    assert storage.bot["reduce_only_mode"] is True
