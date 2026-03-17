"""Database repository: all read/write operations."""

from __future__ import annotations
import json
import time
import aiosqlite
from ..models import ProbeResult, Incident, HealthSnapshot, LatencySample
from .. import config


class Repository:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    # --- Probe results ---

    async def store_probe_result(self, r: ProbeResult):
        await self._db.execute(
            "INSERT INTO probe_results (probe_name, timestamp, success, latency_ms, status, detail, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r.probe_name, r.timestamp, int(r.success), r.latency_ms, r.status, json.dumps(r.detail), r.error),
        )
        await self._db.commit()

    async def get_latest_probe(self, name: str) -> ProbeResult | None:
        cursor = await self._db.execute(
            "SELECT * FROM probe_results WHERE probe_name = ? ORDER BY timestamp DESC LIMIT 1",
            (name,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_probe_result(row)

    async def get_recent_probes(self, name: str, limit: int = 50) -> list[ProbeResult]:
        cursor = await self._db.execute(
            "SELECT * FROM probe_results WHERE probe_name = ? ORDER BY timestamp DESC LIMIT ?",
            (name, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_probe_result(r) for r in rows]

    async def get_all_latest_probes(self) -> dict[str, ProbeResult]:
        cursor = await self._db.execute(
            "SELECT p.* FROM probe_results p "
            "INNER JOIN (SELECT probe_name, MAX(timestamp) as max_ts FROM probe_results GROUP BY probe_name) latest "
            "ON p.probe_name = latest.probe_name AND p.timestamp = latest.max_ts"
        )
        rows = await cursor.fetchall()
        return {r["probe_name"]: self._row_to_probe_result(r) for r in rows}

    def _row_to_probe_result(self, row) -> ProbeResult:
        return ProbeResult(
            probe_name=row["probe_name"],
            timestamp=row["timestamp"],
            success=bool(row["success"]),
            latency_ms=row["latency_ms"],
            status=row["status"],
            detail=json.loads(row["detail"]) if row["detail"] else {},
            error=row["error"],
        )

    # --- Incidents ---

    async def create_incident(self, incident: Incident):
        await self._db.execute(
            "INSERT INTO incidents (incident_id, opened_at, severity, category, component, pattern_key, "
            "summary, detail, status, hit_count, probe_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (incident.incident_id, incident.opened_at, incident.severity, incident.category,
             incident.component, incident.pattern_key, incident.summary,
             json.dumps(incident.detail), incident.status, incident.hit_count, incident.probe_name),
        )
        await self._db.commit()

    async def bump_incident_count(self, pattern_key: str) -> bool:
        cursor = await self._db.execute(
            "SELECT id FROM incidents WHERE pattern_key = ? AND status IN ('open', 'acknowledged') "
            "ORDER BY opened_at DESC LIMIT 1",
            (pattern_key,),
        )
        row = await cursor.fetchone()
        if not row:
            return False
        await self._db.execute(
            "UPDATE incidents SET hit_count = hit_count + 1, updated_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
        await self._db.commit()
        return True

    async def get_open_incidents(self, limit: int = 50) -> list[Incident]:
        cursor = await self._db.execute(
            "SELECT * FROM incidents WHERE status IN ('open', 'acknowledged') ORDER BY opened_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_incident(r) for r in await cursor.fetchall()]

    async def get_recent_incidents(self, limit: int = 50, status_filter: str | None = None) -> list[Incident]:
        if status_filter:
            cursor = await self._db.execute(
                "SELECT * FROM incidents WHERE status = ? ORDER BY opened_at DESC LIMIT ?",
                (status_filter, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM incidents ORDER BY opened_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_incident(r) for r in await cursor.fetchall()]

    async def acknowledge_incident(self, incident_id: str) -> bool:
        cursor = await self._db.execute(
            "UPDATE incidents SET status = 'acknowledged', updated_at = datetime('now') WHERE incident_id = ? AND status = 'open'",
            (incident_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def auto_resolve_stale(self, pattern_key: str, auto_resolve_sec: float):
        cutoff = time.time() - auto_resolve_sec
        await self._db.execute(
            "UPDATE incidents SET status = 'auto_resolved', closed_at = ?, updated_at = datetime('now') "
            "WHERE pattern_key = ? AND status IN ('open', 'acknowledged') AND opened_at < ?",
            (time.time(), pattern_key, cutoff),
        )
        await self._db.commit()

    async def count_open_incidents_by_severity(self) -> dict[str, int]:
        cursor = await self._db.execute(
            "SELECT severity, COUNT(*) as cnt FROM incidents WHERE status IN ('open', 'acknowledged') GROUP BY severity"
        )
        return {row["severity"]: row["cnt"] for row in await cursor.fetchall()}

    async def get_next_incident_seq(self) -> int:
        import datetime
        today = datetime.date.today().isoformat().replace("-", "")
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE incident_id LIKE ?",
            (f"INC-{today}-%",),
        )
        row = await cursor.fetchone()
        return (row["cnt"] if row else 0) + 1

    def _row_to_incident(self, row) -> Incident:
        return Incident(
            incident_id=row["incident_id"],
            opened_at=row["opened_at"],
            severity=row["severity"],
            category=row["category"],
            component=row["component"],
            pattern_key=row["pattern_key"],
            summary=row["summary"],
            detail=json.loads(row["detail"]) if row["detail"] else {},
            status=row["status"],
            closed_at=row["closed_at"],
            hit_count=row["hit_count"],
            probe_name=row["probe_name"],
        )

    # --- Health snapshots ---

    async def store_health_snapshot(self, snap: HealthSnapshot):
        await self._db.execute(
            "INSERT INTO health_snapshots (timestamp, overall_score, overall_status, components) VALUES (?, ?, ?, ?)",
            (snap.timestamp, snap.overall_score, snap.overall_status, json.dumps(snap.components)),
        )
        await self._db.commit()

    async def get_latest_health(self) -> HealthSnapshot | None:
        cursor = await self._db.execute(
            "SELECT * FROM health_snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return HealthSnapshot(
            timestamp=row["timestamp"],
            overall_score=row["overall_score"],
            overall_status=row["overall_status"],
            components=json.loads(row["components"]) if row["components"] else {},
        )

    async def get_health_history(self, hours: float = 2.0) -> list[HealthSnapshot]:
        cutoff = time.time() - hours * 3600
        cursor = await self._db.execute(
            "SELECT * FROM health_snapshots WHERE timestamp > ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        return [
            HealthSnapshot(
                timestamp=r["timestamp"],
                overall_score=r["overall_score"],
                overall_status=r["overall_status"],
                components=json.loads(r["components"]) if r["components"] else {},
            )
            for r in await cursor.fetchall()
        ]

    # --- Latency samples ---

    async def store_latency_sample(self, probe_name: str, timestamp: float, latency_ms: float,
                                    endpoint: str | None = None, status_code: int | None = None):
        await self._db.execute(
            "INSERT INTO latency_samples (probe_name, timestamp, latency_ms, endpoint, status_code) VALUES (?, ?, ?, ?, ?)",
            (probe_name, timestamp, latency_ms, endpoint, status_code),
        )
        await self._db.commit()

    async def get_recent_latencies(self, probe_name: str, window_sec: float = 300) -> list[float]:
        cutoff = time.time() - window_sec
        cursor = await self._db.execute(
            "SELECT latency_ms FROM latency_samples WHERE probe_name = ? AND timestamp > ? ORDER BY timestamp ASC",
            (probe_name, cutoff),
        )
        return [row["latency_ms"] for row in await cursor.fetchall()]

    async def get_latency_history(self, probe_name: str, minutes: int = 30) -> list[dict]:
        cutoff = time.time() - minutes * 60
        cursor = await self._db.execute(
            "SELECT timestamp, latency_ms, status_code FROM latency_samples "
            "WHERE probe_name = ? AND timestamp > ? ORDER BY timestamp ASC",
            (probe_name, cutoff),
        )
        return [{"timestamp": r["timestamp"], "latency_ms": r["latency_ms"], "status_code": r["status_code"]}
                for r in await cursor.fetchall()]

    # --- Retention purge ---

    async def purge_old_data(self):
        now = time.time()
        await self._db.execute(
            "DELETE FROM probe_results WHERE timestamp < ?",
            (now - config.RETENTION_PROBE_RESULTS_DAYS * 86400,),
        )
        await self._db.execute(
            "DELETE FROM incidents WHERE opened_at < ? AND status NOT IN ('open', 'acknowledged')",
            (now - config.RETENTION_INCIDENTS_DAYS * 86400,),
        )
        await self._db.execute(
            "DELETE FROM health_snapshots WHERE timestamp < ?",
            (now - config.RETENTION_HEALTH_DAYS * 86400,),
        )
        await self._db.execute(
            "DELETE FROM latency_samples WHERE timestamp < ?",
            (now - config.RETENTION_LATENCY_DAYS * 86400,),
        )
        await self._db.commit()
