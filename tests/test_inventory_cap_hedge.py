"""
Tests for Hedge-Mode Inventory Cap feature.

Tests per-leg caps, blocking logic, and emergency reduce for hedge mode.
"""

import pytest
from unittest.mock import patch


class TestHedgeInventoryCap:
    """Tests for hedge-mode inventory cap (per-leg caps)."""

    def test_hedge_balanced_both_legs_exceed_cap(self, nlp_service, bot_with_hedge_positions_balanced):
        """Net ~0 but both legs large should trigger cap on BOTH legs."""
        result = nlp_service.check_inventory_cap(
            bot=bot_with_hedge_positions_balanced,
            symbol="ETHUSDT",
        )
        # Net is ~0, but in hedge mode with per-leg caps, both exceed
        assert result["hedge_mode"] is True
        assert result["exceeded"] is True
        assert result["long_exceeded"] is True
        assert result["short_exceeded"] is True
        assert result["net_notional"] == 0  # Balanced
        assert result["long_notional"] == 400.0  # 0.2 * 2000
        assert result["short_notional"] == 400.0  # 0.2 * 2000

    def test_hedge_long_exceeds_cap_only(self, nlp_service, sample_neutral_bot, mock_client):
        """Only long leg exceeds cap (but not emergency), short is fine."""
        # MAJOR preset: Cap = 100 * 10 * 0.30 = $300
        # Emergency = 1.5 * $300 = $450
        # Set long to $400 (exceeds $300 cap but < $450 emergency)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.20",  # 0.20 * 2000 = $400 (exceeds $300 cap but < $450)
                    "avgPrice": "2000",
                    "positionIdx": 1,
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "Sell",
                    "size": "0.05",  # 0.05 * 2000 = $100 (under cap)
                    "avgPrice": "2000",
                    "positionIdx": 2,
                },
            ]}
        }
        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["hedge_mode"] is True
        assert result["exceeded"] is True
        assert result["long_exceeded"] is True
        assert result["short_exceeded"] is False
        assert result["long_action"] == "block_long_opening"
        assert result["short_action"] is None

    def test_hedge_short_exceeds_cap_only(self, nlp_service, sample_neutral_bot, mock_client):
        """Only short leg exceeds cap (but not emergency), long is fine."""
        # MAJOR preset: Cap = 100 * 10 * 0.30 = $300
        # Emergency = 1.5 * $300 = $450
        # Set short to $400 (exceeds $300 cap but < $450 emergency)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.05",  # 0.05 * 2000 = $100 (under cap)
                    "avgPrice": "2000",
                    "positionIdx": 1,
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "Sell",
                    "size": "0.20",  # 0.20 * 2000 = $400 (exceeds $300 cap but < $450)
                    "avgPrice": "2000",
                    "positionIdx": 2,
                },
            ]}
        }
        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["hedge_mode"] is True
        assert result["exceeded"] is True
        assert result["long_exceeded"] is False
        assert result["short_exceeded"] is True
        assert result["long_action"] is None
        assert result["short_action"] == "block_short_opening"

    def test_hedge_both_legs_emergency(self, nlp_service, bot_with_hedge_both_emergency):
        """Both legs exceed emergency threshold (1.5x)."""
        result = nlp_service.check_inventory_cap(
            bot=bot_with_hedge_both_emergency,
            symbol="ETHUSDT",
        )
        assert result["hedge_mode"] is True
        assert result["exceeded"] is True
        assert result["action"] == "emergency_reduce"
        assert result["long_action"] == "emergency_reduce_long"
        assert result["short_action"] == "emergency_reduce_short"

    def test_hedge_block_buy_when_long_exceeded(self, nlp_service, bot_with_hedge_long_exceeded):
        """Should block buys when long leg exceeded."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_hedge_long_exceeded,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=False,
        )
        assert should_block is True
        assert "INVENTORY_CAP_HEDGE" in reason
        assert "block_order=Buy" in reason

    def test_hedge_allow_sell_when_long_exceeded(self, nlp_service, bot_with_hedge_long_exceeded):
        """Should allow sells when only long leg exceeded (sells reduce short, ok)."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_hedge_long_exceeded,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=False,
        )
        assert should_block is False

    def test_hedge_block_sell_when_short_exceeded(self, nlp_service, bot_with_hedge_short_exceeded):
        """Should block sells when short leg exceeded."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_hedge_short_exceeded,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=False,
        )
        assert should_block is True
        assert "INVENTORY_CAP_HEDGE" in reason
        assert "block_order=Sell" in reason

    def test_hedge_allow_buy_when_short_exceeded(self, nlp_service, bot_with_hedge_short_exceeded):
        """Should allow buys when only short leg exceeded (buys reduce long, ok)."""
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_hedge_short_exceeded,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=False,
        )
        assert should_block is False

    def test_hedge_block_both_sides_when_both_exceeded(self, nlp_service, bot_with_hedge_positions_balanced):
        """Should block both buys and sells when both legs exceeded."""
        should_block_buy, _ = nlp_service.should_block_order(
            bot=bot_with_hedge_positions_balanced,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=False,
        )
        should_block_sell, _ = nlp_service.should_block_order(
            bot=bot_with_hedge_positions_balanced,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=False,
        )
        assert should_block_buy is True
        assert should_block_sell is True

    def test_hedge_never_block_reduce_only(self, nlp_service, bot_with_hedge_positions_balanced):
        """Should never block reduce-only orders."""
        should_block_buy, _ = nlp_service.should_block_order(
            bot=bot_with_hedge_positions_balanced,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=True,
        )
        should_block_sell, _ = nlp_service.should_block_order(
            bot=bot_with_hedge_positions_balanced,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=True,
        )
        assert should_block_buy is False
        assert should_block_sell is False


class TestHedgeEmergencyReduce:
    """Tests for hedge-mode emergency reduce."""

    def test_hedge_emergency_reduce_targets_long_leg(self, nlp_service, mock_client, sample_neutral_bot):
        """Emergency reduce should target positionIdx=1 for long leg."""
        # Set up long leg exceeding emergency threshold
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.25",  # $500 (exceeds $375 emergency)
                    "avgPrice": "2000",
                    "positionIdx": 1,
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "Sell",
                    "size": "0.05",  # $100 (under cap)
                    "avgPrice": "2000",
                    "positionIdx": 2,
                },
            ]}
        }

        result = nlp_service.execute_emergency_inventory_reduce(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )

        assert result["success"] is True
        assert "long" in result.get("legs_reduced", [])
        # Verify order was placed with correct positionIdx
        call_kwargs = mock_client.create_order.call_args[1]
        assert call_kwargs["position_idx"] == 1
        assert call_kwargs["side"] == "Sell"  # Close long
        assert call_kwargs["reduce_only"] is True
        assert call_kwargs["ownership_snapshot"]["bot_id"] == sample_neutral_bot["id"]
        assert call_kwargs["ownership_snapshot"]["source"] == "neutral_loss_prevention_service"
        assert call_kwargs["ownership_snapshot"]["action"] == "nlp_close"

    def test_hedge_emergency_reduce_targets_short_leg(self, nlp_service, mock_client, sample_neutral_bot):
        """Emergency reduce should target positionIdx=2 for short leg."""
        # Set up short leg exceeding emergency threshold
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [
                {
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.05",  # $100 (under cap)
                    "avgPrice": "2000",
                    "positionIdx": 1,
                },
                {
                    "symbol": "ETHUSDT",
                    "side": "Sell",
                    "size": "0.25",  # $500 (exceeds $375 emergency)
                    "avgPrice": "2000",
                    "positionIdx": 2,
                },
            ]}
        }

        result = nlp_service.execute_emergency_inventory_reduce(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )

        assert result["success"] is True
        assert "short" in result.get("legs_reduced", [])
        # Verify order was placed with correct positionIdx
        call_kwargs = mock_client.create_order.call_args[1]
        assert call_kwargs["position_idx"] == 2
        assert call_kwargs["side"] == "Buy"  # Close short
        assert call_kwargs["reduce_only"] is True
        assert call_kwargs["ownership_snapshot"]["bot_id"] == sample_neutral_bot["id"]
        assert call_kwargs["ownership_snapshot"]["source"] == "neutral_loss_prevention_service"
        assert call_kwargs["ownership_snapshot"]["action"] == "nlp_close"

    def test_hedge_emergency_reduce_both_legs(self, nlp_service, bot_with_hedge_both_emergency, mock_client):
        """Emergency reduce should handle both legs when both exceed emergency."""
        result = nlp_service.execute_emergency_inventory_reduce(
            bot=bot_with_hedge_both_emergency,
            symbol="ETHUSDT",
        )

        assert result["success"] is True
        assert "long" in result.get("legs_reduced", [])
        assert "short" in result.get("legs_reduced", [])
        # Should have placed 2 orders
        assert mock_client.create_order.call_count == 2


class TestOneWayModeUnchanged:
    """Tests that one-way mode behavior remains unchanged."""

    def test_one_way_uses_net_exposure(self, nlp_service, bot_with_one_way_position):
        """One-way mode should use net exposure (not per-leg)."""
        result = nlp_service.check_inventory_cap(
            bot=bot_with_one_way_position,
            symbol="ETHUSDT",
        )
        # positionIdx=0 means one-way mode
        assert result["hedge_mode"] is False
        assert result["exceeded"] is True  # $400 > $250 cap
        assert result["net_notional"] == 400.0
        # No per-leg fields in one-way mode
        assert result["long_exceeded"] is False
        assert result["short_exceeded"] is False

    def test_one_way_block_based_on_net_side(self, nlp_service, bot_with_one_way_position):
        """One-way mode should block based on net side, not per-leg."""
        # Net long -> block buys
        should_block, reason = nlp_service.should_block_order(
            bot=bot_with_one_way_position,
            symbol="ETHUSDT",
            side="Buy",
            reduce_only=False,
        )
        assert should_block is True
        assert "INVENTORY_CAP block_order" in reason  # Not INVENTORY_CAP_HEDGE

        # Net long -> allow sells
        should_block, _ = nlp_service.should_block_order(
            bot=bot_with_one_way_position,
            symbol="ETHUSDT",
            side="Sell",
            reduce_only=False,
        )
        assert should_block is False

    def test_one_way_emergency_reduce_uses_net(self, nlp_service, mock_client, sample_neutral_bot):
        """One-way emergency reduce should use net-based logic."""
        # Set up one-way position exceeding emergency (1.5x cap)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.25",  # $500 (exceeds $375 emergency)
                "avgPrice": "2000",
                "positionIdx": 0,  # One-way mode
            }]}
        }

        result = nlp_service.execute_emergency_inventory_reduce(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )

        assert result["success"] is True
        # Should NOT have legs_reduced (one-way mode)
        assert "legs_reduced" not in result or not result.get("legs_reduced")
        assert "reduced_qty" in result


class TestHedgeModeDetection:
    """Tests for hedge mode detection from positions."""

    def test_detects_hedge_mode_from_position_idx_1(self, nlp_service, sample_neutral_bot, mock_client):
        """Should detect hedge mode when positionIdx=1 is present."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.1",
                "avgPrice": "2000",
                "positionIdx": 1,  # Hedge long
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["hedge_mode"] is True

    def test_detects_hedge_mode_from_position_idx_2(self, nlp_service, sample_neutral_bot, mock_client):
        """Should detect hedge mode when positionIdx=2 is present."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.1",
                "avgPrice": "2000",
                "positionIdx": 2,  # Hedge short
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["hedge_mode"] is True

    def test_detects_one_way_from_position_idx_0(self, nlp_service, sample_neutral_bot, mock_client):
        """Should detect one-way mode when only positionIdx=0 is present."""
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.1",
                "avgPrice": "2000",
                "positionIdx": 0,  # One-way
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["hedge_mode"] is False
