"""SQLite database initialization and connection management."""

from __future__ import annotations
import aiosqlite
from . import config

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    health_score REAL,
    health_status TEXT,
    source_errors TEXT NOT NULL DEFAULT '{}',
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp DESC);

CREATE TABLE IF NOT EXISTS triage_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL UNIQUE,
    rule_id TEXT NOT NULL,
    opened_at REAL NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    affected_components TEXT NOT NULL DEFAULT '[]',
    diagnosis TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]',
    matched_signals INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    window_hits INTEGER NOT NULL DEFAULT 0,
    persistence_sec REAL NOT NULL DEFAULT 0,
    suggested_checks TEXT NOT NULL DEFAULT '[]',
    suggested_action TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    resolved_at REAL,
    resolution_reason TEXT,
    hit_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_triage_status ON triage_cases(status);
CREATE INDEX IF NOT EXISTS idx_triage_opened ON triage_cases(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_triage_rule ON triage_cases(rule_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT NOT NULL UNIQUE,
    timestamp REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_type, target_id);

-- V2: Agent registry
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stopped',
    enabled INTEGER NOT NULL DEFAULT 0,
    auto_run INTEGER NOT NULL DEFAULT 0,
    interval_sec INTEGER NOT NULL DEFAULT 300,
    last_started_at REAL,
    last_stopped_at REAL,
    last_heartbeat_at REAL,
    last_run_at REAL,
    last_result_summary TEXT NOT NULL DEFAULT '',
    current_task TEXT NOT NULL DEFAULT '',
    error_summary TEXT NOT NULL DEFAULT '',
    run_count INTEGER NOT NULL DEFAULT 0,
    cooldown_until REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- V2: Agent run history
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL DEFAULT 'running',
    result_summary TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_id, started_at DESC);

-- V2: Proposals
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    rationale TEXT NOT NULL,
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    affected_components TEXT NOT NULL DEFAULT '[]',
    action_type TEXT NOT NULL,
    action_params TEXT NOT NULL DEFAULT '{}',
    risk_level TEXT NOT NULL DEFAULT 'low',
    reversibility TEXT NOT NULL DEFAULT 'reversible',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    approved_by TEXT,
    approved_at REAL,
    rejected_by TEXT,
    rejected_at REAL,
    execution_result TEXT,
    execution_started_at REAL,
    execution_finished_at REAL,
    gate_verdict TEXT,
    gate_reason TEXT,
    created_at_str TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_created ON proposals(created_at DESC);

-- V2: Action executions
CREATE TABLE IF NOT EXISTS action_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    action_params TEXT NOT NULL DEFAULT '{}',
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL DEFAULT 'running',
    result TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_executions_proposal ON action_executions(proposal_id);

-- V2.1: Agent activity feed
CREATE TABLE IF NOT EXISTS agent_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_activity_agent ON agent_activity(agent_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON agent_activity(timestamp DESC);
"""


async def init_db() -> aiosqlite.Connection:
    global _db
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.commit()
    return _db


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None
