from unittest.mock import MagicMock, patch


from services.bot_status_service import BotStatusService


def _make_service():
    svc = object.__new__(BotStatusService)
    svc.bot_storage = MagicMock()
    svc.position_service = MagicMock()
    svc.position_service.client = MagicMock()
    svc._live_open_orders_cache = {}
    svc._live_open_orders_cache_ttl_seconds = 5
    svc._last_live_open_orders_diagnostics = {}
    return svc


def test_get_live_open_order_summary_by_symbol_uses_all_orders_fast_path():
    svc = _make_service()
    svc.position_service.client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "reduceOnly": False,
                },
                {
                    "symbol": "XRPUSDT",
                    "reduceOnly": True,
                },
            ]
        },
    }
    bots = [
        {"symbol": "BTCUSDT", "status": "running"},
        {"symbol": "ETHUSDT", "status": "paused"},
        {"symbol": "Auto-Pilot", "status": "running"},
    ]

    summary = svc.get_live_open_order_summary_by_symbol(bots)
    diagnostics = svc.get_last_live_open_orders_diagnostics()

    svc.position_service.client.get_open_orders.assert_called_once_with(
        limit=200,
        skip_cache=False,
    )
    assert summary == {
        "BTCUSDT": {
            "open_order_count": 1,
            "reduce_only_count": 0,
            "entry_order_count": 1,
        },
        "ETHUSDT": {
            "open_order_count": 0,
            "reduce_only_count": 0,
            "entry_order_count": 0,
        },
    }
    assert diagnostics["path"] == "all_orders_client"
    assert diagnostics["symbol_count"] == 2
    assert diagnostics["order_row_count"] == 2
    assert diagnostics["client_query_ms"] >= 0.0
    assert diagnostics["shaping_ms"] >= 0.0


def test_get_live_open_order_summary_by_symbol_falls_back_when_fast_path_is_unsafe():
    svc = _make_service()
    svc.position_service.client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [{"symbol": "BTCUSDT", "reduceOnly": False}] * 200,
        },
    }
    bots = [
        {"symbol": "BTCUSDT", "status": "running"},
        {"symbol": "ETHUSDT", "status": "paused"},
    ]
    with patch.object(
        svc,
        "_build_live_open_orders_by_symbol",
        return_value={
            "BTCUSDT": [{"reduceOnly": True}],
            "ETHUSDT": [],
        },
    ) as mock_build:
        summary = svc.get_live_open_order_summary_by_symbol(bots)

    diagnostics = svc.get_last_live_open_orders_diagnostics()

    mock_build.assert_called_once()
    assert summary == {
        "BTCUSDT": {
            "open_order_count": 1,
            "reduce_only_count": 1,
            "entry_order_count": 0,
        },
        "ETHUSDT": {
            "open_order_count": 0,
            "reduce_only_count": 0,
            "entry_order_count": 0,
        },
    }
    assert diagnostics["path"] == "per_symbol_fallback"
    assert diagnostics["fallback_reason"] == "all_orders_limit_reached"
    assert diagnostics["fallback_build_ms"] >= 0.0
