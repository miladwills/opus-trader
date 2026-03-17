"""
Pytest fixtures for testing loss-prevention features.
"""

import pytest
from unittest.mock import Mock, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.neutral_loss_prevention_service import NeutralLossPreventionService
from services.neutral_suitability_service import NeutralSuitabilityService


@pytest.fixture
def mock_client():
    """Mock BybitClient with common responses."""
    client = Mock()
    client._get_now_ts = Mock(return_value=1704790800.0)  # Fixed timestamp
    client.get_positions = Mock(return_value={
        "success": True,
        "data": {"list": []}
    })
    client.get_open_orders = Mock(return_value={
        "success": True,
        "data": {"list": []}
    })
    client.cancel_all_orders = Mock(return_value={"success": True})
    client.create_order = Mock(return_value={"success": True, "data": {"orderId": "123"}})
    client.normalize_qty = Mock(side_effect=lambda symbol, qty, **kw: qty)
    return client


@pytest.fixture
def mock_bot_storage():
    """Mock BotStorageService."""
    storage = Mock()
    storage.save_bot = Mock(return_value=None)
    storage.get_bot = Mock(return_value=None)
    return storage


@pytest.fixture
def mock_indicator_service():
    """Mock IndicatorService with neutral market conditions."""
    service = Mock()
    service.compute_indicators = Mock(return_value={
        "rsi": 50.0,
        "adx": 20.0,
        "bbw_pct": 0.03,
        "close": 2000.0,
        "bb_upper": 2050.0,
        "bb_lower": 1950.0,
    })
    service.get_ohlcv = Mock(return_value=[
        {"close": 1995.0, "open": 1990.0, "high": 2000.0, "low": 1990.0},
        {"close": 2000.0, "open": 1995.0, "high": 2005.0, "low": 1995.0},
    ])
    return service


@pytest.fixture
def mock_neutral_grid_service():
    """Mock NeutralGridService."""
    return Mock()


@pytest.fixture
def nlp_service(mock_client, mock_bot_storage, mock_indicator_service, mock_neutral_grid_service):
    """NeutralLossPreventionService with mocked dependencies."""
    return NeutralLossPreventionService(
        client=mock_client,
        bot_storage=mock_bot_storage,
        indicator_service=mock_indicator_service,
        neutral_grid_service=mock_neutral_grid_service,
    )


@pytest.fixture
def gate_service(mock_indicator_service):
    """NeutralSuitabilityService (gate) with mocked dependencies."""
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
        "investment_usdt": 100.0,
        "leverage": 10.0,
        "grid_lower_price": 1900.0,
        "grid_upper_price": 2100.0,
        "lower_price": 1900.0,
        "upper_price": 2100.0,
        "grid_levels_total": 20,
        "current_price": 2000.0,
        "neutral_grid": {
            "levels": [1900.0 + i * 10 for i in range(21)],
            "lower_price": 1900.0,
            "upper_price": 2100.0,
            "slots": {},
        },
        "_nlp_state": {},
    }


@pytest.fixture
def bot_with_long_position(sample_neutral_bot, mock_client):
    """Bot with an existing long position."""
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{
            "symbol": "ETHUSDT",
            "side": "Buy",
            "size": "0.1",
            "avgPrice": "2000",
            "positionIdx": 1,
            "unrealisedPnl": "0.5",
        }]}
    }
    return sample_neutral_bot


@pytest.fixture
def bot_with_large_long_position(sample_neutral_bot, mock_client):
    """Bot with a large long position exceeding inventory cap."""
    # 100 * 10 * 0.25 = $250 cap
    # 0.2 * 2000 = $400 notional (exceeds cap)
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{
            "symbol": "ETHUSDT",
            "side": "Buy",
            "size": "0.2",
            "avgPrice": "2000",
            "positionIdx": 1,
            "unrealisedPnl": "-0.5",
        }]}
    }
    return sample_neutral_bot


@pytest.fixture
def bot_with_losing_position(sample_neutral_bot, mock_client):
    """Bot with a losing position."""
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{
            "symbol": "ETHUSDT",
            "side": "Buy",
            "size": "0.1",
            "avgPrice": "2000",
            "positionIdx": 1,
            "unrealisedPnl": "-1.5",  # Exceeds $1 max loss default
        }]}
    }
    return sample_neutral_bot


# =============================================================================
# Hedge Mode Fixtures
# =============================================================================

@pytest.fixture
def bot_with_hedge_positions_balanced(sample_neutral_bot, mock_client):
    """Bot with balanced hedge positions (net ~0 but both legs large)."""
    # 100 * 10 * 0.25 = $250 cap per leg
    # Both legs at $400 notional (exceeds cap)
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [
            {
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.2",  # 0.2 * 2000 = $400
                "avgPrice": "2000",
                "positionIdx": 1,  # Long leg
                "unrealisedPnl": "0",
            },
            {
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.2",  # 0.2 * 2000 = $400
                "avgPrice": "2000",
                "positionIdx": 2,  # Short leg
                "unrealisedPnl": "0",
            },
        ]}
    }
    return sample_neutral_bot


@pytest.fixture
def bot_with_hedge_long_exceeded(sample_neutral_bot, mock_client):
    """Bot with hedge positions where only long leg exceeds cap."""
    # 100 * 10 * 0.25 = $250 cap per leg
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [
            {
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.2",  # 0.2 * 2000 = $400 (exceeds $250)
                "avgPrice": "2000",
                "positionIdx": 1,  # Long leg
                "unrealisedPnl": "0",
            },
            {
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.05",  # 0.05 * 2000 = $100 (under cap)
                "avgPrice": "2000",
                "positionIdx": 2,  # Short leg
                "unrealisedPnl": "0",
            },
        ]}
    }
    return sample_neutral_bot


@pytest.fixture
def bot_with_hedge_short_exceeded(sample_neutral_bot, mock_client):
    """Bot with hedge positions where only short leg exceeds cap."""
    # 100 * 10 * 0.25 = $250 cap per leg
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [
            {
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.05",  # 0.05 * 2000 = $100 (under cap)
                "avgPrice": "2000",
                "positionIdx": 1,  # Long leg
                "unrealisedPnl": "0",
            },
            {
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.2",  # 0.2 * 2000 = $400 (exceeds $250)
                "avgPrice": "2000",
                "positionIdx": 2,  # Short leg
                "unrealisedPnl": "0",
            },
        ]}
    }
    return sample_neutral_bot


@pytest.fixture
def bot_with_hedge_both_emergency(sample_neutral_bot, mock_client):
    """Bot with hedge positions where BOTH legs exceed emergency threshold (1.5x cap)."""
    # 100 * 10 * 0.25 = $250 cap per leg
    # 1.5 * $250 = $375 emergency threshold
    # Both legs at $500 notional (exceeds emergency)
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [
            {
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.25",  # 0.25 * 2000 = $500 (exceeds $375)
                "avgPrice": "2000",
                "positionIdx": 1,  # Long leg
                "unrealisedPnl": "0",
            },
            {
                "symbol": "ETHUSDT",
                "side": "Sell",
                "size": "0.25",  # 0.25 * 2000 = $500 (exceeds $375)
                "avgPrice": "2000",
                "positionIdx": 2,  # Short leg
                "unrealisedPnl": "0",
            },
        ]}
    }
    return sample_neutral_bot


@pytest.fixture
def bot_with_one_way_position(sample_neutral_bot, mock_client):
    """Bot with one-way mode position (positionIdx=0)."""
    mock_client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{
            "symbol": "ETHUSDT",
            "side": "Buy",
            "size": "0.2",  # 0.2 * 2000 = $400
            "avgPrice": "2000",
            "positionIdx": 0,  # One-way mode
            "unrealisedPnl": "0",
        }]}
    }
    return sample_neutral_bot
