import base64
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


class _SizingClient:
    def __init__(self, *, mark_price="4000", last_price="4000", min_qty="0.02", min_notional="5"):
        self.mark_price = mark_price
        self.last_price = last_price
        self.min_qty = min_qty
        self.min_notional = min_notional

    def get_instruments_info(self, symbol):
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "lotSizeFilter": {
                            "minOrderQty": self.min_qty,
                            "minNotionalValue": self.min_notional,
                        }
                    }
                ]
            },
        }

    def get_tickers(self, symbol):
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "markPrice": self.mark_price,
                        "lastPrice": self.last_price,
                    }
                ]
            },
        }


def test_api_bot_presets_returns_catalog(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_preset_service = SimpleNamespace(
        list_presets=lambda: {
            "generated_at": "2026-03-12T12:00:00+00:00",
            "default_preset": "manual_blank",
            "items": [
                {
                    "preset_id": "eth_conservative",
                    "name": "ETH Conservative",
                    "reasons": ["major-coin posture"],
                    "settings": {"leverage": 3.0},
                    "key_fields": [{"field": "leverage", "label": "Leverage", "value": 3.0}],
                }
            ],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.get("/api/bot-presets", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["default_preset"] == "manual_blank"
    assert payload["items"][0]["preset_id"] == "eth_conservative"


def test_api_bot_presets_recommend_returns_conservative_choice(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_preset_service = SimpleNamespace(
        recommend=lambda data: {
            "generated_at": "2026-03-12T12:00:00+00:00",
            "recommended_preset": "small_balance_safe",
            "confidence": "high",
            "reason": "Smaller budgets are safer with fewer grids.",
            "reasons": ["small balance sensitive to min notional"],
            "matched_signals": ["capital_guard_bias", "min_notional_sensitivity"],
            "prefill_settings": {"leverage": 3.0, "grid_count": 6},
            "alternative_presets": [{"preset_id": "manual_blank", "name": "Manual Blank", "reason": "editable baseline defaults"}],
            "preset": {
                "preset_id": "small_balance_safe",
                "name": "Small Balance Safe",
                "settings": {"leverage": 3.0, "grid_count": 6},
                "key_fields": [{"field": "grid_count", "label": "Grid count", "value": 6}],
            },
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-presets/recommend",
            headers=_basic_auth_headers(),
            json={"symbol": "XRPUSDT", "investment": 40.0, "mode": "neutral"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["recommended_preset"] == "small_balance_safe"
    assert payload["confidence"] == "high"
    assert payload["matched_signals"] == ["capital_guard_bias", "min_notional_sensitivity"]
    assert payload["prefill_settings"]["grid_count"] == 6
    assert payload["preset"]["settings"]["grid_count"] == 6


def test_api_bots_save_emits_created_and_override_preset_events_without_persisting_internal_metadata(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    captured = {}

    class _AuditSink:
        def __init__(self):
            self.events = []

        def enabled(self):
            return True

        def record_event(self, payload, **kwargs):
            self.events.append(dict(payload))
            return True

    audit_sink = _AuditSink()

    def _create(payload):
        captured["payload"] = dict(payload)
        saved = dict(payload)
        saved["id"] = "bot-new"
        saved["mode"] = payload.get("mode", "neutral")
        return saved

    class _ConfigWatchdog:
        def record_save_roundtrip(self, submitted, saved, **kwargs):
            return {
                "checked_fields": [],
                "missing_expected_fields": [],
                "missing_in_response": [],
                "missing_in_persisted": [],
                "persisted_mismatches": [],
            }

    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=_create,
        audit_diagnostics_service=audit_sink,
    )
    app_module.bot_preset_service = BotPresetService(
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )
    app_module.config_integrity_watchdog_service = _ConfigWatchdog()

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 100.0,
                "leverage": 3.0,
                "grid_count": 10,
                "_creation_preset_name": "manual_blank",
                "_creation_preset_source": "manual",
                "_creation_preset_recommended": "eth_conservative",
                "_creation_preset_fields": ["leverage", "grid_count", "grid_distribution"],
            },
        )

    assert response.status_code == 200
    assert "_creation_preset_name" not in captured["payload"]
    assert "_creation_preset_source" not in captured["payload"]
    assert "_creation_preset_recommended" not in captured["payload"]
    assert "_creation_preset_fields" not in captured["payload"]
    assert audit_sink.events[-1]["event_type"] == "bot_preset_recommendation_overridden"
    assert audit_sink.events[-1]["preset_name"] == "manual_blank"


def test_api_bots_save_emits_created_from_selected_preset(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    class _AuditSink:
        def __init__(self):
            self.events = []

        def enabled(self):
            return True

        def record_event(self, payload, **kwargs):
            self.events.append(dict(payload))
            return True

    audit_sink = _AuditSink()

    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=lambda payload: {**payload, "id": "bot-new", "mode": payload.get("mode", "neutral")},
        audit_diagnostics_service=audit_sink,
    )
    app_module.bot_preset_service = BotPresetService(
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )
    app_module.config_integrity_watchdog_service = SimpleNamespace(
        record_save_roundtrip=lambda submitted, saved, **kwargs: {
            "checked_fields": [],
            "missing_expected_fields": [],
            "missing_in_response": [],
            "missing_in_persisted": [],
            "persisted_mismatches": [],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 100.0,
                "leverage": 3.0,
                "grid_count": 10,
                "_creation_preset_name": "eth_conservative",
                "_creation_preset_source": "auto",
                "_creation_preset_recommended": "eth_conservative",
                "_creation_preset_fields": ["leverage", "grid_count", "grid_distribution"],
            },
        )

    assert response.status_code == 200
    assert audit_sink.events[-1]["event_type"] == "bot_created_from_preset"
    assert audit_sink.events[-1]["preset_name"] == "eth_conservative"


def test_api_bots_save_blocks_custom_preset_requiring_fresh_session_times_until_fresh_times_are_provided(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    created_payloads = []

    class _AuditSink:
        def __init__(self):
            self.events = []

        def enabled(self):
            return True

        def record_event(self, payload, **kwargs):
            self.events.append(dict(payload))
            return True

    audit_sink = _AuditSink()
    now_dt = datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc)
    custom_service = CustomBotPresetService(
        str(tmp_path / "storage" / "custom_bot_presets.json"),
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: now_dt,
    )
    preset = custom_service.create_preset(
        preset_name="Carry Session Forward",
        fields={
            "leverage": 3,
            "grid_count": 8,
            "session_timer_enabled": True,
            "session_stop_at": "2026-03-12T20:00:00+00:00",
            "session_end_mode": "green_grace_then_stop",
        },
        symbol_hint="ETHUSDT",
        mode_hint="neutral",
    )

    app_module.custom_bot_preset_service = custom_service
    app_module.bot_preset_service = BotPresetService(
        custom_preset_service=custom_service,
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: now_dt,
    )
    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=lambda payload: created_payloads.append(dict(payload)) or {**payload, "id": f"bot-{len(created_payloads)}"},
        audit_diagnostics_service=audit_sink,
    )
    app_module.config_integrity_watchdog_service = SimpleNamespace(
        record_save_roundtrip=lambda submitted, saved, **kwargs: {
            "checked_fields": [],
            "missing_expected_fields": [],
            "missing_in_response": [],
            "missing_in_persisted": [],
            "persisted_mismatches": [],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        missing_times = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 100.0,
                "leverage": 3.0,
                "grid_count": 10,
                "session_timer_enabled": True,
                "session_start_at": None,
                "session_stop_at": None,
                "_creation_preset_name": preset["preset_id"],
                "_creation_preset_source": "manual",
                "_creation_preset_fields": ["session_timer_enabled"],
            },
        )
        stale_times = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 100.0,
                "leverage": 3.0,
                "grid_count": 10,
                "session_timer_enabled": True,
                "session_start_at": "2026-03-12T09:00:00+00:00",
                "session_stop_at": "2026-03-12T10:00:00+00:00",
                "_creation_preset_name": preset["preset_id"],
                "_creation_preset_source": "manual",
                "_creation_preset_fields": ["session_timer_enabled"],
            },
        )

    assert missing_times.status_code == 400
    missing_payload = missing_times.get_json()
    assert missing_payload["blocked_reason"] == "fresh_session_times_required"
    assert missing_payload["preset_id"] == preset["preset_id"]

    assert stale_times.status_code == 400
    stale_payload = stale_times.get_json()
    assert stale_payload["blocked_reason"] == "fresh_session_times_required"
    assert created_payloads == []

    with flask_app.test_client() as client:
        valid_times = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 100.0,
                "leverage": 3.0,
                "grid_count": 10,
                "session_timer_enabled": True,
                "session_start_at": "2026-03-12T13:00:00+00:00",
                "session_stop_at": "2026-03-12T14:30:00+00:00",
                "_creation_preset_name": preset["preset_id"],
                "_creation_preset_source": "manual",
                "_creation_preset_fields": ["session_timer_enabled"],
            },
        )

    assert valid_times.status_code == 200
    assert len(created_payloads) == 1
    assert created_payloads[0]["session_start_at"] == "2026-03-12T13:00:00+00:00"
    assert created_payloads[0]["session_stop_at"] == "2026-03-12T14:30:00+00:00"


def test_api_bots_save_blocks_new_bot_when_min_qty_fails_even_if_min_notional_passes(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    created_payloads = []
    app_module.client = _SizingClient(mark_price="4000", last_price="3995", min_qty="0.02", min_notional="5")
    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=lambda payload: created_payloads.append(dict(payload)) or {**payload, "id": "bot-new"},
        audit_diagnostics_service=None,
    )
    app_module.config_integrity_watchdog_service = SimpleNamespace(
        record_save_roundtrip=lambda submitted, saved, **kwargs: {
            "checked_fields": [],
            "missing_expected_fields": [],
            "missing_in_response": [],
            "missing_in_persisted": [],
            "persisted_mismatches": [],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 120.0,
                "leverage": 3.0,
                "grid_count": 8,
            },
        )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["blocked_reason"] == "below_min_qty"
    assert payload["validation_type"] == "exchange_order_sizing"
    assert payload["estimated_per_order_notional"] == 45.0
    assert payload["min_notional"] == 5.0
    assert payload["min_qty"] == 0.02
    assert payload["effective_min_order_notional"] == 80.0
    assert payload["sizing_validation"]["min_notional_passes"] is True
    assert payload["sizing_validation"]["min_qty_passes"] is False
    assert created_payloads == []


def test_api_bots_save_allows_new_bot_when_exchange_order_sizing_is_valid(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    created_payloads = []
    app_module.client = _SizingClient(mark_price="4000", last_price="3995", min_qty="0.02", min_notional="5")
    app_module.bot_storage = SimpleNamespace(get_bot=lambda bot_id: None)
    app_module.bot_manager = SimpleNamespace(
        create_or_update_bot=lambda payload: created_payloads.append(dict(payload)) or {**payload, "id": "bot-new"},
        audit_diagnostics_service=None,
    )
    app_module.config_integrity_watchdog_service = SimpleNamespace(
        record_save_roundtrip=lambda submitted, saved, **kwargs: {
            "checked_fields": [],
            "missing_expected_fields": [],
            "missing_in_response": [],
            "missing_in_persisted": [],
            "persisted_mismatches": [],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots",
            headers={**_basic_auth_headers(), "X-Bot-Config-Path": "main"},
            json={
                "symbol": "ETHUSDT",
                "mode": "neutral",
                "range_mode": "fixed",
                "lower_price": 1800.0,
                "upper_price": 2100.0,
                "investment": 320.0,
                "leverage": 3.0,
                "grid_count": 8,
            },
        )

    assert response.status_code == 200
    assert len(created_payloads) == 1
