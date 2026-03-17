from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.bot_triage_action_service import (
    BotTriageActionService,
    BotTriageSettingsConflictError,
)
from services.bot_triage_service import BotTriageService
from services.runtime_settings_service import RuntimeSettingsService


class _Storage:
    def __init__(self, bot):
        self.bot = dict(bot)

    def get_bot(self, bot_id):
        if bot_id == self.bot.get("id"):
            return dict(self.bot)
        return None


class _AuditSink:
    def __init__(self):
        self.events = []

    def enabled(self):
        return True

    def record_event(self, payload, **kwargs):
        self.events.append(dict(payload))
        return True


def _bot(**overrides):
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "range_mode": "dynamic",
        "status": "running",
        "leverage": 6.0,
        "grid_count": 15,
        "target_grid_count": 15,
        "grid_distribution": "clustered",
        "settings_version": 11,
        "session_timer_enabled": False,
        "session_stop_at": None,
    }
    bot.update(overrides)
    return bot


def test_apply_reduce_preset_touches_only_expected_fields():
    stored_bot = _bot()
    storage = _Storage(stored_bot)
    audit_sink = _AuditSink()
    saved_payloads = []

    def _save(payload):
        saved_payloads.append(dict(payload))
        saved = dict(payload)
        saved["settings_version"] = 12
        storage.bot = dict(saved)
        return saved

    service = BotTriageActionService(
        bot_storage=storage,
        bot_manager=SimpleNamespace(
            create_or_update_bot=_save,
            audit_diagnostics_service=audit_sink,
        ),
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    result = service.apply_preset(
        "bot-1",
        preset="reduce_risk",
        incoming_settings_version=11,
    )

    assert result["updated"] is True
    assert saved_payloads[0]["leverage"] == 3.0
    assert saved_payloads[0]["grid_count"] == 8
    assert saved_payloads[0]["target_grid_count"] == 8
    assert saved_payloads[0]["grid_distribution"] == "balanced"
    assert "session_timer_enabled" in saved_payloads[0]
    assert audit_sink.events[-1]["event_type"] == "triage_action_apply_reduce_preset"
    assert audit_sink.events[-1]["changed_fields"] == [
        "leverage",
        "grid_count",
        "target_grid_count",
        "grid_distribution",
    ]


def test_apply_sleep_session_preset_sets_expected_session_fields():
    stored_bot = _bot(leverage=3.0, grid_count=8, target_grid_count=8, grid_distribution="balanced")
    storage = _Storage(stored_bot)
    audit_sink = _AuditSink()

    def _save(payload):
        saved = dict(payload)
        saved["settings_version"] = 12
        storage.bot = dict(saved)
        return saved

    service = BotTriageActionService(
        bot_storage=storage,
        bot_manager=SimpleNamespace(
            create_or_update_bot=_save,
            audit_diagnostics_service=audit_sink,
        ),
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    result = service.apply_preset(
        "bot-1",
        preset="sleep_session",
        incoming_settings_version=11,
    )

    bot = result["bot"]
    assert bot["session_timer_enabled"] is True
    assert bot["session_stop_at"] == "2026-03-12T14:00:00+00:00"
    assert bot["session_no_new_entries_before_stop_min"] == 20
    assert bot["session_end_mode"] == "green_grace_then_stop"
    assert bot["session_green_grace_min"] == 15
    assert bot["session_cancel_pending_orders_on_end"] is True
    assert bot["session_reduce_only_on_end"] is True
    assert audit_sink.events[-1]["event_type"] == "triage_action_apply_sleep_preset"


def test_apply_preset_enforces_settings_version_conflict_and_records_it():
    stored_bot = _bot(settings_version=14)
    storage = _Storage(stored_bot)
    conflict_events = []

    class _ConfigWatchdog:
        def record_settings_version_conflict(self, *args, **kwargs):
            conflict_events.append(dict(kwargs))
            return True

    service = BotTriageActionService(
        bot_storage=storage,
        bot_manager=SimpleNamespace(
            create_or_update_bot=lambda payload: payload,
            audit_diagnostics_service=_AuditSink(),
        ),
        config_integrity_watchdog_service=_ConfigWatchdog(),
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(BotTriageSettingsConflictError) as exc_info:
        service.apply_preset(
            "bot-1",
            preset="reduce_risk",
            incoming_settings_version=13,
        )

    assert exc_info.value.current_settings_version == 14
    assert exc_info.value.conflict_reason == "stale_incoming_version"
    assert conflict_events[0]["current_settings_version"] == 14
    assert conflict_events[0]["incoming_settings_version"] == 13


def test_pause_action_records_explicit_pause_cancel_pending_event():
    audit_sink = _AuditSink()
    service = BotTriageActionService(
        bot_storage=_Storage(_bot()),
        bot_manager=SimpleNamespace(
            pause_bot=lambda bot_id: _bot(status="paused", paused_at=123.0, pause_reason="Manual pause"),
            audit_diagnostics_service=audit_sink,
        ),
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    payload = service.pause_action("bot-1", cancel_pending_requested=True)

    assert payload["cancel_pending_requested"] is True
    assert payload["cancel_scope"] == "opening_orders_only"
    assert audit_sink.events[-1]["event_type"] == "triage_action_pause_cancel_pending"


def test_dismiss_and_snooze_suppress_triage_items(tmp_path):
    runtime_settings = RuntimeSettingsService(str(tmp_path / "runtime_settings.json"))
    runtime_settings.set_bot_triage_override("bot-1", mode="dismissed", verdict="REVIEW")
    runtime_settings.set_bot_triage_override(
        "bot-2",
        mode="snoozed",
        verdict="REVIEW",
        snooze_until="2026-03-12T13:00:00+00:00",
    )
    triage_service = BotTriageService(
        watchdog_hub_service=SimpleNamespace(
            build_snapshot=lambda runtime_bots=None: {
                "active_issues": [
                    {
                        "bot_id": "bot-2",
                        "symbol": "ETHUSDT",
                        "watchdog_type": "signal_drift",
                        "reason": "scanner_runtime_disagree",
                        "severity": "WARN",
                    }
                ]
            },
            audit_diagnostics_service=SimpleNamespace(
                get_review_snapshot=lambda: {
                    "bots": {
                        "bot-2": {
                            "current_operational_status": "WATCH",
                            "config_integrity_state": "clean",
                            "margin_viability_state": "viable",
                            "cap_headroom_state": "clear",
                            "recent_suppressions": {},
                            "recent_positive_actions": {},
                        }
                    }
                }
            ),
        ),
        runtime_settings_service=runtime_settings,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    payload = triage_service.build_snapshot(
        runtime_bots=[
            _bot(id="bot-1", symbol="BTCUSDT", total_pnl=5.0),
            _bot(id="bot-2", symbol="ETHUSDT", total_pnl=-8.0),
            _bot(id="bot-3", symbol="SOLUSDT", total_pnl=0.0),
        ]
    )

    assert payload["suppressed_count"] == 2
    assert [item["bot_id"] for item in payload["items"]] == ["bot-3"]
