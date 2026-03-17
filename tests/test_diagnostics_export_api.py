import base64
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.diagnostics_export_service import DiagnosticsExportService


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


def _response_json_payload(response):
    return json.loads(response.get_data(as_text=True))


def test_api_export_ai_layer_writes_latest_and_archive(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.ai_advisor_analytics_service = SimpleNamespace(
        get_recent_reviews=lambda **kwargs: {"decisions": [{"decision_id": "adv-1"}]},
        get_summary=lambda **kwargs: {"summary": {"total_decisions": 1}},
        get_calibration=lambda **kwargs: {"calibration": {"bucket_count": 2}},
    )
    app_module.advisor_replay_analysis_service = SimpleNamespace(
        get_recent=lambda **kwargs: {"recent": [{"replay_id": "rep-1"}]},
        get_summary=lambda **kwargs: {"summary": {"tracked_symbols": 1}},
        get_by_symbol=lambda **kwargs: {"rows": []},
        get_by_mode=lambda **kwargs: {"rows": []},
    )
    app_module.grid_bot_service = SimpleNamespace(
        ai_advisor_service=SimpleNamespace(get_health=lambda: {"status": "ok"})
    )
    app_module.bot_storage = SimpleNamespace(
        list_bots=lambda: [
            {
                "id": "bot-1",
                "ai_advisor_enabled": True,
                "ai_advisor_call_count": 4,
                "ai_advisor_error_count": 1,
                "ai_advisor_timeout_count": 0,
                "ai_advisor_cached_hits": 2,
                "ai_advisor_last_error": "",
            }
        ]
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/export/ai-layer", headers=_basic_auth_headers())

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert "attachment;" in response.headers["Content-Disposition"]
    assert response.headers["X-Opus-Export-Type"] == "ai_layer"
    assert response.headers["X-Opus-Latest-Path"] == "storage/exports/ai_layer/latest.json"
    assert int(response.headers["X-Opus-Bytes-Written"]) > 0

    export_dir = tmp_path / "storage" / "exports" / "ai_layer"
    latest_path = export_dir / "latest.json"
    archive_files = sorted(path for path in export_dir.glob("*.json") if path.name != "latest.json")

    assert latest_path.exists()
    assert len(archive_files) == 1

    payload = _response_json_payload(response)
    assert set(payload) == {"generated_at", "export_type", "app_name", "source", "data", "performance_baseline"}
    assert payload["export_type"] == "ai_layer"
    assert payload["data"]["ai_advisor_recent"]["decisions"][0]["decision_id"] == "adv-1"
    assert payload["data"]["ai_advisor_summary"]["summary"]["total_decisions"] == 1
    assert payload["data"]["ai_advisor_calibration"]["calibration"]["bucket_count"] == 2
    assert payload["data"]["ai_advisor_health"]["health"]["bot_aggregate"]["enabled_bot_count"] == 1
    assert payload["data"]["ai_advisor_replay_recent"]["recent"][0]["replay_id"] == "rep-1"
    assert payload["data"]["ai_advisor_replay_summary"]["summary"]["tracked_symbols"] == 1


def test_api_export_watchdog_writes_latest_and_archive(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app_module,
        "_get_runtime_bots_snapshot",
        lambda: {"bots": [{"id": "bot-1", "symbol": "BTCUSDT"}], "stale_data": False},
    )
    monkeypatch.setattr(
        app_module,
        "_build_watchdog_hub_payload",
        lambda **kwargs: {
            "overview": {"total_active_issues": 1},
            "active_issues": [{"watchdog_type": "signal_drift"}],
            "recent_events": [],
            "issue_registry": [{"is_active": True}],
        },
    )
    monkeypatch.setattr(
        app_module,
        "_build_bot_status_payload",
        lambda: {"running": True, "bots": {"total_bots": 1}},
    )
    monkeypatch.setattr(
        app_module,
        "_get_summary_snapshot",
        lambda: {"account": {"equity": 125.5}},
    )
    app_module.watchdog_hub_service = SimpleNamespace(
        audit_diagnostics_service=SimpleNamespace(
            get_summary_snapshot=lambda: {
                "updated_at": "2026-03-12T09:15:00+00:00",
                "rolling_windows_sec": {"last_15m": 900},
                "health_status_counts": {"WATCH": 1},
                "rollups": {
                    "top_config_issue_types": [{"key": "config_roundtrip_mismatch", "count": 2}],
                    "top_config_issue_ui_paths": [{"key": "main", "count": 2}],
                    "top_bots_by_config_integrity_issue": [{"key": "bot-1", "count": 2}],
                },
            },
            get_review_snapshot=lambda: {
                "updated_at": "2026-03-12T09:15:00+00:00",
                "rolling_windows_sec": {"last_15m": 900},
                "bots": {"bot-1": {"config_integrity_state": "watch"}},
            },
        )
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        export_response = client.get("/api/export/watchdog", headers=_basic_auth_headers())
        watchdog_response = client.get("/api/watchdog-center", headers=_basic_auth_headers())

    assert export_response.status_code == 200
    assert watchdog_response.status_code == 200
    assert watchdog_response.get_json()["overview"]["total_active_issues"] == 1

    assert "attachment;" in export_response.headers["Content-Disposition"]
    assert export_response.headers["X-Opus-Export-Type"] == "watchdog"
    assert export_response.headers["X-Opus-Latest-Path"] == "storage/exports/watchdog/latest.json"

    export_dir = tmp_path / "storage" / "exports" / "watchdog"
    latest_path = export_dir / "latest.json"
    archive_files = sorted(path for path in export_dir.glob("*.json") if path.name != "latest.json")

    assert latest_path.exists()
    assert len(archive_files) == 1

    payload = _response_json_payload(export_response)
    assert set(payload) == {"generated_at", "export_type", "app_name", "source", "data", "performance_baseline"}
    assert payload["export_type"] == "watchdog"
    assert payload["data"]["watchdog_center"]["overview"]["total_active_issues"] == 1
    assert payload["data"]["bot_status"]["bots"]["total_bots"] == 1
    assert payload["data"]["bots_runtime"]["bots"][0]["symbol"] == "BTCUSDT"
    assert payload["data"]["summary"]["account"]["equity"] == 125.5
    assert payload["data"]["config_integrity_report"]["rollups"]["top_config_issue_types"][0]["key"] == "config_roundtrip_mismatch"
    assert payload["data"]["audit_review_snapshot"]["bots"]["bot-1"]["config_integrity_state"] == "watch"


def test_diagnostics_export_service_prunes_old_archives_and_keeps_latest(tmp_path):
    base_dir = tmp_path / "storage" / "exports"
    export_dir = base_dir / "ai_layer"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "latest.json").write_text("{}", encoding="utf-8")
    for name in (
        "20260309T010000_000000Z.json",
        "20260310T010000_000000Z.json",
        "20260311T010000_000000Z.json",
    ):
        (export_dir / name).write_text("{}", encoding="utf-8")

    service = DiagnosticsExportService(base_dir=str(base_dir), archive_retention=2)
    service.write_export(
        "ai_layer",
        {
            "generated_at": "2026-03-12T10:00:00+00:00",
            "export_type": "ai_layer",
            "app_name": "Opus Trader",
            "source": "server_export",
            "data": {"sample": True},
        },
        generated_at="2026-03-12T10:00:00+00:00",
    )

    assert (export_dir / "latest.json").exists()
    archive_files = sorted(path.name for path in export_dir.glob("*.json") if path.name != "latest.json")
    assert archive_files == [
        "20260311T010000_000000Z.json",
        "20260312T100000_000000Z.json",
    ]


def test_diagnostics_export_service_serializes_nested_datetime_values(tmp_path):
    base_dir = tmp_path / "storage" / "exports"
    service = DiagnosticsExportService(base_dir=str(base_dir), archive_retention=2)
    event_ts = datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc)

    service.write_export(
        "ai_layer",
        {
            "generated_at": "2026-03-12T10:31:00+00:00",
            "export_type": "ai_layer",
            "app_name": "Opus Trader",
            "source": "server_export",
            "data": {
                "ai_advisor_recent": {
                    "decisions": [
                        {"decision_id": "adv-live", "recorded_at": event_ts},
                    ]
                },
                "metadata": {
                    "timestamps": [event_ts],
                },
            },
        },
    )

    latest_path = base_dir / "ai_layer" / "latest.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert payload["data"]["ai_advisor_recent"]["decisions"][0]["recorded_at"] == "2026-03-12T10:30:00+00:00"
    assert payload["data"]["metadata"]["timestamps"] == ["2026-03-12T10:30:00+00:00"]


def test_diagnostics_export_download_filename_includes_type_and_baseline_epoch(tmp_path):
    service = DiagnosticsExportService(base_dir=str(tmp_path / "storage" / "exports"))

    filename = service.build_download_filename(
        "all_diagnostics",
        generated_at="2026-03-12T11:45:00+00:00",
        payload={
            "performance_baseline": {
                "effective": {
                    "scope": "global",
                    "epoch_id": "baseline-2026-q1",
                }
            }
        },
    )

    assert filename == "opus-trader-all-diagnostics-global-baseline-2026-q1-20260312T114500Z.json"


def test_api_export_all_diagnostics_includes_ai_and_watchdog(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app_module,
        "_build_ai_layer_export_payload",
        lambda generated_at=None: {
            "generated_at": generated_at or "2026-03-12T11:00:00+00:00",
            "export_type": "ai_layer",
            "app_name": "Opus Trader",
            "source": "server_export",
            "data": {"ai_advisor_summary": {"summary": {"total_decisions": 2}}},
        },
    )
    monkeypatch.setattr(
        app_module,
        "_build_watchdog_export_payload",
        lambda generated_at=None: {
            "generated_at": generated_at or "2026-03-12T11:00:00+00:00",
            "export_type": "watchdog",
            "app_name": "Opus Trader",
            "source": "server_export",
            "data": {"watchdog_center": {"overview": {"total_active_issues": 3}}},
        },
    )

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        response = client.get("/api/export/all-diagnostics", headers=_basic_auth_headers())

    assert response.status_code == 200
    assert "attachment;" in response.headers["Content-Disposition"]
    assert response.headers["X-Opus-Export-Type"] == "all_diagnostics"
    assert "opus-trader-all-diagnostics-" in response.headers["Content-Disposition"]

    latest_path = tmp_path / "storage" / "exports" / "all_diagnostics" / "latest.json"
    payload = _response_json_payload(response)
    assert payload["data"]["ai_layer"]["ai_advisor_summary"]["summary"]["total_decisions"] == 2
    assert payload["data"]["watchdog"]["watchdog_center"]["overview"]["total_active_issues"] == 3


def test_ai_export_handles_empty_optional_sections_and_existing_endpoint_still_works(
    monkeypatch,
    tmp_path,
):
    app_module = _load_app_module(monkeypatch, tmp_path)
    app_module.ai_advisor_analytics_service = None
    app_module.advisor_replay_analysis_service = None
    app_module.grid_bot_service = SimpleNamespace(ai_advisor_service=None)
    app_module.bot_storage = SimpleNamespace(list_bots=lambda: [])

    flask_app = app_module.app
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        export_response = client.get("/api/export/ai-layer", headers=_basic_auth_headers())
        summary_response = client.get("/api/ai-advisor/summary", headers=_basic_auth_headers())

    assert export_response.status_code == 200
    assert summary_response.status_code == 200
    assert summary_response.get_json() == {"summary": {}}

    latest_path = tmp_path / "storage" / "exports" / "ai_layer" / "latest.json"
    payload = _response_json_payload(export_response)
    assert payload["data"]["ai_advisor_recent"] == {"decisions": []}
    assert payload["data"]["ai_advisor_summary"] == {"summary": {}}
    assert payload["data"]["ai_advisor_calibration"] == {"calibration": {}}
    assert payload["data"]["ai_advisor_health"] == {"health": {}}
    assert payload["data"]["ai_advisor_replay_recent"] == {"recent": []}
    assert payload["data"]["ai_advisor_replay_summary"] == {"summary": {}}
