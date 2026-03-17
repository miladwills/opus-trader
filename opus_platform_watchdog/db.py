"""SQLite database initialization and connection management."""

from __future__ import annotations
import aiosqlite
from . import config

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS probe_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    probe_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    success INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_probe_name_ts ON probe_results(probe_name, timestamp DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL UNIQUE,
    opened_at REAL NOT NULL,
    closed_at REAL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    component TEXT NOT NULL,
    pattern_key TEXT,
    summary TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    hit_count INTEGER NOT NULL DEFAULT 1,
    probe_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_opened ON incidents(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_pattern ON incidents(pattern_key, status);

CREATE TABLE IF NOT EXISTS health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    overall_score REAL NOT NULL,
    overall_status TEXT NOT NULL,
    components TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health_snapshots(timestamp DESC);

CREATE TABLE IF NOT EXISTS latency_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    probe_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    latency_ms REAL NOT NULL,
    endpoint TEXT,
    status_code INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_latency_probe_ts ON latency_samples(probe_name, timestamp DESC);
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
