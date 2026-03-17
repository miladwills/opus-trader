from services.grid_bot_service import GridBotService
from services.range_engine_service import RangeEngineService
import config.strategy_config as strategy_cfg


class _AuditCollector:
    def __init__(self):
        self.events = []

    def enabled(self):
        return True

    def record_event(self, payload, **_kwargs):
        self.events.append(dict(payload))
        return True


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.audit_diagnostics_service = _AuditCollector()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._normalize_experiment_tags = GridBotService._normalize_experiment_tags.__get__(
        service, GridBotService
    )
    service._entry_gate_truth_fields = GridBotService._entry_gate_truth_fields.__get__(
        service, GridBotService
    )
    service._entry_gate_disabled_reason = GridBotService._entry_gate_disabled_reason
    service._compact_story_text = GridBotService._compact_story_text
    service._build_compact_entry_story = GridBotService._build_compact_entry_story.__get__(
        service, GridBotService
    )
    service._compact_directional_opening_sizing_fields = (
        GridBotService._compact_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    service._emit_audit_event = GridBotService._emit_audit_event.__get__(
        service, GridBotService
    )
    service._maybe_emit_blocker_stack_event = (
        GridBotService._maybe_emit_blocker_stack_event.__get__(
            service, GridBotService
        )
    )
    service._maybe_emit_entry_signal_event = (
        GridBotService._maybe_emit_entry_signal_event.__get__(
            service, GridBotService
        )
    )
    service._build_audit_blocker_signature = (
        GridBotService._build_audit_blocker_signature
    )
    service._parse_audit_iso_ts = GridBotService._parse_audit_iso_ts
    service._maybe_emit_cache_stale_anomaly = lambda *args, **kwargs: None
    service._maybe_emit_config_runtime_contradiction = lambda *args, **kwargs: None
    return service


def _event_types(service):
    return [event.get("event_type") for event in service.audit_diagnostics_service.events]


def test_clear_directional_entry_runtime_state_preserves_audit_window_marker():
    bot = {
        "_entry_gate_blocked": True,
        "_audit_first_valid_entry_ts": "2026-03-10T21:57:12+00:00",
        "_audit_actual_entry_ts": "2026-03-10T21:58:12+00:00",
    }

    GridBotService._clear_directional_entry_runtime_state(bot)

    assert bot["_entry_gate_blocked"] is False
    assert bot["_audit_first_valid_entry_ts"] == "2026-03-10T21:57:12+00:00"
    assert bot["_audit_actual_entry_ts"] == "2026-03-10T21:58:12+00:00"

    GridBotService._clear_directional_audit_runtime_state(bot)

    assert "_audit_first_valid_entry_ts" not in bot
    assert "_audit_actual_entry_ts" not in bot


def test_first_valid_seen_emits_once_per_validity_window_and_reemits_after_reentry():
    service = _make_service()
    bot = {"id": "bot-1"}

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.0,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )
    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.5,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )

    assert _event_types(service).count("first_valid_seen") == 1

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.2,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[
            {
                "code": "entry_gate",
                "reason": "near resistance",
                "phase": "gate",
                "side": "buy",
            }
        ],
        skipped_reason="near resistance",
        event="cycle",
    )

    assert "_audit_first_valid_entry_ts" not in bot

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=99.8,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )

    assert _event_types(service).count("first_valid_seen") == 2


def test_gate_disabled_path_does_not_clear_existing_first_valid_marker():
    service = GridBotService.__new__(GridBotService)
    service._is_entry_gate_contract_active = lambda bot, mode: False
    service._clear_setup_quality_runtime_state = lambda bot: None
    service._clear_directional_entry_runtime_state = (
        GridBotService._clear_directional_entry_runtime_state
    )

    bot = {
        "id": "bot-1",
        "_audit_first_valid_entry_ts": "2026-03-10T22:10:16.921081+00:00",
    }

    result = GridBotService._evaluate_directional_entry_gate(
        service,
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.0,
        fast_indicators=None,
    )

    assert result["reason"] == "Directional entry gate disabled"
    assert bot["_audit_first_valid_entry_ts"] == "2026-03-10T22:10:16.921081+00:00"


def test_actual_entry_and_entry_delay_remain_single_shot_for_same_entry():
    service = _make_service()
    bot = {"id": "bot-1"}

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.0,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )

    GridBotService._mark_audit_actual_entry(bot)

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.1,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="opening_order_placed",
    )
    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.2,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="opening_order_placed",
    )

    assert _event_types(service).count("actual_entry") == 1
    assert _event_types(service).count("entry_delay") == 1


def test_actual_entry_event_persists_gate_truth_and_entry_story(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "ENTRY_GATE_ENABLED", False)
    service = _make_service()
    bot = {
        "id": "bot-story",
        "entry_gate_enabled": True,
        "entry_signal_code": "breakout",
        "entry_signal_phase": "confirm",
        "entry_signal_preferred": True,
        "entry_signal_executable": True,
        "setup_timing_status": "trigger_ready",
        "setup_timing_actionable": True,
        "setup_timing_reason": "breakout",
        "setup_timing_reason_text": "Breakout ready",
        "setup_timing_source": "analysis_directional",
        "setup_quality_score": 84.2,
        "setup_quality_band": "strong",
        "setup_quality_summary": "Trend aligned and reclaim held.",
    }

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.0,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )

    GridBotService._mark_audit_actual_entry(
        bot,
        opening_kind="initial_opening",
        opening_sizing={
            "planned_qty": 0.9,
            "capped_qty": 0.3,
            "submitted_qty": 0.3,
            "affordability_cap_evaluated": True,
            "affordability_cap_applied": True,
            "affordability_cap_material": True,
        },
    )

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.1,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        gate_result={"reason": "Directional entry gate disabled", "blocked_by": []},
        setup_quality={"score": 84.2, "band": "strong"},
        event="opening_order_placed",
    )

    actual_event = [
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "actual_entry"
    ][0]
    assert actual_event["entry_story"]["candidate_ready"] is True
    assert actual_event["entry_story"]["entry_gate_bot_enabled"] is True
    assert actual_event["entry_story"]["entry_gate_global_master_enabled"] is False
    assert actual_event["entry_story"]["entry_gate_contract_active"] is False
    assert actual_event["entry_story"]["signal_raw_executable"] is True
    assert actual_event["entry_story"]["signal_executable"] is False
    assert actual_event["opening_sizing"]["affordability_cap_material"] is True


def test_entry_signal_state_event_emits_on_signal_or_runtime_blocker_change():
    service = _make_service()
    bot = {
        "id": "bot-1",
        "entry_signal_code": "good_continuation",
        "entry_signal_label": "Good continuation entry",
        "entry_signal_phase": "continuation",
        "entry_signal_detail": "Trend continuation remains tradable.",
        "entry_signal_executable": True,
        "entry_signal_preferred": True,
        "entry_signal_late": False,
    }

    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.0,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )

    bot["_watchdog_position_cap_active"] = True
    service._record_audit_cycle(
        bot,
        symbol="BTCUSDT",
        mode="long",
        last_price=100.1,
        lower_price=95.0,
        upper_price=105.0,
        blocker_stack=[],
        event="cycle",
    )

    signal_events = [
        event
        for event in service.audit_diagnostics_service.events
        if event.get("event_type") == "entry_signal_state_changed"
    ]
    assert len(signal_events) == 2
    assert signal_events[0]["signal_code"] == "good_continuation"
    assert signal_events[0].get("runtime_blocker") is None
    assert signal_events[1]["runtime_blocker"] == "position_cap_hit"


def test_dynamic_recenter_expectation_stays_false_while_price_is_centered():
    service = GridBotService.__new__(GridBotService)
    service.range_engine = RangeEngineService()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)

    result = GridBotService._get_dynamic_recenter_expectation(
        service,
        current_price=100.0,
        lower_price=95.0,
        upper_price=105.0,
        recenter_threshold_pct=0.6,
    )

    assert result["expected_recenter"] is False
    assert result["price_position_pct"] == 0.5


def test_dynamic_recenter_expectation_flags_true_only_near_edge():
    service = GridBotService.__new__(GridBotService)
    service.range_engine = RangeEngineService()
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)

    result = GridBotService._get_dynamic_recenter_expectation(
        service,
        current_price=104.5,
        lower_price=95.0,
        upper_price=105.0,
        recenter_threshold_pct=0.6,
    )

    assert result["expected_recenter"] is True
    assert "upper bound" in str(result["reason"]).lower()
