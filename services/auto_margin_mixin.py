"""
Auto-Margin Mixin — Position Margin Protection

Extracted from grid_bot_service.py. Handles automatic margin addition
to prevent liquidation, reserve calculation, and emergency close logic.

Usage: GridBotService inherits from AutoMarginMixin.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
import logging

import config.strategy_config as strategy_cfg
from config.strategy_config import (
    AUTO_MARGIN_RESERVE_USDT,
    AUTO_MARGIN_RESERVE_PCT,
    AUTO_MARGIN_RESERVE_USE_PCT,
    CRITICAL_LIQ_PCT,
    CRITICAL_LIQ_RECOVERY_TARGET_PCT,
    EMERGENCY_PARTIAL_CLOSE_PCT,
    EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT,
    EMERGENCY_PARTIAL_CLOSE_TIER2_PCT,
    SMALL_CAPITAL_MODE_ENABLED,
    SMALL_CAPITAL_SYMBOL_PROFILES,
    SMALL_CAPITAL_AUTO_MARGIN_CAPS,
    SMALL_CAPITAL_INVEST_USDT_THRESHOLD,
)

logger = logging.getLogger(__name__)


class AutoMarginMixin:
    """Mixin providing all auto-margin methods for GridBotService."""

    def _persist_auto_margin_state(
        self,
        bot: Dict[str, Any],
        state: Dict[str, Any],
        symbol: str,
    ) -> bool:
        bot["auto_margin_state"] = state
        try:
            self._save_runtime_bot(bot)
            return True
        except Exception as exc:
            logger.warning(
                "[%s] Failed to persist auto-margin state for bot %s: %s",
                symbol,
                bot.get("id"),
                exc,
            )
            return False

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
            SMALL_CAPITAL_MODE_ENABLED,
            SMALL_CAPITAL_AUTO_MARGIN_CAPS,
            SMALL_CAPITAL_SYMBOL_PROFILES,
        )

        effective_investment = self._get_effective_investment(bot, investment)

        reserve_usd = 0.0
        usable_investment = effective_investment

        auto_margin_cfg = bot.get("auto_margin") or {}
        auto_margin_state = bot.get("auto_margin_state") or {}
        # Only reserve margin for auto-margin when there's an active position
        # that might need it.  If auto_margin_state is empty (no position),
        # don't consume margin that's needed for opening grid orders.
        auto_margin_has_state = bool(auto_margin_state.get("last_add_ts") or auto_margin_state.get("total_added_usdt"))
        if bool(auto_margin_cfg.get("enabled", False)) and auto_margin_has_state:
            configured_reserve_usd = 0.0
            if AUTO_MARGIN_RESERVE_USE_PCT:
                configured_reserve_usd = max(
                    0.0,
                    effective_investment * self._safe_float(AUTO_MARGIN_RESERVE_PCT, 0.0),
                )
            else:
                configured_reserve_usd = max(
                    0.0, self._safe_float(AUTO_MARGIN_RESERVE_USDT, 0.0)
                )

            reserve_usd = min(
                configured_reserve_usd,
                self._get_opening_viability_reserve_usd(
                    effective_investment=effective_investment,
                    available_equity=available_equity,
                ),
            )

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

    def _calculate_needed_margin(
        self,
        current_mark_price: float,
        current_liq_price: float,
        target_distance_pct: float,
        position_size: float,
        position_side: str,
        current_margin: float,
        mmr: float = 0.005,
    ) -> float:
        """
        Calculate the exact USDT margin needed to move liquidation price to target distance.
        Formula based on Isolated Margin liq price derivation.
        """
        if position_size <= 0 or current_mark_price <= 0:
            return 0.0

        # Target Liq Price
        if position_side == "Buy":
            # Liq = Mark * (1 - TargetDist)
            target_liq = current_mark_price * (1 - (target_distance_pct / 100.0))
            # Current Liq formula (approx): Liq = Entry - Margin/Size + Entry*MMR
            # To move Liq to target_liq:
            # target_liq = Entry - (current_margin + needed)/Size + Entry*MMR
            # needed = Size * (Entry * (1 + MMR) - target_liq) - current_margin

            # Since we don't always have the exact 'Entry' price that the exchange uses for this specific
            # margin sub-calc (it's internal), we use the distance delta.
            # Delta_Liq = Delta_Margin / Size
            # needed = Size * (current_liq_price - target_liq)
            needed = position_size * (current_liq_price - target_liq)
        else:
            # Short: Liq = Mark * (1 + TargetDist)
            target_liq = current_mark_price * (1 + (target_distance_pct / 100.0))
            # needed = Size * (target_liq - current_liq_price)
            needed = position_size * (target_liq - current_liq_price)

        return max(0.0, needed)

    def _auto_margin_guard(
        self,
        bot: Dict[str, Any],
        symbol: str,
        positions_resp: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Smart, continuous auto-margin: when pct_to_liq <= threshold, add a small amount of margin
        (bounded) to push liquidation further away.

        Configuration (per-bot):
            bot["auto_margin"] = {
                "enabled": bool,
                "min_trigger_pct": 4.0,
                "target_liq_pct": 8.0,
                "cooldown_sec": 20,
                "max_add_ratio": 0.25,
                "min_add_usdt": 1.0,
                "max_add_usdt": 50.0,
                "max_total_add_usdt": 0.0,   # 0 = no cap
                "position_idx": 0,
                "critical_pct": 5.0
            }

        State (persisted):
            bot["auto_margin_state"] = { "last_add_ts": ..., "total_added_usdt": ... }
        """
        cfg = bot.get("auto_margin") or {}
        if not bool(cfg.get("enabled", False)):
            return

        # Auto-margin only protects open positions. If no position exists,
        # reset the state so the margin reserve doesn't consume balance
        # that should be available for new grid orders.
        try:
            if positions_resp is None:
                positions_resp = self.client.get_positions(skip_cache=True)
            has_position = False
            if positions_resp.get("success"):
                for pos in positions_resp.get("data", {}).get("list", []) or []:
                    if pos.get("symbol") == symbol and float(pos.get("size") or 0) > 0:
                        has_position = True
                        break
            if not has_position:
                # No position — clear auto-margin state so margin is freed
                if bot.get("auto_margin_state"):
                    logger.info("[%s] Auto-margin: no position — resetting state", symbol)
                    bot["auto_margin_state"] = {}
                # Clear stale margin-skip flags from a previous cycle's
                # emergency margin preservation so new orders aren't blocked
                # when there's no position left to protect.
                bot.pop("_skip_new_orders_for_margin", None)
                bot.pop("_skip_opening_orders_for_margin", None)
                if bot.get("last_warning") == "Preserving margin for auto-margin":
                    bot["last_warning"] = None
                return
        except Exception:
            pass

        try:
            # Default trigger at 15% to liq (user requested)
            min_trigger_pct = float(cfg.get("min_trigger_pct", 15.0))
            target_liq_pct = float(cfg.get("target_liq_pct", 20.0))
            critical_recovery_target_pct = float(
                cfg.get(
                    "critical_recovery_target_pct",
                    CRITICAL_LIQ_RECOVERY_TARGET_PCT,
                )
            )
            cooldown_sec = int(cfg.get("cooldown_sec", 20))
            max_add_ratio = float(cfg.get("max_add_ratio", 0.25))
            min_add_usdt = float(cfg.get("min_add_usdt", 1.0))
            max_add_usdt = float(cfg.get("max_add_usdt", 50.0))
            max_total_add_usdt = float(cfg.get("max_total_add_usdt", 0.0) or 0.0)
            position_idx = int(cfg.get("position_idx", 0) or 0)
            # Critical threshold - skip cooldown when below this
            critical_pct = float(cfg.get("critical_pct", 5.0))

            # leverage awareness: Cap trigger for high leverage, but don't over-tighten
            leverage = self._safe_float(bot.get("leverage"), 0)
            if leverage > 0:
                max_natural_distance = 100.0 / leverage
                cap_trigger = max(1.0, max_natural_distance - 0.5)

                if min_trigger_pct > cap_trigger:
                    min_trigger_pct = cap_trigger
                    if target_liq_pct <= min_trigger_pct + 2.0:
                        target_liq_pct = min_trigger_pct + 5.0

        except (TypeError, ValueError):
            # Invalid config - fail safe
            return

        # Enforce a single liquidation safety floor. When the distance drops
        # below this line, recover only back to that minimum and keep the rest
        # of the free balance available for orders.
        min_trigger_pct = critical_recovery_target_pct
        target_liq_pct = critical_recovery_target_pct

        small_capital_active = (
            SMALL_CAPITAL_MODE_ENABLED
            and self._safe_float(bot.get("investment"), 0.0)
            <= SMALL_CAPITAL_INVEST_USDT_THRESHOLD
        )
        if small_capital_active:
            profile = (
                bot.get("small_capital_profile")
                or ("ETH" if symbol == "ETHUSDT" else "MEME")
            ).upper()
            allow_small_cap_auto_margin = bool(
                bot.get("small_capital_allow_auto_margin", False)
            )
            cap_override = SMALL_CAPITAL_AUTO_MARGIN_CAPS.get(profile)
            if cap_override is not None:
                if not (profile == "MEME" and allow_small_cap_auto_margin):
                    max_total_add_usdt = float(cap_override)

        critical_recovery_target_pct = max(
            float(critical_recovery_target_pct or 0.0),
            CRITICAL_LIQ_RECOVERY_TARGET_PCT,
        )

        state = bot.get("auto_margin_state") or {}
        now_ts = self.client._get_now_ts()
        last_ts = float(state.get("last_add_ts", 0) or 0)
        total_added = float(state.get("total_added_usdt", 0) or 0)

        remaining_cap = None
        if max_total_add_usdt > 0:
            remaining_cap = max_total_add_usdt - total_added
        bot["auto_margin_remaining_cap"] = (
            round(remaining_cap, 4) if remaining_cap is not None else None
        )

        if (
            small_capital_active
            and profile == "MEME"
            and not allow_small_cap_auto_margin
        ):
            bot["auto_margin_remaining_cap"] = 0.0
            logger.info(f"[{symbol}] AutoMargin: disabled for small-cap MEME")
            bot["auto_margin_state"] = state
            return

        if small_capital_active and profile == "ETH":
            min_interval_sec = 3600
            if last_ts and (now_ts - last_ts) < min_interval_sec:
                logger.info(
                    f"[{symbol}] AutoMargin: rate-limited (last_add={int(now_ts - last_ts)}s ago)"
                )
                bot["auto_margin_state"] = state
                return

        if max_total_add_usdt > 0 and remaining_cap is not None and remaining_cap <= 0:
            logger.info(
                f"[{symbol}] AutoMargin: cap reached (remaining=${remaining_cap:.2f})"
            )
            bot["auto_margin_state"] = state
            return

        if bot.get("_upnl_stoploss_reason") or bot.get("upnl_stoploss_cooldown_until"):
            logger.info(
                f"[{symbol}] AutoMargin: skip (stoploss active, remaining=${remaining_cap if remaining_cap is not None else 'n/a'})"
            )
            bot["auto_margin_state"] = state
            return

        # Fetch positions (or reuse)
        if positions_resp is None:
            positions_resp = self.client.get_positions()

        if not (positions_resp or {}).get("success"):
            return

        pos_list = (positions_resp.get("data", {}) or {}).get("list", []) or []
        pos = None
        for p in pos_list:
            if (p.get("symbol") or "") != symbol:
                continue
            try:
                if float(p.get("size", 0) or 0) == 0:
                    continue
            except (TypeError, ValueError):
                continue
            pos = p
            break

        if not pos:
            bot.pop("_skip_new_orders_for_margin", None)
            bot.pop("_skip_opening_orders_for_margin", None)
            if bot.get("last_warning") == "Preserving margin for auto-margin":
                bot["last_warning"] = None
            return

        try:
            mark_price = float(pos.get("markPrice", 0) or 0)
            liq_price = float(pos.get("liqPrice", 0) or 0)
        except (TypeError, ValueError):
            return

        pos_idx = int(pos.get("positionIdx", 0) or 0)
        if pos_idx in (1, 2) and position_idx != pos_idx:
            # In hedge mode, ensure we add margin to the correct leg.
            position_idx = pos_idx

        if mark_price <= 0 or liq_price <= 0:
            return

        pct_to_liq = abs(mark_price - liq_price) / mark_price * 100.0
        state["last_seen_pct_to_liq"] = round(pct_to_liq, 4)

        def _reload_position_snapshot():
            refreshed_positions = self.client.get_positions()
            if not refreshed_positions.get("success"):
                return None
            refreshed_list = (refreshed_positions.get("data", {}) or {}).get(
                "list", []
            ) or []
            for candidate in refreshed_list:
                if (candidate.get("symbol") or "") != symbol:
                    continue
                try:
                    if float(candidate.get("size", 0) or 0) <= 0:
                        continue
                    refreshed_mark = float(candidate.get("markPrice", 0) or 0)
                    refreshed_liq = float(candidate.get("liqPrice", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if refreshed_mark <= 0 or refreshed_liq <= 0:
                    continue
                refreshed_idx = int(candidate.get("positionIdx", 0) or 0)
                refreshed_pct = (
                    abs(refreshed_mark - refreshed_liq) / refreshed_mark * 100.0
                )
                return candidate, refreshed_mark, refreshed_liq, refreshed_pct, refreshed_idx
            return None

        # =============================================================================
        # TIER 2 EMERGENCY: Absolute Floor (Smart Feature #27-A)
        # Triggered regardless of balance when distance < 5%
        # SKIP if bot started < 2 minutes ago to prevent accidental trigger at start
        # =============================================================================
        is_tier2_eligible = True
        started_at = bot.get("started_at")
        if started_at:
            try:
                started_dt = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                )
                uptime_sec = (datetime.now(timezone.utc) - started_dt).total_seconds()
                if uptime_sec < 120:  # 120s grace period for bot initialization
                    is_tier2_eligible = False
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # FIRST-RUN PROTECTION: If a fresh position starts with dangerously low
        # liq distance, immediately add margin before any partial-close logic.
        # Use exact math to reach the target safety distance (15%).
        # ---------------------------------------------------------------------
        from config.strategy_config import AUTO_MARGIN_KEEP_FREE_PCT, AUTO_MARGIN_KEEP_FREE_USDT

        def _refresh_margin_headroom() -> Tuple[float, float]:
            current_available = self._get_usdt_available_balance()
            keep_free_local = max(
                float(AUTO_MARGIN_KEEP_FREE_USDT),
                float(AUTO_MARGIN_KEEP_FREE_PCT) * float(current_available),
            )
            return current_available, max(0.0, current_available - keep_free_local)

        available, available_for_margin = _refresh_margin_headroom()
        if last_ts == 0 and pct_to_liq < min_trigger_pct and available > 0:
            # Calculate exactly how much is needed to reach target_liq_pct (usually 20% or 15%)
            needed_amount = self._calculate_needed_margin(
                current_mark_price=mark_price,
                current_liq_price=liq_price,
                target_distance_pct=target_liq_pct,
                position_size=float(pos.get("size", 0)),
                position_side=pos.get("side", "Buy"),
                current_margin=float(pos.get("positionIM", 0) or 0),
            )

            cap_available = available
            if max_total_add_usdt > 0 and remaining_cap is not None:
                cap_available = min(cap_available, max(0.0, remaining_cap))
            if max_add_ratio > 0:
                ratio_cap = available * max(0.0, min(max_add_ratio, 1.0))
                if needed_amount > 0:
                    ratio_cap = max(
                        ratio_cap,
                        min(available_for_margin, needed_amount),
                    )
                cap_available = min(cap_available, ratio_cap)
            cap_available = min(cap_available, available_for_margin)

            # Use needed_amount but respect per-add and total caps
            per_add_cap = max_add_usdt if max_add_usdt > 0 else cap_available
            if needed_amount > 0:
                per_add_cap = max(per_add_cap, min(cap_available, needed_amount))
            margin_to_add = min(needed_amount, cap_available, per_add_cap)

            if margin_to_add >= 0.01:
                try:
                    resp = self.client.add_or_reduce_margin(
                        symbol=symbol,
                        margin=float(margin_to_add),
                        position_idx=position_idx,
                    )
                    state["last_add_ts"] = now_ts
                    if resp.get("success"):
                        state["last_add_usdt"] = round(float(margin_to_add), 4)
                        state["total_added_usdt"] = round(
                            total_added + float(margin_to_add), 4
                        )
                        state["last_add_reason"] = (
                            f"FIRST_RUN_IMMEDIATE (Targeting {target_liq_pct}%) pct_to_liq={pct_to_liq:.2f}%"
                        )
                        logger.warning(
                            f"[{symbol}] 🛡️ FIRST_RUN_IMMEDIATE: Added ${margin_to_add:.2f} margin "
                            f"to increase liq distance from {pct_to_liq:.2f}% (Target: {target_liq_pct}%)"
                        )
                        state.pop("last_add_error", None)
                        if max_total_add_usdt > 0:
                            remaining_cap = max_total_add_usdt - float(
                                state["total_added_usdt"]
                            )
                            bot["auto_margin_remaining_cap"] = round(remaining_cap, 4)
                        self._persist_auto_margin_state(bot, state, symbol)
                        return
                    else:
                        state["last_add_error"] = (
                            resp.get("error") or "add-margin failed"
                        )
                except Exception as e:
                    state["last_add_ts"] = now_ts
                    state["last_add_error"] = f"Exception: {str(e)}"
                bot["auto_margin_state"] = state

        if is_tier2_eligible and pct_to_liq < EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT:
            logger.warning(
                f"[{symbol}] 🚨 TIER 2 EMERGENCY: Liq distance {pct_to_liq:.2f}% < {EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT}%! "
                f"Cutting size immediately (Absolute Floor)."
            )
            partial_closed = self._emergency_partial_close(
                bot=bot,
                symbol=symbol,
                position_size=float(pos.get("size", 0)),
                position_side=pos.get("side", "Buy"),
                pct_to_liq=pct_to_liq,
                position_idx=int(pos.get("positionIdx", 0) or 0),
                is_tier2=True,
            )
            if partial_closed:
                import time as time_mod

                time_mod.sleep(0.5)
                # Re-fetch balance but continue to other checks to see if we can still add margin
                available = self._get_usdt_available_balance()

                # Trigger grid recenter after partial close to prevent stranded positions
                remaining_size = abs(float(pos.get("size", 0))) * (1 - EMERGENCY_PARTIAL_CLOSE_TIER2_PCT / 100.0)
                if remaining_size > 0:
                    recenter_result = self._trigger_quick_profit_recenter(
                        bot=bot,
                        symbol=symbol,
                        last_price=mark_price,
                        remaining_position_size=remaining_size,
                    )
                    if recenter_result.get("success"):
                        logger.info(
                            f"[{symbol}] Grid recentered after Tier 2 emergency close "
                            f"(remaining: {remaining_size})"
                        )

        # =============================================================================
        # CRITICAL LIQ PROTECTION: Cancel far orders FIRST to free margin
        # This runs BEFORE other checks - it's the highest priority action
        # =============================================================================
        available, available_for_margin = _refresh_margin_headroom()
        required_floor_amount = self._calculate_needed_margin(
            current_mark_price=mark_price,
            current_liq_price=liq_price,
            target_distance_pct=target_liq_pct,
            position_size=float(pos.get("size", 0)),
            position_side=pos.get("side", "Buy"),
            current_margin=float(pos.get("positionIM", 0) or 0),
        )
        if pct_to_liq < min_trigger_pct and (
            available_for_margin + 1e-9 < required_floor_amount
        ):
            import time as time_mod

            # Differentiate between "Warning" (5-10%) and "CRITICAL" (<5%) to avoid log spam
            if pct_to_liq < 5.0:
                log_level = "🚨 CRITICAL"
                max_cancel = 10
            else:
                log_level = "⚠️ Maintenance"
                max_cancel = 3

            logger.warning(
                f"[{symbol}] {log_level}: Liq distance {pct_to_liq:.2f}% < {min_trigger_pct:.2f}% "
                f"and available ${available:.2f} - freeing margin to restore the 8% liq floor."
            )

            cancelled = self._emergency_cancel_far_orders(
                symbol, mark_price, 1, max_cancel, force=True
            )
            if cancelled > 0:
                # Wait a moment for margin to be released, then recheck
                time_mod.sleep(0.5)
                available, available_for_margin = _refresh_margin_headroom()
                logger.info(
                    f"[{symbol}] After cancelling {cancelled} orders, available balance: ${available:.2f}"
                )
                required_floor_amount = self._calculate_needed_margin(
                    current_mark_price=mark_price,
                    current_liq_price=liq_price,
                    target_distance_pct=target_liq_pct,
                    position_size=float(pos.get("size", 0)),
                    position_side=pos.get("side", "Buy"),
                    current_margin=float(pos.get("positionIM", 0) or 0),
                )

            # =============================================================================
            # EMERGENCY PARTIAL CLOSE: Last resort when freed order margin is still
            # not enough to restore the 8% liq floor.
            # =============================================================================
            if available_for_margin + 1e-9 < required_floor_amount:
                # Try emergency partial close
                partial_closed = self._emergency_partial_close(
                    bot=bot,
                    symbol=symbol,
                    position_size=float(pos.get("size", 0)),
                    position_side=pos.get("side", "Buy"),
                    pct_to_liq=pct_to_liq,
                    position_idx=int(pos.get("positionIdx", 0) or 0),
                    is_tier2=False,
                )
                if partial_closed:
                    # Wait for margin to be freed
                    time_mod.sleep(0.5)
                    available, available_for_margin = _refresh_margin_headroom()
                    logger.info(
                        f"[{symbol}] After partial close, available balance: ${available:.2f}"
                    )
                    refreshed_snapshot = _reload_position_snapshot()
                    if refreshed_snapshot:
                        (
                            pos,
                            mark_price,
                            liq_price,
                            pct_to_liq,
                            position_idx,
                        ) = refreshed_snapshot
                        state["last_seen_pct_to_liq"] = round(pct_to_liq, 4)
                        required_floor_amount = self._calculate_needed_margin(
                            current_mark_price=mark_price,
                            current_liq_price=liq_price,
                            target_distance_pct=target_liq_pct,
                            position_size=float(pos.get("size", 0)),
                            position_side=pos.get("side", "Buy"),
                            current_margin=float(pos.get("positionIM", 0) or 0),
                        )

                    # Trigger grid recenter after partial close to prevent stranded positions
                    remaining_size = abs(float(pos.get("size", 0))) * (1 - EMERGENCY_PARTIAL_CLOSE_PCT / 100.0)
                    if remaining_size > 0:
                        recenter_result = self._trigger_quick_profit_recenter(
                            bot=bot,
                            symbol=symbol,
                            last_price=mark_price,
                            remaining_position_size=remaining_size,
                        )
                        if recenter_result.get("success"):
                            logger.info(
                                f"[{symbol}] Grid recentered after Tier 1 emergency close "
                                f"(remaining: {remaining_size})"
                            )

            if cancelled > 0 or pct_to_liq < min_trigger_pct:
                # Block new orders for this cycle so any freed margin can be
                # used immediately by auto-margin recovery below.
                bot["_skip_new_orders_for_margin"] = True
                logger.warning(
                    f"[{symbol}] 🚨 Skipping new order placement to preserve margin for auto-margin"
                )

        # Check if above trigger threshold - no action needed for margin adding
        if pct_to_liq > min_trigger_pct:
            bot["auto_margin_state"] = state
            return

        # ---------------------------------------------------------------------
        # SECONDARY PROTECTION: Continuous small top-ups when distance < trigger
        # ---------------------------------------------------------------------
        # Cooldown check - but SKIP cooldown for critical situations (< 2.5%)
        is_critical = pct_to_liq < critical_pct  # Only skip cooldown when truly critical
        if not is_critical:
            if cooldown_sec > 0 and last_ts and (now_ts - last_ts) < cooldown_sec:
                bot["auto_margin_state"] = state
                return

        if available_for_margin <= 0:
            logger.warning(
                f"[{symbol}] AutoMargin: no available balance (pct_to_liq={pct_to_liq:.2f}%, target={target_liq_pct:.2f}%)"
            )
            bot["auto_margin_state"] = state
            return

        # Calculate exactly how much is needed to reach target_liq_pct (usually 15% or 20%)
        needed_amount = self._calculate_needed_margin(
            current_mark_price=mark_price,
            current_liq_price=liq_price,
            target_distance_pct=target_liq_pct,
            position_size=float(pos.get("size", 0)),
            position_side=pos.get("side", "Buy"),
            current_margin=float(pos.get("positionIM", 0) or 0),
        )
        critical_recovery_needed_amount = 0.0
        if pct_to_liq < CRITICAL_LIQ_PCT:
            emergency_target_pct = max(
                critical_recovery_target_pct,
                min_trigger_pct,
            )
            critical_recovery_needed_amount = self._calculate_needed_margin(
                current_mark_price=mark_price,
                current_liq_price=liq_price,
                target_distance_pct=emergency_target_pct,
                position_size=float(pos.get("size", 0)),
                position_side=pos.get("side", "Buy"),
                current_margin=float(pos.get("positionIM", 0) or 0),
            )

        cap_available = available
        if max_total_add_usdt > 0 and remaining_cap is not None:
            cap_available = min(cap_available, max(0.0, remaining_cap))
        if max_add_ratio > 0:
            ratio_cap = available * max(0.0, min(max_add_ratio, 1.0))
            if critical_recovery_needed_amount > 0:
                ratio_cap = max(
                    ratio_cap,
                    min(available_for_margin, critical_recovery_needed_amount),
                )
            cap_available = min(cap_available, ratio_cap)
        cap_available = min(cap_available, available_for_margin)

        # Use needed_amount but respect per-add and total caps
        per_add_cap = max_add_usdt if max_add_usdt > 0 else cap_available
        if critical_recovery_needed_amount > 0:
            per_add_cap = max(
                per_add_cap,
                min(cap_available, critical_recovery_needed_amount),
            )
        margin_to_add = min(needed_amount, cap_available, per_add_cap)

        # Bybit constraint: position margin cannot exceed position value
        _pos_im = self._safe_float(pos.get("positionIM"), 0)
        _pos_val = self._safe_float(pos.get("positionValue"), 0)
        if _pos_im >= _pos_val and _pos_val > 0:
            logger.info("[%s] AutoMargin: skip (pm>=pv: %.2f >= %.2f)", symbol, _pos_im, _pos_val)
            bot["auto_margin_state"] = state
            return

        if margin_to_add >= min_add_usdt:
            try:
                event_type = "CRITICAL_RECOVERY" if is_critical else "AUTO_MARGIN_TOPUP"
                logger.warning(
                    f"[{symbol}] 🛡️ {event_type}: Adding ${margin_to_add:.2f} margin "
                    f"to increase liq distance from {pct_to_liq:.2f}% (Target: {target_liq_pct}%)"
                )
                resp = self.client.add_or_reduce_margin(
                    symbol=symbol,
                    margin=float(margin_to_add),
                    position_idx=position_idx,
                )
                state["last_add_ts"] = now_ts
                if resp.get("success"):
                    state["last_add_usdt"] = round(float(margin_to_add), 4)
                    state["total_added_usdt"] = round(
                        total_added + float(margin_to_add), 4
                    )
                    state["last_add_reason"] = (
                        f"{event_type} pct_to_liq={pct_to_liq:.2f}%"
                    )
                    state.pop("last_add_error", None)

                    if max_total_add_usdt > 0:
                        remaining_cap = max_total_add_usdt - float(
                            state["total_added_usdt"]
                        )
                        bot["auto_margin_remaining_cap"] = round(remaining_cap, 4)

                    self._persist_auto_margin_state(bot, state, symbol)
                    return
                else:
                    state["last_add_error"] = resp.get("error") or "add-margin failed"
            except Exception as e:
                state["last_add_ts"] = now_ts
                state["last_add_error"] = f"Exception: {str(e)}"
        elif needed_amount > 0 and cap_available <= 0:
            # Budget exhausted but liq distance still dangerous
            logger.error(
                f"[{symbol}] ⚠️ AUTO-MARGIN CAP REACHED! Distance is still unsafe ({pct_to_liq:.2f}%) "
                f"but budget (${total_added:.2f}/${max_total_add_usdt:.2f}) or account balance is exhausted!"
            )

        self._persist_auto_margin_state(bot, state, symbol)

