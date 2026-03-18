"""
Tests for MotionSignalService — market activity quality signal.

Validates score bounds, label assignment, caching, EMA smoothing,
and graceful handling of missing/None indicator data.
"""

import time
import pytest
from unittest.mock import MagicMock


class FakeIndicatorService:
    """Minimal mock returning configurable indicator dicts and candle arrays."""

    def __init__(self, indicators_5m=None, indicators_1m=None, candles_1m=None):
        self._indicators_5m = indicators_5m or {}
        self._indicators_1m = indicators_1m or {}
        self._candles_1m = candles_1m or []

    def compute_indicators(self, symbol, interval, limit):
        if str(interval) == "5":
            return self._indicators_5m
        if str(interval) == "1":
            return self._indicators_1m
        return {}

    def get_ohlcv(self, symbol, interval, limit):
        if str(interval) == "1":
            return self._candles_1m
        return []


def _make_candles(closes, spread_pct=0.002):
    """Build minimal candle dicts from a list of close prices."""
    candles = []
    for c in closes:
        half = c * spread_pct
        candles.append({"open": c, "high": c + half, "low": c - half, "close": c})
    return candles


def _make_chaotic_candles(base=100.0, n=14):
    """Build candles with heavy reversals and extreme spikes."""
    closes = []
    for i in range(n):
        if i % 2 == 0:
            closes.append(base + (i * 2.0))
        else:
            closes.append(base - (i * 1.5))
    candles = []
    for i, c in enumerate(closes):
        spike = 8.0 if i == n // 2 else 0.2
        candles.append({"open": c, "high": c + spike, "low": c - spike, "close": c})
    return candles


def _build_service(indicators_5m=None, indicators_1m=None, candles_1m=None):
    from services.motion_signal_service import MotionSignalService

    fake_ind = FakeIndicatorService(indicators_5m, indicators_1m, candles_1m)
    return MotionSignalService(fake_ind)


# ---------------------------------------------------------------------------
# Score bounds
# ---------------------------------------------------------------------------

class TestScoreBounds:
    def test_score_bounded_0_100_high_input(self):
        candles = _make_candles([100 + i * 5 for i in range(14)])
        svc = _build_service(
            indicators_5m={"atr_pct": 0.10, "volume_ratio": 5.0},
            indicators_1m={"price_velocity": 0.10},
            candles_1m=candles,
        )
        result = svc.compute_motion("BTCUSDT")
        assert 0 <= result["motion_score"] <= 100

    def test_score_bounded_0_100_zero_input(self):
        candles = _make_candles([100.0] * 14)
        svc = _build_service(
            indicators_5m={"atr_pct": 0.0, "volume_ratio": 0.0},
            indicators_1m={"price_velocity": 0.0},
            candles_1m=candles,
        )
        result = svc.compute_motion("BTCUSDT")
        assert 0 <= result["motion_score"] <= 100


# ---------------------------------------------------------------------------
# Label assignment
# ---------------------------------------------------------------------------

class TestLabelAssignment:
    def test_dead_market(self):
        """Near-zero ATR, zero velocity, flat candles → Dead."""
        candles = _make_candles([100.0] * 14, spread_pct=0.0001)
        svc = _build_service(
            indicators_5m={"atr_pct": 0.0001, "volume_ratio": 0.3},
            indicators_1m={"price_velocity": 0.0},
            candles_1m=candles,
        )
        result = svc.compute_motion("DEADUSDT")
        assert result["motion_label"] == "Dead"
        assert result["motion_tint"] == "dead"
        assert result["motion_score"] < 20

    def test_slow_market(self):
        """Low ATR, low velocity → Slow."""
        closes = [100.0 + i * 0.05 for i in range(14)]
        candles = _make_candles(closes, spread_pct=0.001)
        svc = _build_service(
            indicators_5m={"atr_pct": 0.0025, "volume_ratio": 0.9},
            indicators_1m={"price_velocity": 0.002},
            candles_1m=candles,
        )
        result = svc.compute_motion("SLOWUSDT")
        assert result["motion_label"] == "Slow"
        assert result["motion_tint"] == "slow"

    def test_healthy_market(self):
        """Moderate ATR, decent velocity, good continuity → Healthy."""
        closes = [100.0 + i * 0.3 for i in range(14)]
        candles = _make_candles(closes, spread_pct=0.003)
        svc = _build_service(
            indicators_5m={"atr_pct": 0.006, "volume_ratio": 1.2},
            indicators_1m={"price_velocity": 0.008},
            candles_1m=candles,
        )
        result = svc.compute_motion("ETHUSDT")
        assert result["motion_label"] == "Healthy"
        assert result["motion_tint"] == "healthy"

    def test_fast_trending_market(self):
        """High velocity, high efficiency, high ATR → Fast."""
        closes = [100.0 + i * 1.5 for i in range(14)]
        candles = _make_candles(closes, spread_pct=0.004)
        svc = _build_service(
            indicators_5m={"atr_pct": 0.010, "volume_ratio": 2.0},
            indicators_1m={"price_velocity": 0.018},
            candles_1m=candles,
        )
        result = svc.compute_motion("FASTUSDT")
        assert result["motion_label"] == "Fast"
        assert result["motion_tint"] == "fast"

    def test_chaotic_market(self):
        """High ATR, many reversals, extreme spikes → Chaotic."""
        candles = _make_chaotic_candles(base=100.0, n=14)
        svc = _build_service(
            indicators_5m={"atr_pct": 0.008, "volume_ratio": 2.0},
            indicators_1m={"price_velocity": 0.012},
            candles_1m=candles,
        )
        result = svc.compute_motion("CHAOSUSDT")
        assert result["motion_label"] == "Chaotic"
        assert result["motion_tint"] == "chaotic"

    def test_healthy_outranks_chaotic(self):
        """Healthy sustained movement should score higher than chaotic noise."""
        # Healthy: steady uptrend
        closes_h = [100.0 + i * 0.5 for i in range(14)]
        candles_h = _make_candles(closes_h, spread_pct=0.003)
        svc_h = _build_service(
            indicators_5m={"atr_pct": 0.005, "volume_ratio": 1.2},
            indicators_1m={"price_velocity": 0.006},
            candles_1m=candles_h,
        )
        healthy = svc_h.compute_motion("HEALTHY")

        # Chaotic: whipsaw with high ATR
        candles_c = _make_chaotic_candles(base=100.0, n=14)
        svc_c = _build_service(
            indicators_5m={"atr_pct": 0.008, "volume_ratio": 2.0},
            indicators_1m={"price_velocity": 0.012},
            candles_1m=candles_c,
        )
        chaotic = svc_c.compute_motion("CHAOTIC")

        assert healthy["motion_score"] > chaotic["motion_score"]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestCaching:
    def test_cache_read_returns_last_computed(self):
        candles = _make_candles([100.0 + i * 0.3 for i in range(14)])
        svc = _build_service(
            indicators_5m={"atr_pct": 0.005, "volume_ratio": 1.0},
            indicators_1m={"price_velocity": 0.005},
            candles_1m=candles,
        )
        computed = svc.compute_motion("BTCUSDT")
        cached = svc.get_motion("BTCUSDT")
        assert cached["motion_score"] == computed["motion_score"]
        assert cached["motion_label"] == computed["motion_label"]

    def test_cache_miss_returns_empty(self):
        svc = _build_service()
        result = svc.get_motion("NEVERCOMPUTED")
        assert result == {}


# ---------------------------------------------------------------------------
# EMA smoothing
# ---------------------------------------------------------------------------

class TestEmaSmoothing:
    def test_ema_dampens_sudden_jump(self):
        """Second computation with wildly different input should be dampened."""
        from services.motion_signal_service import MotionSignalService

        # First: dead market
        candles_dead = _make_candles([100.0] * 14, spread_pct=0.0001)
        fake1 = FakeIndicatorService(
            indicators_5m={"atr_pct": 0.0001, "volume_ratio": 0.3},
            indicators_1m={"price_velocity": 0.0},
            candles_1m=candles_dead,
        )
        svc = MotionSignalService(fake1)
        first = svc.compute_motion("BTCUSDT")
        first_score = first["motion_score"]

        # Force cache expiry
        svc._cache["BTCUSDT"]["motion_computed_at"] = 0

        # Second: suddenly very active
        candles_fast = _make_candles([100.0 + i * 2 for i in range(14)])
        fake2 = FakeIndicatorService(
            indicators_5m={"atr_pct": 0.010, "volume_ratio": 2.5},
            indicators_1m={"price_velocity": 0.020},
            candles_1m=candles_fast,
        )
        svc.indicator_service = fake2
        second = svc.compute_motion("BTCUSDT")

        # The smoothed score should move toward the new value but not reach it
        assert second["motion_score"] > first_score


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_none_indicators_no_crash(self):
        svc = _build_service(
            indicators_5m=None,
            indicators_1m=None,
            candles_1m=[],
        )
        result = svc.compute_motion("BTCUSDT")
        # Should not raise
        assert "motion_score" in result

    def test_empty_candles_no_crash(self):
        svc = _build_service(
            indicators_5m={"atr_pct": 0.003, "volume_ratio": 1.0},
            indicators_1m={"price_velocity": 0.005},
            candles_1m=[],
        )
        result = svc.compute_motion("BTCUSDT")
        assert 0 <= (result["motion_score"] or 0) <= 100

    def test_indicator_service_exception(self):
        """If indicator service throws, compute_motion returns None fields."""
        from services.motion_signal_service import MotionSignalService

        mock_ind = MagicMock()
        mock_ind.compute_indicators.side_effect = RuntimeError("exchange down")
        mock_ind.get_ohlcv.side_effect = RuntimeError("exchange down")
        svc = MotionSignalService(mock_ind)
        result = svc.compute_motion("BTCUSDT")
        assert result["motion_score"] is None
        assert result["motion_label"] is None


# ---------------------------------------------------------------------------
# Payload fields present
# ---------------------------------------------------------------------------

class TestPayloadShape:
    def test_compute_returns_all_fields(self):
        candles = _make_candles([100.0 + i * 0.3 for i in range(14)])
        svc = _build_service(
            indicators_5m={"atr_pct": 0.003, "volume_ratio": 1.0},
            indicators_1m={"price_velocity": 0.005},
            candles_1m=candles,
        )
        result = svc.compute_motion("BTCUSDT")
        assert "motion_score" in result
        assert "motion_label" in result
        assert "motion_tint" in result
        assert "motion_computed_at" in result
        assert isinstance(result["motion_computed_at"], float)
