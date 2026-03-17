"""
Runner-side event reactor for websocket-driven bot reactions.

This turns websocket events into bot-level wakeups while leaving the existing
bot logic in place as the source of truth.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, Optional, Set


logger = logging.getLogger(__name__)


EVENT_PRIORITY = {
    "execution": 4,
    "order": 3,
    "position": 2,
    "kline": 1,
    "orderbook": 1,
    "ticker": 1,
}

EVENT_DEBOUNCE_SEC = {
    "execution": 0.10,
    "order": 0.20,
    "position": 0.35,
    "kline": 0.75,
    "orderbook": 0.35,
    "ticker": 1.00,
}

GUARDED_PRICE_EVENT_TYPES = {"orderbook", "ticker"}
GUARDED_PRICE_EVENT_DEBOUNCE_SEC = {
    "orderbook": 0.12,
    "ticker": 0.25,
}
DEFERRED_RETRY_SEC = {
    "orderbook": 0.12,
    "ticker": 0.20,
}
MAX_DEFERRED_RETRIES = 2


class StreamReactionService:
    """Translate stream events into throttled bot reactions."""

    def __init__(
        self,
        stream_service: Any,
        bot_storage: Any,
        grid_bot_service: Any,
        max_workers: int = 4,
        fallback_poll_sec: float = 5.0,
    ):
        self.stream_service = stream_service
        self.bot_storage = bot_storage
        self.grid_bot_service = grid_bot_service
        self.fallback_poll_sec = max(float(fallback_poll_sec or 0), 1.0)

        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._executor = ThreadPoolExecutor(
            max_workers=max(int(max_workers or 1), 1),
            thread_name_prefix="StreamReact",
        )
        self._running = False
        self._inflight: Set[str] = set()
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._deferred_retries: Dict[str, Dict[str, Any]] = {}
        self._last_reaction_at: Dict[tuple, float] = {}
        self._last_fallback_poll_at: Dict[str, float] = {}

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="StreamReactionLoop",
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
        self._executor.shutdown(wait=False, cancel_futures=True)

    def is_active(self) -> bool:
        with self._state_lock:
            return self._running and self._thread is not None and self._thread.is_alive()

    def should_poll_fast_refill(self, bot: Dict[str, Any]) -> bool:
        bot_id = str(bot.get("id") or "").strip()
        if not bot_id:
            return True
        if not self.is_active():
            return True
        try:
            if not self.stream_service.has_fresh_private_state(("execution", "order", "position")):
                return True
        except Exception:
            return True
        with self._state_lock:
            last_poll = float(self._last_fallback_poll_at.get(bot_id, 0.0) or 0.0)
        return (time.time() - last_poll) >= self.fallback_poll_sec

    def note_fast_refill_poll(self, bot: Dict[str, Any]) -> None:
        bot_id = str(bot.get("id") or "").strip()
        if not bot_id:
            return
        with self._state_lock:
            self._last_fallback_poll_at[bot_id] = time.time()

    def _run_loop(self) -> None:
        last_seq = self.stream_service.get_latest_event_seq()
        while not self._stop_event.is_set():
            self._dispatch_due_retries()
            try:
                events = self.stream_service.wait_for_events(
                    last_seq,
                    timeout_sec=self._next_wait_timeout(),
                )
            except Exception as exc:
                logger.warning("Stream reaction wait failed: %s", exc)
                time.sleep(1.0)
                continue
            self._dispatch_due_retries()
            if not events:
                continue
            for event in events:
                last_seq = max(last_seq, int(event.get("seq") or 0))
                self._dispatch_event(event)

    def _next_wait_timeout(self) -> float:
        now = time.time()
        with self._state_lock:
            retry_at_values = [
                float(entry.get("retry_at") or 0.0)
                for entry in self._deferred_retries.values()
                if isinstance(entry, dict)
            ]
        future_retry_at = min((value for value in retry_at_values if value > 0.0), default=0.0)
        if future_retry_at <= 0.0:
            return 1.0
        return max(0.05, min(future_retry_at - now, 1.0))

    def _dispatch_event(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").strip()
        if event_type not in EVENT_PRIORITY:
            return
        payload = event.get("payload") or {}
        symbols = self._extract_symbols(payload)
        if not symbols:
            return

        try:
            bots = self.bot_storage.list_bots()
        except Exception as exc:
            logger.warning("Stream reaction bot list failed: %s", exc)
            return

        for bot in bots:
            if bot.get("status") != "running":
                continue
            symbol = str(bot.get("symbol") or "").strip().upper()
            if not symbol or symbol not in symbols:
                continue
            self._schedule_bot(bot, event_type, payload)

    @staticmethod
    def _extract_symbols(payload: Dict[str, Any]) -> Set[str]:
        symbols: Set[str] = set()
        raw_symbols = payload.get("symbols")
        if isinstance(raw_symbols, (list, tuple, set)):
            for symbol in raw_symbols:
                normalized = str(symbol or "").strip().upper()
                if normalized:
                    symbols.add(normalized)
        single_symbol = str(payload.get("symbol") or "").strip().upper()
        if single_symbol:
            symbols.add(single_symbol)
        return symbols

    def _schedule_bot(
        self,
        bot: Dict[str, Any],
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        bot_id = str(bot.get("id") or "").strip()
        if not bot_id:
            return
        lane = "hot" if event_type in ("execution", "order", "position") else "price"
        debounce_key = (bot_id, lane)
        debounce_sec = self._get_debounce_sec(bot, event_type)
        payload = dict(payload or {})
        force_schedule = bool(payload.get("_force_schedule"))
        now = time.time()
        with self._state_lock:
            last_run = float(self._last_reaction_at.get(debounce_key, 0.0) or 0.0)
            pending_event = self._pending.get(bot_id)
            if bot_id in self._inflight:
                if (
                    pending_event is None
                    or EVENT_PRIORITY.get(event_type, 0)
                    >= EVENT_PRIORITY.get(str(pending_event.get("type") or ""), 0)
                ):
                    self._pending[bot_id] = {
                        "type": event_type,
                        "payload": payload,
                    }
                return
            if (now - last_run) < debounce_sec and not force_schedule:
                if (
                    pending_event is None
                    or EVENT_PRIORITY.get(event_type, 0)
                    >= EVENT_PRIORITY.get(str(pending_event.get("type") or ""), 0)
                ):
                    self._pending[bot_id] = {
                        "type": event_type,
                        "payload": payload,
                    }
                return
            self._inflight.add(bot_id)
            self._last_reaction_at[debounce_key] = now
        self._executor.submit(self._run_bot_reaction, bot_id, event_type, payload)

    def _get_debounce_sec(self, bot: Dict[str, Any], event_type: str) -> float:
        debounce_sec = EVENT_DEBOUNCE_SEC.get(event_type, 0.5)
        if self._is_guarded_price_fast_path(bot, event_type):
            return min(
                debounce_sec,
                GUARDED_PRICE_EVENT_DEBOUNCE_SEC.get(event_type, debounce_sec),
            )
        return debounce_sec

    @staticmethod
    def _event_received_at(payload: Optional[Dict[str, Any]] = None) -> float:
        try:
            return float((payload or {}).get("received_at") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _is_guarded_or_blocked_bot(bot: Dict[str, Any]) -> bool:
        return any(
            bool(bot.get(field))
            for field in (
                "_entry_gate_blocked",
                "_block_opening_orders",
                "_nlp_block_opening_orders",
                "_volatility_block_opening_orders",
                "_session_timer_block_opening_orders",
                "_stall_overlay_block_opening_orders",
                "_breakout_invalidation_block_opening_orders",
                "_capital_starved_block_opening_orders",
                "_small_capital_block_opening_orders",
                "auto_pilot_rotation_pending",
            )
        )

    def _is_guarded_price_fast_path(self, bot: Dict[str, Any], event_type: str) -> bool:
        if event_type not in GUARDED_PRICE_EVENT_TYPES:
            return False
        if str(bot.get("status") or "").strip().lower() != "running":
            return False
        mode = str(bot.get("mode") or "").strip().lower()
        if mode not in {"long", "short", "neutral"}:
            return False
        return self._is_guarded_or_blocked_bot(bot)

    def _schedule_deferred_retry(
        self,
        bot_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]],
        *,
        reason: str,
    ) -> None:
        payload = dict(payload or {})
        retry_count = int(payload.get("_retry_count") or 0)
        if retry_count >= MAX_DEFERRED_RETRIES:
            return
        retry_payload = dict(payload)
        retry_payload["_retry_count"] = retry_count + 1
        retry_payload["_force_schedule"] = True
        retry_payload["_deferred_reason"] = str(reason or "bot_cycle_lock_busy")
        retry_payload["_guarded_fast_path"] = True
        retry_delay = DEFERRED_RETRY_SEC.get(event_type, 0.20)
        with self._state_lock:
            self._deferred_retries[bot_id] = {
                "type": event_type,
                "payload": retry_payload,
                "retry_at": time.time() + retry_delay,
            }

    def _dispatch_due_retries(self) -> None:
        due_entries = []
        now = time.time()
        with self._state_lock:
            for bot_id, entry in list(self._deferred_retries.items()):
                retry_at = float((entry or {}).get("retry_at") or 0.0)
                if retry_at > 0.0 and retry_at <= now:
                    due_entries.append((bot_id, dict(entry or {})))
                    self._deferred_retries.pop(bot_id, None)
        for bot_id, entry in due_entries:
            try:
                bot = self.bot_storage.get_bot(bot_id)
            except Exception:
                bot = None
            if not bot or str(bot.get("status") or "").strip().lower() != "running":
                continue
            self._schedule_bot(
                bot,
                str(entry.get("type") or ""),
                entry.get("payload") or {},
            )

    def _run_bot_reaction(
        self,
        bot_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            bot = self.bot_storage.get_bot(bot_id)
            if not bot or bot.get("status") != "running":
                return
            guarded_fast_path = self._is_guarded_price_fast_path(bot, event_type)
            provider_received_at = self._event_received_at(payload)
            if guarded_fast_path and provider_received_at > 0.0:
                bot["_reevaluation_trigger_received_at"] = provider_received_at
                bot["_reevaluation_trigger_reason"] = event_type
                bot["_reevaluation_trigger_path"] = "stream_guarded_price_lane"
                bot["_blocked_guarded_fast_path_requested"] = True
                bot["_fresh_provider_seen_before_eval"] = True
                bot["_evaluation_deferred_reason"] = str(
                    (payload or {}).get("_deferred_reason") or ""
                ) or None
            mode = (bot.get("mode") or "").lower()
            if event_type in ("execution", "order"):
                if mode == "neutral_classic_bybit":
                    self.grid_bot_service.run_neutral_classic_fast_refill(
                        bot,
                        execution_events=(
                            (payload or {}).get("executions")
                            if event_type == "execution"
                            else None
                        ),
                    )
                elif mode == "neutral":
                    self.grid_bot_service.run_neutral_dynamic_fast_refill(bot)
                elif mode == "scalp_pnl":
                    self.grid_bot_service.run_scalp_pnl_fast_refill(bot)
                elif mode == "long":
                    self.grid_bot_service.run_long_fast_refill(bot)
                elif mode == "short":
                    self.grid_bot_service.run_short_fast_refill(bot)
                else:
                    self.grid_bot_service.run_bot_cycle(bot, fast_refill_tick=True)
                return

            # Position and ticker updates should drive the fast-cycle path so
            # trailing SL, soft-stop, quick-profit, and recenter logic use fresh state.
            result = self.grid_bot_service.run_bot_cycle(bot, fast_refill_tick=True)
            if guarded_fast_path and isinstance(result, dict) and result.get("_cycle_lock_busy"):
                self._schedule_deferred_retry(
                    bot_id,
                    event_type,
                    payload,
                    reason=str(
                        result.get("_cycle_lock_busy_reason")
                        or (payload or {}).get("_deferred_reason")
                        or "bot_cycle_lock_busy"
                    ),
                )
        except Exception as exc:
            logger.warning("[bot:%s] Stream reaction failed for %s: %s", bot_id, event_type, exc)
        finally:
            pending_event = None
            with self._state_lock:
                self._inflight.discard(bot_id)
                pending_event = self._pending.pop(bot_id, None)
            if pending_event:
                try:
                    bot = self.bot_storage.get_bot(bot_id)
                except Exception:
                    bot = None
                if bot and bot.get("status") == "running":
                    self._schedule_bot(
                        bot,
                        str(pending_event.get("type") or ""),
                        pending_event.get("payload") or {},
                    )
