"""
Bybit Control Center - Flask Application

Main application server with JSON APIs and dashboard.
"""

import os
import sys
import time
import threading
import logging
import copy
import signal
import re
import zlib
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Dict, List
import pandas as pd

from flask import Flask, request, jsonify, render_template, Response
import json
import uuid
from config.config import (
    apply_trusted_proxy_fix,
    get_request_client_ip,
    load_dashboard_config,
    require_basic_auth,
    DASH_ALLOW_IPS,
    should_bypass_localhost,
)
from config.strategy_config import (
    MAX_BOT_LOSS_PCT,
    MAX_DAILY_LOSS_PCT,
    AUTO_GRID_ADJUSTMENT_BUFFER,
    AUTO_MARGIN_RESERVE_PCT,
    AUTO_MARGIN_RESERVE_USDT,
    AUTO_MARGIN_RESERVE_USE_PCT,
    ENABLE_BTC_CORRELATION_FILTER,
    MAX_ALLOWED_CORRELATION_BTC,
    BTC_STRONG_TREND_ADX_THRESHOLD,
    BTC_CORRELATION_LOOKBACK,
    ENABLE_AUTOMATIC_STOP_LOSS,
    SL_SAFE_ATR_MULTIPLIER,
    SL_NORMAL_ATR_MULTIPLIER,
    SL_AGGRESSIVE_ATR_MULTIPLIER,
    SL_MIN_DISTANCE_PCT,
    SL_MAX_DISTANCE_PCT,
    SL_UPDATE_THRESHOLD_PCT,
    ENABLE_TREND_PROTECTION,
    TREND_ADX_THRESHOLD,
    TREND_DI_DOMINANCE,
    TREND_RSI_THRESHOLD,
    TREND_MIN_CONFIDENCE_SCORE,
    # Batch 3 feature configs
    TP_SAFE_ATR_MULTIPLIER,
    TP_NORMAL_ATR_MULTIPLIER,
    TP_AGGRESSIVE_ATR_MULTIPLIER,
    TP_MIN_DISTANCE_PCT,
    TP_MAX_DISTANCE_PCT,
    DANGER_RSI_OVERBOUGHT,
    DANGER_RSI_OVERSOLD,
    DANGER_VOLUME_SPIKE_MULTIPLIER,
    DANGER_RANGE_EXTREME_PCT,
    get_dynamic_range_settings,
    MIN_RANGE_WIDTH_PCT,
    MAX_RANGE_WIDTH_PCT,
    SYMBOL_TRAINING_ENABLED,
)
from services.bybit_client import BybitClient
from services.bybit_stream_service import BybitStreamService
from services.account_service import AccountService
from services.position_service import PositionService
from services.bot_storage_service import BotStorageService
from services.order_router_service import OrderRouterService
from services.order_ownership_service import (
    OrderOwnershipService,
    build_order_ownership_snapshot,
)
from services.ai_advisor_analytics_service import AIAdvisorAnalyticsService
from services.advisor_replay_analysis_service import AdvisorReplayAnalysisService
from services.bot_triage_action_service import (
    BotTriageActionService,
    BotTriageSettingsConflictError,
)
from services.bot_config_advisor_service import (
    BotConfigAdvisorApplyBlockedError,
    BotConfigAdvisorService,
)
from services.custom_bot_preset_service import CustomBotPresetService
from services.bot_preset_service import BotPresetService
from services.bot_triage_service import BotTriageService
from services.decision_snapshot_service import DecisionSnapshotService
from services.trade_forensics_service import TradeForensicsService
from services.pnl_service import PnlService
from services.risk_manager_service import RiskManagerService
from services.indicator_service import IndicatorService
from services.entry_filter_service_v2 import EntryFilterService
from services.stop_loss_service import StopLossService
from services.trend_protection_service import TrendProtectionService
from services.take_profit_service import TakeProfitService
from services.danger_zone_service import DangerZoneService
from services.range_engine_service import RangeEngineService
from services.grid_engine_service import GridEngineService
from services.neutral_scanner_service import NeutralScannerService
from services.grid_bot_service import GridBotService
from services.bot_manager_service import BotManagerService
from services.bot_status_service import BotStatusService
from services.symbol_pnl_service import SymbolPnlService
from services.symbol_training_service import SymbolTrainingService
from services.price_prediction_service import PricePredictionService
from services.runtime_settings_service import RuntimeSettingsService
from services.runtime_snapshot_bridge_service import RuntimeSnapshotBridgeService
from services.runtime_state_integrity_watchdog_service import (
    RuntimeStateIntegrityWatchdogService,
)
from services.config_integrity_watchdog_service import ConfigIntegrityWatchdogService
from services.control_timing_service import elapsed_ms, iso_from_ts, now_ts
from services.diagnostics_export_service import DiagnosticsExportService
from services.watchdog_hub_service import WatchdogHubService
from services.performance_baseline_service import PerformanceBaselineService
from services.order_sizing_viability import build_order_sizing_viability
from services.mode_semantics import configured_mode, configured_range_mode
from services.backtest.engine import BacktestEngine
from services.backtest.mock_client import MockBybitClient
from services.lock_service import acquire_process_lock

# Initialize Flask app
app = Flask(__name__)
apply_trusted_proxy_fix(app)

# Disable template caching for development
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.after_request
def compress_response(response):
    """Gzip-compress JSON API responses to reduce payload size."""
    if (
        response.status_code < 200
        or response.status_code >= 300
        or response.direct_passthrough
        or response.is_streamed
        or "Content-Encoding" in response.headers
    ):
        return response
    accept_encoding = request.headers.get("Accept-Encoding", "")
    if "gzip" not in accept_encoding.lower():
        return response
    content_type = response.content_type or ""
    # Never compress SSE streams — get_data() would consume the infinite generator
    if "event-stream" in content_type:
        return response
    if not ("json" in content_type or "javascript" in content_type or "text/" in content_type):
        return response
    import gzip as _gzip
    import io as _io
    raw_data = response.get_data()  # Read once, not three times
    buf = _io.BytesIO()
    with _gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=1) as gz:
        gz.write(raw_data)
    compressed = buf.getvalue()
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = len(compressed)
    response.headers["Vary"] = "Accept-Encoding"
    return response

# ============================================================
# B2/B3: TTL cache for slow endpoints (bot-triage, watchdog)
# ============================================================
_ENDPOINT_CACHE: Dict[str, Dict[str, Any]] = {}
_ENDPOINT_CACHE_LOCK = threading.Lock()


def _get_cached_or_compute(key: str, ttl_sec: float, compute_fn):
    """Return cached result if fresh, otherwise compute and cache."""
    now = time.time()
    with _ENDPOINT_CACHE_LOCK:
        entry = _ENDPOINT_CACHE.get(key)
        if entry and now - entry["ts"] < ttl_sec:
            return entry["value"]
    # Compute outside lock to avoid blocking other requests
    value = compute_fn()
    with _ENDPOINT_CACHE_LOCK:
        _ENDPOINT_CACHE[key] = {"ts": time.time(), "value": value}
    return value


def _invalidate_endpoint_cache(*keys: str) -> None:
    """Invalidate specific cache entries (call after bot state changes)."""
    with _ENDPOINT_CACHE_LOCK:
        for key in keys:
            _ENDPOINT_CACHE.pop(key, None)


# Track app startup time for status endpoint
APP_START_TIME = datetime.utcnow()
RUNNER_MONITOR_LOCK = threading.Lock()
RUNNER_LAST_SPAWN_AT = 0.0
RUNNER_WATCHDOG_THREAD = None
RUNNER_MIN_RESPAWN_INTERVAL_SEC = 5.0
RUNNER_WATCHDOG_INTERVAL_SEC = 5.0
PNL_API_SYNC_LOCK = threading.Lock()
PNL_API_LAST_SYNC_AT = 0.0
PNL_API_MIN_SYNC_INTERVAL_SEC = 2.0
PNL_API_SYNC_THREAD = None
APP_RUNTIME_INIT_LOCK = threading.Lock()
APP_RUNTIME_INITIALIZED = False
APP_RUNTIME_INIT_ERROR = None
DASHBOARD_SNAPSHOT_LOCK = threading.Lock()
DASHBOARD_SNAPSHOT_CACHE: Dict[str, Dict[str, Any]] = {}
DASHBOARD_SNAPSHOT_FUTURES: Dict[str, Any] = {}
_FORCE_RUNTIME_REBUILD_UNTIL: float = 0.0
DASHBOARD_SNAPSHOT_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="dashboard-snapshot",
)
DASHBOARD_SNAPSHOT_WAIT_SEC = 1.5
DASHBOARD_SNAPSHOT_REFRESH_TTL_SEC = 1.0
DASHBOARD_BOTS_SNAPSHOT_REFRESH_TTL_SEC = 1.0
DASHBOARD_STREAM_FALLBACK_INTERVAL_SEC = 2.0
BOOTSTRAP_RECOVERY_LOG_LOCK = threading.Lock()
BOOTSTRAP_RECOVERY_LOG_STATE: Dict[str, float] = {"last_logged_at": 0.0}
REQUEST_DIAGNOSTICS_LOCK = threading.Lock()
REQUEST_DIAGNOSTICS: Dict[str, Dict[str, Any]] = {}
REQUEST_DIAGNOSTIC_LOG_STATE: Dict[str, float] = {}
REQUEST_DIAGNOSTIC_LOG_THROTTLE_SEC = 60.0
REQUEST_DIAGNOSTIC_SLOW_MS = {
    "dashboard_bootstrap": 1000.0,
    "bridge_diagnostics": 250.0,
}
RUNTIME_SNAPSHOT_BRIDGE_FILE = os.environ.get(
    "RUNTIME_SNAPSHOT_BRIDGE_FILE",
    os.path.join("storage", "runtime_snapshot_bridge.json"),
)
runtime_snapshot_bridge = RuntimeSnapshotBridgeService(
    file_path=RUNTIME_SNAPSHOT_BRIDGE_FILE,
    owner_name="app",
    write_enabled=False,
)


def _copy_payload(value: Any) -> Any:
    return copy.deepcopy(value)


def _top_timing_phase(phase_ms: Dict[str, Any] | None) -> Dict[str, Any] | None:
    top_name = None
    top_elapsed_ms = -1.0
    for name, elapsed in (phase_ms or {}).items():
        try:
            numeric_elapsed = float(elapsed or 0.0)
        except (TypeError, ValueError):
            continue
        if numeric_elapsed > top_elapsed_ms:
            top_name = str(name)
            top_elapsed_ms = numeric_elapsed
    if top_name is None:
        return None
    return {
        "name": top_name,
        "elapsed_ms": round(top_elapsed_ms, 3),
    }


def _store_request_diagnostics(name: str, payload: Dict[str, Any]) -> None:
    with REQUEST_DIAGNOSTICS_LOCK:
        REQUEST_DIAGNOSTICS[str(name or "").strip() or "unknown"] = _copy_payload(payload)


def _get_request_diagnostics(name: str) -> Dict[str, Any] | None:
    with REQUEST_DIAGNOSTICS_LOCK:
        payload = REQUEST_DIAGNOSTICS.get(str(name or "").strip() or "unknown")
        return _copy_payload(payload) if payload is not None else None


def _maybe_log_request_diagnostics(name: str, payload: Dict[str, Any]) -> None:
    normalized = str(name or "").strip() or "unknown"
    threshold_ms = float(REQUEST_DIAGNOSTIC_SLOW_MS.get(normalized, 0.0) or 0.0)
    total_ms = float((payload or {}).get("total_ms") or 0.0)
    if total_ms < threshold_ms:
        return
    now_mono = time.monotonic()
    with REQUEST_DIAGNOSTICS_LOCK:
        last_logged_at = float(REQUEST_DIAGNOSTIC_LOG_STATE.get(normalized, 0.0))
        if (
            last_logged_at > 0
            and (now_mono - last_logged_at) < REQUEST_DIAGNOSTIC_LOG_THROTTLE_SEC
        ):
            return
        REQUEST_DIAGNOSTIC_LOG_STATE[normalized] = now_mono
    top_phase = (payload or {}).get("top_phase") or {}
    bridge_reads = (payload or {}).get("bridge_reads") or {}
    storage_reads = (payload or {}).get("storage_reads") or {}
    logging.warning(
        "Request diagnostics route=%s total_ms=%.1f top_phase=%s top_phase_ms=%.1f "
        "bridge_snapshot_calls=%d bridge_top_section=%s storage_reads=%d cache_lock_wait_ms=%.1f",
        normalized,
        total_ms,
        top_phase.get("name") or "-",
        float(top_phase.get("elapsed_ms") or 0.0),
        int((bridge_reads.get("operation_counts") or {}).get("read_snapshot") or 0),
        ((bridge_reads.get("top_repeated_section") or {}).get("name") or "-"),
        int(storage_reads.get("storage_read_call_count") or 0),
        float(((storage_reads.get("lock_wait_ms") or {}).get("cache_lock") or 0.0)),
    )


def _runtime_snapshot_bridge_read_diagnostics_context(label: str):
    bridge = runtime_snapshot_bridge
    if bridge is not None and hasattr(bridge, "capture_read_diagnostics"):
        return bridge.capture_read_diagnostics(label)
    return nullcontext({})


def _bot_storage_read_diagnostics_context(label: str):
    storage = globals().get("bot_storage")
    if storage is not None and hasattr(storage, "capture_read_diagnostics"):
        return storage.capture_read_diagnostics(label)
    return nullcontext({})


def _dashboard_future_done(key: str, future) -> None:
    try:
        value = future.result()
    except Exception as exc:
        logging.warning("Dashboard snapshot refresh failed for %s: %s", key, exc)
    else:
        with DASHBOARD_SNAPSHOT_LOCK:
            current = DASHBOARD_SNAPSHOT_FUTURES.get(key)
            if current is future:
                DASHBOARD_SNAPSHOT_CACHE[key] = {
                    "ts": time.time(),
                    "value": _copy_payload(value),
                }
    finally:
        with DASHBOARD_SNAPSHOT_LOCK:
            current = DASHBOARD_SNAPSHOT_FUTURES.get(key)
            if current is future:
                DASHBOARD_SNAPSHOT_FUTURES.pop(key, None)


def _get_dashboard_snapshot_entry(key: str) -> Dict[str, Any] | None:
    with DASHBOARD_SNAPSHOT_LOCK:
        entry = DASHBOARD_SNAPSHOT_CACHE.get(key)
        return _copy_payload(entry) if entry else None


def _store_dashboard_snapshot_entry(key: str, value: Any) -> None:
    with DASHBOARD_SNAPSHOT_LOCK:
        DASHBOARD_SNAPSHOT_CACHE[key] = {
            "ts": time.time(),
            "value": _copy_payload(value),
        }


def _invalidate_dashboard_snapshots(*keys: str) -> None:
    snapshot_keys = {
        str(key or "").strip()
        for key in keys
        if str(key or "").strip()
    }
    if not snapshot_keys:
        return

    # Also invalidate slow-endpoint caches when bot state changes
    _invalidate_endpoint_cache("bot_triage", "bot_config_advisor", "watchdog_center")

    with DASHBOARD_SNAPSHOT_LOCK:
        for key in snapshot_keys:
            DASHBOARD_SNAPSHOT_CACHE.pop(key, None)
            future = DASHBOARD_SNAPSHOT_FUTURES.pop(key, None)
            if future is not None and not future.done():
                future.cancel()


def _invalidate_dashboard_runtime_views() -> None:
    global _FORCE_RUNTIME_REBUILD_UNTIL
    _invalidate_dashboard_snapshots("summary", "positions", "bots_runtime")
    _FORCE_RUNTIME_REBUILD_UNTIL = time.time() + 4.0


def _mark_snapshot_stale(value: Any, error: str) -> Any:
    payload = _copy_payload(value)
    if isinstance(payload, dict):
        payload["stale_data"] = True
        if payload.get("error") in (None, "", 0):
            payload["error"] = error
    return payload


def _dashboard_snapshot(
    key: str,
    builder,
    fallback_builder,
    *,
    wait_timeout: float | None = None,
    refresh_ttl: float | None = None,
):
    wait_timeout = (
        float(wait_timeout)
        if wait_timeout is not None
        else float(DASHBOARD_SNAPSHOT_WAIT_SEC)
    )
    refresh_ttl = (
        float(refresh_ttl)
        if refresh_ttl is not None
        else float(DASHBOARD_SNAPSHOT_REFRESH_TTL_SEC)
    )
    now = time.time()
    cache_entry = None
    future = None
    attach_callback = False

    with DASHBOARD_SNAPSHOT_LOCK:
        cache_entry = DASHBOARD_SNAPSHOT_CACHE.get(key)
        if cache_entry and (now - float(cache_entry.get("ts", 0.0))) < refresh_ttl:
            return _copy_payload(cache_entry.get("value"))

        future = DASHBOARD_SNAPSHOT_FUTURES.get(key)
        if future is None:
            future = DASHBOARD_SNAPSHOT_EXECUTOR.submit(builder)
            DASHBOARD_SNAPSHOT_FUTURES[key] = future
            attach_callback = True

    if attach_callback:
        future.add_done_callback(
            lambda fut, snapshot_key=key: _dashboard_future_done(snapshot_key, fut)
        )

    if cache_entry is not None:
        return _mark_snapshot_stale(
            cache_entry.get("value"),
            f"{key}_stale",
        )

    try:
        return _copy_payload(future.result(timeout=wait_timeout))
    except FuturesTimeoutError:
        logging.warning("Dashboard snapshot timeout for %s after %.1fs", key, wait_timeout)
        return fallback_builder(f"{key}_timeout")
    except Exception as exc:
        logging.warning("Dashboard snapshot error for %s: %s", key, exc)
        return fallback_builder(f"{key}_error")


def _build_positions_fallback_payload(error: str) -> Dict[str, Any]:
    cache_entry = _get_dashboard_snapshot_entry("positions")
    if cache_entry:
        return _mark_snapshot_stale(cache_entry.get("value"), error)
    return {
        "positions": [],
        "summary": {
            "total_positions": 0,
            "longs": 0,
            "shorts": 0,
            "total_unrealized_pnl": 0.0,
        },
        "wallet_balance": 0.0,
        "available_balance": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "error": error,
        "stale_data": True,
    }


def _build_summary_fallback_payload(error: str) -> Dict[str, Any]:
    cache_entry = _get_dashboard_snapshot_entry("summary")
    if cache_entry:
        return _mark_snapshot_stale(cache_entry.get("value"), error)
    return {
        "account": {
            "equity": 0.0,
            "available_balance": 0.0,
            "funding_balance": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "error": error,
        },
        "positions_summary": {
            "total_positions": 0,
            "longs": 0,
            "shorts": 0,
            "total_unrealized_pnl": 0.0,
        },
        "today_pnl": {},
        "daily_loss_pct": 0.0,
        "kill_switch_triggered": False,
        "kill_switch_triggered_at": None,
        "error": error,
        "stale_data": True,
    }


def _build_runtime_bots_fallback(error: str) -> Dict[str, Any]:
    cache_entry = _get_dashboard_snapshot_entry("bots_runtime")
    if cache_entry:
        payload = _mark_snapshot_stale(cache_entry.get("value"), error)
        if isinstance(payload, dict):
            payload.setdefault("runtime_state_source", "dashboard_cache_fallback")
            payload.setdefault("snapshot_source", "dashboard_cache_fallback")
        return payload

    # No bot_storage.list_bots() — avoid cache_lock + file_lock contention
    # on dashboard-critical path. Empty degraded state; bots arrive via bridge/SSE.
    return {
        "bots": [],
        "error": error,
        "stale_data": True,
        "runtime_state_source": "critical_path_empty_fallback",
        "snapshot_source": "critical_path_empty_fallback",
    }


def _build_runtime_bots_light_fallback(error: str) -> Dict[str, Any]:
    """Light-oriented fallback: light cache -> full cache -> empty degraded."""
    cache_entry = _get_dashboard_snapshot_entry("bots_runtime_light")
    if cache_entry:
        payload = _mark_snapshot_stale(cache_entry.get("value"), error)
        if isinstance(payload, dict):
            payload.setdefault("runtime_state_source", "dashboard_light_cache_fallback")
            payload.setdefault("bots_scope", "light")
        return payload
    cache_entry = _get_dashboard_snapshot_entry("bots_runtime")
    if cache_entry:
        payload = _mark_snapshot_stale(cache_entry.get("value"), error)
        if isinstance(payload, dict):
            payload.setdefault("runtime_state_source", "dashboard_cache_fallback")
            payload.setdefault("bots_scope", "full_fallback")
        return payload
    # No bot_storage.list_bots() — avoid cache_lock + file_lock contention
    # on dashboard-critical path. Empty degraded state; bots arrive via bridge/SSE.
    return {
        "bots": [],
        "error": error,
        "stale_data": True,
        "runtime_state_source": "critical_path_empty_fallback",
        "bots_scope": "light",
    }


def _build_runtime_bots_payload() -> Dict[str, Any]:
    bots = []
    try:
        bots = bot_status_service.get_runtime_bots() if "bot_status_service" in globals() else []
    except Exception as exc:
        logging.warning("Runtime bot rebuild failed: %s", exc)
        return _build_runtime_bots_fallback("bots_runtime_rebuild_error")

    now_ts = time.time()
    batch_context = (
        bot_status_service.get_last_runtime_batch_context()
        if "bot_status_service" in globals()
        and bot_status_service is not None
        and hasattr(bot_status_service, "get_last_runtime_batch_context")
        else {}
    )
    payload = {
        "bots": bots or [],
        "error": None,
        "stale_data": False,
        "runtime_state_source": "app_runtime_rebuild",
        "snapshot_published_at": now_ts,
        "snapshot_produced_at": now_ts,
        "snapshot_age_sec": 0.0,
        "snapshot_fresh": True,
        "snapshot_source": "app_runtime_rebuild",
        "snapshot_reason": "direct_runtime_refresh",
        "snapshot_owner": "app",
    }
    if isinstance(batch_context, dict):
        payload["runtime_publish_at"] = batch_context.get("runtime_publish_at")
        payload["runtime_publish_ts"] = batch_context.get("runtime_publish_ts")
        payload["runtime_build_duration_ms"] = batch_context.get(
            "runtime_build_duration_ms"
        )
        payload["readiness_latency"] = dict(
            batch_context.get("readiness_latency") or {}
        )
    return payload


def _build_runtime_bots_light_payload() -> Dict[str, Any]:
    """Build a lightweight bot payload using get_runtime_bots_light() — no heavy enrichment."""
    bots = []
    light_runtime_diagnostics = {}
    try:
        bots = bot_status_service.get_runtime_bots_light() if "bot_status_service" in globals() and bot_status_service is not None else []
        light_runtime_diagnostics = (
            bot_status_service.get_last_runtime_light_diagnostics()
            if "bot_status_service" in globals()
            and bot_status_service is not None
            and hasattr(bot_status_service, "get_last_runtime_light_diagnostics")
            else {}
        )
    except Exception as exc:
        logging.warning("Runtime bot light rebuild failed: %s", exc)
        return _build_runtime_bots_light_fallback("bots_runtime_light_rebuild_error")
    now_ts = time.time()
    return {
        "bots": bots or [],
        "error": None,
        "stale_data": False,
        "runtime_state_source": "app_runtime_light_rebuild",
        "bots_scope": "light",
        "snapshot_published_at": now_ts,
        "snapshot_produced_at": now_ts,
        "snapshot_age_sec": 0.0,
        "snapshot_fresh": True,
        "snapshot_source": "app_runtime_light_rebuild",
        "snapshot_reason": "direct_light_refresh",
        "snapshot_owner": "app",
        "light_runtime_diagnostics": (
            dict(light_runtime_diagnostics)
            if isinstance(light_runtime_diagnostics, dict)
            else {}
        ),
    }


_BRIDGE_PRODUCER_ALIVE_CACHE: Dict[str, Any] = {
    "pid": None, "alive": False, "checked_at": 0.0,
}


def _is_bridge_producer_alive() -> bool:
    """Check if the bridge file's producer PID is alive (cached 5s)."""
    now = time.time()
    cache = _BRIDGE_PRODUCER_ALIVE_CACHE
    if cache["pid"] is not None and (now - cache["checked_at"]) < 5.0:
        return cache["alive"]
    try:
        snapshot = runtime_snapshot_bridge.read_snapshot()
    except (AttributeError, Exception):
        snapshot = None
    if not snapshot:
        cache.update(pid=None, alive=False, checked_at=now)
        return False
    pid = (snapshot.get("meta") or {}).get("producer_pid")
    alive = _pid_is_alive(pid, expected_substring="runner.py")
    cache.update(pid=pid, alive=alive, checked_at=now)
    return alive


def _bridge_section_usable(bridged) -> bool:
    """Return True only when bridged section is present, producer alive, AND fresh."""
    if bridged is None:
        return False
    if not _is_bridge_producer_alive():
        return False
    if bridged.get("stale_data"):
        return False
    return True


def _get_positions_snapshot() -> Dict[str, Any]:
    bridged = runtime_snapshot_bridge.read_section("positions")
    if _bridge_section_usable(bridged):
        return bridged
    # Stale bridge data is better than hitting Bybit
    if isinstance(bridged, dict) and isinstance(bridged.get("positions"), list):
        bridged.setdefault("stale_data", True)
        return bridged
    # No bridge at all — cached or empty fallback (local only, no Bybit)
    return _build_positions_fallback_payload("positions_bridge_unavailable")


def _get_summary_snapshot() -> Dict[str, Any]:
    bridged = runtime_snapshot_bridge.read_section("summary")
    if _bridge_section_usable(bridged):
        return bridged
    # Stale bridge data is better than hitting Bybit
    if isinstance(bridged, dict) and bridged.get("account"):
        bridged.setdefault("stale_data", True)
        return bridged
    # No bridge — cached or empty fallback (local only, no Bybit)
    return _build_summary_fallback_payload("summary_bridge_unavailable")


def _get_runtime_bots_snapshot() -> Dict[str, Any]:
    bridged = runtime_snapshot_bridge.read_section("bots_runtime")
    integrity_watchdog = _get_runtime_state_integrity_watchdog_service()
    rebuilt = None
    force_rebuild = time.time() < _FORCE_RUNTIME_REBUILD_UNTIL
    # Use bridge data only when producer is alive AND section is fresh.
    # If alive-but-stale or dead/missing, fall through to direct recovery.
    bridge_usable = _bridge_section_usable(bridged)
    need_probe = (not bridge_usable) and integrity_watchdog.should_probe_direct_runtime(bridged)
    if need_probe:
        # Bridge stale + watchdog says probe — return degraded fallback instead
        # of submitting heavy _build_runtime_bots_payload to executor (which
        # would call bot_status_service.get_runtime_bots() -> bot_storage.list_bots()
        # and contend on cache_lock + file_lock).
        rebuilt = _build_runtime_bots_fallback("bots_runtime_bridge_stale")
    elif not bridge_usable and bot_status_service is None:
        rebuilt = _build_runtime_bots_fallback("bots_runtime_bridge_unavailable")
    elif force_rebuild and not bridge_usable:
        # Forced rebuild with stale bridge — use degraded fallback, not heavy builder.
        rebuilt = _build_runtime_bots_fallback("bots_runtime_force_rebuild_stale")
    return _get_runtime_state_integrity_watchdog_service().resolve_runtime_bots(
        bridge_payload=bridged,
        app_payload=rebuilt,
        runner_health=_build_runtime_runner_health_snapshot(),
    )


def _get_runtime_bots_light_snapshot() -> Dict[str, Any]:
    """Light-oriented bot snapshot — NEVER falls back to the full/heavy path.

    Fallback chain: fresh light bridge -> stale light bridge -> direct light rebuild.
    """
    bridged_light = runtime_snapshot_bridge.read_section("bots_runtime_light")
    # 1. Fresh light bridge section
    if _bridge_section_usable(bridged_light):
        bridged_light.setdefault("bots_scope", "light")
        return bridged_light
    # 2. Stale-but-structured light section (last-known-good)
    if isinstance(bridged_light, dict) and isinstance(bridged_light.get("bots"), list):
        bridged_light.setdefault("bots_scope", "light")
        bridged_light.setdefault("stale_data", True)
        return bridged_light
    # 3. No bridge at all — cached or storage fallback (local only, no Bybit)
    return _build_runtime_bots_light_fallback("light_bridge_unavailable")


def _bridge_hot_path_fresh_payload(section_name: str) -> Dict[str, Any] | None:
    if _configured_stream_owner() == "app":
        return None
    bridged = runtime_snapshot_bridge.read_section(section_name)
    if not isinstance(bridged, dict):
        return None
    payload = dict(bridged)
    payload.setdefault("fresh_request_degraded", True)
    payload.setdefault(
        "fresh_request_reason",
        f"{section_name}_runner_bridge_preferred",
    )
    return payload


def _snapshot_payload_meta(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = payload or {}
    return {
        "snapshot_published_at": payload.get("snapshot_published_at"),
        "snapshot_produced_at": payload.get("snapshot_produced_at"),
        "snapshot_age_sec": payload.get("snapshot_age_sec"),
        "snapshot_fresh": payload.get("snapshot_fresh"),
        "snapshot_source": payload.get("snapshot_source"),
        "snapshot_reason": payload.get("snapshot_reason"),
        "snapshot_owner": payload.get("snapshot_owner"),
        "snapshot_epoch": payload.get("snapshot_epoch"),
        "stale_data": bool(payload.get("stale_data")),
        "error": payload.get("error"),
    }


def _annotate_runtime_response_payload(
    payload: Dict[str, Any],
    *,
    response_started_ts: float,
) -> Dict[str, Any]:
    result = dict(payload or {})
    now_ts = time.time()
    response_generated_at = _utc_now_iso()
    runtime_integrity = dict(result.get("runtime_integrity") or {})
    snapshot_ts = RuntimeStateIntegrityWatchdogService._payload_snapshot_ts(result)
    runtime_publish_ts = 0.0
    try:
        runtime_publish_ts = float(result.get("runtime_publish_ts") or 0.0)
    except (TypeError, ValueError):
        runtime_publish_ts = 0.0
    result["response_generated_at"] = response_generated_at
    result["response_build_ms"] = round(max(now_ts - float(response_started_ts or now_ts), 0.0) * 1000.0, 2)
    result["response_age_ms"] = (
        round(max(now_ts - snapshot_ts, 0.0) * 1000.0, 2)
        if snapshot_ts > 0
        else None
    )
    result["bridge_age_ms"] = result.get("bridge_age_ms")
    if result["bridge_age_ms"] is None:
        result["bridge_age_ms"] = runtime_integrity.get("bridge_age_ms")
    result["runtime_snapshot_age_ms"] = (
        round(max(now_ts - runtime_publish_ts, 0.0) * 1000.0, 2)
        if runtime_publish_ts > 0
        else result.get("runtime_snapshot_age_ms")
    )
    if result["runtime_snapshot_age_ms"] is None:
        result["runtime_snapshot_age_ms"] = runtime_integrity.get("runtime_snapshot_age_ms")
    result["runtime_integrity_state"] = runtime_integrity.get("runtime_integrity_state") or runtime_integrity.get("status")
    result["held_last_good"] = bool(
        runtime_integrity.get("held_last_good")
        or runtime_integrity.get("preserved_from_last_known_good")
    )
    result["dropped_as_stale"] = bool(runtime_integrity.get("dropped_as_stale"))
    result["rebuilt_from_app"] = bool(runtime_integrity.get("rebuilt_from_app"))
    result["startup_pending"] = bool(runtime_integrity.get("startup_pending"))
    result["startup_stalled"] = bool(runtime_integrity.get("startup_stalled"))
    return result


def _get_runtime_bot_by_id(
    bot_id: str,
    *,
    bots_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    normalized_bot_id = str(bot_id or "").strip()
    if not normalized_bot_id:
        return None
    bots_payload = bots_payload or _get_runtime_bots_snapshot()
    for bot in list((bots_payload or {}).get("bots") or []):
        if str((bot or {}).get("id") or "").strip() == normalized_bot_id:
            return dict(bot)
    return None


def _performance_baseline_metadata(*, bot_id: str | None = None) -> Dict[str, Any]:
    service = performance_baseline_service
    if service is None:
        return {
            "version": 1,
            "updated_at": None,
            "global": {},
            "bot": {"bot_id": bot_id} if bot_id else None,
            "effective": {"scope": "legacy", "baseline_started_at": None, "epoch_id": None},
            "bot_override_count": 0,
        }
    try:
        return service.build_metadata(bot_id=bot_id)
    except Exception as exc:
        logging.warning("Performance baseline metadata build failed: %s", exc)
        return {
            "version": 1,
            "updated_at": None,
            "global": {},
            "bot": {"bot_id": bot_id} if bot_id else None,
            "effective": {"scope": "legacy", "baseline_started_at": None, "epoch_id": None},
            "bot_override_count": 0,
            "error": str(exc),
        }


def _build_performance_reset_archive_snapshot(
    *,
    scope: str,
    bot_id: str | None = None,
    note: str | None = None,
) -> Dict[str, Any]:
    bots_payload = _get_runtime_bots_snapshot()
    target_runtime_bot = _get_runtime_bot_by_id(bot_id or "", bots_payload=bots_payload) if bot_id else None
    triage_payload = _build_bot_triage_payload(bots_payload=bots_payload)
    advisor_payload = _build_bot_config_advisor_payload(bots_payload=bots_payload)
    snapshot = {
        "captured_at": _utc_now_iso(),
        "scope": scope,
        "bot_id": bot_id,
        "note": str(note or "").strip() or None,
        "performance_baseline_before": _performance_baseline_metadata(bot_id=bot_id),
        "summary": _get_summary_snapshot(),
        "pnl_stats_all": (
            pnl_service.get_trade_statistics(
                "all",
                bot_id=bot_id if scope == "bot" else None,
                use_global_baseline=False,
            )
            if pnl_service is not None
            else {}
        ),
        "recent_pnl_logs": (
            pnl_service.get_log(bot_id=bot_id if scope == "bot" else None)[-25:]
            if pnl_service is not None
            else []
        ),
        "watchdog_center": _build_watchdog_hub_payload(
            bots_payload=bots_payload,
            filters={"bot_id": bot_id} if bot_id else None,
            include_registry=True,
        ),
        "bot_triage": (
            {
                "generated_at": triage_payload.get("generated_at"),
                "summary_counts": triage_payload.get("summary_counts") or {},
                "items": [
                    item
                    for item in list(triage_payload.get("items") or [])
                    if not bot_id or str(item.get("bot_id") or "").strip() == str(bot_id or "").strip()
                ],
            }
        ),
        "bot_config_advisor": (
            {
                "generated_at": advisor_payload.get("generated_at"),
                "summary_counts": advisor_payload.get("summary_counts") or {},
                "items": [
                    item
                    for item in list(advisor_payload.get("items") or [])
                    if not bot_id or str(item.get("bot_id") or "").strip() == str(bot_id or "").strip()
                ],
            }
        ),
        "ai_advisor_summary": _build_ai_advisor_summary_payload(force_refresh=True),
        "ai_advisor_replay_summary": _build_ai_advisor_replay_summary_payload(force_refresh=True),
    }
    if scope == "bot":
        snapshot["runtime_bot"] = target_runtime_bot
    else:
        snapshot["bots_runtime_summary"] = {
            "count": len(list((bots_payload or {}).get("bots") or [])),
            "stale_data": bool((bots_payload or {}).get("stale_data")),
            "error": (bots_payload or {}).get("error"),
        }
    return snapshot


def _refresh_performance_reset_views(*, scope: str, bot_id: str | None = None) -> None:
    if pnl_service is not None:
        pnl_service.update_bots_realized_pnl()
    if watchdog_hub_service is not None and hasattr(watchdog_hub_service, "reset_scope"):
        watchdog_hub_service.reset_scope(bot_id=bot_id if scope == "bot" else None)
    if ai_advisor_analytics_service is not None:
        ai_advisor_analytics_service.refresh_snapshot(force=True)
    if advisor_replay_analysis_service is not None:
        advisor_replay_analysis_service.refresh_snapshot(force=True)
    with DASHBOARD_SNAPSHOT_LOCK:
        DASHBOARD_SNAPSHOT_CACHE.clear()
        DASHBOARD_SNAPSHOT_FUTURES.clear()


def _build_watchdog_hub_fallback_payload(error: str) -> Dict[str, Any]:
    cache_entry = _get_dashboard_snapshot_entry("watchdog_hub")
    if cache_entry:
        return _mark_snapshot_stale(cache_entry.get("value"), error)
    return {
        "updated_at": None,
        "stale_data": True,
        "error": error,
        "overview": {
            "total_active_issues": 0,
            "active_counts": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            },
            "affected_bots_count": 0,
            "affected_symbols_count": 0,
            "top_blocker_category": None,
            "top_watchdog_category": None,
            "most_noisy_watchdog": None,
            "top_blocker_categories": [],
            "top_watchdog_categories": [],
        },
        "active_issues": [],
        "recent_events": [],
        "opportunity_funnel": {
            "updated_at": None,
            "snapshot": {
                "watch": 0,
                "armed": 0,
                "trigger_ready": 0,
                "late": 0,
                "bot_count": 0,
                "included_statuses": [],
            },
            "follow_through": {
                "window_sec": 0,
                "executed": 0,
                "blocked": 0,
                "opportunities": 0,
                "trigger_to_execute_rate": None,
            },
            "blocked_reasons": [],
            "repeat_failures": [],
            "structural_untradeable": [],
            "experiment_breakdown": [],
            "experiment_combinations": [],
        },
        "experiment_attribution": {
            "updated_at": None,
            "window_sec": 0,
            "experiments": [],
            "combinations": [],
            "headline": {
                "most_trigger_ready": None,
                "most_executed": None,
                "most_blocked": None,
                "best_net_pnl": None,
                "worst_net_pnl": None,
            },
        },
        "watchdog_cards": [],
        "watchdog_configs": {},
        "available_filters": {
            "severities": ["CRITICAL", "ERROR", "WARN", "INFO"],
            "watchdog_types": [],
            "bots": [],
            "symbols": [],
        },
        "active_registry_counts": {
            "active": 0,
            "resolved_recent": 0,
        },
        "insights": [],
        "config": {
            "enabled": False,
        },
    }


def _get_runtime_state_integrity_watchdog_service() -> RuntimeStateIntegrityWatchdogService:
    global runtime_state_integrity_watchdog_service
    service = runtime_state_integrity_watchdog_service
    if service is None:
        service = RuntimeStateIntegrityWatchdogService()
        runtime_state_integrity_watchdog_service = service
    return service


def _get_watchdog_hub_service_instance() -> WatchdogHubService:
    global watchdog_hub_service
    service = watchdog_hub_service
    if service is None:
        audit_service = getattr(pnl_service, "audit_diagnostics_service", None)
        service = WatchdogHubService(audit_service)
        watchdog_hub_service = service
    return service


def _build_runtime_runner_health_snapshot() -> Dict[str, Any]:
    runner_process = _runner_process_info()
    runner_active = bool(_runner_lock_held() or runner_process.get("active"))
    bridge_snapshot = (
        runtime_snapshot_bridge.read_snapshot()
        if hasattr(runtime_snapshot_bridge, "read_snapshot")
        else {}
    ) or {}
    bridge_meta = bridge_snapshot.get("meta") if isinstance(bridge_snapshot, dict) else {}
    bridge_produced_at = (
        float((bridge_meta or {}).get("produced_at") or 0.0)
        if isinstance(bridge_meta, dict)
        else 0.0
    )
    heartbeat_age_sec = (
        round(max(time.time() - bridge_produced_at, 0.0), 3)
        if bridge_produced_at > 0
        else None
    )
    return {
        "runner_active": runner_active,
        "runner_pid": runner_process.get("pid"),
        "runner_detected_via": runner_process.get("source"),
        "runner_heartbeat_at": bridge_produced_at or None,
        "runner_heartbeat_age_sec": heartbeat_age_sec,
    }


def _get_bot_triage_service_instance() -> BotTriageService:
    global bot_triage_service
    service = bot_triage_service
    if service is None:
        service = BotTriageService(
            _get_watchdog_hub_service_instance(),
            runtime_settings_service=runtime_settings_service,
        )
        bot_triage_service = service
    return service


def _get_bot_triage_action_service_instance() -> BotTriageActionService:
    global bot_triage_action_service
    service = bot_triage_action_service
    if service is None:
        service = BotTriageActionService(
            bot_storage=bot_storage,
            bot_manager=bot_manager,
            runtime_settings_service=runtime_settings_service,
            config_integrity_watchdog_service=config_integrity_watchdog_service,
        )
        bot_triage_action_service = service
    return service


def _get_bot_config_advisor_service_instance() -> BotConfigAdvisorService:
    global bot_config_advisor_service
    service = bot_config_advisor_service
    if service is None:
        service = BotConfigAdvisorService(
            bot_triage_service=_get_bot_triage_service_instance(),
            bot_storage=bot_storage,
            bot_manager=bot_manager,
            runtime_settings_service=runtime_settings_service,
            config_integrity_watchdog_service=config_integrity_watchdog_service,
        )
        bot_config_advisor_service = service
    return service


def _get_custom_bot_preset_service_instance() -> CustomBotPresetService:
    global custom_bot_preset_service
    service = custom_bot_preset_service
    if service is None:
        service = CustomBotPresetService(
            os.path.join("storage", "custom_bot_presets.json"),
            bot_storage=bot_storage,
            audit_diagnostics_service=getattr(bot_manager, "audit_diagnostics_service", None),
        )
        custom_bot_preset_service = service
    return service


def _get_bot_preset_service_instance() -> BotPresetService:
    global bot_preset_service
    service = bot_preset_service
    if service is None:
        service = BotPresetService(
            custom_preset_service=_get_custom_bot_preset_service_instance(),
            audit_diagnostics_service=getattr(bot_manager, "audit_diagnostics_service", None),
        )
        bot_preset_service = service
    return service


def _build_watchdog_hub_payload(
    *,
    bots_payload: Dict[str, Any] | None = None,
    filters: Dict[str, Any] | None = None,
    include_registry: bool = False,
) -> Dict[str, Any]:
    bots_payload = bots_payload or _get_runtime_bots_snapshot()
    payload = _get_watchdog_hub_service_instance().build_snapshot(
        runtime_bots=list((bots_payload or {}).get("bots") or []),
        filters=filters,
        include_registry=include_registry,
    )
    if bots_payload.get("stale_data"):
        payload["stale_data"] = True
        payload["error"] = bots_payload.get("error") or "bots_runtime_stale"
    payload["runtime_integrity"] = (
        bots_payload.get("runtime_integrity")
        or _get_runtime_state_integrity_watchdog_service().get_last_summary()
    )
    payload["readiness_latency"] = dict(bots_payload.get("readiness_latency") or {})
    payload["performance_baseline"] = _performance_baseline_metadata(
        bot_id=str((filters or {}).get("bot_id") or "").strip() or None
    )
    return payload


def _build_watchdog_export_optional_payload() -> Dict[str, Any]:
    audit_service = getattr(
        _get_watchdog_hub_service_instance(),
        "audit_diagnostics_service",
        None,
    )
    if audit_service is None:
        return {}

    summary_snapshot = audit_service.get_summary_snapshot()
    review_snapshot = audit_service.get_review_snapshot()
    config_rollups = dict((summary_snapshot.get("rollups") or {}))
    return {
        "config_integrity_report": {
            "updated_at": summary_snapshot.get("updated_at"),
            "rolling_windows_sec": summary_snapshot.get("rolling_windows_sec"),
            "health_status_counts": summary_snapshot.get("health_status_counts") or {},
            "rollups": {
                "top_config_issue_types": config_rollups.get("top_config_issue_types") or [],
                "top_config_issue_ui_paths": config_rollups.get(
                    "top_config_issue_ui_paths"
                )
                or [],
                "top_bots_by_config_integrity_issue": config_rollups.get(
                    "top_bots_by_config_integrity_issue"
                )
                or [],
            },
        },
        "audit_review_snapshot": review_snapshot,
    }


def _build_bot_triage_payload(
    *,
    bots_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    bots_payload = bots_payload or _get_runtime_bots_snapshot()
    return _get_bot_triage_service_instance().build_snapshot(
        runtime_bots=list((bots_payload or {}).get("bots") or []),
        stale_data=bool(bots_payload.get("stale_data")),
        error=bots_payload.get("error"),
    )


def _build_bot_config_advisor_payload(
    *,
    bots_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    bots_payload = bots_payload or _get_runtime_bots_snapshot()
    return _get_bot_config_advisor_service_instance().build_snapshot(
        runtime_bots=list((bots_payload or {}).get("bots") or []),
        stale_data=bool(bots_payload.get("stale_data")),
        error=bots_payload.get("error"),
    )


def _get_watchdog_hub_snapshot() -> Dict[str, Any]:
    return _dashboard_snapshot(
        "watchdog_hub",
        _build_watchdog_hub_payload,
        _build_watchdog_hub_fallback_payload,
        refresh_ttl=DASHBOARD_BOTS_SNAPSHOT_REFRESH_TTL_SEC,
    )

# Path to runner log file (should match runner.py LOG_FILE_PATH)
RUNNER_LOG_FILE = os.path.join("storage", "runner.log")
APP_LOG_FILE = os.environ.get("APP_LOG_FILE", os.path.join("storage", "app.log"))
RUNNER_LOCK_FILE = os.environ.get(
    "RUNNER_LOCK_FILE", os.path.join("storage", "runner.lock")
)

# Path to runner stop flag file (runner.py checks this to stop gracefully)
RUNNER_STOP_FLAG = os.path.join("storage", "runner.stop")

# Number of log lines to return by default
DEFAULT_LOG_LINES = 100
LIVE_POSITION_OWNER_STATUSES = {
    "running",
    "paused",
    "recovering",
    "flash_crash_paused",
    "stop_cleanup_pending",
    "error",
    "risk_stopped",
}

# ============================================================
# Configure Logging
# ============================================================
os.makedirs("storage", exist_ok=True)
try:
    diagnostics_export_retention = max(
        int(os.environ.get("DIAGNOSTICS_EXPORT_RETENTION_COUNT", "50") or 50),
        1,
    )
except (TypeError, ValueError):
    diagnostics_export_retention = 50
diagnostics_export_service = DiagnosticsExportService(
    base_dir=os.path.join("storage", "exports"),
    archive_retention=diagnostics_export_retention,
)

# Setup console logging for app.py
# Note: Runner logs are written to RUNNER_LOG_FILE by runner.py
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# Create formatter
formatter = logging.Formatter(LOG_FORMAT)


def _add_root_handler_once(handler: logging.Handler, handler_id: str) -> None:
    root_logger = logging.getLogger()
    for existing in root_logger.handlers:
        if getattr(existing, "_bybit_handler_id", None) == handler_id:
            return
    setattr(handler, "_bybit_handler_id", handler_id)
    root_logger.addHandler(handler)

# File handler (dashboard/app logs go to app.log; runner writes runner.log)
try:
    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(
        APP_LOG_FILE,
        maxBytes=1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    _add_root_handler_once(file_handler, "app-file")

    # Aggressively silence werkzeug (Flask access logs)
    werkzeug_log = logging.getLogger("werkzeug")
    werkzeug_log.setLevel(logging.ERROR)
    werkzeug_log.disabled = True

    logging.info("App logging configured to file: %s", APP_LOG_FILE)
except Exception as e:
    logging.warning("Failed to configure app file logging: %s", e)


class SymbolColorFormatter(logging.Formatter):
    _LEVEL_NAMES = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    _SYMBOL_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
    _RESET = "\033[0m"
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


log_formatter = logging.Formatter(LOG_FORMAT)
console_handler = logging.StreamHandler()
console_handler.setFormatter(SymbolColorFormatter(LOG_FORMAT))
logging.getLogger().setLevel(logging.INFO)
_add_root_handler_once(console_handler, "app-console")


def _log_skip_order(
    bot_id: str,
    symbol: str,
    side: str,
    raw_qty: float,
    normalized_qty: float,
    min_qty: float,
    qty_step: float,
    price: float,
) -> None:
    notional_qty = normalized_qty if normalized_qty else (raw_qty or 0)
    notional = (price or 0) * notional_qty
    logging.warning(
        "skip_order qty_below_min bot_id=%s symbol=%s side=%s raw_qty=%s normalized_qty=%s "
        "minQty=%s qtyStep=%s price=%s notional=%s",
        bot_id,
        symbol,
        side,
        raw_qty,
        normalized_qty,
        min_qty,
        qty_step,
        price,
        notional,
    )


# =============================================================================
# IP Allowlist Middleware (NEW - Security Hardening)
# =============================================================================
@app.before_request
def check_ip_allowlist():
    """
    Block requests from IPs not in DASH_ALLOW_IPS.
    Localhost only bypasses this check when explicitly configured.
    If DASH_ALLOW_IPS is empty, all IPs are allowed.
    """
    if DASH_ALLOW_IPS:
        client_ip = get_request_client_ip()
        if should_bypass_localhost(client_ip, req=request):
            return None
        if client_ip not in DASH_ALLOW_IPS:
            return Response(
                json.dumps({"error": "ip_not_allowed"}),
                status=403,
                mimetype="application/json",
            )


# Runtime globals are initialized lazily so importing app.py does not create
# live clients, websocket threads, or background sync workers.
cfg: Dict[str, Any] = {}
client = None
order_router = None
stream_service = None
bot_storage = None
symbol_pnl_service = None
symbol_training_service = None
risk_manager = None
pnl_service = None
account_service = None
position_service = None
indicator_service = None
price_prediction_service = None
entry_filter = None
stop_loss_service = None
trend_protection_service = None
take_profit_service = None
danger_zone_service = None
range_engine = None
grid_engine = None
neutral_scanner = None
grid_bot_service = None
bot_manager = None
bot_status_service = None
runtime_settings_service = None
runtime_state_integrity_watchdog_service = None
config_integrity_watchdog_service = None
watchdog_hub_service = None
performance_baseline_service = None
ai_advisor_analytics_service = None
advisor_replay_analysis_service = None
bot_triage_service = None
bot_triage_action_service = None
bot_config_advisor_service = None
custom_bot_preset_service = None
bot_preset_service = None
trade_forensics_service = None
decision_snapshot_service = None
STREAM_SYMBOL_REFRESH_THREAD = None
STREAM_SYMBOL_REFRESH_INTERVAL_SEC = 5.0
BOT_CONFIG_ADVISOR_QUEUE_THREAD = None
BOT_CONFIG_ADVISOR_QUEUE_INTERVAL_SEC = 5.0


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _request_flag(name: str, default: bool = False) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configured_stream_owner() -> str:
    configured_owner = os.environ.get("BYBIT_STREAM_OWNER", "runner").strip().lower()
    if configured_owner in {"", "default"}:
        configured_owner = "runner"
    return configured_owner


def _prefer_runtime_snapshot_bridge() -> bool:
    configured_owner = _configured_stream_owner()
    if configured_owner == "app":
        return False
    market_snapshot = runtime_snapshot_bridge.read_market_snapshot()
    if not isinstance(market_snapshot, dict):
        return False
    if bool(market_snapshot.get("stale_data")):
        return False
    bots_snapshot = runtime_snapshot_bridge.read_section("bots_runtime")
    if not isinstance(bots_snapshot, dict):
        return False
    if bool(bots_snapshot.get("stale_data")):
        return False
    # M2 audit: require positions and open_orders sections to exist and be non-stale
    positions_snapshot = runtime_snapshot_bridge.read_section("positions")
    if not isinstance(positions_snapshot, dict) or bool(positions_snapshot.get("stale_data")):
        return False
    open_orders_snapshot = runtime_snapshot_bridge.read_section("open_orders")
    if not isinstance(open_orders_snapshot, dict) or bool(open_orders_snapshot.get("stale_data")):
        return False
    snapshot_owner = str(
        market_snapshot.get("snapshot_owner")
        or market_snapshot.get("stream_owner")
        or ""
    ).strip().lower()
    bots_owner = str(
        bots_snapshot.get("snapshot_owner")
        or bots_snapshot.get("stream_owner")
        or ""
    ).strip().lower()
    return snapshot_owner == "runner" and bots_owner == "runner"


def _stream_owner_allows(owner_name: str) -> bool:
    if not _env_flag("ENABLE_BYBIT_STREAMS", default=True):
        return False
    configured_owner = _configured_stream_owner()
    if configured_owner == "none":
        return False
    if configured_owner == "both":
        if owner_name == "app":
            return not _prefer_runtime_snapshot_bridge()
        return True
    return configured_owner == owner_name


def _create_app_client_and_stream(runtime_cfg: Dict[str, Any]) -> tuple[Any, Any, Any]:
    runtime_client = BybitClient(
        api_key=runtime_cfg["api_key"],
        api_secret=runtime_cfg["api_secret"],
        base_url=runtime_cfg["base_url"],
    )
    runtime_order_router = OrderRouterService()
    runtime_client.set_order_router(runtime_order_router)

    runtime_stream_service = None
    if _stream_owner_allows("app"):
        try:
            runtime_stream_service = BybitStreamService(
                api_key=runtime_cfg["api_key"],
                api_secret=runtime_cfg["api_secret"],
                base_url=runtime_cfg["base_url"],
                owner_name="app",
            )
            runtime_client.set_stream_service(runtime_stream_service)
            runtime_stream_service.start()
        except Exception as exc:
            logging.warning("Failed to start app websocket streams: %s", exc)
            runtime_stream_service = None

    return runtime_client, runtime_order_router, runtime_stream_service


def _build_app_runtime(runtime_cfg: Dict[str, Any]) -> Dict[str, Any]:
    runtime_client, runtime_order_router, runtime_stream_service = (
        _create_app_client_and_stream(runtime_cfg)
    )

    runtime_bot_storage = BotStorageService(os.path.join("storage", "bots.json"))
    runtime_runtime_settings_service = RuntimeSettingsService(
        os.path.join("storage", "runtime_settings.json")
    )
    runtime_performance_baseline_service = PerformanceBaselineService(
        file_path=os.path.join("storage", "performance_baselines.json"),
        diagnostics_export_service=diagnostics_export_service,
    )
    runtime_symbol_pnl_service = SymbolPnlService(os.path.join("storage", "symbol_pnl.json"))
    runtime_order_ownership_service = OrderOwnershipService(
        os.path.join("storage", "order_ownership.json")
    )
    runtime_trade_forensics_service = TradeForensicsService(
        os.path.join("storage", "trade_forensics.jsonl")
    )
    runtime_decision_snapshot_service = DecisionSnapshotService(
        trade_forensics_service=runtime_trade_forensics_service,
        file_path=os.path.join("storage", "decision_snapshots.json"),
    )
    runtime_client.set_order_ownership_service(runtime_order_ownership_service)
    runtime_client.set_trade_forensics_service(runtime_trade_forensics_service)
    runtime_symbol_training_service = (
        SymbolTrainingService(os.path.join("storage", "training"))
        if SYMBOL_TRAINING_ENABLED
        else None
    )
    runtime_risk_manager = RiskManagerService(
        file_path=os.path.join("storage", "risk_state.json"),
        max_bot_loss_pct=MAX_BOT_LOSS_PCT,
        max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
    )
    runtime_pnl_service = PnlService(
        runtime_client,
        os.path.join("storage", "trade_logs.json"),
        runtime_bot_storage,
        runtime_symbol_pnl_service,
        runtime_order_ownership_service,
        runtime_trade_forensics_service,
        runtime_risk_manager,
        symbol_training_service=runtime_symbol_training_service,
        performance_baseline_service=runtime_performance_baseline_service,
    )

    runtime_account_service = AccountService(runtime_client)
    runtime_position_service = PositionService(runtime_client)
    runtime_indicator_service = IndicatorService(runtime_client)
    runtime_price_prediction_service = PricePredictionService(
        runtime_indicator_service,
        runtime_client,
    )
    runtime_entry_filter = EntryFilterService(
        indicator_service=runtime_indicator_service,
        enable_btc_filter=ENABLE_BTC_CORRELATION_FILTER,
        max_btc_correlation=MAX_ALLOWED_CORRELATION_BTC,
        btc_strong_adx=BTC_STRONG_TREND_ADX_THRESHOLD,
        btc_lookback=BTC_CORRELATION_LOOKBACK,
    )
    runtime_stop_loss_service = StopLossService(
        bybit_client=runtime_client,
        safe_atr_multiplier=SL_SAFE_ATR_MULTIPLIER,
        normal_atr_multiplier=SL_NORMAL_ATR_MULTIPLIER,
        aggressive_atr_multiplier=SL_AGGRESSIVE_ATR_MULTIPLIER,
        min_sl_distance_pct=SL_MIN_DISTANCE_PCT,
        max_sl_distance_pct=SL_MAX_DISTANCE_PCT,
    )
    runtime_trend_protection_service = TrendProtectionService(
        adx_trend_threshold=TREND_ADX_THRESHOLD,
        di_dominance_threshold=TREND_DI_DOMINANCE,
        rsi_trend_threshold=TREND_RSI_THRESHOLD,
        min_confidence_score=TREND_MIN_CONFIDENCE_SCORE,
    )
    runtime_take_profit_service = TakeProfitService(
        safe_tp_multiplier=TP_SAFE_ATR_MULTIPLIER,
        normal_tp_multiplier=TP_NORMAL_ATR_MULTIPLIER,
        aggressive_tp_multiplier=TP_AGGRESSIVE_ATR_MULTIPLIER,
        min_tp_pct=TP_MIN_DISTANCE_PCT,
        max_tp_pct=TP_MAX_DISTANCE_PCT,
    )
    runtime_danger_zone_service = DangerZoneService(
        extreme_rsi_upper=DANGER_RSI_OVERBOUGHT,
        extreme_rsi_lower=DANGER_RSI_OVERSOLD,
        volume_spike_multiplier=DANGER_VOLUME_SPIKE_MULTIPLIER,
        range_extreme_threshold_pct=DANGER_RANGE_EXTREME_PCT,
    )
    runtime_range_engine = RangeEngineService()
    runtime_grid_engine = GridEngineService()
    runtime_neutral_scanner = NeutralScannerService(
        runtime_client,
        runtime_indicator_service,
        runtime_range_engine,
    )
    runtime_grid_bot_service = GridBotService(
        runtime_client,
        runtime_bot_storage,
        runtime_pnl_service,
        runtime_risk_manager,
        runtime_grid_engine,
        runtime_indicator_service,
        runtime_entry_filter,
        runtime_stop_loss_service,
        runtime_trend_protection_service,
        runtime_take_profit_service,
        runtime_danger_zone_service,
        symbol_training_service=runtime_symbol_training_service,
        stream_service=runtime_stream_service,
        runtime_settings_service=runtime_runtime_settings_service,
        trade_forensics_service=runtime_trade_forensics_service,
    )
    runtime_grid_bot_service.neutral_scanner = runtime_neutral_scanner
    runtime_bot_manager = BotManagerService(
        runtime_client,
        runtime_bot_storage,
        runtime_risk_manager,
        runtime_account_service,
    )
    runtime_config_integrity_watchdog_service = ConfigIntegrityWatchdogService(
        runtime_bot_storage,
        runtime_bot_manager.audit_diagnostics_service,
    )
    runtime_bot_status_service = BotStatusService(
        runtime_bot_storage,
        runtime_position_service,
        runtime_pnl_service,
        runtime_symbol_pnl_service,
        neutral_scanner=runtime_neutral_scanner,
        indicator_service=runtime_indicator_service,
        performance_baseline_service=runtime_performance_baseline_service,
    )
    runtime_ai_advisor_analytics_service = AIAdvisorAnalyticsService(
        audit_diagnostics_service=(
            getattr(runtime_grid_bot_service, "audit_diagnostics_service", None)
            or getattr(runtime_pnl_service, "audit_diagnostics_service", None)
        ),
        pnl_service=runtime_pnl_service,
        file_path=os.path.join("storage", "ai_advisor_review.json"),
        performance_baseline_service=runtime_performance_baseline_service,
    )
    runtime_advisor_replay_analysis_service = AdvisorReplayAnalysisService(
        ai_advisor_analytics_service=runtime_ai_advisor_analytics_service,
        runs_root=os.path.join("storage", "backtest_runs"),
        file_path=os.path.join("storage", "advisor_replay_analysis.json"),
        performance_baseline_service=runtime_performance_baseline_service,
    )
    runtime_watchdog_hub_service = WatchdogHubService(
        getattr(runtime_pnl_service, "audit_diagnostics_service", None),
        performance_baseline_service=runtime_performance_baseline_service,
    )
    runtime_runtime_state_integrity_watchdog_service = (
        RuntimeStateIntegrityWatchdogService()
    )
    runtime_bot_triage_service = BotTriageService(
        runtime_watchdog_hub_service,
        runtime_settings_service=runtime_runtime_settings_service,
    )
    runtime_bot_triage_action_service = BotTriageActionService(
        bot_storage=runtime_bot_storage,
        bot_manager=runtime_bot_manager,
        runtime_settings_service=runtime_runtime_settings_service,
        config_integrity_watchdog_service=runtime_config_integrity_watchdog_service,
    )
    runtime_bot_config_advisor_service = BotConfigAdvisorService(
        bot_triage_service=runtime_bot_triage_service,
        bot_storage=runtime_bot_storage,
        bot_manager=runtime_bot_manager,
        runtime_settings_service=runtime_runtime_settings_service,
        config_integrity_watchdog_service=runtime_config_integrity_watchdog_service,
    )
    runtime_custom_bot_preset_service = CustomBotPresetService(
        os.path.join("storage", "custom_bot_presets.json"),
        bot_storage=runtime_bot_storage,
        audit_diagnostics_service=getattr(runtime_bot_manager, "audit_diagnostics_service", None),
    )
    runtime_bot_preset_service = BotPresetService(
        custom_preset_service=runtime_custom_bot_preset_service,
        audit_diagnostics_service=getattr(runtime_bot_manager, "audit_diagnostics_service", None),
    )

    return {
        "cfg": runtime_cfg,
        "client": runtime_client,
        "order_router": runtime_order_router,
        "stream_service": runtime_stream_service,
        "bot_storage": runtime_bot_storage,
        "symbol_pnl_service": runtime_symbol_pnl_service,
        "symbol_training_service": runtime_symbol_training_service,
        "risk_manager": runtime_risk_manager,
        "pnl_service": runtime_pnl_service,
        "account_service": runtime_account_service,
        "position_service": runtime_position_service,
        "indicator_service": runtime_indicator_service,
        "price_prediction_service": runtime_price_prediction_service,
        "entry_filter": runtime_entry_filter,
        "stop_loss_service": runtime_stop_loss_service,
        "trend_protection_service": runtime_trend_protection_service,
        "take_profit_service": runtime_take_profit_service,
        "danger_zone_service": runtime_danger_zone_service,
        "range_engine": runtime_range_engine,
        "grid_engine": runtime_grid_engine,
        "neutral_scanner": runtime_neutral_scanner,
        "grid_bot_service": runtime_grid_bot_service,
        "bot_manager": runtime_bot_manager,
        "bot_status_service": runtime_bot_status_service,
        "runtime_state_integrity_watchdog_service": (
            runtime_runtime_state_integrity_watchdog_service
        ),
        "ai_advisor_analytics_service": runtime_ai_advisor_analytics_service,
        "advisor_replay_analysis_service": runtime_advisor_replay_analysis_service,
        "trade_forensics_service": runtime_trade_forensics_service,
        "decision_snapshot_service": runtime_decision_snapshot_service,
        "runtime_settings_service": runtime_runtime_settings_service,
        "performance_baseline_service": runtime_performance_baseline_service,
        "config_integrity_watchdog_service": runtime_config_integrity_watchdog_service,
        "watchdog_hub_service": runtime_watchdog_hub_service,
        "bot_triage_service": runtime_bot_triage_service,
        "bot_triage_action_service": runtime_bot_triage_action_service,
        "bot_config_advisor_service": runtime_bot_config_advisor_service,
        "custom_bot_preset_service": runtime_custom_bot_preset_service,
        "bot_preset_service": runtime_bot_preset_service,
    }


# Bounded last-known-good hold for stream symbol collection.
# Prevents subscription churn when bridge is briefly empty/stale.
_last_known_stream_symbols: List[str] = []
_last_known_stream_symbols_ts: float = 0.0
_STREAM_SYMBOLS_HOLD_SEC: float = 60.0


def _collect_stream_symbols() -> List[str]:
    global _last_known_stream_symbols, _last_known_stream_symbols_ts
    symbols = set()
    # Use bridge data instead of bot_storage to avoid cache_lock contention.
    # Prefer lightweight section first, fall back to full runtime section.
    bridged = runtime_snapshot_bridge.read_section("bots_runtime_light")
    bots = (bridged or {}).get("bots") or []
    if not bots:
        bridged = runtime_snapshot_bridge.read_section("bots_runtime")
        bots = (bridged or {}).get("bots") or []
    for bot in bots:
        if bot.get("status") != "running":
            continue
        symbol = str(bot.get("symbol") or "").strip().upper()
        if not symbol or symbol == "AUTO-PILOT":
            continue
        symbols.add(symbol)
    result = sorted(symbols)
    if result:
        _last_known_stream_symbols = result
        _last_known_stream_symbols_ts = time.time()
        return result
    # Bridge returned empty — use last-known-good if within hold window.
    if _last_known_stream_symbols and (time.time() - _last_known_stream_symbols_ts) < _STREAM_SYMBOLS_HOLD_SEC:
        return _last_known_stream_symbols
    return []


def _sync_stream_subscriptions_once() -> None:
    if not stream_service or _prefer_runtime_snapshot_bridge():
        return
    symbols = _collect_stream_symbols()
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


def _stream_symbol_refresh_worker() -> None:
    while True:
        try:
            _sync_stream_subscriptions_once()
        except Exception as exc:
            logging.debug("App stream subscription sync failed: %s", exc)
        time.sleep(STREAM_SYMBOL_REFRESH_INTERVAL_SEC)


def _ensure_stream_symbol_thread() -> None:
    global STREAM_SYMBOL_REFRESH_THREAD
    if not stream_service or STREAM_SYMBOL_REFRESH_THREAD:
        return
    worker = threading.Thread(
        target=_stream_symbol_refresh_worker,
        name="AppStreamSymbolSync",
        daemon=True,
    )
    worker.start()
    STREAM_SYMBOL_REFRESH_THREAD = worker


def _bot_config_advisor_queue_worker() -> None:
    while True:
        try:
            bots_snapshot = _get_runtime_bots_snapshot()
            if not bots_snapshot.get("stale_data"):
                _get_bot_config_advisor_service_instance().process_queued_applies(
                    runtime_bots=list((bots_snapshot or {}).get("bots") or []),
                )
        except Exception as exc:
            logging.debug("Bot config advisor queue worker failed: %s", exc)
        time.sleep(BOT_CONFIG_ADVISOR_QUEUE_INTERVAL_SEC)


def _ensure_bot_config_advisor_queue_thread() -> None:
    global BOT_CONFIG_ADVISOR_QUEUE_THREAD
    if BOT_CONFIG_ADVISOR_QUEUE_THREAD and BOT_CONFIG_ADVISOR_QUEUE_THREAD.is_alive():
        return
    worker = threading.Thread(
        target=_bot_config_advisor_queue_worker,
        name="BotConfigAdvisorQueue",
        daemon=True,
    )
    worker.start()
    BOT_CONFIG_ADVISOR_QUEUE_THREAD = worker


def initialize_app_runtime(force: bool = False) -> None:
    global APP_RUNTIME_INITIALIZED
    global APP_RUNTIME_INIT_ERROR
    global cfg
    global client
    global order_router
    global stream_service
    global bot_storage
    global symbol_pnl_service
    global symbol_training_service
    global risk_manager
    global pnl_service
    global account_service
    global position_service
    global indicator_service
    global price_prediction_service
    global entry_filter
    global stop_loss_service
    global trend_protection_service
    global take_profit_service
    global danger_zone_service
    global range_engine
    global grid_engine
    global neutral_scanner
    global grid_bot_service
    global bot_manager
    global bot_status_service
    global ai_advisor_analytics_service
    global advisor_replay_analysis_service
    global trade_forensics_service
    global decision_snapshot_service
    global runtime_settings_service
    global runtime_state_integrity_watchdog_service
    global performance_baseline_service
    global config_integrity_watchdog_service
    global watchdog_hub_service
    global bot_triage_service
    global bot_triage_action_service
    global bot_config_advisor_service
    global custom_bot_preset_service
    global bot_preset_service

    with APP_RUNTIME_INIT_LOCK:
        if APP_RUNTIME_INITIALIZED and not force:
            return

        APP_RUNTIME_INIT_ERROR = None
        runtime_cfg = load_dashboard_config()
        runtime = _build_app_runtime(runtime_cfg)

        cfg = runtime["cfg"]
        client = runtime["client"]
        order_router = runtime["order_router"]
        stream_service = runtime["stream_service"]
        bot_storage = runtime["bot_storage"]
        symbol_pnl_service = runtime["symbol_pnl_service"]
        symbol_training_service = runtime["symbol_training_service"]
        risk_manager = runtime["risk_manager"]
        pnl_service = runtime["pnl_service"]
        account_service = runtime["account_service"]
        position_service = runtime["position_service"]
        indicator_service = runtime["indicator_service"]
        price_prediction_service = runtime["price_prediction_service"]
        entry_filter = runtime["entry_filter"]
        stop_loss_service = runtime["stop_loss_service"]
        trend_protection_service = runtime["trend_protection_service"]
        take_profit_service = runtime["take_profit_service"]
        danger_zone_service = runtime["danger_zone_service"]
        range_engine = runtime["range_engine"]
        grid_engine = runtime["grid_engine"]
        neutral_scanner = runtime["neutral_scanner"]
        grid_bot_service = runtime["grid_bot_service"]
        bot_manager = runtime["bot_manager"]
        bot_status_service = runtime["bot_status_service"]
        runtime_state_integrity_watchdog_service = runtime[
            "runtime_state_integrity_watchdog_service"
        ]
        ai_advisor_analytics_service = runtime["ai_advisor_analytics_service"]
        advisor_replay_analysis_service = runtime["advisor_replay_analysis_service"]
        trade_forensics_service = runtime["trade_forensics_service"]
        decision_snapshot_service = runtime["decision_snapshot_service"]
        runtime_settings_service = runtime["runtime_settings_service"]
        performance_baseline_service = runtime["performance_baseline_service"]
        config_integrity_watchdog_service = runtime["config_integrity_watchdog_service"]
        watchdog_hub_service = runtime["watchdog_hub_service"]
        bot_triage_service = runtime["bot_triage_service"]
        bot_triage_action_service = runtime["bot_triage_action_service"]
        bot_config_advisor_service = runtime["bot_config_advisor_service"]
        custom_bot_preset_service = runtime["custom_bot_preset_service"]
        bot_preset_service = runtime["bot_preset_service"]

        _ensure_stream_symbol_thread()
        _sync_stream_subscriptions_once()

        # Heavy rebuilds removed from web worker init path.
        # symbol_pnl_service.rebuild_from_logs()       — owned by runner.py startup
        # risk_manager.rebuild_symbol_daily_from_logs() — owned by runner.py startup
        # symbol_training_service.rebuild_from_trade_logs() — disabled via SYMBOL_TRAINING_ENABLED=False
        # Web workers read bridge snapshots and cached state; they do not
        # rebuild from raw trade logs.  Run rebuild_symbol_pnl_data() or
        # runner.py restart to refresh after log changes.
        logging.info("Web worker init complete (lightweight — no trade-log rebuilds)")

        APP_RUNTIME_INITIALIZED = True


@app.before_request
def ensure_app_runtime_initialized():
    global APP_RUNTIME_INIT_ERROR
    if APP_RUNTIME_INITIALIZED:
        return None
    try:
        initialize_app_runtime()
    except Exception as exc:
        APP_RUNTIME_INIT_ERROR = exc
        logging.exception("App runtime initialization failed")
        if request.path.startswith("/api/"):
            return Response(
                json.dumps({"error": "app_initialization_failed"}),
                status=503,
                mimetype="application/json",
            )
        return Response("App initialization failed.", status=503, mimetype="text/plain")
    return None


def json_error(message: str, status: int = 400):
    """
    Create a JSON error response.

    Args:
        message: Error message
        status: HTTP status code

    Returns:
        Flask response with JSON error
    """
    resp = jsonify({"error": message})
    resp.status_code = status
    return resp


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_symbol_order_sizing_context(symbol: str) -> Dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    if not _is_tradeable_position_symbol(normalized_symbol):
        return {}

    context: Dict[str, Any] = {
        "symbol": normalized_symbol,
        "reference_price": None,
        "price_source": None,
        "mark_price": None,
        "last_price": None,
        "min_notional": None,
        "min_qty": None,
    }

    try:
        inst_response = client.get_instruments_info(normalized_symbol)
        if inst_response.get("success"):
            inst_list = (inst_response.get("data") or {}).get("list") or []
            if inst_list:
                lot_filter = dict(inst_list[0].get("lotSizeFilter") or {})
                context["min_notional"] = _safe_float(
                    lot_filter.get("minNotionalValue") or lot_filter.get("minOrderAmt"),
                    0.0,
                ) or None
                context["min_qty"] = _safe_float(lot_filter.get("minOrderQty"), 0.0) or None
    except Exception as exc:
        logging.debug("Sizing context instrument lookup failed for %s: %s", normalized_symbol, exc)

    try:
        ticker_response = client.get_tickers(normalized_symbol)
        if ticker_response.get("success"):
            ticker_list = (ticker_response.get("data") or {}).get("list") or []
            if ticker_list:
                ticker = ticker_list[0]
                context["mark_price"] = _safe_float(ticker.get("markPrice"), 0.0) or None
                context["last_price"] = _safe_float(ticker.get("lastPrice"), 0.0) or None
    except Exception as exc:
        logging.debug("Sizing context ticker lookup failed for %s: %s", normalized_symbol, exc)

    if context["mark_price"]:
        context["reference_price"] = context["mark_price"]
        context["price_source"] = "mark_price"
    elif context["last_price"]:
        context["reference_price"] = context["last_price"]
        context["price_source"] = "last_price"

    return context


def _enrich_with_order_sizing_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(payload or {})
    symbol = str(enriched.get("symbol") or "").strip().upper()
    if not _is_tradeable_position_symbol(symbol):
        return enriched
    sizing_context = _get_symbol_order_sizing_context(symbol)
    for key in ("reference_price", "price_source", "mark_price", "last_price", "min_notional", "min_qty"):
        if sizing_context.get(key) is not None and enriched.get(key) is None:
            enriched[key] = sizing_context[key]
    return enriched


def _build_new_bot_order_sizing_validation(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not _is_tradeable_position_symbol(symbol):
        return None

    enriched = _enrich_with_order_sizing_context(payload)
    reference_price = _safe_float(enriched.get("reference_price"), 0.0)
    min_notional = _safe_float(enriched.get("min_notional"), 0.0)
    min_qty = _safe_float(enriched.get("min_qty"), 0.0)
    if reference_price <= 0 or (min_notional <= 0 and min_qty <= 0):
        return None

    order_splits = (
        _safe_int(enriched.get("grid_levels_total"), 0)
        or _safe_int(enriched.get("target_grid_count"), 0)
        or _safe_int(enriched.get("grid_count"), 0)
        or 1
    )
    return build_order_sizing_viability(
        symbol=symbol,
        reference_price=reference_price,
        price_source=enriched.get("price_source"),
        leverage=enriched.get("leverage"),
        investment=enriched.get("investment"),
        order_splits=order_splits,
        min_notional=min_notional,
        min_qty=min_qty,
    )


def _format_order_sizing_block_message(validation: Dict[str, Any]) -> str:
    per_order_qty = validation.get("estimated_per_order_qty")
    min_qty = validation.get("min_qty")
    per_order_notional = validation.get("estimated_per_order_notional")
    effective_min_notional = validation.get("effective_min_order_notional")
    if "below_min_qty" in list(validation.get("blocked_reasons") or []):
        if per_order_qty is not None and min_qty is not None:
            return (
                f"Per-order qty {per_order_qty:.6f} is below exchange min_qty {min_qty:.6f} "
                f"at the current slice size."
            )
        return "Per-order qty would fall below the exchange minimum quantity."
    if per_order_notional is not None and effective_min_notional is not None:
        return (
            f"Per-order notional ${per_order_notional:.2f} is below the effective minimum "
            f"${effective_min_notional:.2f}."
        )
    return "Bot sizing would violate exchange minimum order requirements."


def _set_no_cache_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _maybe_sync_closed_pnl_for_api(force: bool = False) -> None:
    global PNL_API_LAST_SYNC_AT
    global PNL_API_SYNC_THREAD

    now_ts = time.time()
    if not force and (now_ts - PNL_API_LAST_SYNC_AT) < PNL_API_MIN_SYNC_INTERVAL_SEC:
        return

    if force:
        with PNL_API_SYNC_LOCK:
            now_ts = time.time()
            if not force and (now_ts - PNL_API_LAST_SYNC_AT) < PNL_API_MIN_SYNC_INTERVAL_SEC:
                return
            try:
                pnl_service.sync_closed_pnl()
                pnl_service.update_bots_realized_pnl()
                _invalidate_dashboard_snapshots("summary", "bots_runtime")
            except Exception as exc:
                logging.debug("Closed PnL API sync failed: %s", exc)
            finally:
                PNL_API_LAST_SYNC_AT = time.time()
        return

    with PNL_API_SYNC_LOCK:
        now_ts = time.time()
        if (now_ts - PNL_API_LAST_SYNC_AT) < PNL_API_MIN_SYNC_INTERVAL_SEC:
            return
        worker = PNL_API_SYNC_THREAD
        if worker is not None and worker.is_alive():
            return

        def _run_background_sync() -> None:
            global PNL_API_LAST_SYNC_AT
            global PNL_API_SYNC_THREAD
            try:
                pnl_service.sync_closed_pnl()
                pnl_service.update_bots_realized_pnl()
                _invalidate_dashboard_snapshots("summary", "bots_runtime")
            except Exception as exc:
                logging.debug("Closed PnL API sync failed: %s", exc)
            finally:
                with PNL_API_SYNC_LOCK:
                    PNL_API_LAST_SYNC_AT = time.time()
                    PNL_API_SYNC_THREAD = None

        worker = threading.Thread(
            target=_run_background_sync,
            name="PnlApiSync",
            daemon=True,
        )
        PNL_API_SYNC_THREAD = worker
        worker.start()


def _runner_lock_held() -> bool:
    try:
        # Try to acquire the lock using our cross-platform service
        # If it returns a file object, we got the lock (so it wasn't held)
        # If it returns None, someone else holds it
        lock_fd = acquire_process_lock(RUNNER_LOCK_FILE)

        if lock_fd:
            # We acquired it, meaning it WAS NOT held.
            # Close/release it immediately.
            lock_fd.close()
            return False
        else:
            # We failed to acquire it, meaning it IS held.
            return True

    except Exception as e:
        logging.error("Runner lock check failed: %s", e)
        # Assume held on error to be safe
        return True


def _runner_pid_from_lock() -> int | None:
    try:
        if not os.path.exists(RUNNER_LOCK_FILE):
            return None
        with open(RUNNER_LOCK_FILE, "r", encoding="utf-8") as f:
            raw = (f.read() or "").strip()
        if not raw:
            return None
        pid = int(raw)
        return pid if pid > 0 else None
    except Exception:
        return None


def _pid_is_alive(pid: int | None, expected_substring: str | None = None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat=,args="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        row = (result.stdout or "").strip()
        if not row:
            return False
        parts = row.split(None, 1)
        stat = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        if "Z" in stat:
            return False
        if expected_substring and expected_substring not in args:
            return False
        return True
    except Exception:
        return False


def _runner_process_info() -> dict:
    runner_script = os.path.join(os.path.dirname(__file__), "runner.py")
    lock_pid = _runner_pid_from_lock()
    if _pid_is_alive(lock_pid, expected_substring=runner_script):
        return {"active": True, "pid": lock_pid, "source": "lock_pid"}

    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        for line in (result.stdout or "").splitlines():
            row = (line or "").strip()
            if not row:
                continue
            parts = row.split(None, 1)
            if len(parts) != 2:
                continue
            pid_text, args = parts
            if (
                runner_script not in args
                or "bash -c" in args
                or "grep " in args
                or "rg " in args
                or "pgrep " in args
            ):
                continue
            pid = int(pid_text)
            if pid != os.getpid() and _pid_is_alive(
                pid, expected_substring=runner_script
            ):
                return {"active": True, "pid": pid, "source": "ps"}
    except Exception as e:
        logging.debug("Runner PID scan failed: %s", e)

    return {"active": False, "pid": lock_pid, "source": "none"}


def _runner_heartbeat_age_sec(
    bridge_payload: Dict[str, Any] | None,
    runner_info: Dict[str, Any] | None = None,
) -> float | None:
    bridge_payload = bridge_payload or {}
    bridge_ts = float(
        bridge_payload.get("snapshot_published_at")
        or bridge_payload.get("snapshot_produced_at")
        or 0.0
    )
    if bridge_ts > 0:
        return round(max(time.time() - bridge_ts, 0.0), 3)

    last_log_update_ts = 0.0
    try:
        if os.path.exists(RUNNER_LOG_FILE):
            last_log_update_ts = float(os.stat(RUNNER_LOG_FILE).st_mtime or 0.0)
    except Exception:
        last_log_update_ts = 0.0

    if last_log_update_ts > 0:
        return round(max(time.time() - last_log_update_ts, 0.0), 3)

    runner_info = runner_info or _runner_process_info()
    if runner_info.get("active"):
        return 0.0
    return None


def _spawn_runner_process() -> dict:
    runner_script = os.path.join(os.path.dirname(__file__), "runner.py")
    if not os.path.exists(runner_script):
        raise FileNotFoundError(f"runner.py not found at {runner_script}")

    if os.path.exists(RUNNER_STOP_FLAG):
        try:
            os.remove(RUNNER_STOP_FLAG)
        except Exception:
            pass

    python_exe = sys.executable

    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        process = subprocess.Popen(
            [python_exe, runner_script],
            creationflags=DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            cwd=os.path.dirname(__file__) or ".",
        )
    else:
        process = subprocess.Popen(
            [python_exe, runner_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=os.path.dirname(__file__) or ".",
        )

    logging.info("🚀 Runner started with PID %d", process.pid)
    return {"pid": process.pid}


def _ensure_runner_active(reason: str, force: bool = False) -> dict:
    global RUNNER_LAST_SPAWN_AT

    with RUNNER_MONITOR_LOCK:
        runner_process = _runner_process_info()
        runner_lock_held = _runner_lock_held()
        runner_active = bool(runner_process.get("active") or runner_lock_held)
        if runner_active:
            return {
                "active": True,
                "pid": runner_process.get("pid"),
                "detected_via": runner_process.get("source", "lock"),
                "lock_held": runner_lock_held,
                "spawned": False,
            }

        if os.path.exists(RUNNER_STOP_FLAG) and not force:
            return {
                "active": False,
                "pid": runner_process.get("pid"),
                "detected_via": runner_process.get("source", "none"),
                "lock_held": runner_lock_held,
                "spawned": False,
            }

        now_ts = time.time()
        if (now_ts - RUNNER_LAST_SPAWN_AT) < RUNNER_MIN_RESPAWN_INTERVAL_SEC:
            return {
                "active": False,
                "pid": runner_process.get("pid"),
                "detected_via": "respawn_cooldown",
                "lock_held": runner_lock_held,
                "spawned": False,
            }

        spawn_result = _spawn_runner_process()
        RUNNER_LAST_SPAWN_AT = now_ts
        logging.warning("Runner auto-restarted from %s", reason)
        return {
            "active": True,
            "pid": spawn_result.get("pid"),
            "detected_via": "auto_restart",
            "lock_held": True,
            "spawned": True,
        }


def _write_runner_stop_flag(reason: str) -> None:
    os.makedirs(os.path.dirname(RUNNER_STOP_FLAG) or ".", exist_ok=True)
    with open(RUNNER_STOP_FLAG, "w", encoding="utf-8") as f:
        f.write(f"{reason}|{datetime.utcnow().isoformat()}Z\n")


def _remove_runner_stop_flag() -> None:
    if not os.path.exists(RUNNER_STOP_FLAG):
        return
    try:
        os.remove(RUNNER_STOP_FLAG)
    except Exception:
        pass


def _terminate_runner_process(pid: int | None, force: bool = False) -> None:
    if not pid or pid <= 0:
        return

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return

        os.kill(pid, signal.SIGTERM)
        if not force:
            return

        time.sleep(1.0)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception as exc:
        logging.warning("Failed to terminate runner PID %s: %s", pid, exc)


def _request_runner_stop(
    reason: str,
    *,
    force: bool = False,
    wait_sec: float = 0.0,
) -> dict:
    _write_runner_stop_flag(reason)
    if wait_sec > 0:
        time.sleep(wait_sec)

    runner_info = _runner_process_info()
    pid = runner_info.get("pid") or _runner_pid_from_lock()
    if pid:
        _terminate_runner_process(pid, force=force)

    return {
        "pid": pid,
        "active": bool(runner_info.get("active") or _runner_lock_held()),
        "source": runner_info.get("source", "none"),
    }


def _watch_runner_forever():
    while True:
        try:
            _ensure_runner_active("watchdog")
        except Exception as e:
            logging.error("Runner watchdog failed: %s", e)
        time.sleep(RUNNER_WATCHDOG_INTERVAL_SEC)


def _start_runner_watchdog():
    global RUNNER_WATCHDOG_THREAD

    with RUNNER_MONITOR_LOCK:
        if RUNNER_WATCHDOG_THREAD and RUNNER_WATCHDOG_THREAD.is_alive():
            return
        RUNNER_WATCHDOG_THREAD = threading.Thread(
            target=_watch_runner_forever,
            name="runner-watchdog",
            daemon=True,
        )
        RUNNER_WATCHDOG_THREAD.start()


# ============================================================
# Logout Route
# ============================================================


@app.route("/logout")
def logout():
    """
    Logout endpoint - returns 401 to clear Basic Auth credentials.
    Browser will forget cached credentials when it receives 401.
    """
    response = Response(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Logged Out</title>
            <meta http-equiv="refresh" content="1;url=/" />
            <style>
                body { font-family: Arial; background: #0f172a; color: #fff; display: flex;
                       justify-content: center; align-items: center; height: 100vh; margin: 0; }
                .box { text-align: center; }
                h1 { color: #10b981; }
            </style>
        </head>
        <body>
            <div class="box">
                <h1>Logged Out</h1>
                <p>Redirecting to login...</p>
            </div>
        </body>
        </html>
        """,
        status=401,
        mimetype="text/html",
    )
    response.headers["WWW-Authenticate"] = 'Basic realm="Login Required"'
    return response


# ============================================================
# Dashboard Route
# ============================================================


@app.route("/")
@require_basic_auth
def index():
    """Serve the main dashboard."""
    return render_template(
        "dashboard.html",
        env_label=cfg.get("env_label", "Bybit Environment"),
    )


# ============================================================
# Account & Summary APIs
# ============================================================


@app.route("/api/account/overview")
@require_basic_auth
def api_account_overview():
    """Get account overview with risk info."""
    logging.debug("Fetching account overview")
    overview = account_service.get_overview()
    equity = overview.get("equity", 0.0) or 0.0
    risk = risk_manager.check_account_limits(equity)
    overview["risk"] = risk
    return jsonify(overview)


@app.route("/api/transfer", methods=["POST"])
@require_basic_auth
def api_transfer():
    """
    Transfer funds between accounts (e.g., UNIFIED -> FUND).
    """
    data = request.get_json(force=True) or {}
    amount = data.get("amount")
    coin = data.get("coin", "USDT")
    from_type = data.get("from_type", "UNIFIED")
    to_type = data.get("to_type", "FUND")

    if not amount:
        return json_error("amount is required", 400)

    try:
        transfer_id = str(uuid.uuid4())
        result = client.create_internal_transfer(
            transfer_id=transfer_id,
            coin=coin,
            amount=str(amount),
            from_account_type=from_type,
            to_account_type=to_type,
        )

        if result and result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "transfer_id": result.get("result", {}).get("transferId"),
                }
            )
        else:
            msg = result.get("error") if result else "Unknown error"
            return json_error(f"Transfer failed: {msg}", 400)

    except Exception as e:
        logging.error(f"Transfer error: {e}")
        return json_error(str(e), 500)


@app.route("/api/positions")
@require_basic_auth
def api_positions():
    """Get all open positions with matched bot info.

    Pass ?fresh=1 to request a direct refresh when no runner bridge section is
    available or when the app owns the stream.
    """
    want_fresh = request.args.get("fresh", "").strip().lower() in ("1", "true", "yes")
    if want_fresh and position_service is not None:
        # On the live dashboard hot path, prefer any existing runner bridge
        # payload over an app-side direct probe. Old browser tabs can still
        # issue ?fresh=1 requests after SSE connects, and those probes were
        # enough to wedge workers during exchange/storage contention.
        payload = _bridge_hot_path_fresh_payload("positions")
        if payload is None:
            payload = _dashboard_snapshot(
                "positions",
                _build_positions_payload,
                _build_positions_fallback_payload,
                wait_timeout=1.5,
                refresh_ttl=0.5,
            )
    else:
        payload = _get_positions_snapshot()
    return _set_no_cache_headers(jsonify(payload))


def _build_positions_payload(account: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build the enriched positions payload used by both REST and SSE."""
    _sync_stream_subscriptions_once()
    result = position_service.get_positions(skip_cache=True)

    # Get current wallet balance and available balance
    account = account or account_service.get_overview()
    result["wallet_balance"] = (
        account.get("equity")
        or account.get("wallet_balance")
        or account.get("available_balance")
        or 0
    )
    # Ensure available_balance is strictly numeric and non-None
    result["available_balance"] = float(account.get("available_balance", 0) or 0)
    result["realized_pnl"] = account.get("realized_pnl", 0)

    result["unrealized_pnl"] = account.get("unrealized_pnl", 0)

    # Build active-bot lookup by symbol for enrichment. Paused/recovering
    # control states can still own a real exchange position.
    bots = bot_storage.list_bots()
    bot_lookup = {}
    bot_ids_by_symbol = {}
    for bot in bots:
        symbol = bot.get("symbol")
        if symbol and bot.get("status") in LIVE_POSITION_OWNER_STATUSES:
            bot_lookup.setdefault(symbol, []).append(bot)
            bot_ids_by_symbol.setdefault(symbol, []).append(bot.get("id"))

    # Enrich positions with bot data
    for pos in result.get("positions", []):
        symbol = pos.get("symbol")
        matching_bots = bot_lookup.get(symbol, [])
        pos["bot_count_for_symbol"] = len(matching_bots)
        if len(matching_bots) == 1:
            bot = matching_bots[0]
            pos["bot_mode"] = bot.get("mode", "neutral")
            pos["bot_range_mode"] = bot.get("range_mode", "fixed")
            pos["tp_pct"] = bot.get("tp_pct")
            pos["auto_stop"] = bot.get("auto_stop")
            pos["auto_stop_target_usdt"] = bot.get("auto_stop_target_usdt", 0)
            pos["bot_id"] = bot.get("id")
            pos["bot_attribution"] = "unique_running_bot"
            pos["bot_ids"] = [bot.get("id")] if bot.get("id") else []
            pos["bot_modes"] = [bot.get("mode", "neutral")]
            pos["bot_range_modes"] = [bot.get("range_mode", "fixed")]
        else:
            pos["bot_mode"] = None
            pos["bot_range_mode"] = None
            pos["tp_pct"] = None
            pos["auto_stop"] = None
            pos["auto_stop_target_usdt"] = 0
            pos["bot_id"] = None
            pos["bot_attribution"] = (
                "ambiguous_symbol" if len(matching_bots) > 1 else "none"
            )
            pos["bot_ids"] = [bot_id for bot_id in bot_ids_by_symbol.get(symbol, []) if bot_id]
            pos["bot_modes"] = [bot.get("mode", "neutral") for bot in matching_bots]
            pos["bot_range_modes"] = [
                bot.get("range_mode", "fixed") for bot in matching_bots
            ]

    return result


@app.route("/api/summary")
@require_basic_auth
def api_summary():
    """Get combined summary of account, positions, and today's PnL.

    Pass ?fresh=1 to request a direct refresh when no runner bridge section is
    available or when the app owns the stream.
    """
    want_fresh = request.args.get("fresh", "").strip().lower() in ("1", "true", "yes")
    if want_fresh and account_service is not None:
        payload = _bridge_hot_path_fresh_payload("summary")
        if payload is None:
            payload = _dashboard_snapshot(
                "summary",
                _build_summary_payload,
                _build_summary_fallback_payload,
                wait_timeout=1.5,
                refresh_ttl=0.5,
            )
    else:
        payload = _get_summary_snapshot()
    return _set_no_cache_headers(jsonify(payload))


def _build_summary_payload(
    account: Dict[str, Any] | None = None,
    positions_payload: Dict[str, Any] | None = None,
    today: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    _sync_stream_subscriptions_once()
    account = account or account_service.get_overview()
    positions_payload = positions_payload or _build_positions_payload(account=account)
    today = today or pnl_service.get_today_stats()

    # 001-trading-bot-audit FR-011: Add kill-switch status to summary
    risk_state = (
        risk_manager.get_risk_state() if hasattr(risk_manager, "get_risk_state") else {}
    )

    return {
        "account": account,
        "positions_summary": positions_payload.get("summary", {}),
        "today_pnl": today,
        # 001-trading-bot-audit: Kill-switch monitoring fields
        "daily_loss_pct": risk_state.get("daily_loss_pct", 0.0),
        "kill_switch_triggered": risk_state.get("kill_switch_triggered", False),
        "kill_switch_triggered_at": risk_state.get("kill_switch_triggered_at"),
    }


def _compute_bridge_status(summary, positions, bots_snapshot) -> Dict[str, Any]:
    """Per-section health: healthy only when producer alive AND all sections fresh."""
    alive = _is_bridge_producer_alive()
    sum_degraded = bool((summary or {}).get("stale_data"))
    pos_degraded = bool((positions or {}).get("stale_data"))
    bots_degraded = bool((bots_snapshot or {}).get("stale_data"))
    if isinstance((bots_snapshot or {}).get("bots_meta"), dict):
        bots_degraded = bots_degraded or bool(bots_snapshot["bots_meta"].get("stale_data"))
    healthy = alive and not sum_degraded and not pos_degraded and not bots_degraded
    return {
        "producer_alive": alive,
        "healthy": healthy,
        "summary_degraded": sum_degraded,
        "positions_degraded": pos_degraded,
        "bots_degraded": bots_degraded,
    }


def _build_dashboard_payload_from_snapshots(
    reason: str,
    *,
    summary_snapshot: Dict[str, Any],
    positions_snapshot: Dict[str, Any],
    bots_snapshot: Dict[str, Any],
    market_snapshot: Dict[str, Any] | None = None,
    fast: bool = False,
) -> Dict[str, Any]:
    result = {
        "reason": reason,
        "emitted_at": time.time(),
        "summary": summary_snapshot,
        "positions": positions_snapshot,
        "bots": list((bots_snapshot or {}).get("bots") or []),
        "runtime_integrity": (bots_snapshot or {}).get("runtime_integrity"),
        "market_meta": _snapshot_payload_meta(market_snapshot),
        "summary_meta": _snapshot_payload_meta(summary_snapshot),
        "positions_meta": _snapshot_payload_meta(positions_snapshot),
        "bots_meta": _snapshot_payload_meta(bots_snapshot),
    }
    if isinstance(market_snapshot, dict):
        result["market"] = market_snapshot
    if not fast:
        # These are expensive (10-15s each on cold cache) — only include
        # when explicitly requested, never on the SSE hot path.
        result["watchdog_hub"] = _get_cached_or_compute(
            "watchdog_center", 15.0,
            lambda: _build_watchdog_hub_payload(bots_payload=bots_snapshot),
        )
        result["bot_triage"] = _get_cached_or_compute(
            "bot_triage", 30.0, _build_bot_triage_payload,
        )
        result["bot_config_advisor"] = _get_cached_or_compute(
            "bot_config_advisor", 30.0, _build_bot_config_advisor_payload,
        )
    result["_bridge_status"] = _compute_bridge_status(
        summary_snapshot,
        positions_snapshot,
        bots_snapshot,
    )
    return result


def _build_dashboard_stream_payload(reason: str, *, fast: bool = False) -> Dict[str, Any]:
    """Build the SSE dashboard event payload.

    When *fast* is True, use the lightweight bots_runtime_light snapshot
    and skip expensive watchdog/triage/advisor builders so the SSE stream
    can send its first event within ~1 second.
    """
    bots_snapshot = (
        _get_runtime_bots_light_snapshot() if fast
        else _get_runtime_bots_snapshot()
    )
    summary_snapshot = _get_summary_snapshot()
    positions_snapshot = _get_positions_snapshot()
    market_snapshot = runtime_snapshot_bridge.read_market_snapshot()
    return _build_dashboard_payload_from_snapshots(
        reason,
        summary_snapshot=summary_snapshot,
        positions_snapshot=positions_snapshot,
        bots_snapshot=bots_snapshot,
        market_snapshot=market_snapshot,
        fast=fast,
    )


def _log_bootstrap_recovery_timing(
    *,
    timeout_sec: float,
    section_elapsed_ms: Dict[str, float],
    all_fresh: bool,
) -> None:
    now = time.monotonic()
    with BOOTSTRAP_RECOVERY_LOG_LOCK:
        last_logged_at = float(BOOTSTRAP_RECOVERY_LOG_STATE.get("last_logged_at", 0.0))
        if (now - last_logged_at) < 60.0:
            return
        BOOTSTRAP_RECOVERY_LOG_STATE["last_logged_at"] = now

    logging.warning(
        "Dashboard bootstrap degraded recovery path=inline_local all_fresh=%s "
        "timeout_budget_sec=%.1f total_ms=%.1f summary_ms=%.1f positions_ms=%.1f bots_ms=%.1f",
        all_fresh,
        float(timeout_sec or 0.0),
        round(sum(section_elapsed_ms.values()), 1),
        float(section_elapsed_ms.get("summary", 0.0)),
        float(section_elapsed_ms.get("positions", 0.0)),
        float(section_elapsed_ms.get("bots", 0.0)),
    )


def _recover_bootstrap_dashboard_sections(
    *,
    timeout_sec: float = 3.0,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, float]]:
    section_specs = {
        "summary": {
            "cache_key": "summary",
            "builder": lambda: _build_summary_fallback_payload("bootstrap_recovery"),
            "fallback": _build_summary_fallback_payload,
        },
        "positions": {
            "cache_key": "positions",
            "builder": lambda: _build_positions_fallback_payload("bootstrap_recovery"),
            "fallback": _build_positions_fallback_payload,
        },
        "bots": {
            "cache_key": "bots_runtime_light",
            "builder": lambda: _build_runtime_bots_light_fallback("bootstrap_recovery"),
            "fallback": _build_runtime_bots_light_fallback,
        },
    }
    results: Dict[str, Dict[str, Any]] = {}
    section_elapsed_ms: Dict[str, float] = {}
    for section_name, spec in section_specs.items():
        spec = section_specs[section_name]
        section_started = time.monotonic()
        try:
            payload = spec["builder"]()
        except Exception as exc:
            logging.warning(
                "Dashboard bootstrap %s recovery failed: %s",
                section_name,
                exc,
            )
            payload = spec["fallback"]("bootstrap_error")
        finally:
            section_elapsed_ms[section_name] = round(
                (time.monotonic() - section_started) * 1000.0,
                1,
            )
        if isinstance(payload, dict) and not payload.get("stale_data"):
            _store_dashboard_snapshot_entry(spec["cache_key"], payload)
        results[section_name] = payload
    return results, section_elapsed_ms


def _dashboard_emit_interval_for_event(event_type: str) -> float | None:
    normalized = str(event_type or "").strip().lower()
    if normalized in {"execution", "order", "position"}:
        return 0.4
    if normalized == "ticker":
        return 1.5
    return None


@app.route("/api/dashboard/bootstrap")
@require_basic_auth
def api_dashboard_bootstrap():
    """Single fast payload for first page load — critical data only."""
    request_started = time.monotonic()
    phase_ms: Dict[str, float] = {}
    with _runtime_snapshot_bridge_read_diagnostics_context(
        "api_dashboard_bootstrap"
    ) as bridge_reads, _bot_storage_read_diagnostics_context(
        "api_dashboard_bootstrap"
    ) as storage_reads:
        phase_started = time.monotonic()
        # Check if ALL critical bridge sections are usable (alive + fresh)
        # Prefer bots_runtime_light (fast cadence) over bots_runtime (slow).
        summary_bridged = runtime_snapshot_bridge.read_section("summary")
        positions_bridged = runtime_snapshot_bridge.read_section("positions")
        bots_light_bridged = runtime_snapshot_bridge.read_section("bots_runtime_light")
        bots_bridged = (
            bots_light_bridged
            if _bridge_section_usable(bots_light_bridged)
            else runtime_snapshot_bridge.read_section("bots_runtime")
        )
        all_fresh = (
            _bridge_section_usable(summary_bridged)
            and _bridge_section_usable(positions_bridged)
            and _bridge_section_usable(bots_bridged)
        )
        phase_ms["initial_bridge_probe_ms"] = round(
            max(time.monotonic() - phase_started, 0.0) * 1000.0,
            3,
        )

        if all_fresh:
            phase_started = time.monotonic()
            payload = _build_dashboard_stream_payload("bootstrap", fast=True)
            phase_ms["fresh_payload_build_ms"] = round(
                max(time.monotonic() - phase_started, 0.0) * 1000.0,
                3,
            )
            recovery_elapsed_ms = {}
        else:
            # Any section dead/missing/stale — recover with direct builders so the
            # bootstrap path is not capped by the generic 1.5s snapshot timeout.
            phase_started = time.monotonic()
            results, section_elapsed_ms = _recover_bootstrap_dashboard_sections(timeout_sec=3.0)
            phase_ms["recovery_sections_ms"] = round(
                max(time.monotonic() - phase_started, 0.0) * 1000.0,
                3,
            )
            recovery_elapsed_ms = dict(section_elapsed_ms)
            _log_bootstrap_recovery_timing(
                timeout_sec=3.0,
                section_elapsed_ms=section_elapsed_ms,
                all_fresh=all_fresh,
            )
            bots_snapshot = results["bots"]
            phase_started = time.monotonic()
            payload = _build_dashboard_payload_from_snapshots(
                "bootstrap",
                summary_snapshot=results["summary"],
                positions_snapshot=results["positions"],
                bots_snapshot=bots_snapshot,
                market_snapshot=runtime_snapshot_bridge.read_market_snapshot(),
                fast=True,
            )
            phase_ms["recovery_payload_shape_ms"] = round(
                max(time.monotonic() - phase_started, 0.0) * 1000.0,
                3,
            )

        phase_started = time.monotonic()
        try:
            # PnL sync is runner's responsibility — dashboard serves from local logs only
            logs = pnl_service.get_log(use_global_baseline=True)
            today = pnl_service.get_today_stats(use_global_baseline=True)
            payload["pnl"] = {
                "logs": logs[-100:],
                "today": today,
                "performance_baseline": _performance_baseline_metadata(),
            }
        except Exception:
            payload["pnl"] = {"logs": [], "today": {}}
        phase_ms["pnl_payload_ms"] = round(
            max(time.monotonic() - phase_started, 0.0) * 1000.0,
            3,
        )

        request_diag = {
            "route": "dashboard_bootstrap",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "all_fresh": bool(all_fresh),
            "path": "fresh_bridge" if all_fresh else "degraded_recovery",
            "total_ms": round(
                max(time.monotonic() - request_started, 0.0) * 1000.0,
                3,
            ),
            "phase_ms": phase_ms,
            "bridge_reads": dict(bridge_reads),
            "storage_reads": dict(storage_reads),
            "recovery_section_elapsed_ms": recovery_elapsed_ms,
        }
        request_diag["top_phase"] = _top_timing_phase(phase_ms)
        _store_request_diagnostics("dashboard_bootstrap", request_diag)
        _maybe_log_request_diagnostics("dashboard_bootstrap", request_diag)
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bridge/diagnostics")
@require_basic_auth
def api_bridge_diagnostics():
    """Read-only diagnostics for runtime snapshot bridge health."""
    request_started = time.monotonic()
    phase_ms: Dict[str, float] = {}
    with _runtime_snapshot_bridge_read_diagnostics_context(
        "api_bridge_diagnostics"
    ) as bridge_reads, _bot_storage_read_diagnostics_context(
        "api_bridge_diagnostics"
    ) as storage_reads:
        phase_started = time.monotonic()
        snapshot = runtime_snapshot_bridge.read_snapshot()
        phase_ms["bridge_snapshot_read_ms"] = round(
            max(time.monotonic() - phase_started, 0.0) * 1000.0,
            3,
        )
        now = time.time()
        meta = (snapshot.get("meta") or {}) if snapshot else {}
        producer_pid = meta.get("producer_pid")

        phase_started = time.monotonic()
        producer_alive = _pid_is_alive(producer_pid, expected_substring="runner.py")
        phase_ms["producer_alive_check_ms"] = round(
            max(time.monotonic() - phase_started, 0.0) * 1000.0,
            3,
        )

        sections_data = (snapshot.get("sections") or {}) if snapshot else {}

        section_names = ["market", "open_orders", "positions", "bots_runtime", "bots_runtime_light", "summary"]
        stale_thresholds = runtime_snapshot_bridge.READ_STALE_AGE_SEC
        phase_started = time.monotonic()
        sections_diag = {}
        for name in section_names:
            section = sections_data.get(name) or {}
            payload = section.get("payload") or {}
            published_at = float(section.get("published_at") or 0)
            age_sec = round(now - published_at, 2) if published_at > 0 else None
            threshold = stale_thresholds.get(name, 10.0)
            stale = age_sec is None or age_sec > threshold
            shape_valid = runtime_snapshot_bridge._payload_shape_valid(name, payload)
            counts = {}
            if name == "positions":
                counts["positions"] = len(payload.get("positions") or [])
            elif name in ("bots_runtime", "bots_runtime_light"):
                counts["bots"] = len(payload.get("bots") or [])
                counts["bots_scope"] = payload.get("bots_scope")
            elif name == "open_orders":
                counts["orders"] = len(payload.get("orders") or [])
            section_diag = {
                "present": bool(section),
                "published_at": published_at or None,
                "age_sec": age_sec,
                "stale_threshold_sec": threshold,
                "stale": stale,
                "shape_valid": shape_valid,
                "payload_counts": counts,
                "source": section.get("source"),
                "reason": section.get("reason"),
            }
            if name == "bots_runtime_light" and isinstance(
                payload.get("light_runtime_diagnostics"),
                dict,
            ):
                section_diag["light_runtime_diagnostics"] = dict(
                    payload.get("light_runtime_diagnostics") or {}
                )
            sections_diag[name] = section_diag
        phase_ms["sections_assembly_ms"] = round(
            max(time.monotonic() - phase_started, 0.0) * 1000.0,
            3,
        )

        # Include enrichment thread diagnostics if available
        enrichment_diag = {}
        phase_started = time.monotonic()
        if hasattr(runtime_snapshot_bridge, "get_enrichment_diagnostics"):
            try:
                enrichment_diag = runtime_snapshot_bridge.get_enrichment_diagnostics()
            except Exception:
                enrichment_diag = {"error": "unavailable"}
        phase_ms["enrichment_diagnostics_ms"] = round(
            max(time.monotonic() - phase_started, 0.0) * 1000.0,
            3,
        )

        current_request_diag = {
            "route": "bridge_diagnostics",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "total_ms": round(
                max(time.monotonic() - request_started, 0.0) * 1000.0,
                3,
            ),
            "phase_ms": phase_ms,
            "bridge_reads": dict(bridge_reads),
            "storage_reads": dict(storage_reads),
        }
        current_request_diag["top_phase"] = _top_timing_phase(phase_ms)
        _store_request_diagnostics("bridge_diagnostics", current_request_diag)
        _maybe_log_request_diagnostics("bridge_diagnostics", current_request_diag)

        result = {
            "checked_at": now,
            "producer_pid": producer_pid,
            "producer_alive": producer_alive,
            "snapshot_epoch": meta.get("snapshot_epoch"),
            "produced_at": meta.get("produced_at"),
            "sections": sections_diag,
            "enrichment": enrichment_diag,
            "request_diagnostics": {
                "bridge_diagnostics": current_request_diag,
                "last_bootstrap": _get_request_diagnostics("dashboard_bootstrap"),
            },
        }
    return _set_no_cache_headers(jsonify(result))


def _format_sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, separators=(",", ":"))
    return f"event: {event_name}\ndata: {serialized}\n\n"


def _build_snapshot_poll_health_snapshot() -> Dict[str, Any]:
    market_snapshot = runtime_snapshot_bridge.read_market_snapshot()
    if market_snapshot:
        health = market_snapshot.get("health")
        if isinstance(health, dict) and health:
            health = dict(health)
            health.setdefault("snapshot_owner", market_snapshot.get("snapshot_owner"))
            health.setdefault("snapshot_fresh", market_snapshot.get("snapshot_fresh"))
            return health
    configured_owner = _configured_stream_owner()
    return {
        "transport": "snapshot_poll",
        "stream_service": False,
        "stream_owner": configured_owner,
    }


SSE_MAX_LIFETIME_SEC = 120  # Force reconnect to free threads


def _generate_snapshot_poll_events():
    # Send an immediate heartbeat so the SSE connection opens instantly.
    yield _format_sse_event("heartbeat", {"ts": time.time()})

    started = time.time()
    while (time.time() - started) < SSE_MAX_LIFETIME_SEC:
        try:
            payload = _build_dashboard_stream_payload("snapshot_poll", fast=True)
            yield _format_sse_event("dashboard", payload)
        except Exception as exc:
            logging.debug("Snapshot-poll dashboard build failed: %s", exc)
            yield _format_sse_event("heartbeat", {"ts": time.time()})
        time.sleep(DASHBOARD_STREAM_FALLBACK_INTERVAL_SEC)


@app.route("/api/stream/events")
@require_basic_auth
def api_stream_events():
    """Server-sent event bridge for websocket-backed dashboard updates."""
    if not stream_service or _prefer_runtime_snapshot_bridge():
        response = Response(_generate_snapshot_poll_events(), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    _sync_stream_subscriptions_once()
    symbols = _collect_stream_symbols()

    def generate():
        last_seq = stream_service.get_latest_event_seq()
        initial_snapshot = stream_service.get_dashboard_snapshot(symbols)
        last_dashboard_emit_at = 0.0
        try:
            initial_snapshot["dashboard"] = _build_dashboard_stream_payload("snapshot", fast=True)
            last_dashboard_emit_at = time.time()
        except Exception as exc:
            logging.debug("Failed to build initial live dashboard snapshot: %s", exc)
        yield _format_sse_event("snapshot", initial_snapshot)

        started = time.time()
        while (time.time() - started) < SSE_MAX_LIFETIME_SEC:
            events = stream_service.wait_for_events(last_seq, timeout_sec=15.0)
            if not events:
                heartbeat = {
                    "ts": time.time(),
                    "health": stream_service.get_health_snapshot(),
                }
                yield _format_sse_event("heartbeat", heartbeat)
                continue
            for event in events:
                last_seq = event["seq"]
                event_type = str(event.get("type") or "").strip()
                yield _format_sse_event(event_type, event["payload"])
                dashboard_interval = _dashboard_emit_interval_for_event(event_type)
                if dashboard_interval is None:
                    continue
                now_ts = time.time()
                if (now_ts - last_dashboard_emit_at) < dashboard_interval:
                    continue
                try:
                    dashboard_payload = _build_dashboard_stream_payload(event_type, fast=True)
                except Exception as exc:
                    logging.debug(
                        "Failed to build live dashboard snapshot after %s: %s",
                        event_type,
                        exc,
                    )
                    continue
                last_dashboard_emit_at = time.time()
                yield _format_sse_event("dashboard", dashboard_payload)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/api/predictions")
@require_basic_auth
def api_predictions():
    """Get price predictions for all running bots (30s cache)."""

    def _build_predictions():
        predictions = []
        all_bots = bot_storage.list_bots()
        running_bots = [b for b in all_bots if b.get("status") == "running"]

        for bot in running_bots:
            symbol = str(bot.get("symbol") or "").strip().upper()
            if not _is_tradeable_position_symbol(symbol):
                continue

            try:
                result = price_prediction_service.predict(symbol, timeframe="15")
                prediction_data = {
                    "bot_id": bot.get("id"),
                    "symbol": symbol,
                    "mode": bot.get("mode", "neutral"),
                    "direction": result.direction,
                    "confidence": result.confidence,
                    "score": result.score,
                    "signals": [
                        {
                            "name": s.name,
                            "direction": s.direction,
                            "strength": s.strength,
                            "description": s.description,
                        }
                        for s in result.signals[:6]
                    ],
                    "patterns": list(result.pattern_signals.keys())
                    if result.pattern_signals
                    else [],
                    "divergence": result.divergence_signals.get("type")
                    if result.divergence_signals
                    else None,
                    "sr_levels": {
                        "support": result.sr_levels.get("nearest_support", {}).get("price")
                        if result.sr_levels.get("nearest_support")
                        else None,
                        "resistance": result.sr_levels.get("nearest_resistance", {}).get(
                            "price"
                        )
                        if result.sr_levels.get("nearest_resistance")
                        else None,
                    },
                    "trend_structure": result.trend_structure.get("structure", "unknown"),
                    "mtf_alignment": result.timeframe_alignment.get("alignment", "MIXED")
                    if result.timeframe_alignment
                    else "MIXED",
                    "auto_direction": bot.get("auto_direction", False),
                    "direction_score": bot.get("direction_score"),
                    "direction_signals": bot.get("direction_signals"),
                    "funding_signal": bot.get("funding_signal"),
                    "funding_score": bot.get("funding_score"),
                    "orderbook_signal": bot.get("orderbook_signal"),
                    "orderbook_score": bot.get("orderbook_score"),
                    "orderbook_imbalance": bot.get("orderbook_imbalance"),
                    "liquidation_signal": bot.get("liquidation_signal"),
                    "liquidation_score": bot.get("liquidation_score"),
                    "session_signal": bot.get("session_signal"),
                    "session_name": bot.get("session_name"),
                    "mean_reversion_signal": bot.get("mean_reversion_signal"),
                    "mean_reversion_score": bot.get("mean_reversion_score"),
                    "mean_reversion_deviation": bot.get("mean_reversion_deviation"),
                    "oi_signal": bot.get("oi_signal"),
                    "oi_score": bot.get("oi_score"),
                    "whale_signal": bot.get("whale_signal"),
                    "whale_score": bot.get("whale_score"),
                    "whale_bid_walls": bot.get("whale_bid_walls"),
                    "whale_ask_walls": bot.get("whale_ask_walls"),
                    "whale_reason": bot.get("whale_reason"),
                }
                predictions.append(prediction_data)

            except Exception as e:
                logging.warning(f"Failed to get prediction for {symbol}: {e}")
                predictions.append(
                    {
                        "bot_id": bot.get("id"),
                        "symbol": symbol,
                        "mode": bot.get("mode", "neutral"),
                        "direction": "ERROR",
                        "confidence": 0,
                        "score": 0,
                        "error": str(e),
                    }
                )
        return {"predictions": predictions}

    result = _get_cached_or_compute("predictions", 30.0, _build_predictions)
    return jsonify(result)


# ============================================================
# Flash Crash Protection API (Smart Feature #12)
# ============================================================


@app.route("/api/flash-crash-status")
@require_basic_auth
def api_flash_crash_status():
    """
    Get current flash crash protection status.

    Returns:
        JSON with flash crash state:
        - active: bool - whether flash crash protection is active
        - triggered_at: str - ISO timestamp when triggered (or null)
        - normalized_at: str - ISO timestamp when normalized (or null)
        - affected_symbols: list - symbols that triggered crash
        - paused_bots: list - bot IDs paused by flash crash
        - can_resume: bool - whether normalization conditions are met
    """
    from services.flash_crash_service import FlashCrashService

    flash_service = FlashCrashService()
    state = flash_service.get_flash_crash_state()

    return jsonify(
        {
            "active": state.get("flash_crash_active", False),
            "triggered_at": state.get("triggered_at"),
            "normalized_at": state.get("normalized_at"),
            "affected_symbols": state.get("affected_symbols", []),
            "trigger_details": state.get("trigger_details", {}),
            "paused_bots": state.get("paused_bots", []),
        }
    )


# ============================================================
# Position Management APIs
# ============================================================


def _is_tradeable_position_symbol(symbol: str) -> bool:
    symbol_text = str(symbol or "").strip()
    if not symbol_text:
        return False
    manager = globals().get("bot_manager")
    if manager is not None and hasattr(manager, "_is_tradeable_symbol"):
        try:
            return bool(manager._is_tradeable_symbol(symbol_text))
        except Exception:
            return symbol_text.upper() != "AUTO-PILOT"
    return symbol_text.upper() != "AUTO-PILOT"


def _get_live_owner_bots_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    if not symbol or bot_storage is None:
        return []
    try:
        bots = bot_storage.list_bots()
    except Exception:
        return []
    return [
        bot
        for bot in bots
        if bot.get("symbol") == symbol
        and bot.get("status") in LIVE_POSITION_OWNER_STATUSES
    ]


def _build_bot_close_order_link_id(bot_id: str, close_reason: str = "MANL") -> str:
    runtime_grid_service = globals().get("grid_bot_service")
    if runtime_grid_service is not None and hasattr(
        runtime_grid_service, "_build_close_order_link_id"
    ):
        try:
            return runtime_grid_service._build_close_order_link_id(bot_id, close_reason)
        except Exception:
            pass

    import secrets

    bot_short = (str(bot_id or "").replace("-", "")[:8] if bot_id else "xxxxxxxx")
    ts_ms = str(int(time.time() * 1000))[-8:]
    rand_4 = secrets.token_hex(2)
    reason_4 = str(close_reason or "MANL")[:4].upper().ljust(4, "X")
    return f"cls:{bot_short}:{ts_ms}{rand_4}{reason_4}"


def _build_ambiguous_close_order_link_id(position_idx: int = 0) -> str:
    import secrets

    ts_ms = str(int(time.time() * 1000))[-8:]
    rand_4 = secrets.token_hex(2)
    return f"ambg:{ts_ms}:{int(position_idx or 0)}:{rand_4}"


def _close_symbol_positions_for_global_stop(
    symbol: str,
    *,
    ambiguous: bool = False,
) -> Dict[str, Any]:
    if not _is_tradeable_position_symbol(symbol):
        return {"success": True, "message": "skipped_non_tradeable_symbol"}

    try:
        try:
            positions_resp = client.get_positions(skip_cache=True)
        except TypeError:
            positions_resp = client.get_positions()
        if not positions_resp.get("success"):
            return {
                "success": False,
                "error": positions_resp.get("error", "positions_fetch_failed"),
                "retCode": positions_resp.get("retCode", -1),
            }

        positions = positions_resp.get("data", {}).get("list", []) or []
        closed_any = False
        for pos in positions:
            if pos.get("symbol") != symbol:
                continue
            side = pos.get("side")
            try:
                size = float(pos.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0.0
            if not side or size <= 0:
                continue

            close_side = "Sell" if str(side).lower() == "buy" else "Buy"
            try:
                position_idx = int(pos.get("positionIdx", 0) or 0)
            except (TypeError, ValueError):
                position_idx = 0

            order_link_id = (
                _build_ambiguous_close_order_link_id(position_idx)
                if ambiguous
                else None
            )
            ownership_snapshot = (
                build_order_ownership_snapshot(
                    owner_state="ambiguous",
                    source="global_emergency_stop",
                    action="emergency_close",
                    close_reason="EMRG",
                )
                if ambiguous
                else None
            )
            result = client.create_order(
                symbol=symbol,
                side=close_side,
                qty=size,
                order_type="Market",
                price=None,
                reduce_only=True,
                time_in_force="GTC",
                order_link_id=order_link_id,
                position_idx=position_idx,
                ownership_snapshot=ownership_snapshot,
            )
            if result.get("position_empty"):
                logging.info(
                    "[%s] Global stop close skipped for idx=%s: position already flat",
                    symbol,
                    position_idx,
                )
                continue
            if not result.get("success"):
                return result
            closed_any = True

        if not closed_any:
            return {"success": True, "message": "no_position", "retCode": 0}

        return {"success": True, "message": "position_closed", "retCode": 0}
    except Exception as exc:
        logging.error("[%s] Global stop close exception: %s", symbol, exc)
        return {"success": False, "error": str(exc), "retCode": -1}


def _clear_stop_cleanup_pending_fields(bot: Dict[str, Any]) -> None:
    for key in (
        "stop_cleanup_pending",
        "stop_cleanup_target_status",
        "stop_cleanup_scope",
        "stop_cleanup_reason",
        "stop_cleanup_requested_at",
        "stop_cleanup_final_last_error",
    ):
        bot.pop(key, None)


def _mark_global_stop_cleanup_pending(
    bot: Dict[str, Any],
    *,
    action_received_at_ts: float,
) -> Dict[str, Any]:
    pending_iso = iso_from_ts()
    if hasattr(bot_manager, "_mark_control_state_change"):
        bot_manager._mark_control_state_change(bot)
    if hasattr(bot_manager, "_clear_pause_runtime_state"):
        bot_manager._clear_pause_runtime_state(bot)
    _clear_stop_cleanup_pending_fields(bot)
    bot["status"] = "stop_cleanup_pending"
    bot["started_at"] = None
    bot["last_run_at"] = pending_iso
    bot["reduce_only_mode"] = True
    bot["auto_stop_paused"] = True
    bot["pause_reason"] = "Global emergency stop cleanup pending"
    bot["pause_reason_type"] = "stop_cleanup_pending"
    bot["stop_cleanup_pending"] = True
    bot["stop_cleanup_target_status"] = "stopped"
    bot["stop_cleanup_scope"] = "global_emergency_stop"
    bot["stop_cleanup_reason"] = "global_emergency_stop"
    bot["stop_cleanup_requested_at"] = pending_iso
    bot["stop_cleanup_final_last_error"] = None
    bot["last_error"] = "Global emergency stop cleanup pending"
    if hasattr(bot_manager, "_record_control_stage"):
        bot_manager._record_control_stage(
            bot,
            "global_emergency_stop",
            control_action_kind="global_emergency_stop",
            control_action_received_at=iso_from_ts(action_received_at_ts),
            cleanup_pending_persisted_at=pending_iso,
            cleanup_pending=True,
            cleanup_target_status="stopped",
            control_action_to_cleanup_pending_ms=elapsed_ms(
                action_received_at_ts,
                now_ts(),
            ),
        )
    return bot_storage.save_bot(bot)


def _finalize_global_stop_cleanup(bot: Dict[str, Any]) -> Dict[str, Any]:
    finalized_iso = iso_from_ts()
    if hasattr(bot_manager, "_mark_control_state_change"):
        bot_manager._mark_control_state_change(bot)
    if hasattr(bot_manager, "_clear_pause_runtime_state"):
        bot_manager._clear_pause_runtime_state(bot)
    _clear_stop_cleanup_pending_fields(bot)
    bot["status"] = "stopped"
    bot["started_at"] = None
    bot["last_run_at"] = finalized_iso
    bot["reduce_only_mode"] = False
    bot["auto_stop_paused"] = False
    bot["entry_orders_open"] = 0
    bot["exit_orders_open"] = 0
    bot["open_order_count"] = 0
    bot["active_long_slots"] = 0
    bot["active_short_slots"] = 0
    bot["last_error"] = None
    if hasattr(bot_manager, "_record_control_stage"):
        bot_manager._record_control_stage(
            bot,
            "global_emergency_stop",
            cleanup_finalized_at=finalized_iso,
            cleanup_pending=False,
            final_status="stopped",
        )
    return bot_storage.save_bot(bot)


def _confirm_symbol_flat_for_global_stop(symbol: str) -> Dict[str, Any]:
    if hasattr(bot_manager, "_confirm_symbol_flat"):
        try:
            return bot_manager._confirm_symbol_flat(symbol)
        except Exception as exc:
            logging.warning("[%s] Global stop flat confirmation failed: %s", symbol, exc)
    try:
        try:
            positions_resp = client.get_positions(skip_cache=True)
        except TypeError:
            positions_resp = client.get_positions()
        if not positions_resp.get("success"):
            return {
                "success": False,
                "error": positions_resp.get("error", "positions_fetch_failed"),
                "flat": False,
            }
        positions = positions_resp.get("data", {}).get("list", []) or []
        for pos in positions:
            if pos.get("symbol") != symbol:
                continue
            try:
                if float(pos.get("size", 0) or 0) > 0:
                    return {"success": True, "flat": False}
            except (TypeError, ValueError):
                continue
        return {"success": True, "flat": True}
    except Exception as exc:
        return {"success": False, "error": str(exc), "flat": False}


@app.route("/api/emergency-stop", methods=["POST"])
@require_basic_auth
def api_emergency_stop():
    """
    EMERGENCY STOP - Cancel all orders and close all positions immediately.
    Uses aggressive retry logic via BotManager.
    """
    logging.warning("🚨 EMERGENCY STOP TRIGGERED!")
    request_received_at = now_ts()

    results = {"processed": [], "pending": [], "errors": []}

    # 1. First pass: Filter active bots and move them into cleanup-pending state
    # Include all statuses that may have open positions/orders (not just "running")
    all_bots = bot_storage.list_bots()
    active_bots = [
        b
        for b in all_bots
        if b.get("status")
        in (
            "running",
            "paused",
            "recovering",
            "flash_crash_paused",
            "target_hit",
            "risk_stopped",
            "tp_hit",
            "out_of_range",
            "error",
            "stop_cleanup_pending",
        )
    ]

    for bot in active_bots:
        _mark_global_stop_cleanup_pending(
            bot,
            action_received_at_ts=request_received_at,
        )

    success_count = 0
    pending_count = 0
    fail_count = 0
    handled_symbols = set()
    bots_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for bot in active_bots:
        symbol = bot.get("symbol")
        if symbol:
            bots_by_symbol.setdefault(symbol, []).append(bot)

    # 2. Flatten each affected symbol in PARALLEL (A2).
    # Each symbol's cancel+close is independent, so we can run them
    # concurrently to reduce total emergency stop time from N*1s to ~1s.
    def _stop_symbol(symbol: str, symbol_bots: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Stop a single symbol — called concurrently per symbol."""
        try:
            if len(symbol_bots) == 1:
                primary_bot = symbol_bots[0]
                return bot_manager.emergency_stop(
                    primary_bot.get("id"),
                    action_received_at_ts=request_received_at,
                )
            else:
                bot_ids = [bot.get("id") for bot in symbol_bots if bot.get("id")]
                logging.warning(
                    "[%s] Global emergency stop detected %d same-symbol bots; "
                    "closing with explicit ambiguous ownership marker: %s",
                    symbol, len(bot_ids), ",".join(bot_ids),
                )
                if _is_tradeable_position_symbol(symbol):
                    if hasattr(bot_manager, "_force_cancel_all_orders"):
                        cancel_res = bot_manager._force_cancel_all_orders(symbol)
                    else:
                        cancel_res = client.cancel_all_orders(symbol)
                    close_res = _close_symbol_positions_for_global_stop(
                        symbol, ambiguous=True,
                    )
                else:
                    cancel_res = {"success": True, "cancelled": 0, "skipped": True}
                    close_res = {"success": True, "skipped": True}
                flat_confirm = _confirm_symbol_flat_for_global_stop(symbol)
                overall_success = bool(cancel_res.get("success")) and bool(
                    flat_confirm.get("flat")
                )
                res = {
                    "success": overall_success,
                    "cancel": cancel_res,
                    "close": close_res,
                    "flat_confirm": flat_confirm,
                    "cleanup_pending": not overall_success,
                }
                if overall_success:
                    for bot in symbol_bots:
                        _finalize_global_stop_cleanup(bot)
                else:
                    res["error"] = (
                        flat_confirm.get("error")
                        or close_res.get("error")
                        or cancel_res.get("error")
                        or "global_stop_cleanup_pending"
                    )
                return res
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    symbol_futures: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(min(len(bots_by_symbol), 8), 1), thread_name_prefix="estop") as pool:
        for symbol, symbol_bots in bots_by_symbol.items():
            handled_symbols.add(symbol)
            symbol_futures[symbol] = pool.submit(_stop_symbol, symbol, symbol_bots)

        for symbol, future in symbol_futures.items():
            try:
                res = future.result(timeout=25)
            except Exception as exc:
                res = {"success": False, "error": str(exc)}

            if res.get("success"):
                results["processed"].append(symbol)
                success_count += 1
            elif res.get("cleanup_pending"):
                results["pending"].append(symbol)
                pending_count += 1
                logging.warning(
                    "Global emergency stop cleanup still pending for %s: %s",
                    symbol,
                    res.get("error")
                    or res.get("flat_confirm", {}).get("error")
                    or "awaiting flat/order-clear confirmation",
                )
            else:
                err = res.get("error", "Unknown error")
                results["errors"].append(f"{symbol}: {err}")
                fail_count += 1
                logging.error(f"Emergency stop failed for {symbol}: {err}")

    # Orphaned position cleanup
    try:
        positions_resp = client.get_positions()
        if positions_resp.get("success"):
            positions = positions_resp.get("data", {}).get("list", []) or []
            for pos in positions:
                sym = pos.get("symbol")
                size = float(pos.get("size") or 0)
                if size > 0 and sym not in handled_symbols:
                    logging.warning(f"Closing orphaned position for {sym}")
                    close_res = client.close_position(sym)
                    if not close_res.get("success"):
                        logging.error(
                            "Failed orphan close for %s: %s",
                            sym,
                            close_res.get("error"),
                        )
                    client.cancel_all_orders(sym)
    except Exception as ex:
        logging.error(f"Orphaned position cleanup failed: {ex}")

    message = (
        "Emergency stop executed: "
        f"{success_count} symbols stopped, "
        f"{pending_count} pending cleanup, "
        f"{fail_count} errors"
    )
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    request_ack_at = now_ts()
    return jsonify(
        {
            "success": fail_count == 0 and pending_count == 0,
            "message": message,
            "results": results,
            "timing": {
                "control_action_kind": "global_emergency_stop",
                "control_action_received_at": iso_from_ts(request_received_at),
                "control_action_ack_at": iso_from_ts(request_ack_at),
                "control_action_to_ack_ms": elapsed_ms(
                    request_received_at,
                    request_ack_at,
                ),
            },
        }
    )


@app.route("/api/close-position", methods=["POST"])
@require_basic_auth
def api_close_position():
    """
    Close a position by placing a reduce-only market order in the opposite direction.
    Body JSON must contain: { "symbol": "...", "side": "Buy" or "Sell", "size": optional }
    Optional: { "bot_id": "..." } to preserve per-bot attribution on manual closes.
    """
    data = request.get_json(force=True) or {}
    symbol = data.get("symbol")
    side = data.get("side")
    size = data.get("size")
    position_idx = data.get("position_idx")  # Optional explicit idx
    bot_id = str(data.get("bot_id") or "").strip()

    if not symbol or not side:
        return json_error("symbol and side are required", 400)

    # Determine opposite side
    opposite_side = "Sell" if side.lower() == "buy" else "Buy"

    # If size not provided, lookup position to find current size
    position_size = None
    position_price = None
    # Use raw Bybit positions to extract positionIdx reliably (hedge vs one-way)
    try:
        positions_resp = client.get_positions(skip_cache=True)
        if positions_resp.get("success"):
            for pos in positions_resp.get("data", {}).get("list", []) or []:
                if (
                    pos.get("symbol") == symbol
                    and pos.get("side", "").lower() == side.lower()
                ):
                    if size is None:
                        size = pos.get("size")
                    position_size = pos.get("size")
                    position_price = pos.get("markPrice") or pos.get("avgPrice") or 0
                    if position_idx is None:
                        try:
                            position_idx = int(pos.get("positionIdx", 0) or 0)
                        except (TypeError, ValueError):
                            position_idx = 0
                    break
    except Exception as pos_exc:
        logging.warning(
            "api_close_position: failed to fetch raw positions: %s", pos_exc
        )

    try:
        size = float(size or 0)
    except (TypeError, ValueError):
        size = 0.0

    if not size or size <= 0:
        return json_error("position size not found or invalid", 400)

    filters = client.get_qty_filters(symbol)
    min_qty = filters.get("min_qty")
    qty_step = filters.get("qty_step")

    normalized_size = client.normalize_qty(symbol, size, log_skip=False)
    if not normalized_size:
        # Fallback: Refresh positions to get the exact on-chain size
        logging.warning(
            "api_close_position: normalized_size failed for %s size=%s. Retrying with fresh position data.",
            symbol,
            size,
        )

        # 1. Fetch fresh position data
        positions_resp = client.get_positions(skip_cache=True)
        if positions_resp.get("success"):
            fresh_pos = None
            for pos in positions_resp.get("data", {}).get("list", []):
                if (
                    pos.get("symbol") == symbol
                    and pos.get("side", "").lower() == side.lower()
                ):
                    fresh_pos = pos
                    break

            if fresh_pos:
                fresh_size = float(fresh_pos.get("size", 0))
                if fresh_size > 0:
                    logging.info(
                        "api_close_position: Found fresh size %s for %s",
                        fresh_size,
                        symbol,
                    )
                    size = fresh_size
                    # 2. Retry normalization with fresh size
                    normalized_size = client.normalize_qty(symbol, size, log_skip=False)

    if not normalized_size:
        _log_skip_order(
            "api",
            symbol,
            opposite_side,
            size,
            normalized_size if normalized_size is not None else 0.0,
            min_qty if min_qty is not None else 0.0,
            qty_step if qty_step is not None else 0.0,
            position_price if position_price is not None else 0.0,
        )
        return json_error(
            f"CLOSE_FAILED: Size {size} below min_qty {min_qty} or invalid step {qty_step}",
            400,
        )

    owner_bots = _get_live_owner_bots_for_symbol(symbol)
    owner_bot = None
    if bot_id:
        owner_bot = bot_storage.get_bot(bot_id)
        if not owner_bot:
            return json_error("bot_id not found", 400)
        if str(owner_bot.get("symbol") or "").upper() != str(symbol).upper():
            return json_error("bot_id does not match the requested symbol", 400)
    elif len(owner_bots) == 1:
        owner_bot = dict(owner_bots[0])
        bot_id = str(owner_bot.get("id") or "").strip()
    elif len(owner_bots) > 1:
        logging.error(
            "[%s] Refusing manual close without bot_id; %d live bots share the symbol",
            symbol,
            len(owner_bots),
        )
        return json_error(
            "Ambiguous same-symbol bot ownership; manual close requires a unique bot owner",
            409,
        )

    order_link_id = (
        _build_bot_close_order_link_id(bot_id, "MANL")
        if bot_id
        else f"close_manual_{int(time.time() * 1000)}_{position_idx if position_idx is not None else 0}"
    )
    ownership_snapshot = (
        build_order_ownership_snapshot(
            owner_bot,
            source="manual_close",
            action="manual_close" if owner_bot else "manual_close_unowned",
            close_reason="MANL",
        )
        if owner_bot
        else build_order_ownership_snapshot(
            owner_state="manual",
            source="manual_close",
            action="manual_close_unowned",
            close_reason="MANL",
        )
    )

    result = client.create_order(
        symbol=symbol,
        side=opposite_side,
        qty=normalized_size,
        order_type="Market",
        price=None,
        reduce_only=True,
        time_in_force="GTC",
        order_link_id=order_link_id,
        position_idx=position_idx if position_idx is not None else 0,
        qty_is_normalized=True,
        ownership_snapshot=ownership_snapshot,
    )

    # --- Directional reanchor: mark bot for range reset after manual close ---
    _close_ok = result.get("success") or result.get("position_empty")
    if _close_ok and owner_bot:
        from config.strategy_config import DIRECTIONAL_REANCHOR_ON_MANUAL_CLOSE_ENABLED
        if DIRECTIONAL_REANCHOR_ON_MANUAL_CLOSE_ENABLED:
            _d_mode = str(owner_bot.get("mode") or "").lower()
            _d_range = str(owner_bot.get("range_mode") or "dynamic").lower()
            if _d_mode in ("long", "short") and _d_range != "fixed":
                owner_bot["directional_reanchor_pending"] = True
                owner_bot["directional_reanchor_requested_at"] = datetime.utcnow().isoformat() + "Z"
                bot_storage.save_bot(owner_bot)
                logging.info(
                    "[%s] Directional reanchor pending after manual close (mode=%s range=%s)",
                    symbol, _d_mode, _d_range,
                )

    if result.get("position_empty"):
        logging.info("Position already closed before manual close submission: %s", symbol)
        _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
        return jsonify({"success": True, "result": result, "already_closed": True})

    if not result.get("success"):
        error_msg = result.get("error", "unknown error")
        logging.error("Failed to close position %s: %s", symbol, error_msg)
        # Map common Bybit errors to user-friendly messages
        if "not enough" in error_msg.lower() or "insufficient" in error_msg.lower():
            error_msg = f"Insufficient balance to close position. Original: {error_msg}"
        elif "position" in error_msg.lower() and "not exist" in error_msg.lower():
            error_msg = "Position no longer exists or already closed"
        return json_error(f"Close position failed: {error_msg}", 400)

    logging.info("📍 Position closed: symbol=%s side=%s size=%s", symbol, side, size)
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    return jsonify({"success": True, "result": result})


@app.route("/api/set-take-profit", methods=["POST"])
@require_basic_auth
def api_set_take_profit():
    """
    Set take profit for a position.
    Body JSON must contain: { "symbol": "...", "take_profit": float, "position_idx": 0 (optional) }
    """
    data = request.get_json(force=True) or {}
    symbol = data.get("symbol")
    take_profit = data.get("take_profit")
    position_idx = data.get("position_idx", 0)

    if not symbol:
        return json_error("symbol is required", 400)

    if take_profit is None:
        return json_error("take_profit is required", 400)

    try:
        take_profit = float(take_profit)
        position_idx = int(position_idx)
    except (TypeError, ValueError):
        return json_error("invalid take_profit or position_idx value", 400)

    if take_profit <= 0:
        return json_error("take_profit must be positive", 400)

    result = client.set_trading_stop(
        symbol=symbol,
        position_idx=position_idx,
        take_profit=take_profit,
    )

    if not result.get("success"):
        return json_error(
            f"Failed to set take profit: {result.get('error', 'unknown')}", 502
        )

    return jsonify({"success": True, "result": result})


@app.route("/api/set-stop-loss", methods=["POST"])
@require_basic_auth
def api_set_stop_loss():
    """
    Set stop loss for a position.
    Body JSON must contain: { "symbol": "...", "stop_loss": float, "position_idx": 0 (optional) }
    """
    data = request.get_json(force=True) or {}
    symbol = data.get("symbol")
    stop_loss = data.get("stop_loss")
    position_idx = data.get("position_idx", 0)

    if not symbol:
        return json_error("symbol is required", 400)

    if stop_loss is None:
        return json_error("stop_loss is required", 400)

    try:
        stop_loss = float(stop_loss)
        position_idx = int(position_idx)
    except (TypeError, ValueError):
        return json_error("invalid stop_loss or position_idx value", 400)

    if stop_loss <= 0:
        return json_error("stop_loss must be positive", 400)

    result = client.set_trading_stop(
        symbol=symbol,
        position_idx=position_idx,
        stop_loss=stop_loss,
    )

    if not result.get("success"):
        return json_error(
            f"Failed to set stop loss: {result.get('error', 'unknown')}", 502
        )

    return jsonify({"success": True, "result": result})


# ============================================================
# Bot Management APIs
# ============================================================


@app.route("/api/runtime-settings", methods=["GET"])
@require_basic_auth
def api_runtime_settings():
    """Get persisted server-side runtime/dashboard settings."""
    initialize_app_runtime()
    return jsonify(runtime_settings_service.get_settings())


@app.route("/api/runtime-settings", methods=["POST"])
@require_basic_auth
def api_runtime_settings_update():
    """Update persisted server-side runtime/dashboard settings."""
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    if "auto_stop_on_direction_change" not in data:
        return json_error("auto_stop_on_direction_change is required", 400)

    settings = runtime_settings_service.set_auto_stop_on_direction_change(
        data.get("auto_stop_on_direction_change")
    )
    logging.info(
        "Runtime setting updated: auto_stop_on_direction_change=%s",
        bool(settings.get("auto_stop_on_direction_change")),
    )
    return jsonify(settings)


@app.route("/api/performance-baseline")
@require_basic_auth
def api_performance_baseline():
    """Get current performance baseline metadata."""
    initialize_app_runtime()
    bot_id = str(request.args.get("bot_id") or "").strip() or None
    return _set_no_cache_headers(jsonify({"performance_baseline": _performance_baseline_metadata(bot_id=bot_id)}))


@app.route("/api/performance-baseline/reset", methods=["POST"])
@require_basic_auth
def api_reset_performance_baseline():
    """Create a new global measurement baseline without deleting raw history."""
    initialize_app_runtime()
    data = request.get_json(force=True, silent=True) or {}
    note = str(data.get("note") or "").strip() or None
    service = performance_baseline_service
    if service is None:
        return json_error("performance baseline service unavailable", 503)

    archive_snapshot = _build_performance_reset_archive_snapshot(
        scope="global",
        note=note,
    )
    payload = service.reset(
        scope="global",
        note=note,
        snapshot=archive_snapshot,
    )
    _refresh_performance_reset_views(scope="global")
    payload["warnings"] = [
        "Raw trade logs, exchange/account history, and bot config were preserved.",
        "Account-level exchange realized PnL remains unchanged outside Opus Trader derived views.",
    ]
    payload["reset_fields"] = [
        "derived bot realized_pnl",
        "derived bot total_pnl",
        "watchdog active-state registry",
        "baseline-scoped advisor and replay summaries",
    ]
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bots/<bot_id>/performance-baseline/reset", methods=["POST"])
@require_basic_auth
def api_reset_bot_performance_baseline(bot_id: str):
    """Create a new per-bot measurement baseline without deleting raw history."""
    initialize_app_runtime()
    normalized_bot_id = str(bot_id or "").strip()
    if not normalized_bot_id:
        return json_error("bot_id is required", 400)
    stored_bot = bot_storage.get_bot(normalized_bot_id) if bot_storage is not None else None
    if not stored_bot:
        return json_error("bot not found", 404)

    data = request.get_json(force=True, silent=True) or {}
    note = str(data.get("note") or "").strip() or None
    service = performance_baseline_service
    if service is None:
        return json_error("performance baseline service unavailable", 503)

    archive_snapshot = _build_performance_reset_archive_snapshot(
        scope="bot",
        bot_id=normalized_bot_id,
        note=note,
    )
    payload = service.reset(
        scope="bot",
        bot_id=normalized_bot_id,
        note=note,
        snapshot=archive_snapshot,
    )
    _refresh_performance_reset_views(scope="bot", bot_id=normalized_bot_id)
    payload["bot"] = {
        "id": normalized_bot_id,
        "symbol": stored_bot.get("symbol"),
        "mode": stored_bot.get("mode"),
    }
    payload["warnings"] = [
        "Raw trade logs and exchange/account history were preserved.",
        "Only derived Opus Trader performance views for this bot were re-baselined.",
    ]
    payload["reset_fields"] = [
        "target bot derived realized_pnl",
        "target bot derived total_pnl",
        "target bot watchdog active-state entries",
    ]
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bots")
@require_basic_auth
def api_bots():
    """Get all bots (raw storage data)."""
    return jsonify({"bots": bot_storage.list_bots()})


RECENT_SCANS_FILE = os.path.join("storage", "recent_scans.json")


@app.route("/api/recent-scans", methods=["GET"])
@require_basic_auth
def api_recent_scans_get():
    """Get server-persisted recent scanner coins."""
    try:
        if os.path.exists(RECENT_SCANS_FILE):
            with open(RECENT_SCANS_FILE, "r") as f:
                return jsonify(json.load(f))
    except Exception:
        pass
    return jsonify([])


@app.route("/api/recent-scans", methods=["POST"])
@require_basic_auth
def api_recent_scans_save():
    """Save recent scanner coins server-side."""
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return json_error("expected array", 400)
    # Keep only last 20
    trimmed = data[:20]
    try:
        with open(RECENT_SCANS_FILE, "w") as f:
            json.dump(trimmed, f)
    except Exception as exc:
        return json_error(str(exc), 500)
    return jsonify({"ok": True})


@app.route("/api/bots/runtime")
@require_basic_auth
def api_bots_runtime():
    """Get all bots with enriched runtime data."""
    response_started_ts = time.time()
    payload = _annotate_runtime_response_payload(
        _get_runtime_bots_snapshot(),
        response_started_ts=response_started_ts,
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bots/<bot_id>")
@require_basic_auth
def api_bot_config(bot_id):
    """Get one bot's canonical persisted config for editor hydration."""
    bot = bot_storage.get_bot(bot_id)
    if not bot:
        return json_error("bot not found", 404)
    return _set_no_cache_headers(jsonify({"bot": _build_editor_bot_payload(bot)}))


@app.route("/api/watchdog-center")
@require_basic_auth
def api_watchdog_center():
    """Get the live Watchdog Center Hub snapshot (cached 15s for default view)."""
    include_registry = str(request.args.get("active_only") or "").strip().lower() in {
        "0",
        "false",
        "no",
    }
    filters = {
        "severity": request.args.get("severity"),
        "watchdog_type": request.args.get("watchdog_type"),
        "bot_id": request.args.get("bot"),
        "symbol": request.args.get("symbol"),
        "active_only": request.args.get("active_only"),
        "recent_window_sec": request.args.get("recent_window_sec"),
        "recent_limit": request.args.get("limit"),
    }
    has_filters = any(v for v in filters.values())
    if has_filters:
        bots_payload = _get_runtime_bots_snapshot()
        payload = _build_watchdog_hub_payload(
            bots_payload=bots_payload,
            filters=filters,
            include_registry=include_registry,
        )
    else:
        def _compute():
            bp = _get_runtime_bots_snapshot()
            return _build_watchdog_hub_payload(
                bots_payload=bp,
                filters=filters,
                include_registry=include_registry,
            )
        payload = _get_cached_or_compute("watchdog_center", 15.0, _compute)
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bot-triage")
@require_basic_auth
def api_bot_triage():
    """Get compact per-bot operational triage recommendations (cached 30s)."""
    payload = _get_cached_or_compute("bot_triage", 30.0, _build_bot_triage_payload)
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bot-config-advisor")
@require_basic_auth
def api_bot_config_advisor():
    """Get read-only per-bot config tuning recommendations (cached 30s)."""
    payload = _get_cached_or_compute("bot_config_advisor", 30.0, _build_bot_config_advisor_payload)
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/guardian-log")
@require_basic_auth
def api_guardian_log():
    """Get recent Guardian self-healing events."""
    import json as _json
    log_path = os.path.join("storage", "guardian_healing_log.json")
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            events = _json.load(f)
        if not isinstance(events, list):
            events = []
    except (FileNotFoundError, _json.JSONDecodeError):
        events = []
    limit = int(request.args.get("limit") or 50)
    return _set_no_cache_headers(jsonify(events[-limit:]))


@app.route("/api/bot-presets")
@require_basic_auth
def api_bot_presets():
    initialize_app_runtime()
    return _set_no_cache_headers(jsonify(_get_bot_preset_service_instance().list_presets()))


@app.route("/api/bot-presets/recommend", methods=["POST"])
@require_basic_auth
def api_bot_presets_recommend():
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    data = _enrich_with_order_sizing_context(data)
    return _set_no_cache_headers(jsonify(_get_bot_preset_service_instance().recommend(data)))


@app.route("/api/bot-presets/apply-event", methods=["POST"])
@require_basic_auth
def api_bot_presets_apply_event():
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    preset_id = str(data.get("preset_id") or "").strip()
    target_flow = str(data.get("target_flow") or "").strip().lower()
    if not preset_id:
        return json_error("preset_id is required", 400)
    if target_flow != "new_bot_form":
        return json_error("unsupported target_flow", 400)
    recorded = _get_bot_preset_service_instance().record_custom_applied_to_new_form(
        preset_id=preset_id,
        source=data.get("source"),
        symbol=data.get("symbol"),
        mode=data.get("mode"),
    )
    if not recorded:
        return json_error("custom preset apply event requires a custom preset", 400)
    return _set_no_cache_headers(jsonify({"ok": True, "recorded_at": _utc_now_iso()}))


@app.route("/api/custom-bot-presets")
@require_basic_auth
def api_custom_bot_presets():
    initialize_app_runtime()
    items = _get_bot_preset_service_instance().list_presets().get("custom_items") or []
    return _set_no_cache_headers(
        jsonify(
            {
                "generated_at": _utc_now_iso(),
                "total_presets": len(items),
                "items": items,
            }
        )
    )


@app.route("/api/custom-bot-presets", methods=["POST"])
@require_basic_auth
def api_custom_bot_presets_create():
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    try:
        preset = _get_custom_bot_preset_service_instance().create_preset(
            preset_name=data.get("preset_name"),
            fields=dict(data.get("fields") or {}),
            source_bot_id=data.get("source_bot_id"),
            symbol_hint=data.get("symbol_hint"),
            mode_hint=data.get("mode_hint"),
        )
    except ValueError as exc:
        return json_error(str(exc), 400)
    item = _get_bot_preset_service_instance().get_preset(str(preset.get("preset_id") or ""))
    return _set_no_cache_headers(jsonify({"ok": True, "preset": item}))


@app.route("/api/custom-bot-presets/from-bot/<bot_id>", methods=["POST"])
@require_basic_auth
def api_custom_bot_presets_from_bot(bot_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    try:
        preset = _get_custom_bot_preset_service_instance().create_from_bot(
            bot_id,
            preset_name=data.get("preset_name"),
        )
    except ValueError as exc:
        error = str(exc)
        if error == "bot_not_found":
            return json_error("bot not found", 404)
        return json_error(error, 400)
    item = _get_bot_preset_service_instance().get_preset(str(preset.get("preset_id") or ""))
    return _set_no_cache_headers(jsonify({"ok": True, "preset": item}))


@app.route("/api/custom-bot-presets/<preset_id>", methods=["DELETE"])
@require_basic_auth
def api_custom_bot_presets_delete(preset_id: str):
    initialize_app_runtime()
    deleted = _get_custom_bot_preset_service_instance().delete_preset(preset_id)
    if not deleted:
        return json_error("preset not found", 404)
    return _set_no_cache_headers(
        jsonify(
            {
                "ok": True,
                "preset_id": str(preset_id or ""),
                "deleted_at": _utc_now_iso(),
            }
        )
    )


@app.route("/api/custom-bot-presets/<preset_id>", methods=["PATCH"])
@require_basic_auth
def api_custom_bot_presets_patch(preset_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    normalized_preset_id = str(preset_id or "").strip().lower()
    if normalized_preset_id in BotPresetService.PRESET_ORDER:
        preset = _get_bot_preset_service_instance().get_preset(normalized_preset_id)
        response = {
            "error": "built-in presets cannot be renamed",
            "blocked_reason": "built_in_preset_rename_refused",
            "preset_id": str(preset.get("preset_id") or normalized_preset_id or ""),
            "preset_name": str(preset.get("name") or ""),
            "preset_type": "built_in",
        }
        return _set_no_cache_headers(jsonify(response)), 400
    try:
        preset = _get_custom_bot_preset_service_instance().update_preset(
            preset_id,
            preset_name=data.get("preset_name"),
            symbol_hint=data.get("symbol_hint"),
            mode_hint=data.get("mode_hint"),
        )
    except ValueError as exc:
        error = str(exc)
        if error == "preset_not_found":
            return json_error("preset not found", 404)
        return json_error(error, 400)
    item = _get_bot_preset_service_instance().get_preset(str(preset.get("preset_id") or ""))
    return _set_no_cache_headers(jsonify({"ok": True, "preset": item}))


@app.route("/api/bot-config-advisor/queued-applies")
@require_basic_auth
def api_bot_config_advisor_queued_applies():
    initialize_app_runtime()
    return _set_no_cache_headers(jsonify(_get_bot_config_advisor_service_instance().list_queued_applies()))


@app.route("/api/bot-config-advisor/<bot_id>/apply", methods=["POST"])
@require_basic_auth
def api_bot_config_advisor_apply(bot_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    service = _get_bot_config_advisor_service_instance()
    preview_only = bool(data.get("preview"))
    runtime_bot = _get_runtime_bot_by_id(bot_id)
    try:
        if preview_only:
            return _set_no_cache_headers(jsonify(service.preview_apply(bot_id, runtime_bot=runtime_bot)))
        payload = service.apply_recommendation(
            bot_id,
            incoming_settings_version=data.get("settings_version"),
            runtime_bot=runtime_bot,
            ui_path="config_advisor",
        )
        return _set_no_cache_headers(jsonify(payload))
    except BotTriageSettingsConflictError as exc:
        return (
            _set_no_cache_headers(
                jsonify(
                    {
                        "ok": False,
                        "error": "settings_version_conflict",
                        "message": "Bot settings changed in another editor or window. Reload and try again.",
                        "bot_id": bot_id,
                        "blocked_reason": "settings_version_conflict",
                        "current_settings_version": exc.current_settings_version,
                        "incoming_settings_version": exc.incoming_settings_version,
                        "conflict_reason": exc.conflict_reason,
                    }
                )
            ),
            409,
        )
    except BotConfigAdvisorApplyBlockedError as exc:
        status_code = 409 if exc.blocked_reason == "requires_flat_state" else 400
        return _set_no_cache_headers(jsonify(exc.payload)), status_code
    except ValueError as exc:
        if str(exc) == "bot_not_found":
            return _set_no_cache_headers(jsonify({"ok": False, "error": "bot_not_found"})), 404
        return _set_no_cache_headers(jsonify({"ok": False, "error": str(exc) or "invalid_request"})), 400


@app.route("/api/bot-config-advisor/<bot_id>/queue-apply", methods=["POST"])
@require_basic_auth
def api_bot_config_advisor_queue_apply(bot_id: str):
    initialize_app_runtime()
    service = _get_bot_config_advisor_service_instance()
    runtime_bot = _get_runtime_bot_by_id(bot_id)
    try:
        payload = service.queue_apply(bot_id, runtime_bot=runtime_bot)
        return _set_no_cache_headers(jsonify(payload))
    except BotConfigAdvisorApplyBlockedError as exc:
        status_code = 409 if exc.blocked_reason in {"already_flat_apply_now", "requires_flat_state"} else 400
        return _set_no_cache_headers(jsonify(exc.payload)), status_code
    except ValueError as exc:
        if str(exc) == "bot_not_found":
            return _set_no_cache_headers(jsonify({"ok": False, "error": "bot_not_found"})), 404
        return _set_no_cache_headers(jsonify({"ok": False, "error": str(exc) or "invalid_request"})), 400


@app.route("/api/bot-config-advisor/<bot_id>/cancel-queued-apply", methods=["POST"])
@require_basic_auth
def api_bot_config_advisor_cancel_queued_apply(bot_id: str):
    initialize_app_runtime()
    try:
        payload = _get_bot_config_advisor_service_instance().cancel_queued_apply(bot_id)
        return _set_no_cache_headers(jsonify(payload))
    except ValueError as exc:
        if str(exc) == "bot_not_found":
            return _set_no_cache_headers(jsonify({"ok": False, "error": "bot_not_found"})), 404
        return _set_no_cache_headers(jsonify({"ok": False, "error": str(exc) or "invalid_request"})), 400


@app.route("/api/bot-triage/<bot_id>/apply-preset", methods=["POST"])
@require_basic_auth
def api_bot_triage_apply_preset(bot_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    service = _get_bot_triage_action_service_instance()
    preset = str(data.get("preset") or "").strip().lower()
    preview_only = bool(data.get("preview"))
    try:
        if preview_only:
            return _set_no_cache_headers(
                jsonify(
                    {
                        "bot_id": bot_id,
                        "preset": preset,
                        "preview": service.preview_preset(bot_id, preset),
                    }
                )
            )
        payload = service.apply_preset(
            bot_id,
            preset=preset,
            incoming_settings_version=data.get("settings_version"),
            ui_path="triage",
        )
        _invalidate_dashboard_runtime_views()
        return _set_no_cache_headers(jsonify(payload))
    except BotTriageSettingsConflictError as exc:
        return (
            jsonify(
                {
                    "error": "settings_version_conflict",
                    "message": "Bot settings changed in another editor or window. Reload and try again.",
                    "bot_id": exc.bot_id,
                    "current_settings_version": exc.current_settings_version,
                    "incoming_settings_version": exc.incoming_settings_version,
                    "conflict_reason": exc.conflict_reason,
                }
            ),
            409,
        )
    except ValueError as exc:
        if str(exc) == "bot_not_found":
            return json_error("bot not found", 404)
        if str(exc) == "unsupported_preset":
            return json_error("unsupported preset", 400)
        return json_error(str(exc), 400)


@app.route("/api/bot-triage/<bot_id>/pause-action", methods=["POST"])
@require_basic_auth
def api_bot_triage_pause_action(bot_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    try:
        payload = _get_bot_triage_action_service_instance().pause_action(
            bot_id,
            cancel_pending_requested=bool(data.get("cancel_pending")),
        )
        _invalidate_dashboard_runtime_views()
        return _set_no_cache_headers(jsonify(payload))
    except ValueError:
        return json_error("bot not found", 404)


@app.route("/api/bot-triage/<bot_id>/dismiss", methods=["POST"])
@require_basic_auth
def api_bot_triage_dismiss(bot_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    try:
        payload = _get_bot_triage_action_service_instance().dismiss(
            bot_id,
            verdict=data.get("verdict"),
        )
        _invalidate_dashboard_snapshots("bots_runtime", "summary")
        return _set_no_cache_headers(jsonify(payload))
    except ValueError:
        return json_error("bot not found", 404)


@app.route("/api/bot-triage/<bot_id>/snooze", methods=["POST"])
@require_basic_auth
def api_bot_triage_snooze(bot_id: str):
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    try:
        payload = _get_bot_triage_action_service_instance().snooze(
            bot_id,
            verdict=data.get("verdict"),
            duration=str(data.get("duration") or "1h"),
        )
        _invalidate_dashboard_snapshots("bots_runtime", "summary")
        return _set_no_cache_headers(jsonify(payload))
    except ValueError:
        return json_error("bot not found", 404)


def _build_ai_advisor_recent_payload(
    *,
    limit: int = 50,
    since_seconds: float = 86400.0,
    bot_id: str | None = None,
    symbol: str | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    analytics_service = ai_advisor_analytics_service
    if analytics_service is None:
        return {"decisions": []}
    return analytics_service.get_recent_reviews(
        limit=limit,
        since_seconds=since_seconds,
        bot_id=bot_id,
        symbol=symbol,
        force_refresh=force_refresh,
    )


def _build_ai_advisor_summary_payload(
    *,
    since_seconds: float = 604800.0,
    bot_id: str | None = None,
    symbol: str | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    analytics_service = ai_advisor_analytics_service
    if analytics_service is None:
        return {"summary": {}}
    return analytics_service.get_summary(
        since_seconds=since_seconds,
        bot_id=bot_id,
        symbol=symbol,
        force_refresh=force_refresh,
    )


def _build_ai_advisor_calibration_payload(
    *,
    since_seconds: float = 604800.0,
    bot_id: str | None = None,
    symbol: str | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    analytics_service = ai_advisor_analytics_service
    if analytics_service is None:
        return {"calibration": {}}
    return analytics_service.get_calibration(
        since_seconds=since_seconds,
        bot_id=bot_id,
        symbol=symbol,
        force_refresh=force_refresh,
    )


def _build_ai_advisor_health_payload() -> Dict[str, Any]:
    advisor_service = getattr(grid_bot_service, "ai_advisor_service", None)
    if advisor_service is None:
        return {"health": {}}

    health = dict(advisor_service.get_health() or {})
    aggregate = {
        "enabled_bot_count": 0,
        "bot_call_count": 0,
        "bot_error_count": 0,
        "bot_timeout_count": 0,
        "bot_cached_hits": 0,
        "last_bot_error_count": 0,
    }
    try:
        bots = bot_storage.list_bots() if bot_storage is not None else []
    except Exception:
        bots = []
    for bot in bots:
        if bool(bot.get("ai_advisor_enabled", False)):
            aggregate["enabled_bot_count"] += 1
        aggregate["bot_call_count"] += int(bot.get("ai_advisor_call_count", 0) or 0)
        aggregate["bot_error_count"] += int(bot.get("ai_advisor_error_count", 0) or 0)
        aggregate["bot_timeout_count"] += int(bot.get("ai_advisor_timeout_count", 0) or 0)
        aggregate["bot_cached_hits"] += int(bot.get("ai_advisor_cached_hits", 0) or 0)
        if str(bot.get("ai_advisor_last_error") or "").strip():
            aggregate["last_bot_error_count"] += 1
    health["bot_aggregate"] = aggregate
    return {"health": health}


def _build_ai_advisor_replay_recent_payload(
    *,
    limit: int = 50,
    symbol: str | None = None,
    mode: str | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    service = advisor_replay_analysis_service
    if service is None:
        return {"recent": []}
    return service.get_recent(
        limit=limit,
        symbol=symbol,
        mode=mode,
        force_refresh=force_refresh,
    )


def _build_ai_advisor_replay_summary_payload(
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    service = advisor_replay_analysis_service
    if service is None:
        return {"summary": {}}
    return service.get_summary(force_refresh=force_refresh)


def _wrap_diagnostics_export_payload(
    export_type: str,
    data: Dict[str, Any],
    *,
    generated_at: str | None = None,
) -> Dict[str, Any]:
    return {
        "generated_at": generated_at or _utc_now_iso(),
        "export_type": export_type,
        "app_name": "Opus Trader",
        "source": "server_export",
        "data": dict(data or {}),
        "performance_baseline": _performance_baseline_metadata(),
    }


def _build_ai_layer_export_payload(*, generated_at: str | None = None) -> Dict[str, Any]:
    return _wrap_diagnostics_export_payload(
        "ai_layer",
        {
            "ai_advisor_recent": _build_ai_advisor_recent_payload(),
            "ai_advisor_summary": _build_ai_advisor_summary_payload(),
            "ai_advisor_calibration": _build_ai_advisor_calibration_payload(),
            "ai_advisor_health": _build_ai_advisor_health_payload(),
            "ai_advisor_replay_recent": _build_ai_advisor_replay_recent_payload(),
            "ai_advisor_replay_summary": _build_ai_advisor_replay_summary_payload(),
        },
        generated_at=generated_at,
    )


def _build_watchdog_export_payload(
    *,
    generated_at: str | None = None,
) -> Dict[str, Any]:
    bots_payload = _get_runtime_bots_snapshot()
    data = {
        "watchdog_center": _build_watchdog_hub_payload(
            bots_payload=bots_payload,
            include_registry=True,
        ),
        "bot_status": _build_bot_status_payload(),
        "bots_runtime": bots_payload,
        "summary": _get_summary_snapshot(),
    }
    data.update(_build_watchdog_export_optional_payload())
    return _wrap_diagnostics_export_payload(
        "watchdog",
        data,
        generated_at=generated_at,
    )


def _build_all_diagnostics_export_payload(
    *,
    generated_at: str | None = None,
) -> Dict[str, Any]:
    generated_at = generated_at or _utc_now_iso()
    ai_layer_payload = _build_ai_layer_export_payload(generated_at=generated_at)
    watchdog_payload = _build_watchdog_export_payload(generated_at=generated_at)
    return _wrap_diagnostics_export_payload(
        "all_diagnostics",
        {
            "ai_layer": ai_layer_payload.get("data", {}),
            "watchdog": watchdog_payload.get("data", {}),
        },
        generated_at=generated_at,
    )


def _save_diagnostics_export(payload: Dict[str, Any]) -> Dict[str, Any]:
    generated_at = str(payload.get("generated_at") or _utc_now_iso())
    metadata = diagnostics_export_service.write_export(
        str(payload.get("export_type") or "diagnostics"),
        payload,
        generated_at=generated_at,
    )
    metadata["ok"] = True
    return metadata


def _build_editor_bot_payload(bot: Dict[str, Any]) -> Dict[str, Any]:
    editor_bot = dict(bot or {})
    editor_bot["mode"] = configured_mode(editor_bot)
    editor_bot["range_mode"] = configured_range_mode(editor_bot)
    return editor_bot


def _diagnostics_export_download_response(payload: Dict[str, Any]) -> Response:
    metadata = _save_diagnostics_export(payload)
    text = diagnostics_export_service.serialize_payload(payload)
    filename = diagnostics_export_service.build_download_filename(
        str(payload.get("export_type") or "diagnostics"),
        generated_at=str(payload.get("generated_at") or _utc_now_iso()),
        payload=payload,
    )
    response = Response(text, mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["X-Opus-Export-Type"] = str(metadata.get("export_type") or "")
    response.headers["X-Opus-Export-Filename"] = filename
    response.headers["X-Opus-Archive-Path"] = str(metadata.get("archive_path") or "")
    response.headers["X-Opus-Latest-Path"] = str(metadata.get("latest_path") or "")
    response.headers["X-Opus-Bytes-Written"] = str(metadata.get("bytes_written") or 0)
    return _set_no_cache_headers(response)


@app.route("/api/ai-advisor/recent")
@require_basic_auth
def api_ai_advisor_recent():
    """Get recent AI advisor review records with linked outcome status."""
    try:
        limit = max(1, min(int(request.args.get("limit", 50) or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        since_seconds = max(float(request.args.get("since_seconds", 86400) or 86400), 0.0)
    except (TypeError, ValueError):
        since_seconds = 86400.0
    payload = _build_ai_advisor_recent_payload(
        limit=limit,
        since_seconds=since_seconds,
        bot_id=request.args.get("bot") or None,
        symbol=request.args.get("symbol") or None,
        force_refresh=_request_flag("refresh"),
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/ai-advisor/summary")
@require_basic_auth
def api_ai_advisor_summary():
    """Get compact advisor outcome and usage summary."""
    try:
        since_seconds = max(float(request.args.get("since_seconds", 604800) or 604800), 0.0)
    except (TypeError, ValueError):
        since_seconds = 604800.0
    payload = _build_ai_advisor_summary_payload(
        since_seconds=since_seconds,
        bot_id=request.args.get("bot") or None,
        symbol=request.args.get("symbol") or None,
        force_refresh=_request_flag("refresh"),
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/ai-advisor/calibration")
@require_basic_auth
def api_ai_advisor_calibration():
    """Get correlational calibration metrics for advisor verdicts."""
    try:
        since_seconds = max(float(request.args.get("since_seconds", 604800) or 604800), 0.0)
    except (TypeError, ValueError):
        since_seconds = 604800.0
    payload = _build_ai_advisor_calibration_payload(
        since_seconds=since_seconds,
        bot_id=request.args.get("bot") or None,
        symbol=request.args.get("symbol") or None,
        force_refresh=_request_flag("refresh"),
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/ai-advisor/health")
@require_basic_auth
def api_ai_advisor_health():
    return _set_no_cache_headers(jsonify(_build_ai_advisor_health_payload()))


@app.route("/api/ai-advisor/replay-analysis/recent")
@require_basic_auth
def api_ai_advisor_replay_analysis_recent():
    try:
        limit = max(1, min(int(request.args.get("limit", 50) or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    payload = _build_ai_advisor_replay_recent_payload(
        limit=limit,
        symbol=request.args.get("symbol") or None,
        mode=request.args.get("mode") or None,
        force_refresh=_request_flag("refresh"),
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/ai-advisor/replay-analysis/summary")
@require_basic_auth
def api_ai_advisor_replay_analysis_summary():
    payload = _build_ai_advisor_replay_summary_payload(
        force_refresh=_request_flag("refresh")
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/ai-advisor/replay-analysis/by-symbol")
@require_basic_auth
def api_ai_advisor_replay_analysis_by_symbol():
    service = advisor_replay_analysis_service
    if service is None:
        return _set_no_cache_headers(jsonify({"rows": []}))
    payload = service.get_by_symbol(force_refresh=_request_flag("refresh"))
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/ai-advisor/replay-analysis/by-mode")
@require_basic_auth
def api_ai_advisor_replay_analysis_by_mode():
    service = advisor_replay_analysis_service
    if service is None:
        return _set_no_cache_headers(jsonify({"rows": []}))
    payload = service.get_by_mode(force_refresh=_request_flag("refresh"))
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/export/ai-layer")
@require_basic_auth
def api_export_ai_layer():
    return _diagnostics_export_download_response(_build_ai_layer_export_payload())


@app.route("/api/export/watchdog")
@require_basic_auth
def api_export_watchdog():
    return _diagnostics_export_download_response(_build_watchdog_export_payload())


@app.route("/api/export/all-diagnostics")
@require_basic_auth
def api_export_all_diagnostics():
    return _diagnostics_export_download_response(
        _build_all_diagnostics_export_payload()
    )


@app.route("/api/forensics/recent")
@require_basic_auth
def api_trade_forensics_recent():
    service = trade_forensics_service
    if service is None:
        return _set_no_cache_headers(jsonify({"events": []}))
    try:
        limit = max(1, min(int(request.args.get("limit", 50) or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        since_seconds = max(float(request.args.get("since_seconds", 86400) or 86400), 0.0)
    except (TypeError, ValueError):
        since_seconds = 86400.0
    payload = {
        "events": service.get_recent_events(
            since_seconds=since_seconds,
            bot_id=request.args.get("bot"),
            symbol=request.args.get("symbol"),
            event_type=request.args.get("event_type"),
            limit=limit,
        )
    }
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/forensics/lifecycles")
@require_basic_auth
def api_trade_forensics_lifecycles():
    service = trade_forensics_service
    if service is None:
        return _set_no_cache_headers(jsonify({"lifecycles": []}))
    try:
        limit = max(1, min(int(request.args.get("limit", 20) or 20), 100))
    except (TypeError, ValueError):
        limit = 20
    try:
        since_seconds = max(float(request.args.get("since_seconds", 604800) or 604800), 0.0)
    except (TypeError, ValueError):
        since_seconds = 604800.0
    payload = {
        "lifecycles": service.get_recent_lifecycles(
            since_seconds=since_seconds,
            bot_id=request.args.get("bot"),
            symbol=request.args.get("symbol"),
            limit=limit,
        )
    }
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/forensics/summary")
@require_basic_auth
def api_trade_forensics_summary():
    service = trade_forensics_service
    if service is None:
        return _set_no_cache_headers(jsonify({"summary": {}}))
    try:
        since_seconds = max(float(request.args.get("since_seconds", 604800) or 604800), 0.0)
    except (TypeError, ValueError):
        since_seconds = 604800.0
    payload = {
        "summary": service.get_summary(
            since_seconds=since_seconds,
            bot_id=request.args.get("bot"),
            symbol=request.args.get("symbol"),
        )
    }
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/decision-snapshots/recent")
@require_basic_auth
def api_decision_snapshots_recent():
    service = decision_snapshot_service
    if service is None:
        return _set_no_cache_headers(jsonify({"snapshots": []}))
    try:
        limit = max(1, min(int(request.args.get("limit", 50) or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        since_seconds = max(float(request.args.get("since_seconds", 604800) or 604800), 0.0)
    except (TypeError, ValueError):
        since_seconds = 604800.0
    payload = service.get_recent_snapshots(
        limit=limit,
        since_seconds=since_seconds,
        bot_id=request.args.get("bot"),
        symbol=request.args.get("symbol"),
        status_filter=request.args.get("status"),
        force_refresh=_request_flag("refresh"),
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/decision-snapshots/<snapshot_id>")
@require_basic_auth
def api_decision_snapshot_detail(snapshot_id: str):
    service = decision_snapshot_service
    if service is None:
        return _set_no_cache_headers(jsonify({"snapshot": None}))
    payload = service.get_snapshot(
        snapshot_id,
        force_refresh=_request_flag("refresh"),
    )
    response = jsonify(payload)
    response.status_code = 200 if payload.get("snapshot") is not None else 404
    return _set_no_cache_headers(response)


@app.route("/api/decision-snapshots/summary")
@require_basic_auth
def api_decision_snapshots_summary():
    service = decision_snapshot_service
    if service is None:
        return _set_no_cache_headers(jsonify({"summary": {}}))
    try:
        since_seconds = max(float(request.args.get("since_seconds", 604800) or 604800), 0.0)
    except (TypeError, ValueError):
        since_seconds = 604800.0
    payload = service.get_summary(
        since_seconds=since_seconds,
        bot_id=request.args.get("bot"),
        symbol=request.args.get("symbol"),
        status_filter=request.args.get("status"),
        force_refresh=_request_flag("refresh"),
    )
    return _set_no_cache_headers(jsonify(payload))


@app.route("/api/bots", methods=["POST"])
@require_basic_auth
def api_bots_save():
    """Create or update a bot."""
    data = request.get_json(force=True) or {}
    try:
        preset_name = str(data.pop("_creation_preset_name", "") or "").strip().lower()
        preset_source = str(data.pop("_creation_preset_source", "") or "").strip().lower()
        recommended_preset = str(data.pop("_creation_preset_recommended", "") or "").strip().lower()
        preset_fields = [
            str(field).strip()
            for field in list(data.pop("_creation_preset_fields", []) or [])
            if str(field).strip()
        ]
        ui_path = (
            str(request.headers.get("X-Bot-Config-Path") or data.get("_config_ui_path") or "")
            .strip()
            .lower()
            or "unknown"
        )
        symbol = str(data.get("symbol") or "").strip().upper()
        mode = (data.get("mode") or "neutral").strip().lower()
        range_mode = (data.get("range_mode") or "fixed").strip().lower()
        is_auto_pilot = bool(data.get("auto_pilot"))
        existing_bot = None
        existing_bot_id = str(data.get("id") or "").strip()
        if existing_bot_id:
            existing_bot = bot_storage.get_bot(existing_bot_id)
            if existing_bot:
                current_settings_version = int(existing_bot.get("settings_version") or 0)
                incoming_settings_version = data.get("settings_version")
                try:
                    incoming_settings_version = int(incoming_settings_version)
                except (TypeError, ValueError):
                    incoming_settings_version = None
                if incoming_settings_version is None or incoming_settings_version != current_settings_version:
                    # Auto-resolve for UI saves — the runner's save_bot() can
                    # clobber settings_version between modal open and save.
                    # Use the current version from storage so the save proceeds.
                    if ui_path in ("quick", "main"):
                        data["settings_version"] = current_settings_version
                        app.logger.info(
                            "Auto-resolved settings_version conflict for %s "
                            "(incoming=%s, current=%s, ui_path=%s)",
                            existing_bot_id,
                            incoming_settings_version,
                            current_settings_version,
                            ui_path,
                        )
                    else:
                        conflict_reason = (
                            "missing_incoming_version"
                            if incoming_settings_version is None
                            else "stale_incoming_version"
                        )
                        audit_service = config_integrity_watchdog_service or ConfigIntegrityWatchdogService(
                            bot_storage,
                            getattr(bot_manager, "audit_diagnostics_service", None),
                        )
                        audit_service.record_settings_version_conflict(
                            data,
                            existing_bot,
                            ui_path=ui_path,
                            conflict_reason=conflict_reason,
                            incoming_settings_version=incoming_settings_version,
                            current_settings_version=current_settings_version,
                        )
                        return (
                            jsonify(
                                {
                                    "error": "settings_version_conflict",
                                    "message": "Bot settings changed in another editor or window. Reload and try again.",
                                    "bot_id": existing_bot_id,
                                    "current_settings_version": current_settings_version,
                                    "incoming_settings_version": incoming_settings_version,
                                    "conflict_reason": conflict_reason,
                                }
                            ),
                            409,
                        )

        lower_price = _safe_float(data.get("lower_price"))
        upper_price = _safe_float(data.get("upper_price"))
        if symbol and not is_auto_pilot and (
            lower_price <= 0 or upper_price <= 0 or lower_price >= upper_price
        ):
            range_result = _build_ai_range_suggestion(symbol, mode, range_mode)
            data["lower_price"] = range_result["lower"]
            data["upper_price"] = range_result["upper"]
            if mode == "neutral_classic_bybit":
                data["grid_lower_price"] = range_result["lower"]
                data["grid_upper_price"] = range_result["upper"]

        if not existing_bot and preset_name:
            session_time_error = _get_bot_preset_service_instance().validate_new_bot_session_time_requirement(
                preset_id=preset_name,
                session_timer_enabled=data.get("session_timer_enabled"),
                session_start_at=data.get("session_start_at"),
                session_stop_at=data.get("session_stop_at"),
            )
            if session_time_error is not None:
                return jsonify(session_time_error), 400

        if not existing_bot and not is_auto_pilot:
            sizing_validation = _build_new_bot_order_sizing_validation(data)
            if sizing_validation is not None and not sizing_validation.get("viable"):
                return (
                    jsonify(
                        {
                            "error": _format_order_sizing_block_message(sizing_validation),
                            "blocked_reason": sizing_validation.get("blocked_reason"),
                            "validation_type": "exchange_order_sizing",
                            "sizing_validation": sizing_validation,
                            "estimated_per_order_qty": sizing_validation.get("estimated_per_order_qty"),
                            "min_qty": sizing_validation.get("min_qty"),
                            "estimated_per_order_notional": sizing_validation.get("estimated_per_order_notional"),
                            "min_notional": sizing_validation.get("min_notional"),
                            "effective_min_order_notional": sizing_validation.get("effective_min_order_notional"),
                            "price_source": sizing_validation.get("price_source"),
                            "reference_price": sizing_validation.get("reference_price"),
                        }
                    ),
                    400,
                )

        if not existing_bot:
            preset_item = (
                _get_bot_preset_service_instance().get_preset(preset_name)
                if preset_name
                else None
            )
            data["creation_preset_id"] = preset_name or None
            data["creation_preset_name"] = (
                str((preset_item or {}).get("name") or "").strip() or None
            )
            data["creation_preset_type"] = (
                str((preset_item or {}).get("preset_type") or "").strip().lower()
                or None
            )
            data["creation_preset_source"] = preset_source or None
            data["creation_preset_recommended"] = recommended_preset or None
            data["creation_preset_fields"] = preset_fields

        bot = bot_manager.create_or_update_bot(data)
        persisted_bot = bot_storage.get_bot(str(bot.get("id") or "").strip()) or bot
        audit_service = config_integrity_watchdog_service or ConfigIntegrityWatchdogService(
            bot_storage,
            getattr(bot_manager, "audit_diagnostics_service", None),
        )
        config_integrity_audit = audit_service.record_save_roundtrip(
            data,
            bot,
            persisted_bot=persisted_bot,
            previous_bot=existing_bot,
            ui_path=ui_path,
        )
        config_boolean_audit = {
            "checked_fields": list(config_integrity_audit.get("checked_fields") or []),
            "missing": sorted(
                set(config_integrity_audit.get("missing_expected_fields") or [])
                | set(config_integrity_audit.get("missing_in_response") or [])
                | set(config_integrity_audit.get("missing_in_persisted") or [])
            ),
            "mismatches": list(config_integrity_audit.get("persisted_mismatches") or []),
        }
        global _FORCE_RUNTIME_REBUILD_UNTIL
        _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
        _FORCE_RUNTIME_REBUILD_UNTIL = time.time() + 4.0
        if (
            not existing_bot
            and recommended_preset
            and recommended_preset != preset_name
        ):
            _get_bot_preset_service_instance().record_recommendation_overridden(
                selected_preset=preset_name or "manual_blank",
                recommended_preset=recommended_preset,
                symbol=str(bot.get("symbol") or "").strip().upper(),
                mode=str(bot.get("mode") or "").strip().lower(),
                investment=bot.get("investment"),
            )
        if not existing_bot and preset_name and preset_name != "manual_blank":
            _get_bot_preset_service_instance().record_created_from_preset(
                preset_name=preset_name,
                preset_source=preset_source,
                bot=bot,
                key_fields=preset_fields,
            )
        return jsonify(
            {
                "bot": bot,
                "config_boolean_audit": config_boolean_audit,
                "config_integrity_audit": config_integrity_audit,
            }
        )
    except ValueError as e:
        return json_error(str(e), 400)


@app.route("/api/config-integrity/report", methods=["POST"])
@require_basic_auth
def api_config_integrity_report():
    """Record client-observed config/runtime integrity mismatches."""
    initialize_app_runtime()
    data = request.get_json(force=True) or {}
    event_type = str(data.get("event_type") or "").strip()
    if not event_type:
        return json_error("event_type is required", 400)

    audit_service = config_integrity_watchdog_service or ConfigIntegrityWatchdogService(
        bot_storage,
        getattr(bot_manager, "audit_diagnostics_service", None),
    )
    recorded = audit_service.record_client_report(data)
    if not recorded:
        return json_error("unsupported config integrity event", 400)

    _invalidate_dashboard_snapshots("bots_runtime", "summary")
    return jsonify({"ok": True, "recorded": True})


@app.route("/api/bots/start", methods=["POST"])
@require_basic_auth
def api_bots_start():
    """Start a bot (with pre-launch validation)."""
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)
    request_received_at = now_ts()

    try:
        bot = bot_manager.start_bot(bot_id, action_received_at_ts=request_received_at)
        if not bot:
            return json_error("bot not found", 404)
        _get_runtime_state_integrity_watchdog_service().record_start_accepted(bot)
        _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
        logging.info("▶️ Bot started: id=%s symbol=%s", bot_id, bot.get("symbol"))
        request_ack_at = now_ts()
        return jsonify(
            {
                "bot": bot,
                "timing": {
                    "control_action_kind": "start",
                    "control_action_received_at": iso_from_ts(request_received_at),
                    "control_action_ack_at": iso_from_ts(request_ack_at),
                    "control_action_to_ack_ms": elapsed_ms(
                        request_received_at,
                        request_ack_at,
                    ),
                },
            }
        )
    except ValueError as e:
        # Pre-launch validation failed
        logging.warning(f"Bot start rejected: {bot_id} - {str(e)}")
        return json_error(str(e), 403)  # 403 Forbidden for risk limit violations


@app.route("/api/bots/pause", methods=["POST"])
@require_basic_auth
def api_bots_pause():
    """Pause a bot."""
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)
    bot = bot_manager.pause_bot(bot_id)
    if not bot:
        return json_error("bot not found", 404)
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    logging.info("⏸️ Bot paused: id=%s symbol=%s", bot_id, bot.get("symbol"))
    return jsonify({"bot": bot})


@app.route("/api/bots/soft-stop", methods=["POST"])
@require_basic_auth
def api_bots_soft_stop():
    """Stop a bot without cancelling orders or closing positions."""
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)
    bot = bot_manager.soft_stop_bot(bot_id)
    if not bot:
        return json_error("bot not found", 404)
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    logging.info("⏹️ Bot soft-stopped (orders preserved): id=%s symbol=%s", bot_id, bot.get("symbol"))
    return jsonify({"bot": bot})


@app.route("/api/bots/resume", methods=["POST"])
@require_basic_auth
def api_bots_resume():
    """Resume a paused bot."""
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)
    try:
        bot = bot_manager.resume_bot(bot_id)
        if not bot:
            return json_error("bot not found", 404)
        _get_runtime_state_integrity_watchdog_service().record_start_accepted(bot)
        _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
        return jsonify({"bot": bot})
    except ValueError as e:
        logging.warning(f"Bot resume rejected: {bot_id} - {str(e)}")
        return json_error(str(e), 403)


@app.route("/api/bots/reduce-only", methods=["POST"])
@require_basic_auth
def api_bots_reduce_only():
    """
    Set a bot into reduce-only mode (skip new entries, allow closes).
    Body JSON: { "id": "...", "reduce_only": true/false, "auto_stop_paused": true/false }
    """
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)

    reduce_only = bool(data.get("reduce_only", True))
    auto_stop_paused = bool(data.get("auto_stop_paused", reduce_only))

    bot = bot_storage.get_bot(bot_id)
    if not bot:
        return json_error("bot not found", 404)

    # M5: Cancel orders BEFORE persisting reduce_only flag so the runner
    # cannot read the saved flag while old opening orders are still live.
    cancel_result = None
    symbol = bot.get("symbol")
    if reduce_only and bot_manager._is_tradeable_symbol(symbol):
        cancel_result = bot_manager._cancel_opening_orders_preserve_exits(bot, symbol)

    bot["reduce_only_mode"] = reduce_only
    bot["auto_stop_paused"] = auto_stop_paused
    bot_manager._mark_control_state_change(bot)
    bot = bot_storage.save_bot(bot)
    logging.info(
        "🛑 Bot %s reduce_only_mode=%s auto_stop_paused=%s cancelled_opening_orders=%s",
        bot_id,
        reduce_only,
        auto_stop_paused,
        int((cancel_result or {}).get("cancelled", 0) or 0),
    )
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    return jsonify(
        {
            "bot": bot,
            "reduce_only_mode": reduce_only,
            "cancel_result": cancel_result,
        }
    )


@app.route("/api/bots/stop", methods=["POST"])
@require_basic_auth
def api_bots_stop():
    """Stop a bot and cancel its orders AND close positions."""
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)
    request_received_at = now_ts()

    # Use emergency_stop to both stop the bot AND close positions/cancel orders
    res = bot_manager.emergency_stop(bot_id, action_received_at_ts=request_received_at)

    if not res.get("success"):
        # If emergency stop failed totally (no bot), return 404
        if "not found" in res.get("error", "").lower():
            return json_error("bot not found", 404)

        current_bot = bot_storage.get_bot(bot_id)
        if current_bot and (
            current_bot.get("status") == "stop_cleanup_pending"
            or current_bot.get("stop_cleanup_pending")
            or res.get("cleanup_pending")
        ):
            logging.warning(
                "Bot stop cleanup pending: id=%s symbol=%s details=%s",
                bot_id,
                current_bot.get("symbol"),
                res,
            )
            _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
            request_ack_at = now_ts()
            return jsonify(
                {
                    "bot": current_bot,
                    "result": res,
                    "warning": "stop_cleanup_pending",
                    "timing": {
                        "control_action_kind": "stop",
                        "control_action_received_at": iso_from_ts(request_received_at),
                        "control_action_ack_at": iso_from_ts(request_ack_at),
                        "control_action_to_ack_ms": elapsed_ms(
                            request_received_at,
                            request_ack_at,
                        ),
                    },
                }
            )

        # If bot state is already stopped, treat as success-with-warning.
        # This prevents false "failed" UX when cleanup is partial but stop state is applied.
        if current_bot and current_bot.get("status") == "stopped":
            logging.warning(
                "Bot stop partially completed: id=%s symbol=%s details=%s",
                bot_id,
                current_bot.get("symbol"),
                res,
            )
            _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
            request_ack_at = now_ts()
            return jsonify(
                {
                    "bot": current_bot,
                    "result": res,
                    "warning": "stop_partially_completed",
                    "timing": {
                        "control_action_kind": "stop",
                        "control_action_received_at": iso_from_ts(request_received_at),
                        "control_action_ack_at": iso_from_ts(request_ack_at),
                        "control_action_to_ack_ms": elapsed_ms(
                            request_received_at,
                            request_ack_at,
                        ),
                    },
                }
            )

        # Otherwise return the error from emergency stop
        if res.get("error") == "shared_symbol_active_bots":
            return json_error(
                "Cannot stop and close this symbol while other active bots share it",
                409,
            )
        return json_error(
            res.get("error", "Failed to stop bot and close positions"), 500
        )

    # Get the latest bot state to return
    bot = bot_storage.get_bot(bot_id)
    logging.info(
        "⏹️ Bot stopped and position closed: id=%s symbol=%s",
        bot_id,
        bot.get("symbol") if bot else "unknown",
    )
    request_ack_at = now_ts()
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    return jsonify(
        {
            "bot": bot,
            "result": res,
            "timing": {
                "control_action_kind": "stop",
                "control_action_received_at": iso_from_ts(request_received_at),
                "control_action_ack_at": iso_from_ts(request_ack_at),
                "control_action_to_ack_ms": elapsed_ms(
                    request_received_at,
                    request_ack_at,
                ),
            },
        }
    )


@app.route("/api/bots/delete", methods=["POST"])
@require_basic_auth
def api_bots_delete():
    """Delete a bot."""
    data = request.get_json(force=True) or {}
    bot_id = data.get("id")
    if not bot_id:
        return json_error("id is required", 400)
    global _FORCE_RUNTIME_REBUILD_UNTIL
    try:
        ok = bot_manager.delete_bot(bot_id)
    except ValueError as e:
        return json_error(str(e), 409)
    if not ok:
        return json_error("bot not found", 404)
    logging.info("🗑️ Bot deleted: id=%s", bot_id)
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    _FORCE_RUNTIME_REBUILD_UNTIL = time.time() + 4.0
    return jsonify({"deleted": True})


@app.route("/api/bots/delete-all", methods=["POST"])
@require_basic_auth
def api_bots_delete_all():
    """Delete all bots."""
    bots = bot_storage.list_bots()
    deleted_count = 0
    active_statuses = {
        "running", "paused", "recovering", "flash_crash_paused",
        "stop_cleanup_pending", "out_of_range",
    }
    for bot in bots:
        bot_id = bot.get("id")
        if bot_id:
            # Stop bot first if in any active status
            if bot.get("status") in active_statuses:
                bot_manager.stop_bot(bot_id)
            # Delete bot (now safe since C2 enforces stopped state)
            try:
                if bot_manager.delete_bot(bot_id):
                    deleted_count += 1
            except ValueError:
                # If delete is blocked, force-stop then retry
                bot_manager.stop_bot(bot_id)
                try:
                    if bot_manager.delete_bot(bot_id):
                        deleted_count += 1
                except ValueError as e:
                    logging.warning("Could not delete bot %s: %s", bot_id, e)
    global _FORCE_RUNTIME_REBUILD_UNTIL
    logging.info("🗑️ All bots deleted: count=%d", deleted_count)
    _invalidate_dashboard_snapshots("bots_runtime", "positions", "summary")
    _FORCE_RUNTIME_REBUILD_UNTIL = time.time() + 4.0
    return jsonify({"deleted": True, "deleted_count": deleted_count})


@app.route("/api/bots/<bot_id>/logs", methods=["GET"])
@require_basic_auth
def api_bot_logs(bot_id):
    """Fetch logs for a specific bot (filtered by bot id token first, then symbol)."""
    bot = bot_storage.get_bot(bot_id)
    if not bot:
        return json_error("Bot not found", 404)

    symbol = bot.get("symbol", "")
    bot_id_short = str(bot_id)[:6]
    limit = request.args.get("limit", 200, type=int)

    logs = []
    if os.path.exists(RUNNER_LOG_FILE):
        try:
            with open(RUNNER_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                # Naive approach: read all, filter.
                # For 1MB file, this is < 0.1s.
                lines = f.readlines()

            # Filter logs relevant to this bot.
            # Primary match: runner cycle token [SYMBOL:abcdef]
            # Fallback match: symbol-only markers from lifecycle logs.
            bracket_term = f"[{symbol}]"
            paren_term = f"({symbol})"
            symbol_bot_term = f"[{symbol}:{bot_id_short}]"
            bot_id_term = str(bot_id)

            strict_logs = []
            fallback_logs = []
            for line in lines:
                clean = line.strip()
                if symbol_bot_term in line or bot_id_term in line:
                    strict_logs.append(clean)
                elif not symbol or bracket_term in line or paren_term in line:
                    fallback_logs.append(clean)

            logs = strict_logs if strict_logs else fallback_logs

            # Return last N
            logs = logs[-limit:]

        except Exception as e:
            logging.error(f"Error reading logs for {bot_id}: {e}")
            logs.append(f"Error reading logs: {str(e)}")
    else:
        logs.append("Log file not found.")

    resp = jsonify({"logs": logs})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/bots/<bot_id>/grid", methods=["GET"])
@require_basic_auth
def api_bot_grid(bot_id):
    """Fetch grid visualization data for a specific bot."""
    bot = bot_storage.get_bot(bot_id)
    if not bot:
        return json_error("Bot not found", 404)

    symbol = bot.get("symbol", "")
    if not symbol:
        return json_error("Bot has no symbol", 400)

    # Get grid levels from bot config
    lower_price = bot.get("lower_price", 0)
    upper_price = bot.get("upper_price", 0)
    grid_count = bot.get("grid_count", 10)
    current_price = bot.get("current_price", 0)
    mode = bot.get("mode", "neutral")
    range_mode = bot.get("range_mode", "fixed")

    # Calculate grid levels
    grid_levels = []
    if lower_price and upper_price and grid_count > 0:
        step = (upper_price - lower_price) / grid_count
        for i in range(grid_count + 1):
            grid_levels.append(round(lower_price + (i * step), 8))

    if not _is_tradeable_position_symbol(symbol):
        return _set_no_cache_headers(
            jsonify(
                {
                    "symbol": symbol,
                    "current_price": current_price,
                    "lower_price": lower_price,
                    "upper_price": upper_price,
                    # Compatibility aliases for older dashboard consumers.
                    "lower_bound": lower_price,
                    "upper_bound": upper_price,
                    "grid_count": grid_count,
                    "grid_levels": grid_levels,
                    "orders": [],
                    "position": None,
                    "mode": mode,
                    "range_mode": range_mode,
                    "range_key_family": (
                        "grid_price"
                        if str(mode or "").strip().lower() == "neutral_classic_bybit"
                        else "price"
                    ),
                    "placeholder_symbol": True,
                }
            )
        )

    # Refresh current price from ticker if needed
    market_price = current_price
    try:
        from services.bybit_client import BybitClient

        ticker_resp = client.get_tickers(symbol)
        if ticker_resp.get("success"):
            tick = ticker_resp.get("data", {}).get("list", [{}])[0]
            market_price = float(tick.get("lastPrice", 0) or market_price)
    except Exception as e:
        logging.warning(f"Failed to fetch ticker for grid viz: {e}")
    # Get open orders from exchange (use global client)
    orders = []
    try:
        orders_resp = client.get_open_orders(symbol, skip_cache=True)
        if orders_resp.get("success"):
            for order in orders_resp.get("data", {}).get("list", []) or []:
                orders.append(
                    {
                        "price": float(order.get("price", 0)),
                        "side": order.get("side", ""),
                        "qty": float(order.get("qty", 0)),
                        "reduce_only": order.get("reduceOnly", False),
                    }
                )
    except Exception as e:
        logging.warning(f"Failed to fetch orders for grid viz: {e}")

    # Get position info (use global client)
    position = None
    try:
        pos_resp = client.get_positions(skip_cache=True)
        if pos_resp.get("success"):
            for pos in pos_resp.get("data", {}).get("list", []) or []:
                if pos.get("symbol") == symbol:
                    size = float(pos.get("size", 0) or 0)
                    if size > 0:
                        position = {
                            "side": pos.get("side", "").lower(),
                            "size": size,
                            "entry_price": float(pos.get("avgPrice", 0) or 0),
                            "unrealized_pnl": float(pos.get("unrealisedPnl", 0) or 0),
                        }
                        break
    except Exception as e:
        logging.warning(f"Failed to fetch position for grid viz: {e}")

    return jsonify(
        {
            "symbol": symbol,
            "current_price": market_price,
            "lower_price": lower_price,
            "upper_price": upper_price,
            # Compatibility aliases for older dashboard consumers.
            "lower_bound": lower_price,
            "upper_bound": upper_price,
            "grid_count": grid_count,
            "grid_levels": grid_levels,
            "orders": orders,
            "position": position,
            "mode": mode,
            "range_mode": range_mode,
            "range_key_family": (
                "grid_price"
                if str(mode or "").strip().lower() == "neutral_classic_bybit"
                else "price"
            ),
        }
    )


@app.route("/api/bots/<bot_id>/quick-update", methods=["POST"])
@require_basic_auth
def api_bots_quick_update(bot_id: str):
    """Quick update TP% and Auto Stop on running bots."""
    data = request.get_json(force=True) or {}

    bot = bot_storage.get_bot(bot_id)
    if not bot:
        return json_error("Bot not found", 404)

    # H8: settings_version conflict detection prevents stale concurrent updates
    incoming_sv = data.get("settings_version")
    if incoming_sv is not None:
        try:
            incoming_sv = int(incoming_sv)
        except (TypeError, ValueError):
            incoming_sv = None
        current_sv = int(bot.get("settings_version") or 0)
        if incoming_sv is not None and incoming_sv != current_sv:
            return (
                jsonify(
                    {
                        "error": "settings_version_conflict",
                        "message": "Bot settings changed elsewhere. Reload and try again.",
                        "current_settings_version": current_sv,
                    }
                ),
                409,
            )

    updated = False
    if "tp_pct" in data:
        val = data["tp_pct"]
        if val is None or val == "":
            bot["tp_pct"] = None
        else:
            try:
                bot["tp_pct"] = float(val)
                updated = True
            except (ValueError, TypeError):
                return json_error("Invalid tp_pct value", 400)

    if "auto_stop" in data:
        val = data["auto_stop"]
        if val is None or val == "":
            bot["auto_stop"] = None
        else:
            try:
                bot["auto_stop"] = float(val)
                updated = True
            except (ValueError, TypeError):
                return json_error("Invalid auto_stop value", 400)

    # Auto-stop on balance target (Smart Feature #19)
    if "auto_stop_target_usdt" in data:
        val = data["auto_stop_target_usdt"]
        try:
            target_value = float(val) if val not in (None, "", 0) else 0.0
        except (ValueError, TypeError):
            return json_error("Invalid auto_stop_target_usdt value", 400)
        bot_manager._set_auto_stop_target_config(bot, target_value)
        if target_value > 0:
            updated = True

    if (
        updated
        or "tp_pct" in data
        or "auto_stop" in data
        or "auto_stop_target_usdt" in data
    ):
        bot_manager._mark_settings_state_change(bot)
        bot = bot_storage.save_bot(bot)
        logging.info(
            "⚙️ Bot quick-update: id=%s tp_pct=%s auto_stop=%s auto_stop_target=$%s",
            bot_id,
            bot.get("tp_pct"),
            bot.get("auto_stop"),
            bot.get("auto_stop_target_usdt"),
        )
        _invalidate_dashboard_runtime_views()

    return jsonify({"bot": bot, "updated": updated})


@app.route("/api/bots/<bot_id>/auto-stop-target", methods=["POST"])
@require_basic_auth
def api_bots_set_auto_stop_target(bot_id: str):
    """Set auto-stop target balance for a bot."""
    data = request.get_json(force=True) or {}

    bot = bot_storage.get_bot(bot_id)
    if not bot:
        return json_error("Bot not found", 404)

    # H8: settings_version conflict detection
    incoming_sv = data.get("settings_version")
    if incoming_sv is not None:
        try:
            incoming_sv = int(incoming_sv)
        except (TypeError, ValueError):
            incoming_sv = None
        current_sv = int(bot.get("settings_version") or 0)
        if incoming_sv is not None and incoming_sv != current_sv:
            return (
                jsonify(
                    {
                        "error": "settings_version_conflict",
                        "message": "Bot settings changed elsewhere. Reload and try again.",
                        "current_settings_version": current_sv,
                    }
                ),
                409,
            )

    target = data.get("target_usdt", 0)
    try:
        target = float(target) if target else 0.0
    except (ValueError, TypeError):
        return json_error("Invalid target_usdt value", 400)

    bot_manager._set_auto_stop_target_config(bot, target)
    bot_manager._mark_settings_state_change(bot)
    bot = bot_storage.save_bot(bot)

    if target > 0:
        logging.info("🎯 Auto-stop target set: id=%s target=$%.2f", bot_id, target)
    else:
        logging.info("🎯 Auto-stop target disabled: id=%s", bot_id)

    return jsonify(
        {
            "bot_id": bot_id,
            "auto_stop_target_usdt": target,
            "message": f"Auto-stop target set to ${target:.2f}"
            if target > 0
            else "Auto-stop disabled",
        }
    )


@app.route("/api/bot/delete", methods=["POST"])
@require_basic_auth
def api_bot_delete_legacy():
    """Legacy alias for frontend calls expecting /api/bot/delete."""
    return api_bots_delete()


@app.route("/api/bots/<bot_id>/details")
@require_basic_auth
def api_bot_details(bot_id):
    """Get detailed bot info including trade history and symbol PnL."""
    details = bot_status_service.get_bot_details(bot_id)
    if not details:
        return json_error("bot not found", 404)
    return _set_no_cache_headers(jsonify({"bot": details}))


@app.route("/api/symbol-pnl/<symbol>")
@require_basic_auth
def api_symbol_pnl(symbol):
    """Get cumulative PnL data for a specific symbol."""
    pnl_data = symbol_pnl_service.get_symbol_pnl(symbol.upper())
    if not pnl_data:
        return _set_no_cache_headers(jsonify({"symbol": symbol.upper(), "data": None}))
    return _set_no_cache_headers(jsonify({"symbol": symbol.upper(), "data": pnl_data}))


# ============================================================
# Risk Management APIs
# ============================================================


@app.route("/api/risk/reset-kill-switch", methods=["POST"])
@require_basic_auth
def api_reset_kill_switch():
    """
    Reset the global kill-switch trigger state.
    """
    state = risk_manager.reset_kill_switch()
    return jsonify({"state": state})


@app.route("/api/symbol-pnl")
@require_basic_auth
def api_all_symbol_pnl():
    """Get cumulative PnL data for all symbols."""
    all_pnl = symbol_pnl_service.get_all_symbols_pnl()
    return _set_no_cache_headers(jsonify({"symbols": all_pnl}))


@app.route("/api/training/<symbol>")
@require_basic_auth
def api_symbol_training(symbol):
    """Get training data and status for a symbol."""
    if not symbol_training_service:
        return jsonify({"enabled": False})
    return jsonify(symbol_training_service.get_training_data(symbol.upper()))


@app.route("/api/training")
@require_basic_auth
def api_all_training():
    """Get training summaries for all symbols."""
    if not symbol_training_service:
        return jsonify({"enabled": False})
    return jsonify({"enabled": True, "symbols": symbol_training_service.get_all_training_summary()})


@app.route("/api/training/rebuild", methods=["POST"])
@require_basic_auth
def api_rebuild_training():
    """Rebuild training data from trade logs."""
    if not symbol_training_service:
        return jsonify({"enabled": False})
    trade_logs = pnl_service.get_log()
    rebuilt = symbol_training_service.rebuild_from_trade_logs(trade_logs)
    return jsonify(
        {
            "success": True,
            "enabled": True,
            "symbols": rebuilt,
            "symbol_count": len(rebuilt),
            "trade_count": len(trade_logs),
        }
    )


@app.route("/api/pnl/unattributed")
@require_basic_auth
def api_unattributed_pnl():
    """List closed trades that could not be deterministically attributed to a bot."""
    logs = pnl_service.get_log()
    unattributed = [entry for entry in logs if not entry.get("bot_id")]
    unattributed.sort(key=lambda item: item.get("time", ""), reverse=True)

    if (request.args.get("format") or "").lower() == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "time",
                "symbol",
                "side",
                "qty",
                "price",
                "realized_pnl",
                "order_id",
                "exec_id",
                "order_link_id",
                "position_idx",
                "attribution_source",
            ]
        )
        for entry in unattributed:
            writer.writerow(
                [
                    entry.get("time"),
                    entry.get("symbol"),
                    entry.get("side"),
                    entry.get("qty"),
                    entry.get("price"),
                    entry.get("realized_pnl"),
                    entry.get("order_id") or entry.get("id"),
                    entry.get("exec_id"),
                    entry.get("order_link_id"),
                    entry.get("position_idx"),
                    entry.get("attribution_source"),
                ]
            )
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=unattributed-pnl-{datetime.now().date().isoformat()}.csv"
                )
            },
        )

    return jsonify({"count": len(unattributed), "trades": unattributed})


@app.route("/api/symbol-pnl/rebuild", methods=["POST"])
@require_basic_auth
def api_rebuild_symbol_pnl():
    """Rebuild symbol PnL data from existing trade logs."""
    trade_logs = pnl_service.get_log()
    symbol_pnl_service.rebuild_from_logs(trade_logs)
    return jsonify(
        {
            "success": True,
            "message": f"Symbol PnL data rebuilt from {len(trade_logs)} trade logs",
        }
    )


# ============================================================
# Neutral Scanner APIs
# ============================================================



# ============================================================
# AI Range Suggestion (Smart Feature: Auto-Direction Range)
# ============================================================


def _build_ai_range_suggestion(
    symbol: str, mode: str = "neutral", range_mode: str = "fixed"
) -> dict:
    """Build an automatic lower/upper range suggestion for a symbol, mode, and range_mode."""
    symbol = symbol.strip().upper()
    mode = (mode or "neutral").strip().lower()
    range_mode = (range_mode or "fixed").strip().lower()
    if range_mode not in ("fixed", "dynamic", "trailing"):
        range_mode = "fixed"
    if not symbol:
        raise ValueError("Symbol required")
    if not _is_tradeable_position_symbol(symbol):
        raise ValueError("tradeable symbol is required")

    ticker_resp = client.get_tickers(symbol)
    if not ticker_resp.get("success"):
        raise ValueError(f"Failed to fetch ticker for {symbol}")
    ticker_list = ticker_resp.get("data", {}).get("list", [])
    if not ticker_list:
        raise ValueError(f"No ticker data for {symbol}")

    last_price = float(ticker_list[0].get("lastPrice", 0))
    if last_price <= 0:
        raise ValueError("Invalid price")

    # Compute technical indicators (15m fast + 1h slow)
    fast = indicator_service.compute_indicators(symbol, interval="15", limit=200)
    slow = indicator_service.compute_indicators(symbol, interval="60", limit=200)

    analysis = grid_bot_service.get_auto_direction_analysis(
        symbol=symbol,
        current_mode="neutral",
        fast_indicators=fast,
        slow_indicators=slow,
        current_price=last_price,
        apply_mode_guards=True,
    )
    score = float(analysis.get("score") or 0.0)
    signals = analysis.get("signals") or []
    target_mode = str(analysis.get("target_mode") or "neutral").lower()

    if target_mode == "long":
        bias = "Strong Bullish" if score >= 70 else "Bullish"
    elif target_mode == "short":
        bias = "Strong Bearish" if score <= -70 else "Bearish"
    else:
        bias = "Neutral"

    atr_pct = fast.get("atr_pct")
    bbw_pct = fast.get("bbw_pct")
    range_settings = get_dynamic_range_settings(mode)
    range_result = range_engine.build_neutral_range(
        last_price=last_price,
        atr_pct=atr_pct,
        bbw_pct=bbw_pct,
        width_floor_pct=range_settings.get("width_floor_pct"),
    )

    range_mode_width_mult = {
        "fixed": 1.10,
        "dynamic": 1.00,
        "trailing": 0.92,
    }.get(range_mode, 1.0)
    adjusted_width_pct = max(
        MIN_RANGE_WIDTH_PCT,
        min(range_result["width_pct"] * range_mode_width_mult, MAX_RANGE_WIDTH_PCT),
    )

    half = last_price * adjusted_width_pct / 2.0
    lower = max(0.0, last_price - half)
    upper = last_price + half
    return {
        "success": True,
        "symbol": symbol,
        "price": last_price,
        "lower": round(lower, 8),
        "upper": round(upper, 8),
        "width_pct": round(adjusted_width_pct * 100, 2),
        "mode": mode,
        "range_mode": range_mode,
        "bias": bias,
        "score": round(score),
        "signals": signals,
    }


@app.route("/api/ai-range/<symbol>")
@require_basic_auth
def api_ai_range(symbol):
    """Suggest price range based on technical analysis."""
    symbol = symbol.strip().upper()
    mode = (request.args.get("mode") or "neutral").strip().lower()
    range_mode = (request.args.get("range_mode") or "fixed").strip().lower()
    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"}), 400

    try:
        return jsonify(_build_ai_range_suggestion(symbol, mode, range_mode))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logging.exception(f"AI range error for {symbol}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/neutral-scan")
@require_basic_auth
def api_neutral_scan():
    """Scan symbols for neutral grid trading opportunities."""
    symbols_param = request.args.get("symbols")
    if symbols_param:
        symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
    else:
        # Default universe - top 30+ by 24h volume (correct Bybit symbol names)
        symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "DOGEUSDT",
            "ADAUSDT",
            "SUIUSDT",
            "HYPEUSDT",
            "BCHUSDT",
            "WIFUSDT",
            "1000PEPEUSDT",
            "LINKUSDT",
            "AAVEUSDT",
            "BNBUSDT",
            "ENAUSDT",
            "UNIUSDT",
            "LTCUSDT",
            "DOTUSDT",
            "AVAXUSDT",
            "NEARUSDT",
            "APTUSDT",
            "ARBUSDT",
            "OPUSDT",
            "INJUSDT",
            "SEIUSDT",
            "TIAUSDT",
            "JUPUSDT",
            "ONDOUSDT",
            "WLDUSDT",
            "ATOMUSDT",
            "FTMUSDT",
            "RENDERUSDT",
            "IMXUSDT",
            "STXUSDT",
            "ALGOUSDT",
        ]

    if symbols_param:
        # Custom symbol set — always compute fresh
        results = neutral_scanner.scan(symbols)
    else:
        # Default universe — cache for 30s (scans 34 symbols, 2-5s cold)
        results = _get_cached_or_compute(
            "neutral_scan", 30.0, lambda: neutral_scanner.scan(symbols)
        )
    return jsonify({"results": results})


# ============================================================
# Price & Market Data APIs
# ============================================================


@app.route("/api/symbol/info")
@require_basic_auth
def api_symbol_info():
    """Get instrument details and minimum investment levels for a symbol."""
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return json_error("symbol is required", 400)
    if not _is_tradeable_position_symbol(symbol):
        return json_error("tradeable symbol is required", 400)

    def _safe_float(val):
        try:
            f = float(val)
            return f
        except (TypeError, ValueError):
            return None

    inst_response = client.get_instruments_info(symbol)
    if not inst_response.get("success"):
        return json_error(
            inst_response.get("error", "failed to fetch instrument info"), 502
        )

    inst_list = (inst_response.get("data") or {}).get("list") or []
    if not inst_list:
        return json_error("symbol not found", 404)

    inst = inst_list[0]
    lot_filter = inst.get("lotSizeFilter") or {}
    price_filter = inst.get("priceFilter") or {}

    min_order_qty = _safe_float(lot_filter.get("minOrderQty"))
    max_order_qty = _safe_float(lot_filter.get("maxOrderQty"))
    qty_step = _safe_float(lot_filter.get("qtyStep"))
    min_notional = _safe_float(lot_filter.get("minNotionalValue")) or 5.0
    tick_size = _safe_float(price_filter.get("tickSize"))

    ticker_resp = client.get_tickers(symbol)
    last_price = None
    if ticker_resp.get("success"):
        tick_list = (ticker_resp.get("data") or {}).get("list") or []
        if tick_list:
            last_price = _safe_float(tick_list[0].get("lastPrice")) or None

    min_inv_1x = min_notional
    min_inv_5x = min_notional / 5
    min_inv_10x = min_notional / 10
    min_inv_20x = min_notional / 20

    if last_price and min_order_qty and min_order_qty > 0:
        min_value_from_qty = last_price * min_order_qty
        min_inv_1x = max(min_inv_1x, min_value_from_qty)
        min_inv_5x = max(min_inv_5x, min_value_from_qty / 5)
        min_inv_10x = max(min_inv_10x, min_value_from_qty / 10)
        min_inv_20x = max(min_inv_20x, min_value_from_qty / 20)

    return jsonify(
        {
            "symbol": symbol,
            "min_order_qty": min_order_qty,
            "max_order_qty": max_order_qty,
            "qty_step": qty_step,
            "tick_size": tick_size,
            "min_notional": min_notional,
            "last_price": last_price,
            "min_investment": {
                "1x": round(min_inv_1x, 2),
                "5x": round(min_inv_5x, 2),
                "10x": round(min_inv_10x, 2),
                "20x": round(min_inv_20x, 2),
            },
        }
    )


@app.route("/api/price")
@require_basic_auth
def api_price():
    """Get current price and instrument info for a symbol."""
    symbol = request.args.get("symbol")
    if not symbol:
        return json_error("symbol is required", 400)

    symbol = symbol.upper()
    if not _is_tradeable_position_symbol(symbol):
        return json_error("tradeable symbol is required", 400)

    ticker = client.get_tickers(symbol)
    if not ticker.get("success"):
        return json_error(ticker.get("error", "failed to fetch ticker"), 502)

    data = ticker.get("data", {})
    tick_list = data.get("list") or data.get("result") or []
    last_price = mark_price = bid1 = ask1 = None

    if tick_list:
        t = tick_list[0]
        last_price = float(t.get("lastPrice", 0) or 0)
        mark_price = float(t.get("markPrice", last_price) or 0)
        bid1 = float(t.get("bid1Price", 0) or 0)
        ask1 = float(t.get("ask1Price", 0) or 0)

    # Fetch instrument info for minimum order requirements
    min_order_qty = None
    min_order_value = 5.0  # Default fallback
    qty_step = None
    qty_step_raw = None
    tick_size = None
    tick_size_raw = None
    max_leverage = None

    inst_response = client.get_instruments_info(symbol)
    if inst_response.get("success"):
        inst_data = inst_response.get("data", {})
        inst_list = inst_data.get("list", [])
        if inst_list:
            inst = inst_list[0]
            lot_filter = inst.get("lotSizeFilter", {})
            price_filter = inst.get("priceFilter", {})
            leverage_filter = inst.get("leverageFilter", {})
            min_order_qty = float(lot_filter.get("minOrderQty", 0) or 0)
            qty_step_raw = lot_filter.get("qtyStep")
            qty_step = float(qty_step_raw or 0)
            tick_size_raw = price_filter.get("tickSize")
            tick_size = float(tick_size_raw or 0)
            max_leverage = float(leverage_filter.get("maxLeverage", 0) or 0)
            # Get actual minimum notional from Bybit
            min_notional = lot_filter.get("minNotionalValue") or lot_filter.get(
                "minOrderAmt"
            )
            if min_notional:
                min_order_value = float(min_notional)

    # Calculate minimum qty needed for min order value
    min_qty_for_value = None
    if last_price and last_price > 0:
        min_qty_for_value = min_order_value / last_price
        if qty_step and qty_step > 0:
            import math

            min_qty_for_value = math.ceil(min_qty_for_value / qty_step) * qty_step

    return jsonify(
        {
            "symbol": symbol,
            "last_price": last_price,
            "mark_price": mark_price,
            "bid1": bid1,
            "ask1": ask1,
            "min_order_qty": min_order_qty,
            "min_order_value": min_order_value,
            "safe_min_order_value": min_order_value * AUTO_GRID_ADJUSTMENT_BUFFER,
            "min_qty_for_value": min_qty_for_value,
            "qty_step": qty_step,
            "qty_step_raw": qty_step_raw,
            "tick_size": tick_size,
            "tick_size_raw": tick_size_raw,
            "max_leverage": max_leverage,
            "auto_margin_reserve_pct": AUTO_MARGIN_RESERVE_PCT,
            "auto_margin_reserve_usdt": AUTO_MARGIN_RESERVE_USDT,
            "auto_margin_reserve_use_pct": AUTO_MARGIN_RESERVE_USE_PCT,
        }
    )


# ============================================================
# PnL APIs
# ============================================================


@app.route("/api/pnl/log")
@require_basic_auth
def api_pnl_log():
    """Get PnL logs and today's stats."""
    _maybe_sync_closed_pnl_for_api()
    logs = pnl_service.get_log(use_global_baseline=True)
    today = pnl_service.get_today_stats(use_global_baseline=True)
    response = jsonify(
        {
            "logs": logs[-100:],  # Last 100 entries
            "today": today,
            "performance_baseline": _performance_baseline_metadata(),
        }
    )
    return _set_no_cache_headers(response)


@app.route("/api/pnl/stats")
@require_basic_auth
def api_pnl_stats():
    """
    Get comprehensive trade statistics like Bybit's profitable trades panel.

    Query Parameters:
        period: "today", "7d", "30d", or "all" (default: "all")
    """
    period = request.args.get("period", "all")
    if period not in ("today", "7d", "30d", "all"):
        period = "all"
    _maybe_sync_closed_pnl_for_api()
    stats = pnl_service.get_trade_statistics(period, use_global_baseline=True)
    stats["performance_baseline"] = _performance_baseline_metadata()
    return _set_no_cache_headers(jsonify(stats))


@app.route("/api/pnl/all")
@require_basic_auth
def api_pnl_all():
    """
    Get ALL closed PnL logs with enriched bot config data and summary stats.

    Query Parameters:
        start_date: ISO date string (YYYY-MM-DD) to filter from
        end_date: ISO date string (YYYY-MM-DD) to filter until
        symbol: Filter by symbol
        page: Page number for pagination (default 1)
        per_page: Items per page (default 100, max 500)
    """
    _maybe_sync_closed_pnl_for_api()
    logs = pnl_service.get_log(use_global_baseline=True)  # Returns all logs sorted by time

    # Apply optional filters
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    symbol_filter = request.args.get("symbol", "").upper()

    filtered_logs = logs

    if start_date:
        try:
            filtered_logs = [
                l for l in filtered_logs if l.get("time", "")[:10] >= start_date
            ]
        except (ValueError, TypeError):
            pass

    if end_date:
        try:
            filtered_logs = [
                l for l in filtered_logs if l.get("time", "")[:10] <= end_date
            ]
        except (ValueError, TypeError):
            pass

    if symbol_filter:
        filtered_logs = [
            l for l in filtered_logs
            if symbol_filter in (l.get("symbol") or "").upper()
        ]

    # Calculate summary stats
    total_pnl = sum(l.get("realized_pnl", 0) for l in filtered_logs)
    total_trades = len(filtered_logs)
    wins = sum(1 for l in filtered_logs if l.get("realized_pnl", 0) > 0)
    losses = sum(1 for l in filtered_logs if l.get("realized_pnl", 0) < 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    # Pagination — allow larger page when filtering by symbol without dates
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    per_page_cap = 5000 if (symbol_filter and not start_date and not end_date) else 500
    try:
        per_page = min(per_page_cap, max(1, int(request.args.get("per_page", 100))))
    except (ValueError, TypeError):
        per_page = 100

    total_pages = (
        (len(filtered_logs) + per_page - 1) // per_page if filtered_logs else 1
    )

    # Sort descending (newest first) for display
    sorted_logs = sorted(filtered_logs, key=lambda x: x.get("time", ""), reverse=True)

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_logs = sorted_logs[start_idx:end_idx]

    response = jsonify(
        {
            "logs": paginated_logs,
            "summary": {
                "total_pnl": round(total_pnl, 4),
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 1),
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "total_records": len(filtered_logs),
            },
            "performance_baseline": _performance_baseline_metadata(),
        }
    )
    return _set_no_cache_headers(response)


@app.route("/api/pnl/analytics")
@require_basic_auth
def api_pnl_analytics():
    """
    Get structured analytics data for charting.

    Query Parameters:
        period: "today", "7d", "30d", or "all" (default: "all")
        symbol: Optional symbol filter (e.g. "BTCUSDT")
        bot_id: Optional bot ID filter
    """
    period = request.args.get("period", "all")
    if period not in ("today", "7d", "30d", "all"):
        period = "all"

    symbol = request.args.get("symbol", "").strip().upper() or None
    bot_id = request.args.get("bot_id", "").strip() or None

    _maybe_sync_closed_pnl_for_api()
    analytics = pnl_service.get_analytics_data(
        period, symbol=symbol, bot_id=bot_id, use_global_baseline=True
    )
    analytics["performance_baseline"] = _performance_baseline_metadata(bot_id=bot_id)
    return _set_no_cache_headers(jsonify(analytics))


# ============================================================
# Bot Status & Log APIs (for status/log viewer modal)
# ============================================================


@app.route("/api/bot/status")
@require_basic_auth
def api_bot_status():
    return _set_no_cache_headers(jsonify(_build_bot_status_payload()))


def _build_bot_status_payload() -> Dict[str, Any]:
    """
    Get overall bot system status.

    Returns JSON with:
        - running: bool (True if app is serving)
        - port: int (server port)
        - mode: str (current trading mode, e.g., "grid")
        - last_heartbeat: str (ISO timestamp of last successful request)
        - uptime_seconds: int (seconds since app started)
        - bots: dict (summary from BotStatusService)
        - extra: dict (additional runtime info)

    You can customize this to pull real data from:
        - bot_status_service.get_summary()
        - Any internal state flags
        - External health checks
    """
    now = datetime.utcnow()
    uptime = (now - APP_START_TIME).total_seconds()

    # Get bot summary from existing service
    try:
        bots_summary = bot_status_service.get_summary()
    except Exception as e:
        bots_summary = {"error": str(e)}

    # Check runner lock status and log file timestamp
    runner_lock_held = _runner_lock_held()
    runner_process = _runner_process_info()
    runner_active = bool(runner_lock_held or runner_process.get("active"))
    runner_last_update = None
    try:
        if os.path.exists(RUNNER_LOG_FILE):
            stat = os.stat(RUNNER_LOG_FILE)
            runner_last_update = (
                datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z"
            )
    except Exception:
        pass

    return {
        "running": True,
        "port": 8000,
        "mode": "grid",  # Can be customized based on active bot modes
        "last_heartbeat": now.isoformat() + "Z",
        "uptime_seconds": int(uptime),
        "started_at": APP_START_TIME.isoformat() + "Z",
        "bots": bots_summary,
        "runner": {
            "active": runner_active,
            "lock_held": runner_lock_held,
            "pid": runner_process.get("pid"),
            "detected_via": runner_process.get("source"),
            "last_log_update": runner_last_update,
            "log_file": RUNNER_LOG_FILE,
        },
        "extra": {
            "env_label": cfg.get("env_label", "Bybit Environment"),
            "storage_path": "storage/",
        },
    }


@app.route("/api/bot/log")
@require_basic_auth
def api_bot_log():
    """
    Get the latest lines from the runner log file.

    Query parameters:
        - lines: int (number of lines to return, default 100, max 1000)
        - scope: str ("all" or "running"; default "all")

    Returns plain text with the last N lines of the log file.
    If the log file doesn't exist, returns an informational message.
    """
    # Get number of lines to return
    try:
        num_lines = int(request.args.get("lines", DEFAULT_LOG_LINES))
        num_lines = min(max(num_lines, 1), 1000)  # Clamp between 1 and 1000
    except (TypeError, ValueError):
        num_lines = DEFAULT_LOG_LINES

    # Scope of logs to return
    scope = str(request.args.get("scope", "all") or "all").lower()
    if scope not in ("all", "running"):
        scope = "all"

    # Check if log file exists
    if not os.path.exists(RUNNER_LOG_FILE):
        return (
            (
                f"Log file not found: {RUNNER_LOG_FILE}\n\n"
                "The runner.py process has not started yet.\n"
                "Click the 'Start Runner' button to start it."
            ),
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    try:
        # Read log file and optionally filter to currently running bots only.
        with open(RUNNER_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        tail_lines = lines[-num_lines:] if len(lines) > num_lines else lines

        if scope == "all":
            log_content = "".join(tail_lines).strip()
            if not log_content:
                log_content = "(No log content found in this window.)"
            return (
                log_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                },
            )

        # Build running-bot match tokens
        running_bots = [b for b in bot_storage.list_bots() if b.get("status") == "running"]
        running_tokens = []
        for b in running_bots:
            bot_id = str(b.get("id", ""))
            symbol = str(b.get("symbol", ""))
            if not bot_id or not symbol:
                continue
            running_tokens.append(
                {
                    "bot_id": bot_id,
                    "bot_id_short": bot_id[:6],
                    "symbol": symbol,
                }
            )

        # Keep only lines related to running bots.
        filtered_lines = []
        for line in tail_lines:
            keep = False
            for token in running_tokens:
                if (
                    f"[{token['symbol']}:{token['bot_id_short']}]" in line
                    or f"[{token['symbol']}]" in line
                    or f"({token['symbol']})" in line
                    or token["bot_id"] in line
                ):
                    keep = True
                    break
            if keep:
                filtered_lines.append(line)

        if not running_tokens:
            log_content = "(No running bots. Start a bot to see live bot-focused logs.)"
        else:
            log_content = "".join(filtered_lines).strip()
            if not log_content:
                log_content = (
                    "(No recent log lines for currently running bots in this window. "
                    "Try increasing line count.)"
                )

        return (
            log_content,
            200,
            {
                "Content-Type": "text/plain; charset=utf-8",
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    except Exception as e:
        return (
            f"Error reading log file: {e}",
            500,
            {"Content-Type": "text/plain; charset=utf-8"},
        )


@app.route("/api/runner/start", methods=["POST"])
@require_basic_auth
def api_runner_start():
    """
    Start the runner.py process in the background.

    This spawns runner.py as a detached subprocess.
    The runner will continue running even if this request times out.

    Returns JSON with:
        - success: bool
        - message: str
        - pid: int (process ID if started successfully)
    """
    runner_script = os.path.join(os.path.dirname(__file__), "runner.py")

    if not os.path.exists(runner_script):
        logging.error("runner.py not found at %s", runner_script)
        return jsonify(
            {
                "success": False,
                "message": f"runner.py not found at {runner_script}",
            }
        ), 404

    if _runner_lock_held() or _runner_process_info().get("active"):
        return json_error("runner already running", 409)

    try:
        spawn_result = _spawn_runner_process()
        global RUNNER_LAST_SPAWN_AT
        RUNNER_LAST_SPAWN_AT = time.time()

        return jsonify(
            {
                "success": True,
                "message": f"Runner started successfully with PID {spawn_result['pid']}",
                "pid": spawn_result["pid"],
            }
        )

    except Exception as e:
        logging.error("Failed to start runner: %s", e)
        return jsonify(
            {
                "success": False,
                "message": f"Failed to start runner: {e}",
            }
        ), 500


@app.route("/api/services/status")
@require_basic_auth
def api_services_status():
    """Get runner service status for dashboard controls."""
    runner_lock_held = _runner_lock_held()
    runner_info = _runner_process_info()
    runner_active = bool(runner_lock_held or runner_info.get("active"))
    detected_via = runner_info.get("source", "unknown")
    if runner_lock_held and not runner_info.get("active"):
        detected_via = "lock"

    return jsonify(
        {
            "runner_active": runner_active,
            "runner_pid": runner_info.get("pid") or _runner_pid_from_lock(),
            "detected_via": detected_via,
            "stop_flag_exists": os.path.exists(RUNNER_STOP_FLAG),
        }
    )


@app.route("/api/services/restart", methods=["POST"])
@require_basic_auth
def api_restart_services():
    """Restart the runner process from the dashboard."""
    global RUNNER_LAST_SPAWN_AT

    try:
        with RUNNER_MONITOR_LOCK:
            stop_result = _request_runner_stop(
                "dashboard_restart",
                force=True,
                wait_sec=2.0,
            )
            _remove_runner_stop_flag()
            spawn_result = _spawn_runner_process()
            RUNNER_LAST_SPAWN_AT = time.time()

        logging.info(
            "🔄 Services restarted from dashboard (old PID: %s, new PID: %s)",
            stop_result.get("pid"),
            spawn_result.get("pid"),
        )
        return jsonify(
            {
                "success": True,
                "message": "Runner restarted",
                "old_pid": stop_result.get("pid"),
                "new_pid": spawn_result.get("pid"),
            }
        )
    except Exception as e:
        logging.error("Service restart failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/services/stop", methods=["POST"])
@require_basic_auth
def api_stop_services():
    """Stop the runner process without restarting."""
    try:
        with RUNNER_MONITOR_LOCK:
            stop_result = _request_runner_stop("dashboard_stop", force=False)

        logging.info("⏹️ Runner stopped from dashboard (PID: %s)", stop_result.get("pid"))
        return jsonify(
            {
                "success": True,
                "message": "Runner stopped",
                "pid": stop_result.get("pid"),
            }
        )
    except Exception as e:
        logging.error("Service stop failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/runner/stop", methods=["POST"])
@require_basic_auth
def api_runner_stop():
    """
    Stop the runner.py process gracefully.

    This creates a stop flag file that runner.py checks each cycle.
    When runner.py sees the flag, it exits gracefully.

    Returns JSON with:
        - success: bool
        - message: str
    """
    try:
        with RUNNER_MONITOR_LOCK:
            stop_result = _request_runner_stop("api_runner_stop", force=False)

        logging.info("🛑 Runner stop requested (PID: %s)", stop_result.get("pid"))

        return jsonify(
            {
                "success": True,
                "message": "Stop signal sent. Runner will stop after current cycle completes.",
            }
        )

    except Exception as e:
        logging.error("Failed to create stop flag: %s", e)
        return jsonify(
            {
                "success": False,
                "message": f"Failed to send stop signal: {e}",
            }
        ), 500


# ============================================================
# Backtest API (Form-based grid profit estimation)
# ============================================================


@app.route("/api/backtest", methods=["POST"])
@require_basic_auth
def api_backtest():
    """
    Run a bounded replayable backtest using historical candle data.
    Fetches recent candles from Bybit by default, or loads a local CSV when provided.

    Request body:
        symbol, lower_price, upper_price, grid_count, investment, leverage, mode, range_mode,
        days (optional), csv_path (optional), warmup_candles (optional), maker/taker/slippage bps (optional)
    """
    import time as time_module
    from datetime import datetime, timedelta
    from services.backtest.engine import BacktestEngine

    try:
        data = request.get_json() or {}

        symbol = data.get("symbol", "").upper().strip()
        lower_price = float(data.get("lower_price", 0))
        upper_price = float(data.get("upper_price", 0))
        grid_count = int(data.get("grid_count", 10))
        investment = float(data.get("investment", 100))
        leverage = float(data.get("leverage", 1))
        mode = data.get("mode", "long")
        range_mode = data.get("range_mode", "fixed")
        days = min(int(data.get("days", 7)), 14)  # Max 14 days for speed
        csv_path = str(data.get("csv_path", "") or "").strip()
        warmup_candles = max(int(data.get("warmup_candles", 100)), 20)
        maker_fee_bps = float(data.get("maker_fee_bps", 2.0))
        taker_fee_bps = float(data.get("taker_fee_bps", 5.5))
        market_slippage_bps = float(data.get("market_slippage_bps", 5.0))

        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400
        if not _is_tradeable_position_symbol(symbol):
            return jsonify({"error": "tradeable symbol is required"}), 400
        if lower_price >= upper_price:
            return jsonify({"error": "Lower price must be less than upper price"}), 400
        if grid_count < 2:
            return jsonify({"error": "Grid count must be at least 2"}), 400
        if str(mode or "").strip().lower() not in BacktestEngine.SUPPORTED_MODES:
            supported = ", ".join(sorted(BacktestEngine.SUPPORTED_MODES))
            return jsonify(
                {
                    "error": (
                        f"Replayable Backtest Engine v1 supports [{supported}] only; "
                        f"got '{mode}'"
                    )
                }
            ), 400

        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        candles = []

        if csv_path:
            if not os.path.exists(csv_path):
                return jsonify({"error": f"csv_path not found: {csv_path}"}), 400
            engine = BacktestEngine(
                symbol,
                start_time.isoformat(),
                end_time.isoformat(),
                investment,
                warmup_candles=warmup_candles,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                market_slippage_bps=market_slippage_bps,
            )
            engine.load_data(csv_path)
            candles = list(engine.candles)
        else:
            from services.bybit_client import BybitClient

            logging.info("Backtest: Downloading %d days of data for %s", days, symbol)

            client = BybitClient(
                os.getenv("BYBIT_API_KEY"),
                os.getenv("BYBIT_API_SECRET"),
                "https://api.bybit.com",
            )

            all_klines = []
            current_end = int(end_time.timestamp() * 1000)
            target_start = int(start_time.timestamp() * 1000)

            while current_end > target_start and len(all_klines) < 2000:
                resp = client.get_kline(
                    symbol=symbol,
                    interval="15",
                    limit=200,
                    end=current_end,
                )

                if not resp.get("success"):
                    logging.error("Failed to fetch kline data: %s", resp)
                    break

                kline_list = resp.get("data", {}).get("list", [])
                if not kline_list:
                    break

                oldest_ts = int(kline_list[-1][0])
                if oldest_ts >= current_end:
                    break

                current_end = oldest_ts - 1
                all_klines.extend(kline_list)
                time_module.sleep(0.05)

            if len(all_klines) < warmup_candles + 1:
                return jsonify(
                    {
                        "error": (
                            f"Not enough historical data for {symbol}. "
                            f"Got {len(all_klines)} candles, need {warmup_candles + 1}+"
                        ),
                        "candles_fetched": len(all_klines),
                    }
                ), 400

            for k in all_klines:
                candles.append(
                    {
                        "timestamp": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                )
            candles.sort(key=lambda x: x["timestamp"])
            candles = [
                candle
                for candle in candles
                if candle["timestamp"] >= target_start
            ]

            engine = BacktestEngine(
                symbol,
                start_time.isoformat(),
                end_time.isoformat(),
                investment,
                warmup_candles=warmup_candles,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                market_slippage_bps=market_slippage_bps,
            )
            engine.load_candles(candles)

        logging.info("Backtest: Running replay with %d candles", len(candles))
        if len(candles) <= warmup_candles:
            return jsonify(
                {
                    "error": (
                        f"Not enough historical data for {symbol}. "
                        f"Got {len(candles)} candles, need {warmup_candles + 1}+"
                    ),
                    "candles_fetched": len(candles),
                }
            ), 400

        # Setup bot with user config
        engine.setup_bot(
            {
                "investment": investment,
                "leverage": leverage,
                "grid_count": grid_count,
                "mode": mode,
                "range_mode": range_mode,
                "lower_price": lower_price,
                "upper_price": upper_price,
                "tp_pct": float(data.get("tp_pct", 0.01)),
                "auto_margin": data.get("auto_margin", False),
                "neutral_volatility_gate_enabled": data.get(
                    "neutral_volatility_gate_enabled", False
                ),
                "trailing_sl_enabled": data.get("trailing_sl_enabled", False),
            }
        )

        # Run simulation
        start_sim = time_module.time()
        result = engine.run()
        sim_duration = time_module.time() - start_sim

        trade_summary = dict(result.get("trade_summary") or {})
        decision_summary = dict(result.get("decision_summary") or {})

        return jsonify(
            {
                "success": True,
                "symbol": symbol,
                "lower_price": lower_price,
                "upper_price": upper_price,
                "grid_count": grid_count,
                "investment": investment,
                "leverage": leverage,
                "mode": mode,
                "range_mode": range_mode,
                "days_simulated": days,
                "candles_used": len(candles),
                "simulation_time_sec": round(sim_duration, 2),
                "final_equity": trade_summary.get("final_equity"),
                "profit": trade_summary.get("profit"),
                "roi_pct": trade_summary.get("roi_pct"),
                "max_drawdown_pct": trade_summary.get("max_drawdown_pct"),
                "trades_count": trade_summary.get("closed_trade_count"),
                "decision_count": decision_summary.get("total_decisions"),
                "blocked_decisions": decision_summary.get("blocked_decisions"),
                "is_real_simulation": True,
                "result": result,
            }
        )

    except Exception as e:
        logging.error("Backtest error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/backtest/validate", methods=["POST"])
@require_basic_auth
def api_backtest_validate():
    from services.backtest_validation_service import BacktestValidationService

    try:
        data = request.get_json() or {}
        service = BacktestValidationService()
        payload = service.validate_run(
            run_id=data.get("run_id"),
            run_dir=data.get("run_dir"),
            symbol=data.get("symbol"),
            mode=data.get("mode"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            persist=True,
        )
        return jsonify({"success": True, "validation": payload})
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logging.error("Backtest validation error: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/backtest/validation-recent", methods=["GET"])
@require_basic_auth
def api_backtest_validation_recent():
    from services.backtest_validation_service import BacktestValidationService

    service = BacktestValidationService()
    try:
        limit = max(int(request.args.get("limit", 20)), 1)
    except (TypeError, ValueError):
        limit = 20
    return jsonify(
        {
            "success": True,
            "recent": service.get_recent_validations(limit=limit),
        }
    )


@app.route("/api/backtest/validation-summary", methods=["GET"])
@require_basic_auth
def api_backtest_validation_summary():
    from services.backtest_validation_service import BacktestValidationService

    service = BacktestValidationService()
    try:
        limit = max(int(request.args.get("limit", 50)), 1)
    except (TypeError, ValueError):
        limit = 50
    return jsonify(
        {
            "success": True,
            "summary": service.get_validation_summary(limit=limit),
        }
    )


# ============================================================
# (AI Ops web control routes removed — safety cleanup)




# ============================================================
# Main Entry Point
# ============================================================


if __name__ == "__main__":
    # Ensure storage directory exists
    os.makedirs("storage", exist_ok=True)
    initialize_app_runtime()

    # Allow overriding host/port via environment (systemd sets APP_PORT)
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8000"))
    debug_mode = os.environ.get("APP_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    is_reloader_parent = debug_mode and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
    if not is_reloader_parent:
        _start_runner_watchdog()

    app.run(host=host, port=port, debug=debug_mode)
