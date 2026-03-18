"""Read-only collector for trader storage files."""

import json
import os
import time
import logging

from trading_watchdog.config import (
    BOTS_PATH,
    RISK_STATE_PATH,
    WATCHDOG_STATE_PATH,
    AUDIT_SUMMARY_PATH,
    SYMBOL_PNL_PATH,
    TRADE_LOGS_PATH,
    STORAGE_STALE_THRESHOLD_SEC,
)

log = logging.getLogger("tw.collector.storage")


def _read_json(path, default=None):
    """Safe JSON file read with age tracking."""
    try:
        if not os.path.exists(path):
            return default, -1, False
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        with open(path, "r") as f:
            data = json.load(f)
        return data, age, age < STORAGE_STALE_THRESHOLD_SEC
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read %s: %s", path, e)
        return default, -1, False


class StorageCollector:
    """Reads trader storage files without locking or mutation."""

    def collect_bots(self):
        """Read persisted bot configs from bots.json."""
        data, age, fresh = _read_json(BOTS_PATH, default=[])
        return {"bots": data if isinstance(data, list) else [], "age_sec": age, "fresh": fresh}

    def collect_risk_state(self):
        """Read daily risk state."""
        data, age, fresh = _read_json(RISK_STATE_PATH, default={})
        return {"data": data, "age_sec": age, "fresh": fresh}

    def collect_watchdog_state(self):
        """Read embedded watchdog active state."""
        data, age, fresh = _read_json(WATCHDOG_STATE_PATH, default={})
        return {"data": data, "age_sec": age, "fresh": fresh}

    def collect_audit_summary(self):
        """Read audit diagnostics summary."""
        data, age, fresh = _read_json(AUDIT_SUMMARY_PATH, default={})
        return {"data": data, "age_sec": age, "fresh": fresh}

    def collect_symbol_pnl(self):
        """Read symbol-level PnL."""
        data, age, fresh = _read_json(SYMBOL_PNL_PATH, default={})
        return {"data": data, "age_sec": age, "fresh": fresh}

    def collect_trade_logs(self):
        """Read trade logs (bounded: last 200 entries)."""
        data, age, fresh = _read_json(TRADE_LOGS_PATH, default=[])
        if isinstance(data, list) and len(data) > 200:
            data = data[-200:]
        return {"trades": data if isinstance(data, list) else [], "age_sec": age, "fresh": fresh}

    def collect_all(self):
        """Collect all storage sources in one pass."""
        return {
            "bots": self.collect_bots(),
            "risk_state": self.collect_risk_state(),
            "watchdog_state": self.collect_watchdog_state(),
            "audit_summary": self.collect_audit_summary(),
            "symbol_pnl": self.collect_symbol_pnl(),
            "trade_logs": self.collect_trade_logs(),
        }
