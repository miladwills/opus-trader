import base64
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from services.audit_diagnostics_service import AuditDiagnosticsService
from services.watchdog_hub_service import WatchdogHubService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _record_watchdog_event(audit_service, hub_service, payload):
    assert audit_service.record_event(payload, throttle_key=payload["reason"], throttle_sec=0) is True
    assert hub_service.record_watchdog_event(payload) is True


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
    with app_module.DASHBOARD_SNAPSHOT_LOCK:
        app_module.DASHBOARD_SNAPSHOT_CACHE.clear()
        app_module.DASHBOARD_SNAPSHOT_FUTURES.clear()
    return app_module


def test_watchdog_hub_tracks_active_issue_and_runtime_resolution(monkeypatch, tmp_path):
    now_iso = datetime.now(timezone.utc).isoformat()
    audit_path = tmp_path / "audit.jsonl"
    audit_service = AuditDiagnosticsService(str(audit_path))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))

    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "signal_drift",
        "severity": "WARN",
        "timestamp": now_iso,
        "bot_id": "bot-1",
        "symbol": "BTCUSDT",
        "reason": "ready_but_runtime_blocked",
        "compact_metrics": {"runtime_blocker": "qty_below_min"},
    }
    _record_watchdog_event(audit_service, hub_service, payload)

    active_snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "entry_ready_status": "ready",
                "_small_capital_block_opening_orders": True,
                "last_skip_reason": "qty_below_min",
            }
        ],
        include_registry=True,
    )
    assert active_snapshot["overview"]["total_active_issues"] == 1
    assert active_snapshot["active_issues"][0]["reason"] == "ready_but_runtime_blocked"
    assert active_snapshot["active_issues"][0]["is_active"] is True

    resolved_snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-1",
                "symbol": "BTCUSDT",
                "entry_ready_status": "watch",
            }
        ],
        include_registry=True,
    )
    assert resolved_snapshot["overview"]["total_active_issues"] == 0
    assert resolved_snapshot["recent_events"][0]["reason"] == "ready_but_runtime_blocked"
    assert resolved_snapshot["issue_registry"][0]["is_active"] is False
    assert resolved_snapshot["issue_registry"][0]["resolution_reason"] == "runtime_cleared"


def test_watchdog_hub_expires_non_runtime_warning_but_keeps_history(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_service = AuditDiagnosticsService(str(audit_path))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))
    monkeypatch.setattr(
        WatchdogHubService,
        "_active_ttl_sec",
        classmethod(lambda cls, watchdog_type: 60),
    )
    monkeypatch.setattr(
        WatchdogHubService,
        "_now",
        staticmethod(lambda: WatchdogHubService._parse_ts("2026-03-11T10:20:00+00:00")),
    )

    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "loss_asymmetry",
        "severity": "WARN",
        "timestamp": "2026-03-11T10:00:00+00:00",
        "symbol": "ETHUSDT",
        "reason": "losses_dwarf_wins",
        "compact_metrics": {"net_pnl": -12.5, "win_rate": 60.0},
    }
    _record_watchdog_event(audit_service, hub_service, payload)

    snapshot = hub_service.build_snapshot(
        include_registry=True,
        filters={"recent_window_sec": 10**9},
    )
    assert snapshot["overview"]["total_active_issues"] == 0
    assert snapshot["recent_events"][0]["reason"] == "losses_dwarf_wins"
    assert snapshot["issue_registry"][0]["is_active"] is False
    assert snapshot["issue_registry"][0]["resolution_reason"] == "expired"


def test_watchdog_hub_resolves_missing_bot_scoped_issue_after_grace(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_service = AuditDiagnosticsService(str(audit_path))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))
    monkeypatch.setattr(
        WatchdogHubService,
        "_now",
        staticmethod(lambda: WatchdogHubService._parse_ts("2026-03-11T10:20:00+00:00")),
    )
    monkeypatch.setattr(WatchdogHubService, "active_grace_sec", staticmethod(lambda: 60))

    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "loss_asymmetry",
        "severity": "ERROR",
        "timestamp": "2026-03-11T10:00:00+00:00",
        "bot_id": "bot-1",
        "symbol": "BTCUSDT",
        "reason": "high_win_rate_negative_pnl",
        "compact_metrics": {"net_pnl": -0.7},
    }
    _record_watchdog_event(audit_service, hub_service, payload)
    refreshed_payload = dict(payload)
    refreshed_payload["timestamp"] = "2026-03-11T10:19:00+00:00"
    _record_watchdog_event(audit_service, hub_service, refreshed_payload)

    snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "real-bot",
                "symbol": "SUIUSDT",
            }
        ],
        include_registry=True,
        filters={"recent_window_sec": 10**9},
    )
    assert snapshot["overview"]["total_active_issues"] == 0
    assert snapshot["recent_events"][0]["reason"] == "high_win_rate_negative_pnl"
    assert snapshot["issue_registry"][0]["is_active"] is False
    assert snapshot["issue_registry"][0]["resolution_reason"] == "bot_missing"


def test_watchdog_hub_keeps_symbol_scope_issue_active_without_bot_id(monkeypatch, tmp_path):
    now_iso = "2026-03-11T10:00:00+00:00"
    audit_path = tmp_path / "audit.jsonl"
    audit_service = AuditDiagnosticsService(str(audit_path))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))
    monkeypatch.setattr(
        WatchdogHubService,
        "_now",
        staticmethod(lambda: WatchdogHubService._parse_ts("2026-03-11T10:05:00+00:00")),
    )
    monkeypatch.setattr(WatchdogHubService, "active_grace_sec", staticmethod(lambda: 60))
    monkeypatch.setattr(
        WatchdogHubService,
        "_active_ttl_sec",
        classmethod(lambda cls, watchdog_type: 1800),
    )

    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "pnl_attribution",
        "severity": "WARN",
        "timestamp": now_iso,
        "symbol": "SOLUSDT",
        "reason": "attribution_gap",
        "compact_metrics": {"unresolved_share": 0.8},
    }
    _record_watchdog_event(audit_service, hub_service, payload)

    snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "real-bot",
                "symbol": "SUIUSDT",
            }
        ],
        include_registry=True,
        filters={"recent_window_sec": 10**9},
    )
    assert snapshot["overview"]["total_active_issues"] == 1
    assert snapshot["active_issues"][0]["bot_id"] is None
    assert snapshot["active_issues"][0]["reason"] == "attribution_gap"
    assert snapshot["issue_registry"][0]["is_active"] is True


def test_watchdog_hub_resolves_bot_scoped_issue_when_bot_symbol_changes(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    audit_service = AuditDiagnosticsService(str(audit_path))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))
    monkeypatch.setattr(
        WatchdogHubService,
        "_now",
        staticmethod(lambda: WatchdogHubService._parse_ts("2026-03-11T10:20:00+00:00")),
    )
    monkeypatch.setattr(WatchdogHubService, "active_grace_sec", staticmethod(lambda: 60))

    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "exit_stack",
        "severity": "WARN",
        "timestamp": "2026-03-11T10:00:00+00:00",
        "bot_id": "bot-live",
        "symbol": "ETHUSDT",
        "reason": "forced_exit_concentration",
        "compact_metrics": {"forced_exit_share": 1.0},
    }
    _record_watchdog_event(audit_service, hub_service, payload)

    snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-live",
                "symbol": "SUIUSDT",
            }
        ],
        include_registry=True,
        filters={"recent_window_sec": 10**9},
    )
    assert snapshot["overview"]["total_active_issues"] == 0
    assert snapshot["issue_registry"][0]["is_active"] is False
    assert snapshot["issue_registry"][0]["resolution_reason"] == "bot_symbol_mismatch"


def test_watchdog_center_api_returns_live_active_and_recent_payload(monkeypatch, tmp_path):
    app_module = _load_app_module(monkeypatch, tmp_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    audit_service = AuditDiagnosticsService(str(tmp_path / "audit.jsonl"))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))

    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "small_bot_sizing",
        "severity": "WARN",
        "timestamp": now_iso,
        "bot_id": "bot-3",
        "symbol": "SUIUSDT",
        "reason": "setup_blocked_by_min_size",
        "compact_metrics": {"runtime_blocker": "qty_below_min"},
    }
    _record_watchdog_event(audit_service, hub_service, payload)

    app_module.watchdog_hub_service = hub_service
    app_module.pnl_service = type("PnlStub", (), {"audit_diagnostics_service": audit_service})()
    app_module._get_runtime_bots_snapshot = lambda: {
        "bots": [
            {
                "id": "bot-3",
                "status": "running",
                "symbol": "SUIUSDT",
                "_small_capital_block_opening_orders": True,
                "last_skip_reason": "qty_below_min",
            }
        ]
    }

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        response = client.get("/api/watchdog-center", headers=_basic_auth_headers())

    assert response.status_code == 200
    body = response.get_json()
    assert body["overview"]["total_active_issues"] == 1
    assert body["active_issues"][0]["watchdog_type"] == "small_bot_sizing"
    assert body["recent_events"][0]["reason"] == "setup_blocked_by_min_size"
    assert body["opportunity_funnel"]["snapshot"]["watch"] == 1
    assert body["opportunity_funnel"]["structural_untradeable"][0]["reason"] == "qty_below_min"
    card = next(item for item in body["watchdog_cards"] if item["watchdog_type"] == "small_bot_sizing")
    assert card["current_status"] == "ACTIVE"


def test_watchdog_hub_builds_compact_opportunity_funnel(monkeypatch, tmp_path):
    now_iso = datetime.now(timezone.utc).isoformat()
    audit_path = tmp_path / "audit.jsonl"
    audit_service = AuditDiagnosticsService(str(audit_path))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False))

    audit_service.record_event(
        {
            "event_type": "opening_orders_placed",
            "timestamp": now_iso,
            "bot_id": "bot-trigger",
            "symbol": "BTCUSDT",
            "mode": "long",
        },
        throttle_key="placed",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "opening_orders_suppressed",
            "timestamp": now_iso,
            "bot_id": "bot-blocked-1",
            "symbol": "ETHUSDT",
            "mode": "short",
            "primary_reason": "insufficient_margin",
        },
        throttle_key="blocked-1",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "opening_orders_suppressed",
            "timestamp": now_iso,
            "bot_id": "bot-blocked-2",
            "symbol": "SUIUSDT",
            "mode": "long",
            "primary_reason": "insufficient_margin",
            "skipped_reasons": {"notional_below_min": 1},
        },
        throttle_key="blocked-2",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "opening_orders_suppressed",
            "timestamp": now_iso,
            "bot_id": "bot-blocked-3",
            "symbol": "ETHUSDT",
            "mode": "short",
            "primary_reason": "opening_margin_reserve",
        },
        throttle_key="blocked-3",
        throttle_sec=0,
    )

    snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-watch",
                "status": "running",
                "symbol": "BTCUSDT",
                "mode": "long",
                "setup_timing_status": "watch",
            },
            {
                "id": "bot-armed",
                "status": "running",
                "symbol": "ETHUSDT",
                "mode": "short",
                "setup_timing_status": "armed",
            },
            {
                "id": "bot-trigger",
                "status": "recovering",
                "symbol": "SOLUSDT",
                "mode": "long",
                "setup_timing_status": "trigger_ready",
            },
            {
                "id": "bot-late",
                "status": "running",
                "symbol": "ADAUSDT",
                "mode": "long",
                "setup_timing_status": "late",
            },
            {
                "id": "bot-structural",
                "status": "running",
                "symbol": "SUIUSDT",
                "mode": "long",
                "setup_timing_status": "trigger_ready",
                "execution_viability_reason": "notional_below_min",
            },
            {
                "id": "bot-paused",
                "status": "paused",
                "symbol": "XRPUSDT",
                "mode": "long",
                "setup_timing_status": "trigger_ready",
            },
        ],
        filters={"recent_window_sec": 900},
    )

    funnel = snapshot["opportunity_funnel"]
    assert funnel["snapshot"]["watch"] == 1
    assert funnel["snapshot"]["armed"] == 1
    assert funnel["snapshot"]["trigger_ready"] == 2
    assert funnel["snapshot"]["late"] == 1
    assert funnel["snapshot"]["bot_count"] == 5
    assert funnel["follow_through"]["executed"] == 1
    assert funnel["follow_through"]["blocked"] == 3
    assert funnel["follow_through"]["opportunities"] == 4
    assert funnel["follow_through"]["trigger_to_execute_rate"] == 25.0
    assert funnel["blocked_reasons"][0] == {
        "key": "insufficient_margin",
        "label": "Margin",
        "count": 1,
    }
    reason_lookup = {item["key"]: item["count"] for item in funnel["blocked_reasons"]}
    assert reason_lookup["opening_margin_reserve"] == 1
    assert reason_lookup["notional_below_min"] == 1
    assert funnel["repeat_failures"][0]["label"] == "ETHUSDT · short"
    assert funnel["repeat_failures"][0]["count"] == 2
    assert funnel["repeat_failures"][0]["reason"] in {"insufficient_margin", "opening_margin_reserve"}
    assert funnel["structural_untradeable"][0]["label"] == "SUIUSDT · long"
    assert funnel["structural_untradeable"][0]["reason"] == "notional_below_min"


def test_watchdog_hub_normalizes_snapshot_stage_from_stable_readiness_fields():
    stage = WatchdogHubService._normalize_snapshot_stage(
        {
            "setup_timing_status": "watch",
            "stable_readiness_stage": "trigger_ready",
            "stable_readiness_actionable": True,
        }
    )

    assert stage == "trigger_ready"
