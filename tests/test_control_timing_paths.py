import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from services.bot_manager_service import BotManagerService
from services.bybit_client import BybitClient
from services.grid_bot_service import GridBotService
from runner import should_expedite_running_bot


class _Storage:
    def __init__(self, bot):
        self.bot = dict(bot)
        self.saved = []

    def get_bot(self, bot_id):
        if self.bot.get("id") == bot_id:
            return dict(self.bot)
        return None

    def list_bots(self):
        return [dict(self.bot)]

    def save_bot(self, bot):
        self.bot = dict(bot)
        self.saved.append(dict(bot))
        return dict(bot)


def _build_mock_session():
    session = Mock()
    response = Mock()
    response.status_code = 200
    response.text = '{"retCode": 0, "result": {"list": []}}'
    response.json.return_value = {"retCode": 0, "result": {"list": []}}
    session.get.return_value = response
    session.post.return_value = response
    return session


def test_balance_target_stops_bot_using_account_equity_fallback():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.bot_storage = SimpleNamespace(save_bot=lambda bot: dict(bot))
    service._apply_reevaluation_runtime_context = lambda bot, now_ts: False
    service._ensure_stream_symbol = lambda symbol: None
    service._normalize_mode_range_state = lambda bot: None
    service._auto_pilot_should_force_repick = lambda bot, symbol: False
    service._auto_pilot_pending_rotation_ready = lambda bot, symbol: False
    service._get_position_mode = lambda bot, symbol: 0
    service._close_position_market = Mock(return_value=True)
    service._force_cancel_all_orders = Mock(return_value={"success": True, "cancelled": 0})
    service._confirm_symbol_cleanup_state = Mock(return_value={
        "success": True, "flat": True, "orders_cleared": True, "cleanup_confirmed": True,
    })
    service.client.set_leverage = Mock()
    service.client.get_wallet_balance.return_value = {
        "success": True,
        "data": {"list": [{"coin": [], "totalEquity": "120"}]},
    }

    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
        "mode": "long",
        "auto_stop_target_usdt": 100.0,
        "auto_stop_target_effective_usdt": 100.0,
        "auto_stop_triggered": False,
        "auto_stop_armed": True,
    }

    updated = GridBotService._run_bot_cycle_impl(service, dict(bot))

    assert updated["status"] == "stopped"
    assert updated["auto_stop_triggered"] is True
    assert updated["control_timing"]["balance_target"]["balance_target_metric"] == "account_equity"
    assert updated["control_timing"]["balance_target"]["balance_target_triggered"] is True
    service._close_position_market.assert_called_once_with("BTCUSDT", bot=updated)
    service.client.get_wallet_balance.assert_called_once_with(skip_cache=True)


def test_create_order_checked_records_first_start_order_timing():
    service = GridBotService.__new__(GridBotService)
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
        "_position_mode": "hedge",
        "control_timing": {
            "start": {
                "control_action_received_at": "2026-03-13T12:00:00+00:00",
            }
        },
    }
    service.bot_storage = SimpleNamespace(get_bot=lambda bot_id: dict(bot))
    service.client = Mock()
    service.client.create_order.return_value = {
        "success": True,
        "data": {"orderId": "ord-1"},
        "timing": {"order_submit_ack_at": "2026-03-13T12:00:01+00:00"},
    }
    service._resolve_position_idx = lambda *args, **kwargs: 1
    service._normalize_order_qty = lambda *args, **kwargs: 0.5
    service._get_instrument_info = lambda symbol: None
    service._enforce_auto_pilot_opening_loss_budget = lambda **kwargs: None
    service._build_persistent_ownership_snapshot = lambda *args, **kwargs: None
    service._augment_directional_opening_sizing_fields = lambda *args, **kwargs: None
    service._promote_trade_forensic_context = Mock()

    result = GridBotService._create_order_checked(
        service,
        bot,
        "BTCUSDT",
        "Buy",
        0.5,
        order_type="Limit",
        price=100.0,
        order_link_id="ord-link-1",
    )

    assert result["success"] is True
    assert result["timing"]["decision_to_submit_ack_ms"] is not None
    assert bot["control_timing"]["last_order_submit"]["order_link_id"] == "ord-link-1"
    assert bot["control_timing"]["start"]["first_order_submitted_at"] == "2026-03-13T12:00:01+00:00"
    assert bot["control_timing"]["start"]["start_to_first_order_ms"] == 1000.0


def test_stop_and_emergency_stop_emit_control_timing():
    bot = {"id": "bot-1", "symbol": "BTCUSDT", "status": "running", "mode": "long"}
    storage = _Storage(bot)
    client = Mock()
    client.get_open_orders.return_value = {"success": True, "data": {"list": []}}
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
    client.create_order.return_value = {
        "success": True,
        "timing": {"order_submit_to_ack_ms": 21.0},
    }
    service = BotManagerService(client=client, bot_storage=storage)
    service._force_cancel_all_orders = Mock(
        return_value={
            "success": True,
            "cancelled": 0,
            "timing": {"cancel_request_to_ack_ms": 12.0},
        }
    )

    stopped = service.stop_bot("bot-1", action_received_at_ts=1000.0)
    result = service.emergency_stop("bot-1", action_received_at_ts=1001.0)

    assert stopped["control_timing"]["stop"]["control_action_kind"] == "stop"
    assert stopped["control_timing"]["stop"]["control_action_to_stop_state_ms"] is not None
    assert result["success"] is True
    assert result["timing"]["cancel_total_ms"] is not None
    assert result["timing"]["close_total_ms"] is not None
    assert "flat_confirmed" in result["timing"]


def test_bybit_client_order_and_cancel_timing_markers():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test-key", "test-secret", "https://api.bybit.com")
    client.session = mock_session
    client._run_order_command = lambda symbol, action, callback: {
        "success": True,
        "data": {"orderId": "ord-1"},
    }

    create_result = client.create_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        qty_is_normalized=True,
    )
    cancel_result = client.cancel_order(symbol="BTCUSDT", order_id="ord-1")

    assert create_result["timing"]["order_submit_to_ack_ms"] is not None
    assert cancel_result["timing"]["cancel_request_to_ack_ms"] is not None


def test_recent_control_change_is_expedited_for_runner_pickup():
    bot = {
        "status": "running",
        "started_at": "2026-03-13T12:00:00+00:00",
        "control_updated_at": "2026-03-13T12:00:00+00:00",
        "last_run_at": None,
    }

    assert should_expedite_running_bot(
        bot,
        now_ts=1741876800.5,
    ) is True

    bot["last_run_at"] = "2026-03-13T12:00:02+00:00"
    assert should_expedite_running_bot(
        bot,
        now_ts=1741876803.0,
    ) is False
