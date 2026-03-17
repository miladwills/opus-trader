import base64
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from services.config_integrity_watchdog_service import ConfigIntegrityWatchdogService


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
    app_module._maybe_sync_closed_pnl_for_api = lambda: None
    return app_module


def test_api_bots_save_returns_config_integrity_audit(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    existing_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "quick_profit_enabled": True,
        "entry_gate_enabled": True,
        "settings_version": 4,
    }
    saved_bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "range_mode": "dynamic",
        "lower_price": 90000.0,
        "upper_price": 100000.0,
        "investment": 100.0,
        "leverage": 3.0,
        "quick_profit_enabled": False,
        "entry_gate_enabled": False,
    }
    captured = {}

    class DummyWatchdog:
        def record_save_roundtrip(self, submitted, saved, **kwargs):
            captured["ui_path"] = kwargs.get("ui_path")
            captured["previous_bot"] = kwargs.get("previous_bot")
            return {
                "checked_fields": ["quick_profit_enabled", "entry_gate_enabled"],
                "missing_expected_fields": [],
                "missing_in_response": [],
                "missing_in_persisted": [],
                "persisted_mismatches": [],
                "persisted_matches_intent": True,
                "response_matches_intent": True,
                "requested_values": {
                    "quick_profit_enabled": False,
                    "entry_gate_enabled": False,
                },
                "persisted_values": {
                    "quick_profit_enabled": False,
                    "entry_gate_enabled": False,
                },
            }

    app_module.bot_storage = SimpleNamespace(
        get_bot=lambda bot_id: existing_bot if bot_id == "bot-1" else saved_bot,
    )
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=lambda payload: saved_bot,
        audit_diagnostics_service=None,
    )
    app_module.config_integrity_watchdog_service = DummyWatchdog()

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots",
            headers={
                **_basic_auth_headers(),
                "X-Bot-Config-Path": "quick",
            },
            json={
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "mode": "long",
                "range_mode": "dynamic",
                "lower_price": 90000.0,
                "upper_price": 100000.0,
                "investment": 100.0,
                "leverage": 3.0,
                "settings_version": 4,
                "quick_profit_enabled": False,
                "entry_gate_enabled": False,
            },
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["config_integrity_audit"]["persisted_matches_intent"] is True
    assert payload["config_boolean_audit"]["checked_fields"] == [
        "quick_profit_enabled",
        "entry_gate_enabled",
    ]
    assert captured["ui_path"] == "quick"
    assert captured["previous_bot"]["id"] == "bot-1"


def test_api_bots_save_rejects_stale_or_missing_settings_version(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    stored_bot = {
        "id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "short",
        "range_mode": "dynamic",
        "lower_price": 1900.0,
        "upper_price": 2100.0,
        "investment": 100.0,
        "leverage": 5.0,
        "quick_profit_enabled": False,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "quick_profit_cooldown": 60,
        "trailing_sl_enabled": False,
        "trailing_sl_activation_pct": None,
        "trailing_sl_distance_pct": None,
        "settings_version": 8,
    }
    create_calls = []

    def _unexpected_create(_payload):
        create_calls.append(_payload)
        raise AssertionError("stale save must not reach create_or_update_bot")

    class AuditCollector:
        def __init__(self):
            self.events = []

        def record_event(self, payload, **kwargs):
            self.events.append(dict(payload))
            return True

    audit_sink = AuditCollector()

    app_module.bot_storage = SimpleNamespace(
        get_bot=lambda bot_id: dict(stored_bot) if bot_id == "bot-1" else None,
    )
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=_unexpected_create,
        audit_diagnostics_service=audit_sink,
    )
    app_module.config_integrity_watchdog_service = ConfigIntegrityWatchdogService(
        audit_service=audit_sink
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    payload = {
        "id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "short",
        "range_mode": "dynamic",
        "lower_price": 1900.0,
        "upper_price": 2100.0,
        "investment": 100.0,
        "leverage": 5.0,
        "quick_profit_enabled": False,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "quick_profit_cooldown": 60,
        "trailing_sl_enabled": False,
        "trailing_sl_activation_pct": None,
        "trailing_sl_distance_pct": None,
    }

    with flask_app.test_client() as client:
        # Non-UI paths must be rejected with 409
        stale_response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "api"},
            json={**payload, "settings_version": 7},
        )
        missing_response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "api"},
            json=payload,
        )

    stale_body = stale_response.get_json()
    missing_body = missing_response.get_json()

    assert stale_response.status_code == 409
    assert stale_body["error"] == "settings_version_conflict"
    assert stale_body["current_settings_version"] == 8
    assert stale_body["incoming_settings_version"] == 7

    assert missing_response.status_code == 409
    assert missing_body["error"] == "settings_version_conflict"
    assert missing_body["current_settings_version"] == 8
    assert missing_body["incoming_settings_version"] is None
    assert missing_body["conflict_reason"] == "missing_incoming_version"
    assert create_calls == []
    conflict_events = [
        event for event in audit_sink.events
        if event.get("event_type") == "settings_version_conflict"
    ]
    assert len(conflict_events) == 2
    assert conflict_events[0]["bot_id"] == "bot-1"
    assert conflict_events[0]["symbol"] == "ETHUSDT"
    assert conflict_events[0]["mode"] == "short"
    assert conflict_events[0]["ui_path"] == "api"
    assert conflict_events[0]["incoming_settings_version"] == 7
    assert conflict_events[0]["current_settings_version"] == 8
    assert conflict_events[0]["conflict_reason"] == "stale_incoming_version"
    assert conflict_events[1]["ui_path"] == "api"
    assert conflict_events[1]["incoming_settings_version"] is None
    assert conflict_events[1]["current_settings_version"] == 8
    assert conflict_events[1]["conflict_reason"] == "missing_incoming_version"


def test_api_bots_save_accepts_matching_settings_version_and_preserves_false_booleans(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    existing_bot = {
        "id": "bot-1",
        "symbol": "ETHUSDT",
        "quick_profit_enabled": True,
        "trailing_sl_enabled": True,
        "settings_version": 8,
    }
    saved_bot = {
        "id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "short",
        "range_mode": "dynamic",
        "lower_price": 1900.0,
        "upper_price": 2100.0,
        "investment": 100.0,
        "leverage": 5.0,
        "quick_profit_enabled": False,
        "quick_profit_target": 0.15,
        "quick_profit_close_pct": 0.5,
        "quick_profit_cooldown": 60,
        "trailing_sl_enabled": False,
        "trailing_sl_activation_pct": None,
        "trailing_sl_distance_pct": None,
        "settings_version": 9,
    }
    seen_payload = {}

    class AuditCollector:
        def __init__(self):
            self.events = []

        def record_event(self, payload, **kwargs):
            self.events.append(dict(payload))
            return True

    audit_sink = AuditCollector()

    class DummyWatchdog:
        def record_save_roundtrip(self, submitted, saved, **kwargs):
            audit_sink.record_event(
                {
                    "event_type": "config_save_roundtrip",
                    "bot_id": saved.get("id"),
                    "symbol": saved.get("symbol"),
                    "ui_path": kwargs.get("ui_path"),
                }
            )
            return {
                "checked_fields": ["quick_profit_enabled", "trailing_sl_enabled"],
                "missing_expected_fields": [],
                "missing_in_response": [],
                "missing_in_persisted": [],
                "persisted_mismatches": [],
                "persisted_matches_intent": True,
                "response_matches_intent": True,
                "requested_values": {
                    "quick_profit_enabled": False,
                    "trailing_sl_enabled": False,
                },
                "persisted_values": {
                    "quick_profit_enabled": False,
                    "trailing_sl_enabled": False,
                },
            }

    def _create(payload):
        seen_payload.update(payload)
        return dict(saved_bot)

    app_module.bot_storage = SimpleNamespace(
        get_bot=lambda bot_id: dict(existing_bot) if bot_id == "bot-1" else dict(saved_bot),
    )
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=_create,
        audit_diagnostics_service=audit_sink,
    )
    app_module.config_integrity_watchdog_service = DummyWatchdog()

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "id": "bot-1",
                "symbol": "ETHUSDT",
                "mode": "short",
                "range_mode": "dynamic",
                "lower_price": 1900.0,
                "upper_price": 2100.0,
                "investment": 100.0,
                "leverage": 5.0,
                "settings_version": 8,
                "quick_profit_enabled": False,
                "quick_profit_target": 0.15,
                "quick_profit_close_pct": 0.5,
                "quick_profit_cooldown": 60,
                "trailing_sl_enabled": False,
                "trailing_sl_activation_pct": None,
                "trailing_sl_distance_pct": None,
            },
        )

    body = response.get_json()

    assert response.status_code == 200
    assert seen_payload["settings_version"] == 8
    assert body["bot"]["quick_profit_enabled"] is False
    assert body["bot"]["quick_profit_target"] == 0.15
    assert body["bot"]["quick_profit_close_pct"] == 0.5
    assert body["bot"]["quick_profit_cooldown"] == 60
    assert body["bot"]["trailing_sl_enabled"] is False
    assert body["bot"]["trailing_sl_activation_pct"] is None
    assert body["bot"]["trailing_sl_distance_pct"] is None
    assert not any(
        event.get("event_type") == "settings_version_conflict"
        for event in audit_sink.events
    )
