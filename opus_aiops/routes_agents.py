"""API routes for agent lifecycle management."""

from __future__ import annotations
import time
from fastapi import APIRouter, Depends, HTTPException
from .auth import verify_credentials
from .repo import Repository
from . import db as _db

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def _repo() -> Repository:
    conn = await _db.get_db()
    return Repository(conn)


def _get_supervisor():
    from .main import _supervisor
    return _supervisor


# --- Agent list & detail ---

@router.get("", dependencies=[Depends(verify_credentials)])
async def list_agents(repo: Repository = Depends(_repo)):
    return await repo.get_all_agents()


@router.get("/{agent_id}", dependencies=[Depends(verify_credentials)])
async def agent_detail(agent_id: str, repo: Repository = Depends(_repo)):
    agent = await repo.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.get("/{agent_id}/detail", dependencies=[Depends(verify_credentials)])
async def agent_full_detail(agent_id: str, repo: Repository = Depends(_repo)):
    """Consolidated detail: agent + runs + stats + activity + related data + health."""
    agent = await repo.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    run_stats = await repo.get_agent_run_stats(agent_id, limit=50)
    last_success = await repo.get_last_successful_run(agent_id)
    last_failure = await repo.get_last_failed_run(agent_id)
    recent_runs = await repo.get_agent_runs(agent_id, limit=20)
    activity = await repo.get_agent_activity(agent_id, limit=20)
    related_proposals = await repo.get_agent_related_proposals(agent_id, limit=10)
    related_cases = await repo.get_recent_cases(limit=10)

    now = time.time()
    interval = agent.get("interval_sec", 300)
    last_hb = agent.get("last_heartbeat_at")
    hb_elapsed = (now - last_hb) if last_hb else None

    health_signals = []
    if agent.get("status") == "error":
        health_signals.append({"signal": "status_error", "level": "critical", "detail": agent.get("error_summary", "")})
    if hb_elapsed is not None and hb_elapsed > interval * 3:
        health_signals.append({"signal": "heartbeat_stale", "level": "warning", "detail": f"{int(hb_elapsed)}s since last heartbeat"})
    if run_stats["errors"] > 0 and run_stats["total"] > 0:
        err_rate = run_stats["errors"] / run_stats["total"]
        if err_rate > 0.5:
            health_signals.append({"signal": "high_error_rate", "level": "warning", "detail": f"{run_stats['errors']}/{run_stats['total']} recent runs failed"})
    last_run_at = agent.get("last_run_at")
    if last_run_at and agent.get("auto_run") and agent.get("status") in ("idle", "running"):
        overdue = now - last_run_at - interval
        if overdue > interval * 2:
            health_signals.append({"signal": "overdue", "level": "warning", "detail": f"Run overdue by {int(overdue)}s"})
    if not last_success and run_stats["total"] > 3:
        health_signals.append({"signal": "never_succeeded", "level": "warning", "detail": "No successful runs in recent history"})

    health_ok = len(health_signals) == 0
    health_level = "healthy" if health_ok else ("critical" if any(s["level"] == "critical" for s in health_signals) else "degraded")

    return {
        "agent": agent,
        "run_stats": run_stats,
        "last_success": last_success,
        "last_failure": last_failure,
        "recent_runs": recent_runs,
        "activity": activity,
        "related_proposals": related_proposals,
        "related_cases": related_cases,
        "health": {"level": health_level, "signals": health_signals},
    }


@router.get("/{agent_id}/runs", dependencies=[Depends(verify_credentials)])
async def agent_runs(agent_id: str, limit: int = 20, repo: Repository = Depends(_repo)):
    return await repo.get_agent_runs(agent_id, min(limit, 100))


@router.get("/{agent_id}/activity", dependencies=[Depends(verify_credentials)])
async def agent_activity(agent_id: str, limit: int = 20, repo: Repository = Depends(_repo)):
    return await repo.get_agent_activity(agent_id, min(limit, 100))


# --- Agent controls ---

@router.post("/{agent_id}/start")
async def agent_start(agent_id: str, user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.start_agent(agent_id, actor=user)
    return {"result": result}


@router.post("/{agent_id}/stop")
async def agent_stop(agent_id: str, user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.stop_agent(agent_id, actor=user)
    return {"result": result}


@router.post("/{agent_id}/pause")
async def agent_pause(agent_id: str, user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.pause_agent(agent_id, actor=user)
    return {"result": result}


@router.post("/{agent_id}/resume")
async def agent_resume(agent_id: str, user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.resume_agent(agent_id, actor=user)
    return {"result": result}


@router.post("/{agent_id}/run-once")
async def agent_run_once(agent_id: str, user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.run_once(agent_id, actor=user)
    return {"result": result}


@router.post("/{agent_id}/restart")
async def agent_restart(agent_id: str, user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.restart_agent(agent_id, actor=user)
    return {"result": result}


# --- Bulk controls ---

@router.post("/bulk/start-all")
async def start_all(user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.start_all_enabled(actor=user)
    return {"result": result}


@router.post("/bulk/stop-all")
async def stop_all(user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.stop_all(actor=user)
    return {"result": result}


@router.post("/bulk/pause-all")
async def pause_all(user: str = Depends(verify_credentials)):
    supervisor = _get_supervisor()
    if not supervisor:
        raise HTTPException(503, "Supervisor not available")
    result = await supervisor.pause_all(actor=user)
    return {"result": result}
