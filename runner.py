"""
Bybit Control Center - Grid Bot Runner

Background loop that drives all running grid bots.
"""

import os
import time
import logging
import traceback
import re
import zlib
from datetime import datetime, timezone
from typing import Optional

from services.lock_service import acquire_process_lock
from config.config import load_core_config
from config.strategy_config import (
    MAX_BOT_LOSS_PCT,
    MAX_DAILY_LOSS_PCT,
    ENABLE_FLASH_CRASH_PROTECTION,
    FLASH_CRASH_MONITOR_SYMBOL,
    MARGIN_MONITOR_ENABLED,
    # Entry filter (BTC correlation)
    ENABLE_BTC_CORRELATION_FILTER,
    MAX_ALLOWED_CORRELATION_BTC,
    BTC_STRONG_TREND_ADX_THRESHOLD,
    BTC_CORRELATION_LOOKBACK,
    # Stop-loss config
    SL_SAFE_ATR_MULTIPLIER,
    SL_NORMAL_ATR_MULTIPLIER,
    SL_AGGRESSIVE_ATR_MULTIPLIER,
    SL_MIN_DISTANCE_PCT,
    SL_MAX_DISTANCE_PCT,
    # Trend protection config
    TREND_ADX_THRESHOLD,
    TREND_DI_DOMINANCE,
    TREND_RSI_THRESHOLD,
    TREND_MIN_CONFIDENCE_SCORE,
    # Take-profit config
    TP_SAFE_ATR_MULTIPLIER,
    TP_NORMAL_ATR_MULTIPLIER,
    TP_AGGRESSIVE_ATR_MULTIPLIER,
    TP_MIN_DISTANCE_PCT,
    TP_MAX_DISTANCE_PCT,
    # Danger zone config
    DANGER_RSI_OVERBOUGHT,
    DANGER_RSI_OVERSOLD,
    DANGER_VOLUME_SPIKE_MULTIPLIER,
    DANGER_RANGE_EXTREME_PCT,
    # Smart rotation
    ENABLE_SMART_ROTATION,
    ENABLE_LEGACY_ROTATION,
    # Global risk/TP controls
    ENABLE_UPNL_STOPLOSS,
    # Fast risk tick system (NEW - Part 2)
    GRID_TICK_SECONDS,
    RISK_TICK_SECONDS,
    SYMBOL_TRAINING_ENABLED,
)
from services.bybit_client import BybitClient
from services.bybit_stream_service import BybitStreamService
from services.bot_storage_service import BotStorageService
from services.order_ownership_service import OrderOwnershipService
from services.order_router_service import OrderRouterService
from services.pnl_service import PnlService
from services.trade_forensics_service import TradeForensicsService
from services.risk_manager_service import RiskManagerService
from services.grid_engine_service import GridEngineService
from services.range_engine_service import RangeEngineService
from services.grid_bot_service import GridBotService
from services.account_service import AccountService
from services.position_service import PositionService
from services.indicator_service import IndicatorService
from services.flash_crash_service import FlashCrashService
from services.funding_rate_service import FundingRateService
from services.margin_monitor_service import MarginMonitorService
from services.rotation_service import RotationService
from services.hedge_service import HedgeService
from services.neutral_scanner_service import NeutralScannerService
from services.entry_filter_service_v2 import EntryFilterService
from services.stop_loss_service import StopLossService
from services.trend_protection_service import TrendProtectionService
from services.take_profit_service import TakeProfitService
from services.danger_zone_service import DangerZoneService
from services.symbol_training_service import SymbolTrainingService
from services.runtime_settings_service import RuntimeSettingsService
from services.bot_status_service import BotStatusService
from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
from services.private_account_cache_service import PrivateAccountCacheService
from services.performance_baseline_service import PerformanceBaselineService

# Configure logging with both console and file output
# Log file path - can be customized or set via environment variable
LOG_FILE_PATH = os.environ.get("RUNNER_LOG_FILE", os.path.join("storage", "runner.log"))

# Stop flag file - when this file exists, runner will exit gracefully
STOP_FLAG_FILE = os.path.join("storage", "runner.stop")

# Runner lock file - ensures single instance
RUNNER_LOCK_FILE = os.environ.get(
    "RUNNER_LOCK_FILE", os.path.join("storage", "runner.lock")
)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# Track when we last logged errors for stalled bots to avoid spam
STALLED_LOG_COOLDOWN = {}
FULL_CYCLE_ELIGIBLE_STATUSES = {"running", "paused", "recovering", "stop_cleanup_pending"}
ENABLE_BYBIT_STREAMS = os.environ.get("ENABLE_BYBIT_STREAMS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}


def _stream_owner_allows(owner_name: str) -> bool:
    if not ENABLE_BYBIT_STREAMS:
        return False
    configured_owner = os.environ.get("BYBIT_STREAM_OWNER", "runner").strip().lower()
    if configured_owner in {"", "default"}:
        configured_owner = "runner"
    if configured_owner == "none":
        return False
    if configured_owner == "both":
        return True
    return configured_owner == owner_name


def should_process_full_cycle_status(status: str) -> bool:
    """Return True when a bot status still requires the full-cycle dispatcher."""
    return str(status or "").strip().lower() in FULL_CYCLE_ELIGIBLE_STATUSES


def should_run_legacy_rotation(running_bots) -> bool:
    """Legacy runner rotation is opt-in and isolated from GridBotService rotation."""
    return bool(ENABLE_LEGACY_ROTATION and running_bots)


def _parse_iso_ts(value) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def should_expedite_running_bot(bot: dict, now_ts: float | None = None) -> bool:
    if str((bot or {}).get("status") or "").strip().lower() != "running":
        return False
    check_ts = time.time() if now_ts is None else float(now_ts)
    control_ts = max(
        _parse_iso_ts((bot or {}).get("control_updated_at")),
        _parse_iso_ts((bot or {}).get("started_at")),
    )
    if control_ts <= 0.0:
        return False
    if (check_ts - control_ts) > max(float(GRID_TICK_SECONDS or 0), 1.0):
        return False
    last_run_ts = _parse_iso_ts((bot or {}).get("last_run_at"))
    return last_run_ts <= 0.0 or last_run_ts < control_ts


class SymbolColorFormatter(logging.Formatter):
    _LEVEL_NAMES = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    _SYMBOL_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
    _RESET = "\033[0m"
    # Mix of bright/dim foregrounds for better separation
    _COLORS = (
        "\033[1;31m",  # bright red
        "\033[1;32m",  # bright green
        "\033[1;33m",  # bright yellow
        "\033[1;34m",  # bright blue
        "\033[1;35m",  # bright magenta
        "\033[1;36m",  # bright cyan
        "\033[0;91m",  # light red
        "\033[0;92m",  # light green
        "\033[0;93m",  # light yellow
        "\033[0;94m",  # light blue
        "\033[0;95m",  # light magenta
        "\033[0;96m",  # light cyan
        "\033[0;37m",  # gray/white
    )

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)

        highlight = "Running bot cycle" in message or "🤖" in message

        def repl(match: re.Match) -> str:
            token = match.group(1)
            if token in self._LEVEL_NAMES:
                return match.group(0)
            color = self._color_for_symbol(token)
            prefix = "\033[1m" if highlight else ""
            return f"{prefix}{color}[{token}]{self._RESET}"

        return self._SYMBOL_RE.sub(repl, message)

    def _color_for_symbol(self, symbol: str) -> str:
        idx = zlib.crc32(symbol.encode("utf-8")) % len(self._COLORS)
        return self._COLORS[idx]


# Create formatter
log_formatter = logging.Formatter(LOG_FORMAT)

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(SymbolColorFormatter(LOG_FORMAT))
root_logger.addHandler(console_handler)

# File handler (rotating to keep log file manageable)
try:
    from logging.handlers import RotatingFileHandler

    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=1024 * 1024,  # 1 MB max per file
        backupCount=3,  # Keep 3 backup files
        encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
    logging.info("Logging to file: %s", LOG_FILE_PATH)
except Exception as log_file_err:
    logging.warning("Could not set up file logging: %s", log_file_err)


def check_stop_requested():
    """
    Check if a stop has been requested via the stop flag file.

    Returns:
        bool: True if stop is requested, False otherwise
    """
    try:
        if os.path.exists(STOP_FLAG_FILE):
            logging.debug("Stop flag file found: %s", STOP_FLAG_FILE)
            return True
    except Exception as e:
        logging.warning("Error checking stop flag: %s", e)
    return False


def clear_stop_flag():
    """Remove the stop flag file if it exists."""
    try:
        if os.path.exists(STOP_FLAG_FILE):
            os.remove(STOP_FLAG_FILE)
            logging.info("Cleared stop flag file")
    except Exception as e:
        logging.warning("Failed to clear stop flag: %s", e)


def acquire_runner_lock(lock_path: str = RUNNER_LOCK_FILE):
    """
    Acquire a non-blocking exclusive lock to ensure a single runner instance.

    Returns:
        Open file handle if lock acquired, or None if already locked.
    """
    try:
        lock_fd = acquire_process_lock(lock_path)
        if not lock_fd:
            return None

        lock_fd.seek(0)
        lock_fd.truncate()
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except Exception as e:
        logging.error("Failed to acquire runner lock: %s", e)
        return None


def _merge_reconciled_bots_by_id(
    bots: list[dict],
    reconciled_bots: Optional[list[dict]],
) -> list[dict]:
    updates_by_id = {
        str(bot.get("id") or "").strip(): dict(bot)
        for bot in list(reconciled_bots or [])
        if str(bot.get("id") or "").strip()
    }
    if not updates_by_id:
        return list(bots or [])
    merged: list[dict] = []
    for bot in list(bots or []):
        bot_id = str((bot or {}).get("id") or "").strip()
        merged.append(dict(updates_by_id.get(bot_id) or bot))
    return merged


def _run_exchange_truth_reconciliation(
    grid_bot_service,
    bots: list[dict],
    *,
    reason: str,
    force: bool = False,
) -> list[dict]:
    if grid_bot_service is None or not hasattr(grid_bot_service, "reconcile_bots_exchange_truth"):
        return list(bots or [])
    try:
        reconciled = grid_bot_service.reconcile_bots_exchange_truth(
            list(bots or []),
            reason=reason,
            force=force,
        )
    except Exception as exc:
        logging.error("Exchange reconciliation failed during %s: %s", reason, exc)
        logging.debug("Traceback:\n%s", traceback.format_exc())
        return list(bots or [])
    return _merge_reconciled_bots_by_id(list(bots or []), reconciled)


def _startup_reconciliation_targets(bots: list[dict]) -> list[dict]:
    """Return bots that need exchange-truth reconciliation on startup.

    Includes paused/flash_crash_paused bots (M4) because they may have
    stale position/order state after a runner crash.
    """
    targets: list[dict] = []
    for bot in list(bots or []):
        if not isinstance(bot, dict):
            continue
        status = str(bot.get("status") or "").strip().lower()
        if status in {
            "running",
            "error",
            "stop_cleanup_pending",
            "paused",
            "recovering",
            "flash_crash_paused",
        }:
            targets.append(dict(bot))
            continue
        marker = dict(bot.get("ambiguous_execution_follow_up") or {})
        if marker.get("pending"):
            targets.append(dict(bot))
    return targets


def _cancel_orders_on_error(grid_bot_service, bot: dict, symbol: str) -> None:
    """H6: Auto-cancel open orders when a bot transitions to error state.

    Prevents orphaned orders from accumulating on the exchange while the bot
    is halted.  Best-effort — failures are logged but do not propagate.
    """
    if not symbol or not grid_bot_service:
        return
    try:
        is_tradeable = getattr(grid_bot_service, "_is_tradeable_symbol", None)
        if is_tradeable and not is_tradeable(symbol):
            return
        client = getattr(grid_bot_service, "client", None)
        if client and hasattr(client, "cancel_all_orders"):
            cancel_res = client.cancel_all_orders(symbol)
            cancelled = cancel_res.get("cancelled", 0) if isinstance(cancel_res, dict) else 0
            logging.warning(
                "[%s:%s] Auto-cancelled orders on error state (cancelled=%s)",
                symbol,
                str((bot or {}).get("id") or "?")[:6],
                cancelled,
            )
    except Exception as cancel_exc:
        logging.warning(
            "[%s] Failed to auto-cancel orders on error state: %s",
            symbol,
            cancel_exc,
        )
    # Zero internal order counters so the dashboard shows truthful state.
    # Reconciliation confirms the actual exchange state on the next pass.
    if isinstance(bot, dict):
        bot["open_order_count"] = 0
        bot["entry_orders_open"] = 0
        bot["exit_orders_open"] = 0


_AUTO_RESUME_CHECK_STATUSES = {"stopped", "error"}
_last_auto_resume_check_ts = 0.0
_AUTO_RESUME_INTERVAL_SEC = 30.0


def _auto_resume_exposed_bots(grid_bot_service, bot_storage, bots: list[dict]) -> list[dict]:
    """Auto-resume a stopped/error bot that has open positions or orders.

    Safety rules:
    - Never resume risk_stopped bots (stopped for a safety reason)
    - Only resume ONE bot per symbol (most recent started_at wins)
    - Skip symbols that already have a running bot managing them
    """
    global _last_auto_resume_check_ts
    now = time.time()
    if now - _last_auto_resume_check_ts < _AUTO_RESUME_INTERVAL_SEC:
        return bots
    _last_auto_resume_check_ts = now

    client = getattr(grid_bot_service, "client", None)
    if not client:
        return bots

    # Build set of symbols already managed by a running/active bot
    active_symbols = set()
    for bot in bots:
        status = str(bot.get("status") or "").strip().lower()
        if status in {"running", "stop_cleanup_pending", "recovering"}:
            sym = (bot.get("symbol") or "").upper()
            if sym:
                active_symbols.add(sym)

    # Collect candidates — only stopped/error, NOT risk_stopped
    candidates = []
    for bot in bots:
        status = str(bot.get("status") or "").strip().lower()
        if status in _AUTO_RESUME_CHECK_STATUSES:
            sym = (bot.get("symbol") or "").upper()
            if sym and sym not in active_symbols:
                candidates.append(bot)

    if not candidates:
        return bots

    # Deduplicate: only keep ONE bot per symbol (most recently started)
    best_per_symbol: dict[str, dict] = {}
    for bot in candidates:
        sym = (bot.get("symbol") or "").upper()
        if not sym:
            continue
        existing = best_per_symbol.get(sym)
        if existing is None:
            best_per_symbol[sym] = bot
        else:
            bot_started = str(bot.get("started_at") or "")
            existing_started = str(existing.get("started_at") or "")
            if bot_started > existing_started:
                best_per_symbol[sym] = bot

    candidates = list(best_per_symbol.values())
    if not candidates:
        return bots

    # Batch fetch all positions (single API call)
    symbols_with_position = set()
    try:
        pos_resp = client.get_positions(skip_cache=True)
        if pos_resp.get("success"):
            pos_list = (
                (pos_resp.get("result", {}) or pos_resp.get("data", {})).get("list", []) or []
            )
            for p in pos_list:
                sym = (p.get("symbol") or "").upper()
                if sym and float(p.get("size", 0)) > 0:
                    symbols_with_position.add(sym)
    except Exception as exc:
        logging.warning("Auto-resume position check failed: %s", exc)
        return bots

    resumed_any = False
    for bot in candidates:
        symbol = (bot.get("symbol") or "").upper()
        if not symbol:
            continue
        bot_id = str(bot.get("id") or "")[:8]
        has_exposure = symbol in symbols_with_position

        # If no position, check for open orders
        if not has_exposure:
            try:
                ord_resp = client.get_open_orders(symbol=symbol, skip_cache=True)
                if ord_resp.get("success"):
                    orders = ((ord_resp.get("data", {}) or {}).get("list", []) or [])
                    has_exposure = len(orders) > 0
            except Exception:
                pass

        if not has_exposure:
            continue

        old_status = bot.get("status")
        bot["status"] = "running"
        bot["last_error"] = None
        bot["error_code"] = None
        bot["last_warning"] = (
            f"Auto-resumed: exchange has unmanaged positions/orders (was {old_status})"
        )
        bot["_auto_resumed_from_exchange_exposure"] = True
        # Bump control_version so bot_storage accepts the status change
        bot["control_version"] = int(bot.get("control_version") or 0) + 1
        try:
            bot_storage.save_bot(bot)
        except Exception:
            pass
        logging.warning(
            "[%s:%s] AUTO-RESUMED from %s — exchange has unmanaged exposure",
            symbol, bot_id, old_status,
        )
        resumed_any = True

    if resumed_any:
        try:
            bots = list(bot_storage.list_bots() or [])
        except Exception:
            pass

    return bots


def _persist_bot_cycle_exception(bot_storage, grid_bot_service, bot: dict, exc: Exception) -> Optional[dict]:
    """
    Persist an uncaught cycle exception so the same bot does not loop forever in
    a nominally running state.
    """
    bot_id = bot.get("id")
    symbol = bot.get("symbol", "?")
    status = str(bot.get("status") or "").strip().lower()
    if status not in FULL_CYCLE_ELIGIBLE_STATUSES:
        return

    error_message = f"Unhandled bot cycle exception: {type(exc).__name__}: {exc}"

    try:
        persisted_bot = None
        if bot_id and hasattr(bot_storage, "get_bot"):
            persisted_bot = bot_storage.get_bot(bot_id)
        target_bot = dict(persisted_bot or bot)
        current_status = str(target_bot.get("status") or "").strip().lower()
        if current_status not in FULL_CYCLE_ELIGIBLE_STATUSES:
            return

        target_bot["status"] = "error"
        target_bot["last_error"] = error_message
        target_bot["last_run_at"] = datetime.now(timezone.utc).isoformat()
        saved_bot = bot_storage.save_bot(target_bot)

        # H6: Auto-cancel open orders when bot enters error state to prevent
        # orphaned orders accumulating on the exchange while bot is halted.
        _cancel_orders_on_error(grid_bot_service, saved_bot, symbol)

        reconciled = _run_exchange_truth_reconciliation(
            grid_bot_service,
            [saved_bot],
            reason="cycle_exception",
            force=True,
        )
        logging.error("[%s:%s] Persisted bot error state after cycle exception", symbol, (bot_id or "?")[:6])
        return dict(reconciled[0]) if reconciled else dict(saved_bot)
    except Exception as save_exc:
        logging.error(
            "[%s:%s] Failed to persist bot error state after cycle exception: %s",
            symbol,
            (bot_id or "?")[:6],
            save_exc,
        )
    return None


def risk_check_all_bots(bot_storage, grid_bot_service):
    """
    Fast risk tick tasks (runs every RISK_TICK_SECONDS).

    - Fast refill for selected modes (neutral classic/dynamic, scalp_pnl, long, short)
    - UPnL stop-loss fast check (if enabled)

    Args:
        bot_storage: BotStorageService for loading bots
        grid_bot_service: GridBotService with check_upnl_stoploss_fast method
    """
    try:
        bots = bot_storage.list_bots()
        stream_service = getattr(grid_bot_service, "stream_service", None)
        if stream_service:
            # Include symbols from bots that may hold exchange positions,
            # not just running bots.  Error / risk_stopped / cleanup bots
            # can still have open positions that need live market data.
            _position_owner_statuses = {
                "running", "paused", "recovering", "flash_crash_paused",
                "stop_cleanup_pending", "error", "risk_stopped",
            }
            symbols = sorted(
                {
                    str(bot.get("symbol") or "").strip().upper()
                    for bot in bots
                    if bot.get("status") in _position_owner_statuses
                    and str(bot.get("symbol") or "").strip()
                    and str(bot.get("symbol") or "").strip().lower() != "auto-pilot"
                }
            )
            kline_symbols = {
                interval: symbols
                for interval in getattr(
                    stream_service,
                    "DEFAULT_ACTIVE_KLINE_INTERVALS",
                    ("1", "5", "15"),
                )
            }
            stream_service.set_symbol_subscriptions(
                symbols,
                orderbook_symbols=symbols,
                kline_symbols_by_interval=kline_symbols,
            )

        for bot in bots:
            if bot.get("status") != "running":
                continue

            symbol = bot.get("symbol", "?")
            mode = (bot.get("mode") or "").lower()
            ran_fast_refill = False

            try:
                if should_expedite_running_bot(bot):
                    # Guard: skip if already expedited this grid tick window
                    _exp_key = f"{bot.get('id')}:expedited"
                    _exp_ts = STALLED_LOG_COOLDOWN.get(_exp_key, 0)
                    if time.time() - _exp_ts < max(float(GRID_TICK_SECONDS), 2.0):
                        pass  # Already expedited recently — skip
                    else:
                        STALLED_LOG_COOLDOWN[_exp_key] = time.time()
                        logging.info(
                            "[%s] Expedited runner pickup for recent control change",
                            symbol,
                        )
                        bot = grid_bot_service.run_bot_cycle(bot, fast_refill_tick=True)
                        if bot.get("status") != "running":
                            continue

                # 1) Fast refill for supported modes (independent of UPnL SL)
                should_poll_fast_refill = grid_bot_service.should_poll_fast_refill(bot)
                if should_poll_fast_refill:
                    if mode == "neutral_classic_bybit":
                        bot = grid_bot_service.run_neutral_classic_fast_refill(bot)
                        ran_fast_refill = True
                    elif mode == "neutral":
                        bot = grid_bot_service.run_neutral_dynamic_fast_refill(bot)
                        ran_fast_refill = True
                    elif mode == "scalp_pnl":
                        bot = grid_bot_service.run_scalp_pnl_fast_refill(bot)
                        ran_fast_refill = True
                    elif mode == "long":
                        bot = grid_bot_service.run_long_fast_refill(bot)
                        ran_fast_refill = True
                    elif mode == "short":
                        bot = grid_bot_service.run_short_fast_refill(bot)
                        ran_fast_refill = True
                    if ran_fast_refill:
                        grid_bot_service.note_fast_refill_poll(bot)

                # 2) Fast UPnL stop-loss checks (if enabled globally + per bot)
                if not ENABLE_UPNL_STOPLOSS or not bot.get("upnl_stoploss_enabled"):
                    continue

                result = grid_bot_service.check_upnl_stoploss_fast(bot)

                if result.get("action_taken"):
                    action = result.get("action")
                    reason = result.get("reason", "unknown")

                    if action == "hard_close":
                        logging.warning(
                            "[%s] 🛑 FAST RISK: HARD UPnL SL triggered - %s",
                            symbol,
                            reason,
                        )
                    elif action == "soft_block":
                        logging.warning(
                            "[%s] ⚠️ FAST RISK: SOFT UPnL SL triggered - %s",
                            symbol,
                            reason,
                        )

            except Exception as bot_exc:
                logging.error("[%s] Fast risk check error: %s", symbol, bot_exc)

    except Exception as e:
        logging.error("Fast risk check failed: %s", e)


def main():
    """
    Main runner loop:
      - Initialize all required services.
      - Loop forever:
          - Fetch current account equity.
          - Load all bots from storage.
          - For each bot that still needs the cycle dispatcher (`running`,
            `paused`, `recovering`):
              - Run grid_bot_service.run_bot_cycle(bot) inside try/except.
          - Try to sync closed PnL via pnl_service.sync_closed_pnl().
          - Try to update per-bot realized PnL via pnl_service.update_bots_realized_pnl().
          - Sleep a few seconds.
    """
    # Ensure single instance
    runner_lock_fd = acquire_runner_lock()
    if not runner_lock_fd:
        logging.error("Runner already running (lock held). Exiting.")
        return

    # 1) Load config and create client
    cfg = load_core_config()
    client = BybitClient(
        api_key=cfg["api_key"],
        api_secret=cfg["api_secret"],
        base_url=cfg["base_url"],
    )
    order_router = OrderRouterService()
    client.set_order_router(order_router)
    stream_service = None
    private_account_cache_service = None
    runtime_snapshot_bridge = None
    if _stream_owner_allows("runner"):
        try:
            stream_service = BybitStreamService(
                api_key=cfg["api_key"],
                api_secret=cfg["api_secret"],
                base_url=cfg["base_url"],
                owner_name="runner",
            )
            client.set_stream_service(stream_service)
            stream_service.start()
        except Exception as exc:
            logging.warning("Failed to start runner websocket streams: %s", exc)
            stream_service = None

    # 2) Ensure storage directory exists
    os.makedirs("storage", exist_ok=True)

    # 3) Init storage/services
    bots_path = os.path.join("storage", "bots.json")
    pnl_path = os.path.join("storage", "trade_logs.json")
    risk_path = os.path.join("storage", "risk_state.json")

    bot_storage = BotStorageService(bots_path)
    runtime_settings_service = RuntimeSettingsService(
        os.path.join("storage", "runtime_settings.json")
    )
    performance_baseline_service = PerformanceBaselineService(
        file_path=os.path.join("storage", "performance_baselines.json")
    )
    order_ownership_service = OrderOwnershipService(
        os.path.join("storage", "order_ownership.json")
    )
    trade_forensics_service = TradeForensicsService(
        os.path.join("storage", "trade_forensics.jsonl")
    )
    client.set_order_ownership_service(order_ownership_service)
    client.set_trade_forensics_service(trade_forensics_service)
    symbol_training_service = (
        SymbolTrainingService(os.path.join("storage", "training"))
        if SYMBOL_TRAINING_ENABLED
        else None
    )
    risk_manager = RiskManagerService(
        file_path=risk_path,
        max_bot_loss_pct=MAX_BOT_LOSS_PCT,
        max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
    )
    pnl_service = PnlService(
        client,
        pnl_path,
        bot_storage,
        order_ownership_service=order_ownership_service,
        trade_forensics_service=trade_forensics_service,
        risk_manager=risk_manager,
        symbol_training_service=symbol_training_service,
        performance_baseline_service=performance_baseline_service,
    )
    try:
        existing_logs = pnl_service.get_log()
        risk_manager.rebuild_symbol_daily_from_logs(existing_logs)
        if symbol_training_service:
            symbol_training_service.rebuild_from_trade_logs(existing_logs)
    except Exception as exc:
        logging.warning("Failed to rebuild startup risk/training state: %s", exc)
    grid_engine = GridEngineService()
    indicator_service = IndicatorService(client)
    funding_rate_service = FundingRateService(client)

    # Entry filter with BTC correlation support
    entry_filter = EntryFilterService(
        indicator_service=indicator_service,
        enable_btc_filter=ENABLE_BTC_CORRELATION_FILTER,
        max_btc_correlation=MAX_ALLOWED_CORRELATION_BTC,
        btc_strong_adx=BTC_STRONG_TREND_ADX_THRESHOLD,
        btc_lookback=BTC_CORRELATION_LOOKBACK,
    )

    # Stop-loss service (adaptive)
    stop_loss_service = StopLossService(
        bybit_client=client,
        safe_atr_multiplier=SL_SAFE_ATR_MULTIPLIER,
        normal_atr_multiplier=SL_NORMAL_ATR_MULTIPLIER,
        aggressive_atr_multiplier=SL_AGGRESSIVE_ATR_MULTIPLIER,
        min_sl_distance_pct=SL_MIN_DISTANCE_PCT,
        max_sl_distance_pct=SL_MAX_DISTANCE_PCT,
    )

    # Trend protection service
    trend_protection_service = TrendProtectionService(
        adx_trend_threshold=TREND_ADX_THRESHOLD,
        di_dominance_threshold=TREND_DI_DOMINANCE,
        rsi_trend_threshold=TREND_RSI_THRESHOLD,
        min_confidence_score=TREND_MIN_CONFIDENCE_SCORE,
    )

    # Take-profit service (adaptive)
    take_profit_service = TakeProfitService(
        safe_tp_multiplier=TP_SAFE_ATR_MULTIPLIER,
        normal_tp_multiplier=TP_NORMAL_ATR_MULTIPLIER,
        aggressive_tp_multiplier=TP_AGGRESSIVE_ATR_MULTIPLIER,
        min_tp_pct=TP_MIN_DISTANCE_PCT,
        max_tp_pct=TP_MAX_DISTANCE_PCT,
    )

    # Danger zone detection service
    danger_zone_service = DangerZoneService(
        extreme_rsi_upper=DANGER_RSI_OVERBOUGHT,
        extreme_rsi_lower=DANGER_RSI_OVERSOLD,
        volume_spike_multiplier=DANGER_VOLUME_SPIKE_MULTIPLIER,
        range_extreme_threshold_pct=DANGER_RANGE_EXTREME_PCT,
    )

    grid_bot_service = GridBotService(
        client=client,
        bot_storage=bot_storage,
        pnl_service=pnl_service,
        risk_manager=risk_manager,
        grid_engine=grid_engine,
        indicator_service=indicator_service,
        entry_filter=entry_filter,
        stop_loss_service=stop_loss_service,
        trend_protection_service=trend_protection_service,
        take_profit_service=take_profit_service,
        danger_zone_service=danger_zone_service,
        funding_rate_service=funding_rate_service,
        symbol_training_service=symbol_training_service,
        stream_service=stream_service,
        runtime_settings_service=runtime_settings_service,
        trade_forensics_service=trade_forensics_service,
    )
    grid_bot_service.start_event_reactor()
    account_service = AccountService(client)
    position_service = PositionService(client)

    # Order flow analysis service (tick-level trade flow detection)
    from services.order_flow_service import OrderFlowService
    order_flow_service = OrderFlowService()
    if stream_service is not None:
        stream_service.set_order_flow_service(order_flow_service)
        logging.info("Order flow analysis service attached to stream")
    grid_bot_service.order_flow_service = order_flow_service

    # Auto-Pilot performance memory (Tier 3)
    from services.auto_pilot_memory_service import AutoPilotMemoryService
    auto_pilot_memory = AutoPilotMemoryService()
    try:
        auto_pilot_memory.rebuild_from_trade_logs(pnl_service.get_log())
        logging.info("Auto-Pilot memory loaded with %d symbols", len(auto_pilot_memory.get_all_stats()))
    except Exception as mem_exc:
        logging.warning("Auto-Pilot memory init failed: %s", mem_exc)
    grid_bot_service.auto_pilot_memory = auto_pilot_memory

    # Market sentiment service (OI + L/S ratio + funding rate)
    from services.market_sentiment_service import MarketSentimentService
    market_sentiment_service = MarketSentimentService(client)
    grid_bot_service.market_sentiment_service = market_sentiment_service
    logging.info("Market sentiment service attached (OI + L/S ratio + funding)")

    # Guardian service — self-healing bot health monitor (30 checks, 6 categories)
    from services.guardian_service import GuardianService
    guardian_service = GuardianService(bot_storage, client)
    logging.info("Guardian self-healing service initialized (60s interval)")

    # Flash crash protection service (Smart Feature #12)
    flash_crash_service = FlashCrashService(
        indicator_service=indicator_service,
        bot_storage=bot_storage,
    )

    # Margin monitor service (Smart Feature #18) - protects ALL positions
    margin_monitor_service = MarginMonitorService(
        client=client, bot_storage=bot_storage
    )

    # =============================================================================
    # NEW ADVANCED SERVICES (Smart Rotation & Hedging)
    # =============================================================================
    neutral_scanner = NeutralScannerService(client, indicator_service, RangeEngineService())
    grid_bot_service.neutral_scanner = neutral_scanner  # Auto-Pilot needs this
    from services.motion_signal_service import MotionSignalService
    motion_signal_service = MotionSignalService(indicator_service)
    bot_status_service = BotStatusService(
        bot_storage,
        position_service,
        pnl_service,
        neutral_scanner=neutral_scanner,
        indicator_service=indicator_service,
        performance_baseline_service=performance_baseline_service,
        motion_signal_service=motion_signal_service,
    )
    if stream_service is not None:
        private_account_cache_service = PrivateAccountCacheService(
            client=client,
            stream_service=stream_service,
            owner_name="runner",
        )
        private_account_cache_service.start()
    runtime_snapshot_bridge = RuntimeSnapshotBridgeService(
        file_path=os.environ.get(
            "RUNTIME_SNAPSHOT_BRIDGE_FILE",
            os.path.join("storage", "runtime_snapshot_bridge.json"),
        ),
        owner_name="runner",
        write_enabled=True,
        stream_service=stream_service,
        bot_storage=bot_storage,
        account_service=account_service,
        position_service=position_service,
        pnl_service=pnl_service,
        risk_manager=risk_manager,
        bot_status_service=bot_status_service,
        write_interval_sec=2.0,
    )
    runtime_snapshot_bridge.start()
    rotation_service = (
        RotationService(neutral_scanner, bot_storage)
        if ENABLE_LEGACY_ROTATION
        else None
    )
    hedge_service = HedgeService(client)

    logging.info("=" * 60)
    logging.info("Bybit Grid Bot Runner Starting")
    logging.info("Environment: %s", cfg.get("env_label", "Unknown"))
    if ENABLE_SMART_ROTATION:
        logging.info(
            "Auto-Pilot smart rotation active via GridBotService (ENABLE_SMART_ROTATION=1)"
        )
    else:
        logging.info(
            "Auto-Pilot smart rotation disabled in GridBotService (ENABLE_SMART_ROTATION=0)"
        )
    if ENABLE_LEGACY_ROTATION:
        logging.info(
            "Legacy RotationService enabled separately in runner (ENABLE_LEGACY_ROTATION=1)"
        )
    else:
        logging.info(
            "Legacy RotationService disabled in runner (ENABLE_LEGACY_ROTATION=0)"
        )
    logging.info("=" * 60)

    # Clear any existing stop flag from previous run
    clear_stop_flag()

    try:
        startup_bots = _startup_reconciliation_targets(bot_storage.list_bots())
        if startup_bots:
            reconciled_startup_bots = _run_exchange_truth_reconciliation(
                grid_bot_service,
                startup_bots,
                reason="startup",
                force=True,
            )
            if reconciled_startup_bots:
                logging.info(
                    "Startup exchange reconciliation completed for %d bots",
                    len(reconciled_startup_bots),
                )
    except Exception as startup_reconcile_exc:
        logging.error(
            "Startup exchange reconciliation failed: %s",
            startup_reconcile_exc,
        )
        logging.debug("Traceback:\n%s", traceback.format_exc())

    # =============================================================================
    # DUAL-TICK LOOP SYSTEM (NEW - Part 2)
    # =============================================================================
    # Fast risk tick: RISK_TICK_SECONDS (default 1s) - UPnL SL checks only
    # Full grid tick: GRID_TICK_SECONDS (default 10s) - complete bot cycle
    # This allows catching fast market moves while keeping API usage reasonable

    logging.info(
        "Tick intervals: RISK=%ds, GRID=%ds",
        RISK_TICK_SECONDS,
        GRID_TICK_SECONDS,
    )

    next_risk_tick_at = time.monotonic()
    next_grid_tick_at = next_risk_tick_at
    last_heartbeat_ts = 0

    try:
        while True:
            # Check for stop request at the start of each tick
            if check_stop_requested():
                logging.info("🛑 Stop requested via flag file. Exiting gracefully...")
                clear_stop_flag()
                break

            now_monotonic = time.monotonic()
            if now_monotonic < next_risk_tick_at:
                time.sleep(min(next_risk_tick_at - now_monotonic, RISK_TICK_SECONDS))
                continue

            try:
                # =================================================================
                # FAST RISK CHECK (runs every RISK_TICK_SECONDS)
                # =================================================================
                # Lightweight UPnL stop-loss check for all running bots
                risk_check_all_bots(bot_storage, grid_bot_service)
                # =================================================================
                # HEDGE CHECK - DISABLED (was auto-opening unwanted BTCUSDT positions)
                # The HedgeService opens BTCUSDT short positions to neutralize
                # portfolio long exposure. This is NOT desired when running
                # individual bots on specific coins.
                # =================================================================
                # try:
                #     bots_for_hedge = bot_storage.list_bots()
                #     running_bots_hedge = [
                #         b for b in bots_for_hedge if b.get("status") == "running"
                #     ]
                #     hedge_service.check_and_hedge(running_bots_hedge)
                # except Exception as hedge_exc:
                #     logging.error("Hedge check error: %s", hedge_exc)

                now_monotonic = time.monotonic()
                while next_risk_tick_at <= now_monotonic:
                    next_risk_tick_at += RISK_TICK_SECONDS

            except Exception as risk_exc:
                logging.error("Risk tick error: %s", risk_exc)
                next_risk_tick_at = time.monotonic() + RISK_TICK_SECONDS

            # =================================================================
            # FULL GRID CYCLE (runs every GRID_TICK_SECONDS)
            # =================================================================
            now_monotonic = time.monotonic()
            if now_monotonic < next_grid_tick_at:
                continue

            try:
                while next_grid_tick_at <= now_monotonic:
                    next_grid_tick_at += GRID_TICK_SECONDS
                # 4) Get account equity (for tracking)
                overview = account_service.get_overview()
                equity = float(overview.get("equity") or 0.0)

                if overview.get("error"):
                    logging.warning("Account overview error: %s", overview.get("error"))

                # Update risk state (for per-bot risk checks, no global kill-switch)
                risk_manager.update_equity_state(equity)

                # =================================================================
                # GLOBAL KILL-SWITCH ENFORCEMENT (001-trading-bot-audit US5)
                # =================================================================
                try:
                    risk_manager.enforce_kill_switch(bot_storage, grid_bot_service)
                except Exception as kill_exc:
                    logging.error("Kill-switch enforcement failed: %s", kill_exc)
                    logging.debug("Traceback:\n%s", traceback.format_exc())

                # =================================================================
                # FLASH CRASH PROTECTION CHECK (Smart Feature #12)
                # =================================================================
                # Check for flash crash BEFORE processing bots
                # This will pause all bots if a crash is detected, or resume if normalized
                if ENABLE_FLASH_CRASH_PROTECTION:
                    try:
                        flash_result = flash_crash_service.check_and_protect(
                            symbol=FLASH_CRASH_MONITOR_SYMBOL,
                        )
                        action = flash_result.get("action")

                        if action == "triggered":
                            logging.warning(
                                "🚨 FLASH CRASH DETECTED on %s! Paused %d bots.",
                                FLASH_CRASH_MONITOR_SYMBOL,
                                len(flash_result.get("result", {}).get("paused_bots", [])),
                            )
                        elif action == "resumed":
                            logging.info(
                                "✅ Flash crash normalized. Resumed %d bots.",
                                len(flash_result.get("result", {}).get("resumed_bots", [])),
                            )
                        elif action == "still_active":
                            logging.debug(
                                "Flash crash still active, waiting for normalization..."
                            )
                        # For "normal" and "disabled" actions, just continue silently

                    except Exception as flash_exc:
                        logging.warning("Flash crash check failed: %s", flash_exc)
                        # Continue with bot processing even if flash crash check fails

                # =================================================================
                # MARGIN MONITOR CHECK (Smart Feature #18)
                # =================================================================
                # Check ALL positions and add margin if liquidation is too close
                # Works independently of bot status (protects paused/stopped bots too)
                if MARGIN_MONITOR_ENABLED:
                    try:
                        margin_result = margin_monitor_service.check_all_positions()

                        # Log summary if any actions were taken
                        actions = margin_result.get("actions", [])
                        if actions:
                            for action in actions:
                                logging.warning(
                                    "🛡️ MarginMonitor: %s - Added %.2f USDT (%.1f%% to liq, %s)",
                                    action["symbol"],
                                    action["amount"],
                                    action["pct_to_liq"],
                                    action["reason"],
                                )
                        elif margin_result.get("error"):
                            logging.debug("Margin monitor: %s", margin_result.get("error"))

                    except Exception as margin_exc:
                        logging.error("Margin monitor check failed: %s", margin_exc)
                        logging.debug("Traceback:\n%s", traceback.format_exc())
                        # Continue with bot processing even if margin monitor fails

                # 5) Load bots and run cycles for running bots
                bots = bot_storage.list_bots()
                maintenance_targets = [
                    dict(bot)
                    for bot in bots
                    if (
                        str(bot.get("status") or "").strip().lower() == "error"
                        or bool(dict(bot.get("ambiguous_execution_follow_up") or {}).get("pending"))
                    )
                ]
                if maintenance_targets:
                    bots = _run_exchange_truth_reconciliation(
                        grid_bot_service,
                        bots,
                        reason="ambiguous_follow_up",
                    )
                    error_targets = [
                        dict(bot)
                        for bot in bots
                        if str(bot.get("status") or "").strip().lower() == "error"
                    ]
                    if error_targets:
                        bots = _run_exchange_truth_reconciliation(
                            grid_bot_service,
                            bots,
                            reason="error_maintenance",
                        )
                # Auto-resume any stopped/error bot with exchange exposure
                try:
                    bots = _auto_resume_exposed_bots(grid_bot_service, bot_storage, bots)
                except Exception as ar_exc:
                    logging.warning("Auto-resume check failed: %s", ar_exc)

                running_count = 0

                # Periodic cache cleanup to prevent memory leaks
                try:
                    active_ids = {str(b.get("id") or "").strip() for b in bots if b.get("id")}
                    grid_bot_service._prune_stale_caches(active_ids)
                    # Prune stalled log cooldown
                    if len(STALLED_LOG_COOLDOWN) > 100:
                        STALLED_LOG_COOLDOWN.clear()
                except Exception:
                    pass

                for bot in bots:
                    status = bot.get("status")
                    symbol = bot.get("symbol", "?")
                    bot_id = bot.get("id", "?")
                    bot_id_short = bot_id[:6] if bot_id else "?"

                    if status == "error":
                        now = time.time()
                        cache_key = f"{bot_id}:error"
                        if now - STALLED_LOG_COOLDOWN.get(cache_key, 0) > 300:
                            logging.error(
                                "[%s:%s] ✗ Bot is in ERROR state: %s",
                                symbol,
                                bot_id_short,
                                bot.get("last_error", "unknown"),
                            )
                            STALLED_LOG_COOLDOWN[cache_key] = now
                        continue

                    if not should_process_full_cycle_status(status):
                        continue

                    if status == "running":
                        running_count += 1
                    bot_id = bot.get("id", "?")
                    bot_id_short = bot_id[:6] if bot_id else "?"
                    symbol = bot.get("symbol", "?")

                    if status == "running":
                        logging.info("[%s:%s] 🤖 Running bot cycle", symbol, bot_id_short)
                    else:
                        logging.debug(
                            "[%s:%s] Maintaining %s bot state",
                            symbol,
                            bot_id_short,
                            status,
                        )

                    try:
                        _cycle_t0 = time.monotonic()
                        updated_bot = grid_bot_service.run_bot_cycle(bot)
                        _cycle_dur = time.monotonic() - _cycle_t0
                        updated_bot["_last_cycle_duration_sec"] = round(_cycle_dur, 2)
                        from config.strategy_config import CYCLE_SLA_WARN_SECONDS, CYCLE_SLA_BREACH_ALERT_COUNT
                        if _cycle_dur > CYCLE_SLA_WARN_SECONDS:
                            breach = int(updated_bot.get("_cycle_sla_breach_count") or 0) + 1
                            updated_bot["_cycle_sla_breach_count"] = breach
                            if breach >= CYCLE_SLA_BREACH_ALERT_COUNT:
                                logging.warning(
                                    "[%s:%s] Cycle SLA breach #%d (%.1fs > %.0fs)",
                                    symbol, bot_id_short, breach, _cycle_dur, CYCLE_SLA_WARN_SECONDS,
                                )
                        else:
                            updated_bot["_cycle_sla_breach_count"] = 0

                        # Log result
                        new_status = updated_bot.get("status", "unknown")
                        if new_status == "running":
                            logging.info("[%s:%s] ✓ Cycle completed", symbol, bot_id_short)
                        elif new_status == "out_of_range":
                            logging.info(
                                "[%s:%s] ⚠ Price out of range", symbol, bot_id_short
                            )
                        elif new_status == "risk_stopped":
                            logging.warning(
                                "[%s:%s] 🛑 Stopped by risk manager", symbol, bot_id_short
                            )
                        elif new_status == "stop_cleanup_pending":
                            logging.warning(
                                "[%s:%s] ⏳ Stop cleanup still pending", symbol, bot_id_short
                            )
                        elif new_status == "tp_hit":
                            logging.info(
                                "[%s:%s] 🎯 Take profit hit!", symbol, bot_id_short
                            )
                        elif new_status == "error":
                            logging.error(
                                "[%s:%s] ✗ Error - %s",
                                symbol,
                                bot_id_short,
                                updated_bot.get("last_error", "unknown"),
                            )

                    except Exception as bot_exc:
                        logging.error(
                            "[%s:%s] Error in bot cycle: %s", symbol, bot_id_short, bot_exc
                        )
                        logging.debug("Traceback:\n%s", traceback.format_exc())
                        _persist_bot_cycle_exception(
                            bot_storage,
                            grid_bot_service,
                            bot,
                            bot_exc,
                        )

                if running_count == 0:
                    logging.debug("No running bots to process.")
                    now_ts = time.time()
                    if now_ts - last_heartbeat_ts > 60:  # Log every minute if idle
                        logging.info("Runner active: No running bots. Waiting...")
                        last_heartbeat_ts = now_ts

                # 6) Sync closed PnL (best-effort)
                try:
                    pnl_service.sync_closed_pnl()
                except Exception as pnl_exc:
                    logging.error("Error syncing closed PnL: %s", pnl_exc)
                    logging.debug("Traceback:\n%s", traceback.format_exc())

                # 7) Update per-bot realized PnL from trade logs into bots.json
                try:
                    pnl_service.update_bots_realized_pnl()
                except Exception as pnl_bot_exc:
                    logging.error("Error updating bots realized PnL: %s", pnl_bot_exc)
                    logging.debug("Traceback:\n%s", traceback.format_exc())

                # =================================================================
                # LEGACY SMART ROTATION CHECK (opt-in only)
                # =================================================================
                try:
                    # Re-list bots in case they changed
                    bots_for_rot = bot_storage.list_bots()
                    running_bots_rot = [
                        b for b in bots_for_rot if b.get("status") == "running"
                    ]

                    if should_run_legacy_rotation(running_bots_rot) and rotation_service:
                        rotation_ops = rotation_service.check_rotation(running_bots_rot)
                        if rotation_ops:
                            logging.info(
                                "ROTATION ACTION REQUIRED (Legacy): %s", rotation_ops
                            )
                            # Handle legacy rotation...
                            for stop_id in rotation_ops.get("stop_bot_ids", []):
                                for b in bots_for_rot:
                                    if b["id"] == stop_id:
                                        b["status"] = "stopped"
                                        bot_storage.save_bot(b)
                                        logging.info("Rotation: Stopped bot %s", stop_id)
                except Exception as rot_exc:
                    logging.error("Legacy rotation check error: %s", rot_exc)

                # =================================================================
                # GUARDIAN SELF-HEALING CHECK (every 60s)
                # =================================================================
                try:
                    guardian_service.run_health_check()
                except Exception as guard_exc:
                    logging.error("Guardian health check error: %s", guard_exc)

            except KeyboardInterrupt:
                logging.info("Runner interrupted by user. Exiting main loop.")
                break

            except Exception as loop_exc:
                logging.error("Unhandled error in main loop: %s", loop_exc)
                logging.debug("Traceback:\n%s", traceback.format_exc())
    finally:
        if private_account_cache_service:
            try:
                private_account_cache_service.stop()
            except Exception:
                logging.debug("Failed to stop private account cache service", exc_info=True)
        if runtime_snapshot_bridge:
            try:
                runtime_snapshot_bridge.stop()
            except Exception:
                logging.debug("Failed to stop runtime snapshot bridge", exc_info=True)
        try:
            grid_bot_service.stop_event_reactor()
        except Exception:
            logging.debug("Failed to stop stream reaction service", exc_info=True)
        try:
            order_router.close()
        except Exception:
            logging.debug("Failed to close order router", exc_info=True)
        if stream_service:
            try:
                stream_service.stop()
            except Exception:
                logging.debug("Failed to stop runner stream service", exc_info=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Runner stopped.")
