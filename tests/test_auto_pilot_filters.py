from unittest.mock import Mock

import services.grid_bot_service as grid_bot_service_module
from services.grid_bot_service import GridBotService


def _make_service(now_ts: float = 1_700_000_000.0) -> GridBotService:
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._auto_pilot_instrument_meta_cache = {}
    service._auto_pilot_last_ticker_snapshot = {}
    service._auto_pilot_last_universe_stats = {}
    service._get_cycle_now_ts = Mock(return_value=now_ts)
    return service


def _ticker(
    symbol: str,
    *,
    turnover: float = 50_000_000,
    volume: float = 2_000_000,
    oi: float = 2_000_000,
    price: float = 1.0,
    move_pct: float = 0.02,
) -> dict:
    return {
        "symbol": symbol,
        "turnover24h": str(turnover),
        "volume24h": str(volume),
        "openInterestValue": str(oi),
        "lastPrice": str(price),
        "price24hPcnt": str(move_pct),
    }


def _instrument(
    symbol: str,
    now_ts: float,
    *,
    listing_days: float = 120,
    innovation: bool = False,
) -> dict:
    launch_ms = int((now_ts - (listing_days * 86400.0)) * 1000)
    instrument = {
        "symbol": symbol,
        "status": "Trading",
        "symbolType": "linear",
        "launchTime": str(launch_ms),
    }
    if innovation:
        instrument["innovation"] = "1"
    return instrument


def _instrument_catalog(*instruments: dict) -> dict:
    return {
        "success": True,
        "data": {
            "list": list(instruments),
            "nextPageCursor": "",
        },
    }


def test_auto_pilot_excludes_new_listing_symbols():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("NEWCOINUSDT", turnover=90_000_000),
                _ticker("ETHUSDT", turnover=80_000_000, price=3_000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("NEWCOINUSDT", now_ts, listing_days=3),
        _instrument("ETHUSDT", now_ts, listing_days=400),
    )

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    assert symbols == ["ETHUSDT"]


def test_auto_pilot_default_safe_mode_is_implicit_default():
    service = _make_service()

    settings = GridBotService._get_auto_pilot_filter_settings(service, {})

    assert settings["universe_mode"] == "default_safe"
    assert settings["strong_filters_enabled"] is True
    assert settings["exclude_innovation"] is True
    assert settings["exclude_new_listings"] is True


def test_auto_pilot_blacklist_overrides_liquid_symbol(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_SYMBOL_BLACKLIST",
        ("DOGEUSDT",),
    )
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_SYMBOL_BLACKLIST",
        ("DOGEUSDT",),
    )
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("DOGEUSDT", turnover=120_000_000, oi=8_000_000),
                _ticker("ETHUSDT", turnover=80_000_000, price=3_000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("DOGEUSDT", now_ts, listing_days=600),
        _instrument("ETHUSDT", now_ts, listing_days=400),
    )

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    assert symbols == ["ETHUSDT"]


def test_auto_pilot_quality_filter_rejects_illiquid_symbol():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("THINUSDT", turnover=4_000_000, oi=150_000),
                _ticker("ETHUSDT", turnover=75_000_000, oi=12_000_000, price=3_000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("THINUSDT", now_ts, listing_days=180),
        _instrument("ETHUSDT", now_ts, listing_days=500),
    )

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    assert symbols == ["ETHUSDT"]


def test_auto_pilot_volatility_cap_rejects_extreme_candidate():
    service = _make_service()

    filtered = GridBotService._filter_auto_pilot_scan_results(
        service,
        {},
        [
            {
                "symbol": "WILDUSDT",
                "atr_pct": 0.08,
                "price_change_24h_pct": 0.24,
                "price_velocity": 0.05,
                "volume_24h_usdt": 80_000_000,
            },
            {
                "symbol": "ETHUSDT",
                "atr_pct": 0.018,
                "price_change_24h_pct": 0.02,
                "price_velocity": 0.004,
                "volume_24h_usdt": 250_000_000,
            },
        ],
    )

    assert [candidate["symbol"] for candidate in filtered] == ["ETHUSDT"]
    assert filtered[0]["_auto_pilot_eligibility_status"] == "eligible_conservative"
    assert (
        service._auto_pilot_last_universe_stats["excluded"]["volatility"] == 1
    )


def test_auto_pilot_strong_filter_toggle_preserves_legacy_universe(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    service = _make_service()
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_STRONG_FILTERS_ENABLED",
        False,
    )
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_STRONG_FILTERS_ENABLED",
        False,
    )
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("BANANAXUSDT", turnover=40_000_000),
                _ticker("ETHUSDT", turnover=35_000_000, price=3_000),
            ]
        },
    }

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    assert symbols[:2] == ["BANANAXUSDT", "ETHUSDT"]


def test_auto_pilot_caps_filtered_universe_by_liquidity_proxy(monkeypatch):
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_MAX_SCAN_SYMBOLS",
        3,
    )
    # Distinct momentum values to exercise blended turnover+momentum sort
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("ETHUSDT", turnover=100_000_000, volume=10_000_000, oi=5_000_000, price=3_000, move_pct=0.01),
                _ticker("SOLUSDT", turnover=100_000_000, volume=18_000_000, oi=5_000_000, price=180, move_pct=0.04),
                _ticker("XRPUSDT", turnover=90_000_000, volume=22_000_000, oi=9_000_000, price=2.5, move_pct=0.02),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("ETHUSDT", now_ts, listing_days=500),
        _instrument("SOLUSDT", now_ts, listing_days=500),
        _instrument("XRPUSDT", now_ts, listing_days=500),
    )

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    # SOL wins: tied turnover rank with ETH but best momentum rank
    assert symbols == ["SOLUSDT", "ETHUSDT", "XRPUSDT"]
    assert service._auto_pilot_last_universe_stats["eligible_pre_scan"] == 3
    assert service._auto_pilot_last_universe_stats["scan_universe"] == 3


def test_auto_pilot_scan_cap_zero_preserves_full_filtered_universe(monkeypatch):
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_MAX_SCAN_SYMBOLS",
        0,
    )
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("SOLUSDT", turnover=95_000_000, oi=6_000_000, price=180),
                _ticker("ETHUSDT", turnover=90_000_000, oi=5_000_000, price=3_000),
                _ticker("XRPUSDT", turnover=85_000_000, oi=7_000_000, price=2.5),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("SOLUSDT", now_ts, listing_days=500),
        _instrument("ETHUSDT", now_ts, listing_days=500),
        _instrument("XRPUSDT", now_ts, listing_days=500),
    )

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    assert symbols == ["SOLUSDT", "ETHUSDT", "XRPUSDT"]
    assert service._auto_pilot_last_universe_stats["eligible_pre_scan"] == 3
    assert service._auto_pilot_last_universe_stats["scan_universe"] == 3


def test_auto_pilot_default_filters_drop_banana_variants_before_scan():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("BANANAS31USDT", turnover=95_000_000),
                _ticker("BANANAUSDT", turnover=94_000_000),
                _ticker("ETHUSDT", turnover=80_000_000, price=3_000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("BANANAS31USDT", now_ts, listing_days=180),
        _instrument("BANANAUSDT", now_ts, listing_days=180),
        _instrument("ETHUSDT", now_ts, listing_days=600),
    )
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}

    def _scan(symbols):
        assert symbols == ["ETHUSDT"]
        return [
            {
                "symbol": "ETHUSDT",
                "recommended_mode": "long",
                "recommended_profile": "normal",
                "recommended_range_mode": "dynamic",
                "recommended_grid_levels": 10,
                "recommended_leverage": 3,
                "suggested_range": {"lower": 2900.0, "upper": 3100.0},
                "neutral_score": 82.0,
                "mode_confidence": 0.75,
                "smart_score": 70.0,
                "entry_zone": {"score": 84.0, "verdict": "GOOD", "best_for": "long"},
                "atr_pct": 0.02,
                "price_change_24h_pct": 0.015,
                "price_velocity": 0.004,
                "volume_24h_usdt": 80_000_000,
            }
        ]

    service.neutral_scanner.scan.side_effect = _scan

    updated = GridBotService._auto_pilot_pick_symbol(service, {"id": "bot-1"})

    assert updated["symbol"] == "ETHUSDT"


def test_auto_pilot_excludes_innovation_metadata_symbols():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("TESTUSDT", turnover=65_000_000),
                _ticker("ETHUSDT", turnover=75_000_000, price=3_000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("TESTUSDT", now_ts, listing_days=300, innovation=True),
        _instrument("ETHUSDT", now_ts, listing_days=500),
    )

    symbols = GridBotService._get_auto_pilot_top_symbols(service, {})

    assert symbols == ["ETHUSDT"]


def test_auto_pilot_aggressive_full_relaxes_default_safe_pre_scan_exclusions():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("ETHUSDT", turnover=80_000_000, oi=7_000_000, price=3_000),
                _ticker("NEWCOINUSDT", turnover=4_000_000, oi=300_000),
                _ticker("TESTUSDT", turnover=3_000_000, oi=250_000),
                _ticker("BANANAS31USDT", turnover=2_000_000, oi=200_000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("ETHUSDT", now_ts, listing_days=500),
        _instrument("NEWCOINUSDT", now_ts, listing_days=3),
        _instrument("TESTUSDT", now_ts, listing_days=20, innovation=True),
        _instrument("BANANAS31USDT", now_ts, listing_days=5),
    )

    bot = {"auto_pilot_universe_mode": "aggressive_full"}
    symbols = GridBotService._get_auto_pilot_top_symbols(service, bot)

    assert symbols == ["ETHUSDT", "NEWCOINUSDT", "TESTUSDT", "BANANAS31USDT"]
    assert service._auto_pilot_last_universe_stats["universe_mode"] == "aggressive_full"
    assert bot["auto_pilot_universe_mode"] == "aggressive_full"
    assert "mode=aggressive_full" in bot["auto_pilot_universe_summary"]


def test_auto_pilot_aggressive_full_relaxes_default_safe_volatility_caps():
    service = _make_service()
    bot = {"auto_pilot_universe_mode": "aggressive_full"}

    filtered = GridBotService._filter_auto_pilot_scan_results(
        service,
        bot,
        [
            {
                "symbol": "WILDUSDT",
                "atr_pct": 0.08,
                "price_change_24h_pct": 0.24,
                "price_velocity": 0.05,
                "volume_24h_usdt": 8_000_000,
            },
            {
                "symbol": "ETHUSDT",
                "atr_pct": 0.018,
                "price_change_24h_pct": 0.02,
                "price_velocity": 0.004,
                "volume_24h_usdt": 250_000_000,
            },
        ],
    )

    assert [candidate["symbol"] for candidate in filtered] == ["WILDUSDT", "ETHUSDT"]
    assert bot["auto_pilot_universe_mode"] == "aggressive_full"
    assert "mode=aggressive_full" in bot["auto_pilot_universe_summary"]
