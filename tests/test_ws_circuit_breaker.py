"""Tests for WebSocket order circuit breaker in BybitClient."""

import time
import threading
from contextlib import contextmanager
from unittest.mock import Mock, patch

from services.bybit_client import BybitClient


@contextmanager
def _cb_config(threshold=3, cooldown=60, enabled=True):
    with patch(
        "config.strategy_config.WS_ORDER_CIRCUIT_BREAKER_ENABLED", enabled
    ), patch(
        "config.strategy_config.WS_ORDER_CIRCUIT_BREAKER_THRESHOLD", threshold
    ), patch(
        "config.strategy_config.WS_ORDER_CIRCUIT_BREAKER_COOLDOWN_SEC", cooldown
    ):
        yield


def _make_client() -> BybitClient:
    client = BybitClient.__new__(BybitClient)
    client._ws_order_consecutive_timeouts = 0
    client._ws_order_disabled_until = 0.0
    client.stream_service = Mock()
    client.stream_service.is_trade_ws_ready.return_value = True
    return client


def _make_latency_client() -> BybitClient:
    """Client with latency-stats fields initialised for diagnostics tests."""
    client = _make_client()
    client._recent_latencies = []
    client._max_latency_entries = 50
    client._consecutive_timeouts = 0
    client._latency_lock = threading.Lock()
    return client


def _ws_timeout_response():
    return {"error": "ws_timeout_after_send"}


def _ws_success_response(order_id="ord-123"):
    # Bybit WS returns retCode as string
    return {"retCode": "0", "data": {"orderId": order_id}}


def _ws_error_response(code=10001):
    return {"retCode": code}


def test_circuit_breaker_trips_after_threshold_consecutive_timeouts():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # 3 consecutive timeouts should trip the breaker
        for i in range(3):
            client.stream_service.send_trade_command.return_value = (
                _ws_timeout_response()
            )
            result = client._try_ws_create_order(body)
            assert result["error"] == "ws_timeout_after_send"
            assert result["ambiguous"] is True

        # After tripping, next call should return None (fall back to REST)
        result = client._try_ws_create_order(body)
        assert result is None


def test_circuit_breaker_resets_on_success():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # 2 timeouts (below threshold)
        for _ in range(2):
            client.stream_service.send_trade_command.return_value = (
                _ws_timeout_response()
            )
            client._try_ws_create_order(body)

        assert client._ws_order_consecutive_timeouts == 2

        # Success resets the counter
        client.stream_service.send_trade_command.return_value = (
            _ws_success_response()
        )
        result = client._try_ws_create_order(body)
        assert result["success"] is True
        assert client._ws_order_consecutive_timeouts == 0


def test_circuit_breaker_expires_after_cooldown():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # Trip the breaker
        for _ in range(3):
            client.stream_service.send_trade_command.return_value = (
                _ws_timeout_response()
            )
            client._try_ws_create_order(body)

        # Simulate cooldown expiry
        client._ws_order_disabled_until = time.time() - 1

        # Should try WS again
        client.stream_service.send_trade_command.return_value = (
            _ws_success_response()
        )
        result = client._try_ws_create_order(body)
        assert result["success"] is True
        assert client._ws_order_consecutive_timeouts == 0


def test_circuit_breaker_disabled_does_not_trip():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config(enabled=False):
        # Many timeouts — breaker should NOT trip
        for _ in range(10):
            client.stream_service.send_trade_command.return_value = (
                _ws_timeout_response()
            )
            result = client._try_ws_create_order(body)
            assert result["error"] == "ws_timeout_after_send"

        # Counter stays at 0 (not tracked when disabled)
        assert client._ws_order_consecutive_timeouts == 0
        assert client._ws_order_disabled_until == 0.0


def test_pre_send_failure_does_not_count_toward_circuit_breaker():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # Pre-send failures should fall back to REST without counting
        for error in ("ws_not_connected", "ws_not_available", "ws_send_failed"):
            client.stream_service.send_trade_command.return_value = {"error": error}
            result = client._try_ws_create_order(body)
            assert result is None

        assert client._ws_order_consecutive_timeouts == 0


def test_ws_error_code_does_not_count_toward_circuit_breaker():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # Explicit WS error codes fall back to REST without counting
        client.stream_service.send_trade_command.return_value = (
            _ws_error_response(10001)
        )
        result = client._try_ws_create_order(body)
        assert result is None
        assert client._ws_order_consecutive_timeouts == 0


def test_ambiguous_result_still_returned_even_when_breaker_trips():
    """The current ambiguous timeout must still be returned as ambiguous,
    even on the call that trips the breaker. Only FUTURE calls skip WS."""
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config(threshold=2):
        # Timeout #1
        client.stream_service.send_trade_command.return_value = (
            _ws_timeout_response()
        )
        result = client._try_ws_create_order(body)
        assert result["ambiguous"] is True

        # Timeout #2 — trips the breaker BUT must still return ambiguous
        result = client._try_ws_create_order(body)
        assert result["ambiguous"] is True
        assert result["error"] == "ws_timeout_after_send"

        # Now breaker is active — returns None
        result = client._try_ws_create_order(body)
        assert result is None


# ---------------------------------------------------------------------------
# C1: "ws_timeout" string path (stream service returns this, not
#     "ws_timeout_after_send")
# ---------------------------------------------------------------------------
def test_ws_timeout_string_counts_toward_circuit_breaker():
    """send_trade_command returns 'ws_timeout'; breaker must count it."""
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        for _ in range(3):
            client.stream_service.send_trade_command.return_value = {
                "error": "ws_timeout"
            }
            result = client._try_ws_create_order(body)
            assert result["ambiguous"] is True
            assert result["error"] == "ws_timeout_after_send"

        # Breaker tripped — next call returns None
        result = client._try_ws_create_order(body)
        assert result is None


# ---------------------------------------------------------------------------
# C2: Interleaved timeout / success / timeout / timeout
# ---------------------------------------------------------------------------
def test_interleaved_timeout_success_timeout_resets_counter():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # Timeout #1
        client.stream_service.send_trade_command.return_value = (
            _ws_timeout_response()
        )
        client._try_ws_create_order(body)
        assert client._ws_order_consecutive_timeouts == 1

        # Success — resets counter
        client.stream_service.send_trade_command.return_value = (
            _ws_success_response()
        )
        client._try_ws_create_order(body)
        assert client._ws_order_consecutive_timeouts == 0

        # Timeout #1 again, Timeout #2
        client.stream_service.send_trade_command.return_value = (
            _ws_timeout_response()
        )
        client._try_ws_create_order(body)
        client._try_ws_create_order(body)
        assert client._ws_order_consecutive_timeouts == 2

        # Not tripped yet — still returns ambiguous, not None
        client.stream_service.send_trade_command.return_value = (
            _ws_timeout_response()
        )
        result = client._try_ws_create_order(body)
        assert result["ambiguous"] is True

        # NOW tripped (3 consecutive) — next call returns None
        result = client._try_ws_create_order(body)
        assert result is None


# ---------------------------------------------------------------------------
# C3: Exception from send_trade_command falls back without counting
# ---------------------------------------------------------------------------
def test_exception_in_send_trade_command_does_not_count():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        client.stream_service.send_trade_command.side_effect = RuntimeError(
            "WS exploded"
        )
        result = client._try_ws_create_order(body)
        assert result is None
        assert client._ws_order_consecutive_timeouts == 0
        assert client._ws_order_disabled_until == 0.0


# ---------------------------------------------------------------------------
# C4: Cooldown expiry followed by immediate re-timeout
# ---------------------------------------------------------------------------
def test_cooldown_expiry_then_immediate_re_timeout_restarts_counter():
    client = _make_client()
    body = {"symbol": "BTCUSDT", "side": "Buy", "qty": "0.001"}

    with _cb_config():
        # Trip the breaker
        for _ in range(3):
            client.stream_service.send_trade_command.return_value = (
                _ws_timeout_response()
            )
            client._try_ws_create_order(body)

        # Counter was reset after trip
        assert client._ws_order_consecutive_timeouts == 0
        assert client._ws_order_disabled_until > time.time()

        # Simulate cooldown expiry
        client._ws_order_disabled_until = time.time() - 1

        # First call after expiry: another timeout — counter should be 1
        client.stream_service.send_trade_command.return_value = (
            _ws_timeout_response()
        )
        result = client._try_ws_create_order(body)
        assert result["ambiguous"] is True
        assert client._ws_order_consecutive_timeouts == 1

        # Needs 2 more to re-trip (threshold=3)
        client._try_ws_create_order(body)
        assert client._ws_order_consecutive_timeouts == 2

        # Third re-timeout trips again
        client._try_ws_create_order(body)
        assert client._ws_order_disabled_until > time.time()
        assert client._ws_order_consecutive_timeouts == 0


# ---------------------------------------------------------------------------
# Diagnostics: get_latency_stats exposes breaker state
# ---------------------------------------------------------------------------
def test_latency_stats_includes_breaker_fields_inactive():
    client = _make_latency_client()
    stats = client.get_latency_stats()

    assert stats["ws_circuit_breaker_active"] is False
    assert stats["ws_circuit_breaker_remaining_sec"] == 0.0
    assert stats["ws_order_consecutive_timeouts"] == 0


def test_latency_stats_includes_breaker_fields_active():
    client = _make_latency_client()
    client._ws_order_disabled_until = time.time() + 30
    client._ws_order_consecutive_timeouts = 0  # reset after trip

    stats = client.get_latency_stats()

    assert stats["ws_circuit_breaker_active"] is True
    assert stats["ws_circuit_breaker_remaining_sec"] > 0
    assert stats["ws_circuit_breaker_remaining_sec"] <= 30.0
