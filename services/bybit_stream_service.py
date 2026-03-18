"""
Bybit low-latency websocket service.

This service complements the existing REST client:
- websocket feeds act as the low-latency signal path
- REST remains the command/fallback path
"""

import hashlib
import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

import websocket


logger = logging.getLogger(__name__)


TERMINAL_ORDER_STATUSES = {
    "Cancelled",
    "Deactivated",
    "Filled",
    "PartiallyFilledCanceled",
    "Rejected",
    "TriggeredCancelled",
}


class BybitStreamService:
    """Threaded websocket cache and event fanout for Bybit V5 streams."""

    DEFAULT_TICKER_MAX_AGE_SEC = 2.5
    DEFAULT_PRIVATE_MAX_AGE_SEC = 5.0
    DEFAULT_EXECUTION_MAX_AGE_SEC = 10.0
    DEFAULT_ORDERBOOK_MAX_AGE_SEC = 2.0
    DEFAULT_KLINE_MAX_AGE_SEC = 90.0
    DEFAULT_ORDERBOOK_DEPTH = 50
    DEFAULT_KLINE_HISTORY_LIMIT = 1000
    DEFAULT_EVENT_TIMEOUT_SEC = 15.0
    DEFAULT_RECENT_EXECUTIONS = 200
    DEFAULT_EVENT_BACKLOG = 1000
    DEFAULT_PING_INTERVAL_SEC = 20
    DEFAULT_PING_TIMEOUT_SEC = 10
    DEFAULT_ACTIVE_KLINE_INTERVALS = ("1", "5", "15", "60")

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str,
        owner_name: str = "default",
        ticker_max_age_sec: float = DEFAULT_TICKER_MAX_AGE_SEC,
        private_max_age_sec: float = DEFAULT_PRIVATE_MAX_AGE_SEC,
        execution_max_age_sec: float = DEFAULT_EXECUTION_MAX_AGE_SEC,
        orderbook_max_age_sec: float = DEFAULT_ORDERBOOK_MAX_AGE_SEC,
        orderbook_depth: int = DEFAULT_ORDERBOOK_DEPTH,
        kline_max_age_sec: float = DEFAULT_KLINE_MAX_AGE_SEC,
        kline_history_limit: int = DEFAULT_KLINE_HISTORY_LIMIT,
        recent_executions_limit: int = DEFAULT_RECENT_EXECUTIONS,
        event_backlog: int = DEFAULT_EVENT_BACKLOG,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.owner_name = owner_name
        self.ticker_max_age_sec = max(float(ticker_max_age_sec or 0), 0.5)
        self.private_max_age_sec = max(float(private_max_age_sec or 0), 1.0)
        self.execution_max_age_sec = max(float(execution_max_age_sec or 0), 1.0)
        self.orderbook_max_age_sec = max(float(orderbook_max_age_sec or 0), 0.5)
        self.orderbook_depth = max(int(orderbook_depth or 1), 1)
        self.kline_max_age_sec = max(float(kline_max_age_sec or 0), 5.0)
        self.kline_history_limit = max(int(kline_history_limit or 0), 50)
        self.recent_executions_limit = max(int(recent_executions_limit or 0), 20)

        self.public_url, self.private_url = self._resolve_ws_urls(base_url)

        self._state_lock = threading.RLock()
        self._event_condition = threading.Condition()
        self._stop_event = threading.Event()
        self._started = False
        self._public_thread: Optional[threading.Thread] = None
        self._private_thread: Optional[threading.Thread] = None
        self._public_ws = None
        self._private_ws = None

        self._public_connected = False
        self._private_connected = False
        self._private_authenticated = False
        # WebSocket trade command correlation
        self._pending_trade_commands: Dict[str, Dict[str, Any]] = {}
        self._pending_trade_lock = threading.Lock()
        self._public_reconnect_epoch = 0
        self._private_reconnect_epoch = 0

        self._desired_ticker_symbols: Set[str] = set()
        self._desired_orderbook_symbols: Set[str] = set()
        self._desired_kline_symbols_by_interval: Dict[str, Set[str]] = defaultdict(set)
        self._subscribed_public_topics: Set[str] = set()
        self._subscribed_private_topics: Set[str] = set()

        self._ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._orderbook_cache: Dict[str, Dict[str, Any]] = {}
        self._kline_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._position_cache: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._open_order_cache: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        self._open_orders_bootstrapped_symbols: Set[str] = set()
        self._open_orders_dirty_symbols: Set[str] = set()
        self._open_orders_bootstrapped_all = False
        self._open_orders_dirty_all = False
        self._recent_order_index: Dict[str, Dict[str, Any]] = {}
        self._recent_order_index_ts: Dict[str, float] = {}
        self._execution_cache_by_symbol: Dict[str, Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self.recent_executions_limit)
        )
        self._execution_cache_global: Deque[Dict[str, Any]] = deque(
            maxlen=self.recent_executions_limit
        )
        self._seen_execution_ids: Dict[str, float] = {}
        self._topic_last_message_at: Dict[str, float] = {
            "ticker": 0.0,
            "orderbook": 0.0,
            "kline": 0.0,
            "position": 0.0,
            "order": 0.0,
            "execution": 0.0,
        }
        self._private_topic_state: Dict[str, Dict[str, Any]] = {
            topic: self._new_private_topic_state()
            for topic in ("position", "order", "execution")
        }

        self._events: Deque[Dict[str, Any]] = deque(maxlen=max(int(event_backlog), 100))
        self._next_event_seq = 1

    @staticmethod
    def _new_private_topic_state() -> Dict[str, Any]:
        return {
            "epoch": 0,
            "bootstrapped": False,
            "source": None,
            "last_event_at": 0.0,
            "last_snapshot_at": 0.0,
            "last_reconcile_at": 0.0,
            "last_update_at": 0.0,
            "snapshot_started_at": 0.0,
        }

    @staticmethod
    def _resolve_ws_urls(base_url: str) -> Tuple[str, str]:
        normalized = (base_url or "").strip().lower()
        if "testnet" in normalized:
            host = "stream-testnet.bybit.com"
        else:
            host = "stream.bybit.com"
        return (
            f"wss://{host}/v5/public/linear",
            f"wss://{host}/v5/private",
        )

    def start(self) -> None:
        """Start public and private websocket worker threads once."""
        with self._state_lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()

            self._public_thread = threading.Thread(
                target=self._run_public_loop,
                name=f"BybitPublicStream[{self.owner_name}]",
                daemon=True,
            )
            self._private_thread = threading.Thread(
                target=self._run_private_loop,
                name=f"BybitPrivateStream[{self.owner_name}]",
                daemon=True,
            )
            self._public_thread.start()
            self._private_thread.start()

    def stop(self) -> None:
        """Stop websocket workers."""
        with self._state_lock:
            self._stop_event.set()
            self._started = False
            public_ws = self._public_ws
            private_ws = self._private_ws
        try:
            if public_ws:
                public_ws.close()
        except Exception:
            pass
        try:
            if private_ws:
                private_ws.close()
        except Exception:
            pass

    def ensure_symbol(
        self,
        symbol: str,
        include_orderbook: bool = False,
        kline_intervals: Optional[Iterable[str]] = None,
    ) -> None:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return
        with self._state_lock:
            self._desired_ticker_symbols.add(normalized)
            if include_orderbook:
                self._desired_orderbook_symbols.add(normalized)
            for interval in (kline_intervals or ()):
                normalized_interval = self._normalize_kline_interval(interval)
                if normalized_interval:
                    self._desired_kline_symbols_by_interval[normalized_interval].add(
                        normalized
                    )
        self.start()
        self._sync_public_topics()

    def set_symbol_subscriptions(
        self,
        ticker_symbols: Iterable[str],
        orderbook_symbols: Optional[Iterable[str]] = None,
        kline_symbols_by_interval: Optional[Dict[str, Iterable[str]]] = None,
    ) -> None:
        desired_tickers = {
            symbol
            for symbol in (self._normalize_symbol(s) for s in ticker_symbols)
            if symbol
        }
        desired_orderbooks = {
            symbol
            for symbol in (
                self._normalize_symbol(s)
                for s in (orderbook_symbols if orderbook_symbols is not None else [])
            )
            if symbol
        }
        desired_klines: Dict[str, Set[str]] = defaultdict(set)
        for interval, raw_symbols in (kline_symbols_by_interval or {}).items():
            normalized_interval = self._normalize_kline_interval(interval)
            if not normalized_interval:
                continue
            desired_klines[normalized_interval] = {
                symbol
                for symbol in (self._normalize_symbol(s) for s in (raw_symbols or ()))
                if symbol
            }
        with self._state_lock:
            self._desired_ticker_symbols = desired_tickers
            self._desired_orderbook_symbols = desired_orderbooks
            self._desired_kline_symbols_by_interval = defaultdict(set, desired_klines)
        if desired_tickers or desired_orderbooks or desired_klines:
            self.start()
        self._sync_public_topics()

    def get_ticker_response(
        self,
        symbol: str,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return None
        snapshot = self.get_ticker_snapshot(normalized, max_age_sec=max_age_sec)
        if not snapshot:
            return None
        return {
            "success": True,
            "from_stream": True,
            "data": {
                "category": "linear",
                "list": [snapshot],
            },
        }

    def get_ticker_snapshot(
        self,
        symbol: str,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        age_limit = (
            self.ticker_max_age_sec if max_age_sec is None else max(float(max_age_sec), 0.1)
        )
        with self._state_lock:
            cached = self._ticker_cache.get(symbol)
            if not cached:
                return None
            if time.time() - cached.get("received_at", 0.0) > age_limit:
                return None
            return dict(cached.get("data") or {})

    def get_ticker_rows(
        self,
        symbols: Iterable[str],
        max_age_sec: Optional[float] = None,
    ) -> Dict[str, Dict[str, Any]]:
        age_limit = (
            self.ticker_max_age_sec
            if max_age_sec is None
            else max(float(max_age_sec or 0.0), 0.1)
        )
        normalized_symbols = [
            symbol for symbol in (self._normalize_symbol(s) for s in (symbols or [])) if symbol
        ]
        if not normalized_symbols:
            return {}

        now_ts = time.time()
        rows: Dict[str, Dict[str, Any]] = {}
        with self._state_lock:
            for symbol in normalized_symbols:
                cached = self._ticker_cache.get(symbol)
                if not cached:
                    continue
                received_at = float(cached.get("received_at") or 0.0)
                if received_at <= 0 or (now_ts - received_at) > age_limit:
                    continue
                row = dict(cached.get("data") or {})
                row["_received_at"] = received_at
                rows[symbol] = row
        return rows

    def get_last_price(
        self,
        symbol: str,
        max_age_sec: Optional[float] = None,
    ) -> Optional[float]:
        metadata = self.get_last_price_metadata(symbol, max_age_sec=max_age_sec)
        if metadata:
            return metadata.get("price")
        snapshot = self.get_ticker_snapshot(symbol, max_age_sec=max_age_sec)
        if not snapshot:
            return None
        return self._extract_last_price_from_ticker(snapshot)

    @classmethod
    def _extract_last_price_from_ticker(
        cls,
        snapshot: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        if not isinstance(snapshot, dict):
            return None
        try:
            value = float(snapshot.get("lastPrice", 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
        try:
            bid = float(snapshot.get("bid1Price", 0) or 0)
            ask = float(snapshot.get("ask1Price", 0) or 0)
        except (TypeError, ValueError):
            return None
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        if bid > 0:
            return bid
        if ask > 0:
            return ask
        return None

    def get_last_price_metadata(
        self,
        symbol: str,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return None
        age_limit = (
            self.ticker_max_age_sec
            if max_age_sec is None
            else max(float(max_age_sec), 0.1)
        )
        ticker_metadata = None
        with self._state_lock:
            cached = self._ticker_cache.get(normalized)
            if not cached:
                cached = None
            if cached:
                received_at = float(cached.get("received_at") or 0.0)
                if received_at > 0 and (time.time() - received_at) <= age_limit:
                    snapshot = dict(cached.get("data") or {})
                    price = self._extract_last_price_from_ticker(snapshot)
                    if price is not None and price > 0:
                        exchange_ts = None
                        for key in ("ts", "time", "timestamp"):
                            raw = snapshot.get(key)
                            try:
                                numeric = float(raw)
                            except (TypeError, ValueError):
                                continue
                            if numeric > 10_000_000_000:
                                numeric /= 1000.0
                            if numeric > 0:
                                exchange_ts = numeric
                                break
                        ticker_metadata = {
                            "symbol": normalized,
                            "price": price,
                            "received_at": received_at,
                            "exchange_ts": exchange_ts,
                            "transport": "stream_ticker",
                            "source": "ticker_cache",
                        }

        orderbook_metadata = self.get_orderbook_price_metadata(
            normalized,
            max_age_sec=max_age_sec,
        )
        if orderbook_metadata:
            orderbook_ts = float(orderbook_metadata.get("received_at") or 0.0)
            ticker_ts = float((ticker_metadata or {}).get("received_at") or 0.0)
            if ticker_metadata is None or orderbook_ts > (ticker_ts + 0.001):
                return orderbook_metadata
        return ticker_metadata

    def get_orderbook_price_metadata(
        self,
        symbol: str,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return None
        age_limit = (
            self.orderbook_max_age_sec
            if max_age_sec is None
            else max(float(max_age_sec), 0.1)
        )
        now_ts = time.time()
        with self._state_lock:
            cached = self._orderbook_cache.get(normalized)
            if not cached:
                return None
            received_at = float(cached.get("received_at") or 0.0)
            if received_at <= 0 or (now_ts - received_at) > age_limit:
                return None
            bids = dict(cached.get("bids") or {})
            asks = dict(cached.get("asks") or {})
            exchange_ts = cached.get("exchange_ts")
        best_bid = self._best_book_price(bids, reverse=True)
        best_ask = self._best_book_price(asks, reverse=False)
        if best_bid is None and best_ask is None:
            return None
        if best_bid is not None and best_ask is not None:
            price = (best_bid + best_ask) / 2.0
        else:
            price = best_bid or best_ask
        if price is None or price <= 0:
            return None
        return {
            "symbol": normalized,
            "price": price,
            "bid_price": best_bid,
            "ask_price": best_ask,
            "received_at": received_at,
            "exchange_ts": exchange_ts,
            "transport": "stream_orderbook",
            "source": "orderbook_mid",
        }

    @staticmethod
    def _best_book_price(side: Dict[str, str], *, reverse: bool) -> Optional[float]:
        best_price = None
        for raw_price, raw_size in dict(side or {}).items():
            try:
                price = float(raw_price)
                size = float(raw_size)
            except (TypeError, ValueError):
                continue
            if price <= 0 or size <= 0:
                continue
            if best_price is None:
                best_price = price
            elif reverse and price > best_price:
                best_price = price
            elif not reverse and price < best_price:
                best_price = price
        return best_price

    def get_positions_response(
        self,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._is_private_topic_fresh("position", max_age_sec=max_age_sec):
            return None
        with self._state_lock:
            positions = [dict(value) for value in self._position_cache.values()]
        return {
            "success": True,
            "from_stream": True,
            "data": {
                "category": "linear",
                "list": positions,
            },
        }

    def get_positions_fresh(
        self,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.get_positions_response(max_age_sec=max_age_sec)

    def get_open_orders_response(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._is_private_topic_fresh("order", max_age_sec=max_age_sec):
            return None
        normalized = self._normalize_symbol(symbol) if symbol else None
        with self._state_lock:
            if normalized:
                if (
                    self._open_orders_dirty_all
                    or normalized in self._open_orders_dirty_symbols
                    or normalized not in self._open_orders_bootstrapped_symbols
                ):
                    return None
            elif self._open_orders_dirty_all or not self._open_orders_bootstrapped_all:
                return None
            if normalized:
                orders = list(self._open_order_cache.get(normalized, {}).values())
            else:
                orders = []
                for by_symbol in self._open_order_cache.values():
                    orders.extend(by_symbol.values())
            orders = [dict(order) for order in orders[: max(int(limit or 0), 1)]]
        return {
            "success": True,
            "from_stream": True,
            "data": {
                "category": "linear",
                "list": orders,
            },
        }

    def get_open_orders_fresh(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.get_open_orders_response(
            symbol=symbol,
            limit=limit,
            max_age_sec=max_age_sec,
        )

    def mark_open_orders_dirty(self, symbol: Optional[str] = None) -> None:
        normalized = self._normalize_symbol(symbol) if symbol else None
        with self._state_lock:
            if normalized:
                self._open_orders_dirty_symbols.add(normalized)
            else:
                self._open_orders_dirty_all = True
            state = self._private_topic_state.get("order")
            if state is not None:
                state["source"] = "dirty"

    def mark_positions_dirty(self) -> None:
        with self._state_lock:
            self._invalidate_private_topic_locked("position", "dirty")

    def mark_executions_dirty(self) -> None:
        with self._state_lock:
            self._invalidate_private_topic_locked("execution", "dirty")

    def seed_open_orders_snapshot(
        self,
        symbol: Optional[str],
        orders: Optional[Iterable[Dict[str, Any]]],
        *,
        expected_epoch: Optional[int] = None,
        snapshot_started_at: Optional[float] = None,
        snapshot_received_at: Optional[float] = None,
        source: str = "rest_seed",
        is_reconcile: bool = False,
    ) -> None:
        rows = list(orders or [])
        normalized = self._normalize_symbol(symbol) if symbol else None
        now = float(snapshot_received_at or time.time())
        with self._state_lock:
            if not self._private_epoch_matches_locked(expected_epoch):
                return
            merge_only = self._should_merge_snapshot_locked(
                "order",
                snapshot_started_at=snapshot_started_at,
            )
            if normalized:
                seeded_by_id: Dict[str, Dict[str, Any]] = (
                    dict(self._open_order_cache.get(normalized, {}))
                    if merge_only
                    else {}
                )
                for row in rows:
                    row_symbol = self._normalize_symbol(row.get("symbol") or normalized)
                    if row_symbol != normalized:
                        continue
                    order_id = str(row.get("orderId") or "").strip()
                    if not order_id:
                        continue
                    order_copy = dict(row)
                    order_copy["symbol"] = normalized
                    self._recent_order_index[order_id] = order_copy
                    self._recent_order_index_ts[order_id] = now
                    if self._is_order_open(order_copy):
                        seeded_by_id[order_id] = order_copy
                    elif not merge_only:
                        seeded_by_id.pop(order_id, None)
                self._open_order_cache[normalized] = seeded_by_id
                self._open_orders_bootstrapped_symbols.add(normalized)
                self._open_orders_dirty_symbols.discard(normalized)
                self._record_private_topic_snapshot_locked(
                    "order",
                    received_at=now,
                    source=source,
                    snapshot_started_at=snapshot_started_at,
                    is_reconcile=is_reconcile,
                )
                self._prune_recent_order_index_locked(now)
                return

            rebuilt: Dict[str, Dict[str, Dict[str, Any]]] = (
                defaultdict(dict, {sym: dict(rows_by_id) for sym, rows_by_id in self._open_order_cache.items()})
                if merge_only
                else defaultdict(dict)
            )
            bootstrapped_symbols: Set[str] = (
                set(self._open_orders_bootstrapped_symbols)
                if merge_only
                else set()
            )
            for row in rows:
                row_symbol = self._normalize_symbol(row.get("symbol"))
                order_id = str(row.get("orderId") or "").strip()
                if not row_symbol or not order_id:
                    continue
                order_copy = dict(row)
                order_copy["symbol"] = row_symbol
                self._recent_order_index[order_id] = order_copy
                self._recent_order_index_ts[order_id] = now
                bootstrapped_symbols.add(row_symbol)
                if self._is_order_open(order_copy):
                    rebuilt[row_symbol][order_id] = order_copy
                elif not merge_only:
                    rebuilt[row_symbol].pop(order_id, None)
            self._open_order_cache = defaultdict(dict, rebuilt)
            self._open_orders_bootstrapped_symbols = bootstrapped_symbols
            if not merge_only:
                self._open_orders_dirty_symbols.clear()
                self._open_orders_bootstrapped_all = True
                self._open_orders_dirty_all = False
            self._record_private_topic_snapshot_locked(
                "order",
                received_at=now,
                source=source,
                snapshot_started_at=snapshot_started_at,
                is_reconcile=is_reconcile,
            )
            self._prune_recent_order_index_locked(now)

    def get_executions_response(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        age_limit = self.execution_max_age_sec if max_age_sec is None else max_age_sec
        if not self._is_private_topic_fresh("execution", max_age_sec=age_limit):
            return None
        normalized = self._normalize_symbol(symbol) if symbol else None
        with self._state_lock:
            if normalized:
                execution_list = list(
                    self._execution_cache_by_symbol.get(normalized, deque())
                )
            else:
                execution_list = list(self._execution_cache_global)
            trimmed = [dict(item) for item in execution_list[: max(int(limit or 0), 1)]]
        return {
            "success": True,
            "from_stream": True,
            "data": {
                "category": "linear",
                "list": trimmed,
            },
        }

    def get_recent_executions_fresh(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.get_executions_response(
            symbol=symbol,
            limit=limit,
            max_age_sec=max_age_sec,
        )

    def seed_positions_snapshot(
        self,
        positions: Optional[Iterable[Dict[str, Any]]],
        *,
        expected_epoch: Optional[int] = None,
        snapshot_started_at: Optional[float] = None,
        snapshot_received_at: Optional[float] = None,
        source: str = "rest_seed",
        is_reconcile: bool = False,
    ) -> None:
        rows = list(positions or [])
        now = float(snapshot_received_at or time.time())
        with self._state_lock:
            if not self._private_epoch_matches_locked(expected_epoch):
                return
            merge_only = self._should_merge_snapshot_locked(
                "position",
                snapshot_started_at=snapshot_started_at,
            )
            rebuilt: Dict[Tuple[str, int], Dict[str, Any]] = (
                dict(self._position_cache) if merge_only else {}
            )
            for row in rows:
                symbol = self._normalize_symbol(row.get("symbol"))
                if not symbol:
                    continue
                try:
                    position_idx = int(row.get("positionIdx", 0) or 0)
                except (TypeError, ValueError):
                    position_idx = 0
                row_copy = dict(row)
                row_copy["symbol"] = symbol
                row_copy["positionIdx"] = position_idx
                rebuilt[(symbol, position_idx)] = row_copy
            self._position_cache = rebuilt
            self._record_private_topic_snapshot_locked(
                "position",
                received_at=now,
                source=source,
                snapshot_started_at=snapshot_started_at,
                is_reconcile=is_reconcile,
            )

    def seed_executions_snapshot(
        self,
        executions: Optional[Iterable[Dict[str, Any]]],
        *,
        symbol: Optional[str] = None,
        expected_epoch: Optional[int] = None,
        snapshot_started_at: Optional[float] = None,
        snapshot_received_at: Optional[float] = None,
        source: str = "rest_seed",
        is_reconcile: bool = False,
    ) -> None:
        rows = list(executions or [])
        now = float(snapshot_received_at or time.time())
        normalized_symbol = self._normalize_symbol(symbol) if symbol else None
        with self._state_lock:
            if not self._private_epoch_matches_locked(expected_epoch):
                return
            merge_only = self._should_merge_snapshot_locked(
                "execution",
                snapshot_started_at=snapshot_started_at,
            )
            global_rows: List[Dict[str, Any]]
            by_symbol: Dict[str, List[Dict[str, Any]]]
            if merge_only:
                global_rows = [dict(item) for item in self._execution_cache_global]
                by_symbol = {
                    sym: [dict(item) for item in queue]
                    for sym, queue in self._execution_cache_by_symbol.items()
                }
            else:
                global_rows = []
                by_symbol = {}

            global_seen = {
                str(item.get("execId") or item.get("exec_id") or "").strip()
                for item in global_rows
                if str(item.get("execId") or item.get("exec_id") or "").strip()
            }

            for row in sorted(rows, key=self._execution_sort_key):
                exec_id = str(row.get("execId") or row.get("exec_id") or "").strip()
                if not exec_id or exec_id in global_seen:
                    continue
                order_id = str(row.get("orderId") or "").strip()
                order_link_id = row.get("orderLinkId") or row.get("order_link_id")
                if (not order_link_id) and order_id:
                    mapped = self._recent_order_index.get(order_id) or {}
                    order_link_id = mapped.get("orderLinkId")
                row_copy = dict(row)
                if order_link_id:
                    row_copy["orderLinkId"] = order_link_id
                row_symbol = self._normalize_symbol(
                    row_copy.get("symbol") or normalized_symbol
                )
                if row_symbol:
                    row_copy["symbol"] = row_symbol
                row_copy["_received_at"] = now
                global_rows.append(row_copy)
                global_seen.add(exec_id)
                self._seen_execution_ids[exec_id] = now
                if row_symbol:
                    by_symbol.setdefault(row_symbol, []).append(row_copy)

            global_rows.sort(key=self._execution_sort_key, reverse=True)
            global_rows = global_rows[: self.recent_executions_limit]
            self._execution_cache_global = deque(global_rows, maxlen=self.recent_executions_limit)

            rebuilt_symbol_cache: Dict[str, Deque[Dict[str, Any]]] = defaultdict(
                lambda: deque(maxlen=self.recent_executions_limit)
            )
            if merge_only:
                for sym, items in by_symbol.items():
                    items.sort(key=self._execution_sort_key, reverse=True)
                    rebuilt_symbol_cache[sym] = deque(
                        items[: self.recent_executions_limit],
                        maxlen=self.recent_executions_limit,
                    )
            else:
                for row in global_rows:
                    row_symbol = self._normalize_symbol(row.get("symbol"))
                    if not row_symbol:
                        continue
                    rebuilt_symbol_cache[row_symbol].append(row)
            self._execution_cache_by_symbol = rebuilt_symbol_cache
            self._record_private_topic_snapshot_locked(
                "execution",
                received_at=now,
                source=source,
                snapshot_started_at=snapshot_started_at,
                is_reconcile=is_reconcile,
            )
            self._prune_seen_execution_ids_locked(now)

    def get_orderbook_snapshot(
        self,
        symbol: str,
        max_age_sec: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return None
        age_limit = (
            self.orderbook_max_age_sec
            if max_age_sec is None
            else max(float(max_age_sec), 0.1)
        )
        with self._state_lock:
            cached = self._orderbook_cache.get(normalized)
            if not cached:
                return None
            if time.time() - cached.get("received_at", 0.0) > age_limit:
                return None
            depth = max(int(limit or self.orderbook_depth), 1)
            bids = self._format_book_side(cached.get("bids") or {}, reverse=True, limit=depth)
            asks = self._format_book_side(cached.get("asks") or {}, reverse=False, limit=depth)
            return {
                "bids": bids,
                "asks": asks,
                "timestamp": int(cached.get("exchange_ts", 0) or 0),
                "update_id": cached.get("update_id", 0),
            }

    def get_kline_response(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_interval = self._normalize_kline_interval(interval)
        if not normalized_symbol or not normalized_interval:
            return None
        age_limit = (
            self.kline_max_age_sec
            if max_age_sec is None
            else max(float(max_age_sec or 0.0), 1.0)
        )
        with self._state_lock:
            cached = self._kline_cache.get((normalized_symbol, normalized_interval))
            if not cached:
                return None
            received_at = float(cached.get("received_at") or 0.0)
            rows = list(cached.get("rows") or [])
            if received_at <= 0 or (time.time() - received_at) > age_limit:
                return None
            requested_limit = max(int(limit or 0), 1)
            if len(rows) < requested_limit:
                return None
            result_rows = [
                [
                    str(int(row.get("start") or 0)),
                    str(row.get("open") or "0"),
                    str(row.get("high") or "0"),
                    str(row.get("low") or "0"),
                    str(row.get("close") or "0"),
                    str(row.get("volume") or "0"),
                    str(row.get("turnover") or "0"),
                ]
                for row in reversed(rows[-requested_limit:])
            ]
        return {
            "success": True,
            "from_stream": True,
            "data": {
                "category": "linear",
                "symbol": normalized_symbol,
                "list": result_rows,
            },
        }

    def seed_kline_snapshot(
        self,
        symbol: str,
        interval: str,
        candles: Optional[Iterable[Dict[str, Any]]],
        *,
        received_at: Optional[float] = None,
        source: str = "rest_seed",
    ) -> None:
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_interval = self._normalize_kline_interval(interval)
        if not normalized_symbol or not normalized_interval:
            return
        now = float(received_at or time.time())
        rebuilt_rows: List[Dict[str, Any]] = []
        for candle in candles or []:
            row = self._coerce_seed_kline_row(
                normalized_symbol,
                normalized_interval,
                candle,
            )
            if row is not None:
                rebuilt_rows.append(row)
        if not rebuilt_rows:
            return
        rebuilt_rows.sort(key=lambda item: int(item.get("start") or 0))
        rebuilt_rows = rebuilt_rows[-self.kline_history_limit :]
        with self._state_lock:
            self._kline_cache[(normalized_symbol, normalized_interval)] = {
                "rows": rebuilt_rows,
                "received_at": now,
                "source": source,
                "last_confirmed_at": max(
                    (
                        float(row.get("_received_at") or now)
                        for row in rebuilt_rows
                        if bool(row.get("confirm"))
                    ),
                    default=0.0,
                ),
            }

    def get_health_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return {
                "public_connected": self._public_connected,
                "private_connected": self._private_connected,
                "private_authenticated": self._private_authenticated,
                "public_reconnect_epoch": self._public_reconnect_epoch,
                "private_reconnect_epoch": self._private_reconnect_epoch,
                "desired_ticker_symbols": sorted(self._desired_ticker_symbols),
                "desired_orderbook_symbols": sorted(self._desired_orderbook_symbols),
                "desired_kline_symbols_by_interval": {
                    interval: sorted(symbols)
                    for interval, symbols in self._desired_kline_symbols_by_interval.items()
                    if symbols
                },
                "topic_last_message_at": dict(self._topic_last_message_at),
                "private_cache": {
                    topic: self._build_private_topic_status_locked(topic)
                    for topic in ("position", "order", "execution")
                },
                "public_url": self.public_url,
                "private_url": self.private_url,
            }

    def get_private_reconnect_epoch(self) -> int:
        with self._state_lock:
            return int(self._private_reconnect_epoch or 0)

    def is_topic_fresh(
        self,
        topic: str,
        max_age_sec: Optional[float] = None,
    ) -> bool:
        normalized = str(topic or "").strip().lower()
        if normalized in {"execution", "order", "position"}:
            return self._is_private_topic_fresh(normalized, max_age_sec=max_age_sec)
        with self._state_lock:
            last_message_at = self._topic_last_message_at.get(normalized, 0.0)
            if normalized == "kline":
                default_age = self.kline_max_age_sec
            elif normalized == "orderbook":
                default_age = self.orderbook_max_age_sec
            else:
                default_age = self.ticker_max_age_sec
        age_limit = default_age if max_age_sec is None else max(float(max_age_sec or 0), 0.1)
        return last_message_at > 0 and (time.time() - last_message_at) <= age_limit

    def has_fresh_private_state(
        self,
        topics: Iterable[str] = ("execution", "order", "position"),
        max_age_sec: Optional[float] = None,
    ) -> bool:
        return all(
            self.is_topic_fresh(topic, max_age_sec=max_age_sec)
            for topic in (topics or ())
        )

    def get_dashboard_snapshot(self, symbols: Iterable[str]) -> Dict[str, Any]:
        normalized_symbols = [
            symbol for symbol in (self._normalize_symbol(s) for s in symbols) if symbol
        ]
        ticker_rows = self.get_ticker_rows(normalized_symbols)
        prices: Dict[str, Any] = {}
        price_received_at: Dict[str, float] = {}
        for symbol in normalized_symbols:
            ticker = ticker_rows.get(symbol)
            if not ticker:
                continue
            prices[symbol] = {
                "lastPrice": ticker.get("lastPrice"),
                "bid1Price": ticker.get("bid1Price"),
                "ask1Price": ticker.get("ask1Price"),
            }
            received_at = float(ticker.get("_received_at") or 0.0)
            if received_at > 0:
                price_received_at[symbol] = received_at
        missing_symbols = [
            symbol for symbol in normalized_symbols if symbol not in ticker_rows
        ]
        topic_fresh = self.is_topic_fresh("ticker") if normalized_symbols else None
        return {
            "health": self.get_health_snapshot(),
            "prices": prices,
            "symbols": normalized_symbols,
            "price_received_at": price_received_at,
            "fresh_symbol_count": len(prices),
            "requested_symbol_count": len(normalized_symbols),
            "missing_symbols": missing_symbols,
            "stale_data": bool(normalized_symbols)
            and (bool(missing_symbols) or not bool(topic_fresh)),
            "ticker_topic_fresh": (
                bool(topic_fresh) if topic_fresh is not None else None
            ),
        }

    def wait_for_events(
        self,
        after_seq: int,
        timeout_sec: float = DEFAULT_EVENT_TIMEOUT_SEC,
    ) -> List[Dict[str, Any]]:
        deadline = time.time() + max(float(timeout_sec or 0), 0.1)
        with self._event_condition:
            while True:
                events = [event for event in self._events if event["seq"] > after_seq]
                if events:
                    return events
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._event_condition.wait(timeout=remaining)

    def get_latest_event_seq(self) -> int:
        with self._event_condition:
            return self._next_event_seq - 1

    def _run_public_loop(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            ws_app = websocket.WebSocketApp(
                self.public_url,
                on_open=self._on_public_open,
                on_message=self._on_public_message,
                on_error=self._on_public_error,
                on_close=self._on_public_close,
            )
            with self._state_lock:
                self._public_ws = ws_app
            try:
                ws_app.run_forever(
                    ping_interval=self.DEFAULT_PING_INTERVAL_SEC,
                    ping_timeout=self.DEFAULT_PING_TIMEOUT_SEC,
                )
            except Exception as exc:
                logger.warning("[%s] Public websocket loop failed: %s", self.owner_name, exc)
            finally:
                with self._state_lock:
                    self._public_connected = False
                    self._subscribed_public_topics.clear()
                    if self._public_ws is ws_app:
                        self._public_ws = None
                self._publish_event("health", self.get_health_snapshot())
            if self._stop_event.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)

    def _run_private_loop(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            ws_app = websocket.WebSocketApp(
                self.private_url,
                on_open=self._on_private_open,
                on_message=self._on_private_message,
                on_error=self._on_private_error,
                on_close=self._on_private_close,
            )
            with self._state_lock:
                self._private_ws = ws_app
            try:
                ws_app.run_forever(
                    ping_interval=self.DEFAULT_PING_INTERVAL_SEC,
                    ping_timeout=self.DEFAULT_PING_TIMEOUT_SEC,
                )
            except Exception as exc:
                logger.warning("[%s] Private websocket loop failed: %s", self.owner_name, exc)
            finally:
                with self._state_lock:
                    self._private_connected = False
                    self._private_authenticated = False
                    self._subscribed_private_topics.clear()
                    if self._private_ws is ws_app:
                        self._private_ws = None
                self._publish_event("health", self.get_health_snapshot())
            if self._stop_event.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)

    def _on_public_open(self, ws_app) -> None:
        with self._state_lock:
            self._public_connected = True
            self._public_reconnect_epoch += 1
            self._subscribed_public_topics.clear()
        logger.info("[%s] Connected to public Bybit stream", self.owner_name)
        self._publish_event("health", self.get_health_snapshot())
        self._sync_public_topics()

    def _on_private_open(self, ws_app) -> None:
        with self._state_lock:
            self._private_connected = True
            self._private_authenticated = False
            self._private_reconnect_epoch += 1
            self._subscribed_private_topics.clear()
            self._open_orders_bootstrapped_symbols.clear()
            self._open_orders_dirty_symbols.clear()
            self._open_orders_bootstrapped_all = False
            self._open_orders_dirty_all = False
            for topic in ("position", "order", "execution"):
                self._invalidate_private_topic_locked(
                    topic,
                    source="reconnect_pending",
                )
        logger.info("[%s] Connected to private Bybit stream", self.owner_name)
        self._publish_event("health", self.get_health_snapshot())
        self._send_json(ws_app, self._build_auth_payload())

    def _on_public_message(self, _ws_app, message: str) -> None:
        payload = self._decode_message(message)
        if not payload:
            return
        topic = payload.get("topic", "")
        if not topic:
            return
        if topic.startswith("tickers."):
            self._handle_ticker_message(payload)
            self._note_topic_message("ticker")
        elif topic.startswith("orderbook."):
            self._handle_orderbook_message(payload)
            self._note_topic_message("orderbook")
        elif topic.startswith("kline."):
            self._handle_kline_message(payload)
            self._note_topic_message("kline")
        elif topic.startswith("publicTrade."):
            self._handle_public_trade_message(payload)
            self._note_topic_message("public_trade")

    def _on_private_message(self, ws_app, message: str) -> None:
        payload = self._decode_message(message)
        if not payload:
            return
        op = payload.get("op")
        if op == "auth":
            if payload.get("success"):
                with self._state_lock:
                    self._private_authenticated = True
                logger.info("[%s] Authenticated private Bybit stream", self.owner_name)
                self._publish_event("health", self.get_health_snapshot())
                self._subscribe_private_topics(ws_app)
            else:
                logger.error(
                    "[%s] Private stream auth failed: %s",
                    self.owner_name,
                    payload,
                )
            return
        if op in {"subscribe", "unsubscribe", "ping", "pong"}:
            return

        # Handle trade command responses (order.create, order.cancel, etc.)
        if self._handle_trade_command_response(payload):
            return

        topic = payload.get("topic", "")
        if not topic:
            return
        if topic == "execution":
            self._handle_execution_message(payload)
            self._note_topic_message("execution")
        elif topic == "order":
            self._handle_order_message(payload)
            self._note_topic_message("order")
        elif topic == "position":
            self._handle_position_message(payload)
            self._note_topic_message("position")

    def _on_public_error(self, _ws_app, error: Any) -> None:
        if self._stop_event.is_set():
            return
        logger.warning("[%s] Public stream error: %s", self.owner_name, error)

    def _on_private_error(self, _ws_app, error: Any) -> None:
        if self._stop_event.is_set():
            return
        logger.warning("[%s] Private stream error: %s", self.owner_name, error)

    def _on_public_close(self, _ws_app, status_code: Any, message: Any) -> None:
        if not self._stop_event.is_set():
            logger.warning(
                "[%s] Public stream closed: code=%s message=%s",
                self.owner_name,
                status_code,
                message,
            )

    def _on_private_close(self, _ws_app, status_code: Any, message: Any) -> None:
        with self._state_lock:
            self._private_connected = False
            self._private_authenticated = False
            self._open_orders_bootstrapped_symbols.clear()
            self._open_orders_dirty_symbols.clear()
            self._open_orders_bootstrapped_all = False
            self._open_orders_dirty_all = False
            for topic in ("position", "order", "execution"):
                self._invalidate_private_topic_locked(
                    topic,
                    source="disconnected",
                )
        if not self._stop_event.is_set():
            logger.warning(
                "[%s] Private stream closed: code=%s message=%s",
                self.owner_name,
                status_code,
                message,
            )

    def _sync_public_topics(self) -> None:
        with self._state_lock:
            ws_app = self._public_ws
            if not self._public_connected or not ws_app:
                return
            desired = self._build_public_topics_locked()
            current = set(self._subscribed_public_topics)
        subscribe_topics = sorted(desired - current)
        unsubscribe_topics = sorted(current - desired)
        if subscribe_topics:
            self._send_json(ws_app, {"op": "subscribe", "args": subscribe_topics})
            with self._state_lock:
                self._subscribed_public_topics.update(subscribe_topics)
        if unsubscribe_topics:
            self._send_json(ws_app, {"op": "unsubscribe", "args": unsubscribe_topics})
            with self._state_lock:
                self._subscribed_public_topics.difference_update(unsubscribe_topics)

    def _subscribe_private_topics(self, ws_app) -> None:
        topics = ["execution", "order", "position"]
        self._send_json(ws_app, {"op": "subscribe", "args": topics})
        with self._state_lock:
            self._subscribed_private_topics = set(topics)

    def _build_public_topics_locked(self) -> Set[str]:
        topics = {f"tickers.{symbol}" for symbol in self._desired_ticker_symbols}
        topics.update(
            f"orderbook.{self.orderbook_depth}.{symbol}"
            for symbol in self._desired_orderbook_symbols
        )
        for interval, symbols in self._desired_kline_symbols_by_interval.items():
            topics.update(f"kline.{interval}.{symbol}" for symbol in symbols)
        # Subscribe to public trade stream for tick-level order flow analysis
        topics.update(
            f"publicTrade.{symbol}" for symbol in self._desired_ticker_symbols
        )
        return topics

    def _handle_ticker_message(self, payload: Dict[str, Any]) -> None:
        data = payload.get("data") or {}
        symbol = self._normalize_symbol(data.get("symbol") or payload.get("topic", "").split(".")[-1])
        if not symbol:
            return
        with self._state_lock:
            previous = dict(
                (self._ticker_cache.get(symbol) or {}).get("data") or {}
            )
        snapshot = previous
        snapshot.update(dict(data))
        snapshot["symbol"] = symbol
        received_at = time.time()
        with self._state_lock:
            self._ticker_cache[symbol] = {
                "data": snapshot,
                "received_at": received_at,
            }
        self._publish_event(
            "ticker",
            {
                "symbol": symbol,
                "lastPrice": snapshot.get("lastPrice"),
                "received_at": received_at,
            },
        )

    def _handle_orderbook_message(self, payload: Dict[str, Any]) -> None:
        topic = payload.get("topic", "")
        topic_parts = topic.split(".")
        symbol = self._normalize_symbol(topic_parts[-1] if topic_parts else "")
        if not symbol:
            return

        data = payload.get("data") or {}
        received_at = time.time()
        with self._state_lock:
            book = self._orderbook_cache.setdefault(
                symbol,
                {
                    "bids": {},
                    "asks": {},
                    "update_id": 0,
                    "exchange_ts": 0,
                    "received_at": 0.0,
                },
            )
            if payload.get("type") == "snapshot":
                book["bids"] = self._build_book_side(data.get("b") or [])
                book["asks"] = self._build_book_side(data.get("a") or [])
            else:
                self._apply_book_updates(book["bids"], data.get("b") or [])
                self._apply_book_updates(book["asks"], data.get("a") or [])
            book["update_id"] = data.get("u", book.get("update_id", 0))
            book["exchange_ts"] = payload.get("ts", data.get("ts", 0))
            book["received_at"] = received_at
            bids = dict(book.get("bids") or {})
            asks = dict(book.get("asks") or {})

        best_bid = self._best_book_price(bids, reverse=True)
        best_ask = self._best_book_price(asks, reverse=False)
        mid_price = None
        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2.0
        else:
            mid_price = best_bid or best_ask
        self._publish_event(
            "orderbook",
            {
                "symbol": symbol,
                "bid_price": best_bid,
                "ask_price": best_ask,
                "mid_price": mid_price,
                "received_at": received_at,
            },
        )
        # Feed orderbook imbalance to order flow analysis service
        order_flow = getattr(self, "_order_flow_service", None)
        if order_flow is not None:
            try:
                order_flow.update_orderbook_imbalance(symbol, bids, asks)
            except Exception:
                pass

    def _handle_kline_message(self, payload: Dict[str, Any]) -> None:
        topic = str(payload.get("topic") or "")
        topic_parts = topic.split(".")
        normalized_interval = self._normalize_kline_interval(topic_parts[1] if len(topic_parts) > 2 else "")
        symbol = self._normalize_symbol(topic_parts[-1] if topic_parts else "")
        if not symbol or not normalized_interval:
            return

        raw_rows = payload.get("data") or []
        if isinstance(raw_rows, dict):
            raw_rows = [raw_rows]

        now = time.time()
        confirmed_rows: List[Dict[str, Any]] = []
        with self._state_lock:
            for raw_row in raw_rows:
                row = self._coerce_stream_kline_row(
                    symbol,
                    normalized_interval,
                    raw_row,
                    received_at=now,
                )
                if row is None:
                    continue
                if self._upsert_kline_row_locked(symbol, normalized_interval, row, now):
                    confirmed_rows.append(dict(row))
        if confirmed_rows:
            self._publish_event(
                "kline",
                {
                    "symbol": symbol,
                    "symbols": [symbol],
                    "interval": normalized_interval,
                    "confirmed": True,
                    "rows": confirmed_rows,
                    "received_at": now,
                },
            )

    def _handle_public_trade_message(self, payload: Dict[str, Any]) -> None:
        """Handle public market trade events for order flow analysis."""
        data = payload.get("data")
        if not data:
            return
        trades = data if isinstance(data, list) else [data]
        if not trades:
            return
        symbol = self._normalize_symbol(
            trades[0].get("s") or trades[0].get("symbol")
            or payload.get("topic", "").split(".")[-1]
        )
        if not symbol:
            return
        order_flow = getattr(self, "_order_flow_service", None)
        if order_flow is not None:
            order_flow.record_trades(symbol, trades)

    def set_order_flow_service(self, service) -> None:
        """Attach the order flow analysis service to receive trade events."""
        self._order_flow_service = service

    def send_trade_command(
        self,
        op: str,
        args: list,
        timeout_sec: float = 5.0,
    ) -> Dict[str, Any]:
        """Send an order command via the private WebSocket and wait for response.

        Args:
            op: Operation name (e.g., "order.create", "order.cancel")
            args: List of order parameter dicts
            timeout_sec: Max wait time for response

        Returns:
            Response dict with retCode, data, etc. Falls back error if WS unavailable.
        """
        if not self._private_connected or not self._private_authenticated:
            return {"success": False, "error": "ws_not_connected", "retCode": -1}

        ws = self._private_ws
        if ws is None:
            return {"success": False, "error": "ws_not_available", "retCode": -1}

        import uuid
        req_id = str(uuid.uuid4())[:8]
        event = threading.Event()
        result_holder: Dict[str, Any] = {}

        with self._pending_trade_lock:
            self._pending_trade_commands[req_id] = {
                "event": event,
                "result": result_holder,
                "op": op,
                "sent_at": time.time(),
            }

        # Build the signed trade command
        timestamp = str(int(time.time() * 1000))
        import hmac as _hmac
        import hashlib as _hashlib
        sign_str = f"{timestamp}{self.api_key}5000"
        signature = _hmac.new(
            self.api_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            _hashlib.sha256,
        ).hexdigest()

        payload = {
            "reqId": req_id,
            "header": {
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-SIGN": signature,
                "X-BAPI-RECV-WINDOW": "5000",
            },
            "op": op,
            "args": args,
        }

        try:
            self._send_json(ws, payload)
        except Exception as exc:
            with self._pending_trade_lock:
                self._pending_trade_commands.pop(req_id, None)
            return {"success": False, "error": f"ws_send_failed: {exc}", "retCode": -1}

        # Wait for response
        got_response = event.wait(timeout=timeout_sec)

        with self._pending_trade_lock:
            self._pending_trade_commands.pop(req_id, None)

        if not got_response:
            return {"success": False, "error": "ws_timeout", "retCode": -1}

        return result_holder.get("response", {"success": False, "error": "no_response", "retCode": -1})

    def _handle_trade_command_response(self, payload: Dict[str, Any]) -> bool:
        """Handle responses to trade commands (order.create, order.cancel, etc.).

        Returns True if the message was consumed as a trade command response.
        """
        op = str(payload.get("op") or "").strip().lower()
        if not op.startswith("order."):
            return False

        req_id = str(payload.get("reqId") or "").strip()
        ret_code = int(payload.get("retCode", -1) or -1)
        ret_msg = str(payload.get("retMsg") or "").strip()
        data = payload.get("data") or {}

        response = {
            "success": ret_code == 0,
            "retCode": ret_code,
            "retMsg": ret_msg,
            "data": data,
            "op": op,
        }

        if req_id:
            with self._pending_trade_lock:
                pending = self._pending_trade_commands.get(req_id)
                if pending:
                    pending["result"]["response"] = response
                    pending["event"].set()
                    return True

        # No matching req_id — log for debugging
        logger.debug("Unmatched trade command response: op=%s retCode=%s reqId=%s", op, ret_code, req_id)
        return False

    def is_trade_ws_ready(self) -> bool:
        """Check if the private WebSocket is connected and ready for trade commands."""
        return bool(
            self._private_connected
            and self._private_authenticated
            and self._private_ws is not None
        )

    def _handle_position_message(self, payload: Dict[str, Any]) -> None:
        rows = payload.get("data") or []
        changed_symbols: Set[str] = set()
        now = time.time()
        with self._state_lock:
            for row in rows:
                symbol = self._normalize_symbol(row.get("symbol"))
                if not symbol:
                    continue
                try:
                    position_idx = int(row.get("positionIdx", 0) or 0)
                except (TypeError, ValueError):
                    position_idx = 0
                row_copy = dict(row)
                row_copy["symbol"] = symbol
                row_copy["positionIdx"] = position_idx
                self._position_cache[(symbol, position_idx)] = row_copy
                changed_symbols.add(symbol)
            if changed_symbols:
                self._record_private_topic_event_locked("position", received_at=now)
        if changed_symbols:
            self._publish_event(
                "position",
                {
                    "symbols": sorted(changed_symbols),
                    "positions": [dict(row) for row in rows],
                    "received_at": now,
                },
            )

    def _handle_order_message(self, payload: Dict[str, Any]) -> None:
        rows = payload.get("data") or []
        changed_symbols: Set[str] = set()
        now = time.time()
        with self._state_lock:
            for row in rows:
                symbol = self._normalize_symbol(row.get("symbol"))
                order_id = str(row.get("orderId") or "").strip()
                if not symbol or not order_id:
                    continue
                order_copy = dict(row)
                order_copy["symbol"] = symbol
                self._recent_order_index[order_id] = order_copy
                self._recent_order_index_ts[order_id] = now
                if self._is_order_open(order_copy):
                    self._open_order_cache[symbol][order_id] = order_copy
                else:
                    self._open_order_cache[symbol].pop(order_id, None)
                changed_symbols.add(symbol)
            if changed_symbols:
                self._record_private_topic_event_locked("order", received_at=now)
            self._prune_recent_order_index_locked(now)
        if changed_symbols:
            self._publish_event(
                "order",
                {
                    "symbols": sorted(changed_symbols),
                    "orders": [dict(row) for row in rows],
                    "received_at": now,
                },
            )

    def _handle_execution_message(self, payload: Dict[str, Any]) -> None:
        rows = payload.get("data") or []
        changed_symbols: Set[str] = set()
        now = time.time()
        sorted_rows = sorted(rows, key=self._execution_sort_key)
        published_count = 0
        published_rows: List[Dict[str, Any]] = []
        with self._state_lock:
            for row in sorted_rows:
                exec_id = str(row.get("execId") or row.get("exec_id") or "").strip()
                if not exec_id:
                    continue
                if exec_id in self._seen_execution_ids:
                    continue
                order_id = str(row.get("orderId") or "").strip()
                order_link_id = row.get("orderLinkId") or row.get("order_link_id")
                if (not order_link_id) and order_id:
                    mapped = self._recent_order_index.get(order_id) or {}
                    order_link_id = mapped.get("orderLinkId")

                row_copy = dict(row)
                if order_link_id:
                    row_copy["orderLinkId"] = order_link_id
                symbol = self._normalize_symbol(row_copy.get("symbol"))
                if symbol:
                    row_copy["symbol"] = symbol

                row_copy["_received_at"] = now
                self._seen_execution_ids[exec_id] = now
                self._execution_cache_global.appendleft(row_copy)
                if symbol:
                    self._execution_cache_by_symbol[symbol].appendleft(row_copy)
                    changed_symbols.add(symbol)
                published_count += 1
                published_rows.append(dict(row_copy))
            if published_count:
                self._record_private_topic_event_locked("execution", received_at=now)
            self._prune_seen_execution_ids_locked(now)
        if published_count:
            self._publish_event(
                "execution",
                {
                    "symbols": sorted(changed_symbols),
                    "count": published_count,
                    "executions": published_rows,
                    "received_at": now,
                },
            )

    @staticmethod
    def _execution_sort_key(row: Dict[str, Any]) -> Tuple[float, str]:
        raw_time = row.get("execTime") or row.get("exec_time") or 0
        try:
            ts = float(raw_time)
        except (TypeError, ValueError):
            ts = 0.0
        exec_id = str(row.get("execId") or row.get("exec_id") or "")
        return ts, exec_id

    @staticmethod
    def _normalize_kline_interval(interval: Any) -> str:
        raw = str(interval or "").strip().lower()
        if not raw:
            return ""
        if raw in {"d", "w", "m"}:
            return raw.upper()
        if raw.endswith("m"):
            raw = raw[:-1]
        elif raw.endswith("h"):
            try:
                raw = str(int(raw[:-1]) * 60)
            except (TypeError, ValueError):
                return ""
        if raw in {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720"}:
            return raw
        return ""

    @classmethod
    def _interval_to_ms(cls, interval: str) -> int:
        normalized = cls._normalize_kline_interval(interval)
        mapping = {
            "1": 60_000,
            "3": 180_000,
            "5": 300_000,
            "15": 900_000,
            "30": 1_800_000,
            "60": 3_600_000,
            "120": 7_200_000,
            "240": 14_400_000,
            "360": 21_600_000,
            "720": 43_200_000,
            "D": 86_400_000,
            "W": 604_800_000,
            "M": 2_592_000_000,
        }
        return mapping.get(normalized, 0)

    @classmethod
    def _coerce_seed_kline_row(
        cls,
        symbol: str,
        interval: str,
        candle: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        try:
            open_time = candle.get("open_time")
            if hasattr(open_time, "timestamp"):
                start_ms = int(open_time.timestamp() * 1000)
            else:
                start_ms = int(candle.get("start") or candle.get("open_time_ms") or 0)
        except (TypeError, ValueError):
            return None
        if start_ms <= 0:
            return None
        interval_ms = cls._interval_to_ms(interval)
        end_ms = start_ms + interval_ms - 1 if interval_ms > 0 else start_ms
        return {
            "symbol": symbol,
            "interval": interval,
            "start": start_ms,
            "end": end_ms,
            "open": str(candle.get("open") or "0"),
            "high": str(candle.get("high") or "0"),
            "low": str(candle.get("low") or "0"),
            "close": str(candle.get("close") or "0"),
            "volume": str(candle.get("volume") or "0"),
            "turnover": str(candle.get("turnover") or "0"),
            "confirm": True,
        }

    @classmethod
    def _coerce_stream_kline_row(
        cls,
        symbol: str,
        interval: str,
        row: Dict[str, Any],
        *,
        received_at: float,
    ) -> Optional[Dict[str, Any]]:
        try:
            start_ms = int(row.get("start") or row.get("startTime") or 0)
        except (TypeError, ValueError):
            return None
        if start_ms <= 0:
            return None
        interval_ms = cls._interval_to_ms(interval)
        try:
            end_ms = int(row.get("end") or 0)
        except (TypeError, ValueError):
            end_ms = 0
        if end_ms <= 0:
            end_ms = start_ms + interval_ms - 1 if interval_ms > 0 else start_ms
        return {
            "symbol": symbol,
            "interval": interval,
            "start": start_ms,
            "end": end_ms,
            "open": str(row.get("open") or "0"),
            "high": str(row.get("high") or "0"),
            "low": str(row.get("low") or "0"),
            "close": str(row.get("close") or "0"),
            "volume": str(row.get("volume") or "0"),
            "turnover": str(row.get("turnover") or "0"),
            "timestamp": row.get("timestamp"),
            "confirm": bool(row.get("confirm")),
            "_received_at": received_at,
        }

    def _upsert_kline_row_locked(
        self,
        symbol: str,
        interval: str,
        row: Dict[str, Any],
        received_at: float,
    ) -> bool:
        cache_key = (symbol, interval)
        cached = self._kline_cache.setdefault(
            cache_key,
            {
                "rows": [],
                "received_at": 0.0,
                "source": "ws",
                "last_confirmed_at": 0.0,
            },
        )
        rows = list(cached.get("rows") or [])
        start_ms = int(row.get("start") or 0)
        replaced = False
        for index, existing in enumerate(rows):
            if int(existing.get("start") or 0) != start_ms:
                continue
            rows[index] = row
            replaced = True
            break
        if not replaced:
            rows.append(row)
        rows.sort(key=lambda item: int(item.get("start") or 0))
        rows = rows[-self.kline_history_limit :]
        cached["rows"] = rows
        cached["received_at"] = float(received_at or time.time())
        cached["source"] = "ws"
        if bool(row.get("confirm")):
            cached["last_confirmed_at"] = float(received_at or time.time())
        self._kline_cache[cache_key] = cached
        return bool(row.get("confirm"))

    @staticmethod
    def _build_book_side(levels: List[List[Any]]) -> Dict[str, str]:
        side: Dict[str, str] = {}
        for level in levels:
            if len(level) < 2:
                continue
            price = str(level[0])
            size = str(level[1])
            try:
                if float(size) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            side[price] = size
        return side

    @staticmethod
    def _apply_book_updates(side: Dict[str, str], levels: List[List[Any]]) -> None:
        for level in levels:
            if len(level) < 2:
                continue
            price = str(level[0])
            size = str(level[1])
            try:
                numeric_size = float(size)
            except (TypeError, ValueError):
                continue
            if numeric_size <= 0:
                side.pop(price, None)
            else:
                side[price] = size

    @staticmethod
    def _format_book_side(
        side: Dict[str, str],
        reverse: bool,
        limit: int,
    ) -> List[Dict[str, float]]:
        rows: List[Tuple[float, float]] = []
        for raw_price, raw_size in side.items():
            try:
                price = float(raw_price)
                size = float(raw_size)
            except (TypeError, ValueError):
                continue
            if price <= 0 or size <= 0:
                continue
            rows.append((price, size))
        rows.sort(key=lambda item: item[0], reverse=reverse)
        formatted = []
        for price, size in rows[:limit]:
            formatted.append({"price": price, "size": size})
        return formatted

    @staticmethod
    def _is_order_open(order: Dict[str, Any]) -> bool:
        status = str(order.get("orderStatus") or "").strip()
        if status in TERMINAL_ORDER_STATUSES:
            return False
        if str(order.get("cancelType") or "").strip():
            return False
        return True

    def _is_private_topic_fresh(
        self,
        topic: str,
        max_age_sec: Optional[float] = None,
    ) -> bool:
        if str(topic or "").strip().lower() == "execution":
            default_age = self.execution_max_age_sec
        else:
            default_age = self.private_max_age_sec
        age_limit = default_age if max_age_sec is None else max(float(max_age_sec), 0.1)
        with self._state_lock:
            if not self._private_connected or not self._private_authenticated:
                return False
            state = self._private_topic_state.get(topic) or {}
            if not state.get("bootstrapped"):
                return False
            if int(state.get("epoch") or 0) != int(self._private_reconnect_epoch or 0):
                return False
            last_update_at = float(state.get("last_update_at") or 0.0)
        return last_update_at > 0 and (time.time() - last_update_at) <= age_limit

    def _note_topic_message(self, topic: str) -> None:
        with self._state_lock:
            self._topic_last_message_at[topic] = time.time()

    def _private_epoch_matches_locked(self, expected_epoch: Optional[int]) -> bool:
        if expected_epoch is None:
            return True
        return int(expected_epoch or 0) == int(self._private_reconnect_epoch or 0)

    def _invalidate_private_topic_locked(self, topic: str, source: str) -> None:
        state = self._private_topic_state.setdefault(topic, self._new_private_topic_state())
        state["epoch"] = int(self._private_reconnect_epoch or 0)
        state["bootstrapped"] = False
        state["source"] = source
        state["last_event_at"] = 0.0
        state["last_snapshot_at"] = 0.0
        state["last_reconcile_at"] = 0.0
        state["last_update_at"] = 0.0
        state["snapshot_started_at"] = 0.0

    def _record_private_topic_event_locked(self, topic: str, *, received_at: float) -> None:
        state = self._private_topic_state.setdefault(topic, self._new_private_topic_state())
        state["epoch"] = int(self._private_reconnect_epoch or 0)
        state["bootstrapped"] = True
        state["source"] = "ws"
        state["last_event_at"] = float(received_at or time.time())
        state["last_update_at"] = max(
            float(state.get("last_update_at") or 0.0),
            float(received_at or time.time()),
        )

    def _record_private_topic_snapshot_locked(
        self,
        topic: str,
        *,
        received_at: float,
        source: str,
        snapshot_started_at: Optional[float],
        is_reconcile: bool,
    ) -> None:
        state = self._private_topic_state.setdefault(topic, self._new_private_topic_state())
        state["epoch"] = int(self._private_reconnect_epoch or 0)
        state["bootstrapped"] = True
        state["source"] = source
        state["last_snapshot_at"] = float(received_at or time.time())
        state["last_update_at"] = max(
            float(state.get("last_update_at") or 0.0),
            float(received_at or time.time()),
        )
        state["snapshot_started_at"] = float(snapshot_started_at or 0.0)
        if is_reconcile:
            state["last_reconcile_at"] = float(received_at or time.time())

    def _should_merge_snapshot_locked(
        self,
        topic: str,
        *,
        snapshot_started_at: Optional[float],
    ) -> bool:
        if not snapshot_started_at:
            return False
        state = self._private_topic_state.get(topic) or {}
        return float(state.get("last_event_at") or 0.0) > float(snapshot_started_at or 0.0)

    def _build_private_topic_status_locked(self, topic: str) -> Dict[str, Any]:
        state = dict(self._private_topic_state.get(topic) or {})
        if topic == "execution":
            age_limit = self.execution_max_age_sec
        else:
            age_limit = self.private_max_age_sec
        last_update_at = float(state.get("last_update_at") or 0.0)
        age_sec = (time.time() - last_update_at) if last_update_at > 0 else None
        fresh = bool(
            self._private_connected
            and self._private_authenticated
            and state.get("bootstrapped")
            and int(state.get("epoch") or 0) == int(self._private_reconnect_epoch or 0)
            and age_sec is not None
            and age_sec <= age_limit
        )
        if topic == "order":
            dirty = bool(self._open_orders_dirty_all or self._open_orders_dirty_symbols)
        else:
            dirty = False
        return {
            "epoch": int(state.get("epoch") or 0),
            "bootstrapped": bool(state.get("bootstrapped")),
            "source": state.get("source"),
            "dirty": dirty,
            "last_event_at": state.get("last_event_at"),
            "last_snapshot_at": state.get("last_snapshot_at"),
            "last_reconcile_at": state.get("last_reconcile_at"),
            "last_update_at": state.get("last_update_at"),
            "fresh": fresh,
            "age_sec": round(age_sec, 3) if age_sec is not None else None,
            "max_age_sec": age_limit,
        }

    def _prune_recent_order_index_locked(self, now: float) -> None:
        cutoff = now - 3600.0
        stale_ids = [
            order_id
            for order_id, seen_at in self._recent_order_index_ts.items()
            if seen_at < cutoff
        ]
        for order_id in stale_ids:
            self._recent_order_index_ts.pop(order_id, None)
            self._recent_order_index.pop(order_id, None)
        if len(self._recent_order_index_ts) <= 5000:
            return
        sorted_ids = sorted(
            self._recent_order_index_ts.items(), key=lambda item: item[1], reverse=True
        )
        keep_ids = {order_id for order_id, _ in sorted_ids[:5000]}
        for order_id in list(self._recent_order_index_ts):
            if order_id in keep_ids:
                continue
            self._recent_order_index_ts.pop(order_id, None)
            self._recent_order_index.pop(order_id, None)

    def _prune_seen_execution_ids_locked(self, now: float) -> None:
        cutoff = now - 3600.0
        stale_ids = [
            exec_id
            for exec_id, seen_at in self._seen_execution_ids.items()
            if seen_at < cutoff
        ]
        for exec_id in stale_ids:
            self._seen_execution_ids.pop(exec_id, None)
        if len(self._seen_execution_ids) <= 10000:
            return
        sorted_ids = sorted(
            self._seen_execution_ids.items(), key=lambda item: item[1], reverse=True
        )
        keep_ids = {exec_id for exec_id, _ in sorted_ids[:10000]}
        for exec_id in list(self._seen_execution_ids):
            if exec_id not in keep_ids:
                self._seen_execution_ids.pop(exec_id, None)

    def _build_auth_payload(self) -> Dict[str, Any]:
        expires = int((time.time() + 10.0) * 1000)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "op": "auth",
            "args": [self.api_key, expires, signature],
        }

    @staticmethod
    def _decode_message(message: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(message)
        except Exception:
            return None

    @staticmethod
    def _send_json(ws_app, payload: Dict[str, Any]) -> None:
        try:
            ws_app.send(json.dumps(payload))
        except Exception:
            logger.debug("Failed to send websocket payload: %s", payload, exc_info=True)

    @staticmethod
    def _normalize_symbol(symbol: Optional[str]) -> Optional[str]:
        if not symbol:
            return None
        normalized = str(symbol).strip().upper()
        return normalized or None

    def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        with self._event_condition:
            event = {
                "seq": self._next_event_seq,
                "type": event_type,
                "payload": payload,
            }
            self._next_event_seq += 1
            self._events.append(event)
            self._event_condition.notify_all()
