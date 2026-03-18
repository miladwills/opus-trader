"""Staggered 3-lane data collector for AI Ops.

Fast lane (15s):  watchdog health, trader service status
Medium lane (30s): watchdog incidents/probes, trader health-summary
Slow lane (60s):  trader bridge diagnostics, bridge file, log tails
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

from . import config
from .models import SystemSnapshot

logger = logging.getLogger("aiops.collector")


# ---------------------------------------------------------------------------
# Source functions — each returns partial data for the snapshot
# ---------------------------------------------------------------------------

async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 5.0,
    label: str = "",
) -> tuple[dict | list | None, str | None]:
    """Fetch JSON from an HTTP endpoint. Returns (data, error_or_None)."""
    try:
        resp = await client.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        logger.debug("Source %s failed: %s", label or url, exc)
        return None, str(exc)


# --- Watchdog sources ---

async def fetch_watchdog_health(wdg: httpx.AsyncClient) -> dict:
    data, err = await _fetch_json(wdg, f"{config.WATCHDOG_BASE_URL}/api/health/current", label="watchdog_health")
    if err:
        return {"source_error": err}
    return {
        "health_score": (data or {}).get("overall_score"),
        "health_status": (data or {}).get("overall_status"),
        "component_scores": (data or {}).get("components"),
    }


async def fetch_watchdog_incidents(wdg: httpx.AsyncClient) -> dict:
    data, err = await _fetch_json(wdg, f"{config.WATCHDOG_BASE_URL}/api/incidents/recent?limit=20", label="watchdog_incidents")
    if err:
        return {"source_error": err}
    return {"active_incidents": data if isinstance(data, list) else []}


async def fetch_watchdog_probes(wdg: httpx.AsyncClient) -> dict:
    data, err = await _fetch_json(wdg, f"{config.WATCHDOG_BASE_URL}/api/probes/all", label="watchdog_probes")
    if err:
        return {"source_error": err}
    return {"probe_results": data if isinstance(data, dict) else {}}


# --- Trader sources ---

async def fetch_trader_status(trader: httpx.AsyncClient) -> dict:
    data, err = await _fetch_json(trader, f"{config.TRADER_BASE_URL}/api/services/status", timeout=8.0, label="trader_status")
    if err:
        return {"source_error": err}
    return {
        "runner_active": (data or {}).get("runner_active"),
        "runner_pid": (data or {}).get("runner_pid"),
        "stop_flag_exists": (data or {}).get("stop_flag_exists"),
    }


async def fetch_trader_health_summary(trader: httpx.AsyncClient) -> dict:
    data, err = await _fetch_json(trader, f"{config.TRADER_BASE_URL}/api/aiops/health-summary", timeout=8.0, label="trader_health_summary")
    if err:
        return {"source_error": err}
    return {
        "runner_active": (data or {}).get("runner_active"),
        "runner_pid": (data or {}).get("runner_pid"),
        "bridge_producer_alive": (data or {}).get("bridge_producer_alive"),
        "bridge_produced_at": (data or {}).get("bridge_produced_at"),
        "bridge_stale_sections": (data or {}).get("bridge_stale_sections", []),
        "bridge_stale_count": (data or {}).get("bridge_stale_count"),
        "bot_status_counts": (data or {}).get("bot_status_counts", {}),
        "bot_total": (data or {}).get("bot_total"),
        "flash_crash_active": (data or {}).get("flash_crash_active"),
        "stop_flag_exists": (data or {}).get("stop_flag_exists"),
    }


async def fetch_trader_bridge_diagnostics(trader: httpx.AsyncClient) -> dict:
    data, err = await _fetch_json(trader, f"{config.TRADER_BASE_URL}/api/bridge/diagnostics", timeout=8.0, label="trader_bridge_diag")
    if err:
        return {"source_error": err}
    return {"bridge_diagnostics": data}


# --- File sources (run in thread to avoid blocking event loop) ---

def _read_bridge_bots_light() -> dict:
    """Read bots_runtime_light from bridge file. Bounded JSON parse."""
    try:
        path = config.BRIDGE_JSON_PATH
        if not os.path.exists(path):
            return {"source_error": "bridge file missing"}
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        sections = data.get("sections", {})
        light = sections.get("bots_runtime_light", {}).get("payload", {})
        bots = light.get("bots", [])
        return {"bridge_bots_light": bots}
    except Exception as exc:
        return {"source_error": str(exc)}


def _read_log_tail(path: str, max_bytes: int) -> list[str]:
    """Read last max_bytes of a log file, return as lines."""
    try:
        if not os.path.exists(path):
            return []
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # discard partial line
            return f.readlines()
    except Exception:
        return []


async def fetch_file_sources() -> dict:
    """Read bridge bots light + log tails in a thread."""
    loop = asyncio.get_event_loop()
    bridge_result = await loop.run_in_executor(None, _read_bridge_bots_light)
    runner_lines = await loop.run_in_executor(
        None, _read_log_tail, config.RUNNER_LOG_PATH, config.LOG_SCAN_BYTES,
    )
    app_lines = await loop.run_in_executor(
        None, _read_log_tail, config.APP_LOG_PATH, config.LOG_SCAN_BYTES,
    )
    result: dict[str, Any] = {}
    if "source_error" in bridge_result:
        result["source_error_bridge_file"] = bridge_result["source_error"]
    else:
        result["bridge_bots_light"] = bridge_result.get("bridge_bots_light", [])
    result["runner_log_lines"] = runner_lines[-200:]  # cap at 200 lines
    result["app_log_lines"] = app_lines[-200:]
    return result


# ---------------------------------------------------------------------------
# Staggered collector
# ---------------------------------------------------------------------------

class StaggeredCollector:
    """Runs 3-lane data collection and merges results into SystemSnapshot."""

    def __init__(self):
        self._watchdog_client: httpx.AsyncClient | None = None
        self._trader_client: httpx.AsyncClient | None = None
        self._last_fast: float = 0.0
        self._last_medium: float = 0.0
        self._last_slow: float = 0.0
        # Cached partial results from each lane
        self._fast_data: dict = {}
        self._medium_data: dict = {}
        self._slow_data: dict = {}
        self._source_errors: dict = {}
        self._latest_snapshot: SystemSnapshot | None = None
        self._collection_count: int = 0

    async def start(self):
        self._watchdog_client = httpx.AsyncClient(
            auth=(config.WATCHDOG_AUTH_USER, config.WATCHDOG_AUTH_PASS),
        )
        self._trader_client = httpx.AsyncClient(
            auth=(config.TRADER_AUTH_USER, config.TRADER_AUTH_PASS),
        )

    async def stop(self):
        if self._watchdog_client:
            await self._watchdog_client.aclose()
        if self._trader_client:
            await self._trader_client.aclose()

    async def collect(self) -> SystemSnapshot:
        """Run one collection cycle. Respects lane cadences."""
        now = time.time()
        timing: dict[str, float] = {}
        errors: dict[str, str] = {}

        # Fast lane
        if now - self._last_fast >= config.FAST_LANE_INTERVAL:
            t0 = time.monotonic()
            fast = await self._run_fast_lane(errors)
            timing["fast_ms"] = round((time.monotonic() - t0) * 1000, 1)
            self._fast_data.update(fast)
            self._last_fast = now

        # Medium lane
        if now - self._last_medium >= config.MEDIUM_LANE_INTERVAL:
            t0 = time.monotonic()
            medium = await self._run_medium_lane(errors)
            timing["medium_ms"] = round((time.monotonic() - t0) * 1000, 1)
            self._medium_data.update(medium)
            self._last_medium = now

        # Slow lane
        if now - self._last_slow >= config.SLOW_LANE_INTERVAL:
            t0 = time.monotonic()
            slow = await self._run_slow_lane(errors)
            timing["slow_ms"] = round((time.monotonic() - t0) * 1000, 1)
            self._slow_data.update(slow)
            self._last_slow = now

        self._source_errors = errors
        self._collection_count += 1

        # Merge all lane data into a snapshot
        snapshot = self._merge_snapshot(now, timing)
        self._latest_snapshot = snapshot
        return snapshot

    async def _run_fast_lane(self, errors: dict) -> dict:
        """Watchdog health + trader service status."""
        results: list[dict] = await asyncio.gather(
            fetch_watchdog_health(self._watchdog_client),
            fetch_trader_status(self._trader_client),
            return_exceptions=False,
        )
        merged: dict = {}
        for i, (label, r) in enumerate(zip(["watchdog_health", "trader_status"], results)):
            if isinstance(r, dict) and "source_error" in r:
                errors[label] = r["source_error"]
            elif isinstance(r, dict):
                merged.update(r)
            elif isinstance(r, Exception):
                errors[label] = str(r)
        return merged

    async def _run_medium_lane(self, errors: dict) -> dict:
        """Watchdog incidents/probes + trader health-summary."""
        results = await asyncio.gather(
            fetch_watchdog_incidents(self._watchdog_client),
            fetch_watchdog_probes(self._watchdog_client),
            fetch_trader_health_summary(self._trader_client),
            return_exceptions=False,
        )
        labels = ["watchdog_incidents", "watchdog_probes", "trader_health_summary"]
        merged: dict = {}
        for label, r in zip(labels, results):
            if isinstance(r, dict) and "source_error" in r:
                errors[label] = r["source_error"]
            elif isinstance(r, dict):
                merged.update(r)
            elif isinstance(r, Exception):
                errors[label] = str(r)
        return merged

    async def _run_slow_lane(self, errors: dict) -> dict:
        """Bridge diagnostics + bridge file read + log tails."""
        results = await asyncio.gather(
            fetch_trader_bridge_diagnostics(self._trader_client),
            fetch_file_sources(),
            return_exceptions=False,
        )
        labels = ["trader_bridge_diag", "file_sources"]
        merged: dict = {}
        for label, r in zip(labels, results):
            if isinstance(r, dict):
                # File sources may have individual source errors
                for k, v in r.items():
                    if k.startswith("source_error"):
                        errors[k] = v
                    else:
                        merged[k] = v
            elif isinstance(r, Exception):
                errors[label] = str(r)
        return merged

    def _merge_snapshot(self, now: float, timing: dict) -> SystemSnapshot:
        """Merge fast + medium + slow lane data into a SystemSnapshot."""
        all_data = {}
        all_data.update(self._fast_data)
        all_data.update(self._medium_data)
        all_data.update(self._slow_data)

        return SystemSnapshot(
            timestamp=now,
            health_score=all_data.get("health_score"),
            health_status=all_data.get("health_status"),
            component_scores=all_data.get("component_scores"),
            active_incidents=all_data.get("active_incidents"),
            probe_results=all_data.get("probe_results"),
            runner_active=all_data.get("runner_active"),
            runner_pid=all_data.get("runner_pid"),
            bridge_producer_alive=all_data.get("bridge_producer_alive"),
            bridge_produced_at=all_data.get("bridge_produced_at"),
            bridge_stale_sections=all_data.get("bridge_stale_sections"),
            bridge_stale_count=all_data.get("bridge_stale_count"),
            bot_status_counts=all_data.get("bot_status_counts"),
            bot_total=all_data.get("bot_total"),
            flash_crash_active=all_data.get("flash_crash_active"),
            stop_flag_exists=all_data.get("stop_flag_exists"),
            bridge_diagnostics=all_data.get("bridge_diagnostics"),
            bridge_bots_light=all_data.get("bridge_bots_light"),
            runner_log_lines=all_data.get("runner_log_lines"),
            app_log_lines=all_data.get("app_log_lines"),
            source_errors=dict(self._source_errors),
            collection_timing=timing,
        )

    @property
    def latest_snapshot(self) -> SystemSnapshot | None:
        return self._latest_snapshot

    @property
    def collection_count(self) -> int:
        return self._collection_count

    @property
    def source_errors(self) -> dict:
        return dict(self._source_errors)

    @property
    def lane_ages(self) -> dict:
        now = time.time()
        return {
            "fast_age_sec": round(now - self._last_fast, 1) if self._last_fast else None,
            "medium_age_sec": round(now - self._last_medium, 1) if self._last_medium else None,
            "slow_age_sec": round(now - self._last_slow, 1) if self._last_slow else None,
        }
