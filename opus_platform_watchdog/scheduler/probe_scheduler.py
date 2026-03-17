"""Async probe scheduler: one task per probe with independent cadence."""

from __future__ import annotations
import asyncio
import logging
import time
from ..probes.base import BaseProbe
from ..storage.repo import Repository

logger = logging.getLogger("watchdog.scheduler")


class ProbeScheduler:
    def __init__(self, repo: Repository, probes: list[BaseProbe]):
        self._repo = repo
        self._probes = probes
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self):
        self._running = True
        for probe in self._probes:
            task = asyncio.create_task(
                self._run_loop(probe),
                name=f"probe_{probe.name}",
            )
            self._tasks.append(task)
        logger.info("Scheduler started %d probes", len(self._probes))

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Scheduler stopped")

    async def _run_loop(self, probe: BaseProbe):
        # Stagger start by a fraction of cadence to avoid all probes firing at once
        import hashlib
        stagger = int(hashlib.md5(probe.name.encode()).hexdigest()[:4], 16) % int(probe.cadence_sec * 1000)
        await asyncio.sleep(stagger / 1000.0)

        while self._running:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    probe.execute(),
                    timeout=probe.timeout_sec + 1.0,
                )
            except asyncio.TimeoutError:
                from ..models import ProbeResult
                result = ProbeResult(
                    probe_name=probe.name,
                    timestamp=time.time(),
                    success=False,
                    latency_ms=(time.monotonic() - t0) * 1000,
                    status="timeout",
                    detail={},
                    error="probe_timeout",
                )
            except asyncio.CancelledError:
                return
            except Exception as e:
                from ..models import ProbeResult
                result = ProbeResult(
                    probe_name=probe.name,
                    timestamp=time.time(),
                    success=False,
                    latency_ms=(time.monotonic() - t0) * 1000,
                    status="error",
                    detail={},
                    error=str(e)[:200],
                )
            try:
                await self._repo.store_probe_result(result)
                if result.latency_ms > 0 and probe.name.startswith("http_"):
                    endpoint = {
                        "http_bootstrap": "/api/dashboard/bootstrap",
                        "http_bridge_diag": "/api/bridge/diagnostics",
                        "http_services": "/api/services/status",
                    }.get(probe.name)
                    sc = result.detail.get("status_code")
                    await self._repo.store_latency_sample(
                        probe.name, result.timestamp, result.latency_ms, endpoint, sc
                    )
            except Exception as e:
                logger.error("Failed to store result for %s: %s", probe.name, e)

            elapsed = time.monotonic() - t0
            sleep_for = max(0.5, probe.cadence_sec - elapsed)
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                return
