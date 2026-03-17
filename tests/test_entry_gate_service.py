from unittest.mock import Mock

import pytest

import config.strategy_config as cfg
from services.entry_gate_service import EntryGateService


class DummyIndicatorService:
    def __init__(self):
        self.compute_indicators = Mock(
            return_value={
                "rsi": 50.0,
                "ema_21": 100.0,
                "close": 100.0,
            }
        )
        self.calculate_bollinger_bands = Mock(
            return_value={"success": True, "bb_position": 50.0}
        )
        self.get_ohlcv = Mock(return_value=[])


def test_check_entry_blocks_long_near_resistance_when_sr_gate_enabled(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_MIN_STRENGTH", 5)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": None,
            "nearest_resistance": {
                "price": 100.4,
                "strength": 7,
                "distance_pct": 0.004,
            },
            "levels": [],
            "error": None,
        },
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        indicators={"rsi": 55.0, "ema_21": 100.0, "close": 100.0},
    )

    assert result["suitable"] is False
    assert "RESISTANCE_NEARBY" in result["blocked_by"]
    assert "Resistance 0.40% away" in result["reason"]


def test_check_entry_combines_momentum_and_structure_blocks(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_MIN_STRENGTH", 5)

    indicator_service = DummyIndicatorService()
    indicator_service.calculate_bollinger_bands.return_value = {
        "success": True,
        "bb_position": 99.0,
    }
    service = EntryGateService(indicator_service)
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": None,
            "nearest_resistance": {
                "price": 100.5,
                "strength": 8,
                "distance_pct": 0.005,
            },
            "levels": [],
            "error": None,
        },
    )

    result = service.check_entry(
        symbol="ETHUSDT",
        mode="long",
        indicators={"rsi": 82.0, "ema_21": 94.0, "close": 100.0},
    )

    assert result["suitable"] is False
    assert "RESISTANCE_NEARBY" in result["blocked_by"]
    assert result["scores"]["setup_quality"]["score"] < 60.0


def test_check_side_open_blocks_sell_near_support(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_MIN_STRENGTH", 5)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": {
                "price": 99.6,
                "strength": 6,
                "distance_pct": 0.004,
            },
            "nearest_resistance": None,
            "levels": [],
            "error": None,
        },
    )

    result = service.check_side_open(
        symbol="SOLUSDT",
        side="Sell",
        current_price=100.0,
    )

    assert result["suitable"] is False
    assert result["blocked_by"] == ["SUPPORT_NEARBY"]


def test_check_side_open_ignores_weak_or_far_levels(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_MIN_STRENGTH", 5)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": None,
            "nearest_resistance": {
                "price": 101.8,
                "strength": 4,
                "distance_pct": 0.018,
            },
            "levels": [],
            "error": None,
        },
    )

    result = service.check_side_open(
        symbol="XRPUSDT",
        side="Buy",
        current_price=100.0,
    )

    assert result["suitable"] is True
    assert result["blocked_by"] == []


def test_check_entry_keeps_structure_block_when_experimental_relax_disabled(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(
        cfg,
        "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_ENABLED",
        False,
    )

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": None,
            "nearest_resistance": {
                "price": 100.15,
                "strength": 10,
                "distance_pct": 0.0015,
            },
            "levels": [],
            "error": None,
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda *args, **kwargs: {
            "enabled": True,
            "score": 82.0,
            "entry_allowed": True,
            "band": "strong",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 5.1},
                "indicators": {
                    "price_vs_ema_pct": 0.004,
                    "bb_position": 52.0,
                },
            },
            "component_points": {
                "price_action": 3.2,
                "supportive_structure": 1.8,
                "volume": 1.3,
                "mtf": 0.9,
            },
        },
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        indicators={"rsi": 55.0, "ema_21": 100.0, "close": 100.0},
    )

    assert result["suitable"] is False
    assert "RESISTANCE_NEARBY" in result["blocked_by"]


def test_check_entry_relaxes_moderate_structure_block_for_strong_directional_continuation(
    monkeypatch,
):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(
        cfg,
        "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_ENABLED",
        True,
    )

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": None,
            "nearest_resistance": {
                "price": 100.25,
                "strength": 10,
                "distance_pct": 0.0025,
            },
            "levels": [],
            "error": None,
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda *args, **kwargs: {
            "enabled": True,
            "score": 82.0,
            "entry_allowed": True,
            "band": "strong",
            "components": {
                "price_action_context": {"direction": "bullish"},
                "mode_fit": {"score": 5.1},
                "indicators": {
                    "price_vs_ema_pct": 0.004,
                    "bb_position": 52.0,
                },
            },
            "component_points": {
                "price_action": 3.2,
                "supportive_structure": 1.8,
                "volume": 1.3,
                "mtf": 0.9,
            },
        },
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        indicators={"rsi": 55.0, "ema_21": 100.0, "close": 100.0},
    )

    assert result["suitable"] is True
    assert result["blocked_by"] == []
    assert "exp_directional_structure_relax_used" in result["experiment_tags"]
    assert (
        result["scores"]["structure_result"]["scores"]["experimental_structure_relaxation"]["applied"]
        is True
    )


def test_check_side_open_blocks_buy_on_strong_bearish_price_action(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_BLOCK_SCORE", 16.0)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "get_price_action_context",
        lambda symbol, current_price=None: {
            "direction": "bearish",
            "net_score": -22.0,
            "bullish_score": 0.0,
            "bearish_score": 22.0,
            "components": {
                "market_structure": {"score": -10.0},
                "liquidity_sweep": {"score": -8.0},
                "candle_pattern": {"score": -4.0},
            },
        },
    )
    monkeypatch.setattr(
        service,
        "evaluate_price_action_side",
        lambda symbol, side, current_price=None, context=None: {
            "blocked": True,
            "blocked_by": ["PRICE_ACTION_BEARISH"],
            "reason": "Price action bearish score 22.0 (components: market_structure, liquidity_sweep, candle_pattern)",
        },
    )

    result = service.check_side_open(
        symbol="DOGEUSDT",
        side="Buy",
        current_price=100.0,
    )

    assert result["suitable"] is False
    assert "PRICE_ACTION_BEARISH" in result["blocked_by"]
    assert "Price action bearish score 22.0" in result["reason"]


def test_get_setup_quality_rewards_good_confluence(monkeypatch):
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "score_price_action_mode",
        lambda symbol, mode, current_price=None, context=None: {
            "score": 10.0,
            "direction": "bullish",
        },
    )

    context = {
        "direction": "bullish",
        "net_score": 18.0,
        "bullish_score": 18.0,
        "bearish_score": 2.0,
        "components": {
            "volume_confirmation": {"score": 6.0},
            "mtf_alignment": {"score": 8.0},
            "candle_pattern": {"score": 6.0},
        },
    }
    quality = service.get_setup_quality(
        symbol="BTCUSDT",
        mode="long",
        current_price=100.0,
        indicators={
            "adx": 28.0,
            "atr_pct": 0.02,
            "bbw_pct": 0.03,
            "price_velocity": 0.008,
        },
        structure={
            "nearest_support": {
                "price": 99.3,
                "strength": 8,
                "distance_pct": 0.007,
            },
            "nearest_resistance": {
                "price": 103.0,
                "strength": 5,
                "distance_pct": 0.03,
            },
        },
        price_action_context=context,
        side_result={
            "supportive_score": 18.0,
            "adverse_score": 3.0,
        },
    )

    assert quality["enabled"] is True
    assert quality["score"] > 60.0
    assert quality["entry_allowed"] is True
    assert quality["band"] in {"good", "strong"}
    assert quality["component_points"]["supportive_structure"] > 0


def test_check_entry_blocks_when_setup_quality_is_too_low(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_MIN_ENTRY_SCORE", 52.0)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "check_side_open",
        lambda symbol, side, current_price=None, indicators=None: {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
            "scores": {
                "nearest_support": None,
                "nearest_resistance": None,
                "adverse_level": None,
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda **kwargs: {
            "enabled": True,
            "score": 41.0,
            "entry_allowed": False,
            "breakout_ready": False,
            "band": "poor",
            "summary": "adverse_structure=-9.0",
        },
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.0},
    )

    assert result["suitable"] is False
    assert "SETUP_QUALITY_LOW" in result["blocked_by"]
    assert "Setup quality 41.00 below 52.0" in result["reason"]


def test_setup_quality_disabled_preserves_legacy_behavior(monkeypatch):
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_MIN_STRENGTH", 5)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_structure_levels",
        lambda symbol, current_price=None: {
            "nearest_support": None,
            "nearest_resistance": {
                "price": 100.4,
                "strength": 7,
                "distance_pct": 0.004,
            },
            "levels": [],
            "error": None,
        },
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.0},
    )

    assert result["suitable"] is False
    assert result["blocked_by"] == ["RESISTANCE_NEARBY"]
    assert result["scores"]["setup_quality"]["enabled"] is False


def test_breakout_confirmed_entry_passes_with_closed_candles(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", True)

    service = EntryGateService(DummyIndicatorService())
    price_action_context = {
        "components": {
            "market_structure": {
                "details": {"last_swing_high": (12, 100.0)},
            },
            "volume_confirmation": {"score": 6.0},
            "mtf_alignment": {"score": 7.0},
        }
    }
    monkeypatch.setattr(
        service,
        "check_side_open",
        lambda symbol, side, current_price=None, indicators=None: {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
            "scores": {
                "nearest_support": None,
                "nearest_resistance": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "adverse_level": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "price_action": price_action_context,
                "price_action_side": {
                    "supportive_score": 18.0,
                    "adverse_score": 0.0,
                },
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda **kwargs: {
            "enabled": True,
            "score": 71.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "good",
            "summary": "mode_fit=+8.0",
        },
    )
    monkeypatch.setattr(
        service,
        "_get_closed_candles",
        lambda symbol, interval, limit: [
            {"close": 100.3},
            {"close": 100.35},
        ],
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        bot={"breakout_confirmed_entry": True},
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.3},
    )

    assert result["suitable"] is True
    assert result["scores"]["breakout_confirmation"]["confirmed"] is True


def test_breakout_confirmed_entry_blocks_unconfirmed_breakout(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", False)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", False)

    service = EntryGateService(DummyIndicatorService())
    price_action_context = {
        "components": {
            "market_structure": {
                "details": {"last_swing_high": (12, 100.0)},
            },
            "volume_confirmation": {"score": 6.0},
            "mtf_alignment": {"score": 7.0},
        }
    }
    monkeypatch.setattr(
        service,
        "check_side_open",
        lambda symbol, side, current_price=None, indicators=None: {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
            "scores": {
                "nearest_support": None,
                "nearest_resistance": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "adverse_level": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "price_action": price_action_context,
                "price_action_side": {
                    "supportive_score": 18.0,
                    "adverse_score": 0.0,
                },
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda **kwargs: {
            "enabled": True,
            "score": 71.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "good",
            "summary": "mode_fit=+8.0",
        },
    )
    monkeypatch.setattr(
        service,
        "_get_closed_candles",
        lambda symbol, interval, limit: [
            {"close": 99.9},
            {"close": 100.0},
        ],
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        bot={"breakout_confirmed_entry": True},
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.1},
    )

    assert result["suitable"] is False
    assert "BREAKOUT_NOT_CONFIRMED" in result["blocked_by"]


def test_breakout_no_chase_blocks_extended_confirmed_breakout(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", False)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", False)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_FILTER_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_PCT", 0.002)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_ATR_MULT", 0.8)

    service = EntryGateService(DummyIndicatorService())
    price_action_context = {
        "components": {
            "market_structure": {
                "details": {"last_swing_high": (12, 100.0)},
            },
            "volume_confirmation": {"score": 6.0},
            "mtf_alignment": {"score": 7.0},
        }
    }
    monkeypatch.setattr(
        service,
        "check_side_open",
        lambda symbol, side, current_price=None, indicators=None: {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
            "scores": {
                "nearest_support": None,
                "nearest_resistance": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "adverse_level": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "price_action": price_action_context,
                "price_action_side": {
                    "supportive_score": 18.0,
                    "adverse_score": 0.0,
                },
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda **kwargs: {
            "enabled": True,
            "score": 71.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "good",
            "summary": "mode_fit=+8.0",
            "components": {
                "indicators": {
                    "atr_pct": 0.003,
                }
            },
        },
    )
    monkeypatch.setattr(
        service,
        "_get_closed_candles",
        lambda symbol, interval, limit: [
            {"close": 100.3},
            {"close": 100.35},
        ],
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        bot={"breakout_confirmed_entry": True},
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.65},
    )

    assert result["suitable"] is False
    assert "BREAKOUT_CHASE_TOO_FAR" in result["blocked_by"]
    breakout = result["scores"]["breakout_confirmation"]
    assert breakout["no_chase_filtered"] is True
    assert breakout["no_chase_extension_pct"] == pytest.approx(0.005495, abs=1e-5)


def test_breakout_no_chase_allows_reasonable_extension(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", False)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", False)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_FILTER_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_PCT", 0.01)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_ATR_MULT", 2.0)

    service = EntryGateService(DummyIndicatorService())
    price_action_context = {
        "components": {
            "market_structure": {
                "details": {"last_swing_high": (12, 100.0)},
            },
            "volume_confirmation": {"score": 6.0},
            "mtf_alignment": {"score": 7.0},
        }
    }
    monkeypatch.setattr(
        service,
        "check_side_open",
        lambda symbol, side, current_price=None, indicators=None: {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
            "scores": {
                "nearest_support": None,
                "nearest_resistance": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "adverse_level": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "price_action": price_action_context,
                "price_action_side": {
                    "supportive_score": 18.0,
                    "adverse_score": 0.0,
                },
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda **kwargs: {
            "enabled": True,
            "score": 71.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "good",
            "summary": "mode_fit=+8.0",
            "components": {
                "indicators": {
                    "atr_pct": 0.01,
                }
            },
        },
    )
    monkeypatch.setattr(
        service,
        "_get_closed_candles",
        lambda symbol, interval, limit: [
            {"close": 100.3},
            {"close": 100.35},
        ],
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        bot={"breakout_confirmed_entry": True},
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.2},
    )

    assert result["suitable"] is True
    assert result["scores"]["breakout_confirmation"]["no_chase_filtered"] is False


def test_breakout_no_chase_disabled_preserves_legacy_breakout_entry(monkeypatch):
    monkeypatch.setattr(cfg, "ENTRY_GATE_ENABLED", True)
    monkeypatch.setattr(cfg, "ENTRY_GATE_SR_ENABLED", False)
    monkeypatch.setattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
    monkeypatch.setattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", False)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", False)
    monkeypatch.setattr(cfg, "BREAKOUT_NO_CHASE_FILTER_ENABLED", False)

    service = EntryGateService(DummyIndicatorService())
    price_action_context = {
        "components": {
            "market_structure": {
                "details": {"last_swing_high": (12, 100.0)},
            },
            "volume_confirmation": {"score": 6.0},
            "mtf_alignment": {"score": 7.0},
        }
    }
    monkeypatch.setattr(
        service,
        "check_side_open",
        lambda symbol, side, current_price=None, indicators=None: {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
            "scores": {
                "nearest_support": None,
                "nearest_resistance": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "adverse_level": {
                    "price": 100.0,
                    "strength": 8,
                    "distance_pct": 0.005,
                },
                "price_action": price_action_context,
                "price_action_side": {
                    "supportive_score": 18.0,
                    "adverse_score": 0.0,
                },
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_setup_quality",
        lambda **kwargs: {
            "enabled": True,
            "score": 71.0,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "good",
            "summary": "mode_fit=+8.0",
            "components": {
                "indicators": {
                    "atr_pct": 0.003,
                }
            },
        },
    )
    monkeypatch.setattr(
        service,
        "_get_closed_candles",
        lambda symbol, interval, limit: [
            {"close": 100.3},
            {"close": 100.35},
        ],
    )

    result = service.check_entry(
        symbol="BTCUSDT",
        mode="long",
        bot={"breakout_confirmed_entry": True},
        indicators={"rsi": 50.0, "ema_21": 100.0, "close": 100.65},
    )

    assert result["suitable"] is True
    assert "BREAKOUT_CHASE_TOO_FAR" not in result["blocked_by"]


def test_breakout_confirmation_respects_volume_and_mtf_requirements(monkeypatch):
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", True)

    service = EntryGateService(DummyIndicatorService())
    monkeypatch.setattr(
        service,
        "_get_closed_candles",
        lambda symbol, interval, limit: [
            {"close": 100.3},
            {"close": 100.35},
        ],
    )

    result = service.check_breakout_confirmation(
        symbol="BTCUSDT",
        mode="long",
        current_price=100.3,
        structure={
            "nearest_resistance": {"price": 100.0, "strength": 8},
        },
        price_action_context={
            "components": {
                "market_structure": {
                    "details": {"last_swing_high": (12, 100.0)},
                },
                "volume_confirmation": {"score": 0.0},
                "mtf_alignment": {"score": 0.0},
            }
        },
        setup_quality={
            "enabled": True,
            "score": 70.0,
            "breakout_ready": True,
        },
    )

    assert result["confirmed"] is False
    assert "volume" in result["reason"].lower() or "mtf" in result["reason"].lower()


def test_breakout_confirmation_directional_only_skips_neutral(monkeypatch):
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", True)
    monkeypatch.setattr(cfg, "BREAKOUT_CONFIRM_DIRECTIONAL_ONLY", True)

    service = EntryGateService(DummyIndicatorService())
    result = service.check_breakout_confirmation(
        symbol="BTCUSDT",
        mode="neutral",
    )

    assert result["required"] is False
