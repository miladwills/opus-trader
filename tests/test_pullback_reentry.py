"""Tests for Pullback Re-Entry Watch (Smart Feature #35)."""

import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import config.strategy_config as strategy_cfg
from services.grid_bot_service import GridBotService


def _make_service():
    service = GridBotService.__new__(GridBotService)
    service.mean_reversion_service = Mock()
    service.mean_reversion_service.analyze_mean_reversion.return_value = {
        "success": True,
        "extension_level": "moderate",
        "avg_deviation_pct": 1.2,
    }
    service.bot_storage = SimpleNamespace(save_bot=lambda bot: dict(bot))
    service._save_runtime_bot = lambda bot: dict(bot)
    return service


def _base_bot(**overrides):
    bot = {
        "id": "bot-1",
        "symbol": "SUIUSDT",
        "mode": "long",
        "status": "running",
        "_htf_adx_1h": 35.0,
        "regime_effective": "UP",
        "_pullback_watch_active": False,
        "_pullback_watch_reentry_count": 0,
    }
    bot.update(overrides)
    return bot


# =========================================================================
# Activation tests
# =========================================================================

def test_activate_pullback_watch_on_strong_trend():
    service = _make_service()
    bot = _base_bot()
    result = service._maybe_activate_pullback_watch(bot, "momentum_exhaustion_exit", 1.05)
    assert result is True
    assert bot["_pullback_watch_active"] is True
    assert bot["_pullback_watch_direction"] == "long"
    assert bot["_pullback_watch_exit_price"] == 1.05
    assert bot["_pullback_watch_exit_reason"] == "momentum_exhaustion_exit"


def test_activate_rejects_neutral_mode():
    service = _make_service()
    bot = _base_bot(mode="neutral")
    result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False
    assert bot.get("_pullback_watch_active") is False


def test_activate_rejects_low_adx():
    service = _make_service()
    bot = _base_bot(_htf_adx_1h=15.0)
    result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False


def test_activate_rejects_wrong_regime():
    service = _make_service()
    bot = _base_bot(regime_effective="DOWN")
    result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False


def test_activate_rejects_already_active():
    service = _make_service()
    bot = _base_bot(_pullback_watch_active=True)
    result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False


def test_activate_rejects_max_reentry_count():
    service = _make_service()
    bot = _base_bot(_pullback_watch_reentry_count=3)
    result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False


def test_activate_rejects_during_cancel_cooldown():
    service = _make_service()
    bot = _base_bot(_pullback_watch_last_cancel_at=time.time())
    result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False


def test_activate_disabled_config():
    service = _make_service()
    bot = _base_bot()
    with patch.object(strategy_cfg, "PULLBACK_REENTRY_ENABLED", False):
        result = service._maybe_activate_pullback_watch(bot, "test", 1.0)
    assert result is False


# =========================================================================
# Cancel tests
# =========================================================================

def test_cancel_on_time_expired():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_activated_at=time.time() - 3600,
    )
    reason = service._check_pullback_watch_cancel(bot, "SUIUSDT", 1.0)
    assert reason == "time_expired"


def test_cancel_on_adx_collapse():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_activated_at=time.time(),
        _htf_adx_1h=15.0,
    )
    reason = service._check_pullback_watch_cancel(bot, "SUIUSDT", 1.0)
    assert reason == "adx_collapsed"


def test_cancel_on_regime_flip():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_activated_at=time.time(),
        regime_effective="DOWN",
    )
    reason = service._check_pullback_watch_cancel(bot, "SUIUSDT", 1.0)
    assert reason == "regime_flipped"


def test_cancel_on_pullback_too_deep():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_activated_at=time.time(),
        _pullback_watch_exit_price=1.10,
    )
    # Price dropped 5% from exit = too deep (max 3%)
    reason = service._check_pullback_watch_cancel(bot, "SUIUSDT", 1.045)
    assert reason == "pullback_too_deep"


def test_cancel_on_mode_changed():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_activated_at=time.time(),
        _pullback_watch_exit_price=1.05,
        mode="short",
    )
    reason = service._check_pullback_watch_cancel(bot, "SUIUSDT", 1.04)
    assert reason == "mode_changed"


def test_no_cancel_when_conditions_ok():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_activated_at=time.time(),
        _pullback_watch_exit_price=1.05,
    )
    reason = service._check_pullback_watch_cancel(bot, "SUIUSDT", 1.04)
    assert reason is None


# =========================================================================
# Trigger tests
# =========================================================================

def test_trigger_requires_min_pullback():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_direction="long",
        _pullback_watch_pullback_depth_pct=0.2,  # below 0.5% min
    )
    assert service._pullback_reentry_triggered(bot, 1.04, {}) is False


def test_trigger_requires_rsi_in_zone():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_direction="long",
        _pullback_watch_pullback_depth_pct=1.0,
        direction_score=5,
        candle_pattern="hammer",
    )
    # RSI 65 is above the 50 threshold for longs
    assert service._pullback_reentry_triggered(bot, 1.04, {"rsi": 65}) is False


def test_trigger_requires_direction_score():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_direction="long",
        _pullback_watch_pullback_depth_pct=1.0,
        direction_score=-10,
        candle_pattern="hammer",
    )
    assert service._pullback_reentry_triggered(bot, 1.04, {"rsi": 40}) is False


def test_trigger_requires_confirmation():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_direction="long",
        _pullback_watch_pullback_depth_pct=1.0,
        direction_score=5,
        candle_pattern="doji",  # Not a confirmation pattern
        macd_cross="none",
    )
    assert service._pullback_reentry_triggered(bot, 1.04, {"rsi": 40}) is False


def test_trigger_succeeds_with_all_conditions():
    service = _make_service()
    service.mean_reversion_service.analyze_mean_reversion.return_value = {
        "success": True,
        "extension_level": "weak",
    }
    bot = _base_bot(
        _pullback_watch_direction="long",
        _pullback_watch_pullback_depth_pct=1.5,
        direction_score=10,
        candle_pattern="hammer",
    )
    assert service._pullback_reentry_triggered(bot, 1.04, {"rsi": 40}) is True


def test_trigger_with_macd_confirmation():
    service = _make_service()
    service.mean_reversion_service.analyze_mean_reversion.return_value = {
        "success": True,
        "extension_level": "normal",
    }
    bot = _base_bot(
        _pullback_watch_direction="long",
        _pullback_watch_pullback_depth_pct=1.0,
        direction_score=5,
        candle_pattern="doji",
        macd_cross="bullish",
    )
    assert service._pullback_reentry_triggered(bot, 1.04, {"rsi": 45}) is True


# =========================================================================
# Evaluate (full cycle) tests
# =========================================================================

def test_evaluate_inactive_returns_quickly():
    service = _make_service()
    bot = _base_bot(_pullback_watch_active=False)
    result = service._evaluate_pullback_watch(bot, "SUIUSDT", "long", 1.04, {})
    assert result["active"] is False
    assert result["triggered"] is False


def test_evaluate_cancels_and_clears_state():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_activated_at=time.time() - 3600,
        _pullback_watch_exit_price=1.05,
    )
    result = service._evaluate_pullback_watch(bot, "SUIUSDT", "long", 1.04, {})
    assert result["active"] is False
    assert result["cancel_reason"] == "time_expired"
    assert bot["_pullback_watch_active"] is False


def test_evaluate_tracks_pullback_depth():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_activated_at=time.time(),
        _pullback_watch_exit_price=1.05,
        _pullback_watch_pullback_depth_pct=0.0,
    )
    result = service._evaluate_pullback_watch(bot, "SUIUSDT", "long", 1.04, {})
    assert result["active"] is True
    depth = bot["_pullback_watch_pullback_depth_pct"]
    assert depth > 0.9  # ~0.95% pullback


# =========================================================================
# State cleanup tests
# =========================================================================

def test_clear_state_preserves_reentry_count():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
        _pullback_watch_reentry_count=2,
    )
    service._clear_pullback_watch_state(bot, "test_cancel")
    assert bot["_pullback_watch_active"] is False
    assert bot["_pullback_watch_reentry_count"] == 2
    assert bot["_pullback_watch_cancel_reason"] == "test_cancel"


def test_clear_state_without_cancel_reason():
    service = _make_service()
    bot = _base_bot(
        _pullback_watch_active=True,
        _pullback_watch_direction="long",
    )
    service._clear_pullback_watch_state(bot)
    assert bot["_pullback_watch_active"] is False
    assert "_pullback_watch_direction" not in bot


# =========================================================================
# Entry gate bypass tests
# =========================================================================

def test_short_mode_trigger_checks_rsi_correctly():
    service = _make_service()
    service.mean_reversion_service.analyze_mean_reversion.return_value = {
        "success": True,
        "extension_level": "weak",
    }
    bot = _base_bot(
        mode="short",
        _pullback_watch_direction="short",
        _pullback_watch_pullback_depth_pct=1.5,
        regime_effective="DOWN",
        direction_score=-10,
        candle_pattern="shooting_star",
    )
    # RSI 55 is above short threshold (>= 50) — should trigger
    assert service._pullback_reentry_triggered(bot, 1.06, {"rsi": 55}) is True
    # RSI 40 is below short threshold — should NOT trigger
    assert service._pullback_reentry_triggered(bot, 1.06, {"rsi": 40}) is False
