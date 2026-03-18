"""Tests for AI Ops triage engine and rules."""

import time
import pytest
from opus_aiops.models import SystemSnapshot
from opus_aiops.triage import (
    TriageEngine,
    Correlator,
    rule_storage_contention,
    rule_exchange_ambiguity,
    rule_preview_gating_regression,
    rule_websocket_instability,
    rule_control_state_race,
)


def _base_snapshot(**kwargs) -> SystemSnapshot:
    defaults = dict(
        timestamp=time.time(),
        health_score=85.0,
        health_status="healthy",
        runner_active=True,
        bridge_stale_count=0,
        bridge_stale_sections=[],
        bot_total=2,
        bot_status_counts={"running": 1, "stopped": 1},
        source_errors={},
    )
    defaults.update(kwargs)
    return SystemSnapshot(**defaults)


class TestCorrelator:
    def test_empty_window(self):
        c = Correlator(window_size=5)
        assert c.window_size == 0
        assert c.count_matches(lambda s: True) == 0

    def test_add_and_count(self):
        c = Correlator(window_size=5)
        c.add(_base_snapshot(bridge_stale_count=3))
        c.add(_base_snapshot(bridge_stale_count=0))
        c.add(_base_snapshot(bridge_stale_count=4))
        assert c.count_matches(lambda s: (s.bridge_stale_count or 0) >= 2) == 2

    def test_window_max_size(self):
        c = Correlator(window_size=3)
        for i in range(5):
            c.add(_base_snapshot())
        assert c.window_size == 3

    def test_earliest_match(self):
        c = Correlator(window_size=5)
        t1 = time.time() - 100
        t2 = time.time() - 50
        c.add(_base_snapshot(timestamp=t1, bridge_stale_count=3))
        c.add(_base_snapshot(timestamp=t2, bridge_stale_count=0))
        result = c.earliest_match(lambda s: (s.bridge_stale_count or 0) >= 2)
        assert result == t1


class TestRuleStorageContention:
    def test_no_match_when_healthy(self):
        snap = _base_snapshot()
        c = Correlator()
        assert rule_storage_contention(snap, c) is None

    def test_match_with_stale_sections_and_log_evidence(self):
        c = Correlator(window_size=5)
        # Need 2+ cycles of stale sections
        for _ in range(3):
            snap = _base_snapshot(
                bridge_stale_count=3,
                bridge_stale_sections=["market", "positions", "summary"],
                bridge_diagnostics={
                    "request_diagnostics": {
                        "bridge_diagnostics": {
                            "phase_ms": {"sections_assembly_ms": 150}
                        }
                    }
                },
                runner_log_lines=[
                    "2024-01-01 lock contention detected on storage path\n",
                    "2024-01-01 normal operation\n",
                ],
            )
            c.add(snap)

        result = rule_storage_contention(snap, c)
        assert result is not None
        assert result.rule_id == "storage_contention"
        assert result.severity in ("medium", "high")
        assert result.matched_signals >= 2


class TestRuleExchangeAmbiguity:
    def test_no_match_clean_logs(self):
        snap = _base_snapshot(runner_log_lines=["normal operation\n"])
        c = Correlator()
        assert rule_exchange_ambiguity(snap, c) is None

    def test_match_with_timeout(self):
        snap = _base_snapshot(runner_log_lines=[
            "2024-01-01 ws_timeout_after_send for order xyz\n",
        ])
        c = Correlator()
        result = rule_exchange_ambiguity(snap, c)
        assert result is not None
        assert result.rule_id == "exchange_ambiguity"
        assert result.severity in ("high", "critical")

    def test_match_close_failed(self):
        snap = _base_snapshot(runner_log_lines=[
            "2024-01-01 order CLOSE_FAILED on BTCUSDT\n",
        ])
        c = Correlator()
        result = rule_exchange_ambiguity(snap, c)
        assert result is not None

    def test_match_ambiguous_execution(self):
        snap = _base_snapshot(runner_log_lines=[
            "2024-01-01 ambiguous_execution_follow_up triggered\n",
        ])
        c = Correlator()
        result = rule_exchange_ambiguity(snap, c)
        assert result is not None

    def test_multiple_signals_critical(self):
        snap = _base_snapshot(runner_log_lines=[
            "2024-01-01 ws_timeout_after_send\n",
            "2024-01-01 CLOSE_FAILED\n",
        ])
        c = Correlator()
        result = rule_exchange_ambiguity(snap, c)
        assert result is not None
        assert result.severity == "critical"


class TestRulePreviewGatingRegression:
    def test_no_match_no_bots(self):
        snap = _base_snapshot(bridge_bots_light=None)
        c = Correlator()
        assert rule_preview_gating_regression(snap, c) is None

    def test_no_match_all_running(self):
        snap = _base_snapshot(bridge_bots_light=[
            {"bot_id": "a", "lifecycle_status": "running", "symbol": "BTCUSDT"},
            {"bot_id": "b", "lifecycle_status": "running", "symbol": "ETHUSDT"},
        ])
        c = Correlator()
        assert rule_preview_gating_regression(snap, c) is None

    def test_match_stopped_preview_disabled(self):
        snap = _base_snapshot(bridge_bots_light=[
            {"bot_id": "a", "lifecycle_status": "running", "symbol": "BTCUSDT"},
            {"bot_id": "b", "lifecycle_status": "stopped", "symbol": "ETHUSDT", "preview_mode": "disabled"},
        ])
        c = Correlator()
        result = rule_preview_gating_regression(snap, c)
        assert result is not None
        assert result.rule_id == "preview_gating_regression"

    def test_no_match_same_symbol(self):
        snap = _base_snapshot(bridge_bots_light=[
            {"bot_id": "a", "lifecycle_status": "running", "symbol": "BTCUSDT"},
            {"bot_id": "b", "lifecycle_status": "stopped", "symbol": "BTCUSDT", "preview_mode": "disabled"},
        ])
        c = Correlator()
        # Same symbol — different logic applies, not a regression
        result = rule_preview_gating_regression(snap, c)
        assert result is None


class TestRuleWebsocketInstability:
    def test_no_match_clean(self):
        snap = _base_snapshot(
            active_incidents=[],
            runner_log_lines=["normal\n"],
        )
        c = Correlator()
        assert rule_websocket_instability(snap, c) is None

    def test_match_stream_incidents_plus_log(self):
        snap = _base_snapshot(
            active_incidents=[
                {"category": "stream", "status": "open", "severity": "medium", "summary": "ws disconnect"},
            ],
            runner_log_lines=["2024-01-01 stream disconnected, reconnecting\n"],
        )
        c = Correlator()
        result = rule_websocket_instability(snap, c)
        assert result is not None
        assert result.rule_id == "websocket_instability"


class TestRuleControlStateRace:
    def test_no_match_clean(self):
        snap = _base_snapshot(runner_log_lines=["normal\n"])
        c = Correlator()
        assert rule_control_state_race(snap, c) is None

    def test_match_stale_control_state(self):
        snap = _base_snapshot(runner_log_lines=[
            "2024-01-01 stale control-state save ignored for bot abc\n",
        ])
        c = Correlator()
        result = rule_control_state_race(snap, c)
        assert result is not None
        assert result.rule_id == "control_state_race"
        assert result.severity == "high"


class TestTriageEngine:
    def test_no_cases_healthy_system(self):
        engine = TriageEngine()
        snap = _base_snapshot(runner_log_lines=["all good\n"])
        cases = engine.evaluate(snap)
        assert len(cases) == 0

    def test_case_created_and_updated(self):
        engine = TriageEngine()
        snap = _base_snapshot(runner_log_lines=[
            "ws_timeout_after_send on order\n",
        ])
        cases = engine.evaluate(snap)
        assert len(cases) == 1
        assert cases[0].hit_count == 1

        # Second evaluation should update, not create
        cases2 = engine.evaluate(snap)
        exchange_cases = [c for c in cases2 if c.rule_id == "exchange_ambiguity"]
        assert len(exchange_cases) == 1
        assert exchange_cases[0].hit_count == 2

    def test_auto_resolve(self):
        import opus_aiops.config as cfg
        old_threshold = cfg.TRIAGE_AUTO_RESOLVE_SEC
        cfg.TRIAGE_AUTO_RESOLVE_SEC = 0.1  # very short for test

        engine = TriageEngine()
        snap = _base_snapshot(
            runner_log_lines=["ws_timeout_after_send\n"],
            timestamp=time.time() - 1,
        )
        engine.evaluate(snap)
        assert len(engine.open_cases) == 1

        # Wait and evaluate with clean snapshot
        import time as _time
        _time.sleep(0.15)
        clean_snap = _base_snapshot(runner_log_lines=["all clear\n"])
        cases = engine.evaluate(clean_snap)
        resolved = [c for c in cases if c.status == "auto_resolved"]
        assert len(resolved) == 1

        cfg.TRIAGE_AUTO_RESOLVE_SEC = old_threshold
