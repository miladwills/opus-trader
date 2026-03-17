import json
from pathlib import Path

from services.advisor_replay_analysis_service import AdvisorReplayAnalysisService


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _review(
    decision_id,
    decision_at,
    verdict,
    *,
    symbol="BTCUSDT",
    mode="long",
    decision_type="initial_entry",
    live_pnl=None,
    follow="entry_action_seen",
    confidence=0.8,
):
    outcome = None
    outcome_status = "unresolved"
    if live_pnl is not None:
        outcome = {
            "realized_pnl": live_pnl,
            "win": live_pnl > 0,
        }
        outcome_status = "linked"
    elif follow == "no_entry_action_seen":
        outcome_status = "not_executed"
    return {
        "decision_id": decision_id,
        "decision_at": decision_at,
        "bot_id": "bot-1",
        "symbol": symbol,
        "mode": mode,
        "decision_type": decision_type,
        "status": "ok",
        "verdict": verdict,
        "confidence": confidence,
        "entry_follow_through_status": follow,
        "outcome_status": outcome_status,
        "outcome": outcome,
        "compact_context": {"gate_blocked": follow == "no_entry_action_seen"},
        "local_alignment": "aligned",
    }


def _snapshot(snapshot_id, decision_at, *, symbol="BTCUSDT", mode="long", decision_type="initial_entry", blocked=False, submitted=False, realized_pnl=None, exit_reason=None):
    return {
        "snapshot_id": snapshot_id,
        "forensic_decision_id": snapshot_id,
        "trade_context_id": f"ctx:{snapshot_id}",
        "bot_id": "bt_bot",
        "symbol": symbol,
        "mode": mode,
        "profile": "normal",
        "side": "Buy",
        "decision_type": decision_type,
        "decision_at": decision_at,
        "last_updated_at": decision_at,
        "lifecycle": {
            "blocked": blocked,
            "submitted": submitted,
            "opened": submitted,
            "closed": realized_pnl is not None,
            "realized_pnl": realized_pnl,
            "exit_reason": exit_reason,
        },
    }


def _validation_payload(run_id, run_dir, *, symbol="BTCUSDT", mode="long", grade="B", score=82.0):
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": "ok",
        "comparison": {
            "symbol": symbol,
            "mode": mode,
            "window": {
                "start_time": "2026-03-10T00:00:00+00:00",
                "end_time": "2026-03-10T02:00:00+00:00",
            },
            "realism": {
                "grade": grade,
                "score": score,
            },
        },
    }


def _build_fixture(tmp_path: Path):
    advisor_review = tmp_path / "ai_advisor_review.json"
    _write_json(
        advisor_review,
        {
            "reviews": [
                _review("d1", "2026-03-10T00:15:00+00:00", "APPROVE", live_pnl=10.0),
                _review("d2", "2026-03-10T00:30:00+00:00", "REJECT", live_pnl=-4.0),
                _review("d3", "2026-03-10T00:45:00+00:00", "APPROVE", live_pnl=6.0),
                _review("d4", "2026-03-10T01:00:00+00:00", "REJECT", live_pnl=-3.0),
                _review("d5", "2026-03-10T01:15:00+00:00", "CAUTION", follow="no_entry_action_seen"),
            ]
        },
    )

    runs_root = tmp_path / "backtest_runs"
    run_good = runs_root / "run_good"
    _write_json(run_good / "validation.json", _validation_payload("run_good", run_good))
    _write_json(
        run_good / "decision_snapshots.json",
        {
            "snapshots": [
                _snapshot("s1", "2026-03-10T00:15:00+00:00", submitted=True, realized_pnl=12.0, exit_reason="quick_profit"),
                _snapshot("s2", "2026-03-10T00:30:00+00:00", submitted=True, realized_pnl=-5.0, exit_reason="stop_loss"),
                _snapshot("s3", "2026-03-10T00:45:00+00:00", submitted=True, realized_pnl=4.0, exit_reason="quick_profit"),
                _snapshot("s4", "2026-03-10T01:00:00+00:00", submitted=True, realized_pnl=-2.0, exit_reason="stop_loss"),
                _snapshot("s5", "2026-03-10T01:15:00+00:00", blocked=True),
            ]
        },
    )

    run_insufficient = runs_root / "run_insufficient"
    _write_json(
        run_insufficient / "validation.json",
        _validation_payload(
            "run_insufficient",
            run_insufficient,
            grade="INSUFFICIENT_DATA",
            score=None,
        ),
    )
    _write_json(run_insufficient / "decision_snapshots.json", {"snapshots": []})
    return advisor_review, runs_root


def test_advisor_replay_analysis_aggregates_live_and_replay_metrics(tmp_path):
    advisor_review, runs_root = _build_fixture(tmp_path)
    service = AdvisorReplayAnalysisService(
        advisor_review_path=str(advisor_review),
        runs_root=str(runs_root),
        file_path=str(tmp_path / "advisor_replay_analysis.json"),
    )

    payload = service.get_summary(force_refresh=True)
    summary = payload["summary"]

    assert summary["live_overall"]["verdict_counts"]["approve"] == 2
    assert summary["comparative_subset"]["matched_decision_count"] == 5
    assert summary["comparative_subset"]["live"]["approve"]["avg_pnl"] == 8.0
    assert summary["comparative_subset"]["replay"]["reject"]["avg_pnl"] == -3.5


def test_advisor_replay_analysis_grades_useful_when_live_and_replay_agree(tmp_path):
    advisor_review, runs_root = _build_fixture(tmp_path)
    service = AdvisorReplayAnalysisService(
        advisor_review_path=str(advisor_review),
        runs_root=str(runs_root),
        file_path=str(tmp_path / "advisor_replay_analysis.json"),
    )

    payload = service.get_summary(force_refresh=True)

    assert payload["summary"]["usefulness"]["grade"] == "USEFUL"
    assert (
        payload["summary"]["usefulness"]["reason"]
        == "approve_outperforms_reject_in_live_and_replay"
    )


def test_advisor_replay_analysis_handles_insufficient_data(tmp_path):
    advisor_review = tmp_path / "ai_advisor_review.json"
    _write_json(
        advisor_review,
        {
            "reviews": [
                _review("d1", "2026-03-10T00:15:00+00:00", "APPROVE", live_pnl=2.0),
                _review("d2", "2026-03-10T00:30:00+00:00", "REJECT", live_pnl=-1.0),
            ]
        },
    )
    runs_root = tmp_path / "backtest_runs"
    run_dir = runs_root / "run_small"
    _write_json(run_dir / "validation.json", _validation_payload("run_small", run_dir))
    _write_json(
        run_dir / "decision_snapshots.json",
        {
            "snapshots": [
                _snapshot("s1", "2026-03-10T00:15:00+00:00", submitted=True, realized_pnl=2.5),
                _snapshot("s2", "2026-03-10T00:30:00+00:00", submitted=True, realized_pnl=-0.5),
            ]
        },
    )
    service = AdvisorReplayAnalysisService(
        advisor_review_path=str(advisor_review),
        runs_root=str(runs_root),
        file_path=str(tmp_path / "advisor_replay_analysis.json"),
    )

    payload = service.get_summary(force_refresh=True)

    assert payload["summary"]["usefulness"]["grade"] == "INSUFFICIENT_DATA"


def test_advisor_replay_analysis_marks_unresolved_joins(tmp_path):
    advisor_review, runs_root = _build_fixture(tmp_path)
    extra_payload = json.loads(Path(advisor_review).read_text())
    extra_payload["reviews"].append(
        _review("d6", "2026-03-10T03:15:00+00:00", "APPROVE", live_pnl=1.0)
    )
    _write_json(advisor_review, extra_payload)

    service = AdvisorReplayAnalysisService(
        advisor_review_path=str(advisor_review),
        runs_root=str(runs_root),
        file_path=str(tmp_path / "advisor_replay_analysis.json"),
    )

    recent = service.get_recent(limit=20, force_refresh=True)["recent"]
    statuses = {row["decision_id"]: row["replay_match_status"] for row in recent}

    assert statuses["d6"] == "no_validated_window"


def test_advisor_replay_analysis_exposes_by_symbol_and_by_mode(tmp_path):
    advisor_review, runs_root = _build_fixture(tmp_path)
    service = AdvisorReplayAnalysisService(
        advisor_review_path=str(advisor_review),
        runs_root=str(runs_root),
        file_path=str(tmp_path / "advisor_replay_analysis.json"),
    )

    by_symbol = service.get_by_symbol(force_refresh=True)["rows"]
    by_mode = service.get_by_mode()["rows"]

    assert by_symbol[0]["symbol"] == "BTCUSDT"
    assert by_symbol[0]["usefulness"]["grade"] == "USEFUL"
    assert by_mode[0]["mode"] == "long"


def test_advisor_replay_analysis_safe_failure_returns_error_snapshot(tmp_path, monkeypatch):
    advisor_review, runs_root = _build_fixture(tmp_path)
    output_path = tmp_path / "advisor_replay_analysis.json"
    service = AdvisorReplayAnalysisService(
        advisor_review_path=str(advisor_review),
        runs_root=str(runs_root),
        file_path=str(output_path),
    )

    service.get_summary(force_refresh=True)
    monkeypatch.setattr(service, "_load_validated_runs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = service.get_summary(force_refresh=True)

    assert payload["error"] == "boom"
