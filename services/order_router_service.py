"""
Serialized per-symbol order command router.

This keeps hot-path order commands for a symbol in order while preserving the
existing synchronous client interface.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from services.control_timing_service import elapsed_ms, iso_from_ts, merge_result_timing

logger = logging.getLogger(__name__)


_GLOBAL_SYMBOL = "__GLOBAL__"
_EXCHANGE_CALLBACK_TIMEOUT_SEC = 20.0
_EXCHANGE_CALLBACK_MAX_ATTEMPTS = 3
_SHUTDOWN_GRACE_BUFFER_SEC = 5.0
_MAX_SHUTDOWN_WAIT_SEC = 75.0


@dataclass
class _RouterJob:
    action: str
    callback: Callable[[], Any]
    future: Future
    enqueued_at: float
    job_id: str
    started_at: float = 0.0
    caller_timed_out_at: float = 0.0


class _SymbolWorker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._queue: "queue.Queue[Optional[_RouterJob]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._active_job: Optional[_RouterJob] = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"OrderRouter[{symbol}]",
            # Keep shutdown bounded; durability comes from draining queued work
            # during close() and surfacing unresolved callbacks explicitly.
            daemon=True,
        )
        self._thread.start()

    def owns_current_thread(self) -> bool:
        return threading.current_thread() is self._thread

    def submit(self, job: _RouterJob) -> None:
        self._queue.put(job)

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)

    def join(self, timeout: float = 1.0) -> None:
        self._thread.join(timeout=timeout)

    def get_unresolved_state(self) -> Dict[str, Any]:
        with self._state_lock:
            active_job = self._active_job
            active_payload = None
            if active_job is not None:
                active_payload = {
                    "job_id": active_job.job_id,
                    "action": active_job.action,
                    "started_at": active_job.started_at,
                    "caller_timed_out_at": active_job.caller_timed_out_at,
                }
        return {
            "thread_alive": self._thread.is_alive(),
            "active_job": active_payload,
            "queued_jobs": self._queue.qsize(),
        }

    def _run(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
            if job is None:
                break
            if job.future.cancelled():
                continue
            started_at = time.time()
            job.started_at = started_at
            with self._state_lock:
                self._active_job = job
            try:
                result = job.callback()
            except Exception as exc:
                if job.caller_timed_out_at:
                    logger.warning(
                        "ORDER_ROUTER_TIMEOUT_RESOLVED symbol=%s action=%s job_id=%s outcome=exception error=%s",
                        self.symbol,
                        job.action,
                        job.job_id,
                        exc,
                    )
                logger.warning(
                    "[%s] Order router action failed: %s (%s)",
                    self.symbol,
                    job.action,
                    exc,
                )
                if not job.future.done():
                    job.future.set_exception(exc)
                with self._state_lock:
                    if self._active_job is job:
                        self._active_job = None
                continue
            completed_at = time.time()
            if job.caller_timed_out_at:
                logger.warning(
                    "ORDER_ROUTER_TIMEOUT_RESOLVED symbol=%s action=%s job_id=%s outcome=completed callback_ms=%.1f",
                    self.symbol,
                    job.action,
                    job.job_id,
                    elapsed_ms(started_at, completed_at) or 0.0,
                )
            if isinstance(result, dict):
                result = merge_result_timing(
                    result,
                    order_router_enqueued_at=iso_from_ts(job.enqueued_at),
                    order_router_started_at=iso_from_ts(started_at),
                    order_router_completed_at=iso_from_ts(completed_at),
                    order_router_wait_ms=elapsed_ms(job.enqueued_at, started_at),
                    order_router_callback_ms=elapsed_ms(started_at, completed_at),
                    order_router_total_ms=elapsed_ms(job.enqueued_at, completed_at),
                )
            if not job.future.done():
                job.future.set_result(result)
            with self._state_lock:
                if self._active_job is job:
                    self._active_job = None


class OrderRouterService:
    """Serialize order commands per symbol while keeping a synchronous API."""

    def __init__(self, default_timeout_sec: float = 25.0):
        self.default_timeout_sec = max(float(default_timeout_sec or 0), 1.0)
        self._lock = threading.Lock()
        self._workers: Dict[str, _SymbolWorker] = {}
        self._closed = False
        # C1 audit: warn if router timeout < REST timeout (20s * 3 retries worst case)
        if self.default_timeout_sec < 20.0:
            logger.warning(
                "OrderRouter timeout (%.1fs) is less than REST timeout (20s) — "
                "may cause manufactured ambiguity on slow exchange responses",
                self.default_timeout_sec,
            )

    @staticmethod
    def _normalize_symbol(symbol: Optional[str]) -> str:
        normalized = str(symbol or "").strip().upper()
        return normalized or _GLOBAL_SYMBOL

    def _default_shutdown_wait_sec(self) -> float:
        worst_case_callback_sec = (
            max(self.default_timeout_sec, _EXCHANGE_CALLBACK_TIMEOUT_SEC)
            * _EXCHANGE_CALLBACK_MAX_ATTEMPTS
        )
        return min(
            max(worst_case_callback_sec + _SHUTDOWN_GRACE_BUFFER_SEC, 5.0),
            _MAX_SHUTDOWN_WAIT_SEC,
        )

    def execute(
        self,
        symbol: Optional[str],
        action: str,
        callback: Callable[[], Any],
        timeout_sec: Optional[float] = None,
    ) -> Any:
        symbol_key = self._normalize_symbol(symbol)
        worker = self._get_worker(symbol_key)
        if worker.owns_current_thread():
            started_at = time.time()
            result = callback()
            completed_at = time.time()
            if isinstance(result, dict):
                result = merge_result_timing(
                    result,
                    order_router_enqueued_at=iso_from_ts(started_at),
                    order_router_started_at=iso_from_ts(started_at),
                    order_router_completed_at=iso_from_ts(completed_at),
                    order_router_wait_ms=0.0,
                    order_router_callback_ms=elapsed_ms(started_at, completed_at),
                    order_router_total_ms=elapsed_ms(started_at, completed_at),
                )
            return result

        future: Future = Future()
        enqueued_at = time.time()
        worker.submit(
            job := _RouterJob(
                action=action,
                callback=callback,
                future=future,
                enqueued_at=enqueued_at,
                job_id=(
                    f"{symbol_key}:{action}:{int(enqueued_at * 1000)}"
                ),
            )
        )
        timeout = self.default_timeout_sec if timeout_sec is None else max(
            float(timeout_sec or 0), 0.1
        )
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            timed_out_at = time.time()
            job.caller_timed_out_at = timed_out_at
            status = "in_flight" if job.started_at else "unknown_outcome"
            logger.warning(
                "ORDER_ROUTER_TIMEOUT symbol=%s action=%s status=%s retry_safe=false job_id=%s",
                symbol_key,
                action,
                status,
                job.job_id,
            )
            ambiguous_result: Dict[str, Any] = {
                "success": None,
                "status": status,
                "error": "order_router_timeout",
                "retCode": -2,
                "retry_safe": False,
                "diagnostic_reason": "order_router_timeout",
                "order_router_job_id": job.job_id,
                "truth_check_required": True,
                "truth_check_status": "pending",
            }
            timing_kwargs: Dict[str, Any] = {
                "order_router_enqueued_at": iso_from_ts(enqueued_at),
                "order_router_timeout_at": iso_from_ts(timed_out_at),
                "order_router_total_ms": elapsed_ms(enqueued_at, timed_out_at),
            }
            if job.started_at:
                timing_kwargs["order_router_started_at"] = iso_from_ts(job.started_at)
                timing_kwargs["order_router_wait_ms"] = elapsed_ms(
                    enqueued_at,
                    job.started_at,
                )
            return merge_result_timing(ambiguous_result, **timing_kwargs)

    def close(self, timeout_sec: Optional[float] = None) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = list(self._workers.values())
            self._workers.clear()
        join_timeout = (
            max(float(timeout_sec or 0), 0.1)
            if timeout_sec is not None
            else self._default_shutdown_wait_sec()
        )
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=join_timeout)
            unresolved = worker.get_unresolved_state()
            active_job = unresolved.get("active_job") or {}
            if (
                unresolved.get("thread_alive")
                or active_job
                or int(unresolved.get("queued_jobs") or 0) > 0
            ):
                logger.warning(
                    "ORDER_ROUTER_SHUTDOWN_PENDING symbol=%s active_action=%s job_id=%s queued_jobs=%s wait_sec=%.1f",
                    worker.symbol,
                    active_job.get("action"),
                    active_job.get("job_id"),
                    unresolved.get("queued_jobs"),
                    join_timeout,
                )

    def _get_worker(self, symbol: str) -> _SymbolWorker:
        with self._lock:
            if self._closed:
                raise RuntimeError("OrderRouterService is closed")
            worker = self._workers.get(symbol)
            if worker is None:
                worker = _SymbolWorker(symbol)
                self._workers[symbol] = worker
            return worker
