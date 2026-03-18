"""Environment-based configuration for AI Ops service."""

import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# --- AI Ops auth ---
AIOPS_AUTH_USER = os.getenv("AIOPS_AUTH_USER", "admin")
AIOPS_AUTH_PASS = os.getenv("AIOPS_AUTH_PASS", "changeme")

# --- AI Ops service ---
AIOPS_PORT = int(os.getenv("AIOPS_PORT", "9100"))
DB_PATH = os.getenv("AIOPS_DB_PATH", str(Path(__file__).parent / "aiops.db"))

# --- Opus Trader connection ---
TRADER_BASE_URL = os.getenv("OPUS_TRADER_BASE_URL", "http://127.0.0.1:8000")
TRADER_AUTH_USER = os.getenv("OPUS_TRADER_AUTH_USER", "admin")
TRADER_AUTH_PASS = os.getenv("OPUS_TRADER_AUTH_PASS", "")

# --- Watchdog connection ---
WATCHDOG_BASE_URL = os.getenv("WATCHDOG_BASE_URL", "http://127.0.0.1:9000")
WATCHDOG_AUTH_USER = os.getenv("WATCHDOG_AUTH_USER", "admin")
WATCHDOG_AUTH_PASS = os.getenv("WATCHDOG_AUTH_PASS", "")

# --- Storage paths (read-only) ---
OPUS_STORAGE_PATH = os.getenv("OPUS_STORAGE_PATH", "/var/www/storage")
BRIDGE_JSON_PATH = os.path.join(OPUS_STORAGE_PATH, "runtime_snapshot_bridge.json")
RUNNER_LOG_PATH = os.path.join(OPUS_STORAGE_PATH, "runner.log")
APP_LOG_PATH = os.path.join(OPUS_STORAGE_PATH, "app.log")

# --- Collection cadence (seconds) ---
FAST_LANE_INTERVAL = int(os.getenv("FAST_LANE_INTERVAL_SEC", "15"))
MEDIUM_LANE_INTERVAL = int(os.getenv("MEDIUM_LANE_INTERVAL_SEC", "30"))
SLOW_LANE_INTERVAL = int(os.getenv("SLOW_LANE_INTERVAL_SEC", "60"))

# --- Limits ---
LOG_SCAN_BYTES = int(os.getenv("LOG_SCAN_BYTES", "65536"))

# --- Retention (days) ---
RETENTION_SNAPSHOTS_DAYS = int(os.getenv("RETENTION_SNAPSHOTS_DAYS", "7"))
RETENTION_TRIAGE_DAYS = int(os.getenv("RETENTION_TRIAGE_DAYS", "30"))
RETENTION_AUDIT_DAYS = int(os.getenv("RETENTION_AUDIT_DAYS", "90"))

# --- Triage ---
TRIAGE_AUTO_RESOLVE_SEC = float(os.getenv("TRIAGE_AUTO_RESOLVE_SEC", "600"))
CORRELATOR_WINDOW_SIZE = int(os.getenv("CORRELATOR_WINDOW_SIZE", "10"))

# --- Agent supervisor ---
SUPERVISOR_TICK_SEC = float(os.getenv("SUPERVISOR_TICK_SEC", "5"))
AGENT_HEARTBEAT_TIMEOUT_SEC = float(os.getenv("AGENT_HEARTBEAT_TIMEOUT_SEC", "120"))

# --- Retention: agent runs ---
RETENTION_AGENT_RUNS_DAYS = int(os.getenv("RETENTION_AGENT_RUNS_DAYS", "14"))

# --- Retention: agent activity ---
RETENTION_AGENT_ACTIVITY_DAYS = int(os.getenv("RETENTION_AGENT_ACTIVITY_DAYS", "7"))

# --- Retention: proposals ---
RETENTION_PROPOSALS_DAYS = int(os.getenv("RETENTION_PROPOSALS_DAYS", "30"))

# --- Default agent definitions ---
DEFAULT_AGENTS = [
    {
        "agent_id": "monitor",
        "name": "Monitor",
        "role": "Collects inputs from evidence sources, detects incident candidates, feeds triage engine",
        "interval_sec": 30,
        "enabled": True,
        "auto_run": True,
    },
    {
        "agent_id": "scout",
        "name": "Scout",
        "role": "Groups symptoms, prepares evidence bundles, suggests issue clusters",
        "interval_sec": 120,
        "enabled": True,
        "auto_run": True,
    },
    {
        "agent_id": "evaluator",
        "name": "Evaluator",
        "role": "Ranks findings, decides what is worth surfacing, creates proposal candidates",
        "interval_sec": 180,
        "enabled": True,
        "auto_run": True,
    },
    {
        "agent_id": "fix",
        "name": "Fix",
        "role": "Prepares narrow operational action proposals from allowlisted actions only",
        "interval_sec": 300,
        "enabled": False,
        "auto_run": False,
    },
    {
        "agent_id": "promotion_gate",
        "name": "Promotion Gate",
        "role": "Validates proposals against allowlist and safety rules before approval queue",
        "interval_sec": 60,
        "enabled": True,
        "auto_run": True,
    },
]
