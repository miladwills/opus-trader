"""
Guardian Service — Self-Healing Bot Health Monitor

Runs every 60 seconds inside the runner loop. Detects stuck states,
clears stale flags, and auto-fixes common issues that would otherwise
require manual intervention.

30 health checks across 6 categories:
1. Stuck block flags
2. Stuck reconciliation
3. Silent bot detection
4. Position health
5. Cycle health
6. Resource health

Every fix is logged with "GUARDIAN:" prefix for easy monitoring.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Timeouts for stuck state detection (seconds)
BLOCK_FLAG_TIMEOUT = 120
RECONCILIATION_TIMEOUT = 60
SILENT_BOT_TIMEOUT = 300
ENTRY_GATE_STUCK_TIMEOUT = 600
AUTO_PILOT_HOLD_TIMEOUT = 120
FLOW_OPPOSING_MAX = 180
CYCLE_STUCK_TIMEOUT = 300
ERROR_PERSIST_TIMEOUT = 600
CLEANUP_STUCK_TIMEOUT = 300
RECONCILIATION_STALE_TIMEOUT = 3600


class GuardianService:
    """Self-healing health monitor for trading bots."""

    HEALING_LOG_FILE = os.path.join("storage", "guardian_healing_log.json")

    def __init__(self, bot_storage, client=None):
        self.bot_storage = bot_storage
        self.client = client
        self._healing_log: List[Dict[str, Any]] = []
        self._flag_first_seen: Dict[str, Dict[str, float]] = {}  # bot_id → {flag: timestamp}
        self._last_order_sync_at: Dict[str, float] = {}
        self._max_log_entries = 100
        self._load_healing_log()

    def run_health_check(self) -> Dict[str, Any]:
        """Run all health checks on all running bots. Called every ~60s."""
        try:
            bots = self.bot_storage.list_bots()
        except Exception as exc:
            logger.debug("Guardian: failed to read bots: %s", exc)
            return {"checked": 0, "healed": 0}

        healed = 0
        checked = 0
        save_needed = set()

        for bot in bots:
            status = str(bot.get("status") or "").strip().lower()
            bot_id = str(bot.get("id") or "").strip()
            if not bot_id:
                continue

            if status == "running":
                checked += 1
                h = self._check_stuck_flags(bot)
                h += self._check_reconciliation(bot)
                h += self._check_silent_bot(bot)
                h += self._check_position_health(bot)
                h += self._check_cycle_health(bot)
                h += self._check_resource_health(bot)
                if h > 0:
                    healed += h
                    save_needed.add(bot_id)

            elif status == "error":
                h = self._check_error_persist(bot)
                if h > 0:
                    healed += h

            elif status == "stop_cleanup_pending":
                h = self._check_cleanup_stuck(bot)
                if h > 0:
                    healed += h
                    save_needed.add(bot_id)

        # Save healed bots
        for bot in bots:
            if bot.get("id") in save_needed:
                try:
                    self.bot_storage.save_bot(bot)
                except Exception:
                    pass

        # --- Phase 6/7: Connectivity & rate limit (system-level, not per-bot) ---
        self._check_connectivity_and_rate_limit()

        # --- Phase 10: Storage health (every 5th invocation ~300s) ---
        self._storage_check_counter = getattr(self, "_storage_check_counter", 0) + 1
        if self._storage_check_counter >= 5:
            self._storage_check_counter = 0
            self._check_storage_health()

        if healed > 0:
            logger.info("GUARDIAN: %d heal(s) applied across %d running bots", healed, checked)
            self._persist_healing_log()

        return {"checked": checked, "healed": healed}

    def get_healing_log(self) -> List[Dict[str, Any]]:
        """Get recent healing events for dashboard display."""
        return list(self._healing_log[-50:])

    def _load_healing_log(self) -> None:
        try:
            with open(self.HEALING_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._healing_log = data[-self._max_log_entries:]
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _persist_healing_log(self) -> None:
        try:
            with open(self.HEALING_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._healing_log[-self._max_log_entries:], f)
        except Exception:
            pass

    def _log_heal(self, bot: Dict[str, Any], category: str, detail: str) -> None:
        symbol = bot.get("symbol", "?")
        bot_id = str(bot.get("id") or "?")[:8]
        entry = {
            "ts": time.time(),
            "at": datetime.now(timezone.utc).isoformat(),
            "bot_id": bot.get("id"),
            "symbol": symbol,
            "category": category,
            "detail": detail,
        }
        self._healing_log.append(entry)
        if len(self._healing_log) > self._max_log_entries:
            self._healing_log = self._healing_log[-self._max_log_entries:]
        logger.warning("GUARDIAN: [%s:%s] %s — %s", symbol, bot_id, category, detail)

    def _flag_age(self, bot_id: str, flag: str) -> float:
        """Get how long a flag has been seen as True (seconds)."""
        bot_flags = self._flag_first_seen.setdefault(bot_id, {})
        first = bot_flags.get(flag)
        if first is None:
            bot_flags[flag] = time.time()
            return 0.0
        return time.time() - first

    def _clear_flag_tracking(self, bot_id: str, flag: str) -> None:
        bot_flags = self._flag_first_seen.get(bot_id, {})
        bot_flags.pop(flag, None)

    # =====================================================================
    # Category 1: Stuck Block Flags
    # =====================================================================
    def _check_stuck_flags(self, bot: Dict[str, Any]) -> int:
        healed = 0
        bot_id = bot.get("id", "")
        flags = [
            ("_capital_starved_block_opening_orders", BLOCK_FLAG_TIMEOUT),
            ("_small_capital_block_opening_orders", BLOCK_FLAG_TIMEOUT),
            ("_breakout_invalidation_block_opening_orders", 180),
            ("_nlp_block_opening_orders", BLOCK_FLAG_TIMEOUT),
            ("position_assumption_stale", 60),
            ("order_assumption_stale", 60),
        ]
        for flag, timeout in flags:
            if bot.get(flag):
                age = self._flag_age(bot_id, flag)
                if age >= timeout:
                    bot.pop(flag, None)
                    self._clear_flag_tracking(bot_id, flag)
                    self._log_heal(bot, "stuck_flag", f"Cleared {flag} after {age:.0f}s")
                    healed += 1
            else:
                self._clear_flag_tracking(bot_id, flag)

        # _block_opening_orders — only clear if NOT from UPnL SL
        if bot.get("_block_opening_orders") and not bot.get("_upnl_stoploss_reason"):
            age = self._flag_age(bot_id, "_block_opening_orders")
            if age >= 180:
                bot["_block_opening_orders"] = False
                self._clear_flag_tracking(bot_id, "_block_opening_orders")
                self._log_heal(bot, "stuck_flag", f"Cleared _block_opening_orders after {age:.0f}s")
                healed += 1
        elif not bot.get("_block_opening_orders"):
            self._clear_flag_tracking(bot_id, "_block_opening_orders")

        # _stall_overlay — longer timeout
        if bot.get("_stall_overlay_block_opening_orders"):
            age = self._flag_age(bot_id, "_stall_overlay_block_opening_orders")
            if age >= 300:
                bot["_stall_overlay_block_opening_orders"] = False
                self._clear_flag_tracking(bot_id, "_stall_overlay_block_opening_orders")
                self._log_heal(bot, "stuck_flag", f"Cleared stall overlay after {age:.0f}s")
                healed += 1
        else:
            self._clear_flag_tracking(bot_id, "_stall_overlay_block_opening_orders")

        # Stale _profit_lock_closed_this_cycle (should clear every cycle)
        if bot.get("_profit_lock_closed_this_cycle"):
            bot.pop("_profit_lock_closed_this_cycle", None)
            healed += 1

        return healed

    # =====================================================================
    # Category 2: Stuck Reconciliation
    # =====================================================================
    def _check_reconciliation(self, bot: Dict[str, Any]) -> int:
        healed = 0
        bot_id = bot.get("id", "")
        reconcile = bot.get("exchange_reconciliation")

        if isinstance(reconcile, dict):
            status = str(reconcile.get("status") or "").lower()
            if status in ("diverged", "error_with_exchange_persist_divergence"):
                age = self._flag_age(bot_id, "reconciliation_diverged")
                if age >= RECONCILIATION_TIMEOUT:
                    reconcile["status"] = "guardian_auto_resolved"
                    reconcile["mismatches"] = []
                    bot["exchange_reconciliation"] = reconcile
                    self._clear_flag_tracking(bot_id, "reconciliation_diverged")
                    self._log_heal(bot, "reconciliation", f"Auto-resolved diverged after {age:.0f}s")
                    healed += 1
            else:
                self._clear_flag_tracking(bot_id, "reconciliation_diverged")

            # Stale reconciliation (>1 hour old)
            updated_at = str(reconcile.get("updated_at") or "").strip()
            if updated_at and status not in ("in_sync", "guardian_auto_resolved", "auto_resolved_stale"):
                try:
                    ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
                    if time.time() - ts > RECONCILIATION_STALE_TIMEOUT:
                        bot["exchange_reconciliation"] = None
                        self._log_heal(bot, "reconciliation", f"Cleared stale reconciliation ({(time.time()-ts)/60:.0f}min old)")
                        healed += 1
                except Exception:
                    pass

        # Profit protection blocked with no reason or stale reason
        if bot.get("profit_protection_blocked"):
            reason = str(bot.get("profit_protection_blocked_reason") or "").lower()
            if reason == "reconciliation_diverged":
                age = self._flag_age(bot_id, "pp_blocked_reconcil")
                if age >= RECONCILIATION_TIMEOUT:
                    bot["profit_protection_blocked"] = False
                    bot["profit_protection_blocked_reason"] = None
                    bot["profit_protection_blocked_detail"] = None
                    self._clear_flag_tracking(bot_id, "pp_blocked_reconcil")
                    self._log_heal(bot, "reconciliation", f"Cleared PP blocked (reconcil) after {age:.0f}s")
                    healed += 1
            elif not reason:
                bot["profit_protection_blocked"] = False
                self._log_heal(bot, "reconciliation", "Cleared PP blocked with no reason")
                healed += 1
        else:
            self._clear_flag_tracking(bot_id, "pp_blocked_reconcil")

        return healed

    # =====================================================================
    # Category 3: Silent Bot Detection
    # =====================================================================
    def _check_silent_bot(self, bot: Dict[str, Any]) -> int:
        healed = 0
        bot_id = bot.get("id", "")
        orders = int(bot.get("open_order_count") or 0)

        if orders == 0:
            age = self._flag_age(bot_id, "silent_no_orders")
            if age >= SILENT_BOT_TIMEOUT:
                # Clear ALL block flags
                for flag in (
                    "_capital_starved_block_opening_orders",
                    "_small_capital_block_opening_orders",
                    "_block_opening_orders",
                    "_nlp_block_opening_orders",
                    "_stall_overlay_block_opening_orders",
                    "_breakout_invalidation_block_opening_orders",
                    "position_assumption_stale",
                    "order_assumption_stale",
                ):
                    bot.pop(flag, None)
                bot["profit_protection_blocked"] = False
                bot["exchange_reconciliation"] = None
                self._clear_flag_tracking(bot_id, "silent_no_orders")
                self._log_heal(bot, "silent_bot", f"Bot silent for {age:.0f}s with 0 orders — cleared all blocks")
                healed += 1
        else:
            self._clear_flag_tracking(bot_id, "silent_no_orders")

        # Entry gate stuck for too long
        if bot.get("_entry_gate_blocked"):
            age = self._flag_age(bot_id, "gate_stuck")
            if age >= ENTRY_GATE_STUCK_TIMEOUT:
                bot["_entry_gate_blocked"] = False
                bot.pop("_entry_gate_blocked_until", None)
                bot.pop("_entry_gate_blocked_reason", None)
                self._clear_flag_tracking(bot_id, "gate_stuck")
                self._log_heal(bot, "silent_bot", f"Force-cleared entry gate after {age:.0f}s")
                healed += 1
        else:
            self._clear_flag_tracking(bot_id, "gate_stuck")

        # Auto-Pilot stuck on placeholder
        if bot.get("auto_pilot") and str(bot.get("symbol") or "").strip().lower() == "auto-pilot":
            age = self._flag_age(bot_id, "autopilot_placeholder")
            if age >= AUTO_PILOT_HOLD_TIMEOUT:
                self._clear_flag_tracking(bot_id, "autopilot_placeholder")
                self._log_heal(bot, "silent_bot", f"Auto-Pilot stuck on placeholder for {age:.0f}s")
                healed += 1
        else:
            self._clear_flag_tracking(bot_id, "autopilot_placeholder")

        # Auto-Pilot entry hold stuck
        if bot.get("_auto_pilot_entry_hold"):
            age = self._flag_age(bot_id, "autopilot_hold")
            if age >= AUTO_PILOT_HOLD_TIMEOUT:
                bot["_auto_pilot_entry_hold"] = False
                bot.pop("_auto_pilot_entry_hold_until", None)
                self._clear_flag_tracking(bot_id, "autopilot_hold")
                self._log_heal(bot, "silent_bot", f"Released Auto-Pilot entry hold after {age:.0f}s")
                healed += 1
        else:
            self._clear_flag_tracking(bot_id, "autopilot_hold")

        return healed

    # =====================================================================
    # Category 4: Position Health
    # =====================================================================
    def _check_position_health(self, bot: Dict[str, Any]) -> int:
        healed = 0

        # Auto-margin drain warning
        state = bot.get("auto_margin_state") or {}
        total_added = float(state.get("total_added_usdt") or 0)
        investment = float(bot.get("investment") or 0)
        if investment > 0 and total_added > investment * 0.5:
            self._log_heal(bot, "position_health",
                f"AUTO-MARGIN DRAIN: ${total_added:.2f} added ({total_added/investment*100:.0f}% of investment)")

        # Trailing TP active but no position
        if bot.get("_trailing_tp_active") and not float(bot.get("current_position_size") or 0):
            bot["_trailing_tp_active"] = False
            bot.pop("_trailing_tp_peak_pnl", None)
            bot.pop("_trailing_tp_stop_pnl", None)
            self._log_heal(bot, "position_health", "Cleared stale trailing TP (no position)")
            healed += 1

        # Flow opposing timer stuck
        opposing_since = float(bot.get("_flow_opposing_since") or 0)
        if opposing_since > 0 and time.time() - opposing_since > FLOW_OPPOSING_MAX:
            bot["_flow_opposing_since"] = 0
            bot["_flow_opposing_flicker"] = 0
            self._log_heal(bot, "position_health",
                f"Reset flow opposing timer after {time.time()-opposing_since:.0f}s — loss cut may be stuck")
            healed += 1

        # Auto-margin state with no position on exchange
        if state.get("total_added_usdt") and not float(bot.get("current_position_size") or 0):
            bot["auto_margin_state"] = {}
            self._log_heal(bot, "position_health", "Reset auto-margin state (no position)")
            healed += 1

        return healed

    # =====================================================================
    # Category 5: Cycle Health
    # =====================================================================
    def _check_cycle_health(self, bot: Dict[str, Any]) -> int:
        healed = 0

        # last_run_at too old
        last_run = str(bot.get("last_run_at") or "").strip()
        if last_run:
            try:
                ts = datetime.fromisoformat(last_run.replace("Z", "+00:00")).timestamp()
                age = time.time() - ts
                if age > CYCLE_STUCK_TIMEOUT:
                    self._log_heal(bot, "cycle_health",
                        f"CRITICAL: Bot cycle hasn't run for {age:.0f}s — may be stuck")
            except Exception:
                pass

        # _cycle_count overflow
        cycle_count = int(bot.get("_cycle_count") or 0)
        if cycle_count > 10000:
            bot["_cycle_count"] = 0
            healed += 1

        # mode_policy inconsistency
        if bot.get("mode_policy") is None and bot.get("auto_direction"):
            bot["mode_policy"] = "locked"
            self._log_heal(bot, "cycle_health", "Fixed mode_policy=None with auto_direction=True → locked")
            healed += 1

        return healed

    # =====================================================================
    # Category 6: Resource Health
    # =====================================================================
    def _check_resource_health(self, bot: Dict[str, Any]) -> int:
        healed = 0

        # Count True-valued underscore flags
        true_flags = sum(1 for k, v in bot.items() if k.startswith("_") and v is True)
        if true_flags > 20:
            self._log_heal(bot, "resource_health",
                f"Bot has {true_flags} active underscore flags — possible state bloat")

        # --- Phase 1: Order starvation auto-clear ---
        failures = int(bot.get("_consecutive_order_failures") or 0)
        if failures > 0:
            last_fail_at = float(bot.get("_last_order_failure_at") or 0)
            age = time.time() - last_fail_at if last_fail_at > 0 else 0
            if age > 300:
                # No failure for 5 min — bot recovered on its own
                bot["_consecutive_order_failures"] = 0
                bot.pop("_last_order_failure_reason", None)
                bot.pop("_last_order_failure_at", None)
                if bot.get("_order_starvation_block"):
                    bot["_order_starvation_block"] = False
                    bot["_block_opening_orders"] = False
                self._log_heal(bot, "order_starvation",
                    f"Cleared {failures} consecutive failures (idle {age:.0f}s)")
                healed += 1
            elif bot.get("_order_starvation_block") and age > 120:
                # Blocked for 120s — auto-heal to prevent permanent lockout
                bot["_order_starvation_block"] = False
                bot["_block_opening_orders"] = False
                bot["_consecutive_order_failures"] = 0
                self._log_heal(bot, "order_starvation",
                    f"Auto-healed starvation block after {age:.0f}s (was {failures} failures)")
                healed += 1

        # --- Phase 3: SL rejection auto-clear ---
        sl_rej = int(bot.get("_sl_rejection_count") or 0)
        if sl_rej > 0:
            sl_rej_at = float(bot.get("_sl_last_rejection_at") or 0)
            sl_age = time.time() - sl_rej_at if sl_rej_at > 0 else 0
            if sl_age > 300:
                bot["_sl_rejection_count"] = 0
                bot.pop("_sl_last_rejection_at", None)
                bot.pop("_sl_last_rejection_reason", None)
                self._log_heal(bot, "sl_health",
                    f"Cleared {sl_rej} SL rejections (idle {sl_age:.0f}s)")
                healed += 1
            elif sl_rej >= 3 and sl_age > 120:
                self._log_heal(bot, "sl_health",
                    f"CRITICAL: {sl_rej} SL rejections for {sl_age:.0f}s — position may lack SL protection")

        # --- Phase 4: Ambiguous escalation check ---
        marker = dict(bot.get("ambiguous_execution_follow_up") or {})
        if marker.get("pending"):
            created_ts = 0.0
            try:
                raw = marker.get("created_at")
                if raw:
                    from datetime import datetime as _dt, timezone as _tz
                    created_ts = _dt.fromisoformat(
                        str(raw).replace("Z", "+00:00")
                    ).timestamp()
            except Exception:
                pass
            if created_ts > 0:
                age = time.time() - created_ts
                if age > 300:
                    self._log_heal(bot, "ambiguous_escalation",
                        f"Ambiguous follow-up pending {age:.0f}s — escalation active")

        # --- Phase 8: Orphaned order accumulation ---
        reconcile = dict(bot.get("exchange_reconciliation") or {})
        mismatches = list(reconcile.get("mismatches") or [])
        orphan_count = sum(
            1 for m in mismatches
            if (isinstance(m, str) and "orphan" in m.lower())
            or (isinstance(m, dict) and "orphan" in str(m.get("type") or "").lower())
        )
        if orphan_count > 0:
            bot_id = str(bot.get("id") or "")
            orphan_key = f"orphan_accumulation:{bot_id}"
            orphan_age = self._flag_age(bot_id, orphan_key)
            if orphan_count >= 10:
                self._log_heal(bot, "orphan_accumulation",
                    f"ERROR: {orphan_count} orphaned orders/positions detected")
            elif orphan_age > 180:
                self._log_heal(bot, "orphan_accumulation",
                    f"Persistent orphaned items ({orphan_count}) for {orphan_age:.0f}s")
        else:
            bot_id = str(bot.get("id") or "")
            self._clear_flag_tracking(bot_id, f"orphan_accumulation:{bot_id}")

        # --- Phase 9: Cycle SLA breach ---
        cycle_dur = float(bot.get("_last_cycle_duration_sec") or 0)
        breach_count = int(bot.get("_cycle_sla_breach_count") or 0)
        from config.strategy_config import CYCLE_SLA_BREACH_ALERT_COUNT
        if breach_count >= CYCLE_SLA_BREACH_ALERT_COUNT:
            self._log_heal(bot, "cycle_sla",
                f"Cycle SLA breached {breach_count} times (last={cycle_dur:.1f}s)")
            bot["_cycle_sla_breach_count"] = 0
            healed += 1

        return healed

    # =====================================================================
    # Non-running bot checks
    # =====================================================================
    def _check_error_persist(self, bot: Dict[str, Any]) -> int:
        bot_id = bot.get("id", "")
        age = self._flag_age(bot_id, "error_persist")
        if age >= ERROR_PERSIST_TIMEOUT:
            self._log_heal(bot, "error_persist",
                f"Bot in ERROR state for {age:.0f}s: {(bot.get('last_error') or '?')[:60]}")
            self._clear_flag_tracking(bot_id, "error_persist")
        return 0

    def _check_cleanup_stuck(self, bot: Dict[str, Any]) -> int:
        bot_id = bot.get("id", "")
        age = self._flag_age(bot_id, "cleanup_stuck")
        if age >= CLEANUP_STUCK_TIMEOUT:
            bot["status"] = "stopped"
            bot["started_at"] = None
            bot.pop("stop_cleanup_pending", None)
            bot.pop("stop_cleanup_target_status", None)
            self._clear_flag_tracking(bot_id, "cleanup_stuck")
            self._log_heal(bot, "cleanup_stuck",
                f"Force-stopped cleanup_pending after {age:.0f}s")
            return 1
        return 0

    # =====================================================================
    # System-level checks (Phase 6, 7, 10)
    # =====================================================================
    def _check_connectivity_and_rate_limit(self) -> None:
        """Phase 6+7: Check exchange connectivity health and rate limit proximity."""
        if not self.client:
            return
        try:
            # Phase 7: Rate limit utilization
            rate_limiter = getattr(self.client, "rate_limiter", None)
            if rate_limiter:
                with rate_limiter.lock:
                    now = time.time()
                    active = [t for t in rate_limiter.requests if now - t < rate_limiter.window_seconds]
                    utilization = len(active) / max(rate_limiter.max_requests, 1)
                if utilization > 0.95:
                    logger.error("GUARDIAN: Rate limit utilization at %.0f%% — CRITICAL", utilization * 100)
                elif utilization > 0.80:
                    logger.warning("GUARDIAN: Rate limit utilization at %.0f%%", utilization * 100)

            # Phase 6: Connectivity — check latency stats if available
            stats = getattr(self.client, "get_latency_stats", None)
            if callable(stats):
                latency = stats()
                p95 = latency.get("p95_ms", 0)
                error_rate = latency.get("error_rate_pct", 0)
                consecutive_timeouts = latency.get("consecutive_timeouts", 0)
                if consecutive_timeouts >= 5:
                    logger.error(
                        "GUARDIAN: CRITICAL — %d consecutive exchange timeouts", consecutive_timeouts
                    )
                elif p95 > 5000:
                    logger.warning(
                        "GUARDIAN: Exchange latency p95=%.0fms — degraded connectivity", p95
                    )
                elif error_rate > 10:
                    logger.warning(
                        "GUARDIAN: Exchange error rate %.1f%% — connectivity issues", error_rate
                    )
        except Exception:
            pass

    def _check_storage_health(self) -> None:
        """Phase 10: Validate storage file integrity and disk space."""
        bots_file = os.path.join("storage", "bots.json")
        try:
            if os.path.exists(bots_file):
                size = os.path.getsize(bots_file)
                if size > 5 * 1024 * 1024:
                    logger.warning("GUARDIAN: bots.json is %.1fMB — possible state bloat", size / (1024 * 1024))
                # Validate JSON parsability
                with open(bots_file, "r", encoding="utf-8") as f:
                    json.load(f)
        except json.JSONDecodeError as e:
            logger.error("GUARDIAN: CRITICAL — bots.json is corrupted: %s", e)
        except Exception:
            pass

        # Disk space check
        try:
            stat = os.statvfs("storage/")
            available_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
            if available_mb < 100:
                logger.error("GUARDIAN: CRITICAL — disk space %.0fMB remaining", available_mb)
            elif available_mb < 500:
                logger.warning("GUARDIAN: Low disk space — %.0fMB remaining", available_mb)
        except Exception:
            pass
