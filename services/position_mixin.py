"""
Position Management Mixin — Position Close, Order Cancel, Position Cap, Stall Overlay

Extracted from grid_bot_service.py. Handles position closing, order cancellation,
position size cap enforcement, and stall overlay detection/response.

Usage: GridBotService inherits from PositionMixin.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging

import config.strategy_config as strategy_cfg
from services.control_timing_service import iso_from_ts
from config.strategy_config import (
    MAX_POSITION_PCT,
    STALL_OVERLAY_ENABLED,
    STALL_OVERLAY_COOLDOWN_SECONDS,
    STALL_OVERLAY_MAX_DEFENSIVE_UPNL_PCT,
    STALL_OVERLAY_MAX_NO_ACTION_CYCLES,
    STALL_OVERLAY_MIN_STALL_DURATION_SECONDS,
    STALL_OVERLAY_MIN_TRADE_AGE_SECONDS,
    STALL_OVERLAY_PARTIAL_TRIM_CLOSE_PCT,
    STALL_OVERLAY_PARTIAL_TRIM_ENABLED,
    STALL_OVERLAY_REQUIRE_POSITION_CAP,
    STALL_OVERLAY_REQUIRE_TOO_STRONG,
    STALL_OVERLAY_TIGHTEN_PROFIT_LOCK_MULT,
    STALL_OVERLAY_TIGHTEN_QUICK_PROFIT_MULT,
)
from services.control_timing_service import now_ts, elapsed_ms

logger = logging.getLogger(__name__)


class PositionMixin:
    """Mixin providing position management methods for GridBotService."""

    def _close_position_market(
        self, symbol: str, bot: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Close any open position for symbol via reduce-only market order."""
        self._last_close_position_result = None
        conflict = self._get_shared_symbol_conflict(bot, symbol, "symbol-wide close")
        if conflict:
            self._last_close_position_result = conflict
            return False
        try:
            positions_resp = self.client.get_positions(skip_cache=True)
            if not positions_resp.get("success"):
                self._last_close_position_result = positions_resp
                return False

            positions = positions_resp.get("data", {}).get("list", []) or []
            target_positions = [
                p
                for p in positions
                if p.get("symbol") == symbol and float(p.get("size", 0) or 0) > 0
            ]

            if not target_positions:
                self._clear_full_close_attempt_fence(bot=bot, symbol=symbol)
                self._last_close_position_result = {
                    "success": True,
                    "message": "no_position",
                    "retCode": 0,
                }
                return True

            all_success = True
            last_result: Dict[str, Any] = {"success": True, "retCode": 0}
            for pos in target_positions:
                side = pos.get("side")
                size = float(pos.get("size", 0) or 0)

                # Opposite side for closing
                close_side = "Sell" if side.lower() == "buy" else "Buy"
                price = self._safe_float(
                    pos.get("markPrice"), None
                ) or self._safe_float(pos.get("avgPrice"), None)
                # Use resolved positionIdx to respect hedge/one-way mode; fall back to exchange value
                resolved_idx = (
                    self._resolve_position_idx(bot, symbol, close_side, True)
                    if bot
                    else None
                )
                position_idx = (
                    resolved_idx
                    if resolved_idx is not None
                    else int(pos.get("positionIdx", 0) or 0)
                )
                close_order_link_id = self._get_full_close_attempt_order_link_id(
                    bot=bot,
                    symbol=symbol,
                    close_side=close_side,
                    position_idx=position_idx,
                    close_reason="CLOS",
                )

                # Retry loop for closing position (Exit-path resilience)
                max_retries = 3
                retry_delay = 1.0
                closed_this_pos = False

                for attempt in range(max_retries):
                    result = self._create_order_checked(
                        bot=bot,
                        symbol=symbol,
                        side=close_side,
                        qty=size,
                        order_type="Market",
                        price=price,
                        reduce_only=True,
                        time_in_force="GTC",
                        order_link_id=close_order_link_id,
                        position_idx=position_idx,
                    )
                    last_result = result

                    if result.get("success"):
                        logger.info(
                            f"[{symbol}] Closed {side} position of {size} @ market (attempt {attempt + 1})"
                        )
                        closed_this_pos = True
                        break
                    if self._is_position_empty_close_result(result):
                        logger.info(
                            "[%s] Close skipped on attempt %d/%d: position already flat",
                            symbol,
                            attempt + 1,
                            max_retries,
                        )
                        self._clear_full_close_attempt_fence(
                            bot=bot,
                            symbol=symbol,
                            close_side=close_side,
                            position_idx=position_idx,
                        )
                        closed_this_pos = True
                        break
                    if self._is_ambiguous_order_result(result):
                        logger.warning(
                            "CLOSE_RETRY_NOT_SAFE symbol=%s bot_id=%s order_link_id=%s status=%s retry_safe=%s",
                            symbol,
                            (bot or {}).get("id") or "manual",
                            close_order_link_id,
                            result.get("status"),
                            result.get("retry_safe"),
                        )
                        all_success = False
                        break
                    else:
                        error_msg = result.get("error")
                        is_rate_limit = "10006" in str(error_msg)

                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2**attempt)
                            if is_rate_limit:
                                wait_time = max(wait_time, 2.0)
                            logger.warning(
                                f"[{symbol}] Failed to close position (attempt {attempt + 1}/{max_retries}): {error_msg}. Retrying in {wait_time:.1f}s..."
                            )
                            time.sleep(wait_time)
                        else:
                            logger.error(
                                f"[{symbol}] Final failure closing position after {max_retries} attempts: {error_msg}"
                            )

                if not closed_this_pos:
                    all_success = False

            self._last_close_position_result = last_result
            return all_success
        except Exception as e:
            logger.error(f"[{symbol}] Exception closing position: {e}")
            self._last_close_position_result = {
                "success": False,
                "error": str(e),
                "retCode": -1,
            }
            return False

    def _record_position_cap_transition_event(
        self,
        bot: Optional[Dict[str, Any]],
        *,
        event_type: str,
        symbol: str,
        mode: Optional[str],
        current_notional: float,
        cap_notional: float,
        side: Optional[str] = None,
    ) -> None:
        if not isinstance(bot, dict):
            return
        severity = "WARN" if event_type == "position_cap_suppression_started" else "INFO"
        self._emit_audit_event(
            bot,
            event_type=event_type,
            severity=severity,
            symbol=symbol,
            mode=mode,
            throttle_key=f"{event_type}:{bot.get('id')}:{side or 'na'}",
            throttle_sec=60 if event_type == "position_cap_suppression_started" else 15,
            side=side,
            current_notional=round(self._safe_float(current_notional, 0.0), 4),
            cap_notional=round(self._safe_float(cap_notional, 0.0), 4),
        )

    def _get_effective_max_position_cap_pct(
        self,
        bot: Dict[str, Any],
        *,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        position_side: Optional[str] = None,
        position_size: Optional[float] = None,
        position_unrealized_pnl: Optional[float] = None,
        continuation_add_candidate_active: bool = False,
        capital_starved_opening_reason: Optional[str] = None,
    ) -> float:
        if symbol:
            ai_cap_pct = self._get_ai_max_position_cap_pct(bot, symbol)
            if ai_cap_pct is not None:
                return ai_cap_pct / 100.0

        base_cap_pct = strategy_cfg.get_mode_max_position_pct(mode or bot.get("mode"))
        effective_cap_pct = base_cap_pct

        if self._should_use_experimental_directional_position_cap(
            bot,
            mode=mode,
        ):
            bonus_pct = max(
                0.0,
                self._safe_float(
                    getattr(
                        strategy_cfg,
                        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_BONUS_PCT",
                        0.02,
                    ),
                    0.02,
                ),
            )
            hard_ceiling_pct = max(
                base_cap_pct,
                self._safe_float(
                    getattr(
                        strategy_cfg,
                        "EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_HARD_CEILING_PCT",
                        base_cap_pct,
                    ),
                    base_cap_pct,
                ),
            )
            effective_cap_pct = max(
                effective_cap_pct,
                min(base_cap_pct + bonus_pct, hard_ceiling_pct),
            )
            if effective_cap_pct > base_cap_pct + 1e-9:
                self._remember_runtime_experiment_usage(
                    bot,
                    ["exp_directional_position_cap_headroom_used"],
                    details={
                        "exp_directional_position_cap_headroom_used": {
                            "base_cap_pct": round(base_cap_pct, 6),
                            "effective_cap_pct": round(effective_cap_pct, 6),
                            "bonus_pct": round(bonus_pct, 6),
                            "hard_ceiling_pct": round(hard_ceiling_pct, 6),
                        }
                    },
                )

        if self._should_use_profitable_continuation_add_cap_headroom(
            bot,
            mode=mode,
            position_side=position_side,
            position_size=position_size,
            position_unrealized_pnl=position_unrealized_pnl,
            continuation_add_candidate_active=continuation_add_candidate_active,
            capital_starved_opening_reason=capital_starved_opening_reason,
        ):
            bonus_pct = max(
                0.0,
                self._safe_float(
                    getattr(
                        strategy_cfg,
                        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_BONUS_PCT",
                        0.02,
                    ),
                    0.02,
                ),
            )
            hard_ceiling_pct = max(
                base_cap_pct,
                self._safe_float(
                    getattr(
                        strategy_cfg,
                        "EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_HARD_CEILING_PCT",
                        base_cap_pct,
                    ),
                    base_cap_pct,
                ),
            )
            effective_cap_pct = max(
                effective_cap_pct,
                min(base_cap_pct + bonus_pct, hard_ceiling_pct),
            )
            if effective_cap_pct > base_cap_pct + 1e-9:
                self._remember_runtime_experiment_usage(
                    bot,
                    ["exp_profitable_add_cap_headroom_used"],
                    details={
                        "exp_profitable_add_cap_headroom_used": {
                            "base_cap_pct": round(base_cap_pct, 6),
                            "effective_cap_pct": round(effective_cap_pct, 6),
                            "bonus_pct": round(bonus_pct, 6),
                            "hard_ceiling_pct": round(hard_ceiling_pct, 6),
                        }
                    },
                )

        return effective_cap_pct

    def _cancel_opening_orders_only(self, bot: Dict[str, Any], symbol: str) -> int:
        """
        Cancel only opening (margin-reserving) orders. Preserve reduceOnly orders.
        """
        return self._cancel_non_reducing_bot_orders(bot, symbol)

    def _get_stall_overlay_settings(
        self,
        bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        safe_bot = bot or {}
        partial_trim_close_pct = self._safe_float(
            safe_bot.get("stall_overlay_partial_trim_close_pct"),
            STALL_OVERLAY_PARTIAL_TRIM_CLOSE_PCT,
        )
        partial_trim_close_pct = max(0.0, min(0.5, partial_trim_close_pct))
        defensive_upnl_pct = min(
            0.0,
            self._safe_float(
                safe_bot.get("stall_overlay_max_defensive_upnl_pct"),
                STALL_OVERLAY_MAX_DEFENSIVE_UPNL_PCT,
            ),
        )
        return {
            "enabled": bool(
                safe_bot.get("stall_overlay_enabled", STALL_OVERLAY_ENABLED)
            ),
            "min_trade_age_seconds": max(
                60.0,
                self._safe_float(
                    safe_bot.get("stall_overlay_min_trade_age_seconds"),
                    STALL_OVERLAY_MIN_TRADE_AGE_SECONDS,
                ),
            ),
            "min_stall_duration_seconds": max(
                60.0,
                self._safe_float(
                    safe_bot.get("stall_overlay_min_stall_duration_seconds"),
                    STALL_OVERLAY_MIN_STALL_DURATION_SECONDS,
                ),
            ),
            "require_position_cap": bool(
                safe_bot.get(
                    "stall_overlay_require_position_cap",
                    STALL_OVERLAY_REQUIRE_POSITION_CAP,
                )
            ),
            "require_too_strong": bool(
                safe_bot.get(
                    "stall_overlay_require_too_strong",
                    STALL_OVERLAY_REQUIRE_TOO_STRONG,
                )
            ),
            "max_no_action_cycles": max(
                1,
                int(
                    self._safe_float(
                        safe_bot.get("stall_overlay_max_no_action_cycles"),
                        STALL_OVERLAY_MAX_NO_ACTION_CYCLES,
                    )
                ),
            ),
            "tighten_profit_lock_mult": max(
                0.5,
                min(
                    1.0,
                    self._safe_float(
                        safe_bot.get("stall_overlay_tighten_profit_lock_mult"),
                        STALL_OVERLAY_TIGHTEN_PROFIT_LOCK_MULT,
                    ),
                ),
            ),
            "tighten_quick_profit_mult": max(
                0.5,
                min(
                    1.0,
                    self._safe_float(
                        safe_bot.get("stall_overlay_tighten_quick_profit_mult"),
                        STALL_OVERLAY_TIGHTEN_QUICK_PROFIT_MULT,
                    ),
                ),
            ),
            "partial_trim_enabled": bool(
                safe_bot.get(
                    "stall_overlay_partial_trim_enabled",
                    STALL_OVERLAY_PARTIAL_TRIM_ENABLED,
                )
            ),
            "partial_trim_close_pct": partial_trim_close_pct,
            "max_defensive_upnl_pct": defensive_upnl_pct,
            "cooldown_seconds": max(
                60.0,
                self._safe_float(
                    safe_bot.get("stall_overlay_cooldown_seconds"),
                    STALL_OVERLAY_COOLDOWN_SECONDS,
                ),
            ),
        }

    @staticmethod
    def _clear_stall_overlay_state(bot: Dict[str, Any]) -> None:
        if not bot:
            return
        bot.pop("_stall_overlay_state", None)
        bot["_stall_overlay_block_opening_orders"] = False
        bot["_stall_overlay_quick_profit_mult"] = 1.0
        bot["_stall_overlay_profit_lock_mult"] = 1.0
        bot["stall_overlay_stage"] = 0
        bot["stall_overlay_status"] = "inactive"
        bot["stall_overlay_reason"] = None
        bot["stall_overlay_duration_sec"] = 0.0
        bot["stall_overlay_trade_age_sec"] = 0.0
        bot["stall_overlay_no_action_cycles"] = 0
        bot["stall_overlay_worsening_cycles"] = 0
        bot["stall_overlay_block_openings"] = False
        bot["stall_overlay_last_trim_close_pct"] = bot.get(
            "stall_overlay_last_trim_close_pct"
        )

    def _handle_stall_overlay(
        self,
        bot: Dict[str, Any],
        symbol: str,
        position: Dict[str, Any],
        *,
        mode: str,
        last_price: float,
        profit_pct: float,
        partial_tp_ready: bool,
        profit_lock_ready: bool,
        heartbeat_action: str,
    ) -> None:
        settings = self._get_stall_overlay_settings(bot)
        if not settings["enabled"] or mode not in {"long", "short", "neutral"}:
            self._clear_stall_overlay_state(bot)
            return

        pos_size = max(self._safe_float(position.get("size"), 0.0), 0.0)
        pos_side = str(position.get("side") or "").strip()
        if pos_size <= 0 or not pos_side:
            self._clear_stall_overlay_state(bot)
            return

        timing = self._track_position_timing(bot, symbol, position)
        age_sec = timing["age_sec"]
        unrealized_pnl = self._safe_float(position.get("unrealisedPnl"), 0.0)
        too_strong = str(
            bot.get("entry_filter_regime") or bot.get("regime_effective") or ""
        ).strip().lower() in {"too_strong", "extreme_trend"}
        position_cap_hit = bool(bot.get("stall_overlay_position_cap_hit"))
        no_action = (
            heartbeat_action == "no_action"
            and not partial_tp_ready
            and not profit_lock_ready
        )
        previous_orders_placed = int(self._safe_float(bot.get("orders_placed"), 0.0))
        previous_orders_failed = int(self._safe_float(bot.get("orders_failed"), 0.0))
        adverse = profit_pct <= 0.0 and unrealized_pnl <= 0.0

        # Guard: skip stall overlay for the first few cycles to prevent
        # cold-start lockout where a fresh bot's first losing trade blocks all opens.
        cycle_count = int(bot.get("_cycle_count") or 0)
        bot["_cycle_count"] = cycle_count + 1

        requirements_met = (
            cycle_count >= 3  # Don't trigger on first 3 cycles
            and age_sec >= settings["min_trade_age_seconds"]
            and adverse
            and no_action
            and previous_orders_placed <= 0
            and previous_orders_failed <= 0
            and (
                not settings["require_position_cap"]
                or position_cap_hit
            )
            and (
                not settings["require_too_strong"]
                or too_strong
            )
        )

        existing_state = bot.get("_stall_overlay_state") or {}
        previous_stage = int(self._safe_float(existing_state.get("stage"), 0.0))
        if not requirements_met:
            if previous_stage > 0:
                logger.info("[%s] STALL_OVERLAY cleared", symbol)
            self._clear_stall_overlay_state(bot)
            return

        now_ts = self._get_cycle_now_ts()
        position_idx = int(self._safe_float(position.get("positionIdx"), 0.0))
        position_key = f"{symbol}:{pos_side}:{position_idx}"
        state = existing_state if existing_state.get("position_key") == position_key else {}
        active_since_ts = self._safe_float(state.get("active_since_ts"), 0.0) or now_ts
        no_action_cycles = int(self._safe_float(state.get("no_action_cycles"), 0.0)) + 1
        worsening_cycles = int(self._safe_float(state.get("worsening_cycles"), 0.0))
        last_profit_pct = state.get("last_profit_pct")
        last_unrealized_pnl = state.get("last_unrealized_pnl")
        worsening = False
        if last_profit_pct is not None and profit_pct < self._safe_float(last_profit_pct) - 0.0005:
            worsening = True
        if last_unrealized_pnl is not None:
            pnl_step = max(0.05, abs(self._safe_float(last_unrealized_pnl)) * 0.05)
            if unrealized_pnl < self._safe_float(last_unrealized_pnl) - pnl_step:
                worsening = True
        if worsening:
            worsening_cycles += 1

        stall_duration = max(0.0, now_ts - active_since_ts)
        stage = 0
        if (
            stall_duration >= settings["min_stall_duration_seconds"]
            and no_action_cycles >= settings["max_no_action_cycles"]
        ):
            stage = 1

        stage2_loss_threshold = min(0.0, settings["max_defensive_upnl_pct"] * 0.5)
        if stage >= 1 and worsening_cycles >= 2 and profit_pct <= stage2_loss_threshold:
            stage = 2

        if (
            stage >= 2
            and stall_duration >= (settings["min_stall_duration_seconds"] * 2.0)
            and worsening_cycles >= 3
            and profit_pct <= settings["max_defensive_upnl_pct"]
        ):
            stage = 3

        reason_parts: List[str] = []
        if too_strong:
            reason_parts.append("too_strong")
        if position_cap_hit:
            reason_parts.append("position_cap")
        if no_action:
            reason_parts.append("no_action")
        if previous_orders_placed <= 0 and previous_orders_failed <= 0:
            reason_parts.append("no_new_orders")
        if worsening_cycles > 0:
            reason_parts.append("worsening_upnl")
        reason_text = " + ".join(reason_parts) or "stalled_position"

        bot["_stall_overlay_block_opening_orders"] = stage >= 1
        bot["_stall_overlay_quick_profit_mult"] = (
            settings["tighten_quick_profit_mult"] if stage >= 1 else 1.0
        )
        bot["_stall_overlay_profit_lock_mult"] = (
            settings["tighten_profit_lock_mult"] if stage >= 1 else 1.0
        )
        bot["stall_overlay_stage"] = stage
        bot["stall_overlay_status"] = {
            0: "inactive",
            1: "warning",
            2: "defensive",
            3: "escalated",
        }.get(stage, "inactive")
        bot["stall_overlay_reason"] = reason_text if stage >= 1 else None
        bot["stall_overlay_duration_sec"] = round(stall_duration, 1)
        bot["stall_overlay_trade_age_sec"] = round(age_sec, 1)
        bot["stall_overlay_no_action_cycles"] = no_action_cycles
        bot["stall_overlay_worsening_cycles"] = worsening_cycles
        bot["stall_overlay_block_openings"] = bool(stage >= 1)

        if stage > previous_stage:
            logger.warning(
                "[%s] STALL_OVERLAY triggered: stage=%s reason=%s trade_age=%.0fs stall=%.0fs "
                "upnl_pct=%.4f no_action_cycles=%s worsening_cycles=%s",
                symbol,
                stage,
                reason_text,
                age_sec,
                stall_duration,
                profit_pct,
                no_action_cycles,
                worsening_cycles,
            )

        state.update(
            {
                "position_key": position_key,
                "active_since_ts": active_since_ts,
                "last_seen_ts": now_ts,
                "no_action_cycles": no_action_cycles,
                "worsening_cycles": worsening_cycles,
                "stage": stage,
                "last_profit_pct": profit_pct,
                "last_unrealized_pnl": unrealized_pnl,
            }
        )

        if stage >= 1:
            bot["last_warning"] = (
                f"STALL_OVERLAY stage {stage}: {reason_text}"
            )

        if stage >= 2 and settings["partial_trim_enabled"]:
            last_trim_ts = self._safe_float(state.get("last_trim_ts"), 0.0)
            last_trim_stage = int(self._safe_float(state.get("last_trim_stage"), 0.0))
            if (
                stage > last_trim_stage
                and (now_ts - last_trim_ts) >= settings["cooldown_seconds"]
            ):
                close_pct = settings["partial_trim_close_pct"]
                if stage >= 3:
                    close_pct = min(0.5, max(close_pct, close_pct * 2.0))
                close_qty = pos_size * close_pct
                close_side = "Sell" if pos_side == "Buy" else "Buy"
                trim_result = self._create_order_checked(
                    bot=bot,
                    symbol=symbol,
                    side=close_side,
                    qty=close_qty,
                    order_type="Market",
                    price=last_price,
                    reduce_only=True,
                    time_in_force="GTC",
                    order_link_id=self._build_close_order_link_id(
                        bot.get("id"),
                        f"STL{stage}",
                    ),
                    position_idx=position_idx,
                    full_close_qty=pos_size,
                )
                if self._is_position_empty_close_result(trim_result):
                    logger.info(
                        "[%s] STALL_OVERLAY trim skipped: position already flat",
                        symbol,
                    )
                elif trim_result.get("retCode") == 0 or trim_result.get("success"):
                    state["last_trim_ts"] = now_ts
                    state["last_trim_stage"] = stage
                    bot["stall_overlay_last_trim_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    bot["stall_overlay_last_trim_close_pct"] = round(close_pct, 4)
                    logger.warning(
                        "[%s] STALL_OVERLAY defensive trim executed: stage=%s close_pct=%.2f upnl_pct=%.4f",
                        symbol,
                        stage,
                        close_pct,
                        profit_pct,
                    )
                elif trim_result.get("skipped"):
                    state["last_trim_ts"] = now_ts
                    logger.info(
                        "[%s] STALL_OVERLAY defensive trim skipped: stage=%s reason=%s",
                        symbol,
                        stage,
                        trim_result.get("skip_reason") or trim_result.get("error"),
                    )
                else:
                    logger.warning(
                        "[%s] STALL_OVERLAY defensive trim failed: stage=%s error=%s",
                        symbol,
                        stage,
                        trim_result.get("error", trim_result),
                    )

        bot["_stall_overlay_state"] = state

    def _force_cancel_all_orders(
        self,
        symbol: str,
        max_retries: int = 3,
        bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Forcefully cancel all orders for a symbol with verification retries.
        """
        import time

        conflict = self._get_shared_symbol_conflict(
            bot,
            symbol,
            "symbol-wide order cancel",
        )
        if conflict:
            return conflict

        overall_started_at = now_ts()
        cancelled_count = 0
        remaining_orders: List[Dict[str, Any]] = []
        first_cancel_timing = None

        for attempt in range(max_retries):
            cancel_result = self.client.cancel_all_orders(symbol)
            if first_cancel_timing is None:
                first_cancel_timing = dict((cancel_result or {}).get("timing") or {})
            ambiguous_cancel = self._is_ambiguous_order_result(cancel_result)
            if not cancel_result.get("success"):
                logger.warning(
                    f"[{symbol}] Cancel attempt {attempt + 1} failed: {cancel_result.get('error')}"
                )

            time.sleep(0.3)

            orders_result = self.client.get_open_orders(symbol=symbol)
            if orders_result.get("success"):
                orders = orders_result.get("data", {})
                if isinstance(orders, dict):
                    orders = orders.get("list", [])
                orders = orders or []

                if not orders:
                    logger.info(
                        f"[{symbol}] ✓ All orders cancelled (attempt {attempt + 1})"
                    )
                    result = {
                        "success": True,
                        "cancelled": cancelled_count,
                        "remaining": 0,
                        "attempts": attempt + 1,
                        "timing": {
                            **(first_cancel_timing or {}),
                            "cancel_total_ms": elapsed_ms(
                                overall_started_at,
                                now_ts(),
                            ),
                            "cancel_verification_completed_at": iso_from_ts(),
                        },
                    }
                    self._record_control_timing(
                        bot,
                        "last_order_cancel",
                        symbol=symbol,
                        timing=dict(result.get("timing") or {}),
                    )
                    return result

                remaining_orders = orders
                logger.warning(
                    f"[{symbol}] Still {len(orders)} orders open after cancel attempt {attempt + 1}"
                )
                if ambiguous_cancel:
                    logger.warning(
                        "CANCEL_RETRY_NOT_SAFE symbol=%s status=%s retry_safe=%s remaining=%s",
                        symbol,
                        cancel_result.get("status"),
                        cancel_result.get("retry_safe"),
                        len(orders),
                    )
                    result = {
                        "success": None,
                        "status": cancel_result.get("status") or "unknown_outcome",
                        "error": cancel_result.get("error")
                        or "cancel_all_orders_ambiguous",
                        "retCode": cancel_result.get("retCode", -2),
                        "retry_safe": False,
                        "diagnostic_reason": "cancel_all_orders_ambiguous",
                        "cancelled": cancelled_count,
                        "remaining": len(orders),
                        "remaining_orders": orders,
                        "attempts": attempt + 1,
                        "timing": {
                            **(first_cancel_timing or {}),
                            "cancel_total_ms": elapsed_ms(overall_started_at, now_ts()),
                            "cancel_verification_completed_at": iso_from_ts(),
                        },
                    }
                    self._mark_ambiguous_execution_follow_up(
                        bot,
                        action="cancel_all_orders",
                        symbol=symbol,
                        result=result,
                    )
                    self._record_control_timing(
                        bot,
                        "last_order_cancel",
                        symbol=symbol,
                        timing=dict(result.get("timing") or {}),
                    )
                    return result

                for order in orders:
                    order_id = order.get("orderId")
                    if order_id:
                        try:
                            self.client.cancel_order(symbol=symbol, order_id=order_id)
                            cancelled_count += 1
                        except Exception as exc:
                            logger.warning(
                                f"[{symbol}] Failed to cancel order {order_id}: {exc}"
                            )

                time.sleep(0.3)
            else:
                logger.warning(
                    f"[{symbol}] Failed to verify orders: {orders_result.get('error')}"
                )
                if ambiguous_cancel:
                    logger.warning(
                        "CANCEL_RETRY_NOT_SAFE symbol=%s status=%s retry_safe=%s verification=failed",
                        symbol,
                        cancel_result.get("status"),
                        cancel_result.get("retry_safe"),
                    )
                    result = {
                        "success": None,
                        "status": cancel_result.get("status") or "unknown_outcome",
                        "error": cancel_result.get("error")
                        or orders_result.get("error")
                        or "cancel_all_orders_ambiguous",
                        "retCode": cancel_result.get("retCode", -2),
                        "retry_safe": False,
                        "diagnostic_reason": "cancel_all_orders_ambiguous",
                        "cancelled": cancelled_count,
                        "remaining": None,
                        "attempts": attempt + 1,
                        "timing": {
                            **(first_cancel_timing or {}),
                            "cancel_total_ms": elapsed_ms(overall_started_at, now_ts()),
                            "cancel_verification_completed_at": iso_from_ts(),
                        },
                    }
                    self._mark_ambiguous_execution_follow_up(
                        bot,
                        action="cancel_all_orders",
                        symbol=symbol,
                        result=result,
                    )
                    self._record_control_timing(
                        bot,
                        "last_order_cancel",
                        symbol=symbol,
                        timing=dict(result.get("timing") or {}),
                    )
                    return result

        final_check = self.client.get_open_orders(symbol=symbol)
        final_orders = []
        if final_check.get("success"):
            data = final_check.get("data", {})
            if isinstance(data, dict):
                final_orders = data.get("list", []) or []
            elif isinstance(data, list):
                final_orders = data

        if final_orders:
            logger.error(
                f"[{symbol}] ⚠️ FAILED to cancel all orders after {max_retries} attempts! {len(final_orders)} remaining"
            )
            result = {
                "success": False,
                "cancelled": cancelled_count,
                "remaining": len(final_orders),
                "remaining_orders": final_orders,
                "attempts": max_retries,
                "timing": {
                    **(first_cancel_timing or {}),
                    "cancel_total_ms": elapsed_ms(overall_started_at, now_ts()),
                    "cancel_verification_completed_at": iso_from_ts(),
                },
            }
            self._record_control_timing(
                bot,
                "last_order_cancel",
                symbol=symbol,
                timing=dict(result.get("timing") or {}),
            )
            return result

        result = {
            "success": True,
            "cancelled": cancelled_count,
            "remaining": 0,
            "attempts": max_retries,
            "timing": {
                **(first_cancel_timing or {}),
                "cancel_total_ms": elapsed_ms(overall_started_at, now_ts()),
                "cancel_verification_completed_at": iso_from_ts(),
            },
        }
        self._record_control_timing(
            bot,
            "last_order_cancel",
            symbol=symbol,
            timing=dict(result.get("timing") or {}),
        )
        return result

