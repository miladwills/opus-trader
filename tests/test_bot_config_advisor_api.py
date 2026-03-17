import base64
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.bot_config_advisor_service import BotConfigAdvisorApplyBlockedError
from services.bot_triage_action_service import BotTriageSettingsConflictError


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


def test_api_bot_config_advisor_returns_compact_payload(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_config_advisor_service = SimpleNamespace(
        build_snapshot=lambda **kwargs: {
            "generated_at": "2026-03-12T12:00:00+00:00",
            "total_bots": 1,
            "summary_counts": {
                "REDUCE_RISK": 1,
                "WIDEN_STRUCTURE": 0,
                "REVIEW_MANUALLY": 0,
                "KEEP_CURRENT": 0,
            },
            "items": [
                {
                    "bot_id": "bot-1",
                    "symbol": "BTCUSDT",
                    "mode": "long",
                    "tuning_verdict": "REDUCE_RISK",
                    "confidence": "high",
                    "current_settings": {"leverage": 6.0, "grid_count": 15},
                    "recommended_settings": {"leverage": 3.0, "grid_count": 8},
                    "reasons": ["repeated insufficient margin", "capital compression active"],
                    "rationale": "Lower size-related settings only where repeated blocker evidence is already present.",
                    "suggested_preset": "reduce_risk",
                    "source_signals": {"triage_verdict": "REDUCE", "runtime_status": "running"},
                    "generated_at": "2026-03-12T12:00:00+00:00",
                }
            ],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/bot-config-advisor", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["generated_at"] == "2026-03-12T12:00:00+00:00"
    assert payload["summary_counts"]["REDUCE_RISK"] == 1
    assert payload["items"][0]["tuning_verdict"] == "REDUCE_RISK"
    assert payload["items"][0]["current_settings"]["leverage"] == 6.0
    assert payload["items"][0]["recommended_settings"]["leverage"] == 3.0
    assert payload["items"][0]["suggested_preset"] == "reduce_risk"


def test_api_bot_config_advisor_handles_missing_optional_diagnostics(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    from services.bot_config_advisor_service import BotConfigAdvisorService
    from services.bot_triage_service import BotTriageService

    app_module.bot_config_advisor_service = BotConfigAdvisorService(
        bot_triage_service=BotTriageService(watchdog_hub_service=None),
    )
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
        response = client.get("/api/bot-config-advisor", headers=_basic_auth_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stale_data"] is True
    assert payload["error"] == "bots_runtime_bridge_unavailable"
    assert payload["items"][0]["bot_id"] == "bot-2"
    assert payload["items"][0]["tuning_verdict"] == "REVIEW_MANUALLY"


def test_api_bot_config_advisor_apply_preview(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_config_advisor_service = SimpleNamespace(
        preview_apply=lambda bot_id, runtime_bot=None: {
            "ok": True,
            "bot_id": bot_id,
            "preview": {
                "supports_apply": True,
                "is_flat_now": True,
                "applicable_fields": ["leverage", "grid_count"],
                "advisory_only_fields": ["range_posture"],
            },
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-config-advisor/bot-1/apply",
            headers=_basic_auth_headers(),
            json={"preview": True},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["preview"]["applicable_fields"] == ["leverage", "grid_count"]
    assert payload["preview"]["advisory_only_fields"] == ["range_posture"]


def test_api_bot_config_advisor_apply_handles_blocked_and_conflict(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    def _blocked(bot_id, incoming_settings_version, runtime_bot=None, ui_path="config_advisor"):
        raise BotConfigAdvisorApplyBlockedError(
            bot_id=bot_id,
            blocked_reason="requires_flat_state",
            payload={
                "ok": False,
                "bot_id": bot_id,
                "blocked_reason": "requires_flat_state",
                "applied_fields": [],
                "skipped_advisory_fields": ["range_posture"],
            },
        )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    app_module.bot_config_advisor_service = SimpleNamespace(
        apply_recommendation=_blocked,
    )
    with flask_app.test_client() as client:
        blocked_response = client.post(
            "/api/bot-config-advisor/bot-1/apply",
            headers=_basic_auth_headers(),
            json={"settings_version": 11},
        )

    assert blocked_response.status_code == 409
    assert blocked_response.get_json()["blocked_reason"] == "requires_flat_state"

    def _conflict(bot_id, incoming_settings_version, runtime_bot=None, ui_path="config_advisor"):
        raise BotTriageSettingsConflictError(
            bot_id=bot_id,
            current_settings_version=9,
            incoming_settings_version=8,
            conflict_reason="stale_incoming_version",
        )

    app_module.bot_config_advisor_service = SimpleNamespace(
        apply_recommendation=_conflict,
    )
    with flask_app.test_client() as client:
        conflict_response = client.post(
            "/api/bot-config-advisor/bot-1/apply",
            headers=_basic_auth_headers(),
            json={"settings_version": 8},
        )

    assert conflict_response.status_code == 409
    payload = conflict_response.get_json()
    assert payload["error"] == "settings_version_conflict"
    assert payload["blocked_reason"] == "settings_version_conflict"


def test_api_bot_config_advisor_apply_success(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_config_advisor_service = SimpleNamespace(
        apply_recommendation=lambda bot_id, incoming_settings_version, runtime_bot=None, ui_path="config_advisor": {
            "ok": True,
            "bot_id": bot_id,
            "applied_fields": ["leverage", "grid_count"],
            "skipped_advisory_fields": ["range_posture"],
            "new_settings_version": 12,
            "applied_at": "2026-03-12T12:00:00+00:00",
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-config-advisor/bot-1/apply",
            headers=_basic_auth_headers(),
            json={"settings_version": 11},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["applied_fields"] == ["leverage", "grid_count"]


def test_api_bot_config_advisor_queue_apply_success(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_config_advisor_service = SimpleNamespace(
        queue_apply=lambda bot_id, runtime_bot=None: {
            "ok": True,
            "bot_id": bot_id,
            "state": "waiting_for_flat",
            "queued_fields": ["leverage", "grid_count"],
            "advisory_only_fields": ["range_posture"],
            "blocked_reason": None,
            "queued_at": "2026-03-12T12:00:00+00:00",
            "applied_at": None,
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-config-advisor/bot-1/queue-apply",
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["state"] == "waiting_for_flat"
    assert payload["queued_fields"] == ["leverage", "grid_count"]


def test_api_bot_config_advisor_queue_apply_handles_blocked(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)

    def _blocked(bot_id, runtime_bot=None):
        raise BotConfigAdvisorApplyBlockedError(
            bot_id=bot_id,
            blocked_reason="already_flat_apply_now",
            payload={
                "ok": False,
                "bot_id": bot_id,
                "state": "blocked",
                "queued_fields": ["leverage"],
                "advisory_only_fields": ["range_posture"],
                "blocked_reason": "already_flat_apply_now",
                "queued_at": None,
            },
        )

    app_module.bot_config_advisor_service = SimpleNamespace(queue_apply=_blocked)

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-config-advisor/bot-1/queue-apply",
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["blocked_reason"] == "already_flat_apply_now"
    assert payload["state"] == "blocked"


def test_api_bot_config_advisor_cancel_queued_apply(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_config_advisor_service = SimpleNamespace(
        cancel_queued_apply=lambda bot_id: {
            "ok": True,
            "bot_id": bot_id,
            "state": "canceled",
            "queued_fields": ["leverage"],
            "advisory_only_fields": ["range_posture"],
            "blocked_reason": None,
            "queued_at": "2026-03-12T12:00:00+00:00",
            "applied_at": None,
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bot-config-advisor/bot-1/cancel-queued-apply",
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["state"] == "canceled"


def test_api_bot_config_advisor_lists_queued_applies(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.bot_config_advisor_service = SimpleNamespace(
        list_queued_applies=lambda: {
            "generated_at": "2026-03-12T12:00:00+00:00",
            "total": 1,
            "items": [
                {
                    "bot_id": "bot-1",
                    "state": "waiting_for_flat",
                    "queued_fields": ["leverage", "grid_count"],
                    "advisory_only_fields": ["range_posture"],
                    "blocked_reason": None,
                    "queued_at": "2026-03-12T12:00:00+00:00",
                    "applied_at": None,
                    "updated_at": "2026-03-12T12:00:00+00:00",
                }
            ],
        }
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get(
            "/api/bot-config-advisor/queued-applies",
            headers=_basic_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["items"][0]["state"] == "waiting_for_flat"
