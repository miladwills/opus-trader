"""Database repository: all read/write operations for AI Ops."""

from __future__ import annotations
import datetime
import json
import time
import aiosqlite
from . import config
from .models import SystemSnapshot, TriageCase, AuditEntry, AgentState, Proposal, ActionExecution


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

    # --- Agents ---

    async def upsert_agent(self, agent: AgentState):
        existing = await self._db.execute(
            "SELECT agent_id FROM agents WHERE agent_id = ?", (agent.agent_id,)
        )
        row = await existing.fetchone()
        if row:
            await self._db.execute(
                "UPDATE agents SET name=?, role=?, status=?, enabled=?, auto_run=?, "
                "interval_sec=?, last_started_at=?, last_stopped_at=?, last_heartbeat_at=?, "
                "last_run_at=?, last_result_summary=?, current_task=?, error_summary=?, "
                "run_count=?, cooldown_until=?, updated_at=datetime('now') WHERE agent_id=?",
                (agent.name, agent.role, agent.status, int(agent.enabled), int(agent.auto_run),
                 agent.interval_sec, agent.last_started_at, agent.last_stopped_at,
                 agent.last_heartbeat_at, agent.last_run_at, agent.last_result_summary,
                 agent.current_task, agent.error_summary, agent.run_count,
                 agent.cooldown_until, agent.agent_id),
            )
        else:
            await self._db.execute(
                "INSERT INTO agents (agent_id, name, role, status, enabled, auto_run, "
                "interval_sec, last_started_at, last_stopped_at, last_heartbeat_at, "
                "last_run_at, last_result_summary, current_task, error_summary, "
                "run_count, cooldown_until) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent.agent_id, agent.name, agent.role, agent.status,
                 int(agent.enabled), int(agent.auto_run), agent.interval_sec,
                 agent.last_started_at, agent.last_stopped_at, agent.last_heartbeat_at,
                 agent.last_run_at, agent.last_result_summary, agent.current_task,
                 agent.error_summary, agent.run_count, agent.cooldown_until),
            )
        await self._db.commit()

    async def get_all_agents(self) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM agents ORDER BY agent_id"
        )
        return [self._row_to_agent_dict(r) for r in await cursor.fetchall()]

    async def get_agent(self, agent_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_agent_dict(row) if row else None

    async def update_agent_field(self, agent_id: str, **kwargs) -> bool:
        if not kwargs:
            return False
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [agent_id]
        cursor = await self._db.execute(
            f"UPDATE agents SET {sets}, updated_at=datetime('now') WHERE agent_id=?",
            vals,
        )
        await self._db.commit()
        return cursor.rowcount > 0

    def _row_to_agent_dict(self, row) -> dict:
        return {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "role": row["role"],
            "status": row["status"],
            "enabled": bool(row["enabled"]),
            "auto_run": bool(row["auto_run"]),
            "interval_sec": row["interval_sec"],
            "last_started_at": row["last_started_at"],
            "last_stopped_at": row["last_stopped_at"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "last_run_at": row["last_run_at"],
            "last_result_summary": row["last_result_summary"],
            "current_task": row["current_task"],
            "error_summary": row["error_summary"],
            "run_count": row["run_count"],
            "cooldown_until": row["cooldown_until"],
        }

    # --- Agent runs ---

    async def record_agent_run_start(self, agent_id: str) -> int:
        cursor = await self._db.execute(
            "INSERT INTO agent_runs (agent_id, started_at, status) VALUES (?, ?, 'running')",
            (agent_id, time.time()),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def record_agent_run_end(self, run_id: int, status: str, result: str = "", error: str | None = None):
        await self._db.execute(
            "UPDATE agent_runs SET finished_at=?, status=?, result_summary=?, error=? WHERE id=?",
            (time.time(), status, result, error, run_id),
        )
        await self._db.commit()

    async def get_agent_runs(self, agent_id: str, limit: int = 20) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM agent_runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT ?",
            (agent_id, limit),
        )
        return [
            {"id": r["id"], "agent_id": r["agent_id"], "started_at": r["started_at"],
             "finished_at": r["finished_at"], "status": r["status"],
             "result_summary": r["result_summary"], "error": r["error"]}
            for r in await cursor.fetchall()
        ]

    # --- Proposals ---

    async def create_proposal(self, prop: Proposal):
        await self._db.execute(
            "INSERT INTO proposals (proposal_id, title, category, source_agent, severity, "
            "rationale, evidence_refs, affected_components, action_type, action_params, "
            "risk_level, reversibility, status, created_at, gate_verdict, gate_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (prop.proposal_id, prop.title, prop.category, prop.source_agent, prop.severity,
             prop.rationale, json.dumps(prop.evidence_refs), json.dumps(prop.affected_components),
             prop.action_type, json.dumps(prop.action_params), prop.risk_level,
             prop.reversibility, prop.status, prop.created_at,
             prop.gate_verdict, prop.gate_reason),
        )
        await self._db.commit()

    async def get_pending_proposals(self) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM proposals WHERE status = 'pending' ORDER BY created_at DESC"
        )
        return [self._row_to_proposal_dict(r) for r in await cursor.fetchall()]

    async def get_recent_proposals(self, limit: int = 50, status_filter: str | None = None) -> list[dict]:
        if status_filter:
            cursor = await self._db.execute(
                "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status_filter, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_proposal_dict(r) for r in await cursor.fetchall()]

    async def get_proposal(self, proposal_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_proposal_dict(row) if row else None

    async def update_proposal_status(self, proposal_id: str, **kwargs) -> bool:
        if not kwargs:
            return False
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [proposal_id]
        cursor = await self._db.execute(
            f"UPDATE proposals SET {sets}, updated_at=datetime('now') WHERE proposal_id=?",
            vals,
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_next_proposal_seq(self) -> int:
        today = datetime.date.today().strftime("%Y%m%d")
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM proposals WHERE proposal_id LIKE ?",
            (f"PRP-{today}-%",),
        )
        row = await cursor.fetchone()
        return (row["cnt"] if row else 0) + 1

    async def get_proposal_stats(self) -> dict:
        cursor = await self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status"
        )
        return {row["status"]: row["cnt"] for row in await cursor.fetchall()}

    def _row_to_proposal_dict(self, row) -> dict:
        return {
            "proposal_id": row["proposal_id"],
            "title": row["title"],
            "category": row["category"],
            "source_agent": row["source_agent"],
            "severity": row["severity"],
            "rationale": row["rationale"],
            "evidence_refs": json.loads(row["evidence_refs"]) if row["evidence_refs"] else [],
            "affected_components": json.loads(row["affected_components"]) if row["affected_components"] else [],
            "action_type": row["action_type"],
            "action_params": json.loads(row["action_params"]) if row["action_params"] else {},
            "risk_level": row["risk_level"],
            "reversibility": row["reversibility"],
            "status": row["status"],
            "created_at": row["created_at"],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
            "rejected_by": row["rejected_by"],
            "rejected_at": row["rejected_at"],
            "execution_result": row["execution_result"],
            "execution_started_at": row["execution_started_at"],
            "execution_finished_at": row["execution_finished_at"],
            "gate_verdict": row["gate_verdict"],
            "gate_reason": row["gate_reason"],
        }

    # --- Action executions ---

    async def record_execution(self, execution: ActionExecution) -> int:
        cursor = await self._db.execute(
            "INSERT INTO action_executions (proposal_id, action_type, action_params, "
            "started_at, status) VALUES (?, ?, ?, ?, ?)",
            (execution.proposal_id, execution.action_type,
             json.dumps(execution.action_params), execution.started_at, execution.status),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def update_execution(self, exec_id: int, **kwargs):
        if not kwargs:
            return
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [exec_id]
        await self._db.execute(
            f"UPDATE action_executions SET {sets} WHERE id=?", vals,
        )
        await self._db.commit()

    async def get_recent_executions(self, limit: int = 20) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM action_executions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": r["id"], "proposal_id": r["proposal_id"], "action_type": r["action_type"],
             "action_params": json.loads(r["action_params"]) if r["action_params"] else {},
             "started_at": r["started_at"], "finished_at": r["finished_at"],
             "status": r["status"], "result": r["result"], "error": r["error"]}
            for r in await cursor.fetchall()
        ]

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
        await self._db.execute(
            "DELETE FROM agent_runs WHERE started_at < ?",
            (now - config.RETENTION_AGENT_RUNS_DAYS * 86400,),
        )
        await self._db.execute(
            "DELETE FROM proposals WHERE created_at < ? AND status NOT IN ('pending', 'approved')",
            (now - config.RETENTION_PROPOSALS_DAYS * 86400,),
        )
        await self._db.commit()
