"""Log scanning probes: tail log files and feed the incident classifier."""

from __future__ import annotations
import asyncio
import time
from pathlib import Path
from .base import BaseProbe
from ..models import ProbeResult
from .. import config


class LogScanProbe(BaseProbe):
    timeout_sec = 2.0

    def __init__(self, log_path: str, probe_name: str, source: str):
        self.log_path = log_path
        self.name = probe_name
        self.source = source
        self.cadence_sec = 10.0 if "runner" in probe_name else 15.0
        self._last_offset: int = 0
        self._last_inode: int = 0
        self._classifier = None  # set after construction by scheduler

    def set_classifier(self, classifier):
        self._classifier = classifier

    async def execute(self) -> ProbeResult:
        t0 = time.monotonic()
        try:
            lines = await asyncio.to_thread(self._tail_new_lines)
            latency = (time.monotonic() - t0) * 1000
            new_incidents = []
            if lines and self._classifier:
                new_incidents = await self._classifier.scan_lines(lines, self.source)
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=True, latency_ms=latency, status="ok",
                detail={
                    "lines_scanned": len(lines),
                    "new_incidents": len(new_incidents),
                    "offset": self._last_offset,
                },
            )
        except Exception as e:
            return ProbeResult(
                probe_name=self.name, timestamp=time.time(),
                success=False, latency_ms=(time.monotonic() - t0) * 1000,
                status="error", detail={}, error=str(e)[:200],
            )

    def _tail_new_lines(self) -> list[str]:
        path = Path(self.log_path)
        if not path.exists():
            self._last_offset = 0
            return []
        stat = path.stat()
        current_inode = stat.st_ino
        current_size = stat.st_size
        # Detect rotation: inode changed or file shrank
        if current_inode != self._last_inode or current_size < self._last_offset:
            self._last_offset = 0
            self._last_inode = current_inode
        if current_size == self._last_offset:
            return []
        # First read after start/rotation: skip to end instead of replaying
        # old log lines, which would create ghost incidents from stale events.
        if self._last_offset == 0:
            self._last_offset = current_size
            self._last_inode = current_inode
            return []
        read_start = self._last_offset
        try:
            with open(self.log_path, "r", errors="replace") as f:
                f.seek(read_start)
                raw = f.read(config.LOG_SCAN_BYTES)
                self._last_offset = f.tell()
        except OSError:
            return []
        lines = raw.splitlines()
        # If we seeked to a non-zero offset on first read, skip the partial first line
        if read_start > 0 and lines:
            lines = lines[1:]
        return lines
