"""Tests for verdict model."""

import pytest
from trading_watchdog.models.verdict import Verdict, WatchdogSnapshot, CATEGORIES, SEVERITIES


class TestVerdict:
    def test_create_valid(self):
        v = Verdict(
            key="test:example",
            category="truth",
            severity="high",
            summary="Test verdict",
            evidence=["file:123"],
            affected_symbol="BTCUSDT",
        )
        assert v.key == "test:example"
        assert v.category == "truth"
        assert v.severity_rank == 1  # high is index 1

    def test_invalid_category(self):
        with pytest.raises(ValueError, match="Invalid category"):
            Verdict(key="t", category="invalid", severity="low", summary="x")

    def test_invalid_severity(self):
        with pytest.raises(ValueError, match="Invalid severity"):
            Verdict(key="t", category="truth", severity="bad", summary="x")

    def test_to_dict(self):
        v = Verdict(key="t", category="truth", severity="low", summary="x")
        d = v.to_dict()
        assert isinstance(d, dict)
        assert d["key"] == "t"
        assert d["status"] == "active"

    def test_severity_rank_order(self):
        critical = Verdict(key="a", category="truth", severity="critical", summary="x")
        info = Verdict(key="b", category="truth", severity="info", summary="x")
        assert critical.severity_rank < info.severity_rank

    def test_all_categories_valid(self):
        for cat in CATEGORIES:
            v = Verdict(key="t", category=cat, severity="low", summary="x")
            assert v.category == cat

    def test_all_severities_valid(self):
        for sev in SEVERITIES:
            v = Verdict(key="t", category="truth", severity=sev, summary="x")
            assert v.severity == sev


class TestWatchdogSnapshot:
    def test_empty_snapshot(self):
        snap = WatchdogSnapshot()
        assert snap.health_score == 100
        assert snap.total_bots == 0
        assert snap.verdicts == []

    def test_compute_health(self):
        snap = WatchdogSnapshot()
        snap.verdicts = [
            Verdict(key="a", category="truth", severity="critical", summary="x"),
            Verdict(key="b", category="truth", severity="high", summary="x"),
        ]
        snap.compute_health({"critical": 25, "high": 12, "medium": 5, "low": 2, "info": 0})
        assert snap.health_score == 63
        assert snap.health_label == "fair"

    def test_health_floor_at_zero(self):
        snap = WatchdogSnapshot()
        snap.verdicts = [
            Verdict(key=f"v{i}", category="truth", severity="critical", summary="x")
            for i in range(10)
        ]
        snap.compute_health({"critical": 25, "high": 12, "medium": 5, "low": 2, "info": 0})
        assert snap.health_score == 0
        assert snap.health_label == "critical"

    def test_to_dict(self):
        snap = WatchdogSnapshot()
        snap.verdicts = [Verdict(key="t", category="truth", severity="low", summary="x")]
        d = snap.to_dict()
        assert isinstance(d, dict)
        assert len(d["verdicts"]) == 1
        assert isinstance(d["verdicts"][0], dict)
