"""Process and systemd probes."""

from __future__ import annotations
import asyncio
import time
from .base import BaseProbe
from ..models import ProbeResult


class DirectRuntimeProbe(BaseProbe):
    timeout_sec = 3.0
    cadence_sec = 30.0

    def __init__(
        self,
        *,
        probe_name: str,
        script_path: str,
        label: str,
        match_terms: list[str] | None = None,
        port: int | None = None,
        systemd_unit: str | None = None,
    ):
        self.name = probe_name
        self.script_path = script_path
        self.label = label
        terms = [script_path]
        for term in match_terms or []:
            if term and term not in terms:
                terms.append(term)
        self.match_terms = terms
        self.port = int(port) if port is not None else None
        self.systemd_unit = systemd_unit

    async def _exec(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            int(proc.returncode or 0),
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    async def _find_matching_processes(self) -> list[dict[str, object]]:
        rc, stdout, _ = await self._exec("ps", "-eo", "pid=,args=")
        if rc != 0:
            return []
        matches: list[dict[str, object]] = []
        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            pid_text, args = parts
            if not any(term in args for term in self.match_terms):
                continue
            try:
                pid = int(pid_text)
            except (TypeError, ValueError):
                continue
            matches.append({"pid": pid, "cmdline": args})
        return matches

    async def _find_listening_pids(self) -> list[int]:
        if self.port is None:
            return []
        rc, stdout, _ = await self._exec(
            "lsof",
            "-nP",
            f"-iTCP:{self.port}",
            "-sTCP:LISTEN",
        )
        if rc != 0 and not stdout.strip():
            return []
        pids: list[int] = []
        for line in stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                pids.append(int(parts[1]))
            except (TypeError, ValueError):
                continue
        return sorted(set(pids))

    async def _get_systemd_state(self) -> str | None:
        if not self.systemd_unit:
            return None
        rc, stdout, stderr = await self._exec(
            "systemctl",
            "is-active",
            self.systemd_unit,
        )
        state = stdout.strip() or stderr.strip()
        if state:
            return state
        if rc != 0:
            return "unknown"
        return None

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            processes = await self._find_matching_processes()
            pids = [int(item["pid"]) for item in processes]
            listening_pids = await self._find_listening_pids()
            systemd_state = await self._get_systemd_state()
            latency = (time.monotonic() - t0) * 1000
            pid = pids[0] if pids else None
            detail = {
                "label": self.label,
                "probe_mode": "runtime_process",
                "script_path": self.script_path,
                "match_terms": list(self.match_terms),
                "pid": pid,
                "pids": pids,
                "pid_count": len(pids),
                "cmdline": str(processes[0]["cmdline"]) if processes else None,
                "state": "missing",
            }
            if self.port is not None:
                detail["port"] = self.port
                detail["listening_pids"] = listening_pids
                detail["port_listening"] = bool(set(pids) & set(listening_pids))
            if systemd_state is not None:
                detail["systemd_unit"] = self.systemd_unit
                detail["systemd_state"] = systemd_state

            is_active = bool(pids)
            status = "ok"
            if not is_active:
                status = "down"
                detail["state"] = "missing"
            elif self.port is not None and not bool(set(pids) & set(listening_pids)):
                status = "down"
                detail["state"] = "port_not_listening"
            elif self.port is not None:
                detail["state"] = "listening"
            else:
                detail["state"] = "running"
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=is_active, latency_ms=latency,
                status=status,
                detail=detail,
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={"label": self.label, "script_path": self.script_path},
                error=str(e)[:200],
            )


class SystemResourcesProbe(BaseProbe):
    name = "sys_resources"
    cadence_sec = 30.0
    timeout_sec = 3.0

    def __init__(self):
        self._previous_cpu_sample: tuple[int, int] | None = None

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

            # CPU usage from /proc/stat (simple instant snapshot)
            with open("/proc/stat") as f:
                cpu_line = f.readline().split()
            # cpu_line: cpu user nice system idle iowait irq softirq
            idle = int(cpu_line[4])
            total = sum(int(x) for x in cpu_line[1:])
            detail["cpu_idle_jiffies"] = idle
            detail["cpu_total_jiffies"] = total
            previous_cpu_sample = self._previous_cpu_sample
            if previous_cpu_sample is not None:
                previous_idle, previous_total = previous_cpu_sample
                delta_total = max(total - previous_total, 0)
                delta_idle = max(idle - previous_idle, 0)
                if delta_total > 0:
                    detail["cpu_used_pct"] = round(
                        max(0.0, min(100.0, (1 - (delta_idle / delta_total)) * 100.0)),
                        1,
                    )
            self._previous_cpu_sample = (idle, total)

            latency = (time.monotonic() - t0) * 1000
            # Health based on memory and disk
            if detail["mem_used_pct"] > 95 or detail["disk_used_pct"] > 95:
                status = "down"
            elif detail["mem_used_pct"] > 85 or detail["disk_used_pct"] > 85:
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
