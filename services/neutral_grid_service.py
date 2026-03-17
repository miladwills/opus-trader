"""
Neutral Classic Grid Service (Bybit-style, hedge mode).

Implements slot-based grid behavior with ENTRY/EXIT replacement.
"""

import logging
import math
import time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.strategy_config import (
    AUTO_MARGIN_RESERVE_USDT,
    AUTO_MARGIN_RESERVE_PCT,
    AUTO_MARGIN_RESERVE_USE_PCT,
    OPENING_MARGIN_VIABILITY_RESERVE_PCT,
    OPENING_MARGIN_VIABILITY_RESERVE_CAP_USDT,
    SMALL_CAPITAL_MODE_ENABLED,
    SMALL_CAPITAL_INVEST_USDT_THRESHOLD,
    MAX_POSITION_ENABLED,
    MAX_POSITION_PCT,
    get_mode_max_position_pct,
    TRAILING_RECENTER_COOLDOWN_SEC,
    TRAILING_RECENTER_OUTER_PCT,
    GRID_STEP_MAJOR_MULT,
    TRAILING_MAJOR_SYMBOLS,
)
from services.adaptive_config_service import AdaptiveConfigService
from services.order_ownership_service import build_order_ownership_snapshot

logger = logging.getLogger(__name__)

SKIP_SMALL_QTY_LOG_COOLDOWN_SEC = 60
MAX_EXEC_ID_CACHE = 500
OPEN_ORDER_VISIBILITY_GRACE_SEC = 15.0
OPEN_ORDER_MISS_TOLERANCE = 2


class NeutralGridService:
    def __init__(
        self,
        bot_storage,
        adaptive_config_service: Optional[AdaptiveConfigService] = None,
    ):
        self.bot_storage = bot_storage
        self.adaptive_config_service = (
            adaptive_config_service or AdaptiveConfigService()
        )
        self._instrument_cache: Dict[str, Dict[str, Any]] = {}
        self._last_skip_log_ts: Dict[str, float] = {}
        self._auto_margin_warned = False

    @staticmethod
    def _is_auto_pilot_placeholder_symbol(symbol: Any) -> bool:
        return str(symbol or "").strip().lower() == "auto-pilot"

    def _reset_auto_pilot_placeholder_runtime_state(
        self, bot: Dict[str, Any]
    ) -> bool:
        reset_values = {
            "lower_price": None,
            "upper_price": None,
            "grid_lower_price": None,
            "grid_upper_price": None,
            "grid_levels_total": None,
            "current_price": 0.0,
            "last_trade_price": None,
            "open_order_count": 0,
            "entry_orders_open": 0,
            "exit_orders_open": 0,
            "active_long_slots": 0,
            "active_short_slots": 0,
            "neutral_grid": {},
            "neutral_grid_initialized": False,
            "_entry_structure_skip_buy": False,
            "_entry_structure_skip_sell": False,
            "neutral_grid_last_reconcile_at": None,
            "grid_levels_total_effective": None,
            "levels_count": None,
            "mid_index": None,
            "last_fill_event": None,
            "last_replacement_action": None,
            "_last_recenter_ts": None,
            "_position_mode": None,
            "_position_mode_ts": None,
            "_entry_structure_buy_reason": None,
            "_entry_structure_sell_reason": None,
            "last_error": None,
            "error_code": None,
        }

        changed = False
        for key, value in reset_values.items():
            if bot.get(key) != value:
                bot[key] = value
                changed = True
        return changed

    @staticmethod
    def build_grid_levels(lower: float, upper: float, total_levels: int) -> List[float]:
        if total_levels <= 0 or upper <= lower:
            return []
        step = (upper - lower) / float(total_levels)
        return [lower + step * i for i in range(total_levels + 1)]

    def reconcile_on_start(
        self, bot: Dict[str, Any], symbol: str, client
    ) -> Dict[str, Any]:
        if bot.get("auto_pilot") and (
            self._is_auto_pilot_placeholder_symbol(symbol)
            or self._is_auto_pilot_placeholder_symbol(bot.get("symbol"))
        ):
            if self._reset_auto_pilot_placeholder_runtime_state(bot):
                self.bot_storage.save_bot(bot)
            return bot

        bot = self.ensure_hedge_mode(bot, symbol, client)
        if bot.get("status") == "error":
            return bot

        grid_config = self._get_grid_config(bot)
        if not grid_config:
            return self._set_error(
                bot,
                "Missing neutral grid config (grid_lower_price/grid_upper_price/grid_levels_total)",
            )

        lower_price, upper_price, total_levels = grid_config
        if lower_price <= 0 or upper_price <= lower_price or total_levels <= 0:
            return self._set_error(
                bot, "Invalid neutral grid config (bounds or levels)"
            )

        instrument = self._get_instrument_info(client, symbol)
        if not instrument:
            return self._set_error(bot, f"Missing instrument sizing for {symbol}")

        # 1. Get available balance for unified reserve
        avail_equity = self._get_usdt_available_balance(client)

        effective_levels = self._apply_small_capital_tuning(
            bot=bot,
            symbol=symbol,
            total_levels=total_levels,
            instrument=instrument,
        )

        effective_levels = self._apply_min_notional_guard(
            bot=bot,
            total_levels=effective_levels,
            instrument=instrument,
            available_equity=avail_equity,
        )

        # Smart Feature: Automatic Tightness for Major Coins
        # Scale levels by 1/GRID_STEP_MAJOR_MULT (e.g. 1/0.4 = 2.5x more levels)
        # BUT never exceed the user-specified grid count (total_levels)
        is_major = symbol in TRAILING_MAJOR_SYMBOLS
        if is_major and GRID_STEP_MAJOR_MULT < 1.0:
            count_mult = 1.0 / GRID_STEP_MAJOR_MULT
            old_levels = effective_levels
            effective_levels = int(effective_levels * count_mult)
            # Cap: never exceed user-configured grid count
            if effective_levels > total_levels:
                logger.info(
                    "[%s] 🔒 Major coin grid cap: scaled %d -> %d exceeds user-set %d, capping to %d",
                    symbol,
                    old_levels,
                    effective_levels,
                    total_levels,
                    total_levels,
                )
                effective_levels = total_levels
            else:
                logger.info(
                    "[%s] 🚀 Major coin detected: Tightening grid %d -> %d levels (%.2fx scale)",
                    symbol,
                    old_levels,
                    effective_levels,
                    count_mult,
                )
            bot["grid_levels_total_effective"] = effective_levels

        levels = self.build_grid_levels(lower_price, upper_price, effective_levels)
        if not levels:
            return self._set_error(bot, "Failed to build neutral grid levels")

        neutral_state = bot.get("neutral_grid") or {}
        prev_levels = neutral_state.get("levels") or []
        prev_total = neutral_state.get("total_levels")
        prev_lower = neutral_state.get("lower_price")
        prev_upper = neutral_state.get("upper_price")

        config_changed = (
            prev_total != effective_levels
            or prev_lower != lower_price
            or prev_upper != upper_price
            or len(prev_levels) != len(levels)
        )

        if config_changed or not neutral_state.get("slots"):
            last_price = self._get_last_price(client, symbol, skip_cache=True)
            mid_index = self._find_mid_index(levels, last_price)
            slots = self._build_slots(levels, mid_index)
            neutral_state = {
                "levels": levels,
                "lower_price": lower_price,
                "upper_price": upper_price,
                "total_levels": effective_levels,
                "mid_index": mid_index,
                "slots": slots,
                "seq": int(neutral_state.get("seq", 0) or 0),
                "processed_exec_ids": list(neutral_state.get("processed_exec_ids", [])),
                "slot_width": self._slot_width(effective_levels),
            }
        else:
            neutral_state["levels"] = levels
            neutral_state["lower_price"] = lower_price
            neutral_state["upper_price"] = upper_price
            neutral_state["total_levels"] = effective_levels

        per_order_qty = self._compute_per_order_qty(bot, instrument, levels)
        neutral_state["per_order_qty"] = per_order_qty

        bot_id_16 = self._bot_id_16(bot)
        open_orders = self._get_open_orders(client, symbol, skip_cache=True)
        seq_floor = neutral_state.get("seq", 0)
        slots = neutral_state.get("slots") or {}
        slot_open_map: Dict[str, Dict[str, Any]] = {}
        duplicate_slot_orders: List[Dict[str, Any]] = []
        now_ts = client._get_now_ts() if hasattr(client, "_get_now_ts") else time.time()

        for order in open_orders:
            link_id = order.get("orderLinkId")
            parsed = self._parse_order_link_id(link_id)
            if not parsed or parsed.get("bot_id") != bot_id_16:
                continue
            slot_id = parsed.get("slot")
            if not slot_id:
                continue

            # If slot no longer exists in current grid (due to recenter), it's orphaned
            if slot_id not in slots:
                try:
                    client.cancel_order(
                        symbol=symbol,
                        order_id=order.get("orderId"),
                        order_link_id=link_id,
                    )
                    logger.info(
                        "[%s] Cancelled orphaned slot order %s", symbol, link_id
                    )
                except Exception:
                    pass
                continue

            existing_order = slot_open_map.get(slot_id)
            if existing_order:
                preferred_link_id = str(slots[slot_id].get("order_link_id") or "").strip()
                current_link_id = str(link_id or "").strip()
                existing_link_id = str(existing_order.get("orderLinkId") or "").strip()
                if preferred_link_id and current_link_id == preferred_link_id and (
                    existing_link_id != preferred_link_id
                ):
                    duplicate_slot_orders.append(existing_order)
                    slot_open_map[slot_id] = order
                else:
                    duplicate_slot_orders.append(order)
                continue

            # PRICE VERIFICATION: Ensure the order price matches the new grid levels
            target_price = (
                slots[slot_id]["entry_price"]
                if parsed.get("state") == "E"
                else slots[slot_id]["exit_price"]
            )
            order_price = float(order.get("price") or 0)
            if order_price > 0 and abs(order_price - target_price) > (
                target_price * 0.001
            ):
                try:
                    client.cancel_order(
                        symbol=symbol,
                        order_id=order.get("orderId"),
                        order_link_id=link_id,
                    )
                    logger.info(
                        "[%s] Cancelled stale-price order %s (%.6f vs expected %.6f)",
                        symbol,
                        link_id,
                        order_price,
                        target_price,
                    )
                except Exception:
                    pass
                continue

            slot_open_map[slot_id] = order
            seq_val = parsed.get("seq")
            if seq_val is not None and seq_val > seq_floor:
                seq_floor = seq_val

        neutral_state["seq"] = seq_floor

        cancelled_duplicate_count = 0
        for duplicate_order in duplicate_slot_orders:
            try:
                client.cancel_order(
                    symbol=symbol,
                    order_id=duplicate_order.get("orderId"),
                    order_link_id=duplicate_order.get("orderLinkId"),
                )
                cancelled_duplicate_count += 1
                logger.warning(
                    "[%s] Cancelled duplicate slot order %s",
                    symbol,
                    duplicate_order.get("orderLinkId") or duplicate_order.get("orderId"),
                )
            except Exception:
                logger.warning(
                    "[%s] Failed to cancel duplicate slot order %s",
                    symbol,
                    duplicate_order.get("orderLinkId") or duplicate_order.get("orderId"),
                    exc_info=True,
                )

        if cancelled_duplicate_count > 0:
            time.sleep(0.5)
            logger.info(
                "[%s] Waited 500ms for %d duplicate cancel(s) to propagate",
                symbol,
                cancelled_duplicate_count,
            )

        duplicate_cancelled_slots = set()
        for duplicate_order in duplicate_slot_orders:
            parsed = self._parse_order_link_id(duplicate_order.get("orderLinkId"))
            if not parsed:
                continue
            slot_id = parsed.get("slot")
            if slot_id:
                duplicate_cancelled_slots.add(slot_id)

        position_sizes = self._get_position_sizes(client, symbol)

        for slot_id, slot in slots.items():
            open_order = slot_open_map.get(slot_id)
            if open_order:
                parsed = self._parse_order_link_id(open_order.get("orderLinkId"))
                slot_state = "ENTRY" if parsed.get("state") == "E" else "EXIT"
                slot["state"] = slot_state
                slot["order_id"] = open_order.get("orderId")
                slot["order_link_id"] = open_order.get("orderLinkId")
                slot["last_order_seen_ts"] = now_ts
                slot["visibility_miss_count"] = 0
            else:
                # If no position on this leg, reset to ENTRY to avoid reduce-only errors
                _, reduce_only, pos_idx = self._slot_order_params(slot)
                if reduce_only and position_sizes.get(pos_idx, 0) <= 0:
                    slot["state"] = "ENTRY"
                    slot["order_id"] = None
                    slot["order_link_id"] = None
                    slot["visibility_miss_count"] = 0
                    slot.pop("last_order_seen_ts", None)
                    slot.pop("last_order_submit_ts", None)
                    continue
                if self._should_preserve_missing_slot_order(slot, now_ts):
                    continue
                slot["order_id"] = None
                slot["order_link_id"] = None
                slot["visibility_miss_count"] = 0
                slot.pop("last_order_seen_ts", None)
                slot.pop("last_order_submit_ts", None)

        # Track skip reasons for summary logging
        skipped_reasons = {}

        for slot_id, slot in slots.items():
            if slot.get("order_link_id"):
                continue
            if slot_id in duplicate_cancelled_slots:
                logger.debug(
                    "[%s] Skipping order placement for slot %s (duplicate just cancelled)",
                    symbol,
                    slot_id,
                )
                continue
            place_result = self._place_slot_order(
                bot=bot,
                symbol=symbol,
                client=client,
                neutral_state=neutral_state,
                slot_id=slot_id,
                slot=slot,
            )

            if not place_result.get("success"):
                error_type = place_result.get("error", "unknown")
                if place_result.get("skipped"):
                    skipped_reasons[error_type] = skipped_reasons.get(error_type, 0) + 1

                if error_type == "hedge_mode_required":
                    return place_result.get("bot", bot)
                if error_type == "close_failed":
                    return place_result.get("bot", bot)
                if error_type == "position_zero":
                    slot["state"] = "ENTRY"
                    slot["order_id"] = None
                    slot["order_link_id"] = None
                    neutral_state["needs_reconcile"] = True

                if not place_result.get("skipped") and error_type not in (
                    "position_zero",
                    "invalid_price",
                ):
                    # For non-skip errors (actual failures), we still want a warning/debug
                    # but maybe not for every single slot if they all fail the same way.
                    pass

        # Log skip summary if any skips occurred
        if skipped_reasons:
            reasons_str = ", ".join([f"{k}:{v}" for k, v in skipped_reasons.items()])
            logger.info(f"[{symbol}] ⏭️ Skips: [{reasons_str}]")

        bot["neutral_grid"] = neutral_state
        bot["neutral_grid_initialized"] = True
        bot["neutral_grid_last_reconcile_at"] = datetime.now(timezone.utc).isoformat()
        bot["grid_count"] = len(slots)
        self._update_status_fields(bot, neutral_state)
        return self.bot_storage.save_bot(bot)

    def seed_initial_orders(
        self,
        bot: Dict[str, Any],
        symbol: str,
        levels: List[float],
        mid_index: int,
        client,
    ) -> Dict[str, Any]:
        instrument = self._get_instrument_info(client, symbol)
        if not instrument:
            return self._set_error(bot, f"Missing instrument sizing for {symbol}")

        slots = self._build_slots(levels, mid_index)
        neutral_state = {
            "levels": levels,
            "lower_price": levels[0] if levels else 0,
            "upper_price": levels[-1] if levels else 0,
            "total_levels": max(len(levels) - 1, 0),
            "mid_index": mid_index,
            "slots": slots,
            "seq": int((bot.get("neutral_grid") or {}).get("seq", 0) or 0),
            "processed_exec_ids": list(
                (bot.get("neutral_grid") or {}).get("processed_exec_ids", [])
            ),
            "slot_width": self._slot_width(max(len(levels) - 1, 0)),
        }
        neutral_state["per_order_qty"] = self._compute_per_order_qty(
            bot, instrument, levels
        )

        for slot_id, slot in slots.items():
            place_result = self._place_slot_order(
                bot=bot,
                symbol=symbol,
                client=client,
                neutral_state=neutral_state,
                slot_id=slot_id,
                slot=slot,
            )
            if place_result.get("error") == "hedge_mode_required":
                return place_result.get("bot", bot)
            if place_result.get("error") == "close_failed":
                return place_result.get("bot", bot)

        bot["neutral_grid"] = neutral_state
        bot["neutral_grid_initialized"] = True
        bot["grid_count"] = len(slots)
        self._update_status_fields(bot, neutral_state)
        return self.bot_storage.save_bot(bot)

    def process_execution_events(
        self,
        bot: Dict[str, Any],
        symbol: str,
        client,
        execution_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        neutral_state = bot.get("neutral_grid") or {}
        if not neutral_state.get("slots"):
            return bot

        if execution_events is None:
            # Use fresh executions on fallback polling to minimize replacement delay.
            exec_response = client.get_executions(
                symbol=symbol, limit=100, skip_cache=True
            )
            if not exec_response.get("success"):
                return bot
            exec_list = exec_response.get("data", {}).get("list", []) or []
        else:
            exec_list = list(execution_events or [])

        if not exec_list:
            return bot

        for event in exec_list:
            bot = self.on_order_filled(
                bot,
                symbol,
                event,
                client,
                persist=False,
            )
            if bot.get("status") == "error":
                return bot

        self._update_status_fields(bot, bot.get("neutral_grid") or {})
        return self._save_runtime_bot(bot)

    def on_order_filled(
        self,
        bot: Dict[str, Any],
        symbol: str,
        fill_event: Dict[str, Any],
        client,
        persist: bool = True,
    ) -> Dict[str, Any]:
        neutral_state = bot.get("neutral_grid") or {}
        slots = neutral_state.get("slots") or {}
        if not slots:
            return bot

        exec_id = fill_event.get("execId") or fill_event.get("exec_id")
        if exec_id:
            processed = set(neutral_state.get("processed_exec_ids", []))
            if exec_id in processed:
                return bot

        order_link_id = fill_event.get("orderLinkId") or fill_event.get("order_link_id")
        parsed = self._parse_order_link_id(order_link_id)
        if not parsed:
            return bot

        bot_id_16 = self._bot_id_16(bot)
        if parsed.get("bot_id") != bot_id_16:
            return bot

        slot_id = parsed.get("slot")
        if not slot_id or slot_id not in slots:
            return bot

        if not self._is_fully_filled(fill_event):
            return bot

        slot = slots[slot_id]
        event_state = "ENTRY" if parsed.get("state") == "E" else "EXIT"
        if slot.get("state") != event_state:
            if exec_id:
                self._record_exec_id(neutral_state, exec_id)
            return bot

        next_state = "EXIT" if event_state == "ENTRY" else "ENTRY"
        original_state = slot.get("state")
        slot["state"] = next_state
        slot["order_id"] = None
        slot["order_link_id"] = None

        place_result = self._place_slot_order(
            bot=bot,
            symbol=symbol,
            client=client,
            neutral_state=neutral_state,
            slot_id=slot_id,
            slot=slot,
        )

        if exec_id:
            self._record_exec_id(neutral_state, exec_id)

        if place_result.get("skipped") and place_result.get("skip_reason") in (
            "qty_below_min",
            "notional_below_min",
        ):
            # If exchange rejects due to minimums, revert state but force a reconcile
            # so the grid can be rebuilt (wider spacing / fewer levels) instead of leaving gaps.
            slot["state"] = original_state
            neutral_state["needs_reconcile"] = True
            bot["neutral_grid"] = neutral_state
            bot["last_replacement_action"] = (
                f"{slot_id} {event_state}->ENTRY (min_notional_reconcile)"
            )
            return self._save_runtime_bot(bot) if persist else bot

        if place_result.get("error") == "position_zero":
            slot["state"] = "ENTRY"
            slot["order_id"] = None
            slot["order_link_id"] = None
            neutral_state["needs_reconcile"] = True
            bot["neutral_grid"] = neutral_state
            bot["last_replacement_action"] = (
                f"{slot_id} {event_state}->ENTRY (no_position)"
            )
            return self._save_runtime_bot(bot) if persist else bot

        if place_result.get("error") == "exit_retry":
            neutral_state["needs_reconcile"] = True
            bot["neutral_grid"] = neutral_state
            return self._save_runtime_bot(bot) if persist else bot

        bot["neutral_grid"] = neutral_state
        bot["last_fill_event"] = {
            "exec_id": exec_id,
            "order_link_id": order_link_id,
            "slot": slot_id,
            "state": event_state,
        }
        if bot.get("auto_pilot"):
            bot["auto_pilot_last_fill_at"] = time.time()
        if place_result.get("success"):
            bot["last_replacement_action"] = f"{slot_id} {event_state}->{next_state}"

        if place_result.get("error") == "hedge_mode_required":
            return place_result.get("bot", bot)
        if place_result.get("error") == "close_failed":
            return place_result.get("bot", bot)

        # ===== Per-Bot Realized PnL Tracking =====
        # Extract closedPnl from fill event and accumulate for this bot
        try:
            closed_pnl = float(
                fill_event.get("closedPnl") or fill_event.get("closed_pnl") or 0
            )
            if closed_pnl != 0:
                current_realized = float(bot.get("realized_pnl") or 0)
                bot["realized_pnl"] = current_realized + closed_pnl
                logger.info(
                    "[%s:%s] 💰 Realized PnL: +$%.4f (Total: $%.4f)",
                    symbol,
                    self._bot_id_16(bot)[:6],
                    closed_pnl,
                    bot["realized_pnl"],
                )
        except (TypeError, ValueError) as e:
            logger.debug(
                "[%s:%s] Could not parse closedPnl: %s",
                symbol,
                self._bot_id_16(bot)[:6],
                e,
            )

        return self._save_runtime_bot(bot) if persist else bot

    def recenter_if_needed(
        self, bot: Dict[str, Any], symbol: str, client
    ) -> Dict[str, Any]:
        if not bot.get("neutral_recenter_enabled"):
            return bot

        neutral_state = bot.get("neutral_grid") or {}
        levels = neutral_state.get("levels") or []
        if not levels:
            return bot

        last_price = self._get_last_price(client, symbol, skip_cache=True)
        if not last_price:
            return bot

        # SAFETY: never recenter while any position is open (prevents churn on fresh fills)
        try:
            # Use skip_cache=True for fresh safety check
            position_sizes = self._get_position_sizes(client, symbol, skip_cache=True)
            if position_sizes is None:
                logger.warning(
                    "[%s] Skipping recenter: Could not verify positions (API error)",
                    symbol,
                )
                return bot
            # Check all sides (Long=1, Short=2 or 0)
            open_positions = [
                f"{side}: {size}"
                for side, size in position_sizes.items()
                if abs(size) > 0
            ]
            if open_positions:
                logger.warning(
                    "[%s] 🛡️ RECENTER BLOCKED (Zero Tolerance): Positions open: %s. "
                    "Recenter is only allowed when flat to avoid churn-loss.",
                    symbol,
                    ", ".join(open_positions),
                )
                return bot
        except Exception as e:
            logger.warning(
                "[%s] Skipping recenter: Exception during position check: %s", symbol, e
            )
            return bot

        # Cooldown to prevent rapid recenter churn
        cooldown_sec = 0
        try:
            from config.strategy_config import NEUTRAL_RECENTER_COOLDOWN_SEC

            cooldown_sec = int(NEUTRAL_RECENTER_COOLDOWN_SEC)
        except Exception:
            cooldown_sec = 120
        cooldown_sec = max(1, cooldown_sec)
        now_ts = client._get_now_ts()
        last_recenter = self._safe_float(bot.get("_last_recenter_ts"), 0.0)
        if now_ts - last_recenter < cooldown_sec:
            return bot

        lower = (
            neutral_state.get("lower_price")
            or bot.get("grid_lower_price")
            or bot.get("lower_price")
        )
        upper = (
            neutral_state.get("upper_price")
            or bot.get("grid_upper_price")
            or bot.get("upper_price")
        )
        if not lower or not upper or upper <= lower:
            return bot

        threshold_pct = (
            float(bot.get("neutral_recenter_threshold_pct", 2.0) or 2.0) / 100.0
        )
        lower_trigger = lower * (1 - threshold_pct)
        upper_trigger = upper * (1 + threshold_pct)

        if lower_trigger <= last_price <= upper_trigger:
            return bot

        self._cancel_entry_orders(bot, symbol, client, neutral_state)

        width = upper - lower
        new_lower = max(last_price - width / 2.0, 0.0000001)
        new_upper = last_price + width / 2.0

        bot["grid_lower_price"] = new_lower
        bot["grid_upper_price"] = new_upper
        bot["lower_price"] = new_lower
        bot["upper_price"] = new_upper
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False
        bot["_last_recenter_ts"] = now_ts

        return self.reconcile_on_start(bot, symbol, client)

    def recenter_if_flat_and_stale(
        self,
        bot: Dict[str, Any],
        symbol: str,
        client,
        cooldown_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        When there are no positions or bot-tagged open orders, recenter the grid
        around the latest price (keeping current width) on a cooldown.

        DISABLED: User doesn't want recentering when there's no position.
        This prevents unwanted order placement that can get filled.
        """
        # DISABLED - return immediately without doing anything
        # User doesn't want grid recentering when there's no position
        return bot

        now_ts = client._get_now_ts()
        last_recenter = self._safe_float(bot.get("_last_flat_recenter_ts"), 0.0)
        started_at_str = bot.get("started_at")

        # Cooldown check (last recenter)
        if now_ts - last_recenter < cooldown_seconds:
            return bot

        # Startup check: Don't recenter if bot just started (< 5 min)
        # This prevents breaking the initial user-defined grid range immediately
        if started_at_str:
            try:
                # Handle ISO format '2025-01-08T13:00:00.123456'
                if isinstance(started_at_str, str):
                    started_dt = datetime.fromisoformat(
                        started_at_str.replace("Z", "+00:00")
                    )
                    started_ts = started_dt.timestamp()
                elif isinstance(started_at_str, (int, float)):
                    started_ts = float(started_at_str)
                else:
                    started_ts = 0

                if now_ts - started_ts < 300:  # 5 minutes startup grace period
                    return bot
            except Exception:
                pass  # Ignore timestamp parse errors

        # Ensure no positions for this symbol (any hedge side)
        try:
            positions = client.get_positions()
            if positions.get("success"):
                for pos in positions.get("data", {}).get("list", []) or []:
                    if pos.get("symbol") == symbol and float(pos.get("size") or 0) > 0:
                        return bot
        except Exception:
            return bot

        lower = bot.get("grid_lower_price") or bot.get("lower_price")
        upper = bot.get("grid_upper_price") or bot.get("upper_price")
        if lower is None or upper is None or upper <= lower:
            return bot

        last_price = self._get_last_price(client, symbol, skip_cache=True)
        if not last_price:
            return bot

        # Cancel any existing bot-tagged open orders before recentering
        try:
            self._cancel_bot_orders(bot, symbol, client, cancel_all=True)
            time.sleep(0.5)  # Wait for exchange to process cancels
        except Exception:
            pass

        width = upper - lower
        new_lower = max(last_price - width / 2.0, 0.0000001)
        new_upper = last_price + width / 2.0

        bot["grid_lower_price"] = new_lower
        bot["grid_upper_price"] = new_upper
        bot["lower_price"] = new_lower
        bot["upper_price"] = new_upper
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False
        bot["_last_flat_recenter_ts"] = now_ts

        logger.info(
            "[%s] Neutral flat recenter to %.6f-%.6f (width=%.6f)",
            symbol,
            new_lower,
            new_upper,
            width,
        )

        return self.reconcile_on_start(bot, symbol, client)

    def recenter_if_trailing(
        self,
        bot: Dict[str, Any],
        symbol: str,
        client,
        last_price: float,
    ) -> Dict[str, Any]:
        """
        Trailing range mode for neutral_classic_bybit.
        Recenters grid when price reaches outer 25% of range, keeping positions intact.
        """
        range_mode = (bot.get("range_mode") or "fixed").lower()
        if range_mode != "trailing":
            return bot

        if not bot.get("neutral_recenter_enabled"):
            return bot

        lower = bot.get("grid_lower_price") or bot.get("lower_price")
        upper = bot.get("grid_upper_price") or bot.get("upper_price")
        if not lower or not upper or upper <= lower:
            return bot

        if not last_price or last_price <= 0:
            return bot

        # SAFETY: never recenter while any position is open (prevents churn on fresh fills)
        try:
            # Use skip_cache=True for critical safety check
            pos_sizes = self._get_position_sizes(client, symbol, skip_cache=True)
            if pos_sizes is None:
                logger.warning(
                    "[%s] Skipping trailing recenter: Could not verify positions (API error)",
                    symbol,
                )
                return bot
            if any(abs(size) > 0 for size in pos_sizes.values()):
                logger.debug(
                    "[%s] Skipping trailing recenter: Positions open %s",
                    symbol,
                    pos_sizes,
                )
                return bot
        except Exception as e:
            # If we cannot check positions, fail safe by skipping recenter
            logger.warning(
                "[%s] Skipping trailing recenter: Exception during position check: %s",
                symbol,
                e,
            )
            return bot

        width = upper - lower

        # Use config values with backward-compatible fallbacks
        # Clamp outer_pct to safe range: 0.01 <= p <= 0.49 to avoid invalid inner ranges
        try:
            from config.strategy_config import TRAILING_RECENTER_OUTER_PCT

            outer_pct = float(TRAILING_RECENTER_OUTER_PCT)
        except (TypeError, ValueError):
            outer_pct = 0.25  # Fallback to old behavior
        outer_pct = max(0.01, min(0.49, outer_pct))

        inner_lower = lower + width * outer_pct
        inner_upper = upper - width * outer_pct

        # Only recenter if price in outer zone (outside inner range)
        if inner_lower <= last_price <= inner_upper:
            return bot

        # STABILITY: Only shift if price has moved significantly from current center
        # This prevents micro-churn in tight ranges.
        current_center = (lower + upper) / 2.0
        price_move_pct = abs(last_price - current_center) / current_center
        if price_move_pct < 0.005:  # 0.5% minimum move from center
            return bot

        # Cooldown to prevent rapid recentering (use config with fallback)
        try:
            cooldown_sec = int(TRAILING_RECENTER_COOLDOWN_SEC)
        except (TypeError, ValueError):
            cooldown_sec = 60  # Fallback to old behavior
        cooldown_sec = max(1, cooldown_sec)  # Ensure at least 1 second

        now_ts = client._get_now_ts()
        last_recenter = self._safe_float(bot.get("_last_trailing_recenter_ts"), 0.0)
        if now_ts - last_recenter < cooldown_sec:
            return bot

        # Calculate new range centered around current price
        new_lower = max(last_price - width / 2.0, 0.0000001)
        new_upper = last_price + width / 2.0

        logger.info(
            "[%s] 🔄 Trailing recenter: Price %.6f in outer zone (outer_pct=%.2f), move_pct=%.4f from center %.6f, pos_sizes=%s, shifting %.6f-%.6f -> %.6f-%.6f",
            symbol,
            last_price,
            outer_pct,
            price_move_pct,
            current_center,
            pos_sizes,
            lower,
            upper,
            new_lower,
            new_upper,
        )

        # Cancel existing bot orders (Full clean slate for trailing recenter)
        self._cancel_bot_orders(bot, symbol, client, cancel_all=True)
        time.sleep(0.5)  # Wait for exchange to process cancels

        # Update bot config with new range
        bot["grid_lower_price"] = new_lower
        bot["grid_upper_price"] = new_upper
        bot["lower_price"] = new_lower
        bot["upper_price"] = new_upper
        bot["_last_trailing_recenter_ts"] = now_ts

        # Reset grid state to reinitialize with new levels
        bot["neutral_grid"] = {}
        bot["neutral_grid_initialized"] = False

        return self.reconcile_on_start(bot, symbol, client)

    def ensure_hedge_mode(
        self, bot: Dict[str, Any], symbol: str, client
    ) -> Dict[str, Any]:
        mode_result = client.get_position_mode(symbol=symbol)
        if mode_result.get("success"):
            if mode_result.get("mode") == "hedge":
                return bot

            if mode_result.get("mode") == "one_way":
                # Check cooldown before attempting switch
                now_ts = time.time()
                last_switch = self._safe_float(bot.get("_last_mode_switch_ts"), 0.0)
                if now_ts - last_switch < 300:
                    return self._set_error(
                        bot,
                        "HEDGE_MODE_REQUIRED: Position mode is one-way. Switch attempt on cooldown (300s).",
                        error_code="HEDGE_MODE_REQUIRED",
                    )

                bot["_last_mode_switch_ts"] = now_ts
                logger.info("[%s] Attempting to auto-switch to Hedge Mode...", symbol)
                switch_res = client.switch_position_mode(symbol, mode=3)  # 3 = Hedge
                if switch_res.get("success"):
                    logger.info(
                        "[%s] Successfully auto-switched to Hedge Mode.", symbol
                    )
                    return bot
                else:
                    error_msg = switch_res.get("error", "unknown")
                    # If retCode is 110059, it means it's already set
                    if switch_res.get("retCode") == 110059:
                        return bot

                    return self._set_error(
                        bot,
                        f"HEDGE_MODE_REQUIRED: Failed to auto-switch position mode ({error_msg}). "
                        "Please ensure you have no open positions or pending orders for this symbol.",
                        error_code="HEDGE_MODE_REQUIRED",
                    )

        return self._set_error(
            bot,
            "HEDGE_MODE_REQUIRED: unable to confirm hedge mode",
            error_code="HEDGE_MODE_REQUIRED",
        )

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _get_grid_config(
        self, bot: Dict[str, Any]
    ) -> Optional[Tuple[float, float, int]]:
        lower = bot.get("grid_lower_price") or bot.get("lower_price")
        upper = bot.get("grid_upper_price") or bot.get("upper_price")
        total_levels = bot.get("grid_levels_total") or bot.get("grid_count")
        try:
            lower = float(lower)
            upper = float(upper)
            total_levels = int(total_levels)
        except (TypeError, ValueError):
            return None
        return lower, upper, total_levels

    def _apply_small_capital_tuning(
        self,
        bot: Dict[str, Any],
        symbol: str,
        total_levels: int,
        instrument: Dict[str, Any],
    ) -> int:
        invest = float(bot.get("investment", 0) or 0)
        leverage = float(bot.get("leverage", 1) or 1)
        small_capital_active = (
            SMALL_CAPITAL_MODE_ENABLED and invest <= SMALL_CAPITAL_INVEST_USDT_THRESHOLD
        )
        bot["small_capital_mode_active"] = small_capital_active
        if not small_capital_active:
            return total_levels

        adaptive = self.adaptive_config_service.compute_effective_config(
            symbol=symbol,
            invest_usdt=invest,
            leverage=leverage,
            target_levels=total_levels,
            instrument=instrument,
            atr_5m_pct=bot.get("atr_5m_pct"),
            atr_15m_pct=bot.get("atr_15m_pct"),
            liq_distance_pct=None,
        )
        effective_levels = int(adaptive.get("effective_levels") or total_levels)
        if effective_levels < total_levels:
            bot["grid_levels_total_effective"] = effective_levels
        return max(1, min(total_levels, effective_levels))

    def _apply_min_notional_guard(
        self,
        bot: Dict[str, Any],
        total_levels: int,
        instrument: Dict[str, Any],
        available_equity: Optional[float] = None,
    ) -> int:
        """
        Hard guard: Reduce total_levels if the resulting per-order notional
        would be less than the instrument's minimum (plus a small safety buffer).
        """
        min_notional = float(instrument.get("min_notional_value") or 5.0)
        # Add 10% safety buffer to avoid rounding errors or price fluctuations causing retCode=110017
        safe_min_notional = min_notional * 1.1

        usable_notional = self._get_usable_notional(bot, available_equity)
        if usable_notional <= 0:
            return total_levels

        # Max allowed slots = usable / safe_min
        # Since total_levels = slots + 1 (roughly, or just slots depending on impl),
        # let's assume worst case where each level needs an order.
        # Actually in this neutral grid, # slots = levels - 1.
        # Orders are placed per slot. So we care about slots.
        # usable_notional / slots >= safe_min_notional
        # slots <= usable_notional / safe_min_notional

        max_slots = int(usable_notional / safe_min_notional)
        max_levels = max_slots  # Since 100 levels -> 100 lines usually or 99 slots. Let's start with this.

        # Ensure at least minimal grid
        max_levels = max(2, max_levels)

        if max_levels < total_levels:
            logger.warning(
                "[%s:%s] 🛡️ MinNotionalGuard: Reducing levels %d -> %d to satisfy min notional %.2f (usable=%.2f)",
                bot.get("symbol"),
                self._bot_id_16(bot)[:6],
                total_levels,
                max_levels,
                safe_min_notional,
                usable_notional,
            )
            bot["grid_levels_total_effective"] = max_levels
            return max_levels

        return total_levels

    def _get_usable_notional(
        self, bot: Dict[str, Any], available_equity: Optional[float] = None
    ) -> float:
        investment = float(bot.get("investment", 0) or 0)
        leverage = float(bot.get("leverage", 1) or 1)
        if investment <= 0 or leverage <= 0:
            return 0.0

        # Unified Reserve Check
        reserve_usd, usable_investment = self._calculate_auto_margin_reserve(
            bot, investment, available_equity
        )

        return usable_investment * leverage

    def _get_usdt_available_balance(self, client) -> float:
        """Fetch available USDT balance from Bybit."""
        try:
            resp = client.get_wallet_balance(coin="USDT")
            if resp.get("retCode") == 0:
                list_data = resp.get("result", {}).get("list", [])
                if list_data:
                    coins = list_data[0].get("coin", [])
                    for c in coins:
                        if c.get("coin") == "USDT":
                            return float(
                                c.get("availableToWithdraw")
                                or c.get("availableBalance")
                                or 0.0
                            )
            return 0.0
        except Exception:
            return 0.0

    def _compute_per_order_qty(
        self, bot: Dict[str, Any], instrument: Dict[str, Any], levels: List[float]
    ) -> float:
        last_price = self._get_last_known_price(levels)
        min_price = min(levels) if levels else last_price
        total_slots = max(len(levels) - 1, 1)

        if last_price <= 0 or not instrument:
            return 0.0

        total_notional = self._get_usable_notional(bot)
        qty_raw = total_notional / (total_slots * last_price)
        qty_step = instrument.get("qty_step") or 0
        if qty_step > 0:
            qty_raw = self._round_to_step(qty_raw, qty_step, round_down=True)
        min_order_qty = instrument.get("min_order_qty") or 0.0
        min_notional_value = instrument.get("min_notional_value") or 0.0
        min_qty_for_notional = 0.0
        price_for_notional = min_price or last_price
        if min_notional_value and price_for_notional > 0:
            if qty_step > 0:
                steps = math.ceil((min_notional_value / price_for_notional) / qty_step)
                min_qty_for_notional = steps * qty_step
            else:
                min_qty_for_notional = min_notional_value / price_for_notional

        return max(qty_raw, min_order_qty, min_qty_for_notional, 0.0)

    def _get_last_known_price(self, levels: List[float]) -> float:
        if not levels:
            return 0.0
        mid = len(levels) // 2
        return float(levels[mid])

    def _get_open_orders(
        self, client, symbol: str, skip_cache: bool = False
    ) -> List[Dict[str, Any]]:
        if skip_cache:
            response = client.get_open_orders(symbol, limit=200, skip_cache=True)
        else:
            response = client.get_open_orders(symbol, limit=200)
        if not response.get("success"):
            return []
        data = response.get("data", {}) or {}
        order_list = data.get("list", [])
        if isinstance(order_list, list):
            return order_list
        return []

    def count_bot_open_orders(
        self,
        bot: Dict[str, Any],
        symbol: str,
        client,
        skip_cache: bool = False,
    ) -> int:
        bot_id_16 = self._bot_id_16(bot)
        if not bot_id_16:
            return 0
        orders = self._get_open_orders(client, symbol, skip_cache=skip_cache)
        count = 0
        for order in orders:
            parsed = self._parse_order_link_id(order.get("orderLinkId"))
            if parsed and parsed.get("bot_id") == bot_id_16:
                count += 1
        return count

    def _get_position_sizes(
        self, client, symbol: str, skip_cache: bool = False
    ) -> Optional[Dict[int, float]]:
        sizes = {1: 0.0, 2: 0.0}
        try:
            # Pass skip_cache to BybitClient for fresher data
            resp = client.get_positions(skip_cache=skip_cache)
            if not resp.get("success"):
                logger.warning(
                    "[%s] ⚠️ Failed to fetch position sizes: %s",
                    symbol,
                    resp.get("error"),
                )
                return None  # Return None on failure to avoid "False Flat" readings
            positions = (resp.get("data", {}) or {}).get("list", []) or []
            for pos in positions:
                if pos.get("symbol") != symbol:
                    continue
                idx = int(pos.get("positionIdx", 0) or 0)
                try:
                    sizes[idx] = float(pos.get("size", 0) or 0)
                except (TypeError, ValueError):
                    sizes[idx] = 0.0
        except Exception as e:
            logger.warning("[%s] ⚠️ Exception fetching position sizes: %s", symbol, e)
            return None
        return sizes

    def _is_volatility_gate_active(self, bot: Dict[str, Any]) -> bool:
        if not bot.get("neutral_volatility_gate_enabled"):
            return False

        threshold_raw = float(
            bot.get("neutral_volatility_gate_threshold_pct") or 5.0
        )
        threshold = threshold_raw / 100.0 if threshold_raw > 1.0 else threshold_raw
        current_atr = float(bot.get("atr_5m_pct") or 0.0)

        if current_atr > threshold:
            # We don't spam log here because it's checked per slot order.
            # But maybe we should log once per cycle?
            # For now, just return True. The caller might log if needed.
            return True

        return False

    def _place_slot_order(
        self,
        bot: Dict[str, Any],
        symbol: str,
        client,
        neutral_state: Dict[str, Any],
        slot_id: str,
        slot: Dict[str, Any],
    ) -> Dict[str, Any]:
        # PRE-FLIGHT STATUS CHECK: Ensure bot is still running
        if bot:
            bot_id = bot.get("id")
            if bot_id:
                fresh_bot = self.bot_storage.get_bot(bot_id)
                if fresh_bot and fresh_bot.get("status") not in (
                    "running",
                    "paused",
                    "recovering",
                ):
                    logger.warning(
                        f"[{symbol}] NeutralGrid order placement aborted: bot status is '{fresh_bot.get('status')}'"
                    )
                    return {
                        "success": False,
                        "error": "bot_not_running_abort",
                        "retCode": -1,
                    }

        side, reduce_only, position_idx = self._slot_order_params(slot)
        price = (
            slot.get("entry_price")
            if slot.get("state") == "ENTRY"
            else slot.get("exit_price")
        )
        qty = neutral_state.get("per_order_qty") or 0.0
        if price is None or price <= 0:
            return {"success": False, "error": "invalid_price"}

        instrument = self._get_instrument_info(client, symbol)
        if not instrument:
            return {"success": False, "error": "instrument_missing"}

        if not reduce_only and (
            bot.get("_session_timer_block_opening_orders")
            or bot.get("session_timer_no_new_entries_active")
            or bot.get("_small_capital_block_opening_orders")
            or bot.get("_nlp_block_opening_orders")
            or bot.get("_auto_pilot_loss_budget_block_openings")
        ):
            if bot.get("_session_timer_block_opening_orders") or bot.get(
                "session_timer_no_new_entries_active"
            ):
                bot["last_skip_reason"] = "session_timer_blocked"
            if bot.get("_auto_pilot_loss_budget_block_openings"):
                bot["last_skip_reason"] = "auto_pilot_loss_budget_blocked"
            logger.debug(
                "[%s] Grid placement blocked: _session=%s _block=%s _small=%s _nlp=%s _ap_loss=%s gate_reason=%s",
                symbol,
                bot.get("_session_timer_block_opening_orders"),
                bot.get("_block_opening_orders"),
                bot.get("_small_capital_block_opening_orders"),
                bot.get("_nlp_block_opening_orders"),
                bot.get("_auto_pilot_loss_budget_block_openings"),
                bot.get("_gate_blocked_reason"),
            )
            return {
                "success": False,
                "error": "opening_blocked",
                "skipped": True,
                "skip_reason": (
                    "auto_pilot_loss_budget_blocked"
                    if bot.get("_auto_pilot_loss_budget_block_openings")
                    else bot.get("last_skip_reason") or "opening_blocked"
                ),
            }

        if not reduce_only and self._is_volatility_gate_active(bot):
            return {
                "success": False,
                "error": "volatility_gate_active",
                "skipped": True,
            }

        # MICRO-BIAS per-side skip (ENTRY orders only)
        # Skip counter-bias orders to reduce inventory accumulation against micro-trend
        if not reduce_only:
            if bot.get("_micro_bias_skip_buy") and side == "Buy":
                logger.debug(
                    "[%s] MICRO_BIAS skip Buy ENTRY order (score=%.3f direction=%s)",
                    symbol,
                    bot.get("_micro_bias_score", 0.0),
                    bot.get("_micro_bias_direction", "NEUTRAL"),
                )
                return {"success": False, "error": "micro_bias_skip", "skipped": True}
            if bot.get("_micro_bias_skip_sell") and side == "Sell":
                logger.debug(
                    "[%s] MICRO_BIAS skip Sell ENTRY order (score=%.3f direction=%s)",
                    symbol,
                    bot.get("_micro_bias_score", 0.0),
                    bot.get("_micro_bias_direction", "NEUTRAL"),
                )
                return {"success": False, "error": "micro_bias_skip", "skipped": True}

        if not reduce_only:
            if bot.get("_entry_structure_skip_buy") and side == "Buy":
                logger.debug(
                    "[%s] Structure gate skip Buy ENTRY order: %s",
                    symbol,
                    bot.get("_entry_structure_buy_reason", "nearby resistance"),
                )
                return {
                    "success": False,
                    "error": "structure_entry_skip",
                    "skipped": True,
                    "skip_reason": bot.get(
                        "_entry_structure_buy_reason", "nearby resistance"
                    ),
                }
            if bot.get("_entry_structure_skip_sell") and side == "Sell":
                logger.debug(
                    "[%s] Structure gate skip Sell ENTRY order: %s",
                    symbol,
                    bot.get("_entry_structure_sell_reason", "nearby support"),
                )
                return {
                    "success": False,
                    "error": "structure_entry_skip",
                    "skipped": True,
                    "skip_reason": bot.get(
                        "_entry_structure_sell_reason", "nearby support"
                    ),
                }

        # SPREAD CHECK: Prevent immediate fill/stacking
        # If target price would cross spread, auto-reprice one tick away.
        current_price = self._get_last_price(client, symbol, skip_cache=True)
        tick_size = float(instrument.get("tick_size") or 0.0)
        if current_price and current_price > 0:
            if side == "Buy" and price >= current_price:
                if tick_size <= 0:
                    tick_size = max(current_price * 1e-6, 1e-8)
                adjusted_price = self._round_price_for_order(
                    current_price - tick_size, tick_size, side="Buy"
                )
                if adjusted_price <= 0 or adjusted_price >= current_price:
                    return {
                        "success": False,
                        "error": "would_cross_spread",
                        "skipped": True,
                    }
                logger.debug(
                    "[%s] Neutral: Repriced Buy %.8f -> %.8f (last=%.8f)",
                    symbol,
                    price,
                    adjusted_price,
                    current_price,
                )
                price = adjusted_price
            elif side == "Sell" and price <= current_price:
                if tick_size <= 0:
                    tick_size = max(current_price * 1e-6, 1e-8)
                adjusted_price = self._round_price_for_order(
                    current_price + tick_size, tick_size, side="Sell"
                )
                if adjusted_price <= current_price:
                    return {
                        "success": False,
                        "error": "would_cross_spread",
                        "skipped": True,
                    }
                logger.debug(
                    "[%s] Neutral: Repriced Sell %.8f -> %.8f (last=%.8f)",
                    symbol,
                    price,
                    adjusted_price,
                    current_price,
                )
                price = adjusted_price

        if not self._can_open_side(bot, symbol, client, side, price):
            return {"success": False, "error": "position_cap"}

        normalized_qty, skip_reason = self._preflight_qty(
            bot=bot,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            reduce_only=reduce_only,
            instrument=instrument,
            client=client,
        )
        if not normalized_qty:
            return {
                "success": False,
                "error": skip_reason or "qty_below_min",
                "skipped": True,
                "skip_reason": skip_reason,
            }

        if (
            not reduce_only
            and bot.get("auto_pilot")
            and str(bot.get("auto_pilot_loss_budget_state") or "") == "low"
        ):
            max_opening_notional = float(
                bot.get("auto_pilot_low_budget_max_opening_notional_usdt") or 0.0
            )
            order_notional = float(price or 0.0) * float(normalized_qty or 0.0)
            if max_opening_notional > 0 and order_notional > max_opening_notional:
                bot["last_skip_reason"] = "auto_pilot_low_budget_notional_cap"
                logger.debug(
                    "[%s] Neutral grid Auto-Pilot low-budget cap: notional=%.4f > max=%.4f",
                    symbol,
                    order_notional,
                    max_opening_notional,
                )
                return {
                    "success": False,
                    "error": "auto_pilot_low_budget_notional_cap",
                    "skipped": True,
                    "skip_reason": "auto_pilot_low_budget_notional_cap",
                }

        link_id = self._next_order_link_id(
            bot, neutral_state, slot_id, slot.get("state")
        )
        time_in_force = "PostOnly" if bot.get("neutral_post_only") else "GTC"

        result = client.create_order(
            symbol=symbol,
            side=side,
            qty=normalized_qty,
            order_type="Limit",
            price=price,
            reduce_only=reduce_only,
            time_in_force=time_in_force,
            order_link_id=link_id,
            position_idx=position_idx,
            qty_is_normalized=True,
            ownership_snapshot=build_order_ownership_snapshot(
                bot,
                source="neutral_grid_service",
                action="reduce_only_close" if reduce_only else "entry",
                close_reason=slot.get("state"),
            ),
        )

        if result.get("success"):
            order_data = result.get("data", {}) or {}
            now_ts = client._get_now_ts() if hasattr(client, "_get_now_ts") else time.time()
            self._mark_slot_order_submitted(
                slot,
                order_id=order_data.get("orderId"),
                order_link_id=link_id,
                now_ts=now_ts,
            )
            return {"success": True}

        ret_code = result.get("retCode")
        error_msg = result.get("error", "order_failed")
        try:
            ret_code_int = int(ret_code) if ret_code is not None else None
        except (TypeError, ValueError):
            ret_code_int = None
        if ret_code == 110072:
            now_ts = client._get_now_ts() if hasattr(client, "_get_now_ts") else time.time()
            self._mark_slot_order_submitted(
                slot,
                order_id=slot.get("order_id"),
                order_link_id=link_id,
                now_ts=now_ts,
            )
            return {"success": True, "duplicate": True}
        if self._is_hedge_mode_error(ret_code, error_msg):
            error = (
                "HEDGE_MODE_REQUIRED: hedge mode not enabled or positionIdx unsupported"
            )
            bot = self._set_error(bot, error, error_code="HEDGE_MODE_REQUIRED")
            return {"success": False, "error": "hedge_mode_required", "bot": bot}

        if ret_code_int == 110017:
            # 110017 = OrderQtyZero (reduce-only with 0 position). Common if position closed externally or by TP.
            # Log as info, not warning, to reduce spam.
            logger.info(
                "[%s:%s] Exit order skipped (retCode=110017 - No Position): %s (slot=%s, price=%s, idx=%s)",
                symbol,
                self._bot_id_16(bot)[:6],
                error_msg,
                slot_id,
                price,
                position_idx,
            )
            return {"success": False, "error": "position_zero", "position_empty": True}

        if reduce_only:
            if self._is_reduce_only_no_position_error(ret_code, error_msg):
                size = self._get_position_size(
                    client, symbol, position_idx, skip_cache=True
                )
                if size <= 0:
                    logger.warning(
                        "[%s:%s] Exit order skipped: no position (slot=%s, price=%s, idx=%s)",
                        symbol,
                        self._bot_id_16(bot)[:6],
                        slot_id,
                        price,
                        position_idx,
                    )
                    return {
                        "success": False,
                        "error": "position_zero",
                        "position_empty": True,
                    }
                return {
                    "success": False,
                    "error": "exit_retry",
                    "position_empty": False,
                }
            error = f"CLOSE_FAILED: exit order failed ({error_msg})"
            bot = self._set_error(
                bot, error, error_code="CLOSE_FAILED", block_opening=True
            )
            return {"success": False, "error": "close_failed", "bot": bot}

        if ret_code_int in [110007, 110045]:  # Insufficient balance / margin
            logger.warning(
                "[%s:%s] ⚠ Insufficient margin (ret=%s). Attempting to prune distant orders...",
                symbol,
                self._bot_id_16(bot)[:6],
                ret_code,
            )
            pruned = self._prune_distant_orders(bot, symbol, client)
            if pruned > 0:
                return {
                    "success": False,
                    "error": "insufficient_margin_pruned",
                    "skipped": True,
                }
            return {
                "success": False,
                "error": "insufficient_margin",
                "retCode": ret_code,
            }

        if ret_code_int == 10001:
            logger.info(
                "[%s:%s] Bybit transient response (10001). Will retry next cycle.",
                symbol,
                self._bot_id_16(bot)[:6],
            )
            return {"success": False, "error": "internal_error_10001", "skipped": True}

        return {"success": False, "error": error_msg, "retCode": ret_code}

    def _slot_order_params(self, slot: Dict[str, Any]) -> Tuple[str, bool, int]:
        leg = slot.get("leg")
        state = slot.get("state")
        if leg == "LONG":
            if state == "ENTRY":
                return "Buy", False, 1
            return "Sell", True, 1
        if state == "ENTRY":
            return "Sell", False, 2
        return "Buy", True, 2

    def _can_open_side(
        self, bot: Dict[str, Any], symbol: str, client, side: str, price: float
    ) -> bool:
        if not MAX_POSITION_ENABLED:
            return True

        cap_override = bot.get("ai_max_position_cap_pct")
        if cap_override is None:
            max_position_pct = get_mode_max_position_pct(bot.get("mode"))
        else:
            max_position_pct = float(cap_override or MAX_POSITION_PCT * 100) / 100.0
        investment = float(bot.get("investment", 0) or 0)
        leverage = float(bot.get("leverage", 1) or 1)
        max_notional = investment * leverage * max_position_pct

        positions_resp = client.get_positions()
        if not positions_resp.get("success"):
            return True

        positions = positions_resp.get("data", {}).get("list", []) or []
        for pos in positions:
            if pos.get("symbol") != symbol:
                continue
            pos_idx = int(pos.get("positionIdx", 0) or 0)
            pos_size = float(pos.get("size", 0) or 0)
            if pos_size <= 0:
                continue
            if side == "Buy" and pos_idx == 1:
                if pos_size * price >= max_notional:
                    return False
            if side == "Sell" and pos_idx == 2:
                if pos_size * price >= max_notional:
                    return False
        return True

    def _get_instrument_info(self, client, symbol: str) -> Optional[Dict[str, Any]]:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]

        response = client.get_instruments_info(symbol)
        if not response.get("success"):
            logger.warning(
                "Failed to fetch instrument info for %s: %s",
                symbol,
                response.get("error"),
            )
            return None

        data = response.get("data", {}) or {}
        inst_list = data.get("list", []) or []
        if not inst_list:
            return None

        inst = inst_list[0]
        lot_size_filter = inst.get("lotSizeFilter", {}) or {}
        price_filter = inst.get("priceFilter", {}) or {}

        def _to_positive(value: Any) -> Optional[float]:
            try:
                num = float(value)
            except (TypeError, ValueError):
                return None
            return num if num > 0 else None

        min_notional_value = _to_positive(lot_size_filter.get("minNotionalValue"))
        if min_notional_value is None:
            min_notional_value = _to_positive(lot_size_filter.get("minOrderAmt"))
        if min_notional_value is None:
            min_notional_value = 5.0

        min_order_qty = _to_positive(lot_size_filter.get("minOrderQty"))
        qty_step = _to_positive(lot_size_filter.get("qtyStep"))
        if not min_order_qty or not qty_step:
            logger.warning(
                "Missing qty filters for %s (minQty=%s step=%s)",
                symbol,
                min_order_qty,
                qty_step,
            )
            return None

        info = {
            "min_order_qty": min_order_qty,
            "qty_step": qty_step,
            "tick_size": _to_positive(price_filter.get("tickSize")) or 0.0001,
            "min_notional_value": min_notional_value,
        }
        self._instrument_cache[symbol] = info
        return info

    def _preflight_qty(
        self,
        bot: Dict[str, Any],
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool,
        instrument: Dict[str, Any],
        client,
    ) -> Tuple[Optional[float], Optional[str]]:
        normalized_qty = client.normalize_qty(symbol, qty, log_skip=False)
        min_qty = instrument.get("min_order_qty")
        qty_step = instrument.get("qty_step")
        if qty_step:
            normalized_qty = self._round_to_step(
                normalized_qty or 0, qty_step, round_down=True
            )

        # For reduce_only, cap qty to actual remaining position
        if reduce_only and normalized_qty:
            # Determine position index: Sell closes LONG (1), Buy closes SHORT (2)
            pos_idx = 1 if side == "Sell" else 2
            pos_sizes = self._get_position_sizes(client, symbol)
            pos_size = pos_sizes.get(pos_idx, 0.0)

            if pos_size <= 0:
                # No position to reduce - skip order silently (race condition)
                return None, "no_position_for_reduce_only"

            # Cap to remaining position size
            if normalized_qty > pos_size:
                normalized_qty = pos_size
                # Re-round to step after capping
                if qty_step:
                    normalized_qty = self._round_to_step(
                        normalized_qty, qty_step, round_down=True
                    )

        if not normalized_qty or (min_qty and normalized_qty < min_qty):
            # Only log as warning if not a race-condition reduce-only skip
            if not reduce_only or not (normalized_qty and normalized_qty < min_qty):
                self._log_skip_order(
                    bot,
                    symbol,
                    side,
                    qty,
                    normalized_qty,
                    min_qty,
                    qty_step,
                    price,
                    "qty_below_min",
                )
            return None, "qty_below_min"

        min_notional_value = instrument.get("min_notional_value")
        notional = price * normalized_qty if price else 0
        if min_notional_value and notional < min_notional_value:
            # For reduce-only, if we cap and it falls below min notional, it's often better to just skip
            if not reduce_only:
                self._log_skip_order(
                    bot,
                    symbol,
                    side,
                    qty,
                    normalized_qty,
                    min_qty,
                    qty_step,
                    price,
                    "notional_below_min",
                    min_notional_value=min_notional_value,
                )
            return None, "notional_below_min"

        return normalized_qty, None

    def _log_skip_order(
        self,
        bot: Dict[str, Any],
        symbol: str,
        side: str,
        raw_qty: float,
        normalized_qty: Optional[float],
        min_qty: Optional[float],
        qty_step: Optional[float],
        price: float,
        reason: str,
        min_notional_value: Optional[float] = None,
    ) -> None:
        bot["skipped_small_qty_count"] = (
            int(bot.get("skipped_small_qty_count", 0) or 0) + 1
        )
        bot["last_skip_reason"] = reason

        bot_id = bot.get("id", "unknown")
        key = f"{bot_id}:{symbol}:{reason}"
        now = time.time()
        last_ts = self._last_skip_log_ts.get(key, 0)
        if now - last_ts < SKIP_SMALL_QTY_LOG_COOLDOWN_SEC:
            return
        self._last_skip_log_ts[key] = now

        logger.warning(
            "skip_order bot_id=%s symbol=%s side=%s reason=%s raw_qty=%s normalized_qty=%s min_qty=%s qty_step=%s price=%s min_notional=%s",
            bot_id,
            symbol,
            side,
            reason,
            raw_qty,
            normalized_qty,
            min_qty,
            qty_step,
            price,
            min_notional_value,
        )

    def _set_error(
        self,
        bot: Dict[str, Any],
        message: str,
        error_code: Optional[str] = None,
        block_opening: bool = False,
    ) -> Dict[str, Any]:
        bot["status"] = "error"
        bot["last_error"] = message
        bot["last_run_at"] = datetime.now(timezone.utc).isoformat()
        if error_code:
            bot["error_code"] = error_code
        if block_opening:
            bot["_block_opening_orders"] = True
        self.bot_storage.save_bot(bot)
        logger.error("[%s] %s", bot.get("symbol", "?"), message)
        return bot

    def _save_runtime_bot(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        if hasattr(self.bot_storage, "save_runtime_bot"):
            return self.bot_storage.save_runtime_bot(bot)
        return self.bot_storage.save_bot(bot)

    def _record_exec_id(self, neutral_state: Dict[str, Any], exec_id: str) -> None:
        exec_ids = list(neutral_state.get("processed_exec_ids", []))
        exec_ids.append(exec_id)
        if len(exec_ids) > MAX_EXEC_ID_CACHE:
            exec_ids = exec_ids[-MAX_EXEC_ID_CACHE:]
        neutral_state["processed_exec_ids"] = exec_ids

    def _find_mid_index(self, levels: List[float], last_price: Optional[float]) -> int:
        if not levels:
            return 0
        if not last_price or last_price <= 0:
            return len(levels) // 2
        for idx in range(len(levels) - 1, -1, -1):
            if levels[idx] <= last_price:
                return idx
        return 0

    def _get_last_price(
        self, client, symbol: str, skip_cache: bool = False
    ) -> Optional[float]:
        response = client.get_tickers(symbol, skip_cache=skip_cache)
        if not response.get("success"):
            return None
        data = response.get("data", {}) or {}
        tickers = data.get("list", []) or []
        if not tickers:
            return None
        try:
            last_price = float(tickers[0].get("lastPrice", 0) or 0)
            return last_price if last_price > 0 else None
        except (TypeError, ValueError):
            return None

    def _build_slots(
        self, levels: List[float], mid_index: int
    ) -> Dict[str, Dict[str, Any]]:
        slots: Dict[str, Dict[str, Any]] = {}
        total_levels = len(levels) - 1
        width = self._slot_width(total_levels)
        for i in range(0, mid_index):
            slot_id = f"L{str(i).zfill(width)}"
            slots[slot_id] = {
                "leg": "LONG",
                "level": i,
                "state": "ENTRY",
                "entry_price": levels[i],
                "exit_price": levels[i + 1],
                "order_id": None,
                "order_link_id": None,
            }
        for j in range(mid_index + 1, len(levels)):
            slot_id = f"S{str(j).zfill(width)}"
            slots[slot_id] = {
                "leg": "SHORT",
                "level": j,
                "state": "ENTRY",
                "entry_price": levels[j],
                "exit_price": levels[j - 1],
                "order_id": None,
                "order_link_id": None,
            }
        return slots

    def _slot_width(self, total_levels: int) -> int:
        return max(2, len(str(max(total_levels, 1))))

    def _mark_slot_order_submitted(
        self,
        slot: Dict[str, Any],
        order_id: Optional[str],
        order_link_id: Optional[str],
        now_ts: float,
    ) -> None:
        slot["order_id"] = order_id
        slot["order_link_id"] = order_link_id
        slot["last_order_submit_ts"] = float(now_ts or time.time())
        slot["visibility_miss_count"] = 0

    def _should_preserve_missing_slot_order(
        self,
        slot: Dict[str, Any],
        now_ts: float,
    ) -> bool:
        if not slot.get("order_link_id") and not slot.get("order_id"):
            return False
        miss_count = int(slot.get("visibility_miss_count") or 0) + 1
        slot["visibility_miss_count"] = miss_count
        if miss_count <= OPEN_ORDER_MISS_TOLERANCE:
            return True
        last_seen_ts = self._safe_float(slot.get("last_order_seen_ts"), 0.0)
        last_submit_ts = self._safe_float(slot.get("last_order_submit_ts"), 0.0)
        anchor_ts = max(last_seen_ts, last_submit_ts)
        return anchor_ts > 0 and (now_ts - anchor_ts) < OPEN_ORDER_VISIBILITY_GRACE_SEC

    def _next_order_link_id(
        self,
        bot: Dict[str, Any],
        neutral_state: Dict[str, Any],
        slot_id: str,
        state: str,
    ) -> Optional[str]:
        bot_id = bot.get("id")
        if not bot_id:
            return None
        bot_id_16 = self._bot_id_16(bot)
        seq = int(neutral_state.get("seq", 0) or 0) + 1
        neutral_state["seq"] = seq
        seq_str = f"{seq % 1000000:06d}"
        state_char = "E" if state == "ENTRY" else "X"
        return f"bv2:{bot_id_16}:{seq_str}:{slot_id}:{state_char}"

    def _parse_order_link_id(
        self, order_link_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if not order_link_id or not isinstance(order_link_id, str):
            return None

        # v2 format: bv2:{bot_id_16}:{ts_8}{seq}{side}{intent}
        if order_link_id.startswith("bv2:"):
            parts = order_link_id.split(":")
            if len(parts) == 5:
                _, bot_id_16, seq_str, slot, state = parts
                if state in ("E", "X"):
                    try:
                        seq = int(seq_str)
                    except ValueError:
                        seq = None
                    return {
                        "bot_id": bot_id_16,
                        "seq": seq,
                        "slot": slot,
                        "state": state,
                    }

        # Fallback for older bot:short_id format or scale-out/recovery orders
        if order_link_id.startswith("bot:"):
            parts = order_link_id.split(":")
            if len(parts) >= 2:
                # We return the bot_id part for comparison even if slot/state is missing
                return {"bot_id": parts[1], "seq": None, "slot": None, "state": None}

        return None

    def _bot_id_16(self, bot: Dict[str, Any]) -> str:
        bot_id = bot.get("id", "")
        return bot_id.replace("-", "")[:16]

    def _is_fully_filled(self, event: Dict[str, Any]) -> bool:
        status = (
            event.get("orderStatus") or event.get("order_status") or event.get("status")
        )
        if isinstance(status, str) and status.lower() in (
            "filled",
            "filled/complete",
            "complete",
        ):
            return True
        leaves = (
            event.get("leavesQty")
            or event.get("leaves_qty")
            or event.get("remainingQty")
        )
        try:
            leaves = float(leaves)
        except (TypeError, ValueError):
            leaves = None
        if leaves is not None and leaves <= 0:
            return True
        return False

    def _round_to_step(
        self, value: float, step: float, round_down: bool = True
    ) -> float:
        if step <= 0:
            return value
        step_decimal = Decimal(str(step))
        value_decimal = Decimal(str(value))
        rounding = ROUND_FLOOR if round_down else ROUND_HALF_UP
        return float(
            (value_decimal / step_decimal).to_integral_value(rounding=rounding)
            * step_decimal
        )

    def _round_price_for_order(self, value: float, tick_size: float, side: str) -> float:
        """
        Round price to tick size in a side-aware manner:
          - Buy limits: floor
          - Sell limits: ceil
        """
        if tick_size <= 0:
            return value
        if side.lower() == "buy":
            stepped = math.floor(value / tick_size) * tick_size
        else:
            stepped = math.ceil(value / tick_size) * tick_size
        step_str = f"{tick_size:.10f}".rstrip("0")
        precision = len(step_str.split(".")[1]) if "." in step_str else 0
        return round(stepped, precision)

    def _update_status_fields(
        self, bot: Dict[str, Any], neutral_state: Dict[str, Any]
    ) -> None:
        slots = neutral_state.get("slots") or {}
        entry_open = 0
        exit_open = 0
        long_slots = 0
        short_slots = 0
        for slot in slots.values():
            leg = slot.get("leg")
            if leg == "LONG":
                long_slots += 1
            elif leg == "SHORT":
                short_slots += 1
            if slot.get("order_link_id"):
                if slot.get("state") == "ENTRY":
                    entry_open += 1
                else:
                    exit_open += 1

        bot["neutral_grid_enabled"] = True
        bot["levels_count"] = len(neutral_state.get("levels") or [])
        bot["mid_index"] = neutral_state.get("mid_index")
        bot["entry_orders_open"] = entry_open
        bot["exit_orders_open"] = exit_open
        bot["active_long_slots"] = long_slots
        bot["active_short_slots"] = short_slots

    def _cancel_bot_orders(
        self, bot: Dict[str, Any], symbol: str, client, cancel_all: bool = False
    ) -> None:
        """
        Cancel orders belonging to this bot.
        If cancel_all is True, cancels everything (Entry & Exit).
        If False, cancels only Entry orders.
        """
        bot_id_16 = self._bot_id_16(bot)
        bot_id_full = bot.get("id", "")
        short_id = bot.get("shortId", "")

        orders = self._get_open_orders(client, symbol)
        cancel_count = 0
        max_cancels = 50  # Safety limit per call

        for order in orders:
            if cancel_count >= max_cancels:
                logger.warning(
                    "[%s] 🛡️ Max cancel limit hit in _cancel_bot_orders", symbol
                )
                break

            # SAFETY: Never cancel reduceOnly/exit orders UNLESS we are clearing the slate for a recenter
            # Shifting the grid invalidates old EXIT prices, so we must clear them.
            is_exit = bool(order.get("reduceOnly") or order.get("reduce_only"))
            if is_exit and not cancel_all:
                continue

            link_id = order.get("orderLinkId")
            parsed = self._parse_order_link_id(link_id)

            should_cancel = False

            # 1. Match by v2 link ID
            if parsed and parsed.get("bot_id") == bot_id_16:
                if cancel_all or parsed.get("state") == "E":
                    should_cancel = True

            # 2. Match by legacy link ID
            elif link_id and (short_id in link_id or bot_id_full in link_id):
                should_cancel = True

            if should_cancel:
                try:
                    result = client.cancel_order(
                        symbol=symbol,
                        order_id=order.get("orderId"),
                        order_link_id=link_id,
                    )
                    if not result.get("success"):
                        error_msg = str(result.get("error"))
                        if "10001" in error_msg:
                            logger.warning(
                                "[%s] ⏳ Rate limit hit while cancelling. Backing off 2s...",
                                symbol,
                            )
                            time.sleep(2.0)
                        else:
                            logger.warning(
                                "[%s] Failed to cancel bot order %s: %s",
                                symbol,
                                link_id,
                                error_msg,
                            )
                    else:
                        cancel_count += 1
                except Exception as exc:
                    logger.warning(
                        "[%s] Exception cancelling bot order %s: %s",
                        symbol,
                        link_id,
                        exc,
                    )

    def _cancel_entry_orders(
        self, bot: Dict[str, Any], symbol: str, client, neutral_state: Dict[str, Any]
    ) -> None:
        # Wrapper for backward compatibility
        self._cancel_bot_orders(bot, symbol, client, cancel_all=False)

    def _is_hedge_mode_error(self, ret_code: Optional[int], error_msg: str) -> bool:
        if ret_code in (110029, 110028):
            return True
        return "position idx" in (error_msg or "").lower()

    def _is_reduce_only_no_position_error(
        self, ret_code: Optional[int], error_msg: str
    ) -> bool:
        try:
            ret_code_int = int(ret_code) if ret_code is not None else None
        except (TypeError, ValueError):
            ret_code_int = None
        if ret_code_int != 110017:
            return False
        msg = (error_msg or "").lower()
        return (
            "position is zero" in msg
            or "current position is zero" in msg
            or "position size is zero" in msg
        )

    def _get_position_size(
        self, client, symbol: str, position_idx: int, skip_cache: bool = False
    ) -> float:
        try:
            positions_resp = client.get_positions(skip_cache=skip_cache)
            if not positions_resp.get("success"):
                return 0.0
            positions = positions_resp.get("data", {}).get("list", []) or []
            for pos in positions:
                if pos.get("symbol") != symbol:
                    continue
                if int(pos.get("positionIdx", 0) or 0) != int(position_idx or 0):
                    continue
                try:
                    return float(pos.get("size", 0) or 0)
                except (TypeError, ValueError):
                    return 0.0
        except Exception:
            return 0.0
        return 0.0

    def _prune_distant_orders(
        self, bot: Dict[str, Any], symbol: str, client, count: int = 1
    ) -> int:
        last_price = self._get_last_price(client, symbol, skip_cache=True)
        if not last_price:
            return 0

        all_orders = self._get_open_orders(client, symbol)
        bot_id_16 = self._bot_id_16(bot)

        candidates = []
        for order in all_orders:
            # SAFETY: Never prune reduceOnly orders
            if order.get("reduceOnly") is True or order.get("reduce_only") is True:
                continue

            parsed = self._parse_order_link_id(order.get("orderLinkId"))
            if parsed and parsed.get("bot_id") == bot_id_16:
                try:
                    price = float(order.get("price", 0))
                    dist = abs(price - last_price)
                    candidates.append((dist, order.get("orderId")))
                except (TypeError, ValueError):
                    pass

        # Sort desc by distance (furthest first)
        candidates.sort(key=lambda x: x[0], reverse=True)

        pruned = 0
        for dist, oid in candidates[:count]:
            try:
                res = client.cancel_order(symbol=symbol, order_id=oid)
                # Consider success if API says success (usually cancels are instant)
                if res.get("success"):
                    logger.info(
                        "[%s:%s] ✂ Pruned distant order %s (dist=%.2f) to free margin",
                        symbol,
                        bot_id_16[:6],
                        oid,
                        dist,
                    )
                    pruned += 1
            except Exception as e:
                logger.warning("Failed to prune order %s: %s", oid, e)

        return pruned

    def _calculate_auto_margin_reserve(
        self,
        bot: Dict[str, Any],
        investment: float,
        available_equity: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Calculate unified auto-margin reserve and usable investment.
        Returns: (reserve_usd, usable_investment)
        """
        from config.strategy_config import (
            AUTO_MARGIN_RESERVE_PCT,
            AUTO_MARGIN_RESERVE_USDT,
            AUTO_MARGIN_RESERVE_USE_PCT,
            SMALL_CAPITAL_MODE_ENABLED,
            SMALL_CAPITAL_AUTO_MARGIN_CAPS,
            SMALL_CAPITAL_SYMBOL_PROFILES,
        )

        # 1. Config safety guard
        reserve_pct = AUTO_MARGIN_RESERVE_PCT
        if reserve_pct < 0 or reserve_pct >= 1.0:
            if not getattr(self, "_auto_margin_warned", False):
                logger.warning(
                    f"⚠️ Invalid AUTO_MARGIN_RESERVE_PCT ({reserve_pct}), clamping to [0.0, 0.5]"
                )
                self._auto_margin_warned = True
            reserve_pct = max(0.0, min(0.5, reserve_pct))

        # 2. Calculate reserve_usd
        if AUTO_MARGIN_RESERVE_USE_PCT:
            reserve_usd = investment * reserve_pct
            reserve_usd = min(
                reserve_usd,
                investment * max(0.0, float(OPENING_MARGIN_VIABILITY_RESERVE_PCT or 0.0)),
            )
        else:
            reserve_usd = AUTO_MARGIN_RESERVE_USDT

        reserve_cap_usdt = max(0.0, float(OPENING_MARGIN_VIABILITY_RESERVE_CAP_USDT or 0.0))
        if reserve_cap_usdt > 0:
            reserve_usd = min(reserve_usd, reserve_cap_usdt)

        # 3. Baseline usable investment
        usable_investment = investment - reserve_usd

        # 4. Equity-aware fallback: if account balance is low (less than configured investment), don't over-allocate
        # DISABLED: This causes issues for running bots where equity is already deployed
        # if available_equity is not None and available_equity < investment:
        #     usable_investment = max(0.0, available_equity - reserve_usd)

        # 5. Small-cap caps (if enabled)
        if SMALL_CAPITAL_MODE_ENABLED:
            symbol = bot.get("symbol", "")
            profile = SMALL_CAPITAL_SYMBOL_PROFILES.get(symbol, "MEME")
            cap_usd = SMALL_CAPITAL_AUTO_MARGIN_CAPS.get(profile, 0.0)
            if cap_usd > 0:
                usable_investment = min(usable_investment, cap_usd)

        return reserve_usd, usable_investment
