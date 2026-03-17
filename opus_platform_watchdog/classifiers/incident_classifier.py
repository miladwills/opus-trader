"""Incident classifier: matches log lines against patterns, manages lifecycle."""

from __future__ import annotations
import datetime
import logging
import re
import time
from ..models import Incident
from ..storage.repo import Repository
from .patterns import PATTERNS, LogPattern

logger = logging.getLogger("watchdog.classifier")


class IncidentClassifier:
    _SYNTHETIC_CONTEXT_WINDOW = 250
    _SYNTHETIC_BOT_ID_RE = re.compile(r"\[[^:\]]+:(bot-\d+)\]", re.IGNORECASE)
    _EXPLICIT_SYNTHETIC_MARKERS = (
        "[test]",
        "testusdt",
        "simulated_failure",
        "disk full",
        "forensics boom",
        "nlp:testbot123",
    )

    def __init__(self, repo: Repository):
        self._repo = repo
        self._compiled: list[tuple[LogPattern, re.Pattern]] = [
            (p, re.compile(p.regex, re.IGNORECASE)) for p in PATTERNS
        ]
        self._last_fired: dict[str, float] = {}

    async def scan_lines(self, lines: list[str], source: str) -> list[Incident]:
        new_incidents: list[Incident] = []
        now = time.time()
        for line_index, line in enumerate(lines):
            for pattern, compiled in self._compiled:
                match = compiled.search(line)
                if not match:
                    continue
                if self._should_suppress_match(pattern, lines, line_index, source):
                    continue
                last = self._last_fired.get(pattern.key, 0)
                if now - last < pattern.cooldown_sec:
                    await self._repo.bump_incident_count(pattern.key)
                    continue
                self._last_fired[pattern.key] = now
                incident = await self._create_incident(pattern, match, source, now)
                new_incidents.append(incident)
                break  # one pattern match per line is enough
        return new_incidents

    @classmethod
    def _should_suppress_match(
        cls,
        pattern: LogPattern,
        lines: list[str],
        line_index: int,
        source: str,
    ) -> bool:
        if pattern.key != "bot_error_state" or str(source or "").strip().lower() != "runner":
            return False
        line = str(lines[line_index] if 0 <= line_index < len(lines) else "")
        if not cls._SYNTHETIC_BOT_ID_RE.search(line):
            return False
        start = max(0, line_index - cls._SYNTHETIC_CONTEXT_WINDOW)
        end = min(len(lines), line_index + cls._SYNTHETIC_CONTEXT_WINDOW + 1)
        for context_line in lines[start:end]:
            normalized = str(context_line or "").strip().lower()
            if any(marker in normalized for marker in cls._EXPLICIT_SYNTHETIC_MARKERS):
                return True
        return False

    async def auto_resolve_stale(self):
        for pattern, _ in self._compiled:
            last_seen = self._last_fired.get(pattern.key, 0)
            if last_seen > 0 and time.time() - last_seen > pattern.auto_resolve_sec:
                await self._repo.auto_resolve_stale(pattern.key, pattern.auto_resolve_sec)

    async def _create_incident(self, pattern: LogPattern, match: re.Match,
                                source: str, now: float) -> Incident:
        today = datetime.date.today().isoformat().replace("-", "")
        seq = await self._repo.get_next_incident_seq()
        incident_id = f"INC-{today}-{seq:03d}"
        groups = match.groups()
        incident = Incident(
            incident_id=incident_id,
            opened_at=now,
            severity=pattern.severity,
            category=pattern.category,
            component=pattern.component,
            pattern_key=pattern.key,
            summary=pattern.summary_template,
            detail={
                "source": source,
                "match_groups": list(groups) if groups else [],
                "matched_text": match.group(0)[:200],
            },
            status="open",
            hit_count=1,
        )
        await self._repo.create_incident(incident)
        logger.info("New incident %s: %s [%s]", incident_id, pattern.summary_template, pattern.severity)
        return incident
