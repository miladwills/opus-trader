"""
Tests for websocket-backed Bybit integrations.
"""

import os
import sys
import time
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bybit_client import BybitClient
from services.order_ownership_service import (
    OrderOwnershipService,
    build_order_ownership_snapshot,
)
from services.bybit_stream_service import BybitStreamService


def _build_mock_session():
    session = Mock()
    response = Mock()
    response.status_code = 200
    response.text = '{"retCode": 0, "result": {"list": []}}'
    response.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "50000",
                }
            ]
        },
    }
    session.get.return_value = response
    session.post.return_value = response
    return session


def test_bybit_client_prefers_stream_ticker_snapshot():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    stream_service = Mock()
    stream_service.get_ticker_response.return_value = {
        "success": True,
        "from_stream": True,
        "data": {"category": "linear", "list": [{"symbol": "BTCUSDT", "lastPrice": "50123"}]},
    }
    client.set_stream_service(stream_service)

    result = client.get_tickers("BTCUSDT")

    assert result["from_stream"] is True
    assert result["data"]["list"][0]["lastPrice"] == "50123"
    stream_service.ensure_symbol.assert_called_once_with("BTCUSDT")
    assert mock_session.get.call_count == 0


def test_bybit_client_falls_back_to_rest_when_stream_has_no_snapshot():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    stream_service = Mock()
    stream_service.get_ticker_response.return_value = None
    client.set_stream_service(stream_service)

    result = client.get_tickers("BTCUSDT")

    assert result["success"] is True
    assert mock_session.get.call_count == 1


def test_bybit_client_persists_order_ownership_snapshot_on_success(tmp_path):
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    ownership_service = OrderOwnershipService(str(tmp_path / "order_ownership.json"))
    client.set_order_ownership_service(ownership_service)
    client._run_order_command = Mock(
        return_value={
            "success": True,
            "data": {
                "orderId": "order-123",
                "orderLinkId": "cls:bot12345:068811370513MANL",
            },
        }
    )

    snapshot = build_order_ownership_snapshot(
        {
            "id": "bot-12345",
            "investment": 100.0,
            "leverage": 3,
            "mode": "long",
            "range_mode": "dynamic",
        },
        source="manual_close",
        action="manual_close",
        close_reason="MANL",
    )

    result = client.create_order(
        symbol="BTCUSDT",
        side="Sell",
        qty=0.01,
        order_type="Market",
        reduce_only=True,
        order_link_id="cls:bot12345:068811370513MANL",
        position_idx=2,
        qty_is_normalized=True,
        ownership_snapshot=snapshot,
    )

    assert result["success"] is True

    persisted = ownership_service.get_order_ownership(order_id="order-123")
    assert persisted is not None
    assert persisted["bot_id"] == "bot-12345"
    assert persisted["symbol"] == "BTCUSDT"
    assert persisted["side"] == "Sell"
    assert persisted["position_idx"] == 2
    assert persisted["reduce_only"] is True
    assert persisted["source"] == "manual_close"
    assert persisted["action"] == "manual_close"


def test_bybit_client_marks_reduce_only_zero_position_as_position_empty():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    client._run_order_command = Mock(
        return_value={
            "success": False,
            "error": "current position is zero, cannot fix reduce-only order qty",
            "retCode": 110017,
        }
    )
    client._invalidate_order_caches = Mock()
    client._mark_stream_open_orders_dirty = Mock()
    client._forget_recent_open_order_hints_for_symbol = Mock()

    result = client.create_order(
        symbol="BTCUSDT",
        side="Sell",
        qty=0.01,
        order_type="Market",
        reduce_only=True,
        order_link_id="cls:testbot:MANL",
        position_idx=2,
        qty_is_normalized=True,
    )

    assert result["success"] is False
    assert result["position_empty"] is True
    assert result["retCode"] == 110017
    client._invalidate_order_caches.assert_called_once()
    client._mark_stream_open_orders_dirty.assert_called_once_with("BTCUSDT")
    client._forget_recent_open_order_hints_for_symbol.assert_called_once_with(
        "BTCUSDT"
    )


def test_stream_service_maps_execution_order_link_id_from_order_stream():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    with stream_service._state_lock:
        stream_service._private_connected = True
        stream_service._private_authenticated = True

    stream_service._note_topic_message("order")
    stream_service._handle_order_message(
        {
            "topic": "order",
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "order-1",
                    "orderLinkId": "bot-slot-1",
                    "orderStatus": "New",
                }
            ],
        }
    )

    stream_service._note_topic_message("execution")
    stream_service._handle_execution_message(
        {
            "topic": "execution",
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "order-1",
                    "execId": "exec-1",
                    "execTime": "1000",
                }
            ],
        }
    )

    result = stream_service.get_executions_response(symbol="BTCUSDT", limit=10)

    assert result is not None
    assert result["success"] is True
    assert result["data"]["list"][0]["orderLinkId"] == "bot-slot-1"


def test_stream_dashboard_snapshot_can_skip_health_and_use_normalized_symbols():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )
    now = time.time()
    with stream_service._state_lock:
        stream_service._ticker_cache["BTCUSDT"] = {
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50000",
                "bid1Price": "49999",
                "ask1Price": "50001",
            },
            "received_at": now,
        }
        stream_service._topic_last_message_at["ticker"] = now

    snapshot = stream_service.get_dashboard_snapshot(
        ["BTCUSDT"],
        include_health=False,
        symbols_are_normalized=True,
    )

    assert snapshot["health"] == {}
    assert snapshot["symbols"] == ["BTCUSDT"]
    assert snapshot["fresh_symbol_count"] == 1
    assert snapshot["missing_symbols"] == []
    assert snapshot["ticker_topic_fresh"] is True
    assert snapshot["prices"]["BTCUSDT"]["lastPrice"] == "50000"


def test_stream_service_filters_closed_orders_from_open_order_snapshot():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    with stream_service._state_lock:
        stream_service._private_connected = True
        stream_service._private_authenticated = True

    stream_service.seed_open_orders_snapshot(
        "BTCUSDT",
        [
            {
                "symbol": "BTCUSDT",
                "orderId": "open-1",
                "orderStatus": "New",
            }
        ],
    )

    stream_service._note_topic_message("order")
    stream_service._handle_order_message(
        {
            "topic": "order",
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "open-1",
                    "orderStatus": "New",
                },
                {
                    "symbol": "BTCUSDT",
                    "orderId": "closed-1",
                    "orderStatus": "Filled",
                },
            ],
        }
    )

    result = stream_service.get_open_orders_response(symbol="BTCUSDT", limit=10)

    assert result is not None
    open_orders = result["data"]["list"]
    assert len(open_orders) == 1
    assert open_orders[0]["orderId"] == "open-1"


def test_stream_service_requires_bootstrapped_open_orders_before_using_order_cache():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    with stream_service._state_lock:
        stream_service._private_connected = True
        stream_service._private_authenticated = True

    stream_service._note_topic_message("order")
    stream_service._handle_order_message(
        {
            "topic": "order",
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "open-1",
                    "orderLinkId": "bot-slot-1",
                    "orderStatus": "New",
                }
            ],
        }
    )

    assert stream_service.get_open_orders_response(symbol="BTCUSDT", limit=10) is None

    stream_service.seed_open_orders_snapshot(
        "BTCUSDT",
        [
            {
                "symbol": "BTCUSDT",
                "orderId": "open-1",
                "orderLinkId": "bot-slot-1",
                "orderStatus": "New",
            }
        ],
    )

    result = stream_service.get_open_orders_response(symbol="BTCUSDT", limit=10)

    assert result is not None
    assert result["success"] is True
    assert result["data"]["list"][0]["orderId"] == "open-1"


def test_stream_service_reports_open_order_stream_miss_reason_for_stale_topic():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    with stream_service._state_lock:
        stream_service._private_connected = True
        stream_service._private_authenticated = True
        state = stream_service._private_topic_state["order"]
        state["bootstrapped"] = True
        state["epoch"] = stream_service._private_reconnect_epoch
        state["source"] = "rest_fallback"
        state["last_update_at"] = time.time() - 12.0
        stream_service._open_orders_bootstrapped_symbols.add("BTCUSDT")

    diagnostics = stream_service.get_open_orders_stream_diagnostics(symbol="BTCUSDT")

    assert diagnostics["miss_reason"] == "order_topic_stale"
    assert diagnostics["topic_fresh"] is False
    assert diagnostics["topic_bootstrapped"] is True
    assert diagnostics["symbol_bootstrapped"] is True
    assert diagnostics["topic_age_sec"] is not None
    assert diagnostics["topic_age_sec"] > diagnostics["topic_max_age_sec"]


def test_stream_service_ingests_kline_rows_and_emits_confirmed_event():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    stream_service._note_topic_message("kline")
    stream_service._handle_kline_message(
        {
            "topic": "kline.15.BTCUSDT",
            "data": [
                {
                    "start": 1_700_000_000_000,
                    "end": 1_700_000_899_999,
                    "open": "100",
                    "high": "110",
                    "low": "95",
                    "close": "108",
                    "volume": "1000",
                    "turnover": "108000",
                    "confirm": True,
                }
            ],
        }
    )

    result = stream_service.get_kline_response("BTCUSDT", "15", limit=1)

    assert result is not None
    assert result["success"] is True
    assert result["from_stream"] is True
    assert result["data"]["list"][0][4] == "108"

    events = stream_service.wait_for_events(0, timeout_sec=0.1)
    assert any(event.get("type") == "kline" for event in events)


def test_stream_service_rejects_stale_kline_snapshot():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    stream_service.seed_kline_snapshot(
        "BTCUSDT",
        "15",
        [
            {
                "open_time": time.gmtime(1_700_000_000),
                "start": 1_700_000_000_000,
                "open": 100,
                "high": 110,
                "low": 95,
                "close": 108,
                "volume": 1000,
            }
        ],
        received_at=time.time() - 600,
    )

    assert stream_service.get_kline_response("BTCUSDT", "15", limit=1) is None


def test_stream_service_merges_partial_ticker_deltas_and_preserves_last_price():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    stream_service._handle_ticker_message(
        {
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50000",
                "bid1Price": "49999",
                "ask1Price": "50001",
            },
        }
    )
    stream_service._handle_ticker_message(
        {
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "ask1Price": "50002",
            },
        }
    )

    snapshot = stream_service.get_ticker_snapshot("BTCUSDT", max_age_sec=60)

    assert snapshot is not None
    assert snapshot["lastPrice"] == "50000"
    assert snapshot["ask1Price"] == "50002"
    assert stream_service.get_last_price("BTCUSDT", max_age_sec=60) == 50000.0


def test_stream_service_prefers_fresher_orderbook_mid_metadata_and_emits_event():
    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )

    stream_service._handle_ticker_message(
        {
            "topic": "tickers.BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "50000",
                "bid1Price": "49999",
                "ask1Price": "50001",
            },
        }
    )
    seq_after_ticker = stream_service.get_latest_event_seq()
    time.sleep(0.01)
    stream_service._note_topic_message("orderbook")
    stream_service._handle_orderbook_message(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": int(time.time() * 1000),
            "data": {
                "u": 7,
                "b": [["50010", "3"], ["50009", "1"]],
                "a": [["50012", "2"], ["50013", "4"]],
            },
        }
    )

    metadata = stream_service.get_last_price_metadata("BTCUSDT", max_age_sec=60)
    events = stream_service.wait_for_events(seq_after_ticker, timeout_sec=0.1)

    assert metadata is not None
    assert metadata["source"] == "orderbook_mid"
    assert metadata["transport"] == "stream_orderbook"
    assert metadata["price"] == 50011.0
    assert stream_service.is_topic_fresh("orderbook", max_age_sec=60) is True
    assert any(
        event.get("type") == "orderbook"
        and (event.get("payload") or {}).get("mid_price") == 50011.0
        for event in events
    )


def test_bybit_client_routes_create_order_through_order_router():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    router = Mock()
    router.execute.side_effect = lambda symbol, action, callback: callback()
    client.set_order_router(router)

    with patch.object(
        client,
        "_request",
        return_value={"success": True, "retCode": 0, "data": {"orderId": "123"}},
    ):
        result = client.create_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=1.0,
            order_type="Market",
            qty_is_normalized=True,
        )

    assert result["success"] is True
    router.execute.assert_called_once()
    assert router.execute.call_args[0][:2] == ("BTCUSDT", "create_order")


def test_bybit_client_seeds_open_order_stream_snapshot_from_rest_fallback():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    stream_service = BybitStreamService(
        api_key="key",
        api_secret="secret",
        base_url="https://api.bybit.com",
        owner_name="test",
    )
    with stream_service._state_lock:
        stream_service._private_connected = True
        stream_service._private_authenticated = True
    stream_service._note_topic_message("order")
    client.set_stream_service(stream_service)

    open_orders_resp = {
        "success": True,
        "data": {
            "category": "linear",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "orderId": "open-1",
                    "orderLinkId": "bot-slot-1",
                    "orderStatus": "New",
                }
            ],
        },
    }
    with patch.object(client, "_request", return_value=open_orders_resp) as request_mock:
        first = client.get_open_orders("BTCUSDT", limit=10)
        second = client.get_open_orders("BTCUSDT", limit=10)

    assert first["success"] is True
    assert second["from_stream"] is True
    assert request_mock.call_count == 1


def test_bybit_client_merges_recent_limit_order_hints_into_open_orders():
    mock_session = _build_mock_session()
    with patch("services.bybit_client.requests.Session", return_value=mock_session):
        client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
        client.session = mock_session

    responses = [
        {"success": True, "data": {"orderId": "open-1"}},
        {"success": True, "data": {"category": "linear", "list": []}},
    ]

    with patch.object(client, "_request", side_effect=responses):
        create_result = client.create_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=1.0,
            order_type="Limit",
            price=50000.0,
            order_link_id="bot-slot-1",
            qty_is_normalized=True,
        )
        open_orders = client.get_open_orders("BTCUSDT", limit=10, skip_cache=True)

    assert create_result["success"] is True
    assert open_orders["success"] is True
    rows = open_orders["data"]["list"]
    assert len(rows) == 1
    assert rows[0]["orderId"] == "open-1"
    assert rows[0]["orderLinkId"] == "bot-slot-1"
    assert rows[0]["price"] == "50000.0"
