"""Trading Watchdog configuration."""

import os

# Paths
TRADER_ROOT = os.environ.get("TW_TRADER_ROOT", "/var/www")
STORAGE_PATH = os.path.join(TRADER_ROOT, "storage")
BRIDGE_PATH = os.path.join(STORAGE_PATH, "runtime_snapshot_bridge.json")
BOTS_PATH = os.path.join(STORAGE_PATH, "bots.json")
RISK_STATE_PATH = os.path.join(STORAGE_PATH, "risk_state.json")
WATCHDOG_STATE_PATH = os.path.join(STORAGE_PATH, "watchdog_active_state.json")
AUDIT_SUMMARY_PATH = os.path.join(STORAGE_PATH, "audit_diagnostics_summary.json")
SYMBOL_PNL_PATH = os.path.join(STORAGE_PATH, "symbol_pnl.json")
TRADE_LOGS_PATH = os.path.join(STORAGE_PATH, "trade_logs.json")

# Server
HOST = os.environ.get("TW_HOST", "0.0.0.0")
PORT = int(os.environ.get("TW_PORT", "8200"))
DEBUG = os.environ.get("TW_DEBUG", "0") == "1"

# Polling
POLL_INTERVAL_SEC = int(os.environ.get("TW_POLL_INTERVAL", "30"))
BRIDGE_STALE_THRESHOLD_SEC = 15
STORAGE_STALE_THRESHOLD_SEC = 120

# Health scoring weights (subtracted per verdict)
SEVERITY_PENALTY = {
    "critical": 25,
    "high": 12,
    "medium": 5,
    "low": 2,
    "info": 0,
}

# Shadow mode
SHADOW_MODE = True
