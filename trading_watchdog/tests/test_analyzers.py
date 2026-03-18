"""Tests for analyzers."""

import pytest
from trading_watchdog.analyzers.truth_analyzer import analyze_truth
from trading_watchdog.analyzers.readiness_analyzer import analyze_readiness
from trading_watchdog.analyzers.blocker_analyzer import analyze_blockers
from trading_watchdog.analyzers.drift_analyzer import analyze_drift
from trading_watchdog.analyzers.fit_analyzer import analyze_fit
from trading_watchdog.analyzers.funnel_analyzer import analyze_funnel
from trading_watchdog.analyzers.experiment_analyzer import analyze_experiments


def _bot(overrides=None):
    base = {
        "id": "b1",
        "symbol": "BTCUSDT",
        "status": "running",
        "stable_readiness_stage": "watch",
        "stable_readiness_reason": "watch_setup",
        "display_readiness_score": None,
        "readiness_stability_state": "stable",
        "readiness_hard_invalidated": False,
        "readiness_flip_suppressed": False,
        "stable_readiness_actionable": False,
        "stable_readiness_near_trigger": False,
        "stable_readiness_late": False,
        "execution_blocked": False,
        "execution_viability_reason": "",
        "execution_viability_bucket": "viable",
        "execution_margin_limited": False,
        "execution_viability_stale_data": False,
        "readiness_source_kind": "live_runtime",
        "position_value": 0,
    }
    if overrides:
        base.update(overrides)
    return base


class TestTruthAnalyzer:
    def test_clean_bots_no_verdicts(self):
        bots = [_bot(), _bot({"id": "b2", "symbol": "ETHUSDT"})]
        data, verdicts = analyze_truth(bots)
        assert data["score_stage_mismatch_count"] == 0
        assert len(verdicts) == 0

    def test_high_score_at_blocked_stage_is_mismatch(self):
        """High score + blocked = contradictory, flagged as mismatch."""
        bots = [_bot({"stable_readiness_stage": "blocked", "display_readiness_score": 72})]
        data, verdicts = analyze_truth(bots)
        assert data["score_stage_mismatch_count"] == 1
        assert len(verdicts) == 1
        assert verdicts[0].severity == "high"

    def test_low_score_at_blocked_stage_is_truthful(self):
        """Low score + blocked = truthful (score confirms the block), no mismatch."""
        bots = [_bot({"stable_readiness_stage": "blocked", "display_readiness_score": 28})]
        data, verdicts = analyze_truth(bots)
        assert data["score_stage_mismatch_count"] == 0
        assert not any("score_stage_mismatch" in v.key for v in verdicts)

    def test_score_clear_violation(self):
        bots = [_bot({"stable_readiness_reason": "preview_disabled", "display_readiness_score": 50})]
        data, verdicts = analyze_truth(bots)
        assert any("score_clear_violation" in v.key for v in verdicts)

    def test_null_score_tracking(self):
        bots = [_bot(), _bot({"id": "b2", "display_readiness_score": 80})]
        data, _ = analyze_truth(bots)
        assert data["null_score_count"] == 1

    def test_stability_issue_tracking(self):
        bots = [_bot({"readiness_stability_state": "promoting", "readiness_flip_suppressed": True})]
        data, _ = analyze_truth(bots)
        assert data["stability_issue_count"] == 1


class TestReadinessAnalyzer:
    def test_distribution(self):
        bots = [
            _bot({"stable_readiness_stage": "watch"}),
            _bot({"id": "b2", "stable_readiness_stage": "armed", "stable_readiness_near_trigger": True}),
            _bot({"id": "b3", "stable_readiness_stage": "trigger_ready", "stable_readiness_actionable": True}),
        ]
        data, verdicts = analyze_readiness(bots)
        assert data["stage_counts"]["watch"] == 1
        assert data["stage_counts"]["armed"] == 1
        assert data["actionable_count"] == 1
        assert data["near_trigger_count"] == 1

    def test_armed_but_blocked(self):
        bots = [_bot({
            "stable_readiness_stage": "armed",
            "execution_blocked": True,
            "execution_viability_reason": "insufficient_margin",
        })]
        data, verdicts = analyze_readiness(bots)
        assert data["setup_ready_blocked"] > 0
        assert any("armed_but_blocked" in v.key for v in verdicts)

    def test_trigger_ready_but_blocked(self):
        bots = [_bot({
            "stable_readiness_stage": "trigger_ready",
            "execution_blocked": True,
            "execution_viability_reason": "position_cap_hit",
        })]
        _, verdicts = analyze_readiness(bots)
        assert any(v.severity == "critical" for v in verdicts)


class TestBlockerAnalyzer:
    def test_no_blockers(self):
        bots = [_bot()]
        data, verdicts = analyze_blockers(bots)
        assert data["blocked_count"] == 0
        assert len(verdicts) == 0

    def test_margin_cluster(self):
        bots = [
            _bot({
                "execution_blocked": True,
                "execution_viability_reason": "insufficient_margin",
                "execution_viability_bucket": "margin_limited",
                "execution_margin_limited": True,
            }),
            _bot({
                "id": "b2", "symbol": "ETHUSDT",
                "execution_blocked": True,
                "execution_viability_reason": "insufficient_margin",
                "execution_viability_bucket": "margin_limited",
                "execution_margin_limited": True,
            }),
        ]
        data, verdicts = analyze_blockers(bots)
        assert data["blocked_count"] == 2
        assert data["top_reason"] == "insufficient_margin"
        assert any("margin_cluster" in v.key for v in verdicts)

    def test_stopped_bots_excluded(self):
        bots = [_bot({
            "status": "stopped",
            "execution_blocked": True,
            "execution_viability_reason": "insufficient_margin",
        })]
        data, _ = analyze_blockers(bots)
        assert data["blocked_count"] == 0


class TestDriftAnalyzer:
    def test_fresh_bridge(self):
        bots = [_bot()]
        meta = {"fresh": True, "age_sec": 2.0}
        data, verdicts = analyze_drift(bots, meta)
        assert data["bridge_fresh"] is True
        assert not any("bridge_stale" in v.key for v in verdicts)

    def test_stale_bridge(self):
        bots = [_bot()]
        meta = {"fresh": False, "age_sec": 20.0}
        _, verdicts = analyze_drift(bots, meta)
        assert any("bridge_stale" in v.key for v in verdicts)

    def test_kill_switch(self):
        bots = [_bot()]
        meta = {"fresh": True, "age_sec": 1.0}
        risk = {"global_kill_switch": True}
        _, verdicts = analyze_drift(bots, meta, risk)
        assert any("kill_switch" in v.key for v in verdicts)

    def test_stale_previews(self):
        bots = [_bot({"stable_readiness_reason": "stale_snapshot", "status": "stopped"})]
        meta = {"fresh": True, "age_sec": 1.0}
        data, verdicts = analyze_drift(bots, meta)
        assert data["stale_preview_count"] == 1


class TestFitAnalyzer:
    def test_no_issues(self):
        bots = [_bot()]
        data, verdicts = analyze_fit(bots)
        assert data["poor_fit_count"] == 0
        assert len(verdicts) == 0

    def test_size_suppressed(self):
        bots = [_bot({
            "execution_viability_reason": "qty_below_min",
            "execution_viability_bucket": "size_limited",
        })]
        data, verdicts = analyze_fit(bots)
        assert data["size_suppressed_count"] == 1


class TestFunnelAnalyzer:
    def test_basic_funnel(self):
        bots = [
            _bot({"stable_readiness_stage": "watch"}),
            _bot({"id": "b2", "stable_readiness_stage": "armed"}),
            _bot({"id": "b3", "stable_readiness_stage": "trigger_ready", "position_value": 50}),
        ]
        data, _ = analyze_funnel(bots)
        assert data["funnel"]["watch"] == 1
        assert data["funnel"]["armed"] == 1
        assert data["funnel"]["trigger_ready"] == 1
        assert data["funnel"]["executing"] == 1

    def test_zero_executing_verdict(self):
        bots = [_bot() for _ in range(5)]
        _, verdicts = analyze_funnel(bots)
        assert any("zero_executing" in v.key for v in verdicts)


class TestExperimentAnalyzer:
    def test_no_experiments(self):
        bots = [_bot()]
        data, verdicts = analyze_experiments(bots)
        assert data["available"] is False
        assert len(verdicts) == 0

    def test_with_experiments(self):
        bots = [_bot({
            "experiment_attribution_state": "present",
            "runtime_experiment_tags": ["breakout_fast"],
        })]
        data, _ = analyze_experiments(bots)
        assert data["available"] is True
        assert data["experiment_count"] == 1
        assert data["tag_counts"]["breakout_fast"] == 1
