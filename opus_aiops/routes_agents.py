"""API routes for agent lifecycle management."""

from __future__ import annotations
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


@router.get("/{agent_id}/runs", dependencies=[Depends(verify_credentials)])
async def agent_runs(agent_id: str, limit: int = 20, repo: Repository = Depends(_repo)):
    return await repo.get_agent_runs(agent_id, min(limit, 100))


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
