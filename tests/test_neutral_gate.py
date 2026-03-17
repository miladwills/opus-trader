"""
Tests for the Neutral Suitability Gate Service.

The gate checks if market conditions are suitable for neutral/grid trading
and blocks new orders when market is trending.
"""

import pytest
from unittest.mock import Mock, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.neutral_suitability_service import NeutralSuitabilityService


@pytest.fixture
def mock_indicator_service():
    """Mock IndicatorService with sideways market conditions (default)."""
    service = Mock()
    service.compute_indicators = Mock(return_value={
        "adx": 18.0,       # Low ADX = sideways (< 22 threshold)
        "rsi": 50.0,       # Neutral RSI (35-65 range)
        "atr_pct": 0.02,   # Normal volatility (< 4% threshold)
        "close": 2000.0,
    })
    return service


@pytest.fixture
def gate_service(mock_indicator_service):
    """NeutralSuitabilityService with mocked dependencies."""
    return NeutralSuitabilityService(
        indicator_service=mock_indicator_service,
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
        "neutral_preset": "MAJOR",
    }


class TestNeutralSuitabilityGate:
    """Tests for the neutral suitability gate."""

    def test_suitable_when_sideways(self, gate_service, mock_indicator_service):
        """Allow when ADX < 22, RSI in range, ATR% low."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 18.0,       # Sideways (< 22)
            "rsi": 50.0,       # Neutral (35-65)
            "atr_pct": 0.02,   # Normal volatility (< 4%)
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is True
        assert result["blocked_by"] == []
        assert "sideways" in result["reason"].lower() or "suitable" in result["reason"].lower()

    def test_blocked_when_adx_high(self, gate_service, mock_indicator_service):
        """Block when ADX15 > threshold (trending)."""
        # ETHUSDT uses MAJOR preset with ADX threshold = 28
        # Need ADX > 28 to trigger blocking
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 32.0,       # Trending (> 28 MAJOR threshold)
            "rsi": 50.0,       # Neutral
            "atr_pct": 0.02,   # Normal
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is False
        assert "ADX_15M" in result["blocked_by"]
        assert "ADX" in result["reason"]

    def test_blocked_when_rsi_overbought(self, gate_service, mock_indicator_service):
        """Block when RSI15 > 65 (overbought)."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 18.0,       # Sideways
            "rsi": 72.0,       # Overbought (> 65)
            "atr_pct": 0.02,   # Normal
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is False
        assert "RSI_OVERBOUGHT" in result["blocked_by"]
        assert "RSI" in result["reason"]

    def test_blocked_when_rsi_oversold(self, gate_service, mock_indicator_service):
        """Block when RSI15 < 35 (oversold)."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 18.0,       # Sideways
            "rsi": 28.0,       # Oversold (< 35)
            "atr_pct": 0.02,   # Normal
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is False
        assert "RSI_OVERSOLD" in result["blocked_by"]
        assert "RSI" in result["reason"]

    def test_blocked_when_atr_high(self, gate_service, mock_indicator_service):
        """Block when ATR% > 4% (too volatile)."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 18.0,       # Sideways
            "rsi": 50.0,       # Neutral
            "atr_pct": 0.055,  # High volatility (> 4%)
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is False
        assert "ATR_HIGH" in result["blocked_by"]
        assert "ATR" in result["reason"]

    def test_blocked_when_1m_momentum_high(self, gate_service, mock_indicator_service):
        """Block when 1m ADX > 30 (immediate strong move)."""
        # 15m is fine, but 1m shows strong momentum
        call_count = [0]

        def mock_compute(symbol, interval, **kwargs):
            call_count[0] += 1
            if interval == "15":
                return {"adx": 18.0, "rsi": 50.0, "atr_pct": 0.02}
            elif interval == "1":
                return {"adx": 42.0, "rsi": 50.0}  # Strong 1m momentum
            return {}

        mock_indicator_service.compute_indicators.side_effect = mock_compute

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is False
        assert "ADX_1M" in result["blocked_by"]
        assert "1m" in result["reason"].lower()

    def test_multiple_blocks_combined(self, gate_service, mock_indicator_service):
        """Multiple failing conditions are all reported."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 30.0,       # Trending (> 22)
            "rsi": 72.0,       # Overbought (> 65)
            "atr_pct": 0.055,  # High volatility (> 4%)
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert result["suitable"] is False
        assert "ADX_15M" in result["blocked_by"]
        assert "RSI_OVERBOUGHT" in result["blocked_by"]
        assert "ATR_HIGH" in result["blocked_by"]
        assert len(result["blocked_by"]) == 3


class TestPresetDetection:
    """Tests for preset auto-detection."""

    def test_major_symbol_gets_major_preset(self, gate_service):
        """Major symbols (BTC, ETH, SOL) should get MAJOR preset."""
        assert gate_service.get_preset_for_symbol("BTCUSDT") == "MAJOR"
        assert gate_service.get_preset_for_symbol("ETHUSDT") == "MAJOR"
        assert gate_service.get_preset_for_symbol("SOLUSDT") == "MAJOR"

    def test_meme_symbol_gets_meme_preset(self, gate_service):
        """Unknown/meme symbols should get MEME preset."""
        assert gate_service.get_preset_for_symbol("DOGEUSDT") == "MEME"
        assert gate_service.get_preset_for_symbol("SHIBUSDT") == "MEME"
        assert gate_service.get_preset_for_symbol("WIFUSDT") == "MEME"
        assert gate_service.get_preset_for_symbol("PEPEUSDT") == "MEME"

    def test_preset_returned_in_result(self, gate_service, mock_indicator_service):
        """Suitability result includes the detected preset."""
        result = gate_service.check_suitability("BTCUSDT")
        assert result["preset"] == "MAJOR"

        result = gate_service.check_suitability("DOGEUSDT")
        assert result["preset"] == "MEME"

    def test_explicit_preset_overrides_auto(self, gate_service, mock_indicator_service):
        """Explicit preset parameter overrides auto-detection."""
        # BTCUSDT would normally get MAJOR, but we pass MEME explicitly
        result = gate_service.check_suitability("BTCUSDT", preset="MEME")
        assert result["preset"] == "MEME"


class TestBotStateManagement:
    """Tests for bot state management methods."""

    def test_set_blocked(self, gate_service, sample_neutral_bot):
        """set_blocked() correctly sets blocking state."""
        gate_service.set_blocked(sample_neutral_bot, "ADX too high")

        assert sample_neutral_bot["_nlp_block_opening_orders"] is True
        assert sample_neutral_bot["_gate_blocked_until"] > 0
        assert sample_neutral_bot["_gate_blocked_reason"] == "ADX too high"

    def test_clear_blocked(self, gate_service, sample_neutral_bot):
        """clear_blocked() removes blocking state."""
        # First set blocked
        sample_neutral_bot["_nlp_block_opening_orders"] = True
        sample_neutral_bot["_gate_blocked_until"] = 9999999999
        sample_neutral_bot["_gate_blocked_reason"] = "test"

        # Then clear
        gate_service.clear_blocked(sample_neutral_bot)

        assert sample_neutral_bot["_nlp_block_opening_orders"] is False
        assert "_gate_blocked_until" not in sample_neutral_bot
        assert "_gate_blocked_reason" not in sample_neutral_bot

    def test_get_status_when_blocked(self, gate_service, sample_neutral_bot):
        """get_status() returns blocked state correctly."""
        import time
        now = time.time()
        sample_neutral_bot["_nlp_block_opening_orders"] = True
        sample_neutral_bot["_gate_blocked_until"] = now + 60
        sample_neutral_bot["_gate_blocked_reason"] = "ADX too high"

        status = gate_service.get_status(sample_neutral_bot)

        assert status["blocked"] is True
        assert status["reason"] == "ADX too high"
        assert status["time_remaining"] > 0
        assert status["time_remaining"] <= 60

    def test_get_status_when_not_blocked(self, gate_service, sample_neutral_bot):
        """get_status() returns unblocked state correctly."""
        status = gate_service.get_status(sample_neutral_bot)

        assert status["blocked"] is False
        assert status["time_remaining"] == 0

    def test_should_recheck_when_cooldown_expired(self, gate_service, sample_neutral_bot):
        """should_recheck() returns True when cooldown expired."""
        import time
        sample_neutral_bot["_gate_blocked_until"] = time.time() - 10  # Expired

        assert gate_service.should_recheck(sample_neutral_bot) is True

    def test_should_recheck_when_in_cooldown(self, gate_service, sample_neutral_bot):
        """should_recheck() returns False when still in cooldown."""
        import time
        sample_neutral_bot["_gate_blocked_until"] = time.time() + 60  # Future

        assert gate_service.should_recheck(sample_neutral_bot) is False


class TestGateDisabled:
    """Tests for when gate is disabled."""

    def test_always_suitable_when_disabled(self, mock_indicator_service):
        """When gate disabled, always returns suitable."""
        # Temporarily override the config
        import config.strategy_config as cfg
        original = cfg.NEUTRAL_GATE_ENABLED
        cfg.NEUTRAL_GATE_ENABLED = False

        try:
            gate_service = NeutralSuitabilityService(mock_indicator_service)
            # Even with terrible conditions, should return suitable
            mock_indicator_service.compute_indicators.return_value = {
                "adx": 50.0,       # Very high
                "rsi": 80.0,       # Very overbought
                "atr_pct": 0.10,   # Very volatile
            }

            result = gate_service.check_suitability("ETHUSDT")

            assert result["suitable"] is True
            assert "disabled" in result["reason"].lower()
        finally:
            cfg.NEUTRAL_GATE_ENABLED = original


class TestIndicatorErrors:
    """Tests for handling indicator fetch errors."""

    def test_handles_indicator_fetch_error(self, mock_indicator_service):
        """Gracefully handles indicator fetch errors."""
        mock_indicator_service.compute_indicators.side_effect = Exception("API error")

        gate_service = NeutralSuitabilityService(mock_indicator_service)
        result = gate_service.check_suitability("ETHUSDT")

        # Should not crash, returns empty scores
        assert result["scores"]["adx_15m"] is None
        assert result["scores"]["rsi_15m"] is None

    def test_handles_missing_indicators(self, mock_indicator_service):
        """Handles missing indicator values gracefully."""
        mock_indicator_service.compute_indicators.return_value = {}  # No data

        gate_service = NeutralSuitabilityService(mock_indicator_service)
        result = gate_service.check_suitability("ETHUSDT")

        # Should not crash, should be suitable (no data to block on)
        assert result["scores"]["adx_15m"] is None
        assert result["blocked_by"] == []  # No blocking without data


class TestThresholdsReturnedInResult:
    """Tests that thresholds are included in results."""

    def test_thresholds_in_result(self, gate_service, mock_indicator_service):
        """Result includes the threshold values used."""
        result = gate_service.check_suitability("ETHUSDT")

        assert "thresholds" in result
        assert "adx_15m_max" in result["thresholds"]
        assert "rsi_upper" in result["thresholds"]
        assert "rsi_lower" in result["thresholds"]
        assert "atr_pct_max" in result["thresholds"]
        assert "adx_1m_max" in result["thresholds"]

    def test_scores_in_result(self, gate_service, mock_indicator_service):
        """Result includes the actual indicator scores."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 18.0,
            "rsi": 50.0,
            "atr_pct": 0.02,
        }

        result = gate_service.check_suitability("ETHUSDT")

        assert "scores" in result
        assert result["scores"]["adx_15m"] == 18.0
        assert result["scores"]["rsi_15m"] == 50.0
        assert result["scores"]["atr_pct"] == 0.02
