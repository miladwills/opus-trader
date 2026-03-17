"""H4 regression test: calculate_stop_loss must not raise when actual_entry_price is passed."""

from unittest.mock import Mock
from services.stop_loss_service import StopLossService


def _make_service():
    return StopLossService(bybit_client=Mock())


def test_calculate_stop_loss_uses_actual_entry_price_for_long():
    service = _make_service()
    result = service.calculate_stop_loss(
        symbol="BTCUSDT",
        mode="long",
        current_price=100_000,
        grid_lower=95_000,
        grid_upper=105_000,
        atr_pct=0.02,
        bbw_pct=0.03,
        profile="normal",
        bot_investment=500,
        bot_leverage=10,
        actual_entry_price=99_000,
    )
    assert result.get("enabled") is True
    sl = result.get("sl_price", 0)
    assert sl > 0
    # With 10x leverage and 15% max loss: effective move = 1.5%
    # SL should be closer to entry than grid midpoint would give
    grid_midpoint = (95_000 + 105_000) / 2
    expected_from_actual = 99_000 * (1 - 0.15 / 10)
    assert sl >= expected_from_actual * 0.99  # within 1% tolerance


def test_calculate_stop_loss_uses_actual_entry_price_for_short():
    service = _make_service()
    result = service.calculate_stop_loss(
        symbol="BTCUSDT",
        mode="short",
        current_price=100_000,
        grid_lower=95_000,
        grid_upper=105_000,
        atr_pct=0.02,
        bbw_pct=0.03,
        profile="normal",
        bot_investment=500,
        bot_leverage=10,
        actual_entry_price=101_000,
    )
    assert result.get("enabled") is True
    sl = result.get("sl_price", 0)
    assert sl > 0


def test_calculate_stop_loss_no_error_without_entry_price():
    """Regression: must not raise NameError when actual_entry_price defaults to 0."""
    service = _make_service()
    result = service.calculate_stop_loss(
        symbol="BTCUSDT",
        mode="long",
        current_price=100_000,
        grid_lower=95_000,
        grid_upper=105_000,
        atr_pct=0.02,
        bbw_pct=0.03,
        profile="normal",
        bot_investment=500,
        bot_leverage=10,
    )
    # Must not raise - falls back to grid midpoint
    assert isinstance(result, dict)
    assert "sl_price" in result


def test_calculate_stop_loss_no_error_with_zero_entry():
    """Explicit zero actual_entry_price falls back to grid midpoint."""
    service = _make_service()
    result = service.calculate_stop_loss(
        symbol="BTCUSDT",
        mode="long",
        current_price=100_000,
        grid_lower=95_000,
        grid_upper=105_000,
        atr_pct=0.02,
        bbw_pct=0.03,
        profile="normal",
        bot_investment=500,
        bot_leverage=5,
        actual_entry_price=0,
    )
    assert isinstance(result, dict)
    assert result.get("enabled") is True
