"""JSON API routes for AJAX refresh."""

from __future__ import annotations
from dataclasses import asdict
from fastapi import APIRouter, Depends
from ..auth import verify_credentials
from ..storage.repo import Repository
from .. import db as _db

router = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(verify_credentials)])


async def _repo() -> Repository:
    conn = await _db.get_db()
    return Repository(conn)


@router.get("/health/current")
async def health_current(repo: Repository = Depends(_repo)):
    snap = await repo.get_latest_health()
    if not snap:
        return {"overall_score": 0, "overall_status": "unknown", "components": {}}
    return asdict(snap)


@router.get("/health/history")
async def health_history(hours: float = 2.0, repo: Repository = Depends(_repo)):
    history = await repo.get_health_history(hours)
    return [{"timestamp": h.timestamp, "overall_score": h.overall_score, "overall_status": h.overall_status}
            for h in history]


@router.get("/incidents/recent")
async def incidents_recent(limit: int = 50, status: str | None = None, repo: Repository = Depends(_repo)):
    incidents = await repo.get_recent_incidents(limit, status)
    return [asdict(i) for i in incidents]


@router.post("/incidents/{incident_id}/acknowledge")
async def incident_acknowledge(incident_id: str, repo: Repository = Depends(_repo)):
    ok = await repo.acknowledge_incident(incident_id)
    return {"acknowledged": ok}


@router.get("/probes/all")
async def probes_all(repo: Repository = Depends(_repo)):
    latest = await repo.get_all_latest_probes()
    return {name: asdict(r) for name, r in latest.items()}


@router.get("/probes/{probe_name}/history")
async def probe_history(probe_name: str, limit: int = 50, repo: Repository = Depends(_repo)):
    results = await repo.get_recent_probes(probe_name, limit)
    return [asdict(r) for r in results]


@router.get("/latency/{probe_name}")
async def latency_history(probe_name: str, minutes: int = 30, repo: Repository = Depends(_repo)):
    samples = await repo.get_latency_history(probe_name, minutes)
    return samples
