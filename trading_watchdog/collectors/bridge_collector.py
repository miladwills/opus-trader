"""Read-only collector for runtime_snapshot_bridge.json."""

import json
import os
import time
import logging

from trading_watchdog.config import BRIDGE_PATH, BRIDGE_STALE_THRESHOLD_SEC

log = logging.getLogger("tw.collector.bridge")


class BridgeCollector:
    """Reads the runner-published runtime snapshot bridge atomically."""

    def __init__(self, path=None):
        self.path = path or BRIDGE_PATH
        self._last_data = None
        self._last_read_at = 0
        self._last_mtime = 0

    def collect(self):
        """Read bridge snapshot. Returns dict or None on failure."""
        try:
            if not os.path.exists(self.path):
                log.warning("Bridge file not found: %s", self.path)
                return None

            mtime = os.path.getmtime(self.path)
            age = time.time() - mtime

            with open(self.path, "r") as f:
                data = json.load(f)

            data["_tw_meta"] = {
                "file_mtime": mtime,
                "file_age_sec": round(age, 1),
                "fresh": age < BRIDGE_STALE_THRESHOLD_SEC,
                "read_at": time.time(),
            }

            self._last_data = data
            self._last_read_at = time.time()
            self._last_mtime = mtime
            return data

        except json.JSONDecodeError as e:
            log.error("Bridge JSON parse error: %s", e)
            return self._last_data
        except OSError as e:
            log.error("Bridge read error: %s", e)
            return self._last_data

    def _unwrap(self, section):
        """Unwrap payload wrapper if present. Bridge sections use {payload: ...} format."""
        if isinstance(section, dict) and "payload" in section:
            return section["payload"]
        return section

    def get_bots_runtime(self, data):
        """Extract bots from bridge. Prefers bots_runtime_light."""
        if not data or "sections" not in data:
            return []
        sections = data["sections"]
        # Prefer light payload (always present), fall back to full
        light = self._unwrap(sections.get("bots_runtime_light", {}))
        if light and isinstance(light, dict) and "bots" in light:
            return light["bots"]
        full = self._unwrap(sections.get("bots_runtime", {}))
        if full and isinstance(full, dict) and "bots" in full:
            return full["bots"]
        return []

    def get_positions(self, data):
        """Extract positions from bridge."""
        if not data or "sections" not in data:
            return {"positions": [], "summary": {}, "stale": True}
        pos = self._unwrap(data["sections"].get("positions", {}))
        if not isinstance(pos, dict):
            return {"positions": [], "summary": {}, "stale": True}
        return {
            "positions": pos.get("positions", []),
            "summary": pos.get("summary", {}),
            "wallet_balance": pos.get("wallet_balance"),
            "available_balance": pos.get("available_balance"),
            "stale": pos.get("stale_data", True),
        }

    def get_market(self, data):
        """Extract market health from bridge."""
        if not data or "sections" not in data:
            return {"health": "unavailable", "stale": True}
        return self._unwrap(data["sections"].get("market", {"health": "unavailable", "stale": True}))

    def get_summary(self, data):
        """Extract account summary from bridge."""
        if not data or "sections" not in data:
            return {}
        return self._unwrap(data["sections"].get("summary", {}))

    def get_stream_health(self, data):
        """Extract stream/connection health from bridge meta."""
        if not data or "meta" not in data:
            return {}
        return data.get("meta", {}).get("stream_health", {})

    def get_bridge_meta(self, data):
        """Return bridge-level metadata."""
        if not data:
            return {"fresh": False, "age_sec": -1}
        tw = data.get("_tw_meta", {})
        return {
            "fresh": tw.get("fresh", False),
            "age_sec": tw.get("file_age_sec", -1),
            "snapshot_epoch": data.get("snapshot_epoch"),
            "producer_pid": data.get("meta", {}).get("producer_pid"),
        }
