"""JSON API routes for AI Ops service."""

from __future__ import annotations
import datetime
import time
from fastapi import APIRouter, Depends, HTTPException
from .auth import verify_credentials
from .repo import Repository
from .models import AuditEntry
from . import db as _db

router = APIRouter(prefix="/api", tags=["api"])

# Public health check (no auth — for systemd/monitoring)
health_router = APIRouter(tags=["health"])


async def _repo() -> Repository:
    conn = await _db.get_db()
    return Repository(conn)


def _get_collector():
    """Get collector from app state (set in main.py lifespan)."""
    from .main import _collector
    return _collector


@health_router.get("/api/health")
async def health_check():
    collector = _get_collector()
    return {
        "status": "ok",
        "uptime_sec": round(time.time() - _get_start_time(), 1),
        "collections": collector.collection_count if collector else 0,
    }


_start_time = time.time()


def _get_start_time():
    return _start_time


# --- Status ---

@router.get("/status", dependencies=[Depends(verify_credentials)])
async def service_status(repo: Repository = Depends(_repo)):
    collector = _get_collector()
    stats = await repo.get_triage_stats()
    latest = await repo.get_latest_snapshot()
    return {
        "service": "aiops",
        "uptime_sec": round(time.time() - _get_start_time(), 1),
        "collections": collector.collection_count if collector else 0,
        "lane_ages": collector.lane_ages if collector else {},
        "source_errors": collector.source_errors if collector else {},
        "latest_snapshot_at": latest["timestamp"] if latest else None,
        "latest_health_score": latest["health_score"] if latest else None,
        "latest_health_status": latest["health_status"] if latest else None,
        "triage_stats": stats,
    }


# --- Triage ---

@router.get("/triage/active", dependencies=[Depends(verify_credentials)])
async def triage_active(repo: Repository = Depends(_repo)):
    return await repo.get_active_cases()


@router.get("/triage/recent", dependencies=[Depends(verify_credentials)])
async def triage_recent(limit: int = 50, status: str | None = None, repo: Repository = Depends(_repo)):
    return await repo.get_recent_cases(min(limit, 200), status)


@router.get("/triage/{case_id}", dependencies=[Depends(verify_credentials)])
async def triage_detail(case_id: str, repo: Repository = Depends(_repo)):
    case = await repo.get_case_by_id(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@router.post("/triage/{case_id}/acknowledge")
async def triage_acknowledge(case_id: str, user: str = Depends(verify_credentials), repo: Repository = Depends(_repo)):
    ok = await repo.update_case_status(case_id, "acknowledged")
    if ok:
        seq = await repo.get_next_audit_seq()
        date_str = datetime.date.today().strftime("%Y%m%d")
        await repo.create_audit_entry(AuditEntry(
            entry_id=f"AUD-{date_str}-{seq:04d}",
            timestamp=time.time(),
            actor=user,
            action="triage_acknowledged",
            target_type="triage_case",
            target_id=case_id,
        ))
    return {"acknowledged": ok}


@router.post("/triage/{case_id}/false-positive")
async def triage_false_positive(case_id: str, user: str = Depends(verify_credentials), repo: Repository = Depends(_repo)):
    ok = await repo.update_case_status(case_id, "false_positive", reason="Marked by operator")
    if ok:
        seq = await repo.get_next_audit_seq()
        date_str = datetime.date.today().strftime("%Y%m%d")
        await repo.create_audit_entry(AuditEntry(
            entry_id=f"AUD-{date_str}-{seq:04d}",
            timestamp=time.time(),
            actor=user,
            action="triage_false_positive",
            target_type="triage_case",
            target_id=case_id,
        ))
    return {"marked_false_positive": ok}


# --- Evidence (proxied from upstream sources) ---

@router.get("/evidence/snapshot", dependencies=[Depends(verify_credentials)])
async def evidence_snapshot():
    """Latest collected snapshot summary (not full blob)."""
    collector = _get_collector()
    snap = collector.latest_snapshot if collector else None
    if not snap:
        return {"error": "No snapshot collected yet"}
    return {
        "timestamp": snap.timestamp,
        "health_score": snap.health_score,
        "health_status": snap.health_status,
        "runner_active": snap.runner_active,
        "bridge_producer_alive": snap.bridge_producer_alive,
        "bridge_stale_count": snap.bridge_stale_count,
        "bridge_stale_sections": snap.bridge_stale_sections,
        "bot_total": snap.bot_total,
        "bot_status_counts": snap.bot_status_counts,
        "flash_crash_active": snap.flash_crash_active,
        "active_incidents_count": len(snap.active_incidents) if snap.active_incidents else 0,
        "source_errors": snap.source_errors,
        "collection_timing": snap.collection_timing,
    }


@router.get("/evidence/incidents", dependencies=[Depends(verify_credentials)])
async def evidence_incidents():
    collector = _get_collector()
    snap = collector.latest_snapshot if collector else None
    return snap.active_incidents or [] if snap else []


@router.get("/evidence/probes", dependencies=[Depends(verify_credentials)])
async def evidence_probes():
    collector = _get_collector()
    snap = collector.latest_snapshot if collector else None
    return snap.probe_results or {} if snap else {}


@router.get("/evidence/bridge", dependencies=[Depends(verify_credentials)])
async def evidence_bridge():
    collector = _get_collector()
    snap = collector.latest_snapshot if collector else None
    if not snap or not snap.bridge_diagnostics:
        return {"error": "No bridge diagnostics available"}
    # Return sections summary, not the full blob
    sections = (snap.bridge_diagnostics.get("sections") or {})
    return {
        "producer_alive": snap.bridge_diagnostics.get("producer_alive"),
        "produced_at": snap.bridge_diagnostics.get("produced_at"),
        "sections": {
            name: {
                "present": sec.get("present"),
                "age_sec": sec.get("age_sec"),
                "stale": sec.get("stale"),
                "shape_valid": sec.get("shape_valid"),
            }
            for name, sec in sections.items()
        },
    }


@router.get("/evidence/logs", dependencies=[Depends(verify_credentials)])
async def evidence_logs(source: str = "runner", lines: int = 50):
    collector = _get_collector()
    snap = collector.latest_snapshot if collector else None
    if not snap:
        return {"lines": [], "source": source}
    log_lines = snap.runner_log_lines if source == "runner" else snap.app_log_lines
    if not log_lines:
        return {"lines": [], "source": source}
    capped = min(lines, 200)
    return {"lines": [l.rstrip() for l in log_lines[-capped:]], "source": source}


# --- Audit ---

@router.get("/audit", dependencies=[Depends(verify_credentials)])
async def audit_log(limit: int = 100, action: str | None = None, repo: Repository = Depends(_repo)):
    return await repo.get_audit_log(min(limit, 500), action)
