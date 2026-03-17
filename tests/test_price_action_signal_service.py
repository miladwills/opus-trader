from services.price_action_signal_service import PriceActionSignalService


class DummyIndicatorService:
    def get_ohlcv(self, symbol, interval="15", limit=200):
        return []

    def compute_indicators(self, symbol, interval="15", limit=200):
        if str(interval) == "60":
            return {
                "rsi": 62.0,
                "adx": 28.0,
                "macd_cross": "bullish",
                "ema_cross": "bullish",
                "price_vs_ema": "above",
            }
        return {
            "rsi": 58.0,
            "adx": 25.0,
            "macd_cross": "bullish",
            "ema_cross": "bullish",
            "price_vs_ema": "above",
        }

    def _detect_candle_patterns(self, candles):
        return None


def _base_candles(count=40, price=100.0):
    candles = []
    for idx in range(count):
        candles.append(
            {
                "open": price + (idx * 0.02),
                "high": price + 0.4 + (idx * 0.02),
                "low": price - 0.4 + (idx * 0.02),
                "close": price + (idx * 0.02),
                "volume": 1000.0,
            }
        )
    return candles


def test_market_structure_break_scores_bullish_break(monkeypatch):
    service = PriceActionSignalService(DummyIndicatorService())
    monkeypatch.setattr(
        service._structure_analyzer,
        "analyze_trend_structure",
        lambda candles: {
            "trend": "bullish",
            "strength": 6,
            "last_swing_high": (22, 100.0),
            "last_swing_low": (18, 97.5),
        },
    )

    candles = _base_candles()
    candles[-1]["close"] = 100.6
    candles[-1]["high"] = 100.9
    candles[-1]["low"] = 99.9

    result = service._analyze_market_structure(candles)

    assert result["signal"] == "bullish_break"
    assert result["score"] > 0
    assert "Bullish break" in result["summary"]


def test_liquidity_sweep_detects_bearish_rejection(monkeypatch):
    service = PriceActionSignalService(DummyIndicatorService())
    candles = _base_candles()
    candles[-1] = {
        "open": 100.35,
        "high": 101.1,
        "low": 100.0,
        "close": 100.15,
        "volume": 1800.0,
    }
    levels = {
        "nearest_support": None,
        "nearest_resistance": {"price": 100.5, "strength": 8},
    }

    result = service._analyze_liquidity_sweep(candles, levels)

    assert result["signal"] == "bearish_sweep_rejection"
    assert result["score"] < 0
    assert "Bearish liquidity sweep" in result["summary"]


def test_score_for_mode_penalizes_neutral_when_price_action_is_one_sided():
    service = PriceActionSignalService(DummyIndicatorService())
    context = {
        "direction": "bullish",
        "net_score": 18.0,
        "bullish_score": 18.0,
        "bearish_score": 0.0,
        "components": {},
    }

    neutral_score = service.score_mode_fit(context=context, mode="neutral_classic_bybit")
    long_score = service.score_mode_fit(context=context, mode="long")

    assert neutral_score["score"] < 0
    assert long_score["score"] > 0
