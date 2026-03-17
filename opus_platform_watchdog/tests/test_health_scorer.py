"""Tests for health scoring logic."""

import pytest
from opus_platform_watchdog.scoring.health_scorer import _status_from_score, COMPONENT_WEIGHTS


def test_status_thresholds():
    assert _status_from_score(100) == "healthy"
    assert _status_from_score(95) == "healthy"
    assert _status_from_score(90) == "healthy"
    assert _status_from_score(89) == "degraded"
    assert _status_from_score(70) == "degraded"
    assert _status_from_score(69) == "unhealthy"
    assert _status_from_score(40) == "unhealthy"
    assert _status_from_score(39) == "critical"
    assert _status_from_score(0) == "critical"


def test_weights_sum_to_one():
    total = sum(COMPONENT_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001


def test_all_components_present():
    expected = {"runner_process", "trader_process", "bridge_health", "api_latency", "error_rate"}
    assert set(COMPONENT_WEIGHTS.keys()) == expected
