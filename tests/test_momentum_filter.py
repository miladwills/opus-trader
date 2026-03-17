"""
Tests for Momentum Filter feature.

Tests ADX, RSI, and Bollinger Band blocking logic.
"""

import pytest
from unittest.mock import patch


class TestMomentumFilter:
    """Tests for Momentum Filter feature."""

    def test_no_block_in_neutral_conditions(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should not block when indicators are neutral."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 20.0,
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is False

    def test_block_on_high_adx(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should block when ADX > threshold."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 30.0,  # > 25 threshold
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is True
        assert "ADX" in result["reason"]

    def test_block_on_overbought_rsi(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should block when RSI > upper threshold."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 70.0,  # > 65 threshold
            "adx": 20.0,
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is True
        assert "RSI" in result["reason"]
        # Threshold varies by preset (MAJOR=68, MEME=62, global=65)
        assert ">" in result["reason"]

    def test_block_on_oversold_rsi(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should block when RSI < lower threshold."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 25.0,  # Very oversold - below all preset thresholds
            "adx": 20.0,
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is True
        assert "RSI" in result["reason"]
        # Threshold varies by preset (MAJOR=32, MEME=38, global=35)
        assert "<" in result["reason"]

    def test_block_on_bb_upper_touch(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should block when price is at BB upper."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 20.0,
            "close": 2050.0,  # At BB upper
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is True
        assert "BB_upper" in result["reason"]

    def test_block_on_bb_lower_touch(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should block when price is at BB lower."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 20.0,
            "close": 1950.0,  # At BB lower
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is True
        assert "BB_lower" in result["reason"]

    def test_bb_position_calculation(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should calculate BB position correctly."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 20.0,
            "close": 2000.0,  # Middle of BB range
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["bb_position"] == 50.0  # Middle

    def test_multiple_reasons_combined(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should report all blocking reasons."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 70.0,  # Overbought
            "adx": 30.0,  # High trend
            "close": 2050.0,  # At BB upper
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is True
        assert "ADX" in result["reason"]
        assert "RSI" in result["reason"]
        assert "BB" in result["reason"]

    def test_updates_nlp_state(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """Should update NLP state with block status."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 70.0,
            "adx": 30.0,
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )

        nlp_state = sample_neutral_bot.get("_nlp_state", {})
        assert nlp_state.get("momentum_blocked") is True
        assert nlp_state.get("momentum_blocked_reason") is not None

    def test_should_block_grid_placement_combines_checks(self, nlp_service, sample_neutral_bot, mock_indicator_service, mock_client):
        """Combined check should include momentum and cooldown."""
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 20.0,
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        # Set breakout cooldown
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_cooldown_until"] = mock_client._get_now_ts() + 300

        should_block, reason = nlp_service.should_block_grid_placement(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert should_block is True
        assert reason == "breakout_cooldown"

    def test_no_indicator_service_returns_not_blocked(self, mock_client, mock_bot_storage, sample_neutral_bot):
        """Should not block if no indicator service available."""
        from services.neutral_loss_prevention_service import NeutralLossPreventionService

        service = NeutralLossPreventionService(
            client=mock_client,
            bot_storage=mock_bot_storage,
            indicator_service=None,  # No indicator service
        )

        result = service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is False
        assert result["reason"] == "no_indicator_service"
