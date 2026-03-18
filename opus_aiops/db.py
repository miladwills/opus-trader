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
