from services.bot_status_service import BotStatusService


def make_service():
    service = BotStatusService.__new__(BotStatusService)
    service.neutral_scanner = None
    service.scanner_cache_ttl_seconds = 20
    service._scanner_cache = {}
    return service


def test_enrich_bot_prefers_learned_scalp_opening_cap():
    service = make_service()
    bot = {
        "id": "bot-1",
        "symbol": "RIVERUSDT",
        "mode": "scalp_pnl",
        "status": "running",
        "grid_count": 17,
        "runtime_open_order_cap_total": 17,
        "volatility_derisk_open_cap_total": 17,
        "scalp_learned_opening_order_cap": 14,
        "scalp_learned_opening_cap_reason": "insufficient_margin",
        "entry_orders_open": 14,
        "exit_orders_open": 0,
        "investment": 20,
        "leverage": 10,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["effective_opening_order_cap"] == 14
    assert enriched["effective_opening_order_cap_reason"] == "insufficient_margin"
    assert enriched["entry_orders_open"] == 14


def test_enrich_bot_falls_back_to_runtime_or_grid_cap():
    service = make_service()
    bot = {
        "id": "bot-2",
        "symbol": "TESTUSDT",
        "mode": "scalp_pnl",
        "status": "running",
        "grid_count": 25,
        "runtime_open_order_cap_total": 18,
        "volatility_derisk_open_cap_total": 18,
        "entry_orders_open": 10,
        "exit_orders_open": 0,
        "investment": 20,
        "leverage": 10,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
    )

    assert enriched["effective_opening_order_cap"] == 18
    assert enriched["effective_opening_order_cap_reason"] is None


def test_enrich_bot_exposes_scanner_recommendation_fields():
    service = make_service()
    bot = {
        "id": "bot-3",
        "symbol": "RIVERUSDT",
        "mode": "long",
        "range_mode": "dynamic",
        "status": "running",
        "grid_count": 12,
        "investment": 20,
        "leverage": 5,
    }

    enriched = service._enrich_bot(
        bot=bot,
        position_lookup={},
        symbol_pnl_lookup={},
        bot_pnl_lookup={},
        running_bot_ids_by_symbol={},
        scanner_lookup={
            "RIVERUSDT": {
                "recommended_mode": "short",
                "recommended_range_mode": "dynamic",
                "recommended_profile": "normal",
                "regime": "trending",
                "trend": "downtrend",
                "updated_at": "2026-03-06T18:00:00+00:00",
            }
        },
    )

    assert enriched["scanner_recommended_mode"] == "short"
    assert enriched["scanner_recommended_range_mode"] == "dynamic"
    assert enriched["scanner_recommendation_differs"] is True
    assert enriched["scanner_recommendation_regime"] == "trending"


def test_scanner_recommendation_lookup_uses_cache():
    class FakeScanner:
        def __init__(self):
            self.calls = 0

        def scan(self, symbols):
            self.calls += 1
            return [
                {
                    "symbol": symbols[0],
                    "recommended_mode": "neutral",
                    "recommended_range_mode": "dynamic",
                    "recommended_profile": "normal",
                    "regime": "choppy",
                    "trend": "neutral",
                }
            ]

    service = make_service()
    service.neutral_scanner = FakeScanner()
    bots = [{"symbol": "RIVERUSDT", "status": "running"}]

    first = service._get_scanner_recommendation_lookup(bots)
    second = service._get_scanner_recommendation_lookup(bots)

    assert first["RIVERUSDT"]["recommended_mode"] == "neutral"
    assert second["RIVERUSDT"]["recommended_range_mode"] == "dynamic"
    assert service.neutral_scanner.calls == 1


def test_scanner_recommendation_lookup_skips_auto_pilot_placeholder():
    class FakeScanner:
        def __init__(self):
            self.calls = 0

        def scan(self, symbols):
            self.calls += 1
            return []

    service = make_service()
    service.neutral_scanner = FakeScanner()

    lookup = service._get_scanner_recommendation_lookup(
        [{"symbol": "Auto-Pilot", "status": "running"}]
    )

    assert lookup == {}
    assert service.neutral_scanner.calls == 0
