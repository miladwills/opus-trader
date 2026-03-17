"""
Tests for Inventory/Skew Cap feature.

Tests net exposure calculation, order blocking, and emergency reduce.
"""

import pytest
from unittest.mock import patch


class TestInventoryCap:
    """Tests for Inventory/Skew Cap feature."""

    def test_cap_not_exceeded_allows_orders(self, nlp_service, sample_neutral_bot, mock_client):
        """Net exposure below cap should allow orders."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.05",  # Small position
                "positionIdx": 1,
                "avgPrice": "2000",
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        # 0.05 * 2000 = $100 < 25% of 1000 (inv * lev) = $250
        assert result["exceeded"] is False
        assert result["action"] is None

    def test_cap_exceeded_blocks_opening_orders(self, nlp_service, sample_neutral_bot, mock_client):
        """Net exposure above cap should block opening orders (but not emergency)."""
        # Set position size to exceed cap but not trigger emergency (1.0x-1.5x)
        # Cap = 100 * 10 * 0.25 = $250
        # 0.15 * 2000 = $300 -> 1.2x cap (exceeds but < 1.5x)
        # MAJOR preset uses 30% cap = $300 for $100 * 10x = $1000 notional
        # Position needs to exceed $300 cap
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.20",  # 0.20 * 2000 = $400 > $300 cap
                "avgPrice": "2000",
                "positionIdx": 1,
                "unrealisedPnl": "-0.5",
            }]}
        }
        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        # 0.20 * 2000 = $400 > $300 cap (MAJOR preset 30%)
        assert result["exceeded"] is True
        assert result["action"] == "block_opening"
        assert result["net_side"] == "long"

    def test_emergency_reduce_when_severely_exceeded(self, nlp_service, sample_neutral_bot, mock_client):
        """1.5x over cap should trigger emergency reduce."""
        # 100 * 10 * 0.25 = $250 cap
        # 1.5 * $250 = $375 emergency threshold
        # 0.25 * 2000 = $500 notional (exceeds emergency)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.25",
                "avgPrice": "2000",
                "positionIdx": 1,
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["exceeded"] is True
        assert result["action"] == "emergency_reduce"
        assert result["excess_pct"] >= 1.5

    def test_should_block_buy_when_net_long(self, nlp_service, bot_with_large_long_position):
        """Should block buys when net long and over cap."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_large_long_position,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=False,
        )
        assert should_block is True
        assert "block_order=Buy" in reason

    def test_should_allow_sell_when_net_long(self, nlp_service, bot_with_large_long_position):
        """Should allow sells when net long (reduces exposure)."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_large_long_position,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=False,
        )
        assert should_block is False

    def test_never_block_reduce_only(self, nlp_service, bot_with_large_long_position):
        """Should never block reduce-only orders."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_large_long_position,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=True,
        )
        assert should_block is False

    def test_net_short_position_detected(self, nlp_service, sample_neutral_bot, mock_client):
        """Should detect net short position."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.2",
                "avgPrice": "2000",
                "positionIdx": 2,
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["net_side"] == "short"
        assert result["exceeded"] is True

    def test_should_block_sell_when_net_short(self, nlp_service, sample_neutral_bot, mock_client):
        """Should block sells when net short and over cap."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.2",
                "avgPrice": "2000",
                "positionIdx": 2,
            }]}
        }

        should_block, reason = nlp_service.should_block_order(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=False,
        )
        assert should_block is True
        assert "block_order=Sell" in reason

    def test_balanced_position_not_exceeded(self, nlp_service, sample_neutral_bot, mock_client):
        """Equal long and short positions should have zero net exposure."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.1",
                    "avgPrice": "2000",
                    "positionIdx": 1,
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "Sell",
                    "size": "0.1",
                    "avgPrice": "2000",
                    "positionIdx": 2,
                }
            ]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["exceeded"] is False
        assert result["net_notional"] == 0

    def test_emergency_reduce_execution(self, nlp_service, sample_neutral_bot, mock_client):
        """Emergency reduce should place reduce-only market order."""
        # Set up position that triggers emergency
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.25",
                "avgPrice": "2000",
                "positionIdx": 1,
            }]}
        }

        result = nlp_service.execute_emergency_inventory_reduce(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )

        assert result["success"] is True
        mock_client.create_order.assert_called()

        # Verify it was a reduce-only sell order
        call_kwargs = mock_client.create_order.call_args[1]
        assert call_kwargs["side"] == "Sell"
        assert call_kwargs["reduce_only"] is True

    def test_emergency_reduce_cooldown(self, nlp_service, sample_neutral_bot, mock_client):
        """Emergency reduce should have cooldown."""
        # Set up position that triggers emergency
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.25",
                "avgPrice": "2000",
                "positionIdx": 1,
            }]}
        }

        # Set recent emergency timestamp
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["inventory_emergency_ts"] = mock_client._get_now_ts() - 30  # 30s ago

        result = nlp_service.execute_emergency_inventory_reduce(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )

        assert result["success"] is False
        assert result["reason"] == "emergency_cooldown"
