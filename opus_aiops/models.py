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


# --- V2: Agent model ---

@dataclass
class AgentState:
    """Operational agent state in the AI Ops supervisor."""
    agent_id: str = ""
    name: str = ""
    role: str = ""
    status: str = "stopped"  # running, stopped, paused, error, idle
    enabled: bool = False
    auto_run: bool = False
    interval_sec: int = 300
    last_started_at: float | None = None
    last_stopped_at: float | None = None
    last_heartbeat_at: float | None = None
    last_run_at: float | None = None
    last_result_summary: str = ""
    current_task: str = ""
    error_summary: str = ""
    run_count: int = 0
    cooldown_until: float | None = None


@dataclass
class AgentRun:
    """Record of a single agent execution cycle."""
    id: int = 0
    agent_id: str = ""
    started_at: float = 0.0
    finished_at: float | None = None
    status: str = "running"  # running, completed, error
    result_summary: str = ""
    error: str | None = None


@dataclass
class Proposal:
    """An operational action proposal requiring approval."""
    proposal_id: str = ""
    title: str = ""
    category: str = ""
    source_agent: str = ""
    severity: str = "medium"
    rationale: str = ""
    evidence_refs: list = field(default_factory=list)
    affected_components: list = field(default_factory=list)
    action_type: str = ""
    action_params: dict = field(default_factory=dict)
    risk_level: str = "low"
    reversibility: str = "reversible"
    status: str = "pending"  # pending, approved, rejected, executed, failed, expired
    created_at: float = 0.0
    approved_by: str | None = None
    approved_at: float | None = None
    rejected_by: str | None = None
    rejected_at: float | None = None
    execution_result: str | None = None
    execution_started_at: float | None = None
    execution_finished_at: float | None = None
    gate_verdict: str | None = None
    gate_reason: str | None = None


@dataclass
class AgentActivity:
    """A single activity entry in the per-agent feed."""
    id: int = 0
    agent_id: str = ""
    timestamp: float = 0.0
    event_type: str = ""  # started, stopped, paused, resumed, run_started, run_completed, run_error, run_once, restarted
    summary: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class ActionExecution:
    """Record of an executed allowlisted action."""
    id: int = 0
    proposal_id: str = ""
    action_type: str = ""
    action_params: dict = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float | None = None
    status: str = "running"  # running, completed, failed
    result: str = ""
    error: str | None = None
