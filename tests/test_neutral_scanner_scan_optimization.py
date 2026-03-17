from types import SimpleNamespace
from unittest.mock import Mock

from services.neutral_scanner_service import NeutralScannerService


class _FakeIndicatorService:
    def __init__(self):
        self._ohlcv_cache = {}
        self.fetches = []

    def get_ohlcv(self, symbol, interval="15", limit=200):
        normalized_interval = str(interval)
        cache_key = (symbol, normalized_interval, limit)
        cached = self._ohlcv_cache.get(cache_key)
        if cached is not None:
            return cached

        for (cached_symbol, cached_interval, cached_limit), candles in self._ohlcv_cache.items():
            if (
                cached_symbol == symbol
                and cached_interval == normalized_interval
                and cached_limit >= limit
            ):
                return candles[-limit:]

        self.fetches.append((symbol, normalized_interval, limit))
        base_price = 100.0 if symbol == "ETHUSDT" else 50000.0
        candles = []
        for idx in range(limit):
            close = base_price + (idx * 0.1)
            candles.append(
                {
                    "open": close - 0.05,
                    "high": close + 0.10,
                    "low": close - 0.10,
                    "close": close,
                    "volume": 1000.0 + idx,
                }
            )
        self._ohlcv_cache[cache_key] = candles
        return candles

    def compute_indicators(self, symbol, interval="15", limit=200):
        candles = self.get_ohlcv(symbol, interval=interval, limit=limit)
        close = candles[-1]["close"] if candles else None
        return {
            "rsi": 50.0,
            "adx": 12.0,
            "atr_pct": 0.01,
            "bbw_pct": 0.02,
            "close": close,
            "price_velocity": 0.001,
        }


class _FakePredictionService:
    def __init__(self, indicator_service):
        self.indicator_service = indicator_service

    def predict(self, symbol, timeframe="15"):
        self.indicator_service.get_ohlcv(symbol, timeframe, limit=1000)
        return SimpleNamespace(score=12.5, direction="NEUTRAL")


def _make_service():
    service = NeutralScannerService.__new__(NeutralScannerService)
    service._scan_result_cache = {}
    indicator_service = _FakeIndicatorService()
    classify_calls = []

    def _classify_regime(**kwargs):
        classify_calls.append(kwargs)
        return {"regime": "choppy"}

    service.client = Mock()
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "turnover24h": "2000000000",
                    "fundingRate": "0.0001",
                    "price24hPcnt": "0.01",
                    "lastPrice": "50000",
                    "openInterestValue": "1000000000",
                },
                {
                    "symbol": "ETHUSDT",
                    "turnover24h": "1234567",
                    "fundingRate": "0.0002",
                    "price24hPcnt": "0.02",
                    "lastPrice": "100",
                    "openInterestValue": "500000",
                },
            ]
        },
    }
    service.indicator_service = indicator_service
    service.entry_filter_service = SimpleNamespace(classify_regime=_classify_regime)
    service.range_engine = Mock()
    service.range_engine.build_neutral_range.return_value = {
        "lower": 95.0,
        "upper": 105.0,
        "width_pct": 0.1,
    }
    service.prediction_service = _FakePredictionService(indicator_service)
    service._resolve_scan_symbols = lambda symbols: list(symbols)
    service._compute_correlation = lambda btc_closes, sym_closes: 0.42
    service._classify_speed = lambda atr_pct, bbw_pct: "normal"
    service._compute_neutral_score = lambda **kwargs: 75.0
    service._calculate_smart_momentum_score = lambda **kwargs: {
        "score": 55.0,
        "details": [],
        "pump_risk": False,
    }
    service._detect_trend_direction = lambda indicators: "neutral"
    service._recommend_mode = lambda **kwargs: {
        "recommended_mode": "neutral",
        "mode_confidence": 70.0,
        "mode_reasoning": "ok",
    }
    service._recommend_range_mode = lambda **kwargs: "dynamic"
    service._select_neutral_variant = lambda adx, atr_pct: "dynamic"
    service._recommend_profile = lambda **kwargs: "normal"
    service._recommend_leverage = lambda atr_pct, speed: 3
    service._recommend_grid_levels = lambda width_pct: 8
    service._compute_entry_zone_analysis = lambda **kwargs: {"score": 60.0}
    service._format_velocity = lambda value: "0.10%/hr"
    return service, indicator_service, classify_calls


def test_scan_reuses_bulk_ticker_snapshot_for_regime_and_output():
    service, _, classify_calls = _make_service()

    results = NeutralScannerService.scan(service, ["ETHUSDT"])

    assert len(results) == 1
    assert results[0]["symbol"] == "ETHUSDT"
    assert results[0]["volume_24h_usdt"] == 1234567.0
    assert service.client.get_tickers.call_count == 1
    assert service.client.get_tickers.call_args.args == ()
    assert classify_calls[0]["turnover_24h_usdt"] == 1234567.0


def test_scan_prediction_warms_15m_cache_for_indicator_and_correlation_reads():
    service, indicator_service, _ = _make_service()

    NeutralScannerService.scan(service, ["ETHUSDT"])

    eth_15_fetches = [
        fetch for fetch in indicator_service.fetches if fetch[0] == "ETHUSDT" and fetch[1] == "15"
    ]
    assert eth_15_fetches == [("ETHUSDT", "15", 1000)]


def test_scan_reuses_short_lived_result_cache_for_identical_symbol_sets():
    service, indicator_service, _ = _make_service()

    first_results = NeutralScannerService.scan(service, ["ETHUSDT"])
    first_fetches = list(indicator_service.fetches)
    first_ticker_calls = service.client.get_tickers.call_count

    second_results = NeutralScannerService.scan(service, ["ETHUSDT"])

    assert second_results == first_results
    assert indicator_service.fetches == first_fetches
    assert service.client.get_tickers.call_count == first_ticker_calls


def test_scan_ignores_invalid_stream_ticker_rows_and_falls_back_to_rest():
    service, _, _ = _make_service()
    service.client.stream_service = Mock()
    service.client.stream_service.get_ticker_rows.return_value = Mock()

    results = NeutralScannerService.scan(service, ["ETHUSDT"])

    assert len(results) == 1
    assert results[0]["symbol"] == "ETHUSDT"
    assert results[0]["volume_24h_usdt"] == 1234567.0
    assert service.client.get_tickers.call_count == 1
