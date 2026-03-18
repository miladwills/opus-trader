from unittest.mock import MagicMock, patch


from services.bot_status_service import BotStatusService


def _make_service():
    svc = object.__new__(BotStatusService)
    svc.bot_storage = MagicMock()
    svc.position_service = MagicMock()
    svc.position_service.client = MagicMock()
    svc._live_open_orders_cache = {}
    svc._live_open_orders_all_cache = {}
    svc._live_open_orders_cache_ttl_seconds = 5
    svc._last_live_open_orders_diagnostics = {}
    return svc


def test_get_live_open_order_summary_by_symbol_uses_all_orders_fast_path():
    svc = _make_service()
    svc.position_service.client.stream_service = MagicMock()
    svc.position_service.client.stream_service.get_open_orders_fresh.return_value = None
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
    assert diagnostics["matched_order_row_count"] == 1
    assert diagnostics["stream_handoff_reason"] == "stream_query_failed"
    assert svc._live_open_orders_cache["BTCUSDT"]["orders"] == [
        {
            "symbol": "BTCUSDT",
            "reduceOnly": False,
        }
    ]
    assert svc._live_open_orders_cache["ETHUSDT"]["orders"] == []


def test_get_live_open_order_summary_by_symbol_falls_back_when_fast_path_is_unsafe():
    svc = _make_service()
    svc.position_service.client.stream_service = MagicMock()
    svc.position_service.client.stream_service.get_open_orders_fresh.return_value = None
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


def test_get_live_open_order_summary_by_symbol_uses_per_symbol_stream_when_complete():
    svc = _make_service()
    svc.position_service.client.stream_service = MagicMock()
    svc.position_service.client.stream_service.get_open_orders_fresh.side_effect = [
        {
            "success": True,
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "reduceOnly": False,
                    }
                ]
            },
        },
        {
            "success": True,
            "data": {
                "list": [],
            },
        },
    ]
    bots = [
        {"symbol": "BTCUSDT", "status": "running"},
        {"symbol": "ETHUSDT", "status": "paused"},
    ]

    summary = svc.get_live_open_order_summary_by_symbol(bots)
    diagnostics = svc.get_last_live_open_orders_diagnostics()

    svc.position_service.client.get_open_orders.assert_not_called()
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
    assert diagnostics["path"] == "per_symbol_stream"
    assert diagnostics["stream_hit_count"] == 2
    assert diagnostics["stream_symbol_miss_count"] == 0
    assert diagnostics["order_row_count"] == 1
    assert diagnostics["matched_order_row_count"] == 1
    assert diagnostics["stream_query_ms"] >= 0.0
    assert svc._live_open_orders_cache["BTCUSDT"]["orders"] == [
        {
            "symbol": "BTCUSDT",
            "reduceOnly": False,
        }
    ]
    assert svc._live_open_orders_cache["ETHUSDT"]["orders"] == []


def test_get_live_open_order_summary_by_symbol_reuses_fresh_all_orders_cache():
    svc = _make_service()
    svc.position_service.client.stream_service = MagicMock()
    svc.position_service.client.stream_service.get_open_orders_fresh.return_value = None
    svc.position_service.client.get_open_orders.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "reduceOnly": False,
                },
                {
                    "symbol": "ETHUSDT",
                    "reduceOnly": True,
                },
            ]
        },
    }
    bots = [
        {"symbol": "BTCUSDT", "status": "running"},
        {"symbol": "ETHUSDT", "status": "paused"},
    ]

    first_summary = svc.get_live_open_order_summary_by_symbol(bots)
    first_diagnostics = svc.get_last_live_open_orders_diagnostics()
    second_summary = svc.get_live_open_order_summary_by_symbol(bots)
    second_diagnostics = svc.get_last_live_open_orders_diagnostics()

    svc.position_service.client.get_open_orders.assert_called_once_with(
        limit=200,
        skip_cache=False,
    )
    assert first_summary == second_summary == {
        "BTCUSDT": {
            "open_order_count": 1,
            "reduce_only_count": 0,
            "entry_order_count": 1,
        },
        "ETHUSDT": {
            "open_order_count": 1,
            "reduce_only_count": 1,
            "entry_order_count": 0,
        },
    }
    assert first_diagnostics["path"] == "all_orders_client"
    assert second_diagnostics["path"] == "all_orders_cache"
    assert second_diagnostics["all_orders_cache_hit_count"] == 1
    assert second_diagnostics["all_orders_cache_age_ms"] is not None
    assert second_diagnostics["order_row_count"] == 2
    assert second_diagnostics["matched_order_row_count"] == 2
