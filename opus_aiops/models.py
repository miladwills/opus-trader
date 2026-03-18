"""Data models for AI Ops service."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SystemSnapshot:
    """Point-in-time snapshot assembled from all sources."""
    timestamp: float = 0.0

    # Watchdog data (fast + medium lane)
    health_score: float | None = None
    health_status: str | None = None
    component_scores: dict | None = None
    active_incidents: list | None = None
    probe_results: dict | None = None

    # Trader data (medium lane)
    runner_active: bool | None = None
    runner_pid: int | None = None
    bridge_producer_alive: bool | None = None
    bridge_produced_at: float | None = None
    bridge_stale_sections: list | None = None
    bridge_stale_count: int | None = None
    bot_status_counts: dict | None = None
    bot_total: int | None = None
    flash_crash_active: bool | None = None
    stop_flag_exists: bool | None = None

    # Trader bridge diagnostics (slow lane)
    bridge_diagnostics: dict | None = None

    # File-based data (slow lane)
    bridge_bots_light: list | None = None
    runner_log_lines: list | None = None
    app_log_lines: list | None = None

    # Source availability
    source_errors: dict = field(default_factory=dict)

    # Collection timing (for budget verification)
    collection_timing: dict = field(default_factory=dict)


@dataclass
class TriageCase:
    """A triage case emitted by the rule engine."""
    case_id: str = ""
    rule_id: str = ""
    severity: str = "medium"
    category: str = ""
    title: str = ""
    affected_components: list = field(default_factory=list)
    diagnosis: str = ""
    evidence: list = field(default_factory=list)

    # Grounded match strength
    matched_signals: int = 0
    evidence_count: int = 0
    window_hits: int = 0
    persistence_sec: float = 0.0

    suggested_checks: list = field(default_factory=list)
    suggested_action: str = ""
    status: str = "open"
    hit_count: int = 1
    last_seen_at: float = 0.0
    opened_at: float = 0.0
    resolved_at: float | None = None
    resolution_reason: str | None = None


@dataclass
class AuditEntry:
    """An audit log entry."""
    entry_id: str = ""
    timestamp: float = 0.0
    actor: str = "system"
    action: str = ""
    target_type: str = ""
    target_id: str = ""
    detail: dict = field(default_factory=dict)
