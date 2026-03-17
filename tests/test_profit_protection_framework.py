from unittest.mock import Mock

from services.adaptive_profit_protection_service import (
    AdaptiveProfitProtectionService,
)
from services.audit_diagnostics_service import AuditDiagnosticsService
from services.grid_bot_service import GridBotService
from services.pnl_service import PnlService
from services.trade_forensics_service import TradeForensicsService
from services.watchdog_diagnostics_service import WatchdogDiagnosticsService
from services.watchdog_hub_service import WatchdogHubService


def _make_grid_service(tmp_path, monkeypatch, now_ts=1000.0):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False)
    )
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client._get_now_ts.return_value = now_ts
    service.audit_diagnostics_service = AuditDiagnosticsService(str(tmp_path / "audit.jsonl"))
    service.trade_forensics_service = TradeForensicsService(
        str(tmp_path / "trade_forensics.jsonl")
    )
    service.adaptive_profit_protection_service = AdaptiveProfitProtectionService()
    watchdog_service = WatchdogDiagnosticsService(service.audit_diagnostics_service)
    watchdog_service._watchdog_hub_service = WatchdogHubService(
        service.audit_diagnostics_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    service._watchdog_diagnostics_service = watchdog_service
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._normalize_experiment_tags = GridBotService._normalize_experiment_tags.__get__(
        service, GridBotService
    )
    service._merge_experiment_details = GridBotService._merge_experiment_details.__get__(
        service, GridBotService
    )
    service._emit_audit_event = GridBotService._emit_audit_event.__get__(
        service, GridBotService
    )
    service._touch_watchdog_summary = GridBotService._touch_watchdog_summary
    service._record_watchdog_operational_event = (
        GridBotService._record_watchdog_operational_event.__get__(
            service, GridBotService
        )
    )
    service._get_watchdog_diagnostics_service = lambda: watchdog_service
    service._compact_profit_protection_payload = (
        GridBotService._compact_profit_protection_payload
    )
    service._compact_profit_protection_shadow_payload = (
        GridBotService._compact_profit_protection_shadow_payload
    )
    service._record_trade_forensic_profit_protection_event = (
        GridBotService._record_trade_forensic_profit_protection_event.__get__(
            service, GridBotService
        )
    )
    service._emit_profit_protection_watchdog = (
        GridBotService._emit_profit_protection_watchdog.__get__(
            service, GridBotService
        )
    )
    service._record_profit_protection_event = (
        GridBotService._record_profit_protection_event.__get__(
            service, GridBotService
        )
    )
    service._classify_profit_protection_shadow_outcome = (
        GridBotService._classify_profit_protection_shadow_outcome
    )
    service._finalize_profit_protection_shadow_state = (
        GridBotService._finalize_profit_protection_shadow_state.__get__(
            service, GridBotService
        )
    )
    service._update_profit_protection_shadow_state = (
        GridBotService._update_profit_protection_shadow_state.__get__(
            service, GridBotService
        )
    )
    service._run_adaptive_profit_protection_layer = (
        GridBotService._run_adaptive_profit_protection_layer.__get__(
            service, GridBotService
        )
    )
    service._get_exchange_truth_opening_blocker = (
        GridBotService._get_exchange_truth_opening_blocker.__get__(
            service, GridBotService
        )
    )
    service._build_close_order_link_id = GridBotService._build_close_order_link_id
    service._confirm_symbol_cleanup_state = Mock(return_value={
        "success": True, "flat": True, "orders_cleared": True, "cleanup_confirmed": True,
    })
    service._resolve_position_idx = Mock(return_value=1)
    service._create_order_checked = Mock(return_value={"success": True, "retCode": 0})
    service._is_position_empty_close_result = (
        GridBotService._is_position_empty_close_result
    )
    service._clear_profit_protection_runtime_state = (
        GridBotService._clear_profit_protection_runtime_state.__get__(
            service, GridBotService
        )
    )
    service._build_persistent_ownership_snapshot = (
        GridBotService._build_persistent_ownership_snapshot.__get__(
            service, GridBotService
        )
    )
    service._entry_gate_truth_fields = GridBotService._entry_gate_truth_fields.__get__(
        service, GridBotService
    )
    service._entry_gate_disabled_reason = GridBotService._entry_gate_disabled_reason
    service._build_compact_entry_story = GridBotService._build_compact_entry_story.__get__(
        service, GridBotService
    )
    service._compact_story_text = GridBotService._compact_story_text
    service._compact_directional_opening_sizing_fields = (
        GridBotService._compact_directional_opening_sizing_fields.__get__(
            service, GridBotService
        )
    )
    return service


def _base_bot(mode):
    return {
        "id": "bot-profit-protect",
        "symbol": "BTCUSDT",
        "mode": "long",
        "profile": "normal",
        "profit_protection_mode": mode,
        "forensic_active_decision_id": "fdc:1",
        "forensic_active_trade_context_id": "ftc:1",
        "forensic_active_decision_type": "initial_entry",
        "regime_effective": "SIDEWAYS",
        "regime_confidence": "low",
    }


def _base_position(upnl="1.2", size="3"):
    return {
        "side": "Buy",
        "size": size,
        "positionValue": "300",
        "unrealisedPnl": upnl,
    }


def _weak_long_indicators():
    return {
        "atr_pct": 0.01,
        "adx": 12,
        "rsi": 71,
        "price_velocity": -0.02,
        "ema_slope": -0.01,
    }


def test_advisory_only_emits_exit_advice_without_trade(tmp_path, monkeypatch):
    service = _make_grid_service(tmp_path, monkeypatch)
    bot = _base_bot("advisory_only")

    result = service._run_adaptive_profit_protection_layer(
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_base_position(),
        last_price=100.0,
        exec_indicators=_weak_long_indicators(),
        profit_pct=0.009,
        peak_profit_pct=0.014,
    )

    assert result["advisory"]["decision"] == "exit_now"
    assert result["action_executed"] is False
    service._create_order_checked.assert_not_called()
    audit_events = service.audit_diagnostics_service.get_recent_events(
        event_type="exit_advisory_exit",
        limit=5,
    )
    assert audit_events[-1]["profit_protection"]["reason_family"] == "exhaustion_risk"
    watchdog_events = service.audit_diagnostics_service.get_recent_events(
        event_type="watchdog_event",
        limit=5,
    )
    assert watchdog_events[-1]["watchdog_type"] == "profit_protection"
    assert watchdog_events[-1]["reason"] == "exit_now_advised"


def test_shadow_mode_records_trigger_and_saved_giveback_without_trade(
    tmp_path, monkeypatch
):
    service = _make_grid_service(tmp_path, monkeypatch)
    bot = _base_bot("shadow")

    service._run_adaptive_profit_protection_layer(
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_base_position(upnl="1.4"),
        last_price=100.0,
        exec_indicators=_weak_long_indicators(),
        profit_pct=0.01,
        peak_profit_pct=0.014,
    )
    service.client._get_now_ts.return_value = 1060.0
    service._run_adaptive_profit_protection_layer(
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_base_position(upnl="0.6"),
        last_price=100.0,
        exec_indicators=_weak_long_indicators(),
        profit_pct=0.005,
        peak_profit_pct=0.014,
    )

    service._create_order_checked.assert_not_called()
    assert bot["profit_protection_shadow"]["result"] == "saved_giveback"
    events = service.audit_diagnostics_service.get_recent_events(limit=20)
    event_types = [event["event_type"] for event in events]
    assert "profit_lock_shadow_triggered" in event_types
    assert "profit_lock_saved_giveback" in event_types


def test_partial_live_uses_reduce_only_partial_close(tmp_path, monkeypatch):
    service = _make_grid_service(tmp_path, monkeypatch)
    bot = _base_bot("partial_live")

    result = service._run_adaptive_profit_protection_layer(
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_base_position(size="3"),
        last_price=100.0,
        exec_indicators=_weak_long_indicators(),
        profit_pct=0.008,
        peak_profit_pct=0.013,
    )

    assert result["action_executed"] is True
    kwargs = service._create_order_checked.call_args.kwargs
    assert kwargs["reduce_only"] is True
    assert kwargs["qty"] < 3.0
    assert kwargs["diagnostic_context"]["close_reason"] == "profit_protection_partial"
    events = service.audit_diagnostics_service.get_recent_events(
        event_type="profit_lock_partial_executed",
        limit=5,
    )
    assert events[-1]["profit_protection"]["decision"] == "exit_now"


def test_full_live_blocks_when_exchange_truth_is_untrusted(tmp_path, monkeypatch):
    service = _make_grid_service(tmp_path, monkeypatch)
    bot = _base_bot("full_live")
    bot["exchange_reconciliation"] = {
        "status": "diverged",
        "mismatches": ["position_size"],
    }

    result = service._run_adaptive_profit_protection_layer(
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_base_position(size="3"),
        last_price=100.0,
        exec_indicators=_weak_long_indicators(),
        profit_pct=0.007,
        peak_profit_pct=0.013,
    )

    assert result["action_executed"] is False
    assert result["advisory"]["blocked"] is True
    assert result["advisory"]["blocked_reason"] == "reconciliation_diverged"
    service._create_order_checked.assert_not_called()


def test_full_live_can_full_close_when_allowed(tmp_path, monkeypatch):
    service = _make_grid_service(tmp_path, monkeypatch)
    bot = _base_bot("full_live")

    result = service._run_adaptive_profit_protection_layer(
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_base_position(size="3"),
        last_price=100.0,
        exec_indicators=_weak_long_indicators(),
        profit_pct=0.007,
        peak_profit_pct=0.013,
    )

    assert result["action_executed"] is True
    kwargs = service._create_order_checked.call_args.kwargs
    assert kwargs["reduce_only"] is True
    assert kwargs["qty"] == 3.0
    assert kwargs["diagnostic_context"]["close_reason"] == "profit_protection_full"
    events = service.audit_diagnostics_service.get_recent_events(
        event_type="profit_lock_full_executed",
        limit=5,
    )
    assert events[-1]["profit_protection"]["last_action"] == "profit_protection_full"


def test_profit_protection_fields_persist_into_outcome_forensics(tmp_path, monkeypatch):
    service = _make_grid_service(tmp_path, monkeypatch)
    bot = _base_bot("shadow")
    bot["profit_protection_advisory"] = {
        "mode": "shadow",
        "decision": "exit_now",
        "reason_family": "exhaustion_risk",
        "current_profit_pct": 0.009,
        "peak_profit_pct": 0.014,
        "giveback_pct": 0.005,
        "giveback_threshold_pct": 0.0045,
        "actionable": True,
        "armed": True,
    }
    bot["profit_protection_shadow"] = {
        "active": False,
        "status": "resolved",
        "result": "saved_giveback",
        "trigger_profit_pct": 0.01,
        "saved_giveback_pct": 0.003,
    }

    snapshot = service._build_persistent_ownership_snapshot(
        bot,
        order_link_id="cls:bot-prof:0000PPAR",
        reduce_only=True,
        diagnostic_context={
            "ownership_action": "profit_protection_partial",
            "close_reason": "profit_protection_partial",
        },
    )

    pnl_service = PnlService.__new__(PnlService)
    pnl_service.trade_forensics_service = TradeForensicsService(
        str(tmp_path / "trade_forensics_outcome.jsonl")
    )
    pnl_service.audit_diagnostics_service = AuditDiagnosticsService(
        str(tmp_path / "audit_outcome.jsonl")
    )

    pnl_service._record_trade_forensic_outcome(
        {
            "id": "trade-pp-1",
            "time": "2026-03-14T09:00:00+00:00",
            "bot_id": bot["id"],
            "symbol": "BTCUSDT",
            "bot_mode": "long",
            "bot_profile": "normal",
            "side": "Sell",
            "realized_pnl": 1.05,
            "order_id": "oid-pp-1",
            "order_link_id": "ol-pp-1",
            "position_idx": 1,
            "attribution_source": "ownership_snapshot",
        },
        ownership_snapshot=snapshot,
    )

    event = pnl_service.trade_forensics_service.get_recent_events(
        event_type="realized_outcome",
        limit=5,
    )[-1]
    assert event["outcome"]["profit_protection_advisory"]["decision"] == "exit_now"
    assert event["outcome"]["profit_protection_shadow"]["result"] == "saved_giveback"


def test_profit_protection_watchdog_runtime_resolves_after_advice_clears(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(
        AuditDiagnosticsService, "summary_enabled", staticmethod(lambda: False)
    )
    audit_service = AuditDiagnosticsService(str(tmp_path / "audit_watchdog.jsonl"))
    hub_service = WatchdogHubService(
        audit_service,
        file_path=str(tmp_path / "watchdog_active_state.json"),
    )
    payload = {
        "event_type": "watchdog_event",
        "watchdog_type": "profit_protection",
        "severity": "WARN",
        "timestamp": "2026-03-14T09:00:00+00:00",
        "bot_id": "bot-profit-protect",
        "symbol": "BTCUSDT",
        "reason": "exit_now_advised",
        "compact_metrics": {"decision": "exit_now"},
    }
    assert audit_service.record_event(payload, throttle_key="pp", throttle_sec=0) is True
    assert hub_service.record_watchdog_event(payload) is True

    active_snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-profit-protect",
                "symbol": "BTCUSDT",
                "profit_protection_decision": "exit_now",
                "profit_protection_actionable": True,
            }
        ],
        include_registry=True,
    )
    assert active_snapshot["overview"]["total_active_issues"] == 1

    resolved_snapshot = hub_service.build_snapshot(
        runtime_bots=[
            {
                "id": "bot-profit-protect",
                "symbol": "BTCUSDT",
                "profit_protection_decision": "wait",
                "profit_protection_actionable": False,
            }
        ],
        include_registry=True,
    )
    assert resolved_snapshot["overview"]["total_active_issues"] == 0
    assert resolved_snapshot["issue_registry"][0]["resolution_reason"] == "runtime_cleared"
