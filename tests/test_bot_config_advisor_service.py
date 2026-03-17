from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile

import pytest

from services.bot_config_advisor_service import (
    BotConfigAdvisorApplyBlockedError,
    BotConfigAdvisorService,
)
from services.bot_triage_action_service import BotTriageSettingsConflictError
from services.bot_triage_service import BotTriageService
from services.runtime_settings_service import RuntimeSettingsService


def _base_bot(**overrides):
    bot = {
        "id": "bot-1",
        "symbol": "BTCUSDT",
        "mode": "long",
        "status": "running",
        "total_pnl": 4.0,
        "leverage": 6.0,
        "grid_count": 15,
        "target_grid_count": 15,
        "grid_distribution": "clustered",
        "lower_price": 95.0,
        "upper_price": 105.0,
        "effective_step_pct": 0.003,
        "fee_aware_min_step_pct": 0.0028,
        "session_timer_enabled": False,
        "ai_advisor_enabled": False,
    }
    bot.update(overrides)
    return bot


def _make_service(*, review_bots=None, active_issues=None):
    triage_service = BotTriageService(
        watchdog_hub_service=SimpleNamespace(
            build_snapshot=lambda runtime_bots=None: {
                "active_issues": list(active_issues or []),
            },
            audit_diagnostics_service=SimpleNamespace(
                get_review_snapshot=lambda: {
                    "bots": dict(review_bots or {}),
                }
            ),
        ),
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )
    return BotConfigAdvisorService(
        bot_triage_service=triage_service,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )


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


def _make_apply_service(*, bot, review_bots=None, active_issues=None, config_watchdog=None):
    triage_service = BotTriageService(
        watchdog_hub_service=SimpleNamespace(
            build_snapshot=lambda runtime_bots=None: {
                "active_issues": list(active_issues or []),
            },
            audit_diagnostics_service=SimpleNamespace(
                get_review_snapshot=lambda: {
                    "bots": dict(review_bots or {}),
                }
            ),
        ),
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )
    storage = _Storage(bot)
    audit_sink = _AuditSink()
    saved_payloads = []

    def _save(payload):
        saved_payloads.append(dict(payload))
        saved = dict(payload)
        saved["settings_version"] = int(bot.get("settings_version") or 0) + 1
        storage.bot = dict(saved)
        return saved

    service = BotConfigAdvisorService(
        bot_triage_service=triage_service,
        bot_storage=storage,
        bot_manager=SimpleNamespace(
            create_or_update_bot=_save,
            audit_diagnostics_service=audit_sink,
        ),
        runtime_settings_service=RuntimeSettingsService(
            str(Path(tempfile.mkdtemp()) / "runtime_settings.json")
        ),
        config_integrity_watchdog_service=config_watchdog,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )
    return service, storage, audit_sink, saved_payloads


def test_margin_starved_bot_recommends_reduce_risk_with_exact_safe_caps():
    service = _make_service(
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {
                    "insufficient_margin": 3,
                    "opening_orders_blocked": 4,
                },
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    original_bot = _base_bot()
    payload = service.build_snapshot(runtime_bots=[original_bot])
    item = payload["items"][0]

    assert item["tuning_verdict"] == "REDUCE_RISK"
    assert item["confidence"] == "high"
    assert item["recommended_settings"]["leverage"] == 3.0
    assert item["recommended_settings"]["grid_count"] == 8
    assert item["recommended_settings"]["target_grid_count"] == 8
    assert item["recommended_settings"]["grid_distribution"] == "balanced"
    assert item["recommended_settings"]["step_posture"] == "increase"
    assert item["suggested_preset"] == "reduce_risk"
    assert "repeated insufficient margin" in item["reasons"]
    assert original_bot["leverage"] == 6.0
    assert original_bot["grid_count"] == 15


def test_cost_drag_dense_grid_bot_recommends_wider_structure_without_false_precision():
    service = _make_service(
        review_bots={
            "bot-2": {
                "current_operational_status": "OK",
                "config_integrity_state": "clean",
                "margin_viability_state": "viable",
                "cap_headroom_state": "clear",
                "recent_suppressions": {},
                "recent_positive_actions": {"opening_orders_placed": 3},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-2",
                "symbol": "ETHUSDT",
                "watchdog_type": "pnl_attribution",
                "reason": "known_cost_drag_material",
                "severity": "WARN",
            }
        ],
    )

    payload = service.build_snapshot(
        runtime_bots=[
            _base_bot(
                id="bot-2",
                symbol="ETHUSDT",
                total_pnl=-2.5,
                leverage=4.0,
                grid_count=16,
                target_grid_count=16,
                grid_distribution="clustered",
                effective_step_pct=0.0025,
                fee_aware_min_step_pct=0.0023,
            )
        ]
    )
    item = payload["items"][0]

    assert item["tuning_verdict"] == "WIDEN_STRUCTURE"
    assert item["recommended_settings"]["range_posture"] == "widen"
    assert item["recommended_settings"]["step_posture"] == "increase"
    assert item["recommended_settings"]["leverage"] == 4.0
    assert item["recommended_settings"]["grid_count"] == 16
    assert item["recommended_settings"]["grid_distribution"] == "balanced"
    assert "cost drag from dense structure" in item["reasons"]


def test_stable_bot_recommends_keep_current():
    service = _make_service(
        review_bots={
            "bot-3": {
                "current_operational_status": "OK",
                "config_integrity_state": "clean",
                "margin_viability_state": "viable",
                "cap_headroom_state": "clear",
                "recent_suppressions": {},
                "recent_positive_actions": {"opening_orders_placed": 2},
            }
        },
        active_issues=[],
    )

    payload = service.build_snapshot(
        runtime_bots=[
            _base_bot(
                id="bot-3",
                symbol="SOLUSDT",
                leverage=3.0,
                grid_count=8,
                target_grid_count=8,
                grid_distribution="balanced",
                total_pnl=8.0,
                effective_step_pct=0.004,
                fee_aware_min_step_pct=0.0025,
            )
        ]
    )
    item = payload["items"][0]

    assert item["tuning_verdict"] == "KEEP_CURRENT"
    assert item["confidence"] == "high"
    assert item["recommended_settings"]["leverage"] == 3.0
    assert item["recommended_settings"]["grid_count"] == 8
    assert item["recommended_settings"]["session_timer"] == "recommend_sleep_session_preset"
    assert item["suggested_preset"] == "sleep_session"


def test_missing_data_recommends_manual_review_conservatively():
    triage_service = BotTriageService(
        watchdog_hub_service=None,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )
    service = BotConfigAdvisorService(
        bot_triage_service=triage_service,
        now_fn=lambda: datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc),
    )

    payload = service.build_snapshot(
        runtime_bots=[
            _base_bot(
                id="bot-4",
                symbol="XRPUSDT",
                runtime_snapshot_stale=True,
                total_pnl=0.0,
            )
        ],
        stale_data=True,
        error="bots_runtime_bridge_unavailable",
    )
    item = payload["items"][0]

    assert payload["stale_data"] is True
    assert item["tuning_verdict"] == "REVIEW_MANUALLY"
    assert item["confidence"] == "low"
    assert "runtime data incomplete" in item["reasons"]


def test_preview_separates_applicable_and_advisory_only_fields():
    service, _, _, _ = _make_apply_service(
        bot=_base_bot(settings_version=11),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {
                    "insufficient_margin": 3,
                    "opening_orders_blocked": 4,
                },
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    preview = service.preview_apply("bot-1")["preview"]

    assert preview["supports_apply"] is True
    assert preview["is_flat_now"] is True
    assert preview["applicable_fields"] == [
        "leverage",
        "grid_count",
        "target_grid_count",
        "grid_distribution",
    ]
    assert preview["advisory_only_fields"] == ["range_posture", "step_posture"]


def test_flat_bot_apply_success_uses_normal_save_path_and_emits_success_event():
    config_roundtrips = []

    class _ConfigWatchdog:
        def record_save_roundtrip(self, *args, **kwargs):
            config_roundtrips.append(True)
            return {"ok": True}

    service, storage, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(settings_version=11, position_size=0.0, position_side=""),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {
                    "insufficient_margin": 3,
                    "opening_orders_blocked": 4,
                },
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
        config_watchdog=_ConfigWatchdog(),
    )

    result = service.apply_recommendation("bot-1", incoming_settings_version=11)

    assert result["ok"] is True
    assert result["applied_fields"] == [
        "leverage",
        "grid_count",
        "target_grid_count",
        "grid_distribution",
    ]
    assert result["skipped_advisory_fields"] == ["range_posture", "step_posture"]
    assert result["new_settings_version"] == 12
    assert saved_payloads[0]["leverage"] == 3.0
    assert saved_payloads[0]["grid_count"] == 8
    assert storage.bot["settings_version"] == 12
    assert config_roundtrips
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_apply_attempt",
        "config_advisor_apply_success",
    ]


def test_non_flat_bot_apply_is_blocked_without_mutation():
    service, _, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {"insufficient_margin": 3},
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    with pytest.raises(BotConfigAdvisorApplyBlockedError) as exc_info:
        service.apply_recommendation("bot-1", incoming_settings_version=11)

    assert exc_info.value.blocked_reason == "requires_flat_state"
    assert saved_payloads == []
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_apply_attempt",
        "config_advisor_apply_blocked",
    ]


def test_stale_settings_version_conflict_fails_without_mutation():
    conflict_events = []

    class _ConfigWatchdog:
        def record_settings_version_conflict(self, *args, **kwargs):
            conflict_events.append(dict(kwargs))
            return True

    service, _, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(settings_version=14),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {"insufficient_margin": 3},
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
        config_watchdog=_ConfigWatchdog(),
    )

    with pytest.raises(BotTriageSettingsConflictError):
        service.apply_recommendation("bot-1", incoming_settings_version=13)

    assert saved_payloads == []
    assert conflict_events[0]["current_settings_version"] == 14
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_apply_attempt",
        "config_advisor_apply_blocked",
    ]


def test_advisory_only_recommendation_has_no_apply_support_and_refuses_apply():
    service, _, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(
            id="bot-2",
            symbol="ETHUSDT",
            settings_version=11,
            leverage=4.0,
            grid_count=10,
            target_grid_count=10,
            grid_distribution="balanced",
            effective_step_pct=0.0025,
            fee_aware_min_step_pct=0.0023,
            total_pnl=-2.5,
        ),
        review_bots={
            "bot-2": {
                "current_operational_status": "OK",
                "config_integrity_state": "clean",
                "margin_viability_state": "viable",
                "cap_headroom_state": "clear",
                "recent_suppressions": {},
                "recent_positive_actions": {"opening_orders_placed": 3},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-2",
                "symbol": "ETHUSDT",
                "watchdog_type": "pnl_attribution",
                "reason": "known_cost_drag_material",
                "severity": "WARN",
            }
        ],
    )

    item = service.get_recommendation_for_bot("bot-2")
    preview = service.preview_apply("bot-2")["preview"]

    assert item["supports_apply"] is False
    assert preview["supports_apply"] is False
    assert preview["advisory_only_fields"] == ["range_posture", "step_posture"]
    with pytest.raises(BotConfigAdvisorApplyBlockedError) as exc_info:
        service.apply_recommendation("bot-2", incoming_settings_version=11)
    assert exc_info.value.blocked_reason == "no_supported_changes"
    assert saved_payloads == []
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_apply_attempt",
        "config_advisor_apply_blocked",
    ]


def test_sleep_session_recommendation_previews_and_applies_exact_session_fields():
    service, storage, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(
            id="bot-3",
            symbol="SOLUSDT",
            settings_version=11,
            leverage=3.0,
            grid_count=8,
            target_grid_count=8,
            grid_distribution="balanced",
            total_pnl=8.0,
            effective_step_pct=0.004,
            fee_aware_min_step_pct=0.0025,
            position_size=0.0,
        ),
        review_bots={
            "bot-3": {
                "current_operational_status": "OK",
                "config_integrity_state": "clean",
                "margin_viability_state": "viable",
                "cap_headroom_state": "clear",
                "recent_suppressions": {},
                "recent_positive_actions": {"opening_orders_placed": 2},
            }
        },
        active_issues=[],
    )

    preview = service.preview_apply("bot-3")["preview"]
    result = service.apply_recommendation("bot-3", incoming_settings_version=11)

    assert preview["applicable_fields"] == [
        "session_timer_enabled",
        "session_stop_at",
        "session_no_new_entries_before_stop_min",
        "session_end_mode",
        "session_green_grace_min",
        "session_cancel_pending_orders_on_end",
        "session_reduce_only_on_end",
    ]
    assert result["applied_fields"] == preview["applicable_fields"]
    assert saved_payloads[0]["session_timer_enabled"] is True
    assert saved_payloads[0]["session_stop_at"] == "2026-03-12T14:00:00+00:00"
    assert storage.bot["settings_version"] == 12
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_apply_attempt",
        "config_advisor_apply_success",
    ]


def test_non_flat_queue_creation_persists_waiting_for_flat_without_advisory_write_fields():
    service, _, audit_sink, _ = _make_apply_service(
        bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {"insufficient_margin": 3},
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    result = service.queue_apply("bot-1", runtime_bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"))
    queued = service.list_queued_applies()["items"][0]

    assert result["state"] == "waiting_for_flat"
    assert queued["state"] == "waiting_for_flat"
    assert queued["queued_fields"] == [
        "leverage",
        "grid_count",
        "target_grid_count",
        "grid_distribution",
    ]
    assert queued["advisory_only_fields"] == ["range_posture", "step_posture"]
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_queue_attempt",
        "config_advisor_queue_created",
    ]


def test_queued_apply_executes_once_when_bot_becomes_flat_and_clears_queue():
    service, storage, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {"insufficient_margin": 3},
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    service.queue_apply("bot-1", runtime_bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"))
    results = service.process_queued_applies(
        runtime_bots=[_base_bot(settings_version=11, position_size=0.0, position_side="", unrealized_pnl=0.0)]
    )

    assert results == [{"bot_id": "bot-1", "state": "applied"}]
    assert saved_payloads[0]["leverage"] == 3.0
    assert storage.bot["settings_version"] == 12
    assert service.list_queued_applies()["items"] == []
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_queue_attempt",
        "config_advisor_queue_created",
        "config_advisor_queue_apply_attempt",
        "config_advisor_queue_apply_success",
    ]


def test_queued_apply_blocks_safely_on_settings_version_drift():
    service, storage, audit_sink, saved_payloads = _make_apply_service(
        bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {"insufficient_margin": 3},
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    service.queue_apply("bot-1", runtime_bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"))
    storage.bot["settings_version"] = 12
    results = service.process_queued_applies(
        runtime_bots=[_base_bot(settings_version=12, position_size=0.0, position_side="", unrealized_pnl=0.0)]
    )
    queued = service.list_queued_applies()["items"][0]

    assert results == [{"bot_id": "bot-1", "state": "blocked", "reason": "settings_version_conflict"}]
    assert saved_payloads == []
    assert queued["state"] == "blocked"
    assert queued["blocked_reason"] == "settings_version_conflict"
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_queue_attempt",
        "config_advisor_queue_created",
        "config_advisor_queue_apply_attempt",
        "config_advisor_queue_apply_blocked",
    ]


def test_queue_persistence_survives_reload(tmp_path):
    runtime_settings_path = tmp_path / "runtime_settings.json"
    runtime_settings = RuntimeSettingsService(str(runtime_settings_path))
    runtime_settings.set_bot_config_advisor_queued_apply(
        "bot-1",
        {
            "state": "waiting_for_flat",
            "recommendation_type": "REDUCE_RISK",
            "base_settings_version": 11,
            "applicable_changes": [{"field": "leverage", "from": 6.0, "to": 3.0, "label": "Leverage"}],
            "advisory_only_changes": [{"field": "range_posture", "from": "tight", "to": "keep", "label": "Range posture"}],
            "queued_at": "2026-03-12T12:00:00+00:00",
        },
    )

    reloaded = RuntimeSettingsService(str(runtime_settings_path)).get_bot_config_advisor_queued_applies()

    assert reloaded["bot-1"]["state"] == "waiting_for_flat"
    assert reloaded["bot-1"]["queued_fields"] == ["leverage"]
    assert reloaded["bot-1"]["advisory_only_fields"] == ["range_posture"]


def test_cancel_queued_apply_clears_entry_and_emits_event():
    service, _, audit_sink, _ = _make_apply_service(
        bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"),
        review_bots={
            "bot-1": {
                "current_operational_status": "BLOCKED",
                "config_integrity_state": "clean",
                "margin_viability_state": "starved",
                "cap_headroom_state": "tight",
                "recent_suppressions": {"insufficient_margin": 3},
                "recent_positive_actions": {},
            }
        },
        active_issues=[
            {
                "bot_id": "bot-1",
                "symbol": "BTCUSDT",
                "watchdog_type": "small_bot_sizing",
                "reason": "valid_setup_blocked_by_margin",
                "severity": "ERROR",
            }
        ],
    )

    service.queue_apply("bot-1", runtime_bot=_base_bot(settings_version=11, position_size=1.25, position_side="long"))
    result = service.cancel_queued_apply("bot-1")

    assert result["state"] == "canceled"
    assert service.list_queued_applies()["items"] == []
    assert [event["event_type"] for event in audit_sink.events] == [
        "config_advisor_queue_attempt",
        "config_advisor_queue_created",
        "config_advisor_queue_canceled",
    ]
