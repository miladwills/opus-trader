import base64
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from services.bot_preset_service import BotPresetService
from services.custom_bot_preset_service import CustomBotPresetService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _basic_auth_headers(user="test-user", password="test-pass"):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


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
    app_module.APP_RUNTIME_INITIALIZED = True
    app_module._sync_stream_subscriptions_once = lambda: None
    app_module._maybe_sync_closed_pnl_for_api = lambda force=False: None
    return app_module


class _AuditSink:
    def __init__(self):
        self.events = []

    def enabled(self):
        return True

    def record_event(self, payload, **kwargs):
        self.events.append(dict(payload))
        return True


class _BotStorage:
    def __init__(self, bot):
        self.bot = bot

    def get_bot(self, bot_id):
        if str(bot_id) == str(self.bot.get("id")):
            return dict(self.bot)
        return None


def _wire_services(app_module, tmp_path, bot):
    audit_sink = _AuditSink()
    custom_service = CustomBotPresetService(
        str(tmp_path / "storage" / "custom_bot_presets.json"),
        bot_storage=_BotStorage(bot),
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: datetime(2026, 3, 12, 17, 15, tzinfo=timezone.utc),
    )
    bot_preset_service = BotPresetService(
        custom_preset_service=custom_service,
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: datetime(2026, 3, 12, 17, 15, tzinfo=timezone.utc),
    )
    app_module.custom_bot_preset_service = custom_service
    app_module.bot_preset_service = bot_preset_service
    app_module.bot_storage = _BotStorage(bot)
    app_module.bot_manager = type("Manager", (), {"audit_diagnostics_service": audit_sink})()
    return custom_service, audit_sink


def test_api_custom_bot_presets_from_bot_and_list(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    _, audit_sink = _wire_services(
        app_module,
        tmp_path,
        {
            "id": "bot-7",
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "range_mode": "fixed",
            "leverage": 3,
            "grid_count": 10,
            "grid_distribution": "balanced",
            "session_timer_enabled": False,
            "status": "running",
            "position_size": 2.0,
        },
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        created_response = client.post(
            "/api/custom-bot-presets/from-bot/bot-7",
            headers=_basic_auth_headers(),
            json={"preset_name": "ETH Carry Forward"},
        )
        listed_response = client.get("/api/custom-bot-presets", headers=_basic_auth_headers())

    assert created_response.status_code == 200
    created_payload = created_response.get_json()
    assert created_payload["ok"] is True
    assert created_payload["preset"]["preset_type"] == "custom"
    assert created_payload["preset"]["settings"]["leverage"] == 3.0
    assert "status" not in created_payload["preset"]["settings"]

    assert listed_response.status_code == 200
    listed_payload = listed_response.get_json()
    assert listed_payload["total_presets"] == 1
    assert listed_payload["items"][0]["name"] == "ETH Carry Forward"
    assert listed_payload["items"][0]["source_bot_id"] == "bot-7"
    assert audit_sink.events[-1]["event_type"] in {
        "custom_bot_preset_created",
        "custom_bot_preset_created_from_bot",
    }


def test_api_custom_bot_presets_delete_removes_preset(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    custom_service, _ = _wire_services(
        app_module,
        tmp_path,
        {
            "id": "bot-9",
            "symbol": "BTCUSDT",
            "mode": "neutral",
        },
    )
    preset = custom_service.create_preset(
        preset_name="Delete Me",
        fields={"leverage": 2, "grid_count": 6},
        source_bot_id="bot-9",
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.delete(
            f"/api/custom-bot-presets/{preset['preset_id']}",
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert custom_service.get_preset(preset["preset_id"]) is None


def test_api_custom_bot_presets_patch_renames_preset(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    custom_service, _ = _wire_services(
        app_module,
        tmp_path,
        {
            "id": "bot-11",
            "symbol": "ETHUSDT",
            "mode": "neutral",
        },
    )
    preset = custom_service.create_preset(
        preset_name="Rename Me",
        fields={"leverage": 3, "grid_count": 8},
        source_bot_id="bot-11",
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.patch(
            f"/api/custom-bot-presets/{preset['preset_id']}",
            headers=_basic_auth_headers(),
            json={"preset_name": "Renamed ETH Setup"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["preset"]["name"] == "Renamed ETH Setup"
    assert custom_service.get_preset(preset["preset_id"])["preset_name"] == "Renamed ETH Setup"


def test_api_custom_bot_presets_patch_refuses_built_in_rename(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    _wire_services(
        app_module,
        tmp_path,
        {
            "id": "bot-12",
            "symbol": "ETHUSDT",
            "mode": "neutral",
        },
    )

    built_in_before = app_module.bot_preset_service.get_preset("manual_blank")

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.patch(
            "/api/custom-bot-presets/manual_blank",
            headers=_basic_auth_headers(),
            json={"preset_name": "Renamed Manual Blank"},
        )

    built_in_after = app_module.bot_preset_service.get_preset("manual_blank")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "built-in presets cannot be renamed"
    assert payload["blocked_reason"] == "built_in_preset_rename_refused"
    assert payload["preset_type"] == "built_in"
    assert built_in_before["name"] == "Manual Blank"
    assert built_in_after["name"] == "Manual Blank"
