import json
from pathlib import Path

from services.trade_forensics_service import TradeForensicsService


def _read_jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_trade_forensics_records_bounded_payload_shape(tmp_path):
    service = TradeForensicsService(str(tmp_path / "trade_forensics.jsonl"))

    ok = service.record_event(
        {
            "event_type": "decision",
            "forensic_decision_id": "fdc:test",
            "trade_context_id": "ftc:test",
            "bot_id": "bot-1",
            "symbol": "ethusdt",
            "mode": "long",
            "profile": "normal",
            "side": "buy",
            "decision_type": "initial_entry",
            "decision_context": {
                "local_decision": {
                    "reason_to_enter": [
                        "a" * 300,
                        "b" * 300,
                        "c" * 300,
                        "d" * 300,
                        "e" * 300,
                    ]
                }
            },
            "advisor": {
                "summary": "s" * 300,
                "reasons": ["x" * 300, "y" * 300, "z" * 300, "q" * 300, "extra"],
            },
        }
    )

    assert ok is True
    records = _read_jsonl(Path(service.file_path))
    assert records[0]["symbol"] == "ETHUSDT"
    assert len(records[0]["decision_context"]["local_decision"]["reason_to_enter"]) == 4
    assert records[0]["advisor"]["summary"].endswith("...")
    assert len(records[0]["advisor"]["reasons"]) == 4


def test_trade_forensics_groups_recent_lifecycles(tmp_path):
    service = TradeForensicsService(str(tmp_path / "trade_forensics.jsonl"))
    events = [
        {
            "event_type": "decision",
            "timestamp": "2026-03-11T10:00:00+00:00",
            "forensic_decision_id": "fdc:1",
            "trade_context_id": "ftc:1",
            "bot_id": "bot-1",
            "symbol": "ETHUSDT",
            "side": "buy",
            "decision_type": "initial_entry",
            "decision_context": {"market": {"last_price": 2010.1}},
        },
        {
            "event_type": "order_submitted",
            "timestamp": "2026-03-11T10:00:05+00:00",
            "forensic_decision_id": "fdc:1",
            "trade_context_id": "ftc:1",
            "bot_id": "bot-1",
            "symbol": "ETHUSDT",
            "side": "buy",
            "decision_type": "initial_entry",
            "order": {"order_id": "ord-1"},
        },
        {
            "event_type": "realized_outcome",
            "timestamp": "2026-03-11T10:30:00+00:00",
            "forensic_decision_id": "fdc:1",
            "trade_context_id": "ftc:1",
            "bot_id": "bot-1",
            "symbol": "ETHUSDT",
            "side": "buy",
            "decision_type": "initial_entry",
            "outcome": {"realized_pnl": 3.25, "win": True},
        },
    ]

    for event in events:
        assert service.record_event(event) is True

    lifecycles = service.get_recent_lifecycles(limit=5)

    assert lifecycles[0]["trade_context_id"] == "ftc:1"
    assert lifecycles[0]["event_count"] == 3
    assert lifecycles[0]["latest_outcome"]["realized_pnl"] == 3.25
    assert "order_submitted" in lifecycles[0]["event_types"]


def test_trade_forensics_unresolved_linkage_stays_unlinked(tmp_path):
    service = TradeForensicsService(str(tmp_path / "trade_forensics.jsonl"))

    assert service.record_event(
        {
            "event_type": "realized_outcome",
            "timestamp": "2026-03-11T11:00:00+00:00",
            "bot_id": "bot-2",
            "symbol": "SOLUSDT",
            "outcome": {"realized_pnl": -1.2},
        }
    )

    lifecycles = service.get_recent_lifecycles(limit=5)
    summary = service.get_summary()

    assert lifecycles[0]["lifecycle_id"].startswith("unlinked:")
    assert summary["unresolved_event_count"] == 1


def test_trade_forensics_safe_failure_returns_false(tmp_path):
    service = TradeForensicsService(str(tmp_path / "trade_forensics.jsonl"))
    service.file_path = tmp_path

    ok = service.record_event({"event_type": "decision", "bot_id": "bot-1"})

    assert ok is False


def test_trade_forensics_dedupes_repeated_same_decision(tmp_path):
    service = TradeForensicsService(str(tmp_path / "trade_forensics.jsonl"))
    payload = {
        "event_type": "decision",
        "bot_id": "bot-1",
        "symbol": "BTCUSDT",
        "forensic_decision_id": "fdc:1",
        "trade_context_id": "ftc:1",
        "decision_type": "grid_opening",
        "decision_fingerprint": "abc123",
        "decision_context": {"candidate_counts": {"buy": 1, "sell": 0}},
    }

    assert service.record_event(payload, dedupe_key="k1", dedupe_ttl=60) is True
    assert service.record_event(payload, dedupe_key="k1", dedupe_ttl=60) is False
    assert len(_read_jsonl(Path(service.file_path))) == 1
