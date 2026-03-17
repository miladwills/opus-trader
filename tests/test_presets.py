"""
Tests for MAJOR/MEME Preset System.

Verifies that presets correctly apply different thresholds to all loss-prevention checks.
"""

import pytest
from unittest.mock import Mock, patch
import config.strategy_config as cfg


class TestPresetAutoDetection:
    """Tests for preset auto-detection based on symbol."""

    def test_major_symbol_gets_major_preset(self, nlp_service):
        """BTCUSDT/ETHUSDT should auto-detect as MAJOR."""
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
            bot = {"symbol": symbol}
            preset = nlp_service.get_preset_for_symbol(symbol)
            assert preset == "MAJOR", f"{symbol} should be MAJOR"

    def test_meme_symbol_gets_meme_preset(self, nlp_service):
        """DOGEUSDT/SHIBUSDT should auto-detect as MEME."""
        for symbol in ["DOGEUSDT", "SHIBUSDT", "WIFUSDT", "PEPEUSDT", "BONKUSDT"]:
            bot = {"symbol": symbol}
            preset = nlp_service.get_preset_for_symbol(symbol)
            assert preset == "MEME", f"{symbol} should be MEME"

    def test_unknown_symbol_defaults_to_meme(self, nlp_service):
        """Unknown symbols should default to MEME (safer)."""
        preset = nlp_service.get_preset_for_symbol("UNKNOWNUSDT")
        assert preset == "MEME"

    def test_bot_preset_override(self, nlp_service, sample_neutral_bot):
        """Bot can explicitly override preset."""
        # ETHUSDT normally is MAJOR
        sample_neutral_bot["neutral_preset"] = "MEME"
        config = nlp_service.get_effective_config(sample_neutral_bot)
        # Should use MEME values
        assert config["max_loss_pct"] == cfg.NEUTRAL_PRESETS["MEME"]["max_loss_pct"]


class TestPresetThresholdDifferences:
    """Tests that MAJOR and MEME presets have different thresholds."""

    def test_meme_has_stricter_inventory_cap(self):
        """MEME should have lower inventory cap than MAJOR."""
        major_cap = cfg.NEUTRAL_PRESETS["MAJOR"]["inventory_cap_pct"]
        meme_cap = cfg.NEUTRAL_PRESETS["MEME"]["inventory_cap_pct"]
        assert meme_cap < major_cap, "MEME should have stricter inventory cap"
        assert major_cap == 0.30
        assert meme_cap == 0.20

    def test_meme_has_stricter_max_loss(self):
        """MEME should have lower max loss threshold than MAJOR."""
        major_loss = cfg.NEUTRAL_PRESETS["MAJOR"]["max_loss_pct"]
        meme_loss = cfg.NEUTRAL_PRESETS["MEME"]["max_loss_pct"]
        assert meme_loss < major_loss, "MEME should have stricter max loss"
        assert major_loss == 0.05
        assert meme_loss == 0.03

    def test_meme_has_stricter_momentum_filter(self):
        """MEME should have tighter RSI bounds than MAJOR."""
        major = cfg.NEUTRAL_PRESETS["MAJOR"]
        meme = cfg.NEUTRAL_PRESETS["MEME"]

        # MEME should have narrower RSI range
        major_range = major["momentum_rsi_upper"] - major["momentum_rsi_lower"]
        meme_range = meme["momentum_rsi_upper"] - meme["momentum_rsi_lower"]
        assert meme_range < major_range, "MEME should have narrower RSI range"

    def test_meme_has_faster_breakout_reaction(self):
        """MEME should have faster breakout detection than MAJOR."""
        major = cfg.NEUTRAL_PRESETS["MAJOR"]
        meme = cfg.NEUTRAL_PRESETS["MEME"]

        assert meme["breakout_hold_seconds"] < major["breakout_hold_seconds"]
        assert meme["breakout_threshold_pct"] <= major["breakout_threshold_pct"]


class TestPresetAffectsInventoryCap:
    """Tests that presets affect inventory cap calculations."""

    def test_major_preset_uses_30_percent_cap(self, nlp_service, sample_neutral_bot, mock_client):
        """MAJOR preset should use 30% inventory cap."""
        # ETHUSDT = MAJOR, 100 * 10 * 0.30 = $300 cap
        # Set position at $350 (exceeds $300 but would be under 25%)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.175",  # 0.175 * 2000 = $350 > $300
                "avgPrice": "2000",
                "positionIdx": 1,
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["exceeded"] is True
        assert result["cap_notional"] == 300.0  # 30% of $1000

    def test_meme_preset_uses_20_percent_cap(self, nlp_service, mock_client):
        """MEME preset should use 20% inventory cap."""
        # DOGEUSDT = MEME, 100 * 10 * 0.20 = $200 cap
        meme_bot = {
            "id": "test-meme-bot",
            "symbol": "DOGEUSDT",
            "mode": "neutral_classic_bybit",
            "status": "running",
            "investment": 100.0,
            "investment_usdt": 100.0,
            "leverage": 10.0,
            "_nlp_state": {},
        }

        # Set position at $250 (exceeds 20% but would be under 30%)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "DOGEUSDT",
                "side": "Buy",
                "size": "1000",  # Assume DOGE at $0.25 = $250 > $200
                "avgPrice": "0.25",
                "positionIdx": 1,
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=meme_bot,
            symbol="DOGEUSDT",
        )
        assert result["exceeded"] is True
        assert result["cap_notional"] == 200.0  # 20% of $1000


class TestPresetAffectsMaxLoss:
    """Tests that presets affect max loss calculations."""

    def test_major_preset_uses_5_percent_loss(self, nlp_service, sample_neutral_bot, mock_client):
        """MAJOR preset should use 5% max loss threshold."""
        # ETHUSDT = MAJOR, $100 * 5% = $5 threshold
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.1",
                "avgPrice": "2000",
                "positionIdx": 1,
                "unrealisedPnl": "-4.0",  # Below 5% threshold
            }]}
        }

        result = nlp_service.check_max_loss(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["triggered"] is False
        assert result["threshold"] == -5.0  # 5% of $100

    def test_meme_preset_uses_3_percent_loss(self, nlp_service, mock_client):
        """MEME preset should use 3% max loss threshold."""
        # DOGEUSDT = MEME, $100 * 3% = $3 threshold
        meme_bot = {
            "id": "test-meme-bot",
            "symbol": "DOGEUSDT",
            "mode": "neutral_classic_bybit",
            "status": "running",
            "investment": 100.0,
            "investment_usdt": 100.0,
            "leverage": 10.0,
            "_nlp_state": {},
        }

        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "DOGEUSDT",
                "side": "Buy",
                "size": "1000",
                "avgPrice": "0.25",
                "positionIdx": 1,
                "unrealisedPnl": "-4.0",  # Exceeds 3% ($3) threshold
            }]}
        }

        result = nlp_service.check_max_loss(
            bot=meme_bot,
            symbol="DOGEUSDT",
        )
        assert result["triggered"] is True
        assert result["threshold"] == -3.0  # 3% of $100


class TestPresetAffectsMomentumFilter:
    """Tests that presets affect momentum filter thresholds."""

    def test_major_preset_allows_higher_adx(self, nlp_service, sample_neutral_bot, mock_indicator_service):
        """MAJOR preset should allow ADX up to 28."""
        # ETHUSDT = MAJOR, ADX threshold = 28
        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 26.0,  # Under 28 (MAJOR), would be blocked by 25 (global)
            "close": 2000.0,
            "bb_upper": 2050.0,
            "bb_lower": 1950.0,
        }

        result = nlp_service.check_momentum_filter(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
        )
        assert result["blocked"] is False

    def test_meme_preset_blocks_lower_adx(self, nlp_service, mock_indicator_service):
        """MEME preset should block ADX above 22."""
        # DOGEUSDT = MEME, ADX threshold = 22
        meme_bot = {
            "id": "test-meme-bot",
            "symbol": "DOGEUSDT",
            "mode": "neutral_classic_bybit",
            "status": "running",
            "investment": 100.0,
            "_nlp_state": {},
        }

        mock_indicator_service.compute_indicators.return_value = {
            "rsi": 50.0,
            "adx": 24.0,  # Under 28 (MAJOR) but over 22 (MEME)
            "close": 0.25,
            "bb_upper": 0.26,
            "bb_lower": 0.24,
        }

        result = nlp_service.check_momentum_filter(
            bot=meme_bot,
            symbol="DOGEUSDT",
        )
        assert result["blocked"] is True
        assert "ADX" in result["reason"]


class TestPresetAffectsRecenter:
    """Tests that presets affect recenter thresholds."""

    def test_major_preset_uses_1_percent_deviation(self, nlp_service, sample_neutral_bot):
        """MAJOR preset should use 1% deviation threshold."""
        # ETHUSDT = MAJOR, deviation threshold = 1%
        # Grid: 1900-2100, mid = 2000
        # 0.8% deviation = 16 points, shouldn't trigger
        result = nlp_service.check_recenter_needed(
            bot=sample_neutral_bot,
            symbol="ETHUSDT",
            mark_price=2016.0,  # 0.8% deviation
        )
        assert result["needed"] is False

    def test_meme_preset_uses_half_percent_deviation(self, nlp_service):
        """MEME preset should use 0.5% deviation threshold."""
        # DOGEUSDT = MEME, deviation threshold = 0.5%
        meme_bot = {
            "id": "test-meme-bot",
            "symbol": "DOGEUSDT",
            "mode": "neutral_classic_bybit",
            "status": "running",
            "investment": 100.0,
            "lower_price": 0.19,
            "upper_price": 0.21,  # mid = 0.20
            "_nlp_state": {},
        }

        # 0.8% deviation = 0.0016, should trigger for MEME (0.5%)
        result = nlp_service.check_recenter_needed(
            bot=meme_bot,
            symbol="DOGEUSDT",
            mark_price=0.2016,  # 0.8% deviation from 0.20 mid
        )
        assert result["needed"] is True
        assert result["reason"] == "mid_deviation"


class TestGateUsesPresets:
    """Tests that the suitability gate uses preset thresholds."""

    def test_gate_returns_preset_thresholds(self, gate_service, mock_indicator_service):
        """Gate should return preset-specific thresholds."""
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 20.0,
            "rsi": 50.0,
            "atr_pct": 0.02,
        }

        # ETHUSDT = MAJOR
        result_major = gate_service.check_suitability("ETHUSDT")
        assert result_major["preset"] == "MAJOR"
        # MAJOR uses momentum_adx_threshold=28 as gate threshold
        assert result_major["thresholds"]["adx_15m_max"] == 28

        # DOGEUSDT = MEME
        result_meme = gate_service.check_suitability("DOGEUSDT")
        assert result_meme["preset"] == "MEME"
        # MEME uses momentum_adx_threshold=22 as gate threshold
        assert result_meme["thresholds"]["adx_15m_max"] == 22

    def test_gate_uses_preset_rsi_thresholds(self, gate_service, mock_indicator_service):
        """Gate should use preset RSI thresholds."""
        # RSI 66 - would pass MAJOR (68) but fail MEME (62)
        mock_indicator_service.compute_indicators.return_value = {
            "adx": 18.0,
            "rsi": 66.0,
            "atr_pct": 0.02,
        }

        result_major = gate_service.check_suitability("ETHUSDT")
        assert result_major["suitable"] is True  # RSI 66 < 68

        result_meme = gate_service.check_suitability("DOGEUSDT")
        assert result_meme["suitable"] is False  # RSI 66 > 62
        assert "RSI" in result_meme["reason"]


class TestPresetConfigValues:
    """Tests that preset config returns correct values."""

    def test_get_effective_config_major(self, nlp_service, sample_neutral_bot):
        """Effective config should use MAJOR preset values for ETHUSDT."""
        config = nlp_service.get_effective_config(sample_neutral_bot)

        # Verify MAJOR preset values
        assert config["breakout_threshold_pct"] == 0.003
        assert config["breakout_hold_seconds"] == 60
        assert config["inventory_cap_pct"] == 0.30
        assert config["max_loss_pct"] == 0.05
        assert config["momentum_adx_threshold"] == 28
        assert config["momentum_rsi_upper"] == 68
        assert config["momentum_rsi_lower"] == 32
        assert config["recenter_mid_deviation_pct"] == 0.01

    def test_get_effective_config_meme(self, nlp_service):
        """Effective config should use MEME preset values for DOGEUSDT."""
        meme_bot = {
            "id": "test-meme-bot",
            "symbol": "DOGEUSDT",
            "mode": "neutral_classic_bybit",
            "_nlp_state": {},
        }

        config = nlp_service.get_effective_config(meme_bot)

        # Verify MEME preset values
        assert config["breakout_threshold_pct"] == 0.002
        assert config["breakout_hold_seconds"] == 30
        assert config["inventory_cap_pct"] == 0.20
        assert config["max_loss_pct"] == 0.03
        assert config["momentum_adx_threshold"] == 22
        assert config["momentum_rsi_upper"] == 62
        assert config["momentum_rsi_lower"] == 38
        assert config["recenter_mid_deviation_pct"] == 0.005


class TestPresetEmergencyThresholds:
    """Tests that preset emergency multipliers work correctly."""

    def test_major_emergency_at_1_5x(self, nlp_service, sample_neutral_bot, mock_client):
        """MAJOR preset should trigger emergency at 1.5x cap."""
        # ETHUSDT = MAJOR, cap = $300, emergency at 1.5x = $450
        # Position at $475 should trigger emergency
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "ETHUSDT",
                "side": "Buy",
                "size": "0.2375",  # 0.2375 * 2000 = $475 > $450
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

    def test_meme_emergency_at_1_3x(self, nlp_service, mock_client):
        """MEME preset should trigger emergency at 1.3x cap (earlier)."""
        # DOGEUSDT = MEME, cap = $200, emergency at 1.3x = $260
        meme_bot = {
            "id": "test-meme-bot",
            "symbol": "DOGEUSDT",
            "mode": "neutral_classic_bybit",
            "status": "running",
            "investment": 100.0,
            "investment_usdt": 100.0,
            "leverage": 10.0,
            "_nlp_state": {},
        }

        # Position at $275 - would NOT be emergency for MAJOR (1.5x=$450)
        # but IS emergency for MEME (1.3x=$260)
        mock_client.get_positions.return_value = {
            "success": True,
            "data": {"list": [{
                "symbol": "DOGEUSDT",
                "side": "Buy",
                "size": "1100",  # 1100 * $0.25 = $275 > $260
                "avgPrice": "0.25",
                "positionIdx": 1,
            }]}
        }

        result = nlp_service.check_inventory_cap(
            bot=meme_bot,
            symbol="DOGEUSDT",
        )
        assert result["exceeded"] is True
        assert result["action"] == "emergency_reduce"
