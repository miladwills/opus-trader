import base64
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.bot_triage_action_service import BotTriageSettingsConflictError
from services.bot_triage_service import BotTriageService


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
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()
        app_module.DASHBOARD_SNAPSHOT_FUTURES.clear()
    return app_module


def test_api_bot_triage_returns_compact_payload(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_triage_service = SimpleNamespace(
        build_snapshot=lambda **kwargs: {
            "generated_at": "2026-03-12T12:00:00+00:00",
            "total_bots": 1,
            "summary_counts": {"PAUSE": 1, "REDUCE": 0, "REVIEW": 0, "KEEP": 0},
            "items": [
                {
                    "bot_id": "bot-1",
                    "symbol": "BTCUSDT",
                    "mode": "long",
                    "verdict": "PAUSE",
                    "severity": "high",
                    "reasons": ["repeated insufficient margin", "strong loss asymmetry"],
                    "suggested_action": "pause bot and inspect repeated blockers",
                    "source_signals": {"runtime_status": "running"},
                    "generated_at": "2026-03-12T12:00:00+00:00",
                }
            ],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/bot-triage", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["generated_at"] == "2026-03-12T12:00:00+00:00"
    assert payload["total_bots"] == 1
    assert payload["summary_counts"]["PAUSE"] == 1
    assert payload["items"][0]["bot_id"] == "bot-1"
    assert payload["items"][0]["verdict"] == "PAUSE"
    assert payload["items"][0]["severity"] == "high"
    assert payload["items"][0]["reasons"] == [
        "repeated insufficient margin",
        "strong loss asymmetry",
    ]


def test_api_bot_triage_handles_missing_optional_diagnostics(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_triage_service = BotTriageService(watchdog_hub_service=None)
    monkeypatch.setattr(
        app_module,
        "_get_runtime_bots_snapshot",
        lambda: {
            "bots": [
                {
                    "id": "bot-2",
                    "symbol": "ETHUSDT",
                    "mode": "short",
                    "status": "running",
                    "runtime_snapshot_stale": True,
                }
            ],
            "stale_data": True,
            "error": "bots_runtime_bridge_unavailable",
        },
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/bot-triage", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stale_data"] is True
    assert payload["error"] == "bots_runtime_bridge_unavailable"
    assert payload["items"][0]["bot_id"] == "bot-2"
    assert payload["items"][0]["verdict"] == "REVIEW"


def test_api_bot_triage_apply_preset_preview(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_triage_action_service = SimpleNamespace(
        preview_preset=lambda bot_id, preset: {
            "preset": preset,
            "title": "Reduce Risk Preset",
            "summary_lines": ["Leverage 6 -> 3", "Grid count 15 -> 8"],
            "changed_fields": [
                {"field": "leverage", "from": 6, "to": 3},
                {"field": "grid_count", "from": 15, "to": 8},
            ],
            "no_changes": False,
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-triage/bot-1/apply-preset",
            headers=_basic_auth_headers(),
            json={"preset": "reduce_risk", "preview": True},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bot_id"] == "bot-1"
    assert payload["preview"]["title"] == "Reduce Risk Preset"
    assert payload["preview"]["changed_fields"][0]["field"] == "leverage"


def test_api_bot_triage_apply_preset_rejects_settings_conflict(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    def _raise_conflict(*args, **kwargs):
        raise BotTriageSettingsConflictError(
            bot_id="bot-1",
            current_settings_version=9,
            incoming_settings_version=8,
            conflict_reason="stale_incoming_version",
        )

    app_module.bot_triage_action_service = SimpleNamespace(apply_preset=_raise_conflict)

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-triage/bot-1/apply-preset",
            headers=_basic_auth_headers(),
            json={"preset": "reduce_risk", "settings_version": 8},
        )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error"] == "settings_version_conflict"
    assert payload["current_settings_version"] == 9
    assert payload["incoming_settings_version"] == 8


def test_api_bot_triage_pause_dismiss_and_snooze_routes(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_triage_action_service = SimpleNamespace(
        pause_action=lambda bot_id, cancel_pending_requested: {
            "bot": {"id": bot_id, "status": "paused"},
            "cancel_pending_requested": bool(cancel_pending_requested),
        },
        dismiss=lambda bot_id, verdict: {"bot_id": bot_id, "verdict": verdict},
        snooze=lambda bot_id, verdict, duration: {
            "bot_id": bot_id,
            "verdict": verdict,
            "duration": duration,
            "snooze_until": "2026-03-12T13:00:00+00:00",
        },
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        pause_response = client.post(
            "/api/bot-triage/bot-1/pause-action",
            headers=_basic_auth_headers(),
            json={"cancel_pending": True},
        )
        dismiss_response = client.post(
            "/api/bot-triage/bot-1/dismiss",
            headers=_basic_auth_headers(),
            json={"verdict": "KEEP"},
        )
        snooze_response = client.post(
            "/api/bot-triage/bot-1/snooze",
            headers=_basic_auth_headers(),
            json={"verdict": "KEEP", "duration": "1h"},
        )

    assert pause_response.status_code == 200
    assert pause_response.get_json()["cancel_pending_requested"] is True
    assert dismiss_response.status_code == 200
    assert dismiss_response.get_json()["verdict"] == "KEEP"
    assert snooze_response.status_code == 200
    assert snooze_response.get_json()["duration"] == "1h"
