"""HTTP probes against Opus Trader API endpoints."""

from __future__ import annotations
import time
import httpx
from .base import BaseProbe
from ..models import ProbeResult
from .. import config


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=config.OPUS_BASE_URL,
        auth=(config.OPUS_AUTH_USER, config.OPUS_AUTH_PASS) if config.OPUS_AUTH_PASS else None,
        timeout=10.0,
        verify=False,
    )


class BootstrapProbe(BaseProbe):
    name = "http_bootstrap"
    cadence_sec = 30.0
    timeout_sec = 8.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            async with _client() as client:
                resp = await client.get("/api/dashboard/bootstrap")
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code != 200:
                return ProbeResult(
                    probe_name=self.name, timestamp=time.time(),
                    success=False, latency_ms=latency, status="error",
                    detail={"status_code": resp.status_code},
                    error=f"HTTP {resp.status_code}",
                )
            data = resp.json()
            has_summary = "summary" in data
            has_positions = "positions" in data
            has_bots = "bots" in data or "bots_runtime_light" in data
            all_present = has_summary and has_positions and has_bots
            status = "ok" if all_present else "degraded"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status=status,
                detail={
                    "status_code": resp.status_code,
                    "has_summary": has_summary,
                    "has_positions": has_positions,
                    "has_bots": has_bots,
                    "payload_keys": list(data.keys())[:20],
                    "response_bytes": len(resp.content),
                },
            )
        except httpx.TimeoutException:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="timeout", detail={}, error="request_timeout",
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )


class BridgeDiagnosticsProbe(BaseProbe):
    name = "http_bridge_diag"
    cadence_sec = 15.0
    timeout_sec = 5.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            async with _client() as client:
                resp = await client.get("/api/bridge/diagnostics")
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code != 200:
                return ProbeResult(
                    probe_name=self.name, timestamp=time.time(),
                    success=False, latency_ms=latency, status="error",
                    detail={"status_code": resp.status_code},
                    error=f"HTTP {resp.status_code}",
                )
            data = resp.json()
            sections = data.get("sections", {})
            producer_alive = data.get("producer_alive", False)
            stale_sections = []
            section_detail = {}
            for name, info in sections.items():
                is_stale = info.get("stale", True)
                if is_stale:
                    stale_sections.append(name)
                section_detail[name] = {
                    "present": info.get("present", False),
                    "stale": is_stale,
                    "age_sec": round(info.get("age_sec", -1), 1),
                    "shape_valid": info.get("shape_valid", False),
                }
            if not producer_alive:
                status = "down"
            elif len(stale_sections) >= 3:
                status = "degraded"
            else:
                status = "ok"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status=status,
                detail={
                    "producer_alive": producer_alive,
                    "stale_sections": stale_sections,
                    "stale_count": len(stale_sections),
                    "total_sections": len(sections),
                    "sections": section_detail,
                    "snapshot_epoch": data.get("snapshot_epoch"),
                },
            )
        except httpx.TimeoutException:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="timeout", detail={}, error="request_timeout",
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )


class ServicesStatusProbe(BaseProbe):
    name = "http_services"
    cadence_sec = 15.0
    timeout_sec = 5.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            async with _client() as client:
                resp = await client.get("/api/services/status")
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code != 200:
                return ProbeResult(
                    probe_name=self.name, timestamp=time.time(),
                    success=False, latency_ms=latency, status="error",
                    detail={"status_code": resp.status_code},
                    error=f"HTTP {resp.status_code}",
                )
            data = resp.json()
            runner_active = data.get("runner_active", False)
            status = "ok" if runner_active else "down"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status=status,
                detail={
                    "runner_active": runner_active,
                    "runner_pid": data.get("runner_pid"),
                    "stop_flag_exists": data.get("stop_flag_exists", False),
                },
            )
        except httpx.TimeoutException:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="timeout", detail={}, error="request_timeout",
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )
