"""Async systemd service management utilities."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from .. import config

logger = logging.getLogger("watchdog.systemd")

_SHOW_PROPERTIES = (
    "ActiveState,SubState,MainPID,MemoryCurrent,"
    "ActiveEnterTimestamp,NRestarts,Description"
)


def _parse_memory(raw: str) -> float | None:
    """Convert MemoryCurrent bytes string to MB. Returns None if unavailable."""
    if not raw or raw in ("[not set]", "infinity", ""):
        return None
    try:
        return round(int(raw) / (1024 * 1024), 1)
    except (ValueError, TypeError):
        return None


def _parse_uptime(raw: str) -> float | None:
    """Convert ActiveEnterTimestamp to uptime seconds. Returns None if unavailable."""
    if not raw or raw in ("", "n/a"):
        return None
    # systemd format: "Wed 2026-03-18 10:30:00 UTC" or similar
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S %z"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, time.time() - dt.timestamp())
        except ValueError:
            continue
    return None


async def get_service_detail(unit: str) -> dict:
    """Get detailed status of a single systemd unit."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "show", unit,
            f"--property={_SHOW_PROPERTIES}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        raw = {}
        for line in stdout.decode().strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                raw[k.strip()] = v.strip()

        active_state = raw.get("ActiveState", "unknown")
        sub_state = raw.get("SubState", "unknown")
        pid = int(raw.get("MainPID", "0")) or None
        memory_mb = _parse_memory(raw.get("MemoryCurrent", ""))
        # Only show uptime if service is currently active
        uptime_sec = _parse_uptime(raw.get("ActiveEnterTimestamp", "")) if active_state == "active" else None
        restarts = int(raw.get("NRestarts", "0"))
        description = raw.get("Description", "")

        return {
            "unit": unit,
            "active_state": active_state,
            "sub_state": sub_state,
            "pid": pid,
            "memory_mb": memory_mb,
            "uptime_seconds": uptime_sec,
            "restarts": restarts,
            "description": description,
        }
    except asyncio.TimeoutError:
        logger.warning("Timeout getting status for %s", unit)
        return {"unit": unit, "active_state": "unknown", "sub_state": "timeout",
                "pid": None, "memory_mb": None, "uptime_seconds": None,
                "restarts": 0, "description": ""}
    except Exception as e:
        logger.error("Error getting status for %s: %s", unit, e)
        return {"unit": unit, "active_state": "unknown", "sub_state": "error",
                "pid": None, "memory_mb": None, "uptime_seconds": None,
                "restarts": 0, "description": ""}


async def get_all_services_detail() -> list[dict]:
    """Get detailed status of all managed services."""
    results = []
    for svc in config.MANAGED_SERVICES:
        detail = await get_service_detail(svc["unit"])
        detail["label"] = svc["label"]
        detail["probe_name"] = svc["probe_name"]
        results.append(detail)
    return results


async def _kill_port_holder(port: int) -> None:
    """Kill any process listening on the given TCP port (rogue manual starts)."""
    if not port:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "fuser", "-k", f"{port}/tcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode == 0:
            logger.info("Killed rogue process on port %d", port)
    except Exception:
        pass  # fuser not found or no process — fine


async def _kill_lock_holder(lock_path: str) -> None:
    """Kill the process holding a lock file (PID written inside)."""
    if not lock_path:
        return
    import os
    try:
        with open(lock_path) as f:
            pid = int(f.read().strip())
        # Check it's not a systemd-managed process (ppid=1 from systemd is fine,
        # but we only kill if the unit is not active via systemd)
        os.kill(pid, 15)  # SIGTERM
        logger.info("Killed rogue lock holder PID %d from %s", pid, lock_path)
    except (FileNotFoundError, ValueError):
        pass
    except ProcessLookupError:
        # PID already gone — remove stale lock
        try:
            os.remove(lock_path)
            logger.info("Removed stale lock file %s", lock_path)
        except FileNotFoundError:
            pass
    except PermissionError:
        # Try with sudo
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "kill", str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except Exception:
            pass


def _svc_config(unit: str) -> dict | None:
    """Look up the managed service config for a unit."""
    for svc in config.MANAGED_SERVICES:
        if svc["unit"] == unit:
            return svc
    return None


async def _cleanup_rogue_processes(unit: str) -> None:
    """Kill any rogue manually-started process that would block systemd start."""
    svc = _svc_config(unit)
    if not svc:
        return

    port = svc.get("port")
    lock_path = svc.get("lock_file")

    if lock_path:
        await _kill_lock_holder(lock_path)
    if port:
        await _kill_port_holder(port)

    if port or lock_path:
        await asyncio.sleep(1)  # let resources release


async def restart_service(unit: str) -> dict:
    """Restart a single systemd unit. Returns {success, error}."""
    logger.info("Restarting service: %s", unit)
    try:
        # Kill any rogue process holding the port/lock before systemd start
        await _cleanup_rogue_processes(unit)

        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "restart", unit,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode == 0:
            logger.info("Service %s restarted successfully", unit)
            return {"success": True, "error": None}
        else:
            err = stderr.decode().strip()[:200]
            logger.error("Failed to restart %s: %s", unit, err)
            return {"success": False, "error": err}
    except asyncio.TimeoutError:
        logger.error("Timeout restarting %s", unit)
        return {"success": False, "error": "Restart timed out (30s)"}
    except Exception as e:
        logger.error("Error restarting %s: %s", unit, e)
        return {"success": False, "error": str(e)[:200]}


async def wait_for_active(unit: str, timeout: float = 15.0) -> bool:
    """Poll until a service reaches active state, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "systemctl", "is-active", unit,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout.decode().strip() == "active":
                return True
        except Exception:
            pass
        await asyncio.sleep(2.0)
    return False
