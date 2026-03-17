import base64
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.diagnostics_export_service import DiagnosticsExportService
from services.performance_baseline_service import PerformanceBaselineService


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


def _baseline_service(tmp_path):
    return PerformanceBaselineService(
        file_path=str(tmp_path / "storage" / "performance_baselines.json"),
        diagnostics_export_service=DiagnosticsExportService(
            base_dir=str(tmp_path / "storage" / "exports"),
            archive_retention=5,
        ),
    )


def test_api_global_performance_baseline_reset_returns_archive_metadata(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.performance_baseline_service = _baseline_service(tmp_path)
    app_module.pnl_service = SimpleNamespace(update_bots_realized_pnl=lambda: None)
    app_module.watchdog_hub_service = SimpleNamespace(reset_scope=lambda **kwargs: {"ok": True})
    app_module.ai_advisor_analytics_service = SimpleNamespace(refresh_snapshot=lambda force=False: {})
    app_module.advisor_replay_analysis_service = SimpleNamespace(refresh_snapshot=lambda force=False: {})
    monkeypatch.setattr(
        app_module,
        "_build_performance_reset_archive_snapshot",
        lambda **kwargs: {"summary": {"net_pnl": -12.0}},
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/performance-baseline/reset",
            headers=_basic_auth_headers(),
            json={"note": "fresh comparison window"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["scope"] == "global"
    assert payload["archive_path"].startswith("storage/exports/performance_reset/")
    assert payload["performance_baseline"]["effective"]["scope"] == "global"
    assert payload["warnings"][0].startswith("Raw trade logs")


def test_api_bot_performance_baseline_reset_is_scoped_to_target_bot(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.performance_baseline_service = _baseline_service(tmp_path)
    app_module.bot_storage = SimpleNamespace(
        get_bot=lambda bot_id: {"id": bot_id, "symbol": "ETHUSDT", "mode": "long"}
        if bot_id == "bot-7"
        else None
    )
    app_module.pnl_service = SimpleNamespace(update_bots_realized_pnl=lambda: None)
    reset_calls = []
    app_module.watchdog_hub_service = SimpleNamespace(
        reset_scope=lambda **kwargs: reset_calls.append(kwargs) or {"ok": True}
    )
    app_module.ai_advisor_analytics_service = SimpleNamespace(refresh_snapshot=lambda force=False: {})
    app_module.advisor_replay_analysis_service = SimpleNamespace(refresh_snapshot=lambda force=False: {})
    monkeypatch.setattr(
        app_module,
        "_build_performance_reset_archive_snapshot",
        lambda **kwargs: {"runtime_bot": {"id": kwargs.get("bot_id")}},
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.post(
            "/api/bots/bot-7/performance-baseline/reset",
            headers=_basic_auth_headers(),
            json={"note": "restart bot evaluation"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["scope"] == "bot"
    assert payload["bot"]["id"] == "bot-7"
    assert payload["performance_baseline"]["bot"]["bot_id"] == "bot-7"
    assert payload["performance_baseline"]["effective"]["scope"] == "bot"
    assert reset_calls == [{"bot_id": "bot-7"}]
