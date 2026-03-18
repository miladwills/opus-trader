"""Rule-based triage engine with correlator and 5 detection rules.

No LLM. All output is grounded in matched signals, evidence counts,
window hits, recency, and persistence.
"""

from __future__ import annotations
import datetime
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from . import config
from .models import SystemSnapshot, TriageCase

logger = logging.getLogger("aiops.triage")


# ---------------------------------------------------------------------------
# Correlator — rolling window of recent snapshots
# ---------------------------------------------------------------------------

class Correlator:
    """Maintains a rolling window of snapshots for multi-cycle detection."""

    def __init__(self, window_size: int = 10):
        self._snapshots: deque[SystemSnapshot] = deque(maxlen=window_size)

    def add(self, snapshot: SystemSnapshot):
        self._snapshots.append(snapshot)

    @property
    def window(self) -> list[SystemSnapshot]:
        return list(self._snapshots)

    @property
    def window_size(self) -> int:
        return len(self._snapshots)

    def count_matches(self, check_fn: Callable[[SystemSnapshot], bool]) -> int:
        """Count how many snapshots in the window match a condition."""
        return sum(1 for s in self._snapshots if check_fn(s))

    def earliest_match(self, check_fn: Callable[[SystemSnapshot], bool]) -> float | None:
        """Return timestamp of earliest matching snapshot in window."""
        for s in self._snapshots:
            if check_fn(s):
                return s.timestamp
        return None


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

@dataclass
class RuleMatch:
    """Output from a single rule evaluation."""
    rule_id: str
    severity: str
    category: str
    title: str
    affected_components: list[str]
    diagnosis: str
    evidence: list[dict]
    matched_signals: int
    total_signals: int
    suggested_checks: list[str]
    suggested_action: str = ""


def _log_contains(lines: list[str] | None, *patterns: str) -> list[dict]:
    """Search log lines for patterns. Return evidence items with line excerpts."""
    if not lines:
        return []
    evidence = []
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            if compiled.search(line):
                evidence.append({
                    "source": "log",
                    "pattern": pattern,
                    "excerpt": line.strip()[:200],
                    "timestamp": time.time(),
                })
                break  # one match per pattern is enough
    return evidence


# --- Rule 1: Storage / read-path contention ---

def rule_storage_contention(snap: SystemSnapshot, correlator: Correlator) -> RuleMatch | None:
    signals = 0
    total = 3
    evidence = []

    # Signal 1: bridge sections stale
    if snap.bridge_stale_count and snap.bridge_stale_count >= 2:
        signals += 1
        evidence.append({
            "source": "trader_health_summary",
            "detail": f"{snap.bridge_stale_count} bridge sections stale: {snap.bridge_stale_sections}",
            "timestamp": snap.timestamp,
        })

    # Signal 2: bridge diagnostics show slow assembly
    if snap.bridge_diagnostics:
        req_diag = (snap.bridge_diagnostics.get("request_diagnostics") or {}).get("bridge_diagnostics") or {}
        phase_ms = req_diag.get("phase_ms") or {}
        assembly_ms = phase_ms.get("sections_assembly_ms", 0)
        if assembly_ms > 100:
            signals += 1
            evidence.append({
                "source": "bridge_diagnostics",
                "detail": f"Bridge sections assembly took {assembly_ms}ms (>100ms threshold)",
                "timestamp": snap.timestamp,
            })

    # Signal 3: log evidence of lock contention
    lock_evidence = _log_contains(
        snap.runner_log_lines,
        r"lock.*contention|file_lock.*wait|storage.*lock|lock.*timeout",
    )
    if lock_evidence:
        signals += 1
        evidence.extend(lock_evidence)

    if signals < 2:
        return None

    # Require persistence across 2+ cycles
    window_hits = correlator.count_matches(
        lambda s: (s.bridge_stale_count or 0) >= 2
    )
    if window_hits < 2:
        return None

    return RuleMatch(
        rule_id="storage_contention",
        severity="high" if signals >= 3 else "medium",
        category="contention",
        title="Storage/read-path contention detected",
        affected_components=["bridge", "runner", "storage"],
        diagnosis=(
            f"Bridge sections stale ({snap.bridge_stale_count}/5), "
            f"assembly slow, lock contention in logs. "
            f"Persisted across {window_hits} collection cycles."
        ),
        evidence=evidence,
        matched_signals=signals,
        total_signals=total,
        suggested_checks=[
            "Check runner.log for file_lock wait times",
            "Check bridge section ages in /api/bridge/diagnostics",
            "Check disk I/O with iostat",
            "Check if multiple processes contend on storage/",
        ],
        suggested_action="Investigate storage I/O and lock contention in runner process",
    )


# --- Rule 2: Exchange outcome ambiguity ---

def rule_exchange_ambiguity(snap: SystemSnapshot, correlator: Correlator) -> RuleMatch | None:
    patterns = [
        r"ws_timeout_after_send",
        r"CLOSE_FAILED",
        r"ambiguous_execution_follow_up|ambiguous.*pending.*resolution",
        r"order.*timeout.*uncertain|uncertain.*execution",
    ]
    evidence = _log_contains(snap.runner_log_lines, *patterns)
    if not evidence:
        return None

    signals = len(evidence)

    return RuleMatch(
        rule_id="exchange_ambiguity",
        severity="critical" if signals >= 2 else "high",
        category="exchange",
        title="Exchange outcome ambiguity detected",
        affected_components=["order_router", "bybit_client", "runner"],
        diagnosis=(
            f"Found {signals} exchange ambiguity signal(s) in runner logs: "
            f"{', '.join(e['pattern'] for e in evidence)}. "
            f"Order execution results may be uncertain."
        ),
        evidence=evidence,
        matched_signals=signals,
        total_signals=len(patterns),
        suggested_checks=[
            "Check runner.log for full ambiguous execution context",
            "Check /api/bridge/diagnostics for order section freshness",
            "Verify open orders match expected state on exchange",
            "Check reconciliation status in watchdog",
        ],
        suggested_action="Review ambiguous order outcomes in runner logs and verify exchange state",
    )


# --- Rule 3: Preview gating regression ---

def rule_preview_gating_regression(snap: SystemSnapshot, correlator: Correlator) -> RuleMatch | None:
    bots = snap.bridge_bots_light
    if not bots or not isinstance(bots, list):
        return None

    running_bots = [b for b in bots if b.get("lifecycle_status") == "running"]
    stopped_bots = [b for b in bots if b.get("lifecycle_status") in ("stopped", "stop_cleanup_pending")]

    if not running_bots or not stopped_bots:
        return None

    evidence = []
    for sb in stopped_bots:
        preview = sb.get("preview_mode") or sb.get("entry_preview_mode")
        if preview in ("disabled", "off", False):
            # Check that the running bot is on a different symbol
            sb_symbol = sb.get("symbol", "")
            for rb in running_bots:
                if rb.get("symbol", "") != sb_symbol:
                    evidence.append({
                        "source": "bridge_bots_light",
                        "detail": (
                            f"Stopped bot {sb.get('bot_id', '?')[:8]} ({sb_symbol}) "
                            f"has preview={preview} while bot {rb.get('bot_id', '?')[:8]} "
                            f"({rb.get('symbol', '?')}) is running"
                        ),
                        "timestamp": snap.timestamp,
                    })
                    break

    if not evidence:
        return None

    return RuleMatch(
        rule_id="preview_gating_regression",
        severity="medium",
        category="regression",
        title="Preview gating regression: stopped bot preview disabled",
        affected_components=["bot_status_service", "entry_readiness"],
        diagnosis=(
            f"{len(evidence)} stopped bot(s) have preview disabled "
            f"while unrelated bot(s) are running. "
            f"Stopped bots should retain preview capability."
        ),
        evidence=evidence,
        matched_signals=len(evidence),
        total_signals=len(stopped_bots),
        suggested_checks=[
            "Check bot status service preview gating logic",
            "Verify stopped bots retain preview in bot_status_service.py",
            "Check entry_readiness_service preview mode for stopped bots",
        ],
        suggested_action="Investigate preview gating logic for stopped bots",
    )


# --- Rule 4: WebSocket / transport instability ---

def rule_websocket_instability(snap: SystemSnapshot, correlator: Correlator) -> RuleMatch | None:
    signals = 0
    total = 3
    evidence = []

    # Signal 1: watchdog incidents with stream category
    if snap.active_incidents:
        stream_incidents = [
            i for i in snap.active_incidents
            if isinstance(i, dict) and i.get("category") == "stream"
            and i.get("status") in ("open", "acknowledged")
        ]
        if stream_incidents:
            signals += 1
            for si in stream_incidents[:3]:
                evidence.append({
                    "source": "watchdog_incidents",
                    "detail": f"Stream incident: {si.get('summary', 'unknown')} (severity={si.get('severity')})",
                    "timestamp": si.get("opened_at", snap.timestamp),
                })

    # Signal 2: log evidence of disconnection
    disconnect_evidence = _log_contains(
        snap.runner_log_lines,
        r"stream.*disconnect|websocket.*closed|ws.*disconnect",
    )
    if disconnect_evidence:
        signals += 1
        evidence.extend(disconnect_evidence)

    # Signal 3: fallback polling active
    fallback_evidence = _log_contains(
        snap.runner_log_lines,
        r"fallback.*poll|polling.*fallback|rest.*fallback",
    )
    if not fallback_evidence:
        fallback_evidence = _log_contains(
            snap.app_log_lines,
            r"fallback.*poll|polling.*fallback",
        )
    if fallback_evidence:
        signals += 1
        evidence.extend(fallback_evidence)

    if signals < 2:
        return None

    return RuleMatch(
        rule_id="websocket_instability",
        severity="high" if signals >= 3 else "medium",
        category="stream",
        title="WebSocket transport instability",
        affected_components=["bybit_stream", "runner", "bridge"],
        diagnosis=(
            f"{signals}/{total} instability signals matched. "
            f"Live stream may be degraded with fallback to REST polling."
        ),
        evidence=evidence,
        matched_signals=signals,
        total_signals=total,
        suggested_checks=[
            "Check runner.log for stream reconnection patterns",
            "Check watchdog stream probe history",
            "Verify Bybit API status page for platform issues",
            "Check if bridge data is still updating via REST fallback",
        ],
        suggested_action="Monitor stream reconnection; verify data freshness via REST fallback",
    )


# --- Rule 5: Control-state version ordering race ---

def rule_control_state_race(snap: SystemSnapshot, correlator: Correlator) -> RuleMatch | None:
    patterns = [
        r"stale.*control.state.*save.*ignored",
        r"control_version.*ordering.*conflict|control_version.*rejected.*stale",
        r"newer.*lifecycle.*state.*exists|lifecycle.*version.*conflict",
    ]
    evidence = _log_contains(snap.runner_log_lines, *patterns)
    if not evidence:
        return None

    return RuleMatch(
        rule_id="control_state_race",
        severity="high",
        category="state",
        title="Control-state version ordering race",
        affected_components=["bot_storage", "runner", "state_management"],
        diagnosis=(
            f"Detected {len(evidence)} control-state ordering anomaly signal(s) in runner logs. "
            f"Newer lifecycle state may be overwritten by a stale save."
        ),
        evidence=evidence,
        matched_signals=len(evidence),
        total_signals=len(patterns),
        suggested_checks=[
            "Check runner.log for control_version conflicts",
            "Check bots.json for stale lifecycle states",
            "Verify bot_storage_service version guard logic",
        ],
        suggested_action="Investigate control-state save ordering in runner + bot_storage",
    )


# ---------------------------------------------------------------------------
# Triage engine
# ---------------------------------------------------------------------------

ALL_RULES: list[Callable[[SystemSnapshot, Correlator], RuleMatch | None]] = [
    rule_storage_contention,
    rule_exchange_ambiguity,
    rule_preview_gating_regression,
    rule_websocket_instability,
    rule_control_state_race,
]


class TriageEngine:
    """Runs rules against snapshots, manages case lifecycle."""

    def __init__(self):
        self.correlator = Correlator(window_size=config.CORRELATOR_WINDOW_SIZE)
        self._open_cases: dict[str, TriageCase] = {}  # rule_id -> case
        self._case_seq: int = 0

    def _next_case_id(self) -> str:
        self._case_seq += 1
        date_str = datetime.date.today().strftime("%Y%m%d")
        return f"TRG-{date_str}-{self._case_seq:03d}"

    def evaluate(self, snapshot: SystemSnapshot) -> list[TriageCase]:
        """Run all rules against a snapshot. Returns new or updated cases."""
        self.correlator.add(snapshot)
        now = snapshot.timestamp or time.time()
        results: list[TriageCase] = []

        for rule_fn in ALL_RULES:
            try:
                match = rule_fn(snapshot, self.correlator)
            except Exception as exc:
                logger.warning("Rule %s raised: %s", rule_fn.__name__, exc)
                continue

            rule_id = rule_fn.__name__.replace("rule_", "")

            if match:
                existing = self._open_cases.get(rule_id)
                if existing and existing.status in ("open", "acknowledged"):
                    # Update existing case
                    existing.hit_count += 1
                    existing.last_seen_at = now
                    existing.matched_signals = match.matched_signals
                    existing.evidence_count = len(match.evidence)
                    existing.window_hits = self.correlator.count_matches(
                        lambda s: s.bridge_stale_count and s.bridge_stale_count >= 2
                    ) if rule_id == "storage_contention" else existing.window_hits + 1
                    earliest = self.correlator.earliest_match(lambda s: True)
                    if earliest:
                        existing.persistence_sec = round(now - earliest, 1)
                    existing.evidence = match.evidence
                    existing.severity = match.severity
                    results.append(existing)
                else:
                    # New case
                    case = TriageCase(
                        case_id=self._next_case_id(),
                        rule_id=rule_id,
                        severity=match.severity,
                        category=match.category,
                        title=match.title,
                        affected_components=match.affected_components,
                        diagnosis=match.diagnosis,
                        evidence=match.evidence,
                        matched_signals=match.matched_signals,
                        evidence_count=len(match.evidence),
                        window_hits=1,
                        persistence_sec=0.0,
                        suggested_checks=match.suggested_checks,
                        suggested_action=match.suggested_action,
                        status="open",
                        hit_count=1,
                        last_seen_at=now,
                        opened_at=now,
                    )
                    self._open_cases[rule_id] = case
                    results.append(case)
            else:
                # Rule did not fire — check if we should auto-resolve
                existing = self._open_cases.get(rule_id)
                if existing and existing.status in ("open", "acknowledged"):
                    absent_sec = now - existing.last_seen_at
                    if absent_sec >= config.TRIAGE_AUTO_RESOLVE_SEC:
                        existing.status = "auto_resolved"
                        existing.resolved_at = now
                        existing.resolution_reason = (
                            f"Signals absent for {int(absent_sec)}s "
                            f"(threshold: {int(config.TRIAGE_AUTO_RESOLVE_SEC)}s)"
                        )
                        results.append(existing)
                        del self._open_cases[rule_id]

        return results

    @property
    def open_cases(self) -> list[TriageCase]:
        return [c for c in self._open_cases.values() if c.status in ("open", "acknowledged")]
