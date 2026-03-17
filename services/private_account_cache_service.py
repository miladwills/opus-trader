"""
Runner-owned private account cache coordinator.

Seeds and reconciles websocket-backed private account state so non-critical
runner reads can use fresh private cache while explicit `skip_cache=True`
paths continue to force REST.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterable, Optional


logger = logging.getLogger(__name__)


class PrivateAccountCacheService:
    DEFAULT_POSITIONS_RECONCILE_SEC = 20.0
    DEFAULT_OPEN_ORDERS_RECONCILE_SEC = 20.0
    DEFAULT_EXECUTIONS_RECONCILE_SEC = 45.0
    DEFAULT_EVENT_TIMEOUT_SEC = 2.0
    DEFAULT_OPEN_ORDERS_LIMIT = 200
    DEFAULT_EXECUTIONS_LIMIT = 100

    def __init__(
        self,
        client: Any,
        stream_service: Any,
        *,
        owner_name: str = "runner",
        positions_reconcile_sec: float = DEFAULT_POSITIONS_RECONCILE_SEC,
        open_orders_reconcile_sec: float = DEFAULT_OPEN_ORDERS_RECONCILE_SEC,
        executions_reconcile_sec: float = DEFAULT_EXECUTIONS_RECONCILE_SEC,
        open_orders_limit: int = DEFAULT_OPEN_ORDERS_LIMIT,
        executions_limit: int = DEFAULT_EXECUTIONS_LIMIT,
    ) -> None:
        self.client = client
        self.stream_service = stream_service
        self.owner_name = str(owner_name or "runner").strip().lower() or "runner"
        self.positions_reconcile_sec = max(float(positions_reconcile_sec or 0), 5.0)
        self.open_orders_reconcile_sec = max(float(open_orders_reconcile_sec or 0), 5.0)
        self.executions_reconcile_sec = max(float(executions_reconcile_sec or 0), 10.0)
        self.open_orders_limit = max(int(open_orders_limit or 0), 50)
        self.executions_limit = max(int(executions_limit or 0), 20)

        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_private_epoch = 0
        self._last_positions_seed_at = 0.0
        self._last_open_orders_seed_at = 0.0
        self._last_executions_seed_at = 0.0

    def start(self) -> None:
        if not self.stream_service:
            return
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"PrivateAccountCache[{self.owner_name}]",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._state_lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread:
            thread.join(timeout=2.0)

    def seed_now(self, reason: str = "manual") -> None:
        self._seed_all(reason=reason, is_reconcile=reason == "reconcile")

    def get_positions_fresh(self, max_age_sec: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if self.stream_service and hasattr(self.stream_service, "get_positions_fresh"):
            return self.stream_service.get_positions_fresh(max_age_sec=max_age_sec)
        return None

    def get_open_orders_fresh(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.stream_service and hasattr(self.stream_service, "get_open_orders_fresh"):
            return self.stream_service.get_open_orders_fresh(
                symbol=symbol,
                limit=limit,
                max_age_sec=max_age_sec,
            )
        return None

    def get_recent_executions_fresh(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_sec: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.stream_service and hasattr(self.stream_service, "get_recent_executions_fresh"):
            return self.stream_service.get_recent_executions_fresh(
                symbol=symbol,
                limit=limit,
                max_age_sec=max_age_sec,
            )
        return None

    def _run_loop(self) -> None:
        self._seed_all(reason="startup", is_reconcile=False)
        self._last_private_epoch = self._get_private_epoch()
        if self._last_private_epoch > 0 and self._private_cache_needs_seed(self._last_private_epoch):
            self._seed_all(reason="reconnect", is_reconcile=False)
        last_seq = self._get_latest_event_seq()

        while not self._stop_event.is_set():
            events = self._wait_for_events(last_seq)
            for event in events:
                last_seq = max(last_seq, int(event.get("seq") or 0))

            current_epoch = self._get_private_epoch()
            if current_epoch > 0 and (
                current_epoch != self._last_private_epoch
                or self._private_cache_needs_seed(current_epoch)
            ):
                self._last_private_epoch = current_epoch
                self._seed_all(reason="reconnect", is_reconcile=False)

            now = time.monotonic()
            if (now - self._last_positions_seed_at) >= self.positions_reconcile_sec:
                self._seed_positions(reason="reconcile", is_reconcile=True)
            if (now - self._last_open_orders_seed_at) >= self.open_orders_reconcile_sec:
                self._seed_open_orders(reason="reconcile", is_reconcile=True)
            if (now - self._last_executions_seed_at) >= self.executions_reconcile_sec:
                self._seed_executions(reason="reconcile", is_reconcile=True)

    def _seed_all(self, *, reason: str, is_reconcile: bool) -> None:
        self._seed_positions(reason=reason, is_reconcile=is_reconcile)
        self._seed_open_orders(reason=reason, is_reconcile=is_reconcile)
        self._seed_executions(reason=reason, is_reconcile=is_reconcile)

    def _seed_positions(self, *, reason: str, is_reconcile: bool) -> None:
        epoch = self._get_private_epoch()
        try:
            response = self.client.get_positions(
                skip_cache=True,
                cache_seed_source=reason,
                cache_seed_expected_epoch=epoch if epoch > 0 else None,
            )
            if response.get("success"):
                self._last_positions_seed_at = time.monotonic()
            else:
                logger.debug(
                    "[%s] Private cache position %s failed: %s",
                    self.owner_name,
                    reason,
                    response.get("error"),
                )
        except Exception as exc:
            logger.warning("[%s] Private cache position %s failed: %s", self.owner_name, reason, exc)

    def _seed_open_orders(self, *, reason: str, is_reconcile: bool) -> None:
        epoch = self._get_private_epoch()
        try:
            response = self.client.get_open_orders(
                limit=self.open_orders_limit,
                skip_cache=True,
                cache_seed_source=reason,
                cache_seed_expected_epoch=epoch if epoch > 0 else None,
            )
            if response.get("success"):
                self._last_open_orders_seed_at = time.monotonic()
            else:
                logger.debug(
                    "[%s] Private cache open-order %s failed: %s",
                    self.owner_name,
                    reason,
                    response.get("error"),
                )
        except Exception as exc:
            logger.warning("[%s] Private cache open-order %s failed: %s", self.owner_name, reason, exc)

    def _seed_executions(self, *, reason: str, is_reconcile: bool) -> None:
        epoch = self._get_private_epoch()
        try:
            response = self.client.get_executions(
                limit=self.executions_limit,
                skip_cache=True,
                cache_seed_source=reason,
                cache_seed_expected_epoch=epoch if epoch > 0 else None,
            )
            if response.get("success"):
                self._last_executions_seed_at = time.monotonic()
            else:
                logger.debug(
                    "[%s] Private cache execution %s failed: %s",
                    self.owner_name,
                    reason,
                    response.get("error"),
                )
        except Exception as exc:
            logger.warning("[%s] Private cache execution %s failed: %s", self.owner_name, reason, exc)

    def _wait_for_events(self, last_seq: int) -> Iterable[Dict[str, Any]]:
        if self.stream_service and hasattr(self.stream_service, "wait_for_events"):
            try:
                return self.stream_service.wait_for_events(
                    last_seq,
                    timeout_sec=self.DEFAULT_EVENT_TIMEOUT_SEC,
                )
            except Exception as exc:
                logger.debug("Private cache wait_for_events failed: %s", exc)
                return []
        time.sleep(self.DEFAULT_EVENT_TIMEOUT_SEC)
        return []

    def _get_latest_event_seq(self) -> int:
        if self.stream_service and hasattr(self.stream_service, "get_latest_event_seq"):
            try:
                return int(self.stream_service.get_latest_event_seq() or 0)
            except Exception:
                return 0
        return 0

    def _get_private_epoch(self) -> int:
        if self.stream_service and hasattr(self.stream_service, "get_private_reconnect_epoch"):
            try:
                return int(self.stream_service.get_private_reconnect_epoch() or 0)
            except Exception:
                return 0
        return 0

    def _private_cache_needs_seed(self, epoch: int) -> bool:
        if not self.stream_service or not hasattr(self.stream_service, "get_health_snapshot"):
            return False
        try:
            health = self.stream_service.get_health_snapshot() or {}
        except Exception:
            return False
        private_cache = health.get("private_cache") or {}
        for topic in ("position", "order", "execution"):
            topic_state = private_cache.get(topic) or {}
            if int(topic_state.get("epoch") or 0) != int(epoch or 0):
                return True
            if not bool(topic_state.get("bootstrapped")):
                return True
        return False
