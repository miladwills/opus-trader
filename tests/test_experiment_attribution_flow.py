from datetime import datetime, timezone

from services.audit_diagnostics_service import AuditDiagnosticsService
from services.grid_bot_service import GridBotService
from services.pnl_service import PnlService
from services.trade_forensics_service import TradeForensicsService
from services.watchdog_hub_service import WatchdogHubService


def _make_grid_service(tmp_path):
    service = GridBotService.__new__(GridBotService)
    service.audit_diagnostics_service = AuditDiagnosticsService(str(tmp_path / "audit.jsonl"))
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._normalize_experiment_tags = GridBotService._normalize_experiment_tags.__get__(
        service, GridBotService
    )
    service._merge_experiment_details = GridBotService._merge_experiment_details.__get__(
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
    service._build_persistent_ownership_snapshot = (
        GridBotService._build_persistent_ownership_snapshot.__get__(
            service, GridBotService
        )
    )
    service._emit_audit_event = GridBotService._emit_audit_event.__get__(
        service, GridBotService
    )
    service._record_watchdog_operational_event = (
        GridBotService._record_watchdog_operational_event.__get__(
            service, GridBotService
        )
    )
    service._record_opening_follow_through_event = (
        GridBotService._record_opening_follow_through_event.__get__(
            service, GridBotService
        )
    )
    service._touch_watchdog_summary = GridBotService._touch_watchdog_summary
    return service


def _make_pnl_service(tmp_path):
    service = PnlService.__new__(PnlService)
    service.trade_forensics_service = TradeForensicsService(
        str(tmp_path / "trade_forensics.jsonl")
    )
    service.audit_diagnostics_service = AuditDiagnosticsService(
        str(tmp_path / "audit.jsonl")
    )
    return service


def test_opening_follow_through_event_emits_experiment_attribution(tmp_path, monkeypatch):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False)
    )
    service = _make_grid_service(tmp_path)
    bot = {"id": "bot-exp"}
    GridBotService._remember_runtime_experiment_usage(
        bot,
        [
            "exp_strong_continuation_promotion_used",
            "exp_directional_position_cap_headroom_used",
        ],
    )

    service._record_opening_follow_through_event(
        bot,
        event_type="opening_orders_placed",
        symbol="BTCUSDT",
        mode="long",
        buy_candidates=2,
        sell_candidates=0,
        buy_orders_placed=2,
        sell_orders_placed=0,
        initial_opening_orders_placed=1,
        add_follow_through_placed=1,
    )

    event = service.audit_diagnostics_service.get_recent_events(
        event_type="opening_orders_placed",
        limit=5,
    )[-1]
    assert event["experiment_tags"] == [
        "exp_directional_position_cap_headroom_used",
        "exp_strong_continuation_promotion_used",
    ]
    assert event["experiment_outcome_kind"] == "executed"
    assert "exp_executed_after_directional_position_cap_headroom" in event[
        "experiment_outcome_tags"
    ]
    assert "exp_executed_after_strong_continuation_promotion" in event[
        "experiment_outcome_tags"
    ]
    assert bot["runtime_experiment_last_outcome_kind"] == "executed"


def test_reduce_only_ownership_snapshot_reuses_active_entry_story_and_experiments(tmp_path):
    service = _make_grid_service(tmp_path)
    bot = {
        "id": "bot-active",
        "mode": "long",
        "range_mode": "dynamic",
        "forensic_active_entry_story": {
            "entry_kind": "initial_opening",
            "readiness_stage": "trigger_ready",
            "signal_code": "breakout",
            "experiment_attribution_state": "present",
        },
        "forensic_active_experiment_tags": [
            "exp_strong_continuation_promotion_used"
        ],
        "forensic_active_experiment_details": {
            "exp_strong_continuation_promotion_used": {"score": 81.2}
        },
        "forensic_active_opening_sizing": {
            "planned_qty": 0.9,
            "capped_qty": 0.3,
            "submitted_qty": 0.3,
            "affordability_cap_evaluated": True,
            "affordability_cap_applied": True,
            "affordability_cap_material": True,
        },
    }

    snapshot = service._build_persistent_ownership_snapshot(
        bot,
        order_link_id="cls:bot-active:MANL",
        reduce_only=True,
        diagnostic_context={"action": "reduce_only_close"},
    )

    assert snapshot["experiment_attribution_state"] == "present"
    assert snapshot["experiment_tags"] == [
        "exp_strong_continuation_promotion_used"
    ]
    assert snapshot["entry_story"]["signal_code"] == "breakout"
    assert snapshot["opening_sizing"]["affordability_cap_material"] is True


def test_profitable_add_cap_headroom_emits_blocked_executed_and_profit_attribution(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False)
    )
    service = _make_grid_service(tmp_path)
    bot = {"id": "bot-profitable-add"}
    GridBotService._remember_runtime_experiment_usage(
        bot,
        ["exp_profitable_add_cap_headroom_used"],
    )

    service._record_opening_follow_through_event(
        bot,
        event_type="opening_orders_placed",
        symbol="SOLUSDT",
        mode="long",
        buy_candidates=1,
        sell_candidates=0,
        buy_orders_placed=1,
        sell_orders_placed=0,
        initial_opening_orders_placed=0,
        add_follow_through_placed=1,
    )
    executed_event = service.audit_diagnostics_service.get_recent_events(
        event_type="opening_orders_placed",
        limit=5,
    )[-1]
    assert executed_event["experiment_tags"] == [
        "exp_profitable_add_cap_headroom_used"
    ]
    assert executed_event["experiment_outcome_tags"] == [
        "exp_executed_after_profitable_add_cap_headroom"
    ]

    service._record_opening_follow_through_event(
        bot,
        event_type="opening_orders_suppressed",
        symbol="SOLUSDT",
        mode="long",
        buy_candidates=1,
        sell_candidates=0,
        buy_orders_placed=0,
        sell_orders_placed=0,
        initial_opening_orders_placed=0,
        add_follow_through_placed=0,
        primary_reason="opening_margin_reserve",
        continuation_add_reason="continuation_add_blocked_by_opening_margin_reserve",
    )
    blocked_event = service.audit_diagnostics_service.get_recent_events(
        event_type="opening_orders_suppressed",
        limit=5,
    )[-1]
    assert blocked_event["experiment_tags"] == [
        "exp_profitable_add_cap_headroom_used"
    ]
    assert blocked_event["experiment_outcome_tags"] == [
        "exp_blocked_after_profitable_add_cap_headroom"
    ]
    assert blocked_event["continuation_add_reason"] == (
        "continuation_add_blocked_by_opening_margin_reserve"
    )

    pnl_service = _make_pnl_service(tmp_path)
    pnl_service._record_trade_forensic_outcome(
        {
            "id": "trade-profit-1",
            "time": "2026-03-13T12:00:00+00:00",
            "bot_id": "bot-profitable-add",
            "symbol": "SOLUSDT",
            "bot_mode": "long",
            "bot_profile": "directional",
            "side": "Sell",
            "realized_pnl": 1.75,
            "order_id": "oid-profit-1",
            "order_link_id": "ol-profit-1",
            "position_idx": 1,
            "attribution_source": "ownership_snapshot",
        },
        ownership_snapshot={
            "experiment_tags": ["exp_profitable_add_cap_headroom_used"],
            "forensic_decision_id": "fdc:profit",
            "forensic_trade_context_id": "ftc:profit",
            "forensic_decision_type": "grid_opening",
            "forensic_side": "Buy",
        },
    )

    profit_event = pnl_service.audit_diagnostics_service.get_recent_events(
        event_type="experiment_trade_outcome",
        limit=5,
    )[-1]
    assert profit_event["experiment_tags"] == [
        "exp_profitable_add_cap_headroom_used"
    ]
    assert profit_event["experiment_outcome_kind"] == "profit"
    assert profit_event["experiment_outcome_tags"] == [
        "exp_profit_after_profitable_add_cap_headroom"
    ]


def test_watchdog_and_audit_rollups_separate_experiments_and_combinations(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: True)
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    audit_service = AuditDiagnosticsService(str(tmp_path / "audit.jsonl"))
    relax_tag = "exp_directional_structure_relax_used"
    long_add_tag = "exp_long_near_price_continuation_add_used"

    audit_service.record_event(
        {
            "event_type": "entry_signal_state_changed",
            "timestamp": now_iso,
            "bot_id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "experiment_tags": [relax_tag],
            "experiment_outcome_kind": "trigger_ready",
        },
        throttle_key="trigger-ready",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "opening_orders_placed",
            "timestamp": now_iso,
            "bot_id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "experiment_tags": [relax_tag, long_add_tag],
            "experiment_outcome_kind": "executed",
            "initial_opening_orders_placed": 1,
            "add_follow_through_placed": 2,
        },
        throttle_key="executed",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "opening_orders_suppressed",
            "timestamp": now_iso,
            "bot_id": "bot-2",
            "symbol": "ETHUSDT",
            "mode": "long",
            "experiment_tags": [long_add_tag],
            "experiment_outcome_kind": "blocked",
            "opening_buy_candidates": 2,
            "primary_reason": "insufficient_margin",
        },
        throttle_key="blocked",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "experiment_trade_outcome",
            "timestamp": now_iso,
            "bot_id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "long",
            "experiment_tags": [relax_tag],
            "experiment_outcome_kind": "profit",
            "realized_pnl": 1.5,
        },
        throttle_key="profit",
        throttle_sec=0,
    )
    audit_service.record_event(
        {
            "event_type": "experiment_trade_outcome",
            "timestamp": now_iso,
            "bot_id": "bot-2",
            "symbol": "ETHUSDT",
            "mode": "long",
            "experiment_tags": [long_add_tag],
            "experiment_outcome_kind": "loss",
            "realized_pnl": -0.75,
        },
        throttle_key="loss",
        throttle_sec=0,
    )

    summary = audit_service.get_summary_snapshot()
    executed_lookup = {
        item["key"]: item["count"]
        for item in summary["rollups"]["top_experiment_executed"]
    }
    blocked_lookup = {
        item["key"]: item["count"]
        for item in summary["rollups"]["top_experiment_blocked"]
    }
    profit_lookup = {
        item["key"]: item["count"]
        for item in summary["rollups"]["top_experiment_profit"]
    }
    loss_lookup = {
        item["key"]: item["count"]
        for item in summary["rollups"]["top_experiment_loss"]
    }
    assert executed_lookup[relax_tag] == 1
    assert executed_lookup[long_add_tag] == 1
    assert blocked_lookup[long_add_tag] == 1
    assert profit_lookup[relax_tag] == 1
    assert loss_lookup[long_add_tag] == 1

    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-1",
                "status": "running",
                "symbol": "BTCUSDT",
                "mode": "long",
                "setup_timing_status": "trigger_ready",
            }
        ],
        filters={"recent_window_sec": 900},
    )
    attribution = snapshot["experiment_attribution"]
    by_key = {row["key"]: row for row in attribution["experiments"]}
    combo_key = " + ".join(sorted([long_add_tag, relax_tag]))

    assert by_key[relax_tag]["trigger_ready"] == 1
    assert by_key[relax_tag]["executed_total"] == 3
    assert by_key[relax_tag]["profit"] == 1
    assert by_key[long_add_tag]["executed_total"] == 3
    assert by_key[long_add_tag]["blocked"] == 2
    assert by_key[long_add_tag]["loss"] == 1
    assert by_key[long_add_tag]["net_realized_pnl"] == -0.75
    combo_lookup = {row["key"]: row for row in attribution["combinations"]}
    assert combo_lookup[combo_key]["executed_total"] == 3
    assert snapshot["opportunity_funnel"]["experiment_breakdown"] == attribution["experiments"]
    assert snapshot["opportunity_funnel"]["experiment_combinations"] == attribution["combinations"]


def test_pnl_outcome_emits_experiment_loss_attribution(tmp_path, monkeypatch):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False)
    )
    service = _make_pnl_service(tmp_path)

    service._record_trade_forensic_outcome(
        {
            "id": "trade-1",
            "time": "2026-03-13T10:00:00+00:00",
            "bot_id": "bot-loss",
            "symbol": "SOLUSDT",
            "bot_mode": "long",
            "bot_profile": "directional",
            "side": "Sell",
            "realized_pnl": -1.25,
            "order_id": "oid-1",
            "order_link_id": "ol-1",
            "position_idx": 1,
            "attribution_source": "ownership_snapshot",
        },
        ownership_snapshot={
            "experiment_tags": ["exp_long_near_price_continuation_add_used"],
            "experiment_details": {
                "exp_long_near_price_continuation_add_used": {
                    "candidate_price": 100.12
                }
            },
            "experiment_attribution_state": "present",
            "entry_story": {
                "entry_kind": "add",
                "readiness_stage": "trigger_ready",
                "signal_code": "continuation_entry",
                "signal_executable": True,
                "entry_gate_contract_active": True,
                "experiment_attribution_state": "present",
            },
            "opening_sizing": {
                "planned_qty": 0.9,
                "capped_qty": 0.3,
                "submitted_qty": 0.3,
                "affordability_cap_evaluated": True,
                "affordability_cap_applied": True,
                "affordability_cap_material": True,
            },
            "forensic_decision_id": "fdc:test",
            "forensic_trade_context_id": "ftc:test",
            "forensic_decision_type": "grid_opening",
            "forensic_side": "Buy",
        },
    )

    audit_event = service.audit_diagnostics_service.get_recent_events(
        event_type="experiment_trade_outcome",
        limit=5,
    )[-1]
    assert audit_event["experiment_outcome_kind"] == "loss"
    assert audit_event["experiment_tags"] == [
        "exp_long_near_price_continuation_add_used"
    ]
    assert audit_event["experiment_outcome_tags"] == [
        "exp_loss_after_long_near_price_continuation_add"
    ]

    forensic_event = service.trade_forensics_service.get_recent_events(
        event_type="realized_outcome",
        limit=5,
    )[-1]
    assert forensic_event["outcome"]["experiment_tags"] == [
        "exp_long_near_price_continuation_add_used"
    ]
    assert forensic_event["outcome"]["experiment_attribution_state"] == "present"
    assert forensic_event["outcome"]["entry_story"]["entry_kind"] == "add"
    assert forensic_event["outcome"]["opening_sizing"]["affordability_cap_material"] is True


def test_pnl_outcome_does_not_create_fake_experiment_attribution(tmp_path, monkeypatch):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False)
    )
    service = _make_pnl_service(tmp_path)

    service._record_trade_forensic_outcome(
        {
            "id": "trade-plain-1",
            "time": "2026-03-13T10:05:00+00:00",
            "bot_id": "bot-plain",
            "symbol": "BTCUSDT",
            "bot_mode": "long",
            "bot_profile": "directional",
            "side": "Sell",
            "realized_pnl": 0.55,
            "order_id": "oid-plain-1",
            "order_link_id": "ol-plain-1",
            "position_idx": 1,
            "attribution_source": "ownership_snapshot",
        },
        ownership_snapshot={
            "experiment_attribution_state": "none",
            "entry_story": {
                "entry_kind": "initial_opening",
                "readiness_stage": "armed",
                "signal_code": "breakout",
                "signal_executable": True,
                "experiment_attribution_state": "none",
            },
        },
    )

    assert service.audit_diagnostics_service.get_recent_events(
        event_type="experiment_trade_outcome",
        limit=5,
    ) == []
    forensic_event = service.trade_forensics_service.get_recent_events(
        event_type="realized_outcome",
        limit=5,
    )[-1]
    assert forensic_event["outcome"]["experiment_attribution_state"] == "none"
    assert "experiment_tags" not in forensic_event["outcome"]
