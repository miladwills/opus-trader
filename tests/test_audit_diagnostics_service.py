import json

from services.audit_diagnostics_service import AuditDiagnosticsService


def _read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_summary(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_review_snapshot(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_audit_path_is_isolated_under_pytest(monkeypatch):
    monkeypatch.setenv(
        "PYTEST_CURRENT_TEST",
        "tests/test_audit_diagnostics_service.py::test_default_audit_path_is_isolated_under_pytest (call)",
    )

    service = AuditDiagnosticsService()

    assert "opus_pytest_audit_diagnostics" in str(service.file_path)
    assert str(service.file_path) != "storage/audit_diagnostics.jsonl"


def test_record_event_throttles_identical_events(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))

    payload = {
        "event_type": "blocker_stack_changed",
        "severity": "WARN",
        "bot_id": "bot-1",
        "symbol": "BTCUSDT",
    }

    assert service.record_event(payload, throttle_key="bot-1:blockers", throttle_sec=60) is True
    assert service.record_event(payload, throttle_key="bot-1:blockers", throttle_sec=60) is False

    rows = _read_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "blocker_stack_changed"


def test_record_event_allows_changed_payload_for_same_key(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))

    first = {
        "event_type": "blocker_stack_changed",
        "severity": "WARN",
        "bot_id": "bot-1",
        "symbol": "BTCUSDT",
        "blocker_stack": [{"code": "entry_gate", "reason": "near resistance"}],
    }
    second = {
        "event_type": "blocker_stack_changed",
        "severity": "WARN",
        "bot_id": "bot-1",
        "symbol": "BTCUSDT",
        "blocker_stack": [{"code": "btc_guard", "reason": "btc guard"}],
    }

    assert service.record_event(first, throttle_key="bot-1:blockers", throttle_sec=60) is True
    assert service.record_event(second, throttle_key="bot-1:blockers", throttle_sec=60) is True

    rows = _read_jsonl(path)
    assert len(rows) == 2
    assert rows[0]["blocker_stack"][0]["code"] == "entry_gate"
    assert rows[1]["blocker_stack"][0]["code"] == "btc_guard"


def test_record_event_updates_summary_rollups_and_per_bot_health(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "audit_diagnostics_summary.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    assert service.record_event(
        {
            "event_type": "blocker_stack_changed",
            "severity": "WARN",
            "bot_id": "bot-1",
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "blocker_stack": [
                {"code": "opening_guard", "reason": "Failure breaker cooldown"}
            ],
        },
        throttle_key="bot-1:blockers",
        throttle_sec=0,
    )
    assert service.record_event(
        {
            "event_type": "position_cap_hit",
            "severity": "WARN",
            "bot_id": "bot-1",
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "suppression_kind": "add",
        },
        throttle_key="bot-1:cap",
        throttle_sec=0,
    )
    assert service.record_event(
        {
            "event_type": "opening_orders_suppressed",
            "severity": "WARN",
            "bot_id": "bot-1",
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "primary_reason": "position_cap_hit",
        },
        throttle_key="bot-1:suppressed",
        throttle_sec=0,
    )
    assert service.record_event(
        {
            "event_type": "quick_profit_rebuild_happened",
            "severity": "INFO",
            "bot_id": "bot-1",
            "symbol": "PIPPINUSDT",
            "mode": "long",
        },
        throttle_key="bot-1:rebuild",
        throttle_sec=0,
    )

    summary = _read_summary(summary_path)
    assert summary["event_counts"]["position_cap_hit"] == 1
    assert summary["rollups"]["top_blocker_reasons"][0]["key"] == "opening_guard:failure breaker cooldown"
    assert summary["rollups"]["top_symbols_by_position_cap_hit"][0]["key"] == "PIPPINUSDT"

    health = summary["per_bot_health"]["bot-1"]
    assert health["symbol"] == "PIPPINUSDT"
    assert health["cap_hit_count_recent"] == 1
    assert health["opening_orders_suppressed_count_recent"] == 1
    assert health["last_recenter_state"] == "quick_profit_rebuild_happened"
    assert health["health_status"] == "DEGRADED"
    assert "position_cap_hit" in health["top_bottlenecks"]


def test_record_event_tracks_capital_starved_clear_in_health_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "audit_diagnostics_summary.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    assert service.record_event(
        {
            "event_type": "capital_starved_opening_block",
            "severity": "WARN",
            "bot_id": "bot-2",
            "symbol": "DOGEUSDT",
            "mode": "neutral",
            "reason": "insufficient_margin",
        },
        throttle_key="bot-2:starved",
        throttle_sec=0,
    )
    assert service.record_event(
        {
            "event_type": "capital_starved_block_cleared",
            "severity": "INFO",
            "bot_id": "bot-2",
            "symbol": "DOGEUSDT",
            "mode": "neutral",
        },
        throttle_key="bot-2:starved:clear",
        throttle_sec=0,
    )

    summary = _read_summary(summary_path)
    health = summary["per_bot_health"]["bot-2"]
    assert health["capital_starved_active"] is False
    assert health["last_follow_through_state"] == "capital_starved_block_cleared"
    assert health["health_status"] == "OK"


def test_record_event_writes_review_snapshot_with_rolling_counters(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    review_path = tmp_path / "audit_diagnostics_review_snapshot.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    for payload in (
        {
            "event_type": "position_cap_suppression_started",
            "severity": "WARN",
            "bot_id": "bot-3",
            "symbol": "PIPPINUSDT",
            "mode": "long",
        },
        {
            "event_type": "opening_orders_suppressed",
            "severity": "WARN",
            "bot_id": "bot-3",
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "primary_reason": "position_cap_hit",
        },
        {
            "event_type": "opening_follow_through_restored",
            "severity": "INFO",
            "bot_id": "bot-3",
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "restored_from": "opening_orders_suppressed",
            "restored_to": "opening_orders_placed",
        },
        {
            "event_type": "opening_orders_placed",
            "severity": "INFO",
            "bot_id": "bot-3",
            "symbol": "PIPPINUSDT",
            "mode": "long",
        },
        {
            "event_type": "quick_profit_rebuild_completed",
            "severity": "INFO",
            "bot_id": "bot-3",
            "symbol": "PIPPINUSDT",
            "mode": "long",
        },
    ):
        assert service.record_event(
            payload,
            throttle_key=f"{payload['bot_id']}:{payload['event_type']}",
            throttle_sec=0,
        )

    review = _read_review_snapshot(review_path)
    bot = review["bots"]["bot-3"]
    assert bot["current_operational_status"] == "DEGRADED"
    assert bot["cap_headroom_state"] == "suppressed"
    assert bot["follow_through_state"] == "opening_orders_placed"
    assert bot["last_transition_event"] == "quick_profit_rebuild_completed"
    assert bot["rolling_counters"]["last_15m"]["opening_orders_placed_recent"] == 2
    assert bot["recent_positive_actions"]["opening_orders_placed"] == 2


def test_record_event_tracks_config_integrity_rollups_and_review_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "audit_diagnostics_summary.json"
    review_path = tmp_path / "audit_diagnostics_review_snapshot.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    assert service.record_event(
        {
            "event_type": "config_save_roundtrip",
            "severity": "WARN",
            "bot_id": "bot-4",
            "symbol": "PIPPINUSDT",
            "ui_path": "quick",
            "persisted_matches_intent": False,
            "changed_fields": ["quick_profit_enabled"],
            "normalized_fields": ["quick_profit_enabled"],
            "dropped_fields": [],
        },
        throttle_key="bot-4:config_save_roundtrip",
        throttle_sec=0,
    )
    assert service.record_event(
        {
            "event_type": "config_roundtrip_mismatch",
            "severity": "WARN",
            "bot_id": "bot-4",
            "symbol": "PIPPINUSDT",
            "ui_path": "quick",
            "persisted_mismatches": [
                {
                    "field": "quick_profit_enabled",
                    "requested": True,
                    "observed": False,
                }
            ],
        },
        throttle_key="bot-4:config_roundtrip_mismatch",
        throttle_sec=0,
    )

    summary = _read_summary(summary_path)
    review = _read_review_snapshot(review_path)

    assert summary["rollups"]["top_config_issue_types"][0]["key"] == "config_roundtrip_mismatch"
    assert summary["rollups"]["top_config_issue_ui_paths"][0]["key"] == "quick"
    assert summary["rollups"]["top_bots_by_config_integrity_issue"][0]["key"] == "bot-4"

    health = summary["per_bot_health"]["bot-4"]
    assert health["last_config_save_ui_path"] == "quick"
    assert health["last_config_roundtrip_matches_intent"] is False
    assert health["config_integrity_issue_count_recent"] == 1
    assert health["config_integrity_top_issue"] == "config_roundtrip_mismatch"

    review_bot = review["bots"]["bot-4"]
    assert review_bot["config_integrity_state"] == "watch"
    assert review_bot["last_config_save_ui_path"] == "quick"
    assert review_bot["rolling_counters"]["last_15m"]["config_integrity_issue_recent"] == 1


def test_record_event_tracks_settings_version_conflict_as_config_integrity_issue(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "audit_diagnostics_summary.json"
    review_path = tmp_path / "audit_diagnostics_review_snapshot.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    assert service.record_event(
        {
            "event_type": "settings_version_conflict",
            "severity": "WARN",
            "bot_id": "bot-9",
            "symbol": "ETHUSDT",
            "mode": "short",
            "ui_path": "main",
            "incoming_settings_version": 11,
            "current_settings_version": 12,
            "conflict_reason": "stale_incoming_version",
        },
        throttle_key="bot-9:settings_version_conflict",
        throttle_sec=0,
    )
    assert service.record_event(
        {
            "event_type": "settings_version_conflict",
            "severity": "WARN",
            "bot_id": "bot-9",
            "symbol": "ETHUSDT",
            "mode": "short",
            "ui_path": "quick",
            "incoming_settings_version": None,
            "current_settings_version": 12,
            "conflict_reason": "missing_incoming_version",
        },
        throttle_key="bot-9:settings_version_conflict:missing",
        throttle_sec=0,
    )

    summary = _read_summary(summary_path)
    review = _read_review_snapshot(review_path)
    health = summary["per_bot_health"]["bot-9"]

    assert summary["rollups"]["top_config_issue_types"][0]["key"] == "settings_version_conflict"
    assert summary["rollups"]["top_config_issue_ui_paths"][0]["key"] == "main"
    assert summary["rollups"]["top_bots_by_config_integrity_issue"][0]["key"] == "bot-9"
    assert health["config_integrity_issue_count_recent"] == 2
    assert health["config_integrity_top_issue"] == "settings_version_conflict"
    assert health["last_config_save_ui_path"] == "quick"
    assert health["settings_version_conflicts_total"] == 2
    assert health["settings_version_conflicts_stale"] == 1
    assert health["settings_version_conflicts_missing"] == 1
    assert health["last_settings_version_conflict_source"] == "quick"
    assert health["last_settings_version_conflict_ts"]

    review_bot = review["bots"]["bot-9"]
    assert review_bot["settings_version_conflicts_total"] == 2
    assert review_bot["settings_version_conflicts_stale"] == 1
    assert review_bot["settings_version_conflicts_missing"] == 1
    assert review_bot["last_settings_version_conflict_source"] == "quick"
    assert review_bot["last_settings_version_conflict_ts"]
    assert (
        review_bot["rolling_counters"]["last_15m"]["settings_version_conflict_recent"] == 2
    )
    assert review_bot["rolling_counters"]["last_15m"]["config_integrity_issue_recent"] == 2


def test_record_event_does_not_increment_settings_version_rollup_for_successful_save(
    monkeypatch, tmp_path
):
    path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "audit_diagnostics_summary.json"
    review_path = tmp_path / "audit_diagnostics_review_snapshot.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    assert service.record_event(
        {
            "event_type": "config_save_roundtrip",
            "severity": "INFO",
            "bot_id": "bot-10",
            "symbol": "BTCUSDT",
            "ui_path": "main",
            "persisted_matches_intent": True,
            "changed_fields": ["trailing_sl_enabled"],
            "normalized_fields": [],
            "dropped_fields": [],
        },
        throttle_key="bot-10:config_save_roundtrip",
        throttle_sec=0,
    )

    summary = _read_summary(summary_path)
    review = _read_review_snapshot(review_path)
    health = summary["per_bot_health"]["bot-10"]
    review_bot = review["bots"]["bot-10"]

    assert health.get("settings_version_conflicts_total") in (None, 0)
    assert health.get("settings_version_conflicts_stale") in (None, 0)
    assert health.get("settings_version_conflicts_missing") in (None, 0)
    assert review_bot["settings_version_conflicts_total"] == 0
    assert review_bot["settings_version_conflicts_stale"] == 0
    assert review_bot["settings_version_conflicts_missing"] == 0
    assert review_bot["last_settings_version_conflict_ts"] is None
    assert review_bot["last_settings_version_conflict_source"] is None
    assert (
        review_bot["rolling_counters"]["last_15m"]["settings_version_conflict_recent"] == 0
    )
    assert review_bot["rolling_counters"]["last_15m"]["config_integrity_issue_recent"] == 0


def test_record_event_tracks_watchdog_rollups_and_recent_queries(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    summary_path = tmp_path / "audit_diagnostics_summary.json"
    service = AuditDiagnosticsService(str(path))
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService,
        "summary_enabled",
        staticmethod(lambda: True),
    )

    assert service.record_event(
        {
            "event_type": "watchdog_event",
            "watchdog_type": "signal_drift",
            "severity": "WARN",
            "bot_id": "bot-5",
            "symbol": "BTCUSDT",
            "mode": "long",
            "reason": "scanner_runtime_disagree",
            "compact_metrics": {"entry_ready_status": "ready"},
        },
        throttle_key="bot-5:signal_drift",
        throttle_sec=0,
    )

    summary = _read_summary(summary_path)
    assert summary["rollups"]["top_watchdog_types"][0]["key"] == "signal_drift"
    assert summary["rollups"]["top_watchdog_reasons"][0]["key"] == "scanner_runtime_disagree"
    health = summary["per_bot_health"]["bot-5"]
    assert health["watchdog_last_type"] == "signal_drift"
    assert health["watchdog_event_count_recent"] == 1

    recent = service.get_recent_events(
        event_type="watchdog_event",
        bot_id="bot-5",
        symbol="BTCUSDT",
        limit=5,
    )
    assert len(recent) == 1
    assert recent[0]["watchdog_type"] == "signal_drift"
