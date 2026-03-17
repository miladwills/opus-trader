import importlib
import sys
import base64
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_app_module(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BASIC_AUTH_USER", "test-user")
    monkeypatch.setenv("BASIC_AUTH_PASS", "test-pass")
    monkeypatch.setenv("BYBIT_MAINNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_MAINNET_API_SECRET", "test-secret")
    monkeypatch.setenv("ENABLE_BYBIT_STREAMS", "0")

    if "config.config" in sys.modules:
        importlib.reload(sys.modules["config.config"])

    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")
    app_module.initialize_app_runtime()
    return app_module


def _basic_auth_headers(user="test-user", password="test-pass"):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_api_emergency_stop_marks_bots_stopped_without_crashing(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bots = [
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
        {"id": "bot-2", "symbol": "BTCUSDT", "status": "paused"},
    ]
    saved_bots = []
    cancel_calls = []
    create_order_calls = []
    emergency_stop_calls = []
    app_module.bot_storage = SimpleNamespace()
    app_module.bot_manager = SimpleNamespace()
    app_module.client = SimpleNamespace()

    monkeypatch.setattr(
        app_module.bot_storage,
        "list_bots",
        lambda: bots,
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_storage,
        "save_bot",
        lambda bot: saved_bots.append(dict(bot)),
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_manager,
        "emergency_stop",
        lambda bot_id, **kwargs: emergency_stop_calls.append(bot_id)
        or {"success": True},
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_manager,
        "_force_cancel_all_orders",
        lambda symbol: cancel_calls.append(symbol) or {"success": True, "cancelled": 2},
        raising=False,
    )
    monkeypatch.setattr(
        app_module.client,
        "get_positions",
        Mock(
            side_effect=[
                {
                    "success": True,
                    "data": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "side": "Buy",
                                "size": "1.5",
                                "positionIdx": 1,
                            }
                        ]
                    },
                },
                {"success": True, "data": {"list": []}},
            ]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        app_module.client,
        "create_order",
        lambda **kwargs: create_order_calls.append(kwargs) or {"success": True},
        raising=False,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/emergency-stop",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["results"]["processed"] == ["BTCUSDT"]
    assert emergency_stop_calls == []
    assert cancel_calls == ["BTCUSDT"]
    assert len(create_order_calls) == 1
    assert create_order_calls[0]["order_link_id"].startswith("ambg:")

    assert any(bot["status"] == "stop_cleanup_pending" for bot in saved_bots)
    finalized = [bot for bot in saved_bots if bot["status"] == "stopped"]
    assert len(finalized) == 2
    for bot in finalized:
        assert bot["started_at"] is None
        stop_time = datetime.fromisoformat(bot["last_run_at"])
        assert stop_time.tzinfo == timezone.utc


def test_api_emergency_stop_includes_flash_crash_paused_bots(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bots = [
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "flash_crash_paused"},
    ]
    emergency_stop_calls = []
    app_module.bot_storage = SimpleNamespace()
    app_module.bot_manager = SimpleNamespace()
    app_module.client = SimpleNamespace()

    monkeypatch.setattr(
        app_module.bot_storage,
        "list_bots",
        lambda: bots,
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_storage,
        "save_bot",
        lambda bot: dict(bot),
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_manager,
        "emergency_stop",
        lambda bot_id, **kwargs: emergency_stop_calls.append(bot_id)
        or {"success": True},
        raising=False,
    )
    monkeypatch.setattr(
        app_module.client,
        "get_positions",
        lambda: {"success": True, "data": {"list": []}},
        raising=False,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/emergency-stop",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    assert emergency_stop_calls == ["bot-1"]


def test_api_emergency_stop_keeps_cleanup_pending_when_flatten_not_confirmed(
    monkeypatch, tmp_path
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bots = [
        {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
        {"id": "bot-2", "symbol": "BTCUSDT", "status": "paused"},
    ]
    saved_bots = []
    app_module.bot_storage = SimpleNamespace()
    app_module.bot_manager = SimpleNamespace()
    app_module.client = SimpleNamespace()

    monkeypatch.setattr(app_module.bot_storage, "list_bots", lambda: bots, raising=False)
    monkeypatch.setattr(
        app_module.bot_storage,
        "save_bot",
        lambda bot: saved_bots.append(dict(bot)),
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_manager,
        "_force_cancel_all_orders",
        lambda symbol: {"success": True, "cancelled": 2},
        raising=False,
    )
    monkeypatch.setattr(
        app_module.client,
        "get_positions",
        lambda **kwargs: {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "1.5",
                        "positionIdx": 1,
                    }
                ]
            },
        },
        raising=False,
    )
    monkeypatch.setattr(
        app_module.client,
        "create_order",
        lambda **kwargs: {"success": True},
        raising=False,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/emergency-stop",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["results"]["pending"] == ["BTCUSDT"]
    assert not payload["results"]["errors"]
    assert any(bot["status"] == "stop_cleanup_pending" for bot in saved_bots)


def test_positions_payload_attributes_paused_owner(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    paused_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "paused",
        "mode": "long",
        "range_mode": "dynamic",
        "tp_pct": 0.01,
        "auto_stop": 5.0,
        "auto_stop_target_usdt": 7.0,
    }
    app_module.bot_storage = SimpleNamespace(list_bots=lambda: [paused_bot])
    app_module.position_service = SimpleNamespace(
        get_positions=lambda skip_cache=True: {
            "positions": [{"symbol": "BTCUSDT", "size": 1.0, "side": "Buy"}],
            "summary": {},
        }
    )
    app_module.account_service = SimpleNamespace(
        get_overview=lambda: {
            "equity": 100.0,
            "available_balance": 10.0,
            "realized_pnl": 1.0,
            "unrealized_pnl": 2.0,
        }
    )
    app_module._sync_stream_subscriptions_once = lambda: None

    payload = app_module._build_positions_payload()

    assert payload["positions"][0]["bot_attribution"] == "unique_running_bot"
    assert payload["positions"][0]["bot_id"] == "bot-1"


def test_api_close_position_uses_bot_tagged_order_link_id_when_bot_id_supplied(
    monkeypatch, tmp_path
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bot = {
        "id": "31b431db-9741-44ff-9e16-46eaf31a057a",
        "symbol": "BTCUSDT",
    }
    create_order = Mock(return_value={"success": True})
    app_module.bot_storage = SimpleNamespace(
        get_bot=lambda bot_id: dict(bot) if bot_id == bot["id"] else None
    )
    app_module.client = SimpleNamespace(
        get_positions=lambda skip_cache=True: {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "1.5",
                        "positionIdx": 1,
                        "markPrice": "100000",
                    }
                ]
            },
        },
        get_qty_filters=lambda symbol: {"min_qty": 0.001, "qty_step": 0.001},
        normalize_qty=lambda symbol, qty, log_skip=False: float(qty),
        create_order=create_order,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/close-position",
            json={"symbol": "BTCUSDT", "side": "Buy", "bot_id": bot["id"]},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    kwargs = create_order.call_args.kwargs
    assert kwargs["position_idx"] == 1
    assert kwargs["reduce_only"] is True
    assert kwargs["order_link_id"].startswith("cls:31b431db:")
    assert kwargs["ownership_snapshot"]["bot_id"] == bot["id"]
    assert kwargs["ownership_snapshot"]["source"] == "manual_close"
    assert kwargs["ownership_snapshot"]["action"] == "manual_close"


def test_api_close_position_uses_manual_marker_without_bot_id(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    create_order = Mock(return_value={"success": True})
    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)
    app_module.client = SimpleNamespace(
        get_positions=lambda skip_cache=True: {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "1.5",
                        "positionIdx": 1,
                        "markPrice": "100000",
                    }
                ]
            },
        },
        get_qty_filters=lambda symbol: {"min_qty": 0.001, "qty_step": 0.001},
        normalize_qty=lambda symbol, qty, log_skip=False: float(qty),
        create_order=create_order,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/close-position",
            json={"symbol": "BTCUSDT", "side": "Buy"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    kwargs = create_order.call_args.kwargs
    assert kwargs["position_idx"] == 1
    assert kwargs["reduce_only"] is True
    assert kwargs["order_link_id"].startswith("close_manual_")
    assert kwargs["ownership_snapshot"]["bot_id"] is None
    assert kwargs["ownership_snapshot"]["owner_state"] == "manual"
    assert kwargs["ownership_snapshot"]["source"] == "manual_close"


def test_reduce_only_route_bumps_control_state_and_cancels_opening_orders(
    monkeypatch, tmp_path
):
    app_module = _load_app_module(monkeypatch, tmp_path)

    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "status": "running",
        "control_version": 2,
        "reduce_only_mode": False,
    }
    saved_bots = []
    marked_versions = []
    cancel_calls = []

    app_module.bot_storage = SimpleNamespace()
    app_module.bot_manager = SimpleNamespace()

    monkeypatch.setattr(
        app_module.bot_storage,
        "get_bot",
        lambda bot_id: dict(bot) if bot_id == "bot-1" else None,
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_storage,
        "save_bot",
        lambda incoming: saved_bots.append(dict(incoming)) or dict(incoming),
        raising=False,
    )

    def mark_control_state_change(target):
        target["control_version"] = int(target.get("control_version") or 0) + 1
        marked_versions.append(target["control_version"])

    monkeypatch.setattr(
        app_module.bot_manager,
        "_mark_control_state_change",
        mark_control_state_change,
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_manager,
        "_is_tradeable_symbol",
        lambda symbol: True,
        raising=False,
    )
    monkeypatch.setattr(
        app_module.bot_manager,
        "_cancel_opening_orders_preserve_exits",
        lambda saved_bot, symbol: cancel_calls.append((saved_bot["id"], symbol))
        or {"success": True, "cancelled": 3},
        raising=False,
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots/reduce-only",
            json={"id": "bot-1", "reduce_only": True},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["reduce_only_mode"] is True
    assert marked_versions == [3]
    assert saved_bots[0]["control_version"] == 3
    assert cancel_calls == [("bot-1", "BTCUSDT")]


def test_api_close_position_tags_unique_live_owner(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    live_bot = {"id": "31b431db-9741-44ff-9e16-46eaf31a057a", "symbol": "BTCUSDT", "status": "running"}
    create_order_calls = []
    app_module.bot_storage = SimpleNamespace(
        list_bots=lambda: [live_bot],
        get_bot=lambda bot_id: dict(live_bot) if bot_id == live_bot["id"] else None,
    )
    app_module.client = SimpleNamespace(
        get_positions=lambda **kwargs: {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "0.5",
                        "positionIdx": 1,
                        "markPrice": "100000",
                    }
                ]
            },
        },
        get_qty_filters=lambda symbol: {"min_qty": 0.001, "qty_step": 0.001},
        normalize_qty=lambda symbol, qty, log_skip=False: float(qty),
        create_order=lambda **kwargs: create_order_calls.append(kwargs) or {"success": True},
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/close-position",
            json={"symbol": "BTCUSDT", "side": "Buy"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    assert len(create_order_calls) == 1
    assert create_order_calls[0]["order_link_id"].startswith("cls:")
    assert create_order_calls[0]["position_idx"] == 1


def test_api_close_position_rejects_ambiguous_same_symbol_owner(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    app_module.bot_storage = SimpleNamespace(
        list_bots=lambda: [
            {"id": "bot-1", "symbol": "BTCUSDT", "status": "running"},
            {"id": "bot-2", "symbol": "BTCUSDT", "status": "paused"},
        ],
        get_bot=lambda bot_id: None,
    )
    app_module.client = SimpleNamespace(
        get_positions=lambda **kwargs: {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "0.5",
                        "positionIdx": 1,
                        "markPrice": "100000",
                    }
                ]
            },
        },
        get_qty_filters=lambda symbol: {"min_qty": 0.001, "qty_step": 0.001},
        normalize_qty=lambda symbol, qty, log_skip=False: float(qty),
        create_order=lambda **kwargs: {"success": True},
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/close-position",
            json={"symbol": "BTCUSDT", "side": "Buy"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 409
    payload = response.get_json()
    assert "Ambiguous same-symbol bot ownership" in payload["error"]
