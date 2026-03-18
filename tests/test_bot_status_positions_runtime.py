from unittest.mock import MagicMock


from services.bot_status_service import BotStatusService


def _make_service():
    svc = object.__new__(BotStatusService)
    svc.position_service = MagicMock()
    svc.position_service.client = MagicMock()
    svc.position_service.normalize_position_row = MagicMock(
        side_effect=lambda row, account_equity=0.0: {
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "size": float(row.get("size") or 0.0),
            "entry_price": 100.0,
            "mark_price": 101.0,
            "unrealized_pnl": 1.25,
            "position_value": 125.0,
        }
    )
    svc._runtime_positions_cache = {}
    svc._last_runtime_cache_status = {"stale_data": False, "error": None}
    svc._last_runtime_positions_diagnostics = {}
    return svc


def test_get_runtime_positions_payload_records_stream_diagnostics():
    svc = _make_service()
    svc.position_service.client.stream_service = MagicMock()
    svc.position_service.client.stream_service.get_positions_fresh.return_value = {
        "success": True,
        "data": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "1.25",
                }
            ]
        },
    }

    payload = svc.get_runtime_positions_payload(skip_cache=False)
    diagnostics = svc.get_last_runtime_positions_diagnostics()

    assert payload["stale_data"] is False
    assert payload["positions"][0]["symbol"] == "BTCUSDT"
    assert diagnostics["path"] == "stream"
    assert diagnostics["fetch_ms"] >= 0.0
    assert diagnostics["normalize_ms"] >= 0.0
    assert diagnostics["position_count"] == 1
    assert diagnostics["stale_data"] is False


def test_get_runtime_positions_payload_records_cached_stale_path():
    svc = _make_service()
    svc.position_service.client.stream_service = MagicMock()
    svc.position_service.client.stream_service.get_positions_fresh.return_value = None
    svc._runtime_positions_cache = {
        "payload": {
            "positions": [{"symbol": "ETHUSDT"}],
            "summary": {"total_positions": 1},
            "error": None,
        },
        "cached_at": 1.0,
    }

    payload = svc.get_runtime_positions_payload(skip_cache=False)
    diagnostics = svc.get_last_runtime_positions_diagnostics()

    assert payload["stale_data"] is True
    assert diagnostics["path"] == "cached_stale"
    assert diagnostics["position_count"] == 1
    assert diagnostics["stale_data"] is True
