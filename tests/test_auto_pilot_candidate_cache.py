from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

import services.grid_bot_service as grid_bot_service_module
from services.grid_bot_service import GridBotService


def _make_service(now_ts: float = 1_700_000_000.0) -> GridBotService:
    service = GridBotService.__new__(GridBotService)
    service.client = Mock()
    service.client._get_now_ts.return_value = now_ts
    service.neutral_scanner = Mock()
    service.bot_storage = Mock()
    service._auto_pilot_instrument_meta_cache = {}
    service._auto_pilot_last_ticker_snapshot = {}
    service._auto_pilot_last_universe_stats = {}
    service.auto_pilot_candidate_cache_service = None
    service._get_cycle_now_ts = Mock(return_value=now_ts)
    service._refresh_auto_pilot_loss_budget_state = Mock(return_value={"status": "healthy"})
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


def _candidate(symbol: str, score: float) -> dict:
    return {
        "symbol": symbol,
        "recommended_mode": "neutral_classic_bybit",
        "recommended_profile": "normal",
        "recommended_range_mode": "fixed",
        "recommended_grid_levels": 8,
        "recommended_leverage": 3,
        "suggested_range": {"lower": 10.0, "upper": 12.0},
        "neutral_score": score,
        "_auto_pilot_score": score,
        "_auto_pilot_rank_reasons": [f"score={score:.1f}"],
        "_auto_pilot_eligibility_status": "eligible_conservative",
    }


def test_candidate_cache_refresh_populates_ranked_candidates(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_CANDIDATE_CACHE_MAX_ITEMS",
        2,
    )
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_CANDIDATE_CACHE_MAX_ITEMS",
        2,
    )
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("SOLUSDT", turnover=90_000_000, oi=6_000_000, price=180),
                _ticker("ETHUSDT", turnover=80_000_000, oi=7_000_000, price=3000),
                _ticker("XRPUSDT", turnover=75_000_000, oi=8_000_000, price=2.5),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("SOLUSDT", now_ts, listing_days=500),
        _instrument("ETHUSDT", now_ts, listing_days=500),
        _instrument("XRPUSDT", now_ts, listing_days=500),
    )
    service.neutral_scanner.scan.return_value = [
        {
            **_candidate("SOLUSDT", 90.0),
            "entry_zone": {"score": 88.0, "verdict": "GOOD", "best_for": "neutral_classic"},
        },
        {
            **_candidate("ETHUSDT", 86.0),
            "entry_zone": {"score": 82.0, "verdict": "GOOD", "best_for": "neutral_classic"},
        },
        {
            **_candidate("XRPUSDT", 82.0),
            "entry_zone": {"score": 79.0, "verdict": "GOOD", "best_for": "neutral_classic"},
        },
    ]

    snapshot = GridBotService._prepare_auto_pilot_candidate_cache(
        service,
        {},
        reason="background",
        force=True,
    )

    assert snapshot["candidate_count"] == 2
    assert snapshot["scan_universe"] == 3
    assert [candidate["symbol"] for candidate in snapshot["candidates"]] == [
        "SOLUSDT",
        "ETHUSDT",
    ]
    assert snapshot["candidates"][0]["_auto_pilot_cached_at"] is not None


def test_fresh_candidate_cache_is_reused_by_pick_path():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    service.client.set_margin_mode.return_value = {"success": True}
    service.client.set_leverage.return_value = {"success": True}
    service.neutral_scanner.scan.side_effect = AssertionError("live scan should not run")
    cache_service = GridBotService._get_auto_pilot_candidate_cache_service(service)
    cache_service.store(
        candidates=[_candidate("KITEUSDT", 76.2)],
        source="background",
        scan_universe=5,
        now_ts=now_ts,
        prepared_at=datetime.now(timezone.utc).isoformat(),
    )

    updated = GridBotService._auto_pilot_pick_symbol(service, {"id": "bot-1"})

    assert updated["symbol"] == "KITEUSDT"
    assert updated["auto_pilot_candidate_source"] == "cache"
    assert updated["auto_pilot_pick_status"] == "selected"
    service.client.set_margin_mode.assert_called_once_with(
        "KITEUSDT", "ISOLATED_MARGIN"
    )


def test_stale_candidate_cache_falls_back_to_live_scan():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    cache_service = GridBotService._get_auto_pilot_candidate_cache_service(service)
    cache_service.store(
        candidates=[_candidate("STALEUSDT", 70.0)],
        source="background",
        scan_universe=1,
        now_ts=now_ts - 600,
        prepared_at=datetime.now(timezone.utc).isoformat(),
    )
    service._scan_auto_pilot_candidates_live = Mock(
        return_value=([_candidate("FRESHUSDT", 88.0)], 3)
    )

    bot = {}
    ranked = GridBotService._get_ranked_auto_pilot_candidates(service, bot, reason="rotation")

    assert [candidate["symbol"] for candidate in ranked] == ["FRESHUSDT"]
    assert bot["_auto_pilot_candidate_source_hint"] == "live"
    service._scan_auto_pilot_candidates_live.assert_called_once()


def test_candidate_cache_refresh_respects_strong_filters_and_scan_cap(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_MAX_SCAN_SYMBOLS",
        1,
    )
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_MAX_SCAN_SYMBOLS",
        1,
    )
    service.client.get_tickers.return_value = {
        "success": True,
        "data": {
            "list": [
                _ticker("BANANAS31USDT", turnover=95_000_000, oi=9_000_000),
                _ticker("SOLUSDT", turnover=90_000_000, oi=8_000_000, price=180),
                _ticker("ETHUSDT", turnover=80_000_000, oi=7_000_000, price=3000),
            ]
        },
    }
    service.client.get_instruments_info.return_value = _instrument_catalog(
        _instrument("BANANAS31USDT", now_ts, listing_days=500),
        _instrument("SOLUSDT", now_ts, listing_days=500),
        _instrument("ETHUSDT", now_ts, listing_days=500),
    )
    service.neutral_scanner.scan.return_value = [
        {
            **_candidate("SOLUSDT", 88.0),
            "entry_zone": {"score": 85.0, "verdict": "GOOD", "best_for": "neutral_classic"},
        }
    ]

    snapshot = GridBotService._prepare_auto_pilot_candidate_cache(
        service,
        {},
        reason="background",
        force=True,
    )

    assert service.neutral_scanner.scan.call_args.args[0] == ["SOLUSDT"]
    assert snapshot["scan_universe"] == 1
    assert [candidate["symbol"] for candidate in snapshot["candidates"]] == ["SOLUSDT"]


def test_disabling_candidate_cache_preserves_live_scan_behavior(monkeypatch):
    import services.auto_pilot_mixin as auto_pilot_mixin_module
    service = _make_service()
    monkeypatch.setattr(
        grid_bot_service_module,
        "AUTO_PILOT_CANDIDATE_CACHE_ENABLED",
        False,
    )
    monkeypatch.setattr(
        auto_pilot_mixin_module,
        "AUTO_PILOT_CANDIDATE_CACHE_ENABLED",
        False,
    )
    cache_service = GridBotService._get_auto_pilot_candidate_cache_service(service)
    cache_service.store(
        candidates=[_candidate("CACHEDUSDT", 91.0)],
        source="background",
        scan_universe=1,
        now_ts=1_700_000_000.0,
        prepared_at=datetime.now(timezone.utc).isoformat(),
    )
    service._scan_auto_pilot_candidates_live = Mock(
        return_value=([_candidate("LIVEUSDT", 84.0)], 2)
    )

    ranked = GridBotService._get_ranked_auto_pilot_candidates(
        service,
        {},
        reason="pick",
    )

    assert [candidate["symbol"] for candidate in ranked] == ["LIVEUSDT"]
    service._scan_auto_pilot_candidates_live.assert_called_once()


def test_candidate_cache_is_isolated_by_universe_mode():
    now_ts = 1_700_000_000.0
    service = _make_service(now_ts)
    default_cache = GridBotService._get_auto_pilot_candidate_cache_service(service, {})
    default_cache.store(
        candidates=[_candidate("SAFEONLYUSDT", 91.0)],
        source="background",
        scan_universe=1,
        now_ts=now_ts,
        prepared_at=datetime.now(timezone.utc).isoformat(),
    )
    service._scan_auto_pilot_candidates_live = Mock(
        return_value=([_candidate("AGGRUSDT", 84.0)], 2)
    )

    ranked = GridBotService._get_ranked_auto_pilot_candidates(
        service,
        {"auto_pilot_universe_mode": "aggressive_full"},
        reason="pick",
    )

    assert [candidate["symbol"] for candidate in ranked] == ["AGGRUSDT"]
    service._scan_auto_pilot_candidates_live.assert_called_once()
