"""File-based probes: bridge JSON, runner lock, log freshness."""

from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path
from .base import BaseProbe
from ..models import ProbeResult
from .. import config


class BridgeJsonProbe(BaseProbe):
    name = "file_bridge"
    cadence_sec = 10.0
    timeout_sec = 2.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            data = await asyncio.to_thread(self._read_bridge)
            latency = (time.monotonic() - t0) * 1000
            if data is None:
                return ProbeResult(
                    probe_name=self.name, timestamp=time.time(),
                    success=False, latency_ms=latency, status="down",
                    detail={}, error="bridge_file_missing_or_unparseable",
                )
            meta = data.get("meta", {})
            produced_at = meta.get("produced_at", 0)
            age = time.time() - produced_at if produced_at else 999
            producer_pid = meta.get("producer_pid")
            snapshot_epoch = meta.get("snapshot_epoch", 0)
            sections = data.get("sections", {})
            section_ages = {}
            now = time.time()
            for sec_name, sec_data in sections.items():
                pub = sec_data.get("published_at", 0)
                sec_age = now - pub if pub else 999
                threshold = config.BRIDGE_STALE_THRESHOLDS.get(sec_name, 10.0)
                section_ages[sec_name] = {
                    "age_sec": round(sec_age, 1),
                    "stale": sec_age > threshold,
                    "threshold": threshold,
                }
            stale_count = sum(1 for v in section_ages.values() if v["stale"])
            if age > 30:
                status = "down"
            elif stale_count >= 3:
                status = "degraded"
            else:
                status = "ok"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status=status,
                detail={
                    "bridge_age_sec": round(age, 1),
                    "producer_pid": producer_pid,
                    "snapshot_epoch": snapshot_epoch,
                    "section_count": len(sections),
                    "stale_count": stale_count,
                    "sections": section_ages,
                },
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )

    def _read_bridge(self) -> dict | None:
        path = Path(config.OPUS_BRIDGE_JSON)
        if not path.exists():
            return None
        try:
            raw = path.read_text()
            return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return None


class RunnerLockProbe(BaseProbe):
    name = "file_runner_lock"
    cadence_sec = 15.0
    timeout_sec = 1.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            result = await asyncio.to_thread(self._check_lock)
            latency = (time.monotonic() - t0) * 1000
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=result["exists"], latency_ms=latency,
                status=result["status"], detail=result,
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )

    def _check_lock(self) -> dict:
        path = Path(config.OPUS_RUNNER_LOCK)
        if not path.exists():
            return {"exists": False, "pid": None, "pid_alive": False, "status": "down"}
        try:
            pid_str = path.read_text().strip()
            pid = int(pid_str)
        except (ValueError, OSError):
            return {"exists": True, "pid": None, "pid_alive": False, "status": "degraded"}
        try:
            os.kill(pid, 0)
            alive = True
        except (ProcessLookupError, PermissionError):
            alive = False
        return {
            "exists": True,
            "pid": pid,
            "pid_alive": alive,
            "status": "ok" if alive else "down",
        }


class LogFreshnessProbe(BaseProbe):
    name = "file_log_fresh"
    cadence_sec = 15.0
    timeout_sec = 1.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            result = await asyncio.to_thread(self._check_logs)
            latency = (time.monotonic() - t0) * 1000
            worst_age = max(result.get("runner_age", 999), result.get("app_age", 999))
            if worst_age > 120:
                status = "down"
            elif worst_age > 60:
                status = "degraded"
            else:
                status = "ok"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status=status,
                detail=result,
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )

    def _check_logs(self) -> dict:
        now = time.time()
        result = {}
        for key, path_str in [("runner", config.OPUS_RUNNER_LOG), ("app", config.OPUS_APP_LOG)]:
            path = Path(path_str)
            if path.exists():
                mtime = path.stat().st_mtime
                result[f"{key}_age"] = round(now - mtime, 1)
                result[f"{key}_size"] = path.stat().st_size
                result[f"{key}_exists"] = True
            else:
                result[f"{key}_age"] = 999
                result[f"{key}_size"] = 0
                result[f"{key}_exists"] = False
        return result
