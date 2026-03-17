from services.audit_diagnostics_service import AuditDiagnosticsService
from services.pnl_service import PnlService
from services.symbol_pnl_service import SymbolPnlService


class _ClientStub:
    pass


def _make_pnl_service(tmp_path):
    audit_service = AuditDiagnosticsService(str(tmp_path / "audit.jsonl"))
    symbol_pnl = SymbolPnlService(str(tmp_path / "symbol_pnl.json"))
    return PnlService(
        _ClientStub(),
        str(tmp_path / "trade_logs.json"),
        symbol_pnl_service=symbol_pnl,
        audit_diagnostics_service=audit_service,
    )


def _watchdog_events(service, watchdog_type):
    return service.audit_diagnostics_service.get_recent_events(
        event_type="watchdog_event",
        limit=50,
    )


def test_loss_asymmetry_watchdog_emits_for_high_win_rate_negative_pnl(tmp_path):
    service = _make_pnl_service(tmp_path)
    logs = [
        {"time": f"2026-03-11T10:00:0{i}+00:00", "symbol": "BTCUSDT", "bot_id": "bot-1", "realized_pnl": pnl}
        for i, pnl in enumerate([0.4, 0.35, 0.3, 0.25, -2.2, 0.2], start=1)
    ]

    service._run_scope_watchdogs(logs, bot_ids={"bot-1"})

    events = _watchdog_events(service, "loss_asymmetry")
    matching = [event for event in events if event.get("watchdog_type") == "loss_asymmetry"]
    assert len(matching) == 1
    assert matching[0]["reason"] == "high_win_rate_negative_pnl"
    assert matching[0]["compact_metrics"]["win_rate"] > 60


def test_exit_stack_watchdog_emits_for_forced_exit_concentration(tmp_path, monkeypatch):
    service = _make_pnl_service(tmp_path)
    monkeypatch.setattr(AuditDiagnosticsService, "enabled", staticmethod(lambda: True))
    for index in range(4):
        service.audit_diagnostics_service.record_event(
            {
                "event_type": "exit_reason",
                "severity": "WARN",
                "bot_id": "bot-2",
                "symbol": "ETHUSDT",
                "mode": "long",
                "reason": "inventory_emergency_reduce",
            },
            throttle_key=f"exit:{index}",
            throttle_sec=0,
        )
    logs = [
        {"time": "2026-03-11T10:00:01+00:00", "symbol": "ETHUSDT", "bot_id": "bot-2", "realized_pnl": -0.8},
        {"time": "2026-03-11T10:00:02+00:00", "symbol": "ETHUSDT", "bot_id": "bot-2", "realized_pnl": 0.2},
        {"time": "2026-03-11T10:00:03+00:00", "symbol": "ETHUSDT", "bot_id": "bot-2", "realized_pnl": -0.4},
        {"time": "2026-03-11T10:00:04+00:00", "symbol": "ETHUSDT", "bot_id": "bot-2", "realized_pnl": 0.1},
    ]

    service._run_scope_watchdogs(logs, bot_ids={"bot-2"})

    events = _watchdog_events(service, "exit_stack")
    matching = [event for event in events if event.get("watchdog_type") == "exit_stack"]
    assert len(matching) == 1
    assert matching[0]["reason"] == "forced_exit_concentration"


def test_pnl_attribution_watchdog_emits_for_unresolved_share_and_cost_drag(tmp_path):
    service = _make_pnl_service(tmp_path)
    logs = [
        {
            "time": f"2026-03-11T10:00:0{i}+00:00",
            "symbol": "SOLUSDT",
            "realized_pnl": pnl,
            "attribution_source": source,
            "total_fee": fee,
        }
        for i, (pnl, source, fee) in enumerate(
            [
                (-0.20, "ambiguous_symbol", 0.08),
                (0.05, "unattributed", 0.07),
                (-0.04, "order_link_id_unresolved", 0.06),
                (0.03, "unique_symbol_fallback", 0.05),
                (-0.01, "explicit_order_link_id_unmapped", 0.05),
            ],
            start=1,
        )
    ]

    service._run_scope_watchdogs(logs, symbols={"SOLUSDT"})

    events = _watchdog_events(service, "pnl_attribution")
    matching = [event for event in events if event.get("watchdog_type") == "pnl_attribution"]
    reasons = sorted(event["reason"] for event in matching)
    assert reasons == ["ambiguous_attribution", "attribution_gap", "known_cost_drag_material"]


def test_trade_window_stats_ignore_unresolved_labels_when_bot_metadata_exists(tmp_path):
    service = _make_pnl_service(tmp_path)
    stats = service._build_trade_window_stats(
        [
            {
                "time": "2026-03-11T10:00:01+00:00",
                "symbol": "SOLUSDT",
                "realized_pnl": -0.2,
                "attribution_source": "unattributed",
                "bot_id": "bot-sol-1",
            },
            {
                "time": "2026-03-11T10:00:02+00:00",
                "symbol": "SOLUSDT",
                "realized_pnl": 0.1,
                "attribution_source": "ambiguous_symbol",
                "bot_id": "bot-sol-1",
            },
        ]
    )

    assert stats["unresolved_sources"] == 0
    assert stats["ambiguous_sources"] == 0
