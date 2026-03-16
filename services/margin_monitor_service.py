"""
Bybit Control Center - Margin Monitor Service

Independent margin monitoring for ALL positions, regardless of bot status.
Automatically adds margin when distance to liquidation drops below threshold.
Works even when bots are paused, stopped, or in error state.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Optional

from services.bybit_client import BybitClient
from services.bot_storage_service import BotStorageService
from config.strategy_config import (
    MARGIN_MONITOR_ENABLED,
    MARGIN_MONITOR_TRIGGER_PCT,
    MARGIN_MONITOR_TARGET_PCT,
    MARGIN_MONITOR_CRITICAL_PCT,
    MARGIN_MONITOR_COOLDOWN_SEC,
    MARGIN_MONITOR_MAX_ADD_RATIO,
    MARGIN_MONITOR_MIN_ADD_USDT,
    MARGIN_MONITOR_MAX_ADD_USDT,
    MARGIN_MONITOR_ALL_POSITIONS,
    MARGIN_MONITOR_EMERGENCY_MAX_PCT_PER_BOT,
    MARGIN_MONITOR_EMERGENCY_MAX_PCT_TOTAL,
    MARGIN_MONITOR_EMERGENCY_WINDOW_SEC,
    MARGIN_MONITOR_KEEP_FREE_PCT,
    MARGIN_MONITOR_KEEP_FREE_USDT,
)

logger = logging.getLogger(__name__)


ACTIVE_MARGIN_BLOCK_STATUSES = {
    "running",
    "paused",
    "recovering",
    "risk_stopped",
}


class MarginMonitorService:
    """
    Independent margin monitor that protects ALL positions from liquidation.

    Unlike per-bot auto-margin, this service:
    - Monitors ALL open positions on the account
    - Works independently of bot status (paused/stopped/error bots still protected)
    - Uses global config thresholds
    - Has its own state persistence
    """

    STATE_FILE = os.path.join("storage", "margin_monitor_state.json")

    def __init__(self, client: BybitClient, bot_storage: Optional[BotStorageService] = None):
        """
        Initialize the margin monitor service.

        Args:
            client: Initialized BybitClient instance
        """
        self.client = client
        self.bot_storage = bot_storage
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load persisted state from JSON file."""
        try:
            if os.path.exists(self.STATE_FILE):
                with open(self.STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load margin monitor state: {e}")
        return {}

    def _save_state(self) -> None:
        """Persist state to JSON file."""
        try:
            os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
            with open(self.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save margin monitor state: {e}")

    def _get_emergency_history(self) -> List[Dict[str, Any]]:
        history = self.state.get("_emergency_add_history", [])
        if not isinstance(history, list):
            history = []

        cutoff = time.time() - MARGIN_MONITOR_EMERGENCY_WINDOW_SEC
        history = [entry for entry in history if entry.get("ts", 0) >= cutoff]
        self.state["_emergency_add_history"] = history
        return history

    def _record_emergency_add(self, symbol: str, amount: float) -> None:
        history = self._get_emergency_history()
        history.append({
            "ts": time.time(),
            "symbol": symbol,
            "amount": round(float(amount), 4),
        })
        self.state["_emergency_add_history"] = history

    def _bot_blocking_reason(self, symbol: str) -> Optional[str]:
        """Check if margin operations should be blocked due to bot status."""
        if not self.bot_storage:
            return None

        try:
            bots = self.bot_storage.list_bots()
        except Exception as e:
            logger.warning("MarginMonitor: failed to load bots for %s: %s", symbol, e)
            return None

        symbol_bots = [bot for bot in bots if bot.get("symbol") == symbol]
        if not symbol_bots:
            return None

        candidate_bots = symbol_bots
        if MARGIN_MONITOR_ALL_POSITIONS:
            # When protecting all positions, ignore stale stopped/error bots that
            # share the symbol. Only an active bot state should suppress add-margin.
            candidate_bots = [
                bot
                for bot in symbol_bots
                if (bot.get("status") or "").lower() in ACTIVE_MARGIN_BLOCK_STATUSES
            ]
            if not candidate_bots:
                return None

        for bot in candidate_bots:
            status = (bot.get("status") or "").lower()

            # Always block if explicitly risk-stopped or reduce-only
            if status == "risk_stopped":
                return "status=risk_stopped"
            if bot.get("reduce_only_mode"):
                return "reduce_only_mode"

            if bot.get("_upnl_stoploss_reason"):
                return "upnl_stoploss_active"

            pause_reason = bot.get("pause_reason_type")
            if pause_reason and not MARGIN_MONITOR_ALL_POSITIONS:
                return f"pause_reason={pause_reason}"

            cooldown_until = bot.get("upnl_stoploss_cooldown_until")
            if cooldown_until:
                try:
                    cooldown_str = cooldown_until.replace("Z", "").split(".")[0]
                    cooldown_ts = time.mktime(time.strptime(cooldown_str, "%Y-%m-%dT%H:%M:%S"))
                    if cooldown_ts > time.time():
                        return "upnl_stoploss_cooldown"
                except Exception:
                    return "upnl_stoploss_cooldown"

            # Block margin adds when opening orders are blocked (regardless of mode)
            if bot.get("_block_opening_orders"):
                return "block_opening_orders"

            if not MARGIN_MONITOR_ALL_POSITIONS:
                if status in ("paused", "recovering", "error", "stopped"):
                    return f"status={status}"
                if bot.get("_block_opening_orders"):
                    return "block_opening_orders"
                if bot.get("btc_guard_active"):
                    return "btc_guard_active"
                if bot.get("smart_entry_active"):
                    return "smart_entry_active"

        return None

    def _get_available_balance(self) -> float:
        """Get available USDT balance for margin operations."""
        try:
            response = self.client.get_wallet_balance()
            if response.get("success"):
                data = response.get("data", {})
                account_list = data.get("list", [])
                if account_list:
                    account = account_list[0]
                    coins = account.get("coin", [])
                    for coin in coins:
                        if coin.get("coin") == "USDT":
                            # Try availableToWithdraw first
                            available = coin.get("availableToWithdraw")
                            if available and str(available).strip():
                                return float(available)

                            # Calculate available = walletBalance - totalPositionIM - totalOrderIM
                            wallet_balance = float(coin.get("walletBalance", 0) or 0)
                            position_im = float(coin.get("totalPositionIM", 0) or 0)
                            order_im = float(coin.get("totalOrderIM", 0) or 0)
                            calculated = wallet_balance - position_im - order_im
                            if calculated > 0:
                                return calculated

                            return 0.0
                    # Fallback to account-level
                    return float(account.get("totalAvailableBalance", 0) or 0)
        except Exception as e:
            logger.warning(f"Failed to get available balance: {e}")
        return 0.0

    @staticmethod
    def _calculate_needed_margin(
        current_mark_price: float,
        current_liq_price: float,
        target_distance_pct: float,
        position_size: float,
        position_side: str,
    ) -> float:
        """
        Estimate margin needed to reach a target liquidation distance.
        """
        if current_mark_price <= 0 or current_liq_price <= 0 or position_size <= 0:
            return 0.0

        if position_side.lower() == "buy":
            target_liq = current_mark_price * (1 - (target_distance_pct / 100.0))
            needed = position_size * (current_liq_price - target_liq)
        else:
            target_liq = current_mark_price * (1 + (target_distance_pct / 100.0))
            needed = position_size * (target_liq - current_liq_price)

        return max(0.0, needed)

    def check_all_positions(self) -> Dict[str, Any]:
        """
        Check ALL open positions and add margin if needed.

        Returns:
            Dict with:
            - actions: List of margin additions performed
            - checked: Number of positions checked
            - skipped: Number of positions skipped (above threshold)
            - error: Error message if any
        """
        result = {
            "actions": [],
            "checked": 0,
            "skipped": 0,
            "error": None,
        }

        if not MARGIN_MONITOR_ENABLED:
            result["error"] = "Margin monitor disabled"
            return result

        # Fetch all positions
        positions_resp = self.client.get_positions()
        if not positions_resp.get("success"):
            result["error"] = positions_resp.get("error", "Failed to fetch positions")
            return result

        pos_list = (positions_resp.get("data", {}) or {}).get("list", []) or []

        # C3 audit: build set of symbols where an active bot owns auto_margin.
        # Skip those symbols here — the per-bot _auto_margin_guard handles them.
        bot_owned_margin_symbols: set = set()
        if self.bot_storage:
            try:
                for _b in self.bot_storage.list_bots():
                    if (
                        str(_b.get("status") or "").lower() in ("running", "recovering")
                        and (_b.get("auto_margin") or {}).get("enabled", False)
                        and _b.get("symbol")
                    ):
                        bot_owned_margin_symbols.add(str(_b["symbol"]).strip().upper())
            except Exception:
                pass
        if bot_owned_margin_symbols:
            logger.debug(
                "MarginMonitor deferring %d symbol(s) to per-bot auto_margin: %s",
                len(bot_owned_margin_symbols),
                ", ".join(sorted(bot_owned_margin_symbols)),
            )

        # Get available balance once (reuse for all positions)
        available_balance = self._get_available_balance()
        available_balance_start = available_balance
        keep_free = max(
            float(MARGIN_MONITOR_KEEP_FREE_USDT),
            float(MARGIN_MONITOR_KEEP_FREE_PCT) * float(available_balance_start),
        )
        # Emergency cap tracking (rolling window)
        emergency_history = self._get_emergency_history()
        total_emergency = sum(float(h.get("amount", 0) or 0) for h in emergency_history)
        emergency_by_symbol: Dict[str, float] = {}
        for entry in emergency_history:
            sym = entry.get("symbol")
            if not sym:
                continue
            emergency_by_symbol[sym] = emergency_by_symbol.get(sym, 0.0) + float(
                entry.get("amount", 0) or 0
            )
        now_ts = time.time()

        for pos in pos_list:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue

            # C3 audit: skip symbols managed by per-bot auto_margin
            if symbol.strip().upper() in bot_owned_margin_symbols:
                result["skipped"] += 1
                continue

            # Check if position has size > 0
            try:
                size = float(pos.get("size", 0) or 0)
                if size == 0:
                    continue
            except (TypeError, ValueError):
                continue

            result["checked"] += 1

            # Calculate distance to liquidation
            try:
                mark_price = float(pos.get("markPrice", 0) or 0)
                liq_price = float(pos.get("liqPrice", 0) or 0)
            except (TypeError, ValueError):
                continue

            if mark_price <= 0 or liq_price <= 0:
                continue

            pct_to_liq = abs(mark_price - liq_price) / mark_price * 100.0

            # Get or create state for this symbol
            sym_state = self.state.get(symbol, {})
            sym_state["last_seen_pct_to_liq"] = round(pct_to_liq, 4)

            # Check if above trigger threshold - no action needed
            if pct_to_liq > MARGIN_MONITOR_TRIGGER_PCT:
                self.state[symbol] = sym_state
                result["skipped"] += 1
                continue

            # Check cooldown
            last_add_ts = float(sym_state.get("last_add_ts", 0) or 0)
            is_critical = pct_to_liq < MARGIN_MONITOR_CRITICAL_PCT
            is_first_run = (last_add_ts == 0)

            # Skip cooldown for first run or critical situations
            if not is_first_run and not is_critical:
                if MARGIN_MONITOR_COOLDOWN_SEC > 0:
                    if (now_ts - last_add_ts) < MARGIN_MONITOR_COOLDOWN_SEC:
                        self.state[symbol] = sym_state
                        continue

            # Check available balance (keep some free for orders/fees)
            available_for_margin = max(0.0, available_balance - keep_free)
            if available_for_margin <= 0:
                sym_state["last_add_error"] = "No available balance"
                self.state[symbol] = sym_state
                continue

            # EMERGENCY MODE: Enforce per-bot and total caps in a rolling window.
            is_emergency = pct_to_liq <= MARGIN_MONITOR_CRITICAL_PCT
            if is_emergency:
                effective_min = 0.01  # Bybit minimum
                total_cap = (
                    available_balance_start * MARGIN_MONITOR_EMERGENCY_MAX_PCT_TOTAL
                    if MARGIN_MONITOR_EMERGENCY_MAX_PCT_TOTAL > 0
                    else 0.0
                )
                per_bot_cap = (
                    available_balance_start * MARGIN_MONITOR_EMERGENCY_MAX_PCT_PER_BOT
                    if MARGIN_MONITOR_EMERGENCY_MAX_PCT_PER_BOT > 0
                    else 0.0
                )
                total_remaining = (
                    max(0.0, total_cap - total_emergency)
                    if total_cap > 0
                    else available_balance
                )
                bot_used = emergency_by_symbol.get(symbol, 0.0)
                bot_remaining = (
                    max(0.0, per_bot_cap - bot_used)
                    if per_bot_cap > 0
                    else available_balance
                )
                emergency_remaining = min(available_balance, total_remaining, bot_remaining)
                if emergency_remaining <= 0:
                    sym_state["last_add_error"] = "Emergency cap reached"
                    self.state[symbol] = sym_state
                    continue
                logger.warning(
                    "[%s] MarginMonitor: emergency mode - capped add (remaining=%.2f)",
                    symbol,
                    emergency_remaining,
                )
            else:
                effective_min = MARGIN_MONITOR_MIN_ADD_USDT
                effective_ratio = MARGIN_MONITOR_MAX_ADD_RATIO

            # Calculate amount to add
            if is_emergency:
                base_budget = emergency_remaining
            else:
                base_budget = min(
                    available_for_margin * max(0.0, min(effective_ratio, 1.0)),
                    MARGIN_MONITOR_MAX_ADD_USDT,
                )

            if base_budget < effective_min:
                sym_state["last_add_error"] = "Budget below minimum"
                self.state[symbol] = sym_state
                continue

            # Severity scale: add more when closer to liq
            severity = (MARGIN_MONITOR_TARGET_PCT - pct_to_liq) / max(MARGIN_MONITOR_TARGET_PCT, 0.0001)
            severity = max(0.15, min(1.0, severity))

            # In critical situations (< 8%), use maximum severity
            if is_emergency or is_critical:
                severity = 1.0

            # Calculate amount needed to reach target liq distance
            needed_amount = self._calculate_needed_margin(
                current_mark_price=mark_price,
                current_liq_price=liq_price,
                target_distance_pct=MARGIN_MONITOR_TARGET_PCT,
                position_size=float(pos.get("size", 0) or 0),
                position_side=pos.get("side", "Buy"),
            )

            amount = base_budget * severity
            if not is_emergency:
                amount = min(amount, MARGIN_MONITOR_MAX_ADD_USDT)
            # Never add more than needed, and respect free-balance reserve
            amount = min(amount, needed_amount, available_for_margin)

            # Final check - in emergency allow any amount >= $0.01.
            # If the calculated amount fell below the minimum due to severity/needed
            # clamps, retry by clamping up to effective_min (if balance permits).
            if amount < effective_min:
                if is_emergency and amount >= 0.01:
                    pass  # Allow it
                elif available_for_margin >= effective_min:
                    # Calculated amount is too small but we have balance — use the
                    # minimum instead of silently skipping. Log so the operator can
                    # see the clamp happened.
                    logger.warning(
                        "[%s] MarginMonitor: calculated amount %.4f < min %.4f; "
                        "clamping to minimum for retry",
                        symbol,
                        amount,
                        effective_min,
                    )
                    amount = effective_min
                else:
                    sym_state["last_add_error"] = "Amount below minimum, insufficient balance for min retry"
                    self.state[symbol] = sym_state
                    continue

            # Skip if position margin already exceeds position value (Bybit constraint: pm > pv)
            try:
                position_margin = float(pos.get("positionIM", 0) or 0)
                position_value = float(pos.get("positionValue", 0) or 0)
                if position_margin >= position_value and position_value > 0:
                    logger.info(
                        "[%s] MarginMonitor: skip add-margin (pm>=pv: %.2f >= %.2f)",
                        symbol,
                        position_margin,
                        position_value,
                    )
                    sym_state["last_add_error"] = f"pm>=pv ({position_margin:.2f} >= {position_value:.2f})"
                    self.state[symbol] = sym_state
                    continue
            except (TypeError, ValueError):
                pass  # If we can't parse, proceed with add-margin attempt

            block_reason = self._bot_blocking_reason(symbol)
            if block_reason:
                logger.warning(
                    "[%s] MarginMonitor: skip add margin due to %s; prioritize closing risk",
                    symbol,
                    block_reason,
                )
                sym_state["last_add_error"] = f"blocked: {block_reason}"
                self.state[symbol] = sym_state
                continue

            # Execute add-margin
            try:
                position_idx = int(pos.get("positionIdx", 0) or 0)
                resp = self.client.add_or_reduce_margin(
                    symbol=symbol,
                    margin=float(amount),
                    position_idx=position_idx
                )
            except Exception as e:
                sym_state["last_add_ts"] = now_ts
                sym_state["last_add_error"] = f"Exception: {str(e)}"
                self.state[symbol] = sym_state
                logger.error(f"[{symbol}] MarginMonitor add-margin exception: {e}")
                continue

            sym_state["last_add_ts"] = now_ts

            if resp.get("success"):
                total_added = float(sym_state.get("total_added_usdt", 0) or 0)
                sym_state["last_add_usdt"] = round(float(amount), 4)
                sym_state["total_added_usdt"] = round(total_added + float(amount), 4)
                reason = "CRITICAL" if is_critical else ("FIRST_RUN" if is_first_run else "NORMAL")
                sym_state["last_add_reason"] = f"pct_to_liq {pct_to_liq:.2f}% <= {MARGIN_MONITOR_TRIGGER_PCT:.2f}% ({reason})"
                sym_state.pop("last_add_error", None)

                # Reduce available balance for next position
                available_balance = max(0, available_balance - amount)

                action = {
                    "symbol": symbol,
                    "amount": round(amount, 4),
                    "pct_to_liq": round(pct_to_liq, 2),
                    "reason": reason,
                    "side": pos.get("side", ""),
                }
                result["actions"].append(action)

                logger.warning(
                    f"[{symbol}] 🛡️ MarginMonitor: Added {amount:.4f} USDT "
                    f"(pct_to_liq={pct_to_liq:.2f}%, {reason})"
                )
                if is_emergency:
                    self._record_emergency_add(symbol, amount)
                    total_emergency += float(amount)
                    emergency_by_symbol[symbol] = emergency_by_symbol.get(symbol, 0.0) + float(amount)
            else:
                sym_state["last_add_error"] = resp.get("error") or "add-margin failed"
                logger.error(f"[{symbol}] MarginMonitor add-margin failed: {resp.get('error')}")

            self.state[symbol] = sym_state

        # Clear stale state for symbols that no longer have open positions
        active_symbols = {
            str(p.get("symbol") or "").strip()
            for p in pos_list
            if float(p.get("size", 0) or 0) > 0
        }
        for sym in list(self.state.keys()):
            if sym.startswith("_"):
                continue  # Skip meta keys like _emergency_add_history
            if sym not in active_symbols:
                self.reset_symbol_state(sym)

        # Save state after processing all positions
        self._save_state()

        return result

    def get_status(self) -> Dict[str, Any]:
        """
        Get current margin monitor status for all tracked symbols.

        Returns:
            Dict with current state of all monitored positions
        """
        return {
            "enabled": MARGIN_MONITOR_ENABLED,
            "trigger_pct": MARGIN_MONITOR_TRIGGER_PCT,
            "target_pct": MARGIN_MONITOR_TARGET_PCT,
            "critical_pct": MARGIN_MONITOR_CRITICAL_PCT,
            "positions": dict(self.state),
        }

    def reset_symbol_state(self, symbol: str) -> bool:
        """
        Reset state for a specific symbol (e.g., after position is closed).

        Args:
            symbol: Trading pair symbol to reset

        Returns:
            True if state was reset, False if symbol not found
        """
        if symbol in self.state:
            del self.state[symbol]
            self._save_state()
            return True
        return False

    def reset_all_state(self) -> None:
        """Reset all margin monitor state."""
        self.state = {}
        self._save_state()
        logger.info("MarginMonitor: All state reset")
