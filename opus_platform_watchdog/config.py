"""Configuration for Platform Watchdog."""

import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load .env from watchdog directory
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# --- Watchdog auth ---
WATCHDOG_AUTH_USER = os.getenv("WATCHDOG_AUTH_USER", "admin")
WATCHDOG_AUTH_PASS = os.getenv("WATCHDOG_AUTH_PASS", "changeme")

# --- Opus Trader connection ---
OPUS_BASE_URL = os.getenv("OPUS_TRADER_BASE_URL", "http://127.0.0.1:8000")
OPUS_AUTH_USER = os.getenv("OPUS_TRADER_AUTH_USER", "admin")
OPUS_AUTH_PASS = os.getenv("OPUS_TRADER_AUTH_PASS", "")
_parsed_opus_base = urlparse(OPUS_BASE_URL)
OPUS_TRADER_PORT = int(
    os.getenv(
        "OPUS_TRADER_PORT",
        str(_parsed_opus_base.port or (443 if _parsed_opus_base.scheme == "https" else 8000)),
    )
)
OPUS_APP_PATH = os.getenv("OPUS_APP_PATH", "/var/www/app.py")
OPUS_RUNNER_PATH = os.getenv("OPUS_RUNNER_PATH", "/var/www/runner.py")
OPUS_TRADER_SYSTEMD_UNIT = os.getenv("OPUS_TRADER_SYSTEMD_UNIT", "opus_trader")
OPUS_RUNNER_SYSTEMD_UNIT = os.getenv("OPUS_RUNNER_SYSTEMD_UNIT", "opus_runner")

# --- Paths to monitor ---
OPUS_RUNNER_LOG = os.getenv("OPUS_RUNNER_LOG", "/var/www/storage/runner.log")
OPUS_APP_LOG = os.getenv("OPUS_APP_LOG", "/var/www/storage/app.log")
OPUS_BRIDGE_JSON = os.getenv("OPUS_BRIDGE_JSON", "/var/www/storage/runtime_snapshot_bridge.json")
OPUS_RUNNER_LOCK = os.getenv("OPUS_RUNNER_LOCK", "/var/www/storage/runner.lock")

# --- Watchdog settings ---
WATCHDOG_PORT = int(os.getenv("WATCHDOG_PORT", "9000"))
DB_PATH = os.getenv("WATCHDOG_DB_PATH", str(Path(__file__).parent / "watchdog.db"))
LOG_SCAN_BYTES = int(os.getenv("LOG_SCAN_BYTES", "65536"))

# --- Retention (days) ---
RETENTION_PROBE_RESULTS_DAYS = int(os.getenv("RETENTION_PROBE_RESULTS_DAYS", "7"))
RETENTION_INCIDENTS_DAYS = int(os.getenv("RETENTION_INCIDENTS_DAYS", "30"))
RETENTION_HEALTH_DAYS = int(os.getenv("RETENTION_HEALTH_DAYS", "7"))
RETENTION_LATENCY_DAYS = int(os.getenv("RETENTION_LATENCY_DAYS", "3"))

# --- Bridge stale thresholds (seconds) ---
BRIDGE_STALE_THRESHOLDS = {
    "market": 5.0,
    "open_orders": 6.0,
    "positions": 8.0,
    "bots_runtime": 6.0,
    "bots_runtime_light": 6.0,
    "summary": 12.0,
}
