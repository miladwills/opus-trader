"""Process and systemd probes."""

from __future__ import annotations
import asyncio
import time
from .base import BaseProbe
from ..models import ProbeResult


class SystemdProbe(BaseProbe):
    timeout_sec = 3.0
    cadence_sec = 30.0

    def __init__(self, unit_name: str, probe_name: str):
        self.unit_name = unit_name
        self.name = probe_name

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "is-active", self.unit_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            latency = (time.monotonic() - t0) * 1000
            state = stdout.decode().strip()
            is_active = state == "active"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=is_active, latency_ms=latency,
                status="ok" if is_active else "down",
                detail={"unit": self.unit_name, "state": state},
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={"unit": self.unit_name},
                error=str(e)[:200],
            )


class SystemResourcesProbe(BaseProbe):
    name = "sys_resources"
    cadence_sec = 30.0
    timeout_sec = 3.0

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            detail = {}
            # Load average
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                detail["load_1m"] = float(parts[0])
                detail["load_5m"] = float(parts[1])
                detail["load_15m"] = float(parts[2])

            # Memory from /proc/meminfo
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    if ":" in line:
                        key, val = line.split(":", 1)
                        meminfo[key.strip()] = int(val.strip().split()[0])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            detail["mem_total_mb"] = round(total_kb / 1024, 0)
            detail["mem_available_mb"] = round(avail_kb / 1024, 0)
            detail["mem_used_pct"] = round((1 - avail_kb / total_kb) * 100, 1) if total_kb else 0

            # Disk usage via statvfs
            import os
            st = os.statvfs("/var/www")
            total_bytes = st.f_blocks * st.f_frsize
            free_bytes = st.f_bavail * st.f_frsize
            detail["disk_total_gb"] = round(total_bytes / (1024**3), 1)
            detail["disk_free_gb"] = round(free_bytes / (1024**3), 1)
            detail["disk_used_pct"] = round((1 - free_bytes / total_bytes) * 100, 1) if total_bytes else 0

            # CPU usage from /proc/stat (two-sample delta for %)
            with open("/proc/stat") as f:
                c1 = f.readline().split()
            idle1 = int(c1[4])
            total1 = sum(int(x) for x in c1[1:])
            await asyncio.sleep(0.25)
            with open("/proc/stat") as f:
                c2 = f.readline().split()
            idle2 = int(c2[4])
            total2 = sum(int(x) for x in c2[1:])
            d_total = total2 - total1
            d_idle = idle2 - idle1
            detail["cpu_used_pct"] = round((1 - d_idle / d_total) * 100, 1) if d_total else 0
            detail["cpu_idle_jiffies"] = idle2
            detail["cpu_total_jiffies"] = total2

            latency = (time.monotonic() - t0) * 1000
            # Health based on CPU, memory and disk
            if detail["mem_used_pct"] > 95 or detail["disk_used_pct"] > 95 or detail["cpu_used_pct"] > 95:
                status = "down"
            elif detail["mem_used_pct"] > 85 or detail["disk_used_pct"] > 85 or detail["cpu_used_pct"] > 90:
                status = "degraded"
            else:
                status = "ok"

            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status=status,
                detail=detail,
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )
