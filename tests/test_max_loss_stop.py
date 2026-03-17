"""
Tests for Max Loss / Equity Stop feature.

Tests unrealized PnL monitoring and emergency stop behavior.
"""

import pytest
from unittest.mock import patch


class TestMaxLossStop:
    """Tests for Max Loss Stop feature."""

    def test_no_trigger_when_profitable(self, nlp_service, bot_with_long_position):
        """Should not trigger when position is profitable."""
        result = nlp_service.check_max_loss(
            bot=bot_with_long_position,
            symbol="ETHUSDT",
        )
        assert result["triggered"] is False
        assert result["action"] is None

    def test_trigger_when_loss_exceeds_threshold(self, nlp_service, bot_with_losing_position, mock_client):
        """Should trigger when unrealized loss exceeds threshold."""
        # MAJOR preset uses 5% of investment ($100 * 5% = -$5 threshold)
        # Set loss higher than this threshold
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.1",
                "avgPrice": "2000",
                "positionIdx": 1,
                "unrealisedPnl": "-6.0",  # Exceeds 5% threshold
            }]}
        }
        result = nlp_service.check_max_loss(
            bot=bot_with_losing_position,
            symbol="ETHUSDT",
        )
        assert result["triggered"] is True
        assert result["action"] == "flatten"
        assert result["upnl"] == -6.0

    def test_threshold_uses_pct_for_major_preset(self, nlp_service, sample_neutral_bot, mock_client):
        """MAJOR preset uses percentage-based threshold (5% of investment)."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.1",
                "avgPrice": "2000",
                "positionIdx": 1,
                "unrealisedPnl": "-4.0",  # Below 5% ($5) threshold for $100 investment
            }]}
        }

        result = nlp_service.check_max_loss(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        # MAJOR preset: max_loss_pct=0.05, investment=$100, threshold=-$5
        assert result["triggered"] is False
        assert result["threshold"] == -5.0  # 5% of $100 investment

    def test_cooldown_blocks_trigger(self, nlp_service, bot_with_losing_position, mock_client):
        """Should not trigger during cooldown."""
        nlp_state = nlp_service._get_nlp_state(bot_with_losing_position)
        nlp_state["max_loss_cooldown_until"] = mock_client._get_now_ts() + 300

        result = nlp_service.check_max_loss(
            bot=bot_with_losing_position,
            symbol="ETHUSDT",
        )
        assert result["triggered"] is False
        assert result["action"] == "in_cooldown"

    def test_execute_max_loss_stop(self, nlp_service, bot_with_losing_position, mock_client):
        """Should cancel orders, flatten, and enter cooldown."""
        # Call sequence: check_max_loss→get_positions (1), flatten→get_positions (2),
        # verification→get_positions (3). First two need position data, third must be empty.
        position_data = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT", "side": "Buy", "size": "0.1",
                "avgPrice": "2000", "positionIdx": 1, "unrealisedPnl": "-1.5",
            }]}
        }
        empty_positions = {"success": True, "data": {"list": []}}
        mock_client.get_positions.side_effect = [position_data, position_data, empty_positions, empty_positions]

        result = nlp_service.execute_max_loss_stop(
            bot=bot_with_losing_position,
            symbol="ETHUSDT",
        )

        assert result["success"] is True

        # Verify orders cancelled
        mock_client.cancel_all_orders.assert_called_once_with("ETHUSDT")

        # Verify position closed
        mock_client.create_order.assert_called()
        call_kwargs = mock_client.create_order.call_args[1]
        assert call_kwargs["reduce_only"] is True

        # Verify bot status
        assert bot_with_losing_position["status"] == "stopped"
        assert "MAX_LOSS_STOP" in bot_with_losing_position["last_error"]

        # Verify cooldown set
        nlp_state = bot_with_losing_position.get("_nlp_state", {})
        assert nlp_state.get("max_loss_cooldown_until") is not None

    def test_multiple_positions_summed(self, nlp_service, sample_neutral_bot, mock_client):
        """Should sum unrealized PnL across multiple positions."""
        # MAJOR preset uses 5% threshold = -$5 for $100 investment
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.1",
                    "avgPrice": "2000",
                    "positionIdx": 1,
                    "unrealisedPnl": "-3.0",
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "Sell",
                    "size": "0.1",
                    "avgPrice": "2000",
                    "positionIdx": 2,
                    "unrealisedPnl": "-3.0",
                }
            ]}
        }

        result = nlp_service.check_max_loss(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        # Total uPnL = -6.0, exceeds 5% ($5) threshold
        assert result["triggered"] is True
        assert result["upnl"] == -6.0

    def test_ignores_other_symbols(self, nlp_service, sample_neutral_bot, mock_client):
        """Should only consider positions for the bot's symbol."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.1",
                    "avgPrice": "2000",
                    "positionIdx": 1,
                    "unrealisedPnl": "-0.5",
                },
                {
                    "symbol": "BTCUSDT",  # Different symbol
                    "side": "Buy",
                    "size": "0.01",
                    "avgPrice": "50000",
                    "positionIdx": 1,
                    "unrealisedPnl": "-10.0",  # Should be ignored
                }
            ]}
        }

        result = nlp_service.check_max_loss(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        # Only ETHUSDT uPnL should be counted
        assert result["triggered"] is False
        assert result["upnl"] == -0.5

    def test_no_position_returns_zero_upnl(self, nlp_service, sample_neutral_bot, mock_client):
        """Should return zero uPnL when no position exists."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": []}
        }

        result = nlp_service.check_max_loss(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["triggered"] is False
        assert result["upnl"] == 0
