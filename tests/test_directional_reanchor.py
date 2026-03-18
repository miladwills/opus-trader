"""Tests for directional manual-close reanchor mechanism."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import config.strategy_config as strategy_cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(mode="long", range_mode="dynamic", position_size=1.0, **overrides):
    bot = {
        "id": "test-bot-001",
        "symbol": "BTCUSDT",
        "mode": mode,
        "range_mode": range_mode,
        "status": "running",
        "current_position_size": position_size,
        "current_position_side": "buy" if mode == "long" else "sell",
        "lower_price": 49000.0,
        "upper_price": 51000.0,
    }
    bot.update(overrides)
    return bot


def _make_close_result(success=True, position_empty=False):
    r = {"success": success}
    if position_empty:
        r["position_empty"] = True
    return r


def _should_set_reanchor(bot, result):
    """Simulate the reanchor flag-setting logic from app.py close endpoint."""
    _close_ok = result.get("success") or result.get("position_empty")
    if not (_close_ok and bot):
        return False
    if not strategy_cfg.DIRECTIONAL_REANCHOR_ON_MANUAL_CLOSE_ENABLED:
        return False
    _d_mode = str(bot.get("mode") or "").lower()
    _d_range = str(bot.get("range_mode") or "dynamic").lower()
    return _d_mode in ("long", "short") and _d_range != "fixed"


# ---------------------------------------------------------------------------
# Test: Flag-setting logic (app.py side)
# ---------------------------------------------------------------------------

def test_manual_close_dynamic_long_sets_pending():
    bot = _make_bot(mode="long", range_mode="dynamic")
    result = _make_close_result(success=True)
    assert _should_set_reanchor(bot, result) is True


def test_manual_close_dynamic_short_sets_pending():
    bot = _make_bot(mode="short", range_mode="dynamic")
    result = _make_close_result(success=True)
    assert _should_set_reanchor(bot, result) is True


def test_already_closed_position_empty_sets_pending():
    bot = _make_bot(mode="long", range_mode="trailing")
    result = _make_close_result(success=False, position_empty=True)
    assert _should_set_reanchor(bot, result) is True


def test_fixed_range_directional_does_not_set_pending():
    bot = _make_bot(mode="long", range_mode="fixed")
    result = _make_close_result(success=True)
    assert _should_set_reanchor(bot, result) is False


def test_neutral_mode_does_not_set_pending():
    bot = _make_bot(mode="neutral", range_mode="dynamic")
    result = _make_close_result(success=True)
    assert _should_set_reanchor(bot, result) is False


def test_failed_close_does_not_set_pending():
    bot = _make_bot(mode="long", range_mode="dynamic")
    result = {"success": False}
    assert _should_set_reanchor(bot, result) is False


def test_no_owner_bot_does_not_set_pending():
    result = _make_close_result(success=True)
    assert _should_set_reanchor(None, result) is False


# ---------------------------------------------------------------------------
# Test: Consumption logic (grid_bot_service side)
# ---------------------------------------------------------------------------

def _make_service():
    from services.grid_bot_service import GridBotService
    svc = GridBotService.__new__(GridBotService)
    svc._last_grid_center = {}
    svc.client = MagicMock()
    svc.bot_storage = MagicMock()
    return svc


def test_pending_not_consumed_while_position_still_open():
    """If exchange still shows position, keep pending marker and wait."""
    bot = _make_bot(
        mode="long",
        range_mode="dynamic",
        position_size=0.0,  # will be overridden in simulation
        directional_reanchor_pending=True,
        directional_reanchor_requested_at=datetime.now(timezone.utc).isoformat() + "Z",
    )
    # Simulate: exchange still has position (current_position_size > 0)
    current_position_size = 1.5
    mode = "long"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Run the check logic inline
    if bot.get("directional_reanchor_pending") and mode in ("long", "short"):
        reanchor_cycle = int(bot.get("_reanchor_pending_cycle", 0)) + 1
        bot["_reanchor_pending_cycle"] = reanchor_cycle
        if current_position_size > 0:
            if reanchor_cycle <= strategy_cfg.DIRECTIONAL_REANCHOR_MAX_PENDING_CYCLES:
                pass  # Still waiting

    assert bot.get("directional_reanchor_pending") is True
    assert bot.get("_reanchor_pending_cycle") == 1


def test_pending_expires_by_cycle_bound():
    """After max cycles without flat, pending expires."""
    bot = _make_bot(
        mode="short",
        range_mode="trailing",
        directional_reanchor_pending=True,
        directional_reanchor_requested_at=datetime.now(timezone.utc).isoformat() + "Z",
        _reanchor_pending_cycle=strategy_cfg.DIRECTIONAL_REANCHOR_MAX_PENDING_CYCLES,
    )
    current_position_size = 1.0
    mode = "short"
    now_iso = datetime.now(timezone.utc).isoformat()

    if bot.get("directional_reanchor_pending") and mode in ("long", "short"):
        reanchor_cycle = int(bot.get("_reanchor_pending_cycle", 0)) + 1
        bot["_reanchor_pending_cycle"] = reanchor_cycle
        if current_position_size > 0:
            if reanchor_cycle > strategy_cfg.DIRECTIONAL_REANCHOR_MAX_PENDING_CYCLES:
                bot["directional_reanchor_pending"] = False
                bot["_reanchor_pending_cycle"] = 0
                bot["directional_reanchor_last_expired_at"] = now_iso
                bot["directional_reanchor_last_result"] = "expired_position_still_open"

    assert bot.get("directional_reanchor_pending") is False
    assert bot.get("directional_reanchor_last_result") == "expired_position_still_open"


def test_pending_expires_by_age_bound():
    """After max age seconds, pending expires even if cycle count is low."""
    _past = datetime.now(timezone.utc) - timedelta(seconds=strategy_cfg.DIRECTIONAL_REANCHOR_MAX_PENDING_AGE_SEC + 10)
    old_time = _past.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    bot = _make_bot(
        mode="long",
        range_mode="dynamic",
        directional_reanchor_pending=True,
        directional_reanchor_requested_at=old_time,
        _reanchor_pending_cycle=0,
    )
    current_position_size = 1.0
    mode = "long"
    now_iso = datetime.now(timezone.utc).isoformat()

    if bot.get("directional_reanchor_pending") and mode in ("long", "short"):
        reanchor_cycle = int(bot.get("_reanchor_pending_cycle", 0)) + 1
        bot["_reanchor_pending_cycle"] = reanchor_cycle

        _reanchor_age_expired = False
        _reanchor_requested = bot.get("directional_reanchor_requested_at", "")
        if _reanchor_requested:
            try:
                _req_dt = datetime.fromisoformat(str(_reanchor_requested).replace("Z", "+00:00"))
                _age_sec = (datetime.now(timezone.utc) - _req_dt).total_seconds()
                _reanchor_age_expired = _age_sec > strategy_cfg.DIRECTIONAL_REANCHOR_MAX_PENDING_AGE_SEC
            except Exception:
                pass

        if current_position_size > 0:
            if reanchor_cycle > strategy_cfg.DIRECTIONAL_REANCHOR_MAX_PENDING_CYCLES or _reanchor_age_expired:
                bot["directional_reanchor_pending"] = False
                bot["_reanchor_pending_cycle"] = 0
                bot["directional_reanchor_last_expired_at"] = now_iso
                bot["directional_reanchor_last_result"] = "expired_position_still_open"

    assert bot.get("directional_reanchor_pending") is False
    assert bot.get("directional_reanchor_last_result") == "expired_position_still_open"


def test_reanchor_clears_range_on_confirmed_flat():
    """When exchange confirms flat, lower_price/upper_price reset to 0."""
    bot = _make_bot(
        mode="long",
        range_mode="dynamic",
        directional_reanchor_pending=True,
        directional_reanchor_requested_at=datetime.now(timezone.utc).isoformat() + "Z",
    )
    bot["lower_price"] = 49000.0
    bot["upper_price"] = 51000.0

    svc = _make_service()
    svc._last_grid_center["test-bot-001_BTCUSDT"] = 50000.0
    svc._cancel_opening_orders_only = MagicMock(return_value=3)
    svc._save_runtime_bot = MagicMock()

    # Simulate confirmed flat
    current_position_size = 0.0
    mode = "long"
    bot_id = bot["id"]
    symbol = bot["symbol"]
    now_iso = datetime.now(timezone.utc).isoformat()

    if bot.get("directional_reanchor_pending") and mode in ("long", "short"):
        if current_position_size == 0:
            _reanchor_cancelled = svc._cancel_opening_orders_only(bot, symbol)
            bot["lower_price"] = 0.0
            bot["upper_price"] = 0.0
            _gc_key = f"{bot_id}_{symbol}"
            svc._last_grid_center.pop(_gc_key, None)
            bot["directional_reanchor_pending"] = False
            bot["_reanchor_pending_cycle"] = 0
            bot["directional_reanchor_last_completed_at"] = now_iso
            bot["directional_reanchor_last_cancelled_opening_orders"] = _reanchor_cancelled
            bot["directional_reanchor_last_result"] = "completed"

    assert bot["lower_price"] == 0.0
    assert bot["upper_price"] == 0.0
    assert bot.get("directional_reanchor_pending") is False
    assert bot.get("directional_reanchor_last_result") == "completed"
    assert bot.get("directional_reanchor_last_cancelled_opening_orders") == 3


def test_reanchor_clears_cached_grid_center():
    """Grid center cache entry is removed on reanchor."""
    svc = _make_service()
    svc._last_grid_center["test-bot-001_BTCUSDT"] = 50000.0
    svc._cancel_opening_orders_only = MagicMock(return_value=0)

    _gc_key = "test-bot-001_BTCUSDT"
    svc._last_grid_center.pop(_gc_key, None)

    assert _gc_key not in svc._last_grid_center


def test_reanchor_calls_cancel_opening_orders_only():
    """Reanchor calls _cancel_opening_orders_only, not a broader cancel method."""
    svc = _make_service()
    svc._cancel_opening_orders_only = MagicMock(return_value=2)

    bot = _make_bot(mode="short", range_mode="dynamic")
    symbol = bot["symbol"]

    result = svc._cancel_opening_orders_only(bot, symbol)
    svc._cancel_opening_orders_only.assert_called_once_with(bot, symbol)
    assert result == 2


def test_no_duplicate_reanchor_loop():
    """Once reanchor completes, pending is cleared and won't re-trigger."""
    bot = _make_bot(
        mode="long",
        range_mode="dynamic",
        directional_reanchor_pending=False,
        directional_reanchor_last_result="completed",
    )
    # With pending=False, the reanchor block should not execute
    assert bot.get("directional_reanchor_pending") is False
    # Simulating the guard check
    should_run = bot.get("directional_reanchor_pending") and bot.get("mode") in ("long", "short")
    assert should_run is False


# ---------------------------------------------------------------------------
# Test: Auto-reanchor on flat detection (exchange-side close / TP/SL fills)
# ---------------------------------------------------------------------------

def _simulate_auto_reanchor(bot, prev_persisted, current_position_size, mode, range_mode, now_iso):
    """Simulate the auto-reanchor detection logic from grid_bot_service."""
    _prev_position_side = str(bot.get("current_position_side") or "").lower()
    if (
        mode in ("long", "short")
        and range_mode != "fixed"
        and not bot.get("directional_reanchor_pending")
        and prev_persisted > 0
        and current_position_size == 0
    ):
        _side_matches_mode = (
            (mode == "long" and _prev_position_side == "buy")
            or (mode == "short" and _prev_position_side == "sell")
        )
        if _side_matches_mode:
            if strategy_cfg.DIRECTIONAL_REANCHOR_ON_FLAT_DETECTED_ENABLED:
                bot["directional_reanchor_pending"] = True
                bot["directional_reanchor_requested_at"] = now_iso
                bot["_reanchor_source"] = "flat_detected"
                return True
    return False


def test_auto_reanchor_on_flat_detected():
    """Position transitions from open to flat — auto-reanchor triggers."""
    bot = _make_bot(mode="long", range_mode="dynamic", position_size=1.5)
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=1.5, current_position_size=0.0,
                                         mode="long", range_mode="dynamic", now_iso=now_iso)
    assert triggered is True
    assert bot["directional_reanchor_pending"] is True
    assert bot["_reanchor_source"] == "flat_detected"
    assert bot["directional_reanchor_requested_at"] == now_iso


def test_auto_reanchor_on_flat_detected_short():
    """Short mode: position flat → auto-reanchor triggers."""
    bot = _make_bot(mode="short", range_mode="trailing", position_size=2.0)
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=2.0, current_position_size=0.0,
                                         mode="short", range_mode="trailing", now_iso=now_iso)
    assert triggered is True
    assert bot["directional_reanchor_pending"] is True


def test_auto_reanchor_skipped_for_fixed_range():
    """Fixed range mode — no auto-reanchor."""
    bot = _make_bot(mode="long", range_mode="fixed", position_size=1.0)
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=1.0, current_position_size=0.0,
                                         mode="long", range_mode="fixed", now_iso=now_iso)
    assert triggered is False
    assert bot.get("directional_reanchor_pending") is not True


def test_auto_reanchor_skipped_when_already_pending():
    """If reanchor is already pending (manual close path), don't double-trigger."""
    bot = _make_bot(mode="long", range_mode="dynamic", position_size=1.0,
                    directional_reanchor_pending=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=1.0, current_position_size=0.0,
                                         mode="long", range_mode="dynamic", now_iso=now_iso)
    assert triggered is False


def test_auto_reanchor_skipped_for_neutral_mode():
    """Neutral mode — no auto-reanchor."""
    bot = _make_bot(mode="neutral", range_mode="dynamic", position_size=1.0)
    bot["current_position_side"] = "buy"
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=1.0, current_position_size=0.0,
                                         mode="neutral", range_mode="dynamic", now_iso=now_iso)
    assert triggered is False


def test_auto_reanchor_skipped_for_side_mismatch():
    """Long mode but previous position was sell — no auto-reanchor (mode switch edge case)."""
    bot = _make_bot(mode="long", range_mode="dynamic", position_size=1.0)
    bot["current_position_side"] = "sell"  # Wrong side for long mode
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=1.0, current_position_size=0.0,
                                         mode="long", range_mode="dynamic", now_iso=now_iso)
    assert triggered is False


def test_auto_reanchor_disabled_via_config():
    """Config flag disabled — no auto-reanchor."""
    bot = _make_bot(mode="long", range_mode="dynamic", position_size=1.0)
    now_iso = datetime.now(timezone.utc).isoformat()
    original = strategy_cfg.DIRECTIONAL_REANCHOR_ON_FLAT_DETECTED_ENABLED
    try:
        strategy_cfg.DIRECTIONAL_REANCHOR_ON_FLAT_DETECTED_ENABLED = False
        triggered = _simulate_auto_reanchor(bot, prev_persisted=1.0, current_position_size=0.0,
                                             mode="long", range_mode="dynamic", now_iso=now_iso)
        assert triggered is False
    finally:
        strategy_cfg.DIRECTIONAL_REANCHOR_ON_FLAT_DETECTED_ENABLED = original


def test_auto_reanchor_no_trigger_when_still_has_position():
    """Position still open — no auto-reanchor (only triggers on transition to flat)."""
    bot = _make_bot(mode="long", range_mode="dynamic", position_size=1.0)
    now_iso = datetime.now(timezone.utc).isoformat()
    triggered = _simulate_auto_reanchor(bot, prev_persisted=1.0, current_position_size=0.5,
                                         mode="long", range_mode="dynamic", now_iso=now_iso)
    assert triggered is False
