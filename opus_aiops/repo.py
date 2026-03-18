"""Database repository: all read/write operations for AI Ops."""

from __future__ import annotations
import datetime
import json
import time
import aiosqlite
from . import config
from .models import SystemSnapshot, TriageCase, AuditEntry


class Repository:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    # --- Snapshots ---

    async def store_snapshot(self, snap: SystemSnapshot):
        data_blob = json.dumps({
            "health_score": snap.health_score,
            "health_status": snap.health_status,
            "runner_active": snap.runner_active,
            "bridge_stale_count": snap.bridge_stale_count,
            "bot_total": snap.bot_total,
            "bot_status_counts": snap.bot_status_counts,
            "flash_crash_active": snap.flash_crash_active,
            "collection_timing": snap.collection_timing,
        })
        await self._db.execute(
            "INSERT INTO snapshots (timestamp, health_score, health_status, source_errors, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (snap.timestamp, snap.health_score, snap.health_status,
             json.dumps(snap.source_errors), data_blob),
        )
        await self._db.commit()

    async def get_latest_snapshot(self) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "timestamp": row["timestamp"],
            "health_score": row["health_score"],
            "health_status": row["health_status"],
            "source_errors": json.loads(row["source_errors"]) if row["source_errors"] else {},
            "data": json.loads(row["data"]) if row["data"] else {},
        }

    async def get_snapshot_history(self, hours: float = 2.0) -> list[dict]:
        cutoff = time.time() - hours * 3600
        cursor = await self._db.execute(
            "SELECT timestamp, health_score, health_status FROM snapshots "
            "WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        return [
            {"timestamp": r["timestamp"], "health_score": r["health_score"],
             "health_status": r["health_status"]}
            for r in await cursor.fetchall()
        ]

    # --- Triage cases ---

    async def upsert_triage_case(self, case: TriageCase):
        """Insert or update a triage case by case_id."""
        existing = await self._db.execute(
            "SELECT id FROM triage_cases WHERE case_id = ?", (case.case_id,)
        )
        row = await existing.fetchone()
        if row:
            await self._db.execute(
                "UPDATE triage_cases SET severity=?, title=?, diagnosis=?, evidence=?, "
                "matched_signals=?, evidence_count=?, window_hits=?, persistence_sec=?, "
                "suggested_checks=?, suggested_action=?, status=?, hit_count=?, "
                "last_seen_at=?, resolved_at=?, resolution_reason=?, "
                "updated_at=datetime('now') WHERE case_id=?",
                (case.severity, case.title, case.diagnosis,
                 json.dumps(case.evidence), case.matched_signals, case.evidence_count,
                 case.window_hits, case.persistence_sec,
                 json.dumps(case.suggested_checks), case.suggested_action,
                 case.status, case.hit_count, case.last_seen_at,
                 case.resolved_at, case.resolution_reason, case.case_id),
            )
        else:
            await self._db.execute(
                "INSERT INTO triage_cases "
                "(case_id, rule_id, opened_at, severity, category, title, "
                "affected_components, diagnosis, evidence, matched_signals, "
                "evidence_count, window_hits, persistence_sec, suggested_checks, "
                "suggested_action, status, hit_count, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (case.case_id, case.rule_id, case.opened_at, case.severity,
                 case.category, case.title, json.dumps(case.affected_components),
                 case.diagnosis, json.dumps(case.evidence), case.matched_signals,
                 case.evidence_count, case.window_hits, case.persistence_sec,
                 json.dumps(case.suggested_checks), case.suggested_action,
                 case.status, case.hit_count, case.last_seen_at),
            )
        await self._db.commit()

    async def get_active_cases(self) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM triage_cases WHERE status IN ('open', 'acknowledged') "
            "ORDER BY opened_at DESC"
        )
        return [self._row_to_case_dict(r) for r in await cursor.fetchall()]

    async def get_recent_cases(self, limit: int = 50, status_filter: str | None = None) -> list[dict]:
        if status_filter:
            cursor = await self._db.execute(
                "SELECT * FROM triage_cases WHERE status = ? ORDER BY opened_at DESC LIMIT ?",
                (status_filter, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM triage_cases ORDER BY opened_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_case_dict(r) for r in await cursor.fetchall()]

    async def get_case_by_id(self, case_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM triage_cases WHERE case_id = ?", (case_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_case_dict(row) if row else None

    async def update_case_status(self, case_id: str, status: str, reason: str | None = None) -> bool:
        now = time.time()
        resolved_at = now if status in ("resolved", "auto_resolved", "false_positive") else None
        cursor = await self._db.execute(
            "UPDATE triage_cases SET status=?, resolved_at=?, resolution_reason=?, "
            "updated_at=datetime('now') WHERE case_id=?",
            (status, resolved_at, reason, case_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_triage_stats(self) -> dict:
        cursor = await self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM triage_cases GROUP BY status"
        )
        return {row["status"]: row["cnt"] for row in await cursor.fetchall()}

    def _row_to_case_dict(self, row) -> dict:
        return {
            "case_id": row["case_id"],
            "rule_id": row["rule_id"],
            "opened_at": row["opened_at"],
            "severity": row["severity"],
            "category": row["category"],
            "title": row["title"],
            "affected_components": json.loads(row["affected_components"]) if row["affected_components"] else [],
            "diagnosis": row["diagnosis"],
            "evidence": json.loads(row["evidence"]) if row["evidence"] else [],
            "matched_signals": row["matched_signals"],
            "evidence_count": row["evidence_count"],
            "window_hits": row["window_hits"],
            "persistence_sec": row["persistence_sec"],
            "suggested_checks": json.loads(row["suggested_checks"]) if row["suggested_checks"] else [],
            "suggested_action": row["suggested_action"],
            "status": row["status"],
            "hit_count": row["hit_count"],
            "last_seen_at": row["last_seen_at"],
            "resolved_at": row["resolved_at"],
            "resolution_reason": row["resolution_reason"],
        }

    # --- Audit log ---

    async def create_audit_entry(self, entry: AuditEntry):
        await self._db.execute(
            "INSERT INTO audit_log (entry_id, timestamp, actor, action, target_type, target_id, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry.entry_id, entry.timestamp, entry.actor, entry.action,
             entry.target_type, entry.target_id, json.dumps(entry.detail)),
        )
        await self._db.commit()

    async def get_audit_log(self, limit: int = 100, action_filter: str | None = None) -> list[dict]:
        if action_filter:
            cursor = await self._db.execute(
                "SELECT * FROM audit_log WHERE action = ? ORDER BY timestamp DESC LIMIT ?",
                (action_filter, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [
            {
                "entry_id": r["entry_id"],
                "timestamp": r["timestamp"],
                "actor": r["actor"],
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "detail": json.loads(r["detail"]) if r["detail"] else {},
            }
            for r in await cursor.fetchall()
        ]

    async def get_next_audit_seq(self) -> int:
        today = datetime.date.today().strftime("%Y%m%d")
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM audit_log WHERE entry_id LIKE ?",
            (f"AUD-{today}-%",),
        )
        row = await cursor.fetchone()
        return (row["cnt"] if row else 0) + 1

    # --- Retention purge ---

    async def purge_old_data(self):
        now = time.time()
        await self._db.execute(
            "DELETE FROM snapshots WHERE timestamp < ?",
            (now - config.RETENTION_SNAPSHOTS_DAYS * 86400,),
        )
        await self._db.execute(
            "DELETE FROM triage_cases WHERE opened_at < ? AND status NOT IN ('open', 'acknowledged')",
            (now - config.RETENTION_TRIAGE_DAYS * 86400,),
        )
        await self._db.execute(
            "DELETE FROM audit_log WHERE timestamp < ?",
            (now - config.RETENTION_AUDIT_DAYS * 86400,),
        )
        await self._db.commit()
