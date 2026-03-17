"""
Tests for emergency orderLinkId generation (hedge-safe).

Validates uniqueness and format of orderLinkIds used for emergency orders.
"""

import pytest
from unittest.mock import Mock


class TestOrderLinkIdGeneration:
    """Tests for _generate_emergency_order_link_id() method."""

    def test_format_length_within_limit(self, nlp_service, sample_neutral_bot):
        """orderLinkId must be <= 36 chars (Bybit limit)."""
        order_link_id = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "BRK", 1
        )
        assert len(order_link_id) <= 36, f"orderLinkId too long: {len(order_link_id)} chars"

    def test_format_structure(self, nlp_service, sample_neutral_bot):
        """orderLinkId should follow format: nlp:{bot12}:{action}:{pidx}:{ms10}:{c2}."""
        order_link_id = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "BRK", 1
        )
        parts = order_link_id.split(":")
        assert len(parts) == 6, f"Expected 6 parts, got {len(parts)}: {order_link_id}"
        assert parts[0] == "nlp", f"Expected 'nlp' prefix, got: {parts[0]}"
        assert len(parts[1]) <= 12, f"Bot ID should be <= 12 chars, got: {len(parts[1])}"
        assert parts[2] == "BRK", f"Expected 'BRK' action, got: {parts[2]}"
        assert parts[3] == "1", f"Expected positionIdx '1', got: {parts[3]}"
        assert len(parts[4]) == 10, f"Timestamp should be 10 chars, got: {len(parts[4])}"
        assert len(parts[5]) == 2, f"Counter should be 2 chars, got: {len(parts[5])}"

    def test_format_structure_with_long_id(self, nlp_service):
        """orderLinkId with long bot ID should truncate to 12 chars."""
        bot = {
            "id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4",  # Long ID
            "mode": "neutral_classic_bybit",
            "_nlp_state": {},
        }
        order_link_id = nlp_service._generate_emergency_order_link_id(bot, "BRK", 1)
        parts = order_link_id.split(":")
        assert len(parts[1]) == 12, f"Bot ID should be exactly 12 chars for long IDs, got: {len(parts[1])}"
        assert parts[1] == "a1b2c3d4e5f6"

    def test_uniqueness_same_millisecond_same_pidx(self, nlp_service, sample_neutral_bot, mock_client):
        """Multiple calls within same ms should produce unique IDs via counter."""
        # Fixed timestamp (mocked in conftest)
        ids = set()
        for _ in range(10):
            order_link_id = nlp_service._generate_emergency_order_link_id(
                sample_neutral_bot, "BRK", 1
            )
            ids.add(order_link_id)

        assert len(ids) == 10, f"Expected 10 unique IDs, got {len(ids)}"

    def test_uniqueness_across_position_idx(self, nlp_service, sample_neutral_bot):
        """Different positionIdx should produce different IDs even at same timestamp."""
        id_long = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "BRK", 1
        )
        id_short = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "BRK", 2
        )
        assert id_long != id_short, "Long and short leg IDs should be different"

        # Verify positionIdx is in the ID
        assert ":1:" in id_long, f"positionIdx 1 not found in: {id_long}"
        assert ":2:" in id_short, f"positionIdx 2 not found in: {id_short}"

    def test_counter_wraps_at_100(self, nlp_service, sample_neutral_bot):
        """Counter should wrap from 99 to 00."""
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["emergency_olid_counter"] = 99

        # This call uses counter 99
        id1 = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "INV", 1
        )

        # Counter should have wrapped to 0
        assert nlp_state["emergency_olid_counter"] == 0

        # This call uses counter 0
        id2 = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "INV", 1
        )

        # Counter should now be 1
        assert nlp_state["emergency_olid_counter"] == 1

        # Verify IDs are different
        assert id1 != id2

    def test_different_actions_produce_different_ids(self, nlp_service, sample_neutral_bot):
        """Different action codes should produce different IDs."""
        # Reset counter to get consistent comparison
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["emergency_olid_counter"] = 0

        id_brk = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "BRK", 1
        )

        nlp_state["emergency_olid_counter"] = 0  # Reset
        id_inv = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "INV", 1
        )

        nlp_state["emergency_olid_counter"] = 0  # Reset
        id_max = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "MAX", 1
        )

        # With same counter and timestamp, only action differs
        assert ":BRK:" in id_brk
        assert ":INV:" in id_inv
        assert ":MAX:" in id_max

        # All should be different
        assert len({id_brk, id_inv, id_max}) == 3

    def test_missing_bot_id_uses_fallback(self, nlp_service):
        """Bot with missing ID should use 'unknown' fallback."""
        bot_no_id = {"mode": "neutral_classic_bybit", "_nlp_state": {}}

        order_link_id = nlp_service._generate_emergency_order_link_id(
            bot_no_id, "BRK", 0
        )

        assert order_link_id.startswith("nlp:unknown")

    def test_position_idx_zero_for_one_way(self, nlp_service, sample_neutral_bot):
        """One-way mode should use positionIdx=0."""
        order_link_id = nlp_service._generate_emergency_order_link_id(
            sample_neutral_bot, "BRK", 0
        )

        parts = order_link_id.split(":")
        assert parts[3] == "0", f"Expected positionIdx '0', got: {parts[3]}"

    def test_bot_id_with_dashes_normalized(self, nlp_service):
        """Bot ID with dashes should be normalized (dashes removed)."""
        bot = {
            "id": "a1b2-c3d4-e5f6-g7h8-i9j0",
            "mode": "neutral_classic_bybit",
            "_nlp_state": {},
        }

        order_link_id = nlp_service._generate_emergency_order_link_id(
            bot, "MAX", 2
        )

        parts = order_link_id.split(":")
        # Should be first 12 chars without dashes: "a1b2c3d4e5f6"
        assert parts[1] == "a1b2c3d4e5f6", f"Expected 'a1b2c3d4e5f6', got: {parts[1]}"
        assert "-" not in parts[1]
