"""
Tests for Breakout Guard feature.

Tests breakout detection, position flattening, and cooldown behavior.
"""

import pytest
from unittest.mock import patch


class TestBreakoutGuard:
    """Tests for Breakout Guard feature."""

    def test_no_breakout_when_price_in_range(self, nlp_service, sample_neutral_bot):
        """Price within range should not trigger breakout."""
        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2000.0,  # Within 1900-2100 range
        )
        assert result["triggered"] is False
        assert result["action"] is None

    def test_breakout_tracking_starts_on_breach(self, nlp_service, sample_neutral_bot, mock_client):
        """First price breach should start tracking."""
        # Price above upper (2100 * 1.002 = 2104.2)
        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2110.0,
        )
        assert result["triggered"] is False
        assert result["side"] == "UP"
        assert "breakout_started" in result["reason"]

        # Verify state was set
        nlp_state = sample_neutral_bot.get("_nlp_state", {})
        assert nlp_state.get("breakout_side") == "UP"
        assert nlp_state.get("breakout_first_ts") is not None

    def test_breakout_triggered_after_hold_time(self, nlp_service, sample_neutral_bot, mock_client):
        """Price outside range for hold_seconds should trigger breakout."""
        # Set initial breakout timestamp 60 seconds ago
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_first_ts"] = mock_client._get_now_ts() - 60
        nlp_state["breakout_side"] = "UP"

        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2110.0,  # Above breakout threshold
        )
        assert result["triggered"] is True
        assert result["side"] == "UP"
        assert result["action"] == "flatten"
        assert "hold_time" in result["reason"]

    def test_breakout_detected_by_candle_closes(self, nlp_service, sample_neutral_bot, mock_client):
        """Two consecutive candle closes outside range should trigger."""
        # The candle check runs after time-based tracking.
        # To reach candle check with price outside range:
        # 1. Set breakout_side to match current_side (so it doesn't return "breakout_started")
        # 2. Set breakout_first_ts recently (so hold_time hasn't elapsed)
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_side"] = "UP"
        nlp_state["breakout_first_ts"] = mock_client._get_now_ts() - 10  # 10s ago (< 45s)

        candles = [
            {"close": 2110.0},  # Above range (2100)
            {"close": 2115.0},  # Above range - 2 consecutive closes
        ]
        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2115.0,
            candles_1m=candles,
        )
        assert result["triggered"] is True
        assert result["side"] == "UP"
        assert "candle_closes" in result["reason"]

    def test_downside_breakout_detected(self, nlp_service, sample_neutral_bot, mock_client):
        """Downside breakout should be detected."""
        # Set initial breakout timestamp 60 seconds ago
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_first_ts"] = mock_client._get_now_ts() - 60
        nlp_state["breakout_side"] = "DOWN"

        # Price below lower (1900 * 0.998 = 1896.2)
        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=1890.0,
        )
        assert result["triggered"] is True
        assert result["side"] == "DOWN"

    def test_breakout_cooldown_blocks_detection(self, nlp_service, sample_neutral_bot, mock_client):
        """During cooldown, breakout should not be triggered."""
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_cooldown_until"] = mock_client._get_now_ts() + 300

        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2110.0,
        )
        assert result["triggered"] is False
        assert result["action"] == "in_cooldown"

    def test_breakout_tracking_resets_when_back_in_range(self, nlp_service, sample_neutral_bot, mock_client):
        """Tracking should reset when price returns to range."""
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_first_ts"] = mock_client._get_now_ts() - 30
        nlp_state["breakout_side"] = "UP"

        # Price back in range
        result = nlp_service.check_breakout_guard(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2000.0,
        )
        assert result["triggered"] is False

        # Verify state was reset
        nlp_state = sample_neutral_bot.get("_nlp_state", {})
        assert nlp_state.get("breakout_side") is None
        assert nlp_state.get("breakout_first_ts") is None

    def test_flatten_cancels_orders_and_closes_position(self, nlp_service, sample_neutral_bot, mock_client):
        """Flatten should cancel all orders and close positions."""
        # First call returns position (for flatten), second returns empty (for verification)
        mock_client.get_positions.side_effect = [
            {
                "success": True,
                "data": {"list": [{
                    "symbol": "ETHUSDT",
                    "side": "Buy",
                    "size": "0.1",
                    "positionIdx": 1,
                }]},
            },
            {
                "success": True,
                "data": {"list": []},
            },
        ]

        result = nlp_service.execute_breakout_flatten(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            side="UP",
        )

        assert result["success"] is True
        mock_client.cancel_all_orders.assert_called_once_with("ETHUSDT")
        mock_client.create_order.assert_called()  # For reduce-only close

        # Verify cooldown was set
        nlp_state = sample_neutral_bot.get("_nlp_state", {})
        assert nlp_state.get("breakout_cooldown_until") is not None

        # Verify bot stays running (not paused) but blocks new orders
        assert sample_neutral_bot["status"] == "running"
        assert sample_neutral_bot.get("_nlp_block_opening_orders") is True

    def test_cooldown_expiry_check(self, nlp_service, sample_neutral_bot, mock_client):
        """Cooldown expiry should be correctly detected."""
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)

        # Cooldown not expired
        nlp_state["breakout_cooldown_until"] = mock_client._get_now_ts() + 300
        assert nlp_service.check_breakout_cooldown_expired(sample_neutral_bot) is False

        # Cooldown expired
        nlp_state["breakout_cooldown_until"] = mock_client._get_now_ts() - 10
        assert nlp_service.check_breakout_cooldown_expired(sample_neutral_bot) is True

        # No cooldown set
        nlp_state["breakout_cooldown_until"] = None
        assert nlp_service.check_breakout_cooldown_expired(sample_neutral_bot) is True

    def test_rebuild_grid_after_cooldown(self, nlp_service, sample_neutral_bot):
        """Grid should be rebuilt after cooldown expires."""
        nlp_state = nlp_service._get_nlp_state(sample_neutral_bot)
        nlp_state["breakout_cooldown_until"] = 1704790800.0

        result = nlp_service.rebuild_grid_after_breakout(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            current_price=2050.0,
        )

        assert result["success"] is True

        # Verify grid state was cleared
        assert sample_neutral_bot.get("neutral_grid") == {}
        assert sample_neutral_bot.get("neutral_grid_initialized") is False
        assert sample_neutral_bot.get("status") == "running"

        # Verify cooldown was cleared
        nlp_state = sample_neutral_bot.get("_nlp_state", {})
        assert nlp_state.get("breakout_cooldown_until") is None
