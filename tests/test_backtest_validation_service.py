import json
from pathlib import Path

import pytest

from services.backtest_validation_service import BacktestValidationService


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _snapshot(snapshot_id, decision_at, *, symbol="BTCUSDT", mode="long", blocked=False, submitted=False, closed=False, realized_pnl=None):
    return {
        "snapshot_id": snapshot_id,
        "forensic_decision_id": snapshot_id,
        "trade_context_id": f"ctx:{snapshot_id}",
        "bot_id": "bot-1",
        "symbol": symbol,
        "mode": mode,
        "profile": "normal",
        "side": "Buy",
        "decision_type": "initial_entry",
        "decision_at": decision_at,
        "last_updated_at": decision_at,
        "decision": {"reason_summary": ["synthetic"]},
        "advisor": {},
        "lifecycle": {
            "blocked": blocked,
            "submitted": submitted,
            "opened": submitted,
            "closed": closed,
            "realized_pnl": realized_pnl,
            "outcome_status": "blocked" if blocked else ("realized" if closed else "submitted"),
        },
    }


def _forensic_event(event_type, timestamp, *, suffix, symbol="BTCUSDT", mode="long", exit_reason=None, hold_time_sec=None, realized_pnl=None):
    payload = {
        "event_type": event_type,
        "timestamp": timestamp,
        "recorded_at": timestamp,
        "forensic_decision_id": f"fd:{suffix}",
        "trade_context_id": f"tc:{suffix}",
        "bot_id": "bot-1",
        "symbol": symbol,
        "mode": mode,
        "profile": "normal",
        "side": "Buy",
        "decision_type": "initial_entry",
        "linkage_method": "direct_runtime",
        "attribution_status": "linked",
    }
    if event_type == "skip_blocked":
        payload["event_status"] = "blocked"
        payload["decision_context"] = {
            "local_decision": {
                "gate": {"blocked": True, "reason": "synthetic_block"},
                "blockers": [{"code": "synthetic_block", "reason": "blocked"}],
            }
        }
    elif event_type == "decision":
        payload["event_status"] = "candidate"
        payload["decision_context"] = {
            "local_decision": {
                "gate": {"blocked": False},
                "reason_to_enter": ["synthetic"],
            }
        }
    elif event_type == "order_submitted":
        payload["event_status"] = "submitted"
        payload["order"] = {"order_id": f"oid:{suffix}", "qty": 1.0}
    elif event_type == "realized_outcome":
        payload["event_status"] = "realized"
        payload["exit"] = {
            "close_reason": exit_reason,
            "hold_time_sec": hold_time_sec,
        }
        payload["outcome"] = {
            "realized_pnl": realized_pnl,
            "order_id": f"oid:{suffix}",
        }
    return payload


def _build_validation_fixture(tmp_path: Path):
    runs_root = tmp_path / "backtest_runs"
    run_dir = runs_root / "run_alpha"
    _write_json(
        run_dir / "results.json",
        {
            "run_id": "run_alpha",
            "symbol": "BTCUSDT",
            "mode": "long",
            "start_time": "2026-03-10T00:00:00+00:00",
            "end_time": "2026-03-10T01:00:00+00:00",
            "assumptions": {
                "fees": {"taker_fee_bps": 5.0},
                "slippage": {"market_slippage_bps": 5.0},
            },
        },
    )
    _write_json(
        run_dir / "trade_logs.json",
        [
            {
                "id": "r1",
                "time": "2026-03-10T00:15:00+00:00",
                "symbol": "BTCUSDT",
                "bot_mode": "long",
                "realized_pnl": 12.0,
                "total_fee": 1.0,
                "attribution_source": "ownership_snapshot",
            },
            {
                "id": "r2",
                "time": "2026-03-10T00:45:00+00:00",
                "symbol": "BTCUSDT",
                "bot_mode": "long",
                "realized_pnl": -3.0,
                "total_fee": 0.8,
                "attribution_source": "ownership_snapshot",
            },
        ],
    )
    _write_json(
        run_dir / "decision_snapshots.json",
        {
            "version": 1,
            "updated_at": "2026-03-10T01:00:00+00:00",
            "metadata": {},
            "summary": {},
            "error": None,
            "snapshots": [
                _snapshot("snap-1", "2026-03-10T00:15:00+00:00", submitted=True, closed=True, realized_pnl=12.0),
                _snapshot("snap-2", "2026-03-10T00:30:00+00:00", blocked=True),
            ],
        },
    )
    _write_jsonl(
        run_dir / "trade_forensics.jsonl",
        [
            _forensic_event("decision", "2026-03-10T00:15:00+00:00", suffix="a"),
            _forensic_event("order_submitted", "2026-03-10T00:15:05+00:00", suffix="a"),
            _forensic_event(
                "realized_outcome",
                "2026-03-10T00:25:00+00:00",
                suffix="a",
                exit_reason="quick_profit",
                hold_time_sec=600,
                realized_pnl=12.0,
            ),
            _forensic_event("skip_blocked", "2026-03-10T00:30:00+00:00", suffix="b"),
        ],
    )

    live_trade_logs = tmp_path / "live_trade_logs.json"
    _write_json(
        live_trade_logs,
        [
            {
                "id": "l1",
                "time": "2026-03-10T00:15:00+00:00",
                "symbol": "BTCUSDT",
                "bot_mode": "long",
                "realized_pnl": 8.0,
                "total_fee": 0.7,
                "attribution_source": "ownership_snapshot",
            }
        ],
    )
    live_forensics = tmp_path / "live_trade_forensics.jsonl"
    _write_jsonl(
        live_forensics,
        [
            _forensic_event("decision", "2026-03-10T00:15:00+00:00", suffix="live-a"),
            _forensic_event("order_submitted", "2026-03-10T00:15:05+00:00", suffix="live-a"),
            _forensic_event(
                "realized_outcome",
                "2026-03-10T00:32:00+00:00",
                suffix="live-a",
                exit_reason="stop_loss",
                hold_time_sec=1020,
                realized_pnl=8.0,
            ),
            _forensic_event("skip_blocked", "2026-03-10T00:30:00+00:00", suffix="live-b"),
        ],
    )
    return runs_root, live_trade_logs, live_forensics


def test_validation_compares_replay_vs_live_counts_and_stats(tmp_path):
    runs_root, live_trade_logs, live_forensics = _build_validation_fixture(tmp_path)
    service = BacktestValidationService(
        runs_root=str(runs_root),
        live_trade_logs_path=str(live_trade_logs),
        live_trade_forensics_path=str(live_forensics),
    )

    payload = service.validate_run(run_id="run_alpha")

    counts = payload["comparison"]["count_metrics"]
    assert counts["trade_count_diff"] == 1
    assert counts["decision_count_diff"] == 0
    assert payload["comparison"]["trade_metrics"]["diff"]["avg_pnl"] == -3.5
    assert payload["comparison"]["decision_alignment"]["alignment_rate"] == 1.0


def test_validation_classifies_mismatch_categories(tmp_path):
    runs_root, live_trade_logs, live_forensics = _build_validation_fixture(tmp_path)
    service = BacktestValidationService(
        runs_root=str(runs_root),
        live_trade_logs_path=str(live_trade_logs),
        live_trade_forensics_path=str(live_forensics),
    )

    payload = service.validate_run(run_id="run_alpha")
    categories = {item["type"] for item in payload["comparison"]["mismatch_categories"]}

    assert "entry_count_mismatch" in categories
    assert "exit_reason_mismatch" in categories
    assert "pnl_distribution_mismatch" in categories


def test_validation_handles_unresolved_live_reference_gracefully(tmp_path):
    runs_root, _live_trade_logs, _live_forensics = _build_validation_fixture(tmp_path)
    empty_live_logs = tmp_path / "empty_live_trade_logs.json"
    empty_live_forensics = tmp_path / "empty_live_trade_forensics.jsonl"
    _write_json(empty_live_logs, [])
    _write_jsonl(empty_live_forensics, [])
    service = BacktestValidationService(
        runs_root=str(runs_root),
        live_trade_logs_path=str(empty_live_logs),
        live_trade_forensics_path=str(empty_live_forensics),
    )

    payload = service.validate_run(run_id="run_alpha")

    assert payload["comparison"]["realism"]["grade"] == "INSUFFICIENT_DATA"
    assert payload["comparison"]["reference_quality"]["insufficient_live_data"] is True


def test_validation_reports_assumption_sensitivity(tmp_path):
    runs_root, live_trade_logs, live_forensics = _build_validation_fixture(tmp_path)
    service = BacktestValidationService(
        runs_root=str(runs_root),
        live_trade_logs_path=str(live_trade_logs),
        live_trade_forensics_path=str(live_forensics),
    )

    payload = service.validate_run(run_id="run_alpha")
    scenarios = {row["name"]: row for row in payload["sensitivity"]["scenarios"]}

    assert scenarios["baseline"]["adjusted_net_pnl"] == 9.0
    assert (
        scenarios["conservative_costs"]["adjusted_net_pnl"]
        < scenarios["slippage_plus_2_5bps"]["adjusted_net_pnl"]
        < scenarios["baseline"]["adjusted_net_pnl"]
    )


def test_validation_fails_cleanly_for_invalid_results(tmp_path):
    runs_root = tmp_path / "backtest_runs"
    run_dir = runs_root / "broken_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text("{not-json", encoding="utf-8")
    service = BacktestValidationService(
        runs_root=str(runs_root),
        live_trade_logs_path=str(tmp_path / "live.json"),
        live_trade_forensics_path=str(tmp_path / "live.jsonl"),
    )

    with pytest.raises(ValueError):
        service.validate_run(run_id="broken_run")
