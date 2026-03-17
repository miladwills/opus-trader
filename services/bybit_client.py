"""
Bybit Control Center - Bybit V5 REST Client

Minimal client for Bybit V5 API (linear USDT perpetuals, unified trading account).
Includes retry logic with exponential backoff, rate limiting, connection pooling,
and micro-caching for high-frequency GET endpoints.
"""

import time
import hmac
import hashlib
import json
import logging
import threading
from decimal import Decimal, ROUND_FLOOR
from typing import Optional, Dict, Any, List, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from services.control_timing_service import elapsed_ms, iso_from_ts, merge_result_timing

logger = logging.getLogger(__name__)


# =============================================================================
# MICRO-CACHE CONFIGURATION
# =============================================================================
# Short-lived cache for high-frequency GET endpoints to reduce API load.
# Each endpoint can have different TTLs based on how frequently data changes.

CACHE_TTL_CONFIG = {
    # Market data - changes frequently but small delays are acceptable
    "/v5/market/tickers": 1.0,  # 1 second cache for tickers
    "/v5/market/kline": 2.0,  # 2 second cache for klines
    "/v5/market/orderbook": 0.5,  # 0.5 second for orderbook
    "/v5/market/funding/history": 30.0,  # 30 second for funding rate
    # Account data - changes less frequently
    "/v5/position/list": 1.0,  # 1 second cache for positions
    "/v5/order/realtime": 1.0,  # 1 second cache for open orders
    "/v5/account/wallet-balance": 2.0,  # 2 second cache for balance
    "/v5/execution/list": 2.0,  # 2 second cache for executions
}

# Default cache TTL for endpoints not in the config
DEFAULT_CACHE_TTL = 1.0


class MicroCache:
    """
    Thread-safe micro-cache for high-frequency API calls.

    Uses a simple TTL-based eviction strategy. Cached entries are keyed
    by (path, params_hash) tuples.
    """

    def __init__(self, max_size: int = 500):
        """
        Initialize the micro-cache.

        Args:
            max_size: Maximum number of entries to store (LRU eviction when full)
        """
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def _make_key(self, path: str, params: Optional[Dict[str, Any]]) -> str:
        """Create a cache key from path and params."""
        if params:
            # Sort params for consistent keys
            sorted_params = sorted(params.items())
            params_str = "&".join(f"{k}={v}" for k, v in sorted_params)
            return f"{path}?{params_str}"
        return path

    def get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached result if still valid.

        Args:
            path: API endpoint path
            params: Query parameters

        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(path, params)
        ttl = CACHE_TTL_CONFIG.get(path, DEFAULT_CACHE_TTL)

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            cached_at, result = entry
            if time.time() - cached_at > ttl:
                # Expired - remove and return None
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            return result

    def set(
        self, path: str, params: Optional[Dict[str, Any]], result: Dict[str, Any]
    ) -> None:
        """
        Store result in cache.

        Args:
            path: API endpoint path
            params: Query parameters
            result: API response to cache
        """
        # Only cache successful responses
        if not result.get("success"):
            return

        key = self._make_key(path, params)

        with self._lock:
            # Simple LRU eviction - remove oldest entries if full
            if len(self._cache) >= self._max_size:
                # Remove oldest 10% of entries
                entries_to_remove = max(1, self._max_size // 10)
                sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][0])
                for old_key, _ in sorted_entries[:entries_to_remove]:
                    del self._cache[old_key]

            self._cache[key] = (time.time(), result)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def invalidate(self, path: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Invalidate a specific cache entry.

        Args:
            path: API endpoint path
            params: Query parameters
        """
        key = self._make_key(path, params)
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_path(self, path: str) -> None:
        """
        Invalidate all entries for a path (any params).

        Args:
            path: API endpoint path to invalidate
        """
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(path)]
            for key in keys_to_remove:
                del self._cache[key]

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": round(hit_rate, 1),
                "size": len(self._cache),
                "max_size": self._max_size,
            }


class RateLimiter:
    """
    Simple rate limiter using sliding window.
    Bybit limits: 120 requests per 5 seconds for most endpoints.
    """

    def __init__(self, max_requests: int = 100, window_seconds: float = 5.0):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in the window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: List[float] = []
        self.lock = threading.Lock()

    def acquire(self) -> None:
        """
        Wait if necessary to stay within rate limits.
        """
        with self.lock:
            now = time.time()
            # Remove requests outside the window
            self.requests = [t for t in self.requests if now - t < self.window_seconds]

            if len(self.requests) >= self.max_requests:
                # Calculate wait time
                oldest = min(self.requests)
                wait_time = self.window_seconds - (now - oldest) + 0.1
                if wait_time > 0:
                    logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                    time.sleep(wait_time)
                    # Clean up again after waiting
                    now = time.time()
                    self.requests = [
                        t for t in self.requests if now - t < self.window_seconds
                    ]

            self.requests.append(time.time())


class BybitClient:
    """
    Bybit V5 REST API client for linear USDT perpetuals.
    Includes automatic retry with exponential backoff and rate limiting.
    """

    RECV_WINDOW = "5000"

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 0.5  # seconds
    RETRY_MAX_DELAY = 5.0  # seconds

    # Retryable error codes
    RETRYABLE_CODES = {
        -1,  # Network/timeout errors
        10006,  # Rate limit exceeded
        10016,  # Server busy
        10018,  # Service unavailable
    }

    # Codes that should NOT be retried (permanent failures)
    NON_RETRYABLE_CODES = {
        10001,  # Invalid parameter
        10003,  # Invalid API key
        10004,  # Invalid sign
        10005,  # Permission denied
        100028,  # Unified account is forbidden (account type mismatch)
        110001,  # Order not found
        110007,  # Insufficient balance
        110012,  # Insufficient available balance
        110072,  # Duplicate orderLinkId
    }

    # Error codes that should only be logged once per interval (rate-limited logging)
    RATE_LIMITED_ERROR_CODES = {
        10002: 60,  # Timestamp / recv_window drift - log once per minute
        100028: 300,  # Unified account forbidden - log once per 5 minutes
        110017: 60,  # Zero position - log once per minute
    }

    # Connection pool configuration
    POOL_CONNECTIONS = 50  # Number of connection pools to cache
    POOL_MAXSIZE = 100  # Maximum connections per host
    POOL_BLOCK = False  # Don't block when pool is full
    RECENT_OPEN_ORDER_HINT_TTL_SEC = 15.0

    def __init__(self, api_key: str, api_secret: str, base_url: str):
        """
        Initialize the Bybit client.

        Args:
            api_key: Bybit API key
            api_secret: Bybit API secret
            base_url: Bybit API base URL (e.g., https://api.bybit.com)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")

        # Set up session with proper connection pooling
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=self.POOL_CONNECTIONS,
            pool_maxsize=self.POOL_MAXSIZE,
            pool_block=self.POOL_BLOCK,
            max_retries=0,  # We handle retries ourselves
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.rate_limiter = RateLimiter(max_requests=100, window_seconds=5.0)
        self._last_request_time = 0
        self._min_request_interval = 0.01  # 10ms minimum between requests (Bybit allows 10 req/s)

        # Phase 6: Latency tracking for connectivity health monitoring
        self._recent_latencies: List[tuple] = []  # [(timestamp, latency_ms), ...]
        self._max_latency_entries = 50
        self._consecutive_timeouts = 0
        self._latency_lock = threading.Lock()
        self._last_health_check = 0
        self._is_healthy = True
        self._instrument_cache: Dict[str, Dict[str, Any]] = {}
        self._health_check_lock = threading.Lock()
        self._health_check_inflight = False

        # Time synchronization offset (server_time - local_time) in ms
        self._time_offset_ms = 0
        self._last_time_sync = time.time()

        # Micro-cache for high-frequency GET requests
        self._micro_cache = MicroCache(max_size=500)
        self._cache_enabled = True  # Master toggle for caching

        # Rate-limited error logging tracker
        # Maps error_code -> last_logged_timestamp
        self._error_log_times: Dict[int, float] = {}
        self._error_log_lock = threading.Lock()
        self._recent_open_order_hints: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._recent_open_order_hints_lock = threading.RLock()
        self.stream_service = None
        self.order_router = None
        self.order_ownership_service = None
        self.trade_forensics_service = None

    def set_stream_service(self, stream_service: Any) -> "BybitClient":
        """Attach an optional websocket-backed stream service."""
        self.stream_service = stream_service
        return self

    def _try_ws_create_order(self, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Try to place an order via WebSocket. Returns None to fall back to REST."""
        stream = getattr(self, "stream_service", None)
        if not stream or not hasattr(stream, "send_trade_command"):
            return None
        if not stream.is_trade_ws_ready():
            return None
        try:
            ws_resp = stream.send_trade_command(
                op="order.create",
                args=[body],
                timeout_sec=3.0,
            )
            ws_error = ws_resp.get("error")
            # Pre-send failures: safe to fall back to REST (order was never sent)
            if ws_error in ("ws_not_connected", "ws_not_available", "ws_send_failed"):
                return None  # Fallback to REST
            # H1 audit: WS timeout AFTER send = ambiguous — order may have been
            # placed on exchange. NEVER fall back to REST (would create duplicate).
            if ws_error in ("ws_timeout", "ws_timeout_after_send"):
                logger.warning(
                    "[%s] WebSocket order AMBIGUOUS (timeout after send) — "
                    "NOT falling back to REST to prevent duplicates",
                    body.get("symbol"),
                )
                return {
                    "success": False,
                    "ambiguous": True,
                    "retry_safe": False,
                    "truth_check_required": True,
                    "error": "ws_timeout_after_send",
                    "transport": "websocket",
                }
            ret_code = int(ws_resp.get("retCode", -1) or -1)
            if ret_code == 0:
                data = ws_resp.get("data") or {}
                result = {"success": True, "data": data, "transport": "websocket"}
                logger.debug(
                    "[%s] Order placed via WebSocket (orderId=%s)",
                    body.get("symbol"),
                    data.get("orderId"),
                )
                return result
            # WS failed with explicit error code — fall back to REST.
            logger.warning(
                "[%s] WebSocket order failed (retCode=%s), falling back to REST",
                body.get("symbol"),
                ret_code,
            )
            return None  # Fallback to REST
        except Exception as exc:
            logger.debug("WebSocket order attempt failed, falling back to REST: %s", exc)
            return None  # Fallback to REST

    def set_order_router(self, order_router: Any) -> "BybitClient":
        """Attach an optional serialized order router."""
        self.order_router = order_router
        return self

    def set_order_ownership_service(self, order_ownership_service: Any) -> "BybitClient":
        """Attach an optional persistent order ownership store."""
        self.order_ownership_service = order_ownership_service
        return self

    def set_trade_forensics_service(self, trade_forensics_service: Any) -> "BybitClient":
        """Attach an optional trade forensics service."""
        self.trade_forensics_service = trade_forensics_service
        return self

    def _run_order_command(
        self,
        symbol: Optional[str],
        action: str,
        callback: Any,
    ) -> Dict[str, Any]:
        if not self.order_router:
            return callback()
        try:
            return self.order_router.execute(symbol, action, callback)
        except Exception as exc:
            logger.warning("[%s] Order command %s failed: %s", symbol or "*", action, exc)
            return {
                "success": False,
                "error": f"order_router:{action}:{exc}",
                "retCode": -1,
            }

    def health_check(self) -> Dict[str, Any]:
        """
        Check API connectivity and authentication.

        Returns:
            Dict with 'healthy' bool, 'latency_ms', and optional 'error'
        """
        start_time = time.time()
        try:
            # Use server time endpoint - lightweight, no auth required
            response = self.session.get(f"{self.base_url}/v5/market/time", timeout=5)
            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                if data.get("retCode") == 0:
                    sync_ts = end_time
                    server_time_ms = self._extract_server_time_ms(data)
                    if server_time_ms:
                        # Use the receive edge as the applied offset so transport
                        # asymmetry or local pre-send delay cannot push signed
                        # timestamps into the future. Midpoint remains diagnostic.
                        midpoint_local_ms = int((start_time + (latency_ms / 2000)) * 1000)
                        receive_local_ms = int(end_time * 1000)
                        midpoint_offset_ms = server_time_ms - midpoint_local_ms
                        receive_edge_offset_ms = server_time_ms - receive_local_ms
                        self._time_offset_ms = receive_edge_offset_ms
                        logger.info(
                            "Bybit time synchronized. Offset: %sms "
                            "midpoint_offset_ms=%s receive_edge_offset_ms=%s latency_ms=%.1f",
                            self._time_offset_ms,
                            midpoint_offset_ms,
                            receive_edge_offset_ms,
                            latency_ms,
                        )

                    self._last_time_sync = sync_ts
                    self._is_healthy = True
                    self._last_health_check = sync_ts
                    return {
                        "healthy": True,
                        "latency_ms": round(latency_ms, 1),
                        "server_time": server_time_ms,
                        "offset_ms": self._time_offset_ms
                    }

            self._is_healthy = False
            self._last_health_check = time.time()
            return {
                "healthy": False,
                "latency_ms": round(latency_ms, 1),
                "error": f"Unexpected response: {response.status_code}",
            }

        except requests.exceptions.Timeout:
            self._is_healthy = False
            self._last_health_check = time.time()
            return {"healthy": False, "error": "Connection timeout"}
        except requests.exceptions.ConnectionError as e:
            self._is_healthy = False
            self._last_health_check = time.time()
            return {"healthy": False, "error": f"Connection failed: {str(e)}"}
        except Exception as e:
            self._is_healthy = False
            self._last_health_check = time.time()
            return {"healthy": False, "error": f"Health check failed: {str(e)}"}

    def _extract_server_time_ms(self, data: Dict[str, Any]) -> int:
        """Extract Bybit server time in milliseconds from known response shapes."""
        try:
            raw_time = data.get("time")
            if raw_time:
                return int(raw_time)

            result = data.get("result") or {}
            time_nano = result.get("timeNano")
            if time_nano:
                return int(int(str(time_nano)) / 1_000_000)

            time_second = result.get("timeSecond")
            if time_second:
                return int(float(time_second) * 1000)
        except (TypeError, ValueError):
            return 0
        return 0

    def _schedule_async_health_check(self) -> None:
        """Refresh time sync asynchronously without spawning duplicate health checks."""
        now = time.time()
        if now - self._last_time_sync <= 1800:
            return
        with self._health_check_lock:
            if self._health_check_inflight or now - self._last_health_check < 15:
                return
            self._health_check_inflight = True

        def _worker():
            try:
                self.health_check()
            finally:
                with self._health_check_lock:
                    self._health_check_inflight = False

        threading.Thread(target=_worker, daemon=True).start()

    def is_healthy(self) -> bool:
        """
        Quick check if last health check was successful.
        Performs new health check if stale (>60s).
        """
        if time.time() - self._last_health_check > 60:
            self.health_check()
        return self._is_healthy

    # =========================================================================
    # Cache Management Methods
    # =========================================================================

    def _invalidate_order_caches(self) -> None:
        """
        Invalidate caches related to orders and positions.
        Called after order creation, cancellation, or any order-modifying operation.
        """
        self._micro_cache.invalidate_path("/v5/position/list")
        self._micro_cache.invalidate_path("/v5/order/realtime")
        self._micro_cache.invalidate_path("/v5/account/wallet-balance")
        self._micro_cache.invalidate_path("/v5/execution/list")

    def _mark_stream_open_orders_dirty(self, symbol: Optional[str] = None) -> None:
        if self.stream_service and hasattr(self.stream_service, "mark_open_orders_dirty"):
            try:
                self.stream_service.mark_open_orders_dirty(symbol)
            except Exception:
                logger.debug(
                    "[%s] Failed to mark stream open orders dirty",
                    symbol or "*",
                    exc_info=True,
                )

    def _mark_stream_positions_dirty(self) -> None:
        if self.stream_service and hasattr(self.stream_service, "mark_positions_dirty"):
            try:
                self.stream_service.mark_positions_dirty()
            except Exception:
                logger.debug("Failed to mark stream positions dirty", exc_info=True)

    def _mark_stream_executions_dirty(self) -> None:
        if self.stream_service and hasattr(self.stream_service, "mark_executions_dirty"):
            try:
                self.stream_service.mark_executions_dirty()
            except Exception:
                logger.debug("Failed to mark stream executions dirty", exc_info=True)

    @staticmethod
    def _is_ambiguous_order_action_result(result: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(result, dict):
            return False
        # H1 audit: also treat explicit ambiguous=True (e.g. WS timeout after send)
        if result.get("ambiguous") is True:
            return True
        status = str(result.get("status") or "").strip().lower()
        return result.get("success") is None or status in {
            "in_flight",
            "unknown_outcome",
        }

    def _invalidate_after_order_write(
        self,
        symbol: Optional[str],
        *,
        action: str,
        result: Dict[str, Any],
        force_invalidate: bool = False,
        clear_symbol_hints: bool = False,
        clear_order_hint: Optional[Dict[str, Optional[str]]] = None,
    ) -> Dict[str, Any]:
        ambiguous = self._is_ambiguous_order_action_result(result)
        if not force_invalidate and not result.get("success") and not ambiguous:
            return result
        self._invalidate_order_caches()
        self._mark_stream_open_orders_dirty(symbol)
        self._mark_stream_positions_dirty()
        self._mark_stream_executions_dirty()
        if clear_symbol_hints:
            self._forget_recent_open_order_hints_for_symbol(symbol)
        elif clear_order_hint:
            self._forget_recent_open_order_hint(
                symbol=symbol,
                order_id=clear_order_hint.get("order_id"),
                order_link_id=clear_order_hint.get("order_link_id"),
            )
        if not ambiguous:
            return result
        logger.warning(
            "ORDER_STATE_INVALIDATED symbol=%s action=%s reason=ambiguous_outcome retry_safe=%s",
            symbol or "*",
            action,
            result.get("retry_safe"),
        )
        updated = dict(result)
        updated["cache_invalidated"] = True
        updated["cache_invalidation_reason"] = "ambiguous_order_action"
        return updated

    @staticmethod
    def _normalize_symbol(symbol: Optional[str]) -> str:
        return str(symbol or "").strip().upper()

    @staticmethod
    def _open_order_hint_key(
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
        fallback: Optional[str] = None,
    ) -> str:
        key = str(order_id or "").strip()
        if key:
            return f"oid:{key}"
        key = str(order_link_id or "").strip()
        if key:
            return f"olid:{key}"
        return f"tmp:{fallback or int(time.time() * 1000)}"

    def _prune_recent_open_order_hints_locked(self, now_ts: Optional[float] = None) -> None:
        now = float(now_ts or time.time())
        ttl = max(float(self.RECENT_OPEN_ORDER_HINT_TTL_SEC), 1.0)
        expired_symbols: List[str] = []
        for symbol, hints in self._recent_open_order_hints.items():
            expired_keys = [
                key
                for key, hint in hints.items()
                if (now - float(hint.get("_hint_ts") or 0.0)) > ttl
            ]
            for key in expired_keys:
                hints.pop(key, None)
            if not hints:
                expired_symbols.append(symbol)
        for symbol in expired_symbols:
            self._recent_open_order_hints.pop(symbol, None)

    def _remember_open_order_hint(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str,
        price: Optional[float],
        reduce_only: bool,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> None:
        if str(order_type or "").strip().lower() != "limit":
            return
        normalized_symbol = self._normalize_symbol(symbol)
        if not normalized_symbol:
            return
        try:
            price_value = float(price or 0)
            qty_value = float(qty or 0)
        except (TypeError, ValueError):
            return
        if price_value <= 0 or qty_value <= 0:
            return
        now_ts = time.time()
        hint_key = self._open_order_hint_key(
            order_id=order_id,
            order_link_id=order_link_id,
            fallback=f"{normalized_symbol}:{side}:{price_value}",
        )
        hint = {
            "symbol": normalized_symbol,
            "orderId": str(order_id or "").strip() or None,
            "orderLinkId": str(order_link_id or "").strip() or None,
            "side": side,
            "price": f"{price_value}",
            "qty": f"{qty_value}",
            "leavesQty": f"{qty_value}",
            "reduceOnly": bool(reduce_only),
            "orderStatus": "New",
            "_hint_ts": now_ts,
        }
        with self._recent_open_order_hints_lock:
            by_symbol = self._recent_open_order_hints.setdefault(normalized_symbol, {})
            by_symbol[hint_key] = hint
            self._prune_recent_open_order_hints_locked(now_ts)

    def _forget_recent_open_order_hint(
        self,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> None:
        normalized_symbol = self._normalize_symbol(symbol) if symbol else None
        order_id_text = str(order_id or "").strip()
        order_link_text = str(order_link_id or "").strip()
        if not normalized_symbol and not order_id_text and not order_link_text:
            return
        with self._recent_open_order_hints_lock:
            symbols = (
                [normalized_symbol]
                if normalized_symbol
                else list(self._recent_open_order_hints.keys())
            )
            for symbol_key in symbols:
                hints = self._recent_open_order_hints.get(symbol_key) or {}
                remove_keys = []
                for key, hint in hints.items():
                    if order_id_text and str(hint.get("orderId") or "").strip() == order_id_text:
                        remove_keys.append(key)
                        continue
                    if (
                        order_link_text
                        and str(hint.get("orderLinkId") or "").strip() == order_link_text
                    ):
                        remove_keys.append(key)
                for key in remove_keys:
                    hints.pop(key, None)
                if not hints:
                    self._recent_open_order_hints.pop(symbol_key, None)

    def _forget_recent_open_order_hints_for_symbol(self, symbol: Optional[str]) -> None:
        normalized_symbol = self._normalize_symbol(symbol)
        if not normalized_symbol:
            return
        with self._recent_open_order_hints_lock:
            self._recent_open_order_hints.pop(normalized_symbol, None)

    def _merge_recent_open_order_hints(
        self,
        symbol: Optional[str],
        response: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not response.get("success"):
            return response
        normalized_symbol = self._normalize_symbol(symbol) if symbol else None
        data = dict(response.get("data", {}) or {})
        order_list = data.get("list", [])
        order_rows = list(order_list) if isinstance(order_list, list) else []
        existing_ids = {
            str((row or {}).get("orderId") or "").strip()
            for row in order_rows
            if str((row or {}).get("orderId") or "").strip()
        }
        existing_link_ids = {
            str((row or {}).get("orderLinkId") or "").strip()
            for row in order_rows
            if str((row or {}).get("orderLinkId") or "").strip()
        }

        with self._recent_open_order_hints_lock:
            self._prune_recent_open_order_hints_locked()
            if normalized_symbol:
                hint_maps = [self._recent_open_order_hints.get(normalized_symbol) or {}]
            else:
                hint_maps = list(self._recent_open_order_hints.values())
            for hints in hint_maps:
                for hint in hints.values():
                    hint_order_id = str(hint.get("orderId") or "").strip()
                    hint_link_id = str(hint.get("orderLinkId") or "").strip()
                    if hint_order_id and hint_order_id in existing_ids:
                        continue
                    if hint_link_id and hint_link_id in existing_link_ids:
                        continue
                    order_rows.append(dict(hint))
                    if hint_order_id:
                        existing_ids.add(hint_order_id)
                    if hint_link_id:
                        existing_link_ids.add(hint_link_id)

        data["list"] = order_rows
        merged = dict(response)
        merged["data"] = data
        return merged

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.

        Returns:
            Dict with hits, misses, hit_rate_pct, size, max_size
        """
        return self._micro_cache.get_stats()

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._micro_cache.clear()

    def set_cache_enabled(self, enabled: bool) -> None:
        """
        Enable or disable the micro-cache.

        Args:
            enabled: True to enable caching, False to disable
        """
        self._cache_enabled = enabled

    # =========================================================================
    # Rate-Limited Error Logging
    # =========================================================================

    def _should_log_error(self, ret_code: int) -> bool:
        """
        Check if an error should be logged (rate-limited for certain codes).

        Some error codes (like 100028 unified account forbidden) can spam
        logs if they occur frequently. This method implements rate-limiting
        for such errors.

        Args:
            ret_code: Bybit return code

        Returns:
            True if the error should be logged, False if suppressed
        """
        # Check if this error code has rate-limited logging
        if ret_code not in self.RATE_LIMITED_ERROR_CODES:
            return True

        interval = self.RATE_LIMITED_ERROR_CODES[ret_code]
        now = time.time()

        with self._error_log_lock:
            last_logged = self._error_log_times.get(ret_code, 0)
            if now - last_logged >= interval:
                self._error_log_times[ret_code] = now
                return True
            return False

    def get_server_time(self) -> int:
        """Get Bybit server time."""
        endpoint = "/v5/market/time"
        response = self._request("GET", endpoint)
        if response.get("success"):
            return int(response.get("data", {}).get("timeSecond", time.time()))
        return int(time.time())

    @staticmethod
    def _extract_recv_window_skew_ms(error_msg: Any) -> Optional[int]:
        details = BybitClient._extract_recv_window_error_details(error_msg)
        return details.get("skew_ms")

    @staticmethod
    def _extract_recv_window_error_details(error_msg: Any) -> Dict[str, Optional[int]]:
        text = str(error_msg or "")

        def _extract_value(field: str) -> Optional[int]:
            marker = f"{field}["
            start = text.find(marker)
            if start < 0:
                return None
            start += len(marker)
            end = text.find("]", start)
            if end < 0:
                return None
            try:
                return int(text[start:end])
            except (TypeError, ValueError):
                return None

        req_ts = _extract_value("req_timestamp")
        server_ts = _extract_value("server_timestamp")
        recv_window_ms = _extract_value("recv_window")
        skew_ms = None
        if req_ts is not None and server_ts is not None:
            skew_ms = req_ts - server_ts
        return {
            "request_timestamp_ms": req_ts,
            "server_timestamp_ms": server_ts,
            "recv_window_ms": recv_window_ms,
            "skew_ms": skew_ms,
        }

    def _retry_after_recv_window_error(
        self,
        *,
        method: str,
        path: str,
        error_msg: Any,
        attempt: int,
        request_timestamp_ms: Optional[int] = None,
        request_round_trip_ms: Optional[float] = None,
        pre_send_delay_ms: Optional[int] = None,
    ) -> bool:
        if attempt >= self.MAX_RETRIES - 1:
            return False
        details = self._extract_recv_window_error_details(error_msg)
        previous_offset_ms = int(self._time_offset_ms or 0)
        sync = self.health_check()
        if not sync.get("healthy"):
            if self._should_log_error(10002):
                logger.warning(
                    "BYBIT_TIME_RESYNC reason=recv_window method=%s path=%s result=sync_failed "
                    "attempt=%d/%d req_timestamp_ms=%s server_timestamp_ms=%s recv_window_ms=%s "
                    "skew_ms=%s request_round_trip_ms=%s pre_send_delay_ms=%s "
                    "old_offset_ms=%s error=%s",
                    method,
                    path,
                    attempt + 1,
                    self.MAX_RETRIES,
                    details.get("request_timestamp_ms") or request_timestamp_ms,
                    details.get("server_timestamp_ms"),
                    details.get("recv_window_ms"),
                    details.get("skew_ms"),
                    request_round_trip_ms,
                    pre_send_delay_ms,
                    previous_offset_ms,
                    sync.get("error"),
                )
            return False
        if self._should_log_error(10002):
            logger.info(
                "BYBIT_TIME_RESYNC reason=recv_window method=%s path=%s result=retrying "
                "attempt=%d/%d req_timestamp_ms=%s server_timestamp_ms=%s recv_window_ms=%s "
                "skew_ms=%s request_round_trip_ms=%s pre_send_delay_ms=%s "
                "old_offset_ms=%s new_offset_ms=%s sync_latency_ms=%s",
                method,
                path,
                attempt + 1,
                self.MAX_RETRIES,
                details.get("request_timestamp_ms") or request_timestamp_ms,
                details.get("server_timestamp_ms"),
                details.get("recv_window_ms"),
                details.get("skew_ms"),
                request_round_trip_ms,
                pre_send_delay_ms,
                previous_offset_ms,
                int(self._time_offset_ms or 0),
                sync.get("latency_ms"),
            )
        return True

    def create_internal_transfer(
        self,
        transfer_id: str,
        coin: str,
        amount: str,
        from_account_type: str,
        to_account_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Create an internal transfer between accounts (e.g., UNIFIED -> FUND).

        Args:
            transfer_id: Unique UUID for the transfer
            coin: Coin currency (e.g., USDT)
            amount: Amount to transfer
            from_account_type: Account type to transfer from (e.g., UNIFIED)
            to_account_type: Account type to transfer to (e.g., FUND)
        """
        endpoint = "/v5/asset/transfer/inter-transfer"
        payload = {
            "transferId": transfer_id,
            "coin": coin,
            "amount": amount,
            "fromAccountType": from_account_type,
            "toAccountType": to_account_type,
        }
        return self._request("POST", endpoint, body=payload)

    def _record_latency(self, latency_ms: float, is_timeout: bool = False) -> None:
        """Record request latency for connectivity health monitoring."""
        with self._latency_lock:
            now = time.time()
            self._recent_latencies.append((now, latency_ms))
            if len(self._recent_latencies) > self._max_latency_entries:
                self._recent_latencies = self._recent_latencies[-self._max_latency_entries:]
            if is_timeout:
                self._consecutive_timeouts += 1
            else:
                self._consecutive_timeouts = 0

    def get_latency_stats(self) -> Dict[str, Any]:
        """Return latency p50/p95 and error metrics for the last 5 minutes."""
        with self._latency_lock:
            now = time.time()
            recent = [lat for ts, lat in self._recent_latencies if now - ts < 300]
            if not recent:
                return {
                    "p50_ms": 0, "p95_ms": 0, "error_rate_pct": 0,
                    "consecutive_timeouts": self._consecutive_timeouts,
                    "sample_count": 0,
                }
            recent_sorted = sorted(recent)
            n = len(recent_sorted)
            p50 = recent_sorted[n // 2]
            p95 = recent_sorted[min(int(n * 0.95), n - 1)]
            error_count = sum(1 for lat in recent if lat < 0)
            return {
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "error_rate_pct": round(error_count / max(n, 1) * 100, 1),
                "consecutive_timeouts": self._consecutive_timeouts,
                "sample_count": n,
            }

    def _timestamp_ms(self) -> int:
        """
        Get current timestamp in milliseconds, synchronized with Bybit server.
        """
        # Periodic re-sync if offset is more than 30 minutes old
        self._schedule_async_health_check()
        return int(time.time() * 1000) + self._time_offset_ms

    def _get_now_ts(self) -> float:
        """Unified time source for cooldowns and timestamps."""
        return time.time()

    def _sign(self, timestamp: str, params_str: str) -> str:
        """
        Compute HMAC SHA256 signature for Bybit V5 API.

        Bybit V5 signing format:
        sign = HMAC_SHA256(timestamp + api_key + recv_window + params_str)

        Args:
            timestamp: Request timestamp in milliseconds (string)
            params_str: Query string for GET or JSON body for POST

        Returns:
            Hex-encoded signature string
        """
        sign_payload = f"{timestamp}{self.api_key}{self.RECV_WINDOW}{params_str}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _should_retry(self, ret_code: int, attempt: int) -> bool:
        """
        Determine if a request should be retried based on error code.

        Args:
            ret_code: Bybit return code or -1 for network errors
            attempt: Current attempt number (0-indexed)

        Returns:
            True if should retry, False otherwise
        """
        if attempt >= self.MAX_RETRIES - 1:
            return False
        if ret_code in self.NON_RETRYABLE_CODES:
            return False
        # Retry on network errors (-1) or known retryable codes
        return ret_code == -1 or ret_code in self.RETRYABLE_CODES

    def _get_retry_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = self.RETRY_BASE_DELAY * (2**attempt)
        return min(delay, self.RETRY_MAX_DELAY)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        skip_cache: bool = False,
    ) -> Dict[str, Any]:
        """
        Common helper for GET/POST to Bybit V5 with retry logic.

        Args:
            method: HTTP method ("GET" or "POST")
            path: API endpoint path (e.g., "/v5/market/tickers")
            params: Query parameters for GET requests
            body: JSON body for POST requests
            skip_cache: If True, bypass cache for this request

        Returns:
            { "success": True, "data": ... } on success
            { "success": False, "error": str, "retCode": int } on error
        """
        url = f"{self.base_url}{path}"
        last_result = None

        # Check cache for GET requests (unless skip_cache is set)
        if method.upper() == "GET" and self._cache_enabled and not skip_cache:
            cached = self._micro_cache.get(path, params)
            if cached is not None:
                return cached

        for attempt in range(self.MAX_RETRIES):
            # Apply rate limiting
            self.rate_limiter.acquire()

            # Ensure minimum interval between requests
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)

            # Fresh timestamp for each attempt
            timestamp = str(self._timestamp_ms())
            request_timestamp_ms = int(timestamp)

            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": self.RECV_WINDOW,
                "Content-Type": "application/json",
            }

            _req_t0 = time.monotonic()
            pre_send_delay_ms: Optional[int] = None
            try:
                if method.upper() == "GET":
                    # Build query string for signing
                    if params:
                        sorted_params = sorted(params.items())
                        query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
                    else:
                        query_string = ""

                    signature = self._sign(timestamp, query_string)
                    headers["X-BAPI-SIGN"] = signature
                    pre_send_delay_ms = max(int(time.time() * 1000) - request_timestamp_ms, 0)
                    response = self.session.get(
                        url, params=params, headers=headers, timeout=20
                    )

                elif method.upper() == "POST":
                    if body:
                        body_str = json.dumps(body, separators=(",", ":"))
                    else:
                        body_str = ""

                    signature = self._sign(timestamp, body_str)
                    headers["X-BAPI-SIGN"] = signature
                    pre_send_delay_ms = max(int(time.time() * 1000) - request_timestamp_ms, 0)
                    response = self.session.post(
                        url, data=body_str, headers=headers, timeout=20
                    )

                else:
                    logger.error(f"Unsupported HTTP method: {method}")
                    return {
                        "success": False,
                        "error": f"Unsupported HTTP method: {method}",
                        "retCode": -1,
                    }

                self._last_request_time = time.time()
                status_code = response.status_code
                raw_text = response.text

                # Handle empty body
                if not raw_text or not raw_text.strip():
                    logger.error(
                        f"Empty response (status {status_code}) for {method} {path}"
                    )
                    last_result = {
                        "success": False,
                        "error": f"Empty response (status {status_code})",
                        "retCode": -1,
                        "status_code": status_code,
                    }
                    if self._should_retry(-1, attempt):
                        delay = self._get_retry_delay(attempt)
                        logger.info(
                            f"Retrying {method} {path} in {delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue
                    self._record_latency(-1.0)
                    return last_result

                # Parse response
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    snippet = raw_text[:200].replace("\n", " ").strip()
                    logger.error(
                        f"Failed to parse JSON (status {status_code}): {e}. Preview: {snippet}"
                    )
                    last_result = {
                        "success": False,
                        "error": f"Invalid JSON response (status {status_code})",
                        "retCode": -1,
                        "status_code": status_code,
                    }
                    if self._should_retry(-1, attempt):
                        delay = self._get_retry_delay(attempt)
                        logger.info(
                            f"Retrying {method} {path} in {delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue
                    self._record_latency(-1.0)
                    return last_result

                # C1: Validate HTTP status code before trusting retCode.
                # A non-2xx response with retCode=0 in the body is NOT a
                # success — it's a server error with misleading JSON.
                if status_code < 200 or status_code >= 300:
                    ret_code_hint = data.get("retCode", -1)
                    error_msg = data.get("retMsg") or f"HTTP {status_code}"
                    logger.warning(
                        "HTTP %d for %s %s (retCode=%s msg=%s) — treated as error",
                        status_code, method, path, ret_code_hint, error_msg,
                    )
                    last_result = {
                        "success": False,
                        "error": f"HTTP {status_code}: {error_msg}",
                        "retCode": int(ret_code_hint) if ret_code_hint != -1 else -status_code,
                        "status_code": status_code,
                    }
                    if self._should_retry(int(ret_code_hint or -1), attempt):
                        delay = self._get_retry_delay(attempt)
                        logger.info(
                            "Retrying %s %s in %.1fs (HTTP %d, attempt %d/%d)",
                            method, path, delay, status_code, attempt + 1, self.MAX_RETRIES,
                        )
                        time.sleep(delay)
                        continue
                    self._record_latency(-1.0)
                    return last_result

                # Check Bybit return code
                ret_code = data.get("retCode", -1)
                if ret_code == 0:
                    self._record_latency((time.monotonic() - _req_t0) * 1000)
                    result = {"success": True, "data": data.get("result", {})}
                    # Cache successful GET responses
                    if (
                        method.upper() == "GET"
                        and self._cache_enabled
                        and not skip_cache
                    ):
                        self._micro_cache.set(path, params, result)
                    return result
                else:
                    error_msg = data.get("retMsg", "Unknown error")
                    last_result = {
                        "success": False,
                        "error": error_msg,
                        "retCode": ret_code,
                        "status_code": status_code,
                    }

                    if ret_code == 10002 and self._retry_after_recv_window_error(
                        method=method,
                        path=path,
                        error_msg=error_msg,
                        attempt=attempt,
                        request_timestamp_ms=request_timestamp_ms,
                        request_round_trip_ms=round(
                            (time.monotonic() - _req_t0) * 1000, 1
                        ),
                        pre_send_delay_ms=pre_send_delay_ms,
                    ):
                        continue

                    # Check if we should retry
                    if self._should_retry(ret_code, attempt):
                        delay = self._get_retry_delay(attempt)
                        logger.info(
                            f"Retrying {method} {path} in {delay:.1f}s after error: {error_msg} (attempt {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        continue

                    # Don't retry - return immediately
                    # Use rate-limited logging for certain error codes to avoid log spam
                    if ret_code not in (110072,) and self._should_log_error(ret_code):
                        if ret_code in (110017, 110043):
                            logger.info(
                                f"Bybit API info: {error_msg} (retCode={ret_code})"
                            )
                        else:
                            logger.warning(
                                f"Bybit API error: {error_msg} (retCode={ret_code})"
                            )
                    self._record_latency(-1.0)
                    return last_result

            except requests.exceptions.Timeout:
                self._record_latency((time.monotonic() - _req_t0) * 1000, is_timeout=True)
                logger.error(f"Request timeout: {method} {path}")
                last_result = {
                    "success": False,
                    "error": "Request timeout",
                    "retCode": -1,
                }
                if self._should_retry(-1, attempt):
                    delay = self._get_retry_delay(attempt)
                    logger.info(
                        f"Retrying {method} {path} in {delay:.1f}s after timeout (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue
                return last_result

            except requests.exceptions.ConnectionError as e:
                self._record_latency(-1.0)
                logger.error(f"Connection error: {method} {path} - {e}")
                last_result = {
                    "success": False,
                    "error": f"Connection error: {str(e)}",
                    "retCode": -1,
                }
                if self._should_retry(-1, attempt):
                    delay = self._get_retry_delay(attempt)
                    logger.info(
                        f"Retrying {method} {path} in {delay:.1f}s after connection error (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue
                return last_result

            except requests.exceptions.RequestException as e:
                self._record_latency(-1.0)
                logger.error(f"Request exception: {method} {path} - {e}")
                last_result = {
                    "success": False,
                    "error": f"Request failed: {str(e)}",
                    "retCode": -1,
                }
                if self._should_retry(-1, attempt):
                    delay = self._get_retry_delay(attempt)
                    logger.info(
                        f"Retrying {method} {path} in {delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    continue
                return last_result

        # All retries exhausted
        logger.error(f"All {self.MAX_RETRIES} retries exhausted for {method} {path}")
        return last_result or {
            "success": False,
            "error": "All retries exhausted",
            "retCode": -1,
        }

    def get_tickers(
        self, symbol: Optional[str] = None, skip_cache: bool = False
    ) -> Dict[str, Any]:
        """
        Get market tickers for linear USDT perpetuals.

        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT")
            skip_cache: If True, bypass internal micro-cache

        Returns:
            Standard success/error dict with ticker data
        """
        if symbol and self.stream_service:
            self.stream_service.ensure_symbol(symbol)
            stream_resp = self.stream_service.get_ticker_response(symbol)
            if stream_resp:
                return stream_resp

        params = {"category": "linear"}
        if symbol:
            params["symbol"] = symbol
        return self._request(
            "GET", "/v5/market/tickers", params=params, skip_cache=skip_cache
        )

    def get_kline(
        self, symbol: str, interval: str = "15", limit: int = 200, **kwargs
    ) -> Dict[str, Any]:
        """
        Get kline/candlestick data.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            interval: Kline interval (1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, M, W)
            limit: Number of klines to retrieve (max 200)
            **kwargs: Additional parameters (e.g., start, end)

        Returns:
            Standard success/error dict with kline data
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        params.update(kwargs)
        return self._request("GET", "/v5/market/kline", params=params)

    def get_positions(
        self,
        skip_cache: bool = False,
        cache_seed_source: Optional[str] = None,
        cache_seed_expected_epoch: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get all positions for linear USDT perpetuals.

        Args:
            skip_cache: If True, bypass internal micro-cache

        Returns:
            Standard success/error dict with position data
        """
        if self.stream_service and not skip_cache:
            stream_resp = self.stream_service.get_positions_response()
            if stream_resp:
                return stream_resp

        params = {
            "category": "linear",
            "settleCoin": "USDT",
        }
        request_started_at = time.time()
        response = self._request(
            "GET", "/v5/position/list", params=params, skip_cache=skip_cache
        )
        if response.get("success") and self.stream_service and hasattr(
            self.stream_service, "seed_positions_snapshot"
        ):
            try:
                expected_epoch = cache_seed_expected_epoch
                if expected_epoch is None and hasattr(
                    self.stream_service, "get_private_reconnect_epoch"
                ):
                    expected_epoch = self.stream_service.get_private_reconnect_epoch()
                self.stream_service.seed_positions_snapshot(
                    (response.get("data", {}) or {}).get("list", []) or [],
                    expected_epoch=expected_epoch,
                    snapshot_started_at=request_started_at,
                    snapshot_received_at=time.time(),
                    source=cache_seed_source
                    or ("rest_fetch" if skip_cache else "rest_fallback"),
                    is_reconcile=str(cache_seed_source or "").strip().lower() == "reconcile",
                )
            except Exception:
                logger.debug(
                    "Failed to seed stream positions snapshot",
                    exc_info=True,
                )
        return response

    def get_wallet_balance(
        self,
        account_type: str = "UNIFIED",
        skip_cache: bool = False,
    ) -> Dict[str, Any]:
        """
        Get wallet balance for a specific account type.

        Args:
            account_type: Account type to fetch balance for (e.g., "UNIFIED", "FUND")

        Returns:
            Standard success/error dict with balance data
        """
        params = {
            "accountType": account_type,
        }
        return self._request(
            "GET",
            "/v5/account/wallet-balance",
            params=params,
            skip_cache=skip_cache,
        )

    def get_coins_balance(
        self, account_type: str, coin: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query asset balance for a specific account type (Asset Endpoint).
        Required for Funding account in UTA mode where get_wallet_balance fails.

        Args:
            account_type: Account type (UNIFIED, FUND, SPOT, etc.)
            coin: Optional specific coin to query (e.g., "USDT")

        Returns:
            Standard success/error dict with coin balance data
        """
        params = {
            "accountType": account_type,
        }
        if coin:
            params["coin"] = coin
        return self._request(
            "GET", "/v5/asset/transfer/query-account-coins-balance", params=params
        )

    def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """
        Get current funding rate for a perpetual contract.

        Bybit perpetuals have funding every 8 hours.
        Positive rate = longs pay shorts (bullish sentiment, longs crowded)
        Negative rate = shorts pay longs (bearish sentiment, shorts crowded)

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")

        Returns:
            Standard success/error dict with funding rate data:
            - fundingRate: Current funding rate (e.g., 0.0001 = 0.01%)
            - fundingRateTimestamp: Next funding time
        """
        params = {
            "category": "linear",
            "symbol": symbol,
        }
        return self._request("GET", "/v5/market/funding/history", params=params)

    def get_open_interest(self, symbol: str, interval: str = "5min") -> Dict[str, Any]:
        """Get open interest history for a perpetual contract.

        Rising OI + rising price = real conviction (new money entering).
        Rising OI + falling price = shorts piling in.
        Falling OI + rising price = short squeeze (weak, likely to reverse).
        Falling OI + falling price = longs closing (capitulation).
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": interval,
            "limit": 10,
        }
        return self._request("GET", "/v5/market/open-interest", params=params)

    def get_long_short_ratio(self, symbol: str, period: str = "5min") -> Dict[str, Any]:
        """Get long/short account ratio.

        Ratio > 1.0 = more accounts long than short (crowd is bullish).
        Ratio < 1.0 = more accounts short than long (crowd is bearish).
        Extreme ratios often precede reversals (crowd is usually wrong at extremes).
        """
        params = {
            "category": "linear",
            "symbol": symbol,
            "period": period,
            "limit": 10,
        }
        return self._request("GET", "/v5/market/account-ratio", params=params)

    def create_order(
        self,
        symbol: str,
        side: str,
        qty: Optional[float],
        order_type: str = "Market",
        price: Optional[float] = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        order_link_id: Optional[str] = None,
        position_idx: Optional[int] = None,
        qty_is_normalized: bool = False,
        ownership_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an order for linear USDT perpetuals.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            side: Order side ("Buy" or "Sell")
            qty: Order quantity
            order_type: Order type ("Market" or "Limit")
            price: Limit price (required for Limit orders)
            reduce_only: Whether order should only reduce position
            time_in_force: Time in force ("GTC", "IOC", "FOK", "PostOnly")
            order_link_id: Optional custom order ID for tracking (max 36 chars)
            position_idx: Optional position index (0 one-way, 1 buy hedge, 2 sell hedge)
            qty_is_normalized: If True, qty is assumed normalized and will not be re-normalized
            ownership_snapshot: Optional durable owner snapshot for later PnL attribution

        Returns:
            Standard success/error dict with order data
        """
        normalized_qty = qty if qty_is_normalized else self.normalize_qty(symbol, qty)
        if not normalized_qty:
            return {
                "success": False,
                "error": "qty_below_min",
                "retCode": -1,
            }

        body = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": f"{normalized_qty:f}".rstrip("0").rstrip("."),
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
        }

        if price is not None and order_type == "Limit":
            body["price"] = str(price)

        if order_link_id is not None:
            body["orderLinkId"] = order_link_id

        if position_idx is not None:
            body["positionIdx"] = int(position_idx)

        submit_started_at = time.time()
        # Try WebSocket first (50ms) — fallback to REST (400ms) if WS unavailable
        ws_result = self._try_ws_create_order(body)
        if ws_result is not None:
            result = ws_result
        else:
            result = self._run_order_command(
                symbol,
                "create_order",
                lambda: self._request("POST", "/v5/order/create", body=body),
            )
        submit_completed_at = time.time()
        result = merge_result_timing(
            result,
            order_submit_started_at=iso_from_ts(submit_started_at),
            order_submit_ack_at=iso_from_ts(submit_completed_at),
            order_submit_to_ack_ms=elapsed_ms(submit_started_at, submit_completed_at),
        )

        if (
            reduce_only
            and not result.get("success")
            and self._is_reduce_only_no_position_error(
                result.get("retCode"),
                result.get("error"),
            )
        ):
            result = dict(result)
            result["position_empty"] = True
        ambiguous_result = self._is_ambiguous_order_action_result(result)
        if result.get("success") or ambiguous_result or result.get("position_empty"):
            result = self._invalidate_after_order_write(
                symbol,
                action="create_order",
                result=result,
                force_invalidate=bool(result.get("position_empty")),
                clear_symbol_hints=ambiguous_result or bool(result.get("position_empty")),
            )

        # Invalidate related caches after order creation
        if result.get("success"):
            order_data = result.get("data", {}) or {}
            self._remember_open_order_hint(
                symbol=symbol,
                side=side,
                qty=normalized_qty,
                order_type=order_type,
                price=price,
                reduce_only=reduce_only,
                order_id=order_data.get("orderId"),
                order_link_id=order_data.get("orderLinkId") or order_link_id,
            )
            if ownership_snapshot and self.order_ownership_service:
                try:
                    ownership_record = dict(ownership_snapshot)
                    ownership_record.setdefault(
                        "action", "reduce_only_close" if reduce_only else "entry"
                    )
                    ownership_record["symbol"] = symbol
                    ownership_record["side"] = side
                    ownership_record["position_idx"] = position_idx
                    ownership_record["reduce_only"] = bool(reduce_only)
                    ownership_record["order_id"] = (
                        str(order_data.get("orderId") or "").strip() or None
                    )
                    ownership_record["order_link_id"] = (
                        str(order_data.get("orderLinkId") or order_link_id or "").strip()
                        or None
                    )
                    self.order_ownership_service.record_order(ownership_record)
                except Exception as exc:
                    logger.warning(
                        "[%s] Failed to persist order ownership snapshot for %s: %s",
                        symbol,
                        order_link_id or order_data.get("orderId") or "?",
                        exc,
                    )
                    result["ownership_recording_failed"] = True
            if ownership_snapshot and self.trade_forensics_service:
                try:
                    linkage_method = (
                        "ownership_snapshot"
                        if ownership_snapshot.get("forensic_trade_context_id")
                        or ownership_snapshot.get("forensic_decision_id")
                        else "bot_symbol_only"
                    )
                    base_payload = {
                        "forensic_decision_id": ownership_snapshot.get(
                            "forensic_decision_id"
                        ),
                        "trade_context_id": ownership_snapshot.get(
                            "forensic_trade_context_id"
                        ),
                        "bot_id": ownership_snapshot.get("bot_id"),
                        "symbol": symbol,
                        "mode": ownership_snapshot.get("bot_mode"),
                        "profile": ownership_snapshot.get("bot_profile"),
                        "side": ownership_snapshot.get("forensic_side") or side,
                        "decision_type": ownership_snapshot.get("forensic_decision_type"),
                        "linkage_method": linkage_method,
                        "attribution_status": (
                            "linked"
                            if ownership_snapshot.get("forensic_trade_context_id")
                            or ownership_snapshot.get("forensic_decision_id")
                            else "unresolved"
                        ),
                        "order": {
                            "order_id": (
                                str(order_data.get("orderId") or "").strip() or None
                            ),
                            "order_link_id": (
                                str(order_data.get("orderLinkId") or order_link_id or "").strip()
                                or None
                            ),
                            "order_type": order_type,
                            "qty": round(float(normalized_qty), 8),
                            "price": round(float(price), 8) if price is not None else None,
                            "reduce_only": bool(reduce_only),
                            "position_idx": position_idx,
                            "action": ownership_snapshot.get("action"),
                            "experiment_tags": list(
                                ownership_snapshot.get("experiment_tags") or []
                            ),
                            "experiment_attribution_state": (
                                str(
                                    ownership_snapshot.get(
                                        "experiment_attribution_state"
                                    )
                                    or ""
                                ).strip()
                                or "none"
                            ),
                            "entry_story": dict(
                                ownership_snapshot.get("entry_story") or {}
                            )
                            or None,
                            "opening_sizing": ownership_snapshot.get("opening_sizing"),
                            "profit_protection_advisory": dict(
                                ownership_snapshot.get("profit_protection_advisory")
                                or {}
                            )
                            or None,
                            "profit_protection_shadow": dict(
                                ownership_snapshot.get("profit_protection_shadow")
                                or {}
                            )
                            or None,
                        },
                    }
                    if reduce_only:
                        self.trade_forensics_service.record_event(
                            dict(
                                base_payload,
                                event_type="exit_decision",
                                event_status="submitted",
                                exit={
                                    "action": ownership_snapshot.get("action"),
                                    "close_reason": ownership_snapshot.get("close_reason"),
                                },
                            )
                        )
                    self.trade_forensics_service.record_event(
                        dict(
                            base_payload,
                            event_type="order_submitted",
                            event_status="submitted",
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] Failed to record trade forensic order event for %s: %s",
                        symbol,
                        order_link_id or order_data.get("orderId") or "?",
                        exc,
                    )

        return result

    @staticmethod
    def _is_reduce_only_no_position_error(
        ret_code: Optional[int], error_msg: Optional[str]
    ) -> bool:
        try:
            ret_code_int = int(ret_code) if ret_code is not None else None
        except (TypeError, ValueError):
            ret_code_int = None
        if ret_code_int != 110017:
            return False
        msg = str(error_msg or "").lower()
        return (
            "position is zero" in msg
            or "current position is zero" in msg
            or "position size is zero" in msg
            or "cannot fix reduce-only order qty" in msg
        )

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: Optional[float],
        order_type: str = "Market",
        price: Optional[float] = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        order_link_id: Optional[str] = None,
        position_idx: Optional[int] = None,
        ownership_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Backwards-compatible wrapper for create_order.
        """
        return self.create_order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=order_type,
            price=price,
            reduce_only=reduce_only,
            time_in_force=time_in_force,
            order_link_id=order_link_id,
            position_idx=position_idx,
            ownership_snapshot=ownership_snapshot,
        )

    def get_executions(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        skip_cache: bool = False,
        cache_seed_source: Optional[str] = None,
        cache_seed_expected_epoch: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get execution records (fills).

        Args:
            symbol: Optional symbol filter
            limit: Number of records to retrieve (max 100)
            skip_cache: If True, bypass internal micro-cache

        Returns:
            Standard success/error dict with execution data
        """
        if self.stream_service and not skip_cache:
            if symbol:
                self.stream_service.ensure_symbol(symbol)
            stream_resp = self.stream_service.get_executions_response(
                symbol=symbol,
                limit=limit,
            )
            if stream_resp:
                return stream_resp

        params = {
            "category": "linear",
            "limit": limit,
        }
        if symbol:
            params["symbol"] = symbol
        request_started_at = time.time()
        response = self._request(
            "GET", "/v5/execution/list", params=params, skip_cache=skip_cache
        )
        if response.get("success") and self.stream_service and hasattr(
            self.stream_service, "seed_executions_snapshot"
        ):
            try:
                expected_epoch = cache_seed_expected_epoch
                if expected_epoch is None and hasattr(
                    self.stream_service, "get_private_reconnect_epoch"
                ):
                    expected_epoch = self.stream_service.get_private_reconnect_epoch()
                self.stream_service.seed_executions_snapshot(
                    (response.get("data", {}) or {}).get("list", []) or [],
                    symbol=symbol,
                    expected_epoch=expected_epoch,
                    snapshot_started_at=request_started_at,
                    snapshot_received_at=time.time(),
                    source=cache_seed_source
                    or ("rest_fetch" if skip_cache else "rest_fallback"),
                    is_reconcile=str(cache_seed_source or "").strip().lower() == "reconcile",
                )
            except Exception:
                logger.debug(
                    "[%s] Failed to seed stream executions snapshot",
                    symbol or "*",
                    exc_info=True,
                )
        return response

    def close_position(self, symbol: str) -> Dict[str, Any]:
        """
        Close any open position for symbol via reduce-only market order.
        """
        try:
            positions_resp = self.get_positions(skip_cache=True)
            if not positions_resp.get("success"):
                return {
                    "success": False,
                    "error": positions_resp.get("error", "positions_fetch_failed"),
                    "retCode": positions_resp.get("retCode", -1),
                }

            positions = positions_resp.get("data", {}).get("list", []) or []
            closed_any = False
            filters = self.get_qty_filters(symbol)

            for pos in positions:
                if pos.get("symbol") != symbol:
                    continue
                side = pos.get("side")
                size = float(pos.get("size", 0) or 0)
                if not side or size <= 0:
                    continue

                close_side = "Sell" if side.lower() == "buy" else "Buy"
                position_idx = int(pos.get("positionIdx", 0) or 0)
                normalized_qty = self.normalize_qty(symbol, size, log_skip=False)
                if not normalized_qty:
                    self._log_skip_order(
                        symbol=symbol,
                        raw_qty=size,
                        normalized_qty=normalized_qty,
                        min_qty=filters.get("min_qty"),
                        qty_step=filters.get("qty_step"),
                        price=None,
                    )
                    return {"success": False, "error": "qty_below_min", "retCode": -1}

                result = self.create_order(
                    symbol=symbol,
                    side=close_side,
                    qty=normalized_qty,
                    order_type="Market",
                    price=None,
                    reduce_only=True,
                    time_in_force="GTC",
                    order_link_id=f"close_manual_{int(time.time() * 1000)}",
                    position_idx=position_idx,
                    qty_is_normalized=True,
                )
                if not result.get("success"):
                    logger.error(
                        "[%s] close_position failed: %s", symbol, result.get("error")
                    )
                    return result
                closed_any = True

            if not closed_any:
                return {"success": True, "message": "no_position", "retCode": 0}

            return {"success": True, "message": "position_closed", "retCode": 0}
        except Exception as e:
            logger.error("[%s] close_position exception: %s", symbol, e)
            return {"success": False, "error": str(e), "retCode": -1}

    def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """
        Cancel all open orders for a given symbol.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")

        Returns:
            Standard success/error dict
        """
        body = {
            "category": "linear",
            "symbol": symbol,
        }
        cancel_started_at = time.time()
        result = self._run_order_command(
            symbol,
            "cancel_all_orders",
            lambda: self._request("POST", "/v5/order/cancel-all", body=body),
        )
        cancel_completed_at = time.time()
        result = merge_result_timing(
            result,
            cancel_request_sent_at=iso_from_ts(cancel_started_at),
            cancel_request_ack_at=iso_from_ts(cancel_completed_at),
            cancel_request_to_ack_ms=elapsed_ms(cancel_started_at, cancel_completed_at),
            cancel_action="cancel_all_orders",
        )

        # Invalidate caches after cancellation
        if result.get("success") or self._is_ambiguous_order_action_result(result):
            result = self._invalidate_after_order_write(
                symbol,
                action="cancel_all_orders",
                result=result,
                clear_symbol_hints=True,
            )

        return result

    def create_batch_orders(
        self,
        symbol: str,
        orders: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Place up to 20 orders in a single Bybit API call.

        Each entry in *orders* must contain:
            side, qty (already normalized), order_type, price (for Limit),
            reduce_only, time_in_force, order_link_id, position_idx (optional),
            ownership_snapshot (optional).

        Returns:
            { "success": True/False, "results": [ per-order result dicts ] }
        """
        if not orders:
            return {"success": True, "results": [], "placed": 0, "failed": 0}

        # Build the batch request body (max 20 per Bybit docs)
        request_list: list = []
        meta_list: list = []  # ownership snapshots parallel to request_list
        for entry in orders[:20]:
            body: Dict[str, Any] = {
                "symbol": symbol,
                "side": entry["side"],
                "orderType": entry.get("order_type", "Limit"),
                "qty": f'{float(entry["qty"]):f}'.rstrip("0").rstrip("."),
                "timeInForce": entry.get("time_in_force", "GTC"),
                "reduceOnly": bool(entry.get("reduce_only", False)),
            }
            if entry.get("price") is not None and body["orderType"] == "Limit":
                body["price"] = str(entry["price"])
            if entry.get("order_link_id"):
                body["orderLinkId"] = entry["order_link_id"]
            if entry.get("position_idx") is not None:
                body["positionIdx"] = int(entry["position_idx"])
            request_list.append(body)
            meta_list.append(entry.get("ownership_snapshot"))

        batch_body = {"category": "linear", "request": request_list}

        submit_started_at = time.time()
        # Route through order router to preserve per-symbol serialization
        result = self._run_order_command(
            symbol,
            "create_batch_orders",
            lambda: self._request("POST", "/v5/order/create-batch", body=batch_body),
        )
        submit_completed_at = time.time()
        batch_ms = round((submit_completed_at - submit_started_at) * 1000, 1)

        # Parse per-order results from Bybit response
        per_order_results: list = []
        placed = 0
        failed = 0

        if result.get("success"):
            result_list = (result.get("data") or {}).get("list") or []
            ext_list = (result.get("data") or {}).get("retExtInfo", {}).get("list") or (
                result.get("retExtInfo", {}).get("list") or []
            )
            for idx, req in enumerate(request_list):
                order_data = result_list[idx] if idx < len(result_list) else {}
                ext_data = ext_list[idx] if idx < len(ext_list) else {}
                ext_code = int(ext_data.get("code", 0) or 0)
                order_success = ext_code == 0

                entry_result: Dict[str, Any] = {
                    "success": order_success,
                    "order_id": order_data.get("orderId"),
                    "order_link_id": order_data.get("orderLinkId") or req.get("orderLinkId"),
                    "side": req.get("side"),
                    "price": req.get("price"),
                    "qty": req.get("qty"),
                    "reduce_only": req.get("reduceOnly", False),
                    "batch_index": idx,
                    "batch_ms": batch_ms,
                }
                if not order_success:
                    entry_result["error"] = ext_data.get("msg") or "batch_order_failed"
                    entry_result["retCode"] = ext_code
                    failed += 1
                else:
                    placed += 1
                    # Record ownership + forensics for successful orders
                    ownership = meta_list[idx] if idx < len(meta_list) else None
                    self._record_batch_order_ownership(
                        symbol, req, order_data, ownership
                    )

                per_order_results.append(entry_result)

            # Invalidate caches after batch placement
            if placed > 0:
                self._invalidate_after_order_write(
                    symbol,
                    action="create_batch_orders",
                    result=result,
                    force_invalidate=True,
                    clear_symbol_hints=True,
                )
        else:
            # Entire batch failed
            for idx, req in enumerate(request_list):
                per_order_results.append({
                    "success": False,
                    "error": result.get("error", "batch_request_failed"),
                    "retCode": result.get("retCode", -1),
                    "side": req.get("side"),
                    "price": req.get("price"),
                    "qty": req.get("qty"),
                    "batch_index": idx,
                })
                failed += 1

        logger.info(
            "[%s] Batch order: %d placed, %d failed in %.0fms (%d submitted)",
            symbol,
            placed,
            failed,
            batch_ms,
            len(request_list),
        )

        return {
            "success": failed == 0 and placed > 0,
            "partial": placed > 0 and failed > 0,
            "results": per_order_results,
            "placed": placed,
            "failed": failed,
            "batch_ms": batch_ms,
            "submitted": len(request_list),
        }

    def _record_batch_order_ownership(
        self,
        symbol: str,
        req: Dict[str, Any],
        order_data: Dict[str, Any],
        ownership: Optional[Dict[str, Any]],
    ) -> None:
        """Record ownership and forensics for a single order in a batch."""
        if not ownership:
            return
        order_link_id = order_data.get("orderLinkId") or req.get("orderLinkId")
        order_id = order_data.get("orderId")
        side = req.get("side", "")
        reduce_only = req.get("reduceOnly", False)
        position_idx = req.get("positionIdx")
        if self.order_ownership_service:
            try:
                record = dict(ownership)
                record.setdefault("action", "reduce_only_close" if reduce_only else "entry")
                record["symbol"] = symbol
                record["side"] = side
                record["position_idx"] = position_idx
                record["reduce_only"] = bool(reduce_only)
                record["order_id"] = str(order_id or "").strip() or None
                record["order_link_id"] = str(order_link_id or "").strip() or None
                self.order_ownership_service.record_order(record)
            except Exception as exc:
                logger.warning(
                    "[%s] Failed to persist batch order ownership for %s: %s",
                    symbol,
                    order_link_id or order_id or "?",
                    exc,
                )

    def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cancel a single order by orderId or orderLinkId.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            order_id: Bybit order ID (either this or order_link_id required)
            order_link_id: Custom order link ID (either this or order_id required)

        Returns:
            Standard success/error dict
        """
        if not order_id and not order_link_id:
            return {
                "success": False,
                "error": "Either orderId or orderLinkId is required",
                "retCode": -1,
            }

        body = {
            "category": "linear",
            "symbol": symbol,
        }

        if order_id:
            body["orderId"] = order_id
        if order_link_id:
            body["orderLinkId"] = order_link_id

        cancel_started_at = time.time()
        result = self._run_order_command(
            symbol,
            "cancel_order",
            lambda: self._request("POST", "/v5/order/cancel", body=body),
        )
        cancel_completed_at = time.time()
        result = merge_result_timing(
            result,
            cancel_request_sent_at=iso_from_ts(cancel_started_at),
            cancel_request_ack_at=iso_from_ts(cancel_completed_at),
            cancel_request_to_ack_ms=elapsed_ms(cancel_started_at, cancel_completed_at),
            cancel_action="cancel_order",
        )

        # Invalidate caches after cancellation
        if result.get("success") or self._is_ambiguous_order_action_result(result):
            result = self._invalidate_after_order_write(
                symbol,
                action="cancel_order",
                result=result,
                clear_order_hint={
                    "order_id": order_id,
                    "order_link_id": order_link_id,
                },
            )

        return result

    def get_closed_pnl(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Get closed PnL records.

        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT")
            limit: Number of records to retrieve (max 100)

        Returns:
            Standard success/error dict with closed PnL data
        """
        params = {
            "category": "linear",
            "limit": limit,
        }
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/v5/position/closed-pnl", params=params)

    def get_instruments_info(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        symbol_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get instrument specifications for linear USDT perpetuals.

        Returns lot size filter (minOrderQty, qtyStep) and price filter (tickSize).

        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT")
            status: Optional instrument status filter
            limit: Optional page size
            cursor: Optional pagination cursor
            symbol_type: Optional Bybit symbolType filter

        Returns:
            Standard success/error dict with instrument info
        """
        params = {
            "category": "linear",
        }
        if symbol:
            params["symbol"] = symbol
        if status:
            params["status"] = status
        if limit:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor
        if symbol_type:
            params["symbolType"] = symbol_type
        return self._request("GET", "/v5/market/instruments-info", params=params)

    def _get_qty_filters(self, symbol: str) -> Optional[Dict[str, float]]:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]

        resp = self.get_instruments_info(symbol)
        if not resp.get("success"):
            logger.warning(
                "[qty_normalize] failed to fetch instrument info for %s: %s",
                symbol,
                resp.get("error"),
            )
            return None

        data = resp.get("data", {}) or {}
        inst_list = data.get("list", []) or []
        if not inst_list:
            logger.warning("[qty_normalize] empty instrument info for %s", symbol)
            return None

        inst = inst_list[0]
        lot_size_filter = inst.get("lotSizeFilter", {}) or {}

        def _to_positive(value: Any) -> Optional[float]:
            try:
                num = float(value)
            except (TypeError, ValueError):
                return None
            return num if num > 0 else None

        min_qty = _to_positive(lot_size_filter.get("minOrderQty"))
        qty_step = _to_positive(lot_size_filter.get("qtyStep"))
        max_qty = _to_positive(lot_size_filter.get("maxOrderQty"))

        if not min_qty or not qty_step:
            logger.warning(
                "[qty_normalize] missing qty filters for %s (minQty=%s, step=%s)",
                symbol,
                min_qty,
                qty_step,
            )
            return None

        filters = {
            "min_qty": min_qty,
            "qty_step": qty_step,
            "max_qty": max_qty,
        }
        self._instrument_cache[symbol] = filters
        return filters

    def get_qty_filters(self, symbol: str) -> Dict[str, Optional[float]]:
        filters = self._get_qty_filters(symbol) or {}
        return {
            "min_qty": filters.get("min_qty"),
            "qty_step": filters.get("qty_step"),
            "max_qty": filters.get("max_qty"),
        }

    def _log_skip_order(
        self,
        symbol: str,
        raw_qty: Optional[float],
        normalized_qty: Optional[float],
        min_qty: Optional[float],
        qty_step: Optional[float],
        price: Optional[float],
    ) -> None:
        notional_qty = normalized_qty if normalized_qty else (raw_qty or 0)
        notional = (price or 0) * notional_qty
        logger.warning(
            "skip_order qty_below_min bot_id=None symbol=%s side=None raw_qty=%s normalized_qty=%s "
            "minQty=%s qtyStep=%s price=%s notional=%s",
            symbol,
            raw_qty,
            normalized_qty,
            min_qty,
            qty_step,
            price,
            notional,
        )

    def normalize_qty(
        self, symbol: str, qty: Optional[float], log_skip: bool = True
    ) -> Optional[float]:
        raw_qty = qty
        if qty is None or qty <= 0:
            if log_skip:
                self._log_skip_order(symbol, raw_qty, None, None, None, None)
            return None

        filters = self._get_qty_filters(symbol)
        if not filters:
            if log_skip:
                self._log_skip_order(symbol, raw_qty, None, None, None, None)
            return None

        min_qty = filters["min_qty"]
        qty_step = filters["qty_step"]
        max_qty = filters.get("max_qty")

        if qty_step <= 0:
            if log_skip:
                self._log_skip_order(symbol, raw_qty, None, min_qty, qty_step, None)
            return None

        step_decimal = Decimal(str(qty_step))
        qty_decimal = Decimal(str(qty))
        precision = max(0, -step_decimal.as_tuple().exponent)
        normalized = float(
            (qty_decimal / step_decimal).to_integral_value(rounding=ROUND_FLOOR)
            * step_decimal
        )
        normalized = round(normalized, precision)

        if max_qty and normalized > max_qty:
            max_qty_decimal = Decimal(str(max_qty))
            normalized = float(
                (
                    max_qty_decimal / step_decimal
                ).to_integral_value(rounding=ROUND_FLOOR)
                * step_decimal
            )
            normalized = round(normalized, precision)

        if normalized < min_qty or normalized <= 0:
            if log_skip:
                self._log_skip_order(
                    symbol, raw_qty, normalized, min_qty, qty_step, None
                )
            return None

        return normalized

    def get_open_orders(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        skip_cache: bool = False,
        cache_seed_source: Optional[str] = None,
        cache_seed_expected_epoch: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get open/unfilled orders for linear USDT perpetuals.

        Args:
            symbol: Optional symbol filter (e.g., "BTCUSDT")
            limit: Number of orders to retrieve (max 50)
            skip_cache: If True, bypass internal micro-cache

        Returns:
            Standard success/error dict with open orders
        """
        if self.stream_service and not skip_cache:
            if symbol:
                self.stream_service.ensure_symbol(symbol)
            stream_resp = self.stream_service.get_open_orders_response(
                symbol=symbol,
                limit=limit,
            )
            if stream_resp:
                return self._merge_recent_open_order_hints(symbol, stream_resp)

        params = {
            "category": "linear",
            "limit": limit,
        }
        if symbol:
            params["symbol"] = symbol
        else:
            params["settleCoin"] = "USDT"
        request_started_at = time.time()
        response = self._request(
            "GET", "/v5/order/realtime", params=params, skip_cache=skip_cache
        )
        response = self._merge_recent_open_order_hints(symbol, response)
        if response.get("success") and self.stream_service and hasattr(
            self.stream_service, "seed_open_orders_snapshot"
        ):
            try:
                expected_epoch = cache_seed_expected_epoch
                if expected_epoch is None and hasattr(
                    self.stream_service, "get_private_reconnect_epoch"
                ):
                    expected_epoch = self.stream_service.get_private_reconnect_epoch()
                self.stream_service.seed_open_orders_snapshot(
                    symbol,
                    (response.get("data", {}) or {}).get("list", []) or [],
                    expected_epoch=expected_epoch,
                    snapshot_started_at=request_started_at,
                    snapshot_received_at=time.time(),
                    source=cache_seed_source
                    or ("rest_fetch" if skip_cache else "rest_fallback"),
                    is_reconcile=str(cache_seed_source or "").strip().lower() == "reconcile",
                )
            except Exception:
                logger.debug(
                    "[%s] Failed to seed stream open order snapshot",
                    symbol or "*",
                    exc_info=True,
                )
        return response

    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account info (used for position mode checks).

        Returns:
            Standard success/error dict with account info data
        """
        return self._request("GET", "/v5/account/info", params={})

    def get_position_mode(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Best-effort query for position mode (hedge vs one-way).

        Returns:
            Dict with:
            - success: bool
            - mode: "hedge" | "one_way" | None
        """
        params = {"category": "linear"}
        if symbol:
            params["symbol"] = symbol
        else:
            params["settleCoin"] = "USDT"

        resp = self._request("GET", "/v5/position/list", params=params)
        if resp.get("success"):
            pos_list = resp.get("data", {}).get("list", []) or []
            idxs = set()
            for pos in pos_list:
                try:
                    idxs.add(int(pos.get("positionIdx", 0) or 0))
                except (TypeError, ValueError):
                    continue
            if idxs:
                if any(idx in (1, 2) for idx in idxs):
                    return {"success": True, "mode": "hedge"}
                if idxs == {0}:
                    return {"success": True, "mode": "one_way"}

        info = self.get_account_info()
        if info.get("success"):
            mode_value = self._find_key_case_insensitive(
                info.get("data"), "positionMode"
            )
            if mode_value is not None:
                try:
                    if isinstance(mode_value, str):
                        if mode_value.isdigit():
                            mode_value = int(mode_value)
                    if isinstance(mode_value, (int, float)):
                        if int(mode_value) == 3:
                            return {"success": True, "mode": "hedge"}
                        if int(mode_value) == 0:
                            return {"success": True, "mode": "one_way"}
                    if isinstance(mode_value, str):
                        value = mode_value.strip().lower()
                        if "hedge" in value or "both" in value:
                            return {"success": True, "mode": "hedge"}
                        if "one" in value or "single" in value:
                            return {"success": True, "mode": "one_way"}
                except Exception:
                    pass

        return {"success": False, "mode": None, "error": "position_mode_unknown"}

    def _find_key_case_insensitive(self, data: Any, key: str) -> Optional[Any]:
        if data is None:
            return None
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and k.lower() == key.lower():
                    return v
                nested = self._find_key_case_insensitive(v, key)
                if nested is not None:
                    return nested
        if isinstance(data, list):
            for item in data:
                nested = self._find_key_case_insensitive(item, key)
                if nested is not None:
                    return nested
        return None

    def set_trading_stop(
        self,
        symbol: str,
        position_idx: int = 0,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        tp_trigger_by: str = "LastPrice",
        sl_trigger_by: str = "LastPrice",
    ) -> Dict[str, Any]:
        """
        Set take profit and/or stop loss for a position.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            position_idx: Position index (0 for one-way mode, 1 for Buy hedge, 2 for Sell hedge)
            take_profit: Take profit price (None to not set/clear)
            stop_loss: Stop loss price (None to not set/clear)
            tp_trigger_by: Trigger price type for TP ("LastPrice", "MarkPrice", "IndexPrice")
            sl_trigger_by: Trigger price type for SL ("LastPrice", "MarkPrice", "IndexPrice")

        Returns:
            Standard success/error dict
        """
        body = {
            "category": "linear",
            "symbol": symbol,
            "positionIdx": position_idx,
        }

        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
            body["tpTriggerBy"] = tp_trigger_by

        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
            body["slTriggerBy"] = sl_trigger_by

        return self._run_order_command(
            symbol,
            "set_trading_stop",
            lambda: self._request("POST", "/v5/position/trading-stop", body=body),
        )

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        Set leverage for a symbol on Bybit.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            leverage: Leverage value (e.g., 3 for 3x)

        Returns:
            Standard success/error dict
        """
        leverage_str = str(int(leverage))
        body = {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": leverage_str,
            "sellLeverage": leverage_str,
        }
        return self._request("POST", "/v5/position/set-leverage", body=body)

    def set_margin_mode(
        self, symbol: str, margin_mode: str = "ISOLATED"
    ) -> Dict[str, Any]:
        """
        Set margin mode for a symbol (ISOLATED or CROSS).

        Bybit V5 API: POST /v5/position/switch-isolated
        See: https://bybit-exchange.github.io/docs/v5/position/cross-isolated

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            margin_mode: "ISOLATED" or "CROSS"

        Returns:
            Standard success/error dict

        Note:
            - retCode 110026 means position mode already set (not an error)
            - This is required to enforce ISOLATED margin for safety
        """
        # tradeMode: 0 = cross margin, 1 = isolated margin
        trade_mode = 1 if margin_mode.upper() == "ISOLATED" else 0
        body = {
            "category": "linear",
            "symbol": symbol,
            "tradeMode": trade_mode,
            "buyLeverage": "1",  # Required by API but leverage is set separately; use 1x as safe default
            "sellLeverage": "1",
        }
        return self._request("POST", "/v5/position/switch-isolated", body=body)

    def set_auto_add_margin(
        self, symbol: str, auto_add_margin: int = 1, position_idx: int = 0
    ) -> Dict[str, Any]:
        """
        Turn on/off Bybit's built-in auto-add-margin for an isolated position.

        Notes:
            - This is the exchange-level feature (not the bot's smart auto-margin logic).
            - 0: off, 1: on

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            auto_add_margin: 0 or 1
            position_idx: 0 for one-way mode, 1 for Buy hedge, 2 for Sell hedge

        Returns:
            Standard success/error dict
        """
        body = {
            "category": "linear",
            "symbol": symbol,
            "autoAddMargin": int(auto_add_margin),
            "positionIdx": int(position_idx),
        }
        return self._request("POST", "/v5/position/set-auto-add-margin", body=body)

    def add_or_reduce_margin(
        self, symbol: str, margin: float, position_idx: int = 0
    ) -> Dict[str, Any]:
        """
        Manually add (positive) or reduce (negative) margin for an isolated position.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            margin: Positive to add, negative to reduce (supports up to 4 decimals)
            position_idx: 0 for one-way mode, 1 for Buy hedge, 2 for Sell hedge

        Returns:
            Standard success/error dict
        """
        body = {
            "category": "linear",
            "symbol": symbol,
            "margin": str(round(float(margin), 4)),
            "positionIdx": int(position_idx),
        }
        return self._request("POST", "/v5/position/add-margin", body=body)

    def switch_position_mode(self, symbol: str, mode: int = 3) -> Dict[str, Any]:
        """
        Switch position mode for a symbol.
        Bybit V5: POST /v5/position/switch-mode

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            mode: 0 (One-Way) or 3 (Hedge Mode)

        Returns:
            Standard success/error dict
        """
        body = {
            "category": "linear",
            "symbol": symbol,
            "mode": int(mode),
        }
        return self._request("POST", "/v5/position/switch-mode", body=body)
