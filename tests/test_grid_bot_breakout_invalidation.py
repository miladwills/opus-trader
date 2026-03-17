from unittest.mock import Mock

import services.grid_bot_service as grid_cfg

from services.grid_bot_service import GridBotService


class _FakeEntryGate:
    def __init__(self, candles):
        self._candles = candles

    def check_breakout_invalidation(
        self,
        symbol,
        mode,
        reference_level,
        reference_type=None,
    ):
        confirm_candles = max(int(grid_cfg.BREAKOUT_INVALIDATION_CONFIRM_CANDLES or 2), 1)
        buffer_pct = float(grid_cfg.BREAKOUT_INVALIDATION_RECLAIM_BUFFER_PCT or 0.0)
        recent_candles = list(self._candles)[-confirm_candles:]
        if len(recent_candles) < confirm_candles:
            return {
                "eligible": True,
                "invalidated": False,
                "reason": "Insufficient closed candles for breakout invalidation",
                "required_close": None,
                "latest_close": None,
                "confirm_candles": confirm_candles,
            }

        closes = [float((candle or {}).get("close") or 0.0) for candle in recent_candles]
        if str(mode or "").strip().lower() == "long":
            required_close = reference_level * (1.0 - buffer_pct)
            invalidated = all(close <= required_close for close in closes)
        else:
            required_close = reference_level * (1.0 + buffer_pct)
            invalidated = all(close >= required_close for close in closes)

        return {
            "eligible": True,
            "invalidated": invalidated,
            "reason": "fake invalidation",
            "required_close": round(required_close, 8),
            "latest_close": closes[-1],
            "confirm_candles": confirm_candles,
        }


def _make_service(*, candles, now_ts=1_700_000_000.0):
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client._get_now_ts.return_value = now_ts
    service._get_cycle_now_ts = Mock(return_value=now_ts)
    service._build_entry_gate_service = Mock(return_value=_FakeEntryGate(candles))
    service._cancel_opening_orders_only = Mock(return_value=2)
    service._build_close_order_link_id = Mock(return_value="cls:breakout")
    service._create_order_checked = Mock(return_value={"success": True})
    service._close_position_or_hard_fail = Mock(return_value={"success": True})
    service._get_shared_symbol_conflict = Mock(return_value=None)
    return service


def _enable_invalidation(monkeypatch, **overrides):
    values = {
        "BREAKOUT_INVALIDATION_EXIT_ENABLED": True,
        "BREAKOUT_INVALIDATION_CONFIRM_CANDLES": 2,
        "BREAKOUT_INVALIDATION_RECLAIM_BUFFER_PCT": 0.001,
        "BREAKOUT_INVALIDATION_PARTIAL_TRIM_ENABLED": True,
        "BREAKOUT_INVALIDATION_PARTIAL_TRIM_CLOSE_PCT": 0.12,
        "BREAKOUT_INVALIDATION_CLOSE_ON_PERSIST_ENABLED": False,
        "BREAKOUT_INVALIDATION_PERSIST_SECONDS": 180,
        "BREAKOUT_INVALIDATION_LOGGING_ENABLED": False,
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setattr(f"services.grid_bot_service.{name}", value)


def _breakout_bot(mode="long"):
    return {
        "id": "bot-breakout",
        "mode": mode,
        "breakout_confirmed_entry": True,
        "breakout_entry_confirmed": True,
        "breakout_entry_mode": mode,
        "breakout_reference_level": 100.0,
        "breakout_reference_type": "resistance" if mode == "long" else "support",
        "breakout_invalidation_state": "inactive",
    }


def _position(*, side, size=10.0, avg_price=100.0, position_idx=1):
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "size": str(size),
        "avgPrice": str(avg_price),
        "positionIdx": position_idx,
    }


def test_evaluate_breakout_invalidation_detects_long_reclaim_below_reference(monkeypatch):
    _enable_invalidation(monkeypatch)
    service = _make_service(candles=[{"close": 99.85}, {"close": 99.82}])

    result = GridBotService._evaluate_breakout_invalidation(
        service,
        bot=_breakout_bot("long"),
        symbol="BTCUSDT",
        mode="long",
        position=_position(side="Buy"),
    )

    assert result["eligible"] is True
    assert result["confirmed"] is True
    assert result["threshold_price"] == 99.9


def test_evaluate_breakout_invalidation_detects_short_reclaim_above_reference(monkeypatch):
    _enable_invalidation(monkeypatch)
    service = _make_service(candles=[{"close": 100.12}, {"close": 100.18}])

    result = GridBotService._evaluate_breakout_invalidation(
        service,
        bot=_breakout_bot("short"),
        symbol="BTCUSDT",
        mode="short",
        position=_position(side="Sell"),
    )

    assert result["eligible"] is True
    assert result["confirmed"] is True
    assert result["threshold_price"] == 100.1


def test_evaluate_breakout_invalidation_respects_confirm_candles_and_buffer(monkeypatch):
    _enable_invalidation(monkeypatch)
    service = _make_service(candles=[{"close": 99.85}, {"close": 99.95}])

    result = GridBotService._evaluate_breakout_invalidation(
        service,
        bot=_breakout_bot("long"),
        symbol="BTCUSDT",
        mode="long",
        position=_position(side="Buy"),
    )

    assert result["eligible"] is True
    assert result["confirmed"] is False


def test_breakout_invalidation_guard_blocks_adds_and_trims(monkeypatch):
    _enable_invalidation(monkeypatch)
    service = _make_service(candles=[{"close": 99.85}, {"close": 99.82}])
    bot = _breakout_bot("long")

    result = GridBotService._handle_breakout_invalidation_guard(
        service,
        bot=bot,
        symbol="BTCUSDT",
        position=_position(side="Buy"),
        mode="long",
        last_price=99.8,
    )

    assert result["active"] is True
    assert result["action"] == "trimmed"
    assert bot["_breakout_invalidation_block_opening_orders"] is True
    assert bot["breakout_invalidation_state"] == "trimmed"
    service._cancel_opening_orders_only.assert_called_once_with(bot, "BTCUSDT")
    kwargs = service._create_order_checked.call_args.kwargs
    assert kwargs["reduce_only"] is True
    assert kwargs["side"] == "Sell"
    assert kwargs["qty"] == 1.2
    assert kwargs["position_idx"] == 1


def test_breakout_invalidation_guard_can_close_when_persisted(monkeypatch):
    _enable_invalidation(
        monkeypatch,
        BREAKOUT_INVALIDATION_CLOSE_ON_PERSIST_ENABLED=True,
        BREAKOUT_INVALIDATION_PARTIAL_TRIM_ENABLED=True,
        BREAKOUT_INVALIDATION_PERSIST_SECONDS=180,
    )
    now_ts = 1_700_000_000.0
    service = _make_service(
        candles=[{"close": 99.85}, {"close": 99.82}],
        now_ts=now_ts,
    )
    bot = _breakout_bot("long")
    bot["_breakout_invalidation_state"] = {
        "position_key": "BTCUSDT:Buy:1:long",
        "active_since_ts": now_ts - 240.0,
        "partial_trim_done": True,
    }

    result = GridBotService._handle_breakout_invalidation_guard(
        service,
        bot=bot,
        symbol="BTCUSDT",
        position=_position(side="Buy"),
        mode="long",
        last_price=99.8,
    )

    assert result["action"] == "closed"
    assert result["position_closed"] is True
    assert bot["breakout_invalidation_state"] == "closing"
    service._close_position_or_hard_fail.assert_called_once_with(
        bot,
        "BTCUSDT",
        "breakout_invalidation",
    )
    service._create_order_checked.assert_not_called()


def test_breakout_invalidation_guard_skips_trim_when_symbol_has_active_sibling_bot(
    monkeypatch,
):
    _enable_invalidation(monkeypatch)
    service = _make_service(candles=[{"close": 99.85}, {"close": 99.82}])
    service._get_shared_symbol_conflict.return_value = {
        "success": False,
        "error": "shared_symbol_active_bots",
    }
    bot = _breakout_bot("long")

    result = GridBotService._handle_breakout_invalidation_guard(
        service,
        bot=bot,
        symbol="BTCUSDT",
        position=_position(side="Buy"),
        mode="long",
        last_price=99.8,
    )

    assert result["active"] is True
    assert result["action"] == "blocked"
    assert bot["_breakout_invalidation_block_opening_orders"] is True
    assert bot["breakout_invalidation_state"] == "risk"
    service._cancel_opening_orders_only.assert_called_once_with(bot, "BTCUSDT")
    service._create_order_checked.assert_not_called()


def test_breakout_invalidation_guard_keeps_adds_blocked_after_recovery(monkeypatch):
    _enable_invalidation(monkeypatch)
    now_ts = 1_700_000_000.0
    service = _make_service(
        candles=[{"close": 99.95}, {"close": 100.02}],
        now_ts=now_ts,
    )
    bot = _breakout_bot("long")
    bot["_breakout_invalidation_state"] = {
        "position_key": "BTCUSDT:Buy:1:long",
        "active_since_ts": now_ts - 120.0,
        "reason": "reclaim below broken resistance (100.000000)",
    }

    result = GridBotService._handle_breakout_invalidation_guard(
        service,
        bot=bot,
        symbol="BTCUSDT",
        position=_position(side="Buy"),
        mode="long",
        last_price=100.05,
    )

    assert result["active"] is True
    assert result["action"] == "recovered_blocked"
    assert bot["_breakout_invalidation_block_opening_orders"] is True
    assert bot["breakout_invalidation_state"] == "recovered_blocked"
    service._cancel_opening_orders_only.assert_not_called()
    service._create_order_checked.assert_not_called()


def test_breakout_invalidation_guard_ignores_neutral_and_non_breakout_bots(monkeypatch):
    _enable_invalidation(monkeypatch)
    service = _make_service(candles=[{"close": 99.85}, {"close": 99.82}])
    bot = {
        "id": "bot-neutral",
        "mode": "neutral",
        "breakout_confirmed_entry": False,
        "breakout_entry_confirmed": False,
    }

    result = GridBotService._handle_breakout_invalidation_guard(
        service,
        bot=bot,
        symbol="BTCUSDT",
        position=_position(side="Buy"),
        mode="neutral",
        last_price=99.8,
    )

    assert result["active"] is False
    assert bot["_breakout_invalidation_block_opening_orders"] is False
    service._cancel_opening_orders_only.assert_not_called()
    service._create_order_checked.assert_not_called()


def test_activate_breakout_entry_context_only_after_real_position():
    service = _make_service(candles=[{"close": 99.85}, {"close": 99.82}])
    bot = {
        "id": "bot-breakout",
        "mode": "long",
        "breakout_confirmed_entry": True,
        "_breakout_entry_pending_context": {
            "mode": "long",
            "level_price": 100.0,
            "level_type": "resistance",
            "required_close": 100.15,
        },
    }

    GridBotService._activate_breakout_entry_context_from_position(
        service,
        bot=bot,
        symbol="BTCUSDT",
        mode="long",
        position=_position(side="Buy"),
    )

    assert bot["breakout_entry_confirmed"] is True
    assert bot["breakout_entry_mode"] == "long"
    assert bot["breakout_reference_level"] == 100.0
    assert bot["breakout_reference_type"] == "resistance"
    assert "_breakout_entry_pending_context" not in bot
