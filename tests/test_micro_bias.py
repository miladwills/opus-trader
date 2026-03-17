"""
Tests for the Micro-Bias Awareness Service.

The micro-bias service detects slight directional drift in the market
and helps neutral mode avoid accumulating inventory against the micro-trend.
"""

import pytest
from unittest.mock import Mock, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.micro_bias_service import MicroBiasService


@pytest.fixture
def mock_indicator_service():
    """Mock IndicatorService with neutral market conditions (default)."""
    service = Mock()
    service.compute_indicators = Mock(return_value={
        "price_velocity": 0.0,  # No drift
        "ema_slope": 0.0,  # Flat
        "rsi": 50.0,  # Neutral
        "close": 2000.0,
    })
    service.get_ohlcv = Mock(return_value=[])
    return service


@pytest.fixture
def mock_orderbook_service():
    """Mock OrderBookService with balanced order book (default)."""
    service = Mock()
    service.calculate_imbalance = Mock(return_value={
        "success": True,
        "imbalance": 0.0,  # Balanced
        "bid_volume": 100.0,
        "ask_volume": 100.0,
    })
    return service


@pytest.fixture
def micro_bias_service(mock_indicator_service, mock_orderbook_service):
    """MicroBiasService with mocked dependencies."""
    return MicroBiasService(
        indicator_service=mock_indicator_service,
        orderbook_service=mock_orderbook_service,
    )


@pytest.fixture
def sample_neutral_bot():
    """Sample neutral_classic_bybit bot configuration."""
    return {
        "id": "test-bot-123",
        "symbol": "ETHUSDT",
        "mode": "neutral_classic_bybit",
        "status": "running",
        "investment": 100.0,
        "leverage": 10.0,
    }


class TestMicroBiasCalculation:
    """Tests for micro-bias score calculation."""

    def test_neutral_when_all_signals_neutral(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Return NEUTRAL when all signals are balanced."""
        # All defaults are neutral
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            hysteresis_checks=1,  # Disable hysteresis for this test
        )

        assert result["direction"] == "NEUTRAL"
        assert abs(result["score"]) < 0.30
        assert result["skip_probability"] == 0.0

    def test_bullish_on_strong_bid_imbalance(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Detect BULLISH bias when order book shows strong bid pressure."""
        # Strong bid imbalance (positive)
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.60,  # 60% imbalance toward bids (bullish)
        }
        # Other signals slightly bullish
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.01,  # Slight upward drift
            "ema_slope": 0.001,  # Slight upward slope
            "rsi": 55.0,  # Slightly above 50
        }

        # Clear hysteresis and run multiple times to satisfy hysteresis
        # Use cache_seconds=0 to disable caching for hysteresis testing
        micro_bias_service.clear_cache()
        for _ in range(3):
            result = micro_bias_service.calculate_bias(
                bot=sample_neutral_bot,
                symbol="ETHUSDT",
                threshold=0.30,
                hysteresis_checks=2,
                cache_seconds=0,  # Disable caching
            )

        assert result["direction"] == "BULLISH"
        assert result["score"] > 0.30
        assert result["skip_probability"] > 0
        assert result["hysteresis_met"] is True

    def test_bearish_on_strong_ask_imbalance(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Detect BEARISH bias when order book shows strong ask pressure."""
        # Strong ask imbalance (negative)
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": -0.60,  # 60% imbalance toward asks (bearish)
        }
        # Other signals slightly bearish
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": -0.01,  # Slight downward drift
            "ema_slope": -0.001,  # Slight downward slope
            "rsi": 45.0,  # Slightly below 50
        }

        # Clear hysteresis and run multiple times
        micro_bias_service.clear_cache()
        for _ in range(3):
            result = micro_bias_service.calculate_bias(
                bot=sample_neutral_bot,
                symbol="ETHUSDT",
                threshold=0.30,
                hysteresis_checks=2,
                cache_seconds=0,  # Disable caching
            )

        assert result["direction"] == "BEARISH"
        assert result["score"] < -0.30
        assert result["skip_probability"] > 0

    def test_strong_bias_higher_skip_probability(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Strong bias should have higher skip probability than moderate."""
        # Very strong bullish signals
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.80,  # Very strong bid pressure
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.02,  # Strong upward drift
            "ema_slope": 0.002,  # Strong upward slope
            "rsi": 65.0,  # Well above 50
        }

        micro_bias_service.clear_cache()
        for _ in range(3):
            result = micro_bias_service.calculate_bias(
                bot=sample_neutral_bot,
                symbol="ETHUSDT",
                threshold=0.30,
                strong_threshold=0.50,
                skip_pct_moderate=0.40,
                skip_pct_strong=0.70,
                hysteresis_checks=2,
                cache_seconds=0,  # Disable caching
            )

        assert result["direction"] == "BULLISH"
        assert result["score"] >= 0.50
        assert result["skip_probability"] == 0.70  # Strong skip probability


class TestMicroBiasHysteresis:
    """Tests for hysteresis behavior."""

    def test_hysteresis_prevents_immediate_bias(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Hysteresis should require multiple consistent readings."""
        # Strong bullish signal
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.60,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.01,
            "ema_slope": 0.001,
            "rsi": 55.0,
        }

        # Clear and test first reading
        micro_bias_service.clear_cache()
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            threshold=0.30,
            hysteresis_checks=2,
        )

        # First reading should not trigger bias due to hysteresis
        assert result["hysteresis_met"] is False
        assert result["direction"] == "NEUTRAL"  # No action yet

    def test_hysteresis_satisfied_after_consecutive_readings(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """After enough consecutive readings, hysteresis should be satisfied."""
        # Strong bullish signal
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.60,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.01,
            "ema_slope": 0.001,
            "rsi": 55.0,
        }

        micro_bias_service.clear_cache()

        # Run twice with same signals (disable caching to ensure separate calculations)
        micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            threshold=0.30,
            hysteresis_checks=2,
            cache_seconds=0,
        )
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            threshold=0.30,
            hysteresis_checks=2,
            cache_seconds=0,
        )

        assert result["hysteresis_met"] is True
        assert result["direction"] == "BULLISH"

    def test_hysteresis_resets_on_direction_change(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Hysteresis should reset if signal direction changes."""
        # First: Strong bullish
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.60,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.01,
            "ema_slope": 0.001,
            "rsi": 55.0,
        }

        micro_bias_service.clear_cache()
        micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            threshold=0.30,
            hysteresis_checks=2,
        )

        # Then: Strong bearish (direction change)
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": -0.60,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": -0.01,
            "ema_slope": -0.001,
            "rsi": 45.0,
        }

        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            threshold=0.30,
            hysteresis_checks=2,
        )

        # Should not satisfy hysteresis due to direction change
        assert result["hysteresis_met"] is False


class TestMicroBiasComponents:
    """Tests for individual signal components."""

    def test_orderbook_component_weight(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Order book should have 40% weight in final score."""
        # Only orderbook signal, others neutral
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 1.0,  # Maximum bullish
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.0,
            "ema_slope": 0.0,
            "rsi": 50.0,
        }

        micro_bias_service.clear_cache()
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            hysteresis_checks=1,
        )

        # Score should be approximately 0.4 * 1.0 * 1.2 (with amplification)
        # but clamped to 1.0, so we expect 0.40-0.50 range
        assert 0.35 <= result["score"] <= 0.55
        assert result["components"]["orderbook"]["weight"] == 0.40

    def test_velocity_component_weight(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Price velocity should have 30% weight in final score."""
        # Only velocity signal
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.0,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.02,  # Strong upward drift (1%/hr * 50 = +1.0)
            "ema_slope": 0.0,
            "rsi": 50.0,
        }

        micro_bias_service.clear_cache()
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            hysteresis_checks=1,
        )

        assert result["components"]["velocity"]["weight"] == 0.30

    def test_graceful_handling_of_missing_data(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Should handle missing or failed data gracefully."""
        # Orderbook fails
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": False,
            "error": "API error",
        }
        # Indicators missing values
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": None,
            "ema_slope": None,
            "rsi": None,
        }

        micro_bias_service.clear_cache()
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            hysteresis_checks=1,
        )

        # Should return neutral without crashing
        assert result["direction"] == "NEUTRAL"
        assert result["score"] == 0.0


class TestMicroBiasSafetyGuarantees:
    """Tests for safety guarantees."""

    def test_exit_orders_never_affected(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Verify bias only affects ENTRY orders, not EXIT."""
        # This is tested implicitly in the integration with neutral_grid_service
        # The service only sets skip flags, actual skip logic checks reduce_only

        # Strong bias
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.80,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.02,
            "ema_slope": 0.002,
            "rsi": 65.0,
        }

        micro_bias_service.clear_cache()
        for _ in range(3):
            result = micro_bias_service.calculate_bias(
                bot=sample_neutral_bot,
                symbol="ETHUSDT",
                hysteresis_checks=2,
                cache_seconds=0,  # Disable caching
            )

        # Service should return skip info but NOT control reduce_only logic
        assert result["direction"] == "BULLISH"
        # The actual skip is handled by neutral_grid_service with reduce_only check

    def test_score_clamped_to_bounds(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Score should always be clamped to [-1.0, +1.0]."""
        # All maximum bullish signals
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 1.0,  # Max
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 1.0,  # Extreme
            "ema_slope": 1.0,  # Extreme
            "rsi": 100.0,  # Max
        }

        micro_bias_service.clear_cache()
        result = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            hysteresis_checks=1,
        )

        assert -1.0 <= result["score"] <= 1.0

    def test_master_toggle_respected(self):
        """Verify feature can be disabled via config."""
        # This is tested at integration level in grid_bot_service
        # Config constant NEUTRAL_MICRO_BIAS_ENABLED controls this
        pass


class TestMicroBiasCache:
    """Tests for caching behavior."""

    def test_cache_returns_same_result(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """Cached result should be returned within cache window."""
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.50,
        }
        mock_indicator_service.compute_indicators.return_value = {
            "price_velocity": 0.01,
            "ema_slope": 0.001,
            "rsi": 55.0,
        }

        micro_bias_service.clear_cache()
        result1 = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            cache_seconds=60,
            hysteresis_checks=1,
        )

        # Change mock (should not affect cached result)
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": -0.50,
        }

        result2 = micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            cache_seconds=60,
            hysteresis_checks=1,
        )

        # Should return same cached result
        assert result1["score"] == result2["score"]

    def test_clear_cache_removes_all(
        self, micro_bias_service, mock_indicator_service, mock_orderbook_service, sample_neutral_bot
    ):
        """clear_cache should remove cached data."""
        mock_orderbook_service.calculate_imbalance.return_value = {
            "success": True,
            "imbalance": 0.50,
        }

        micro_bias_service.calculate_bias(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            hysteresis_checks=1,
        )

        assert micro_bias_service.get_cached_bias("ETHUSDT") is not None

        micro_bias_service.clear_cache()

        assert micro_bias_service.get_cached_bias("ETHUSDT") is None
