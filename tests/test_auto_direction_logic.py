import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import services.grid_bot_service as grid_bot_service_module
from services.grid_bot_service import GridBotService

_NOW_TS = 1_700_000_000.0


def _setup_auto_pilot_service_attrs(service, symbols=None):
    """Set attributes required by Auto-Pilot pick/rotation paths."""
    symbols = symbols or []
    service._auto_pilot_instrument_meta_cache = {}
    service._auto_pilot_last_ticker_snapshot = {}
    service._auto_pilot_last_universe_stats = {}
    service.auto_pilot_candidate_cache_service = None
    service._get_cycle_now_ts = Mock(return_value=_NOW_TS)
    service._refresh_auto_pilot_loss_budget_state = Mock(
        return_value={"status": "healthy", "remaining_pct": 1.0}
    )
    # Build instruments catalog so strong-filter path doesn't fail
    launch_ms = str(int((_NOW_TS - 400 * 86400) * 1000))
    instruments = [
        {"symbol": sym, "status": "Trading", "symbolType": "linear", "launchTime": launch_ms}
        for sym in symbols
    ]
    service.client.get_instruments_info.return_value = {
        "success": True,
        "data": {"list": instruments, "nextPageCursor": ""},
    }


@pytest.fixture(autouse=True)
def _allow_btc_for_ranking_logic_tests(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    filtered = tuple(
        symbol
        for symbol in grid_bot_service_module.AUTO_PILOT_SYMBOL_BLACKLIST
        if symbol != "BTCUSDT"
    )
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_SYMBOL_BLACKLIST",
        filtered,
    )
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_SYMBOL_BLACKLIST",
        filtered,
    )


def test_auto_direction_blocks_neutral_entry_when_adx_below_threshold():
    service = GridBotService.__new__(GridBotService)
    bot = {"id": "bot-1"}

    analysis = GridBotService.get_auto_direction_analysis(
        service,
        symbol="BTCUSDT",
        current_mode="neutral",
        current_price=100.0,
        fast_indicators={
            "rsi": 65.0,
            "ema_cross": "bullish",
            "price_vs_ema": "above",
            "macd_cross": "bullish",
            "macd_histogram": 1.0,
            "volume_trend": "high",
            "volume_ratio": 2.0,
            "candle_pattern": "bullish_engulfing",
            "candle_signal": "bullish",
        },
        slow_indicators={
            "rsi": 60.0,
            "adx": 10.0,
            "ema_cross": "bullish",
            "macd_cross": "bullish",
        },
        bot=bot,
    )

    assert analysis["score"] >= 50
    assert analysis["target_mode"] == "neutral"
    assert analysis["blocked_mode_change"] is True
    assert bot["direction_score"] == analysis["score"]
    assert "EMA9/21" in bot["direction_signals"]


def test_dynamic_side_cancel_preserves_reduce_only_and_other_bot_orders():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service._is_reduce_only_order = GridBotService._is_reduce_only_order.__get__(
        service, GridBotService
    )
    service._parse_order_link_id = GridBotService._parse_order_link_id
    service._bot_id_matches_order_bot_id = (
        GridBotService._bot_id_matches_order_bot_id.__get__(service, GridBotService)
    )
    service._extract_order_list_from_response = (
        GridBotService._extract_order_list_from_response
    )

    bot = {"id": "7fe5dc76-0f86-4233-a74d-581ccfb8fead"}
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "orderId": "close-1",
                    "side": "Sell",
                    "reduceOnly": True,
                    "orderLinkId": "bv2:7fe5dc760f864233:12345678S0C",
                },
                {
                    "orderId": "open-1",
                    "side": "Sell",
                    "reduceOnly": False,
                    "orderLinkId": "bv2:7fe5dc760f864233:12345678S0O",
                },
                {
                    "orderId": "open-other-bot",
                    "side": "Sell",
                    "reduceOnly": False,
                    "orderLinkId": "bv2:aaaaaaaaaaaaaaaa:12345678S0O",
                },
                {
                    "orderId": "buy-open-1",
                    "side": "Buy",
                    "reduceOnly": False,
                    "orderLinkId": "bv2:7fe5dc760f864233:12345678B0O",
                },
            ]
        },
    }
    service.client.cancel_order.return_value = {"success": True}

    cancelled = GridBotService._cancel_bot_opening_orders_by_side(
        service,
        bot=bot,
        symbol="RIVERUSDT",
        side="Sell",
    )

    assert cancelled == 1
    service.client.cancel_order.assert_called_once_with(
        symbol="RIVERUSDT",
        order_id="open-1",
    )


def test_auto_pilot_only_enables_auto_direction_for_supported_modes():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    _setup_auto_pilot_service_attrs(service, ["BTCUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "50000000",
                    "lastPrice": "100000",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                }
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "scalp_pnl",
            "recommended_profile": "normal",
            "recommended_range_mode": "dynamic",
            "recommended_grid_levels": 10,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 80.0,
        }
    ]

    bot = {"id": "bot-1"}
    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["mode"] == "scalp_pnl"
    assert updated["auto_direction"] is False


def test_auto_pilot_uses_auto_calculated_leverage_from_scanner():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    _setup_auto_pilot_service_attrs(service, ["ETHUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "ETHUSDT",
                    "turnover24h": "50000000",
                    "lastPrice": "3000",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                }
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 2900.0, "upper": 3100.0},
            "neutral_score": 80.0,
        }
    ]

    bot = {"id": "bot-1", "leverage": 3}
    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["symbol"] == "ETHUSDT"
    # Auto-pilot auto-calculates leverage: neutral mode caps at min(scanner, 5)
    assert updated["leverage"] == 5
    service.client.set_leverage.assert_called_once_with("ETHUSDT", 5)


def test_auto_pilot_prefers_entry_suitable_candidate_over_raw_neutral_score():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "10000000",
                    "lastPrice": "100000",
                },
                {
                    "symbol": "ETHUSDT",
                    "turnover24h": "9000000",
                    "lastPrice": "3000",
                },
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    neutral_gate = Mock()

    def _check_side_open(symbol, side, current_price=None, indicators=None):
        if symbol == "BTCUSDT":
            return {
                "suitable": False,
                "reason": f"{side} blocked",
                "blocked_by": [f"{side}_BLOCKED"],
            }
        return {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
        }

    entry_gate.check_side_open.side_effect = _check_side_open
    neutral_gate.check_suitability.return_value = {"suitable": True, "reason": "clear"}
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 95.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {"score": 55.0, "verdict": "CAUTION", "best_for": "neutral_classic"},
        },
        {
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 2900.0, "upper": 3100.0},
            "neutral_score": 78.0,
            "mode_confidence": 0.65,
            "smart_score": 60.0,
            "entry_zone": {"score": 84.0, "verdict": "GOOD", "best_for": "neutral_classic"},
        },
    ]

    bot = {"id": "bot-1"}
    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["symbol"] == "ETHUSDT"
    assert updated["mode"] == "neutral_classic_bybit"
    service.client.set_margin_mode.assert_called_once_with(
        "ETHUSDT", "ISOLATED_MARGIN"
    )


def test_auto_pilot_setup_quality_bonus_prefers_higher_quality_candidate(monkeypatch):
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {"symbol": "BTCUSDT", "turnover24h": "10000000", "lastPrice": "100000"},
                {"symbol": "ETHUSDT", "turnover24h": "9000000", "lastPrice": "3000"},
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }

    def _get_setup_quality(symbol, mode, indicators=None):
        return {
            "enabled": True,
            "score": 42.0 if symbol == "BTCUSDT" else 78.0,
            "entry_allowed": True,
            "breakout_ready": True,
        }

    entry_gate.get_setup_quality.side_effect = _get_setup_quality
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {"suitable": True, "reason": "clear"}
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.8,
            "smart_score": 75.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 2900.0, "upper": 3100.0},
            "neutral_score": 89.0,
            "mode_confidence": 0.8,
            "smart_score": 75.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    updated = GridBotService._auto_pilot_pick_symbol(service, {"id": "bot-1"})

    assert updated["symbol"] == "ETHUSDT"


def test_auto_pilot_setup_quality_disabled_preserves_legacy_pick(monkeypatch):
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    _setup_auto_pilot_service_attrs(service, ["BTCUSDT", "ETHUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {"symbol": "BTCUSDT", "turnover24h": "50000000", "lastPrice": "100000", "volume24h": "2000000", "openInterestValue": "5000000", "price24hPcnt": "0.01"},
                {"symbol": "ETHUSDT", "turnover24h": "45000000", "lastPrice": "3000", "volume24h": "2000000", "openInterestValue": "5000000", "price24hPcnt": "0.01"},
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    entry_gate.get_setup_quality.return_value = {
        "enabled": False,
        "score": 20.0,
        "entry_allowed": True,
        "breakout_ready": True,
    }
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {"suitable": True, "reason": "clear"}
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.8,
            "smart_score": 75.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 2900.0, "upper": 3100.0},
            "neutral_score": 89.0,
            "mode_confidence": 0.8,
            "smart_score": 75.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    updated = GridBotService._auto_pilot_pick_symbol(service, {"id": "bot-1"})

    assert updated["symbol"] == "BTCUSDT"


def test_auto_pilot_velocity_factor_remains_bounded_and_mode_aware():
    service = GridBotService.__new__(GridBotService)

    long_baseline = GridBotService._score_auto_pilot_candidate(
        service,
        bot={},
        candidate={
            "symbol": "BTCUSDT",
            "recommended_mode": "long",
            "entry_zone": {"score": 82.0, "verdict": "GOOD", "best_for": "long"},
            "neutral_score": 60.0,
            "mode_confidence": 0.8,
            "smart_score": 70.0,
            "price_velocity": 0.0,
        },
    )
    long_fast = GridBotService._score_auto_pilot_candidate(
        service,
        bot={},
        candidate={
            "symbol": "BTCUSDT",
            "recommended_mode": "long",
            "entry_zone": {"score": 82.0, "verdict": "GOOD", "best_for": "long"},
            "neutral_score": 60.0,
            "mode_confidence": 0.8,
            "smart_score": 70.0,
            "price_velocity": 0.03,
        },
    )
    neutral_fast = GridBotService._score_auto_pilot_candidate(
        service,
        bot={},
        candidate={
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "entry_zone": {
                "score": 82.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
            "neutral_score": 60.0,
            "mode_confidence": 0.8,
            "smart_score": 70.0,
            "price_velocity": 0.03,
        },
    )
    neutral_baseline = GridBotService._score_auto_pilot_candidate(
        service,
        bot={},
        candidate={
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "entry_zone": {
                "score": 82.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
            "neutral_score": 60.0,
            "mode_confidence": 0.8,
            "smart_score": 70.0,
            "price_velocity": 0.0,
        },
    )

    assert 0 < (long_fast["score"] - long_baseline["score"]) <= 6.0  # was 4.0 — matches new velocity weight
    assert 0 < (neutral_baseline["score"] - neutral_fast["score"]) <= 6.0  # was 4.0 — matches new velocity weight


def test_auto_pilot_velocity_factor_can_be_disabled(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    service = GridBotService.__new__(GridBotService)
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_VELOCITY_FACTOR_ENABLED",
        False,
    )

    baseline = GridBotService._score_auto_pilot_candidate(
        service,
        bot={},
        candidate={
            "symbol": "BTCUSDT",
            "recommended_mode": "long",
            "entry_zone": {"score": 80.0, "verdict": "GOOD", "best_for": "long"},
            "neutral_score": 60.0,
            "mode_confidence": 0.8,
            "smart_score": 70.0,
            "price_velocity": 0.0,
        },
    )
    disabled = GridBotService._score_auto_pilot_candidate(
        service,
        bot={},
        candidate={
            "symbol": "BTCUSDT",
            "recommended_mode": "long",
            "entry_zone": {"score": 80.0, "verdict": "GOOD", "best_for": "long"},
            "neutral_score": 60.0,
            "mode_confidence": 0.8,
            "smart_score": 70.0,
            "price_velocity": 0.03,
        },
    )

    assert disabled["score"] == baseline["score"]


def test_auto_pilot_adaptive_rotation_interval_shortens_for_weak_high_vol_symbol():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)

    interval = GridBotService._compute_auto_pilot_rotation_interval(
        service,
        bot={},
        current_candidate={
            "_auto_pilot_score": 60.0,
            "atr_pct": 0.05,
            "price_velocity": 0.001,
            "recommended_mode": "long",
        },
        best_candidate={"price_velocity": 0.02},
        score_gap=24.0,
        urgent_rotation=False,
    )

    assert interval["effective_seconds"] < interval["base_seconds"]
    assert "current_symbol_weak" in interval["reasons"]
    assert "volatility_high" in interval["reasons"]
    assert "score_gap_strong" in interval["reasons"]


def test_auto_pilot_adaptive_rotation_interval_stays_longer_when_symbol_is_healthy():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)

    interval = GridBotService._compute_auto_pilot_rotation_interval(
        service,
        bot={},
        current_candidate={
            "_auto_pilot_score": 95.0,
            "atr_pct": 0.01,
            "price_velocity": 0.001,
            "recommended_mode": "neutral_classic_bybit",
        },
        best_candidate={"price_velocity": 0.0015},
        score_gap=3.0,  # was 4.0 — fits within new threshold (7.0 * 0.5 = 3.5)
        urgent_rotation=False,
    )

    assert interval["effective_seconds"] >= interval["base_seconds"]
    assert "current_symbol_healthy" in interval["reasons"]


def test_auto_pilot_adaptive_rotation_still_respects_score_threshold():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._force_cancel_all_orders = Mock(return_value={"success": True})
    service._close_position_market = Mock(return_value=True)
    _setup_auto_pilot_service_attrs(service, ["XAUTUSDT", "BTCUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {"symbol": "XAUTUSDT", "turnover24h": "50000000", "lastPrice": "5143.7", "volume24h": "2000000", "openInterestValue": "5000000", "price24hPcnt": "0.01"},
                {"symbol": "BTCUSDT", "turnover24h": "45000000", "lastPrice": "100000", "volume24h": "2000000", "openInterestValue": "5000000", "price24hPcnt": "0.01"},
            ]
        },
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{"symbol": "XAUTUSDT", "size": "0", "unrealisedPnl": "0"}]},
    }
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {"list": []},
    }

    entry_gate = Mock()
    neutral_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    neutral_gate.check_suitability.return_value = {
        "suitable": True,
        "reason": "clear",
    }
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "XAUTUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 5040.0, "upper": 5246.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "atr_pct": 0.05,
            "price_velocity": 0.001,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.7,
            "smart_score": 77.0,
            "atr_pct": 0.03,
            "price_velocity": 0.002,
            "entry_zone": {
                "score": 95.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "mode": "neutral_classic_bybit",
        "auto_pilot": True,
        "auto_pilot_last_scan_at": (
            datetime.now(timezone.utc) - timedelta(seconds=1000)
        ).isoformat(),
        "auto_pilot_effective_rotation_interval_sec": 900,
    }

    updated = GridBotService._auto_pilot_check_rotation(service, bot, "XAUTUSDT")

    assert updated is None
    assert bot["symbol"] == "XAUTUSDT"
    assert bot["auto_pilot_best_available"].startswith("BTCUSDT:")
    service._force_cancel_all_orders.assert_not_called()


def test_auto_pilot_penalizes_neutral_gate_blocked_candidate():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "10000000",
                    "lastPrice": "100000",
                },
                {
                    "symbol": "ETHUSDT",
                    "turnover24h": "9000000",
                    "lastPrice": "3000",
                },
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }

    neutral_gate = Mock()

    def _check_suitability(symbol, preset=None):
        if symbol == "BTCUSDT":
            return {"suitable": False, "reason": "ADX1m strong move"}
        return {"suitable": True, "reason": "clear"}

    neutral_gate.check_suitability.side_effect = _check_suitability
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 95.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 2900.0, "upper": 3100.0},
            "neutral_score": 78.0,
            "mode_confidence": 0.65,
            "smart_score": 60.0,
            "entry_zone": {
                "score": 84.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {"id": "bot-1"}
    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["symbol"] == "ETHUSDT"
    assert updated["mode"] == "neutral_classic_bybit"


def test_auto_pilot_penalizes_one_sided_neutral_candidate_via_price_action():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "10000000",
                    "lastPrice": "100000",
                },
                {
                    "symbol": "ETHUSDT",
                    "turnover24h": "9000000",
                    "lastPrice": "3000",
                },
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {"suitable": True, "reason": "clear"}
    price_action_service = Mock()

    def _analyze(symbol):
        if symbol == "BTCUSDT":
            return {
                "symbol": symbol,
                "direction": "bullish",
                "net_score": 18.0,
                "bullish_score": 18.0,
                "bearish_score": 0.0,
                "summary": "Bullish break with strong volume",
            }
        return {
            "symbol": symbol,
            "direction": "neutral",
            "net_score": 2.0,
            "bullish_score": 2.0,
            "bearish_score": 0.0,
            "summary": "Mixed price action",
        }

    def _score_mode_fit(context, mode):
        if context["symbol"] == "BTCUSDT":
            return {"score": -16.0, "direction": context["direction"]}
        return {"score": 5.0, "direction": context["direction"]}

    price_action_service.analyze.side_effect = _analyze
    price_action_service.score_mode_fit.side_effect = _score_mode_fit
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)
    service._build_price_action_signal_service = Mock(return_value=price_action_service)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 95.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "ETHUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 2900.0, "upper": 3100.0},
            "neutral_score": 82.0,
            "mode_confidence": 0.65,
            "smart_score": 60.0,
            "entry_zone": {
                "score": 84.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {"id": "bot-1"}
    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["symbol"] == "ETHUSDT"
    assert updated["mode"] == "neutral_classic_bybit"


def test_auto_pilot_pick_clears_stale_neutral_grid_state():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BEATUSDT",
                    "turnover24h": "10000000",
                    "lastPrice": "0.35947",
                }
            ]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {
        "suitable": True,
        "reason": "clear",
    }
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BEATUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 0.3521, "upper": 0.3683},
            "neutral_score": 83.0,
            "mode_confidence": 0.7,
            "smart_score": 53.0,
            "entry_zone": {
                "score": 80.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        }
    ]

    bot = {
        "id": "bot-1",
        "symbol": "Auto-Pilot",
        "mode": "neutral_classic_bybit",
        "neutral_grid": {
            "lower_price": 5040.434,
            "upper_price": 5246.166,
            "slots": {"L00": {"state": "ENTRY"}},
        },
        "neutral_grid_initialized": True,
        "grid_lower_price": 5040.434,
        "grid_upper_price": 5246.166,
        "grid_levels_total": 10,
        "levels_count": 11,
        "mid_index": 5,
        "entry_orders_open": 10,
        "active_long_slots": 5,
        "active_short_slots": 5,
        "last_error": "Invalid neutral grid config (bounds or levels)",
    }

    updated = GridBotService._auto_pilot_pick_symbol(service, bot)

    assert updated["symbol"] == "BEATUSDT"
    assert updated["neutral_grid"] == {}
    assert updated["neutral_grid_initialized"] is False
    assert updated["neutral_grid_last_reconcile_at"] is None
    assert updated["grid_lower_price"] == 0.3521
    assert updated["grid_upper_price"] == 0.3683
    assert updated["grid_levels_total"] == 8
    assert updated["levels_count"] is None
    assert updated["mid_index"] is None
    assert updated["entry_orders_open"] == 0
    assert updated["active_long_slots"] == 0
    assert updated["active_short_slots"] == 0
    assert updated["_position_mode"] is None
    assert updated["_position_mode_ts"] is None
    assert updated["last_error"] is None


def test_should_poll_fast_refill_skips_auto_pilot_placeholder():
    service = GridBotService.__new__(GridBotService)
    service._stream_reaction_service = Mock()

    should_poll = GridBotService.should_poll_fast_refill(
        service,
        {"id": "bot-1", "symbol": "Auto-Pilot", "auto_pilot": True},
    )

    assert should_poll is False
    service._stream_reaction_service.should_poll_fast_refill.assert_not_called()


def test_neutral_classic_fast_refill_skips_auto_pilot_placeholder():
    service = GridBotService.__new__(GridBotService)
    service.bot_storage = Mock()
    service.bot_storage.get_bot.return_value = None
    service.neutral_grid_service = Mock()
    service._try_acquire_bot_run_lock = Mock(return_value=(True, object()))
    service._release_bot_run_lock = Mock()
    service._ensure_stream_symbol = Mock()

    bot = {
        "id": "bot-1",
        "symbol": "Auto-Pilot",
        "auto_pilot": True,
        "mode": "neutral_classic_bybit",
        "status": "running",
    }

    updated = GridBotService.run_neutral_classic_fast_refill(service, bot)

    assert updated == bot
    service.neutral_grid_service.reconcile_on_start.assert_not_called()
    service._ensure_stream_symbol.assert_not_called()
    service._release_bot_run_lock.assert_called_once()


def test_auto_pilot_force_repick_bypasses_rotation_interval_when_flat_and_blocked():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._force_cancel_all_orders = Mock(return_value={"success": True})
    service._close_position_market = Mock(return_value=True)
    _setup_auto_pilot_service_attrs(service, ["XAUTUSDT", "BTCUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "XAUTUSDT",
                    "turnover24h": "50000000",
                    "lastPrice": "5143.7",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "45000000",
                    "lastPrice": "100000",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
            ]
        },
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [
                {"symbol": "XAUTUSDT", "size": "0", "unrealisedPnl": "0"},
            ]
        },
    }
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {"list": []},
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()

    def _check_side_open(symbol, side, current_price=None, indicators=None):
        if symbol == "XAUTUSDT":
            return {
                "suitable": False,
                "reason": f"{side} blocked",
                "blocked_by": [f"{side}_BLOCKED"],
            }
        return {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
        }

    neutral_gate = Mock()

    def _check_suitability(symbol, preset=None):
        if symbol == "XAUTUSDT":
            return {"suitable": False, "reason": "ADX1m strong move"}
        return {"suitable": True, "reason": "clear"}

    entry_gate.check_side_open.side_effect = _check_side_open
    neutral_gate.check_suitability.side_effect = _check_suitability
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "XAUTUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 5040.0, "upper": 5246.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 82.0,
            "mode_confidence": 0.6,
            "smart_score": 60.0,
            "entry_zone": {
                "score": 80.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "mode": "neutral_classic_bybit",
        "auto_pilot": True,
        "_nlp_block_opening_orders": True,
        "_entry_structure_skip_buy": True,
        "_entry_structure_skip_sell": True,
        "auto_pilot_last_scan_at": datetime.now(timezone.utc).isoformat(),
        "auto_pilot_opening_blocked_since": time.time() - 180,
    }

    updated = GridBotService._auto_pilot_check_rotation(service, bot, "XAUTUSDT")

    assert updated is bot
    assert updated["symbol"] == "BTCUSDT"
    service._force_cancel_all_orders.assert_called_once_with(
        "XAUTUSDT", max_retries=2, bot=bot
    )


def test_auto_pilot_force_repick_disqualifies_current_blocked_symbol_even_if_top_scored():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._force_cancel_all_orders = Mock(return_value={"success": True})
    service._close_position_market = Mock(return_value=True)
    _setup_auto_pilot_service_attrs(service, ["XAUTUSDT", "BTCUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "XAUTUSDT",
                    "turnover24h": "50000000",
                    "lastPrice": "5143.7",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "45000000",
                    "lastPrice": "100000",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
            ]
        },
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{"symbol": "XAUTUSDT", "size": "0", "unrealisedPnl": "0"}]},
    }
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {"list": []},
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {
        "suitable": True,
        "reason": "clear",
    }
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "XAUTUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 5040.0, "upper": 5246.0},
            "neutral_score": 95.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {
                "score": 90.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 82.0,
            "mode_confidence": 0.6,
            "smart_score": 60.0,
            "entry_zone": {
                "score": 80.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "mode": "neutral_classic_bybit",
        "auto_pilot": True,
        "_nlp_block_opening_orders": True,
        "_entry_structure_skip_buy": True,
        "_entry_structure_skip_sell": True,
        "auto_pilot_last_scan_at": datetime.now(timezone.utc).isoformat(),
        "auto_pilot_opening_blocked_since": time.time() - 180,
    }

    updated = GridBotService._auto_pilot_check_rotation(service, bot, "XAUTUSDT")

    assert updated is bot
    assert updated["symbol"] == "BTCUSDT"
    assert str(updated["auto_pilot_best_available"]).startswith("BTCUSDT:")
    service._force_cancel_all_orders.assert_called_once_with(
        "XAUTUSDT", max_retries=2, bot=bot
    )


def test_auto_pilot_defers_rotation_and_freezes_openings_on_losing_position():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._force_cancel_all_orders = Mock(return_value={"success": True})
    service._close_position_market = Mock(return_value=True)
    service._cancel_opening_orders_only = Mock(return_value=3)
    _setup_auto_pilot_service_attrs(service, ["XAUTUSDT", "BTCUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "XAUTUSDT",
                    "turnover24h": "50000000",
                    "lastPrice": "5143.7",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "45000000",
                    "lastPrice": "100000",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
            ]
        },
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {
            "list": [{"symbol": "XAUTUSDT", "size": "0.02", "unrealisedPnl": "-1.25"}]
        },
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {
        "suitable": True,
        "reason": "clear",
    }
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.9,
            "smart_score": 85.0,
            "entry_zone": {
                "score": 90.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "XAUTUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 5040.0, "upper": 5246.0},
            "neutral_score": 70.0,
            "mode_confidence": 0.5,
            "smart_score": 40.0,
            "entry_zone": {
                "score": 70.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "mode": "neutral_classic_bybit",
        "auto_pilot": True,
    }

    updated = GridBotService._auto_pilot_check_rotation(service, bot, "XAUTUSDT")

    assert updated is None
    assert bot["symbol"] == "XAUTUSDT"
    assert bot["_block_opening_orders"] is True
    assert bot["auto_pilot_rotation_pending"] is True
    assert bot["auto_pilot_rotation_pending_since"] is not None
    assert str(bot["auto_pilot_rotation_pending_target"]).startswith("BTCUSDT:")
    service._cancel_opening_orders_only.assert_called_once_with(bot, "XAUTUSDT")
    service._force_cancel_all_orders.assert_not_called()


def test_auto_pilot_pending_rotation_disqualifies_current_symbol_when_flat():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._force_cancel_all_orders = Mock(return_value={"success": True})
    service._close_position_market = Mock(return_value=True)
    _setup_auto_pilot_service_attrs(service, ["XAUTUSDT", "BTCUSDT"])

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "XAUTUSDT",
                    "turnover24h": "50000000",
                    "lastPrice": "5143.7",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "45000000",
                    "lastPrice": "100000",
                    "volume24h": "2000000",
                    "openInterestValue": "5000000",
                    "price24hPcnt": "0.01",
                },
            ]
        },
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{"symbol": "XAUTUSDT", "size": "0", "unrealisedPnl": "0"}]},
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()
    entry_gate.check_side_open.return_value = {
        "suitable": True,
        "reason": "clear",
        "blocked_by": [],
    }
    neutral_gate = Mock()
    neutral_gate.check_suitability.return_value = {
        "suitable": True,
        "reason": "clear",
    }
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "XAUTUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 5040.0, "upper": 5246.0},
            "neutral_score": 95.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {
                "score": 90.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "BTCUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 99000.0, "upper": 101000.0},
            "neutral_score": 82.0,
            "mode_confidence": 0.6,
            "smart_score": 60.0,
            "entry_zone": {
                "score": 80.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "mode": "neutral_classic_bybit",
        "auto_pilot": True,
        "auto_pilot_rotation_pending": True,
        "auto_pilot_last_scan_at": datetime.now(timezone.utc).isoformat(),
    }

    updated = GridBotService._auto_pilot_check_rotation(service, bot, "XAUTUSDT")

    assert updated is bot
    assert updated["symbol"] == "BTCUSDT"
    assert updated["auto_pilot_rotation_pending"] is False
    service._force_cancel_all_orders.assert_called_once_with(
        "XAUTUSDT", max_retries=2, bot=bot
    )


def test_auto_pilot_rotation_clears_stale_neutral_grid_state():
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._force_cancel_all_orders = Mock(return_value={"success": True})
    service._close_position_market = Mock(return_value=True)

    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "XAUTUSDT",
                    "turnover24h": "10000000",
                    "lastPrice": "5143.7",
                },
                {
                    "symbol": "BEATUSDT",
                    "turnover24h": "9000000",
                    "lastPrice": "0.35947",
                },
            ]
        },
    }
    service.client.get_positions.return_value = {
        "success": True,
        "data": {"list": [{"symbol": "XAUTUSDT", "size": "0", "unrealisedPnl": "0"}]},
    }
    service.client.get_open_orders.return_value = {
        "success": True,
        "data": {"list": []},
    }
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    entry_gate = Mock()

    def _check_side_open(symbol, side, current_price=None, indicators=None):
        if symbol == "XAUTUSDT":
            return {
                "suitable": False,
                "reason": f"{side} blocked",
                "blocked_by": [f"{side}_BLOCKED"],
            }
        return {
            "suitable": True,
            "reason": "clear",
            "blocked_by": [],
        }

    neutral_gate = Mock()

    def _check_suitability(symbol, preset=None):
        if symbol == "XAUTUSDT":
            return {"suitable": False, "reason": "ADX1m strong move"}
        return {"suitable": True, "reason": "clear"}

    entry_gate.check_side_open.side_effect = _check_side_open
    neutral_gate.check_suitability.side_effect = _check_suitability
    service._build_entry_gate_service = Mock(return_value=entry_gate)
    service._build_neutral_suitability_service = Mock(return_value=neutral_gate)

    service.neutral_scanner.scan.return_value = [
        {
            "symbol": "XAUTUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 10,
            "recommended_leverage": 5,
            "suggested_range": {"lower": 5040.0, "upper": 5246.0},
            "neutral_score": 90.0,
            "mode_confidence": 0.9,
            "smart_score": 80.0,
            "entry_zone": {
                "score": 88.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
        {
            "symbol": "BEATUSDT",
            "recommended_mode": "neutral_classic_bybit",
            "recommended_profile": "normal",
            "recommended_range_mode": "fixed",
            "recommended_grid_levels": 8,
            "recommended_leverage": 3,
            "suggested_range": {"lower": 0.3521, "upper": 0.3683},
            "neutral_score": 90.5,
            "mode_confidence": 0.7,
            "smart_score": 53.0,
            "entry_zone": {
                "score": 80.0,
                "verdict": "GOOD",
                "best_for": "neutral_classic",
            },
        },
    ]

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "mode": "neutral_classic_bybit",
        "auto_pilot": True,
        "_nlp_block_opening_orders": True,
        "_entry_structure_skip_buy": True,
        "_entry_structure_skip_sell": True,
        "auto_pilot_last_scan_at": datetime.now(timezone.utc).isoformat(),
        "auto_pilot_opening_blocked_since": time.time() - 180,
        "neutral_grid": {
            "lower_price": 5040.434,
            "upper_price": 5246.166,
            "slots": {"L00": {"state": "ENTRY"}},
        },
        "neutral_grid_initialized": True,
        "grid_lower_price": 5040.434,
        "grid_upper_price": 5246.166,
        "grid_levels_total": 10,
        "levels_count": 11,
        "mid_index": 5,
        "entry_orders_open": 10,
        "active_long_slots": 5,
        "active_short_slots": 5,
        "last_error": "Invalid neutral grid config (bounds or levels)",
    }

    updated = GridBotService._auto_pilot_check_rotation(service, bot, "XAUTUSDT")

    assert updated is bot
    assert updated["symbol"] == "BEATUSDT"
    assert updated["neutral_grid"] == {}
    assert updated["neutral_grid_initialized"] is False
    assert updated["neutral_grid_last_reconcile_at"] is None
    assert updated["grid_lower_price"] == 0.3521
    assert updated["grid_upper_price"] == 0.3683
    assert updated["grid_levels_total"] == 8
    assert updated["levels_count"] is None
    assert updated["mid_index"] is None
    assert updated["entry_orders_open"] == 0
    assert updated["active_long_slots"] == 0
    assert updated["active_short_slots"] == 0
    assert updated["_position_mode"] is None
    assert updated["_position_mode_ts"] is None
    assert updated["last_error"] is None


def test_run_bot_cycle_checks_force_repick_even_when_smart_rotation_disabled():
    service = GridBotService.__new__(GridBotService)
    service._ensure_stream_symbol = Mock()
    service._auto_pilot_should_force_repick = Mock(return_value=True)
    service._auto_pilot_pending_rotation_ready = Mock(return_value=False)
    service._auto_pilot_check_rotation = Mock(
        return_value={"id": "bot-1", "symbol": "BTCUSDT"}
    )

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "auto_pilot": True,
    }

    updated = GridBotService._run_bot_cycle_impl(service, bot)

    assert updated["symbol"] == "BTCUSDT"
    service._auto_pilot_check_rotation.assert_called_once_with(bot, "XAUTUSDT")


def test_run_bot_cycle_checks_pending_rotation_even_when_smart_rotation_disabled():
    service = GridBotService.__new__(GridBotService)
    service._ensure_stream_symbol = Mock()
    service._auto_pilot_should_force_repick = Mock(return_value=False)
    service._auto_pilot_pending_rotation_ready = Mock(return_value=True)
    service._auto_pilot_check_rotation = Mock(
        return_value={"id": "bot-1", "symbol": "BTCUSDT"}
    )

    bot = {
        "id": "bot-1",
        "symbol": "XAUTUSDT",
        "auto_pilot": True,
        "auto_pilot_rotation_pending": True,
    }

    updated = GridBotService._run_bot_cycle_impl(service, bot)

    assert updated["symbol"] == "BTCUSDT"
    service._auto_pilot_check_rotation.assert_called_once_with(bot, "XAUTUSDT")
