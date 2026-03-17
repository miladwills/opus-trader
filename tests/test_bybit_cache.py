"""
Tests for Bybit client micro-caching and connection pooling.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bybit_client import MicroCache, BybitClient, CACHE_TTL_CONFIG


class TestMicroCache:
    """Tests for the MicroCache class."""

    def test_cache_miss_on_empty(self):
        """Empty cache should return None."""
        cache = MicroCache()
        result = cache.get("/v5/market/tickers", {"symbol": "BTCUSDT"})
        assert result is None

    def test_cache_set_and_get(self):
        """Should be able to store and retrieve values."""
        cache = MicroCache()
        test_data = {"success": True, "data": {"price": 50000}}

        cache.set("/v5/market/tickers", {"symbol": "BTCUSDT"}, test_data)
        result = cache.get("/v5/market/tickers", {"symbol": "BTCUSDT"})

        assert result == test_data

    def test_cache_expiration(self):
        """Cache entries should expire after TTL."""
        cache = MicroCache()
        test_data = {"success": True, "data": {"price": 50000}}

        # Set with very short TTL (funding rate has 30s TTL in config)
        with patch.dict(CACHE_TTL_CONFIG, {"/v5/test/endpoint": 0.01}):
            cache.set("/v5/test/endpoint", None, test_data)

            # Should exist immediately
            result = cache.get("/v5/test/endpoint", None)
            assert result == test_data

            # Wait for expiration
            time.sleep(0.02)

            # Should be expired now
            result = cache.get("/v5/test/endpoint", None)
            assert result is None

    def test_cache_different_params(self):
        """Different params should have different cache entries."""
        cache = MicroCache()
        btc_data = {"success": True, "data": {"symbol": "BTCUSDT"}}
        eth_data = {"success": True, "data": {"symbol": "ETHUSDT"}}

        cache.set("/v5/market/tickers", {"symbol": "BTCUSDT"}, btc_data)
        cache.set("/v5/market/tickers", {"symbol": "ETHUSDT"}, eth_data)

        btc_result = cache.get("/v5/market/tickers", {"symbol": "BTCUSDT"})
        eth_result = cache.get("/v5/market/tickers", {"symbol": "ETHUSDT"})

        assert btc_result == btc_data
        assert eth_result == eth_data

    def test_cache_only_stores_success(self):
        """Should only cache successful responses."""
        cache = MicroCache()
        error_data = {"success": False, "error": "rate_limit"}

        cache.set("/v5/market/tickers", None, error_data)
        result = cache.get("/v5/market/tickers", None)

        assert result is None  # Not cached

    def test_cache_invalidate_specific(self):
        """Should invalidate a specific cache entry."""
        cache = MicroCache()
        test_data = {"success": True, "data": {"price": 50000}}

        cache.set("/v5/market/tickers", {"symbol": "BTCUSDT"}, test_data)
        cache.invalidate("/v5/market/tickers", {"symbol": "BTCUSDT"})

        result = cache.get("/v5/market/tickers", {"symbol": "BTCUSDT"})
        assert result is None

    def test_cache_invalidate_path(self):
        """Should invalidate all entries for a path."""
        cache = MicroCache()
        btc_data = {"success": True, "data": {"symbol": "BTCUSDT"}}
        eth_data = {"success": True, "data": {"symbol": "ETHUSDT"}}

        cache.set("/v5/market/tickers", {"symbol": "BTCUSDT"}, btc_data)
        cache.set("/v5/market/tickers", {"symbol": "ETHUSDT"}, eth_data)

        cache.invalidate_path("/v5/market/tickers")

        assert cache.get("/v5/market/tickers", {"symbol": "BTCUSDT"}) is None
        assert cache.get("/v5/market/tickers", {"symbol": "ETHUSDT"}) is None

    def test_cache_clear(self):
        """Should clear all entries."""
        cache = MicroCache()
        cache.set("/v5/market/tickers", None, {"success": True})
        cache.set("/v5/position/list", None, {"success": True})

        cache.clear()
        stats = cache.get_stats()

        assert stats["size"] == 0

    def test_cache_stats(self):
        """Should track hits and misses."""
        cache = MicroCache()
        test_data = {"success": True, "data": {}}

        # Miss
        cache.get("/v5/test", None)

        # Set
        cache.set("/v5/test", None, test_data)

        # Hit
        cache.get("/v5/test", None)
        cache.get("/v5/test", None)

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate_pct"] == pytest.approx(66.7, rel=0.1)

    def test_cache_lru_eviction(self):
        """Should evict oldest entries when full."""
        cache = MicroCache(max_size=3)

        # Fill cache
        for i in range(3):
            cache.set(f"/v5/test/{i}", None, {"success": True, "id": i})
            time.sleep(0.001)  # Ensure different timestamps

        # All entries should exist
        assert cache.get("/v5/test/0", None) is not None
        assert cache.get("/v5/test/1", None) is not None
        assert cache.get("/v5/test/2", None) is not None

        # Add one more - should trigger eviction
        cache.set("/v5/test/3", None, {"success": True, "id": 3})

        # Newest entries should remain
        assert cache.get("/v5/test/3", None) is not None

        # Cache size should be at max or below
        stats = cache.get_stats()
        assert stats["size"] <= 3


class TestBybitClientCache:
    """Tests for BybitClient caching behavior."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for testing."""
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.text = '{"retCode": 0, "result": {"list": []}}'
        response.json.return_value = {"retCode": 0, "result": {"list": []}}
        session.get.return_value = response
        session.post.return_value = response
        return session

    @pytest.fixture
    def client(self, mock_session):
        """Create a BybitClient with mocked session."""
        with patch('services.bybit_client.requests.Session', return_value=mock_session):
            client = BybitClient("test_key", "test_secret", "https://api.bybit.com")
            # Replace session with our mock
            client.session = mock_session
            return client

    def test_get_request_uses_cache(self, client, mock_session):
        """GET requests should be cached."""
        # First call - should hit API
        client.get_tickers("BTCUSDT")
        assert mock_session.get.call_count == 1

        # Second call - should use cache
        client.get_tickers("BTCUSDT")
        assert mock_session.get.call_count == 1  # No additional API call

    def test_cache_disabled_skips_cache(self, client, mock_session):
        """Should skip cache when disabled."""
        # First call
        client.get_tickers("BTCUSDT")
        assert mock_session.get.call_count == 1

        # Disable cache
        client.set_cache_enabled(False)

        # Second call - should hit API
        client.get_tickers("BTCUSDT")
        assert mock_session.get.call_count == 2

    def test_post_invalidates_cache(self, client, mock_session):
        """POST operations should invalidate related caches."""
        # Pre-populate cache
        client.get_positions()
        assert mock_session.get.call_count == 1

        # Create order (POST)
        client.create_order("BTCUSDT", "Buy", 0.001)

        # Position cache should be invalidated
        # Next get_positions should hit API again
        client.get_positions()
        assert mock_session.get.call_count == 2

    def test_cancel_invalidates_cache(self, client, mock_session):
        """Cancel operations should invalidate caches."""
        # Pre-populate cache
        client.get_positions()
        assert mock_session.get.call_count == 1

        # Cancel all orders (POST)
        client.cancel_all_orders("BTCUSDT")

        # Position cache should be invalidated
        client.get_positions()
        assert mock_session.get.call_count == 2

    def test_ambiguous_create_order_invalidates_caches_and_marks_dirty(self, client, caplog):
        client._run_order_command = Mock(
            return_value={
                "success": None,
                "status": "in_flight",
                "error": "order_router_timeout",
                "retCode": -2,
                "retry_safe": False,
            }
        )
        client._invalidate_order_caches = Mock()
        client._mark_stream_open_orders_dirty = Mock()
        client._mark_stream_positions_dirty = Mock()
        client._mark_stream_executions_dirty = Mock()
        client._forget_recent_open_order_hints_for_symbol = Mock()

        with caplog.at_level("WARNING"):
            result = client.create_order(
                "BTCUSDT",
                "Buy",
                0.001,
                qty_is_normalized=True,
            )

        assert result["success"] is None
        assert result["cache_invalidated"] is True
        assert result["cache_invalidation_reason"] == "ambiguous_order_action"
        client._invalidate_order_caches.assert_called_once()
        client._mark_stream_open_orders_dirty.assert_called_once_with("BTCUSDT")
        client._mark_stream_positions_dirty.assert_called_once_with()
        client._mark_stream_executions_dirty.assert_called_once_with()
        client._forget_recent_open_order_hints_for_symbol.assert_called_once_with(
            "BTCUSDT"
        )
        assert "ORDER_STATE_INVALIDATED symbol=BTCUSDT action=create_order" in caplog.text

    def test_health_check_uses_receive_edge_offset_to_avoid_future_skew(self, client, mock_session):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "retCode": 0,
            "result": {"timeNano": "103500000000"},
        }
        mock_session.get.return_value = response

        with patch("services.bybit_client.logger.info"), patch(
            "services.bybit_client.time.time", side_effect=[100.0, 104.0]
        ):
            result = client.health_check()

        assert result["healthy"] is True
        assert result["offset_ms"] == -500
        assert client._time_offset_ms == -500

    def test_extract_recv_window_error_details(self):
        details = BybitClient._extract_recv_window_error_details(
            "invalid request, please check your server timestamp or recv_window param: "
            "req_timestamp[1773773230612],server_timestamp[1773773229002],recv_window[5000]"
        )

        assert details == {
            "request_timestamp_ms": 1773773230612,
            "server_timestamp_ms": 1773773229002,
            "recv_window_ms": 5000,
            "skew_ms": 1610,
        }

    def test_request_resyncs_and_retries_recv_window_error(self, client, mock_session, caplog):
        error_response = Mock()
        error_response.status_code = 200
        error_response.text = (
            '{"retCode":10002,"retMsg":"invalid request, please check your server '
            'timestamp or recv_window param: '
            'req_timestamp[1773773230612],server_timestamp[1773773229002],recv_window[5000]"}'
        )
        error_response.json.return_value = {
            "retCode": 10002,
            "retMsg": (
                "invalid request, please check your server timestamp or recv_window param: "
                "req_timestamp[1773773230612],server_timestamp[1773773229002],recv_window[5000]"
            ),
        }
        success_response = Mock()
        success_response.status_code = 200
        success_response.text = '{"retCode":0,"result":{"list":[]}}'
        success_response.json.return_value = {"retCode": 0, "result": {"list": []}}
        mock_session.get.side_effect = [error_response, success_response]

        def _health_check():
            client._time_offset_ms = -1700
            return {"healthy": True, "offset_ms": -1700, "latency_ms": 210.5}

        client.health_check = Mock(side_effect=_health_check)

        with caplog.at_level("INFO"):
            result = client._request(
                "GET",
                "/v5/position/list",
                params={"category": "linear", "settleCoin": "USDT"},
                skip_cache=True,
            )

        assert result["success"] is True
        client.health_check.assert_called_once()
        assert mock_session.get.call_count == 2
        assert "BYBIT_TIME_RESYNC reason=recv_window" in caplog.text
        assert "req_timestamp_ms=1773773230612" in caplog.text
        assert "server_timestamp_ms=1773773229002" in caplog.text
        assert "skew_ms=1610" in caplog.text
        assert "sync_latency_ms=210.5" in caplog.text

    def test_request_does_not_retry_recv_window_error_when_resync_fails(self, client, mock_session):
        error_response = Mock()
        error_response.status_code = 200
        error_response.text = (
            '{"retCode":10002,"retMsg":"invalid request, please check your server '
            'timestamp or recv_window param: '
            'req_timestamp[1773773230612],server_timestamp[1773773229002],recv_window[5000]"}'
        )
        error_response.json.return_value = {
            "retCode": 10002,
            "retMsg": (
                "invalid request, please check your server timestamp or recv_window param: "
                "req_timestamp[1773773230612],server_timestamp[1773773229002],recv_window[5000]"
            ),
        }
        mock_session.get.return_value = error_response
        client.health_check = Mock(return_value={"healthy": False, "error": "sync_failed"})

        result = client._request(
            "GET",
            "/v5/position/list",
            params={"category": "linear", "settleCoin": "USDT"},
            skip_cache=True,
        )

        assert result["success"] is False
        assert result["retCode"] == 10002
        client.health_check.assert_called_once()
        assert mock_session.get.call_count == 1

    def test_ambiguous_cancel_all_orders_invalidates_caches_and_clears_hints(self, client):
        client._run_order_command = Mock(
            return_value={
                "success": None,
                "status": "unknown_outcome",
                "error": "order_router_timeout",
                "retCode": -2,
                "retry_safe": False,
            }
        )
        client._invalidate_order_caches = Mock()
        client._mark_stream_open_orders_dirty = Mock()
        client._mark_stream_positions_dirty = Mock()
        client._mark_stream_executions_dirty = Mock()
        client._forget_recent_open_order_hints_for_symbol = Mock()

        result = client.cancel_all_orders("BTCUSDT")

        assert result["success"] is None
        assert result["cache_invalidated"] is True
        assert result["cache_invalidation_reason"] == "ambiguous_order_action"
        client._invalidate_order_caches.assert_called_once()
        client._mark_stream_open_orders_dirty.assert_called_once_with("BTCUSDT")
        client._mark_stream_positions_dirty.assert_called_once_with()
        client._mark_stream_executions_dirty.assert_called_once_with()
        client._forget_recent_open_order_hints_for_symbol.assert_called_once_with(
            "BTCUSDT"
        )

    def test_cache_stats_available(self, client):
        """Should expose cache statistics."""
        stats = client.get_cache_stats()

        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate_pct" in stats
        assert "size" in stats

    def test_clear_cache(self, client, mock_session):
        """Should be able to clear cache."""
        # Populate cache
        client.get_tickers("BTCUSDT")
        assert mock_session.get.call_count == 1

        # Clear cache
        client.clear_cache()

        # Next call should hit API
        client.get_tickers("BTCUSDT")
        assert mock_session.get.call_count == 2


class TestConnectionPooling:
    """Tests for HTTP connection pooling configuration."""

    def test_session_has_adapter(self):
        """Session should have HTTPAdapter with custom pool."""
        with patch('services.bybit_client.requests.Session') as mock_session_cls:
            mock_session = Mock()
            mock_session_cls.return_value = mock_session

            client = BybitClient("key", "secret", "https://api.bybit.com")

            # Verify mount was called for https
            mock_session.mount.assert_any_call("https://", unittest.mock.ANY)
            mock_session.mount.assert_any_call("http://", unittest.mock.ANY)

    def test_pool_configuration(self):
        """Pool should be configured with correct sizes."""
        from services.bybit_client import BybitClient

        assert BybitClient.POOL_CONNECTIONS == 50
        assert BybitClient.POOL_MAXSIZE == 100
        assert BybitClient.POOL_BLOCK is False


class TestRateLimitedErrorLogging:
    """Tests for rate-limited error logging."""

    def test_should_log_error_first_time(self):
        """First occurrence of error should always be logged."""
        with patch('services.bybit_client.requests.Session'):
            client = BybitClient("key", "secret", "https://api.bybit.com")

            # First time should log
            assert client._should_log_error(100028) is True

    def test_should_not_log_error_within_interval(self):
        """Repeated errors within interval should be suppressed."""
        with patch('services.bybit_client.requests.Session'):
            client = BybitClient("key", "secret", "https://api.bybit.com")

            # First time - should log
            assert client._should_log_error(100028) is True

            # Second time immediately - should suppress
            assert client._should_log_error(100028) is False

    def test_should_log_error_after_interval(self):
        """Errors after interval should be logged again."""
        with patch('services.bybit_client.requests.Session'):
            client = BybitClient("key", "secret", "https://api.bybit.com")

            # First time - should log
            assert client._should_log_error(100028) is True

            # Simulate time passing (hack the last log time)
            client._error_log_times[100028] = time.time() - 400  # 400s ago

            # Should log again after interval (300s for 100028)
            assert client._should_log_error(100028) is True

    def test_non_rate_limited_errors_always_logged(self):
        """Errors not in RATE_LIMITED_ERROR_CODES should always log."""
        with patch('services.bybit_client.requests.Session'):
            client = BybitClient("key", "secret", "https://api.bybit.com")

            # Random error code not in rate-limited list
            assert client._should_log_error(12345) is True
            assert client._should_log_error(12345) is True  # Still logs

    def test_100028_in_non_retryable_codes(self):
        """100028 unified account forbidden should be in NON_RETRYABLE_CODES."""
        assert 100028 in BybitClient.NON_RETRYABLE_CODES

    def test_100028_has_rate_limited_logging(self):
        """100028 should have rate-limited logging configured."""
        assert 100028 in BybitClient.RATE_LIMITED_ERROR_CODES
        assert BybitClient.RATE_LIMITED_ERROR_CODES[100028] == 300  # 5 minutes


# Need unittest.mock for the ANY matcher
import unittest.mock
