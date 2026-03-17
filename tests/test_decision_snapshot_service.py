import json
from pathlib import Path

import config.strategy_config as strategy_cfg
from services.decision_snapshot_service import DecisionSnapshotService


class StubTradeForensicsService:
    def __init__(self, events):
        self.events = list(events or [])

    def get_recent_events(
        self,
        *,
        since_seconds=None,
        bot_id=None,
        symbol=None,
        event_type=None,
        limit=200,
    ):
        rows = list(self.events)
        if bot_id:
            rows = [row for row in rows if str(row.get("bot_id") or "").strip() == str(bot_id)]
        if symbol:
            normalized_symbol = str(symbol or "").strip().upper()
            rows = [
                row for row in rows if str(row.get("symbol") or "").strip().upper() == normalized_symbol
            ]
        if event_type:
            rows = [row for row in rows if str(row.get("event_type") or "").strip() == str(event_type)]
        if len(rows) > limit:
            return rows[-limit:]
        return rows


def _decision_event(
    *,
    forensic_decision_id="fdc:1",
    trade_context_id="ftc:1",
    timestamp="2026-03-11T10:00:00+00:00",
    symbol="ETHUSDT",
    bot_id="bot-1",
    side="buy",
):
    return {
        "event_type": "decision",
        "timestamp": timestamp,
        "forensic_decision_id": forensic_decision_id,
        "trade_context_id": trade_context_id,
        "bot_id": bot_id,
        "symbol": symbol,
        "mode": "long",
        "profile": "normal",
        "side": side,
        "decision_type": "initial_entry",
        "decision_context": {
            "local_decision": {
                "candidate_ready": True,
                "reason_to_enter": ["Breakout aligned", "Momentum supported", "Volume confirmed"],
                "setup_quality": {
                    "score": 73.4,
                    "band": "strong",
                    "entry_allowed": True,
                    "breakout_ready": True,
                    "summary": "Strong trend support",
                },
                "entry_signal": {
                    "code": "breakout",
                    "phase": "confirm",
                    "preferred": True,
                    "late": False,
                    "executable": True,
                },
                "gate": {
                    "blocked": False,
                    "reason": "Entry conditions favorable",
                    "blocked_by": [],
                },
                "blockers": [],
            },
            "market": {
                "last_price": 2011.12,
                "regime_effective": "UP",
                "regime_confidence": "high",
                "atr_5m_pct": 0.012,
                "atr_15m_pct": 0.021,
                "bbw_pct": 0.031,
                "rsi": 62.4,
                "adx": 24.9,
                "price_velocity": 0.18,
            },
            "position": {"side": None, "size": 0.0, "has_position": False},
            "risk": {
                "reduce_only_mode": False,
                "capital_starved": False,
                "volatility_block_opening_orders": False,
                "entry_gate_enabled": True,
                "entry_gate_bot_enabled": True,
                "entry_gate_global_master_applicable": True,
                "entry_gate_global_master_enabled": True,
                "entry_gate_contract_active": True,
            },
            "entry_story": {
                "candidate_ready": True,
                "readiness_stage": "trigger_ready",
                "signal_code": "breakout",
                "entry_gate_contract_active": True,
                "experiment_attribution_state": "none",
            },
            "watchdogs": {"position_cap_active": False, "capital_compression_active": False},
            "advisor": {
                "status": "ok",
                "verdict": "APPROVE",
                "confidence": 0.78,
                "model": "gpt-5-nano",
                "escalated": False,
                "summary": "Aligned with local structure",
            },
        },
        "linkage_method": "direct_runtime",
        "attribution_status": "linked",
    }


def _skip_event(*, forensic_decision_id="fdc:2", trade_context_id="ftc:2", timestamp="2026-03-11T10:05:00+00:00"):
    event = _decision_event(
        forensic_decision_id=forensic_decision_id,
        trade_context_id=trade_context_id,
        timestamp=timestamp,
    )
    event["event_type"] = "skip_blocked"
    event["exit"] = {"skip_reason": "entry_gate"}
    return event


def _order_event(*, forensic_decision_id="fdc:1", trade_context_id="ftc:1", timestamp="2026-03-11T10:00:05+00:00"):
    return {
        "event_type": "order_submitted",
        "timestamp": timestamp,
        "forensic_decision_id": forensic_decision_id,
        "trade_context_id": trade_context_id,
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "profile": "normal",
        "side": "buy",
        "decision_type": "initial_entry",
        "order": {"order_id": "ord-1", "order_link_id": "bv2:test", "qty": 0.05},
        "linkage_method": "ownership_snapshot",
        "attribution_status": "linked",
    }


def _position_opened_event(*, forensic_decision_id="fdc:1", trade_context_id="ftc:1", timestamp="2026-03-11T10:00:06+00:00"):
    return {
        "event_type": "position_opened",
        "timestamp": timestamp,
        "forensic_decision_id": forensic_decision_id,
        "trade_context_id": trade_context_id,
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "profile": "normal",
        "side": "buy",
        "decision_type": "initial_entry",
        "order": {"order_id": "ord-1", "order_link_id": "bv2:test", "price": 2011.12},
        "linkage_method": "direct_runtime",
        "attribution_status": "linked",
    }


def _outcome_event(*, forensic_decision_id="fdc:1", trade_context_id="ftc:1", timestamp="2026-03-11T10:25:00+00:00", pnl=4.5):
    return {
        "event_type": "realized_outcome",
        "timestamp": timestamp,
        "forensic_decision_id": forensic_decision_id,
        "trade_context_id": trade_context_id,
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "profile": "normal",
        "side": "buy",
        "decision_type": "initial_entry",
        "outcome": {
            "realized_pnl": pnl,
            "balance_after": 31.2,
            "win": pnl > 0,
            "order_id": "ord-1",
            "attribution_source": "ownership_snapshot",
            "total_fee": 0.08,
        },
        "linkage_method": "ownership_snapshot",
        "attribution_status": "linked",
    }


def _build_service(tmp_path, events, monkeypatch):
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_ENABLED", True)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_LOOKBACK_SECONDS", 86400)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_EVENT_LIMIT", 200)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_RECENT_LIMIT", 100)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_TTL_SECONDS", 30)
    return DecisionSnapshotService(
        trade_forensics_service=StubTradeForensicsService(events),
        file_path=str(tmp_path / "decision_snapshots.json"),
        now_fn=lambda: 1760000000.0,
    )


def test_decision_snapshot_creation_from_decision_event(tmp_path, monkeypatch):
    service = _build_service(tmp_path, [_decision_event()], monkeypatch)

    payload = service.get_recent_snapshots(limit=10, force_refresh=True)
    snapshot = payload["snapshots"][0]

    assert snapshot["snapshot_id"] == "fdc:1"
    assert snapshot["decision"]["candidate_ready"] is True
    assert snapshot["decision"]["entry_story"]["readiness_stage"] == "trigger_ready"
    assert snapshot["decision"]["setup_quality"]["score"] == 73.4
    assert snapshot["advisor"]["verdict"] == "APPROVE"
    assert snapshot["market_runtime"]["risk"]["entry_gate_contract_active"] is True
    assert snapshot["status"]["review_state"] == "decision_only"


def test_decision_snapshot_lifecycle_enrichment_updates_existing_snapshot(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        [_decision_event(), _order_event(), _position_opened_event(), _outcome_event()],
        monkeypatch,
    )

    snapshot = service.get_snapshot("fdc:1", force_refresh=True)["snapshot"]

    assert snapshot["lifecycle"]["submitted"] is True
    assert snapshot["lifecycle"]["opened"] is True
    assert snapshot["lifecycle"]["realized_pnl"] == 4.5
    assert snapshot["status"]["review_state"] == "complete"


def test_blocked_snapshot_stays_reviewable_without_trade(tmp_path, monkeypatch):
    service = _build_service(tmp_path, [_skip_event()], monkeypatch)

    snapshot = service.get_recent_snapshots(limit=10, force_refresh=True)["snapshots"][0]

    assert snapshot["status"]["blocked"] is True
    assert snapshot["lifecycle"]["skip_reason"] == "entry_gate"
    assert snapshot["status"]["review_state"] == "blocked_complete"


def test_late_outcome_refresh_enriches_existing_snapshot(tmp_path, monkeypatch):
    initial_events = [_decision_event(), _order_event(), _position_opened_event()]
    trade_service = StubTradeForensicsService(initial_events)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_ENABLED", True)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_LOOKBACK_SECONDS", 86400)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_EVENT_LIMIT", 200)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_RECENT_LIMIT", 100)
    monkeypatch.setattr(strategy_cfg, "DECISION_SNAPSHOT_TTL_SECONDS", 30)
    service = DecisionSnapshotService(
        trade_forensics_service=trade_service,
        file_path=str(tmp_path / "decision_snapshots.json"),
        now_fn=lambda: 1760000000.0,
    )

    first = service.get_snapshot("fdc:1", force_refresh=True)["snapshot"]
    assert first["lifecycle"]["realized_pnl"] is None
    assert first["status"]["review_state"] == "awaiting_outcome"

    trade_service.events.append(_outcome_event(pnl=-1.25))
    second = service.get_snapshot("fdc:1", force_refresh=True)["snapshot"]

    assert second["lifecycle"]["realized_pnl"] == -1.25
    assert second["lifecycle"]["win"] is False
    assert second["status"]["review_state"] == "complete"


def test_orphaned_lifecycle_without_decision_remains_partial(tmp_path, monkeypatch):
    service = _build_service(tmp_path, [_outcome_event(forensic_decision_id="", trade_context_id="ftc:orphan")], monkeypatch)

    snapshot = service.get_recent_snapshots(limit=10, force_refresh=True)["snapshots"][0]

    assert snapshot["orphaned"] is True
    assert snapshot["snapshot_id"] == "ftc:orphan"
    assert snapshot["status"]["review_state"] == "complete"
    assert snapshot["decision"]["reason_summary"] == []


def test_snapshot_refresh_safe_failure_uses_last_good_snapshot(tmp_path, monkeypatch):
    service = _build_service(tmp_path, [_decision_event()], monkeypatch)
    first = service.refresh_snapshot(force=True)

    class FailingTradeForensicsService:
        def get_recent_events(self, **kwargs):
            raise RuntimeError("forensics boom")

    failing = DecisionSnapshotService(
        trade_forensics_service=FailingTradeForensicsService(),
        file_path=str(tmp_path / "decision_snapshots.json"),
        now_fn=lambda: 1760000000.0,
    )
    payload = failing.get_recent_snapshots(limit=5, force_refresh=True)

    assert first["snapshots"][0]["snapshot_id"] == "fdc:1"
    assert payload["snapshots"][0]["snapshot_id"] == "fdc:1"
    assert payload["error"] == "forensics boom"


def test_snapshot_payload_stays_compact(tmp_path, monkeypatch):
    noisy = _decision_event()
    noisy["decision_context"]["local_decision"]["reason_to_enter"] = ["x" * 300] * 5
    noisy["decision_context"]["local_decision"]["blockers"] = [
        {"code": "c", "reason": "r" * 300, "phase": "p", "side": "s"}
        for _ in range(6)
    ]
    service = _build_service(tmp_path, [noisy], monkeypatch)

    snapshot = service.get_recent_snapshots(limit=5, force_refresh=True)["snapshots"][0]

    assert len(snapshot["decision"]["reason_summary"]) == 3
    assert len(snapshot["decision"]["blockers"]) == 4
    assert snapshot["decision"]["reason_summary"][0].endswith("...")
    assert snapshot["decision"]["blockers"][0]["reason"].endswith("...")
