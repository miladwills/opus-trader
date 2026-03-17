"""
Bybit Control Center - Risk Manager Service

Manages risk state for account-level and per-bot risk controls.
Implements file locking to prevent race conditions.
"""

from pathlib import Path
from copy import deepcopy
import json
import os
import tempfile
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from services.lock_service import file_lock

logger = logging.getLogger(__name__)


class RiskManagerService:
    """
    Service for managing risk state and enforcing risk limits.
    """

    DEFAULT_STATE = {
        "daily_start_equity": 0.0,
        "peak_equity": 0.0,
        "global_kill_switch": False,
        "kill_switch_triggered": False,  # 001-trading-bot-audit FR-011
        "kill_switch_triggered_at": None,  # 001-trading-bot-audit FR-011
        "daily_loss_pct": 0.0,  # 001-trading-bot-audit
        "last_daily_reset": None,  # 001-trading-bot-audit
        "per_bot": {},
        "symbol_daily": {},
        "kill_switch_enforced": False,  # Tracks whether enforcement actions have executed
    }

    def __init__(
        self, file_path: str, max_bot_loss_pct: float, max_daily_loss_pct: float
    ):
        """
        Initialize the risk manager service.

        Args:
            file_path: Path to the JSON file for risk state
            max_bot_loss_pct: Maximum loss percentage per bot (e.g., 0.05 for 5%)
            max_daily_loss_pct: Maximum daily drawdown percentage (e.g., 0.08 for 8%)
        """
        self.file_path = Path(file_path)
        self.lock_path = Path(str(file_path) + ".lock")
        self.max_bot_loss_pct = max_bot_loss_pct
        self.max_daily_loss_pct = max_daily_loss_pct

        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create lock file if it doesn't exist
        if not self.lock_path.exists():
            self.lock_path.touch()

        # Create file with default structure if it doesn't exist
        if not self.file_path.exists():
            self._write_state(self.DEFAULT_STATE.copy())
        self._last_good_state = None

    @contextmanager
    def _file_lock(self, exclusive: bool = False):
        """
        Context manager for file locking.

        Args:
            exclusive: If True, acquire exclusive lock (for writes).
                      If False, acquire shared lock (for reads).
        """
        with file_lock(self.lock_path, exclusive=exclusive) as lock_fd:
            yield lock_fd

    def _read_modify_write(self, modifier_fn) -> Dict[str, Any]:
        """
        H3 audit: Atomic read-modify-write under a single exclusive lock span.
        Eliminates TOCTOU race on kill-switch state, peak equity, daily loss.
        """
        try:
            with self._file_lock(exclusive=True):
                try:
                    with open(self.file_path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    if not isinstance(state, dict):
                        state = deepcopy(self.DEFAULT_STATE)
                    for key, default_value in self.DEFAULT_STATE.items():
                        if key not in state:
                            state[key] = default_value
                except (json.JSONDecodeError, FileNotFoundError):
                    state = deepcopy(self.DEFAULT_STATE)
                state = modifier_fn(state)
                dir_path = self.file_path.parent
                fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state, f, indent=2, ensure_ascii=False)
                    os.replace(temp_path, self.file_path)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
                self._last_good_state = deepcopy(state)
                return state
        except Exception as exc:
            logger.warning("Atomic read-modify-write failed: %s", exc)
            return self._read_state()

    def _read_state(self) -> Dict[str, Any]:
        """
        Read risk state from the JSON file with locking.

        Returns:
            Risk state dictionary, or default structure on error
        """
        try:
            with self._file_lock(exclusive=False):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # Ensure all required keys exist
                        for key, default_value in self.DEFAULT_STATE.items():
                            if key not in data:
                                data[key] = default_value
                        data.pop("risk_state_read_error", None)
                        self._last_good_state = deepcopy(data)
                        return data
                    raise ValueError("Risk state file did not contain a JSON object")
        except (json.JSONDecodeError, FileNotFoundError, IOError, ValueError) as exc:
            logger.error("Failed to read risk state safely: %s", exc)
            stored_state = getattr(self, "_last_good_state", None)
            state = deepcopy(stored_state) if stored_state is not None else deepcopy(self.DEFAULT_STATE)
            if stored_state is None:
                state["global_kill_switch"] = True
                state["kill_switch_triggered"] = True
                state["kill_switch_enforced"] = False
                state["kill_switch_triggered_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
            state["risk_state_read_error"] = str(exc)
            return state

    def _write_state(self, state: Dict[str, Any]) -> None:
        """
        Write risk state to the JSON file with locking.
        Uses atomic write pattern.

        Args:
            state: Risk state dictionary to write
        """
        try:
            with self._file_lock(exclusive=True):
                dir_path = self.file_path.parent
                fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state, f, indent=2, ensure_ascii=False)
                    os.replace(temp_path, self.file_path)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
        except (IOError, OSError) as e:
            logger.warning(f"Failed to write risk state: {e}")

    def _clear_global_kill_switch_state(
        self, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clear the account-level kill-switch latch without touching daily metrics."""
        state["global_kill_switch"] = False
        state["kill_switch_triggered"] = False
        state["kill_switch_triggered_at"] = None
        state["kill_switch_enforced"] = False
        return state

    @staticmethod
    def _today_iso() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _reset_daily_namespaces_if_needed(self, state: Dict[str, Any]) -> Dict[str, Any]:
        today = self._today_iso()
        last_reset = state.get("last_daily_reset")
        if last_reset != today:
            state["symbol_daily"] = {}
        else:
            state.setdefault("symbol_daily", {})
        return state

    def update_equity_state(self, current_equity: float) -> Dict[str, Any]:
        """
        Update equity tracking state and check for daily drawdown breach.
        H3 audit: Now uses atomic _read_modify_write to eliminate TOCTOU race.
        """
        from config.strategy_config import GLOBAL_KILL_SWITCH_ENABLED
        max_daily = self.max_daily_loss_pct

        def _modifier(state):
            state = self._reset_daily_namespaces_if_needed(state)
            today = self._today_iso()
            last_reset = state.get("last_daily_reset")
            if last_reset != today:
                if current_equity > 0:
                    state["daily_start_equity"] = current_equity
                    state["peak_equity"] = current_equity
                else:
                    state["daily_start_equity"] = 0.0
                    state["peak_equity"] = 0.0
                state["daily_loss_pct"] = 0.0
                state["last_daily_reset"] = today
                self._clear_global_kill_switch_state(state)
                state["symbol_daily"] = {}
            if state["daily_start_equity"] == 0.0:
                state["daily_start_equity"] = current_equity
            state["peak_equity"] = max(state["peak_equity"], current_equity)
            daily_start = state["daily_start_equity"]
            daily_drawdown_pct = (
                (current_equity - daily_start) / daily_start if daily_start > 0 else 0.0
            )
            state["daily_loss_pct"] = (
                abs(daily_drawdown_pct) if daily_drawdown_pct < 0 else 0.0
            )
            if not GLOBAL_KILL_SWITCH_ENABLED:
                self._clear_global_kill_switch_state(state)
                return state
            if not state.get("kill_switch_triggered"):
                if daily_drawdown_pct <= -max_daily:
                    import time as _t
                    state["kill_switch_triggered"] = True
                    state["kill_switch_triggered_at"] = _t.time()
                    state["global_kill_switch"] = True
                    state["kill_switch_enforced"] = False
                    logger.warning(
                        "GLOBAL KILL-SWITCH TRIGGERED: Daily loss %.2f%% exceeds limit %.2f%%",
                        abs(daily_drawdown_pct) * 100, max_daily * 100,
                    )
            return state

        return self._read_modify_write(_modifier)

    def check_account_limits(self, current_equity: float) -> Dict[str, Any]:
        """
                Check account-level risk limits.

                Args:
                    current_equity: Current account equity

                Returns:
        Dict with kill_switch status and drawdown percentage
        """
        state = self.update_equity_state(current_equity)

        daily_start = state["daily_start_equity"]
        if daily_start > 0:
            drawdown_pct = (current_equity - daily_start) / daily_start
        else:
            drawdown_pct = 0.0

        return {
            "kill_switch": state["global_kill_switch"],
            "drawdown_pct": round(drawdown_pct, 6),
        }

    def get_risk_state(self) -> Dict[str, Any]:
        """
        Get current risk state for API exposure.

        001-trading-bot-audit FR-011: Exposes kill-switch status.

        Returns:
            Dict with kill_switch_triggered, kill_switch_triggered_at, daily_loss_pct
        """
        return self._reset_daily_namespaces_if_needed(self._read_state())

    # =====================================================================
    # Kill-Switch Enforcement (US5)
    # =====================================================================
    def enforce_kill_switch(self, bot_storage, grid_bot_service) -> Dict[str, Any]:
        """
        Pause all bots and cancel non-reducing orders when kill-switch triggers.

        Args:
            bot_storage: Storage service to list/save bots
            grid_bot_service: Grid service to cancel opening orders

        Returns:
            Dict with enforcement details
        """
        state = self._read_state()
        if not state.get("kill_switch_triggered"):
            return {"enforced": False, "reason": "not_triggered"}
        if state.get("kill_switch_enforced"):
            return {"enforced": False, "reason": "already_enforced"}

        paused_bots = []
        cancel_errors = []

        try:
            bots = bot_storage.list_bots()
        except Exception as e:
            logger.error(f"Kill-switch enforcement failed: cannot list bots ({e})")
            return {"enforced": False, "reason": "list_bots_failed"}

        for bot in bots:
            bot_id = bot.get("id")
            symbol = bot.get("symbol")
            status = bot.get("status")

            # Pause any bot that could place orders
            if status in ("running", "recovering", "paused"):
                bot["status"] = "paused"
                bot["auto_stop_paused"] = True
                bot["reduce_only_mode"] = True
                bot_storage.save_bot(bot)
                if bot_id:
                    paused_bots.append(bot_id)

            # Cancel opening (non-reduce-only) orders to avoid new exposure
            if symbol:
                try:
                    grid_bot_service._cancel_non_reducing_bot_orders(bot, symbol)
                except Exception as ce:
                    logger.warning(
                        f"[{symbol}] Kill-switch cancel opening orders failed: {ce}"
                    )
                    cancel_errors.append(symbol)

        state["kill_switch_enforced"] = True
        self._write_state(state)
        logger.warning(
            "Kill-switch enforcement complete: paused %d bots, cancel_errors=%d",
            len(paused_bots),
            len(cancel_errors),
        )
        return {
            "enforced": True,
            "paused_bots": paused_bots,
            "cancel_errors": cancel_errors,
        }

    def reset_kill_switch(self) -> Dict[str, Any]:
        """
        Clear kill-switch triggered state (manual reset via API).

        Returns:
            Updated risk state
        """
        state = self._read_state()
        self._clear_global_kill_switch_state(state)
        self._write_state(state)
        logger.info("Kill-switch state reset via API")
        return state

    def check_bot_limits(
        self, bot_id: str, bot_realized_pnl: float, bot_capital: float
    ) -> Dict[str, Any]:
        """
        Check per-bot risk limits.

        Args:
            bot_id: Unique identifier for the bot
            bot_realized_pnl: Bot's realized PnL
            bot_capital: Bot's allocated capital

        Returns:
            Dict with risk_stopped status and PnL percentage
        """
        state = self._read_state()

        # Calculate PnL percentage
        if bot_capital > 0:
            bot_pnl_pct = bot_realized_pnl / bot_capital
        else:
            bot_pnl_pct = 0.0

        # Check if bot loss limit breached
        risk_stopped = bot_pnl_pct <= -self.max_bot_loss_pct

        # Update per-bot state
        if "per_bot" not in state:
            state["per_bot"] = {}

        state["per_bot"][bot_id] = {
            "pnl_pct": round(bot_pnl_pct, 6),
            "risk_stopped": risk_stopped,
        }

        self._write_state(state)

        return {"risk_stopped": risk_stopped, "pnl_pct": round(bot_pnl_pct, 6)}

    def reset_daily_state(self, new_start_equity: float = 0.0) -> Dict[str, Any]:
        """
        Reset daily risk tracking state (call at start of new trading day).

        Args:
            new_start_equity: New starting equity (0 to auto-set on next update)

        Returns:
            Updated risk state dictionary
        """
        state = self._read_state()
        state["daily_start_equity"] = new_start_equity
        state["peak_equity"] = new_start_equity
        state["daily_loss_pct"] = 0.0
        state["last_daily_reset"] = datetime.now(timezone.utc).date().isoformat()
        self._clear_global_kill_switch_state(state)
        state["symbol_daily"] = {}
        self._write_state(state)
        return state

    def reset_bot_state(self, bot_id: str) -> None:
        """
        Reset risk state for a specific bot.

        Args:
            bot_id: Unique identifier for the bot
        """
        state = self._read_state()
        if "per_bot" in state and bot_id in state["per_bot"]:
            del state["per_bot"][bot_id]
            self._write_state(state)

    def record_symbol_trade(
        self, symbol: str, realized_pnl: float, trade_time_iso: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record realized PnL for a symbol in today's risk namespace.
        H3 audit: Uses atomic _read_modify_write to prevent TOCTOU race.
        """
        symbol = (symbol or "").upper()
        if not symbol:
            return {}

        trade_day = self._today_iso()
        if trade_time_iso:
            try:
                trade_day = (
                    datetime.fromisoformat(str(trade_time_iso).replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    .date()
                    .isoformat()
                )
            except (TypeError, ValueError):
                trade_day = self._today_iso()

        _result_entry = {}

        def _modifier(state):
            nonlocal _result_entry
            state = self._reset_daily_namespaces_if_needed(state)
            if state.get("last_daily_reset") != trade_day and trade_day != self._today_iso():
                return state
            symbol_daily = state.setdefault("symbol_daily", {})
            entry = symbol_daily.get(symbol) or {
                "realized_pnl": 0.0,
                "loss_abs": 0.0,
                "trade_count": 0,
                "triggered": False,
                "triggered_at": None,
                "last_trade_at": None,
            }
            pnl_value = float(realized_pnl or 0.0)
            entry["realized_pnl"] = round(float(entry.get("realized_pnl", 0.0)) + pnl_value, 8)
            if pnl_value < 0:
                entry["loss_abs"] = round(float(entry.get("loss_abs", 0.0)) + abs(pnl_value), 8)
            else:
                entry["loss_abs"] = round(float(entry.get("loss_abs", 0.0)), 8)
            entry["trade_count"] = int(entry.get("trade_count", 0) or 0) + 1
            entry["last_trade_at"] = trade_time_iso or datetime.now(timezone.utc).isoformat()
            symbol_daily[symbol] = entry
            _result_entry = entry
            return state

        self._read_modify_write(_modifier)
        return _result_entry

    def rebuild_symbol_daily_from_logs(self, trade_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Rebuild today's per-symbol realized PnL state from trade logs.
        """
        state = self._read_state()
        today = self._today_iso()
        rebuilt: Dict[str, Dict[str, Any]] = {}
        for log in trade_logs or []:
            symbol = (log.get("symbol") or "").upper()
            if not symbol:
                continue
            time_iso = log.get("time")
            try:
                trade_day = (
                    datetime.fromisoformat(str(time_iso).replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    .date()
                    .isoformat()
                )
            except (TypeError, ValueError):
                continue
            if trade_day != today:
                continue
            pnl_value = float(log.get("realized_pnl") or 0.0)
            entry = rebuilt.setdefault(
                symbol,
                {
                    "realized_pnl": 0.0,
                    "loss_abs": 0.0,
                    "trade_count": 0,
                    "triggered": False,
                    "triggered_at": None,
                    "last_trade_at": None,
                },
            )
            entry["realized_pnl"] = round(entry["realized_pnl"] + pnl_value, 8)
            if pnl_value < 0:
                entry["loss_abs"] = round(entry["loss_abs"] + abs(pnl_value), 8)
            entry["trade_count"] += 1
            entry["last_trade_at"] = time_iso

        state["symbol_daily"] = rebuilt
        state["last_daily_reset"] = today
        self._write_state(state)
        return rebuilt

    def get_symbol_daily_state(self, symbol: Optional[str] = None) -> Any:
        state = self._reset_daily_namespaces_if_needed(self._read_state())
        symbol_daily = state.get("symbol_daily") or {}
        if symbol:
            return symbol_daily.get(str(symbol).upper(), {})
        return symbol_daily

    def check_symbol_daily_loss(self, symbol: str, loss_limit_usdt: float) -> Dict[str, Any]:
        """H3 audit: uses atomic _read_modify_write to eliminate TOCTOU race."""
        symbol = (symbol or "").upper()
        limit_value = max(float(loss_limit_usdt or 0.0), 0.0)
        _result_snapshot = {}

        def _modifier(state):
            nonlocal _result_snapshot
            state = self._reset_daily_namespaces_if_needed(state)
            symbol_daily = state.setdefault("symbol_daily", {})
            entry = symbol_daily.get(symbol) or {
                "realized_pnl": 0.0,
                "loss_abs": 0.0,
                "trade_count": 0,
                "triggered": False,
                "triggered_at": None,
                "last_trade_at": None,
            }
            triggered = bool(
                limit_value > 0
                and float(entry.get("loss_abs", 0.0) or 0.0) >= limit_value
            )
            if triggered and not entry.get("triggered"):
                entry["triggered"] = True
                entry["triggered_at"] = datetime.now(timezone.utc).isoformat()
                symbol_daily[symbol] = entry
            _result_snapshot = {
                "symbol": symbol,
                "triggered": bool(entry.get("triggered") or triggered),
                "loss_abs": float(entry.get("loss_abs", 0.0) or 0.0),
                "realized_pnl": float(entry.get("realized_pnl", 0.0) or 0.0),
                "trade_count": int(entry.get("trade_count", 0) or 0),
                "triggered_at": entry.get("triggered_at"),
                "loss_limit_usdt": limit_value,
            }
            return state

        self._read_modify_write(_modifier)
        return _result_snapshot

    def get_state(self) -> Dict[str, Any]:
        """
        Get current risk state.

        Returns:
            Current risk state dictionary
        """
        return self._read_state()

    def validate_new_bot(
        self,
        symbol: str,
        planned_investment: float,
        planned_leverage: float,
        account_equity: float,
        existing_bots: List[Dict[str, Any]],
        max_risk_per_bot_pct: float = 0.10,
        max_capital_per_symbol_pct: float = 0.25,
        max_capital_per_symbol_usdt: float = 0,
        max_bots_per_symbol: int = 0,
        max_symbol_share_pct: float = 0.30,
        max_concurrent_symbols: int = 0,
        max_concurrent_bots: int = 0,
        exclude_bot_id: Optional[str] = None,
        enforce_single_symbol: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate whether a new bot can be opened without violating risk limits.
        Implements comprehensive pre-launch checks from mytrading parity.

        Args:
            symbol: Trading symbol for the new bot
            planned_investment: Planned investment in USDT
            planned_leverage: Planned leverage multiplier
            account_equity: Current account equity in USDT
            existing_bots: List of all existing bot dictionaries
            max_risk_per_bot_pct: Max % of equity per bot (e.g., 0.10 = 10%)
            max_capital_per_symbol_pct: Max % of equity per symbol (e.g., 0.25 = 25%)
            max_capital_per_symbol_usdt: Absolute USDT cap per symbol (0 = disabled)
            max_bots_per_symbol: Max concurrent bots per symbol (0 = disabled)
            max_symbol_share_pct: Max % of total bot notional for one symbol (0.30 = 30%)
            max_concurrent_symbols: Max different symbols (0 = unlimited)
            max_concurrent_bots: Max total running bots (0 = unlimited)

        Returns:
            Dict with:
            - allowed: bool (True if validation passed)
            - reasons: List[str] (rejection reasons if any)
            - checks: Dict with detailed check results
        """
        reasons = []
        checks = {}

        # Filter for running bots only
        running_bots = [
            b
            for b in existing_bots
            if b.get("status") == "running" and b.get("id") != exclude_bot_id
        ]

        # Calculate planned notional exposure
        planned_notional = planned_investment * planned_leverage

        # =====================================================================
        # CHECK 1: Risk per bot % (bot capital vs account equity)
        # =====================================================================
        if account_equity > 0:
            risk_pct = planned_notional / account_equity
            checks["risk_per_bot_pct"] = round(risk_pct, 4)

            if max_risk_per_bot_pct > 0 and risk_pct > max_risk_per_bot_pct:
                reasons.append(
                    f"bot_capital_pct_too_high: {risk_pct * 100:.2f}% > {max_risk_per_bot_pct * 100:.2f}% limit"
                )
        else:
            checks["risk_per_bot_pct"] = 0.0

        # =====================================================================
        # CHECK 2: Per-symbol exposure % (all bots on this symbol vs equity)
        # =====================================================================
        symbol_bots = [b for b in running_bots if b.get("symbol") == symbol]
        existing_symbol_exposure = sum(
            b.get("investment", 0) * b.get("leverage", 1) for b in symbol_bots
        )
        total_symbol_exposure = existing_symbol_exposure + planned_notional

        if account_equity > 0:
            symbol_exposure_pct = total_symbol_exposure / account_equity
            checks["symbol_exposure_pct"] = round(symbol_exposure_pct, 4)

            if (
                max_capital_per_symbol_pct > 0
                and symbol_exposure_pct > max_capital_per_symbol_pct
            ):
                reasons.append(
                    f"symbol_exposure_too_high: {symbol_exposure_pct * 100:.2f}% > {max_capital_per_symbol_pct * 100:.2f}% limit for {symbol}"
                )
        else:
            checks["symbol_exposure_pct"] = 0.0

        # =====================================================================
        # CHECK 3: Per-symbol USDT cap (absolute dollar limit)
        # =====================================================================
        if max_capital_per_symbol_usdt > 0:
            checks["symbol_exposure_usdt"] = round(total_symbol_exposure, 2)

            if total_symbol_exposure > max_capital_per_symbol_usdt:
                reasons.append(
                    f"symbol_usdt_cap_exceeded: ${total_symbol_exposure:.2f} > ${max_capital_per_symbol_usdt:.2f} limit for {symbol}"
                )

        # =====================================================================
        # CHECK 4: Max bots per symbol
        # =====================================================================
        if max_bots_per_symbol > 0:
            symbol_bot_count = len(symbol_bots)
            checks["bots_on_symbol"] = symbol_bot_count

            if symbol_bot_count >= max_bots_per_symbol:
                reasons.append(
                    f"max_bots_per_symbol_reached: {symbol_bot_count} bots already on {symbol} (limit: {max_bots_per_symbol})"
                )

        if enforce_single_symbol and symbol_bots:
            reasons.append(
                f"single_running_bot_per_symbol: {symbol} already has a running bot"
            )

        # =====================================================================
        # CHECK 5: Symbol share of total portfolio
        # (one symbol shouldn't dominate all bot exposure)
        # =====================================================================
        total_bot_notional = sum(
            b.get("investment", 0) * b.get("leverage", 1) for b in running_bots
        )
        total_bot_notional_after = total_bot_notional + planned_notional

        if total_bot_notional_after > 0:
            symbol_share = total_symbol_exposure / total_bot_notional_after
            checks["symbol_share_of_portfolio"] = round(symbol_share, 4)

            if symbol_share > max_symbol_share_pct:
                reasons.append(
                    f"symbol_share_too_high: {symbol} would be {symbol_share * 100:.2f}% of portfolio (limit: {max_symbol_share_pct * 100:.2f}%)"
                )
        else:
            checks["symbol_share_of_portfolio"] = 0.0

        # =====================================================================
        # CHECK 6: Max concurrent symbols (portfolio diversification)
        # =====================================================================
        if max_concurrent_symbols > 0:
            unique_symbols = set(b.get("symbol") for b in running_bots)
            unique_symbols.add(symbol)  # Include new symbol
            checks["concurrent_symbols"] = len(unique_symbols)

            if len(unique_symbols) > max_concurrent_symbols:
                reasons.append(
                    f"max_concurrent_symbols_exceeded: {len(unique_symbols)} symbols > {max_concurrent_symbols} limit"
                )

        # =====================================================================
        # CHECK 7: Max concurrent bots (total bot count)
        # =====================================================================
        if max_concurrent_bots > 0:
            running_bot_count = len(running_bots)
            checks["concurrent_bots"] = running_bot_count

            if running_bot_count >= max_concurrent_bots:
                reasons.append(
                    f"max_concurrent_bots_reached: {running_bot_count} bots running (limit: {max_concurrent_bots})"
                )

        # Final verdict
        allowed = len(reasons) == 0

        # 001-trading-bot-audit T073: Log validation failures for visibility
        if not allowed:
            logger.warning(
                "VALIDATE_NEW_BOT symbol=%s allowed=%s reasons=%s checks=%s",
                symbol,
                allowed,
                reasons,
                checks,
            )

        return {"allowed": allowed, "reasons": reasons, "checks": checks}
