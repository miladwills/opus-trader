"""HTML page routes rendered with Jinja2."""

from __future__ import annotations
import time
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .auth import verify_credentials
from .repo import Repository
from . import db as _db

router = APIRouter(dependencies=[Depends(verify_credentials)])


async def _repo() -> Repository:
    conn = await _db.get_db()
    return Repository(conn)


def _get_collector():
    from .main import _collector
    return _collector


def _get_supervisor():
    from .main import _supervisor
    return _supervisor


def _time_ago(ts) -> str:
    if not ts:
        return "never"
    diff = time.time() - float(ts)
    if diff < 0:
        return "just now"
    if diff < 60:
        return f"{int(diff)}s ago"
    elif diff < 3600:
        return f"{int(diff / 60)}m ago"
    elif diff < 86400:
        return f"{int(diff / 3600)}h ago"
    return f"{int(diff / 86400)}d ago"


def _severity_color(sev: str) -> str:
    return {
        "critical": "red",
        "high": "orange",
        "medium": "yellow",
        "low": "blue",
    }.get(sev, "gray")


def _status_color(status: str) -> str:
    return {
        "running": "emerald",
        "idle": "cyan",
        "paused": "yellow",
        "stopped": "gray",
        "error": "red",
    }.get(status, "gray")


@router.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/overview")


@router.get("/overview", response_class=HTMLResponse)
async def overview(request: Request, repo: Repository = Depends(_repo)):
    collector = _get_collector()
    supervisor = _get_supervisor()
    snap = collector.latest_snapshot if collector else None
    active_cases = await repo.get_active_cases()
    stats = await repo.get_triage_stats()
    recent_audit = await repo.get_audit_log(limit=10)
    health_history = await repo.get_snapshot_history(hours=2.0)
    agents = await repo.get_all_agents()
    pending_proposals = await repo.get_pending_proposals()
    proposal_stats = await repo.get_proposal_stats()

    return request.app.state.templates.TemplateResponse("overview.html", {
        "request": request,
        "snap": snap,
        "active_cases": active_cases,
        "stats": stats,
        "recent_audit": recent_audit,
        "health_history": health_history,
        "collector": collector,
        "agents": agents,
        "pending_proposals": pending_proposals,
        "proposal_stats": proposal_stats,
        "time_ago": _time_ago,
        "severity_color": _severity_color,
        "status_color": _status_color,
        "now": time.time(),
    })


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request, repo: Repository = Depends(_repo)):
    agents = await repo.get_all_agents()
    return request.app.state.templates.TemplateResponse("agents.html", {
        "request": request,
        "agents": agents,
        "time_ago": _time_ago,
        "status_color": _status_color,
        "now": time.time(),
    })


@router.get("/triage", response_class=HTMLResponse)
async def triage(request: Request, status: str | None = None, repo: Repository = Depends(_repo)):
    if status:
        cases = await repo.get_recent_cases(limit=100, status_filter=status)
    else:
        cases = await repo.get_recent_cases(limit=100)

    stats = await repo.get_triage_stats()

    return request.app.state.templates.TemplateResponse("triage.html", {
        "request": request,
        "cases": cases,
        "stats": stats,
        "current_filter": status,
        "time_ago": _time_ago,
        "severity_color": _severity_color,
        "now": time.time(),
    })


@router.get("/evidence", response_class=HTMLResponse)
async def evidence(request: Request):
    collector = _get_collector()
    snap = collector.latest_snapshot if collector else None

    return request.app.state.templates.TemplateResponse("evidence.html", {
        "request": request,
        "snap": snap,
        "time_ago": _time_ago,
        "now": time.time(),
    })


@router.get("/approvals", response_class=HTMLResponse)
async def approvals_page(request: Request, status: str | None = None, repo: Repository = Depends(_repo)):
    if status:
        proposals = await repo.get_recent_proposals(limit=100, status_filter=status)
    else:
        proposals = await repo.get_recent_proposals(limit=100)
    stats = await repo.get_proposal_stats()
    recent_execs = await repo.get_recent_executions(limit=10)

    return request.app.state.templates.TemplateResponse("approvals.html", {
        "request": request,
        "proposals": proposals,
        "stats": stats,
        "current_filter": status,
        "recent_executions": recent_execs,
        "time_ago": _time_ago,
        "severity_color": _severity_color,
        "now": time.time(),
    })


@router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request, repo: Repository = Depends(_repo)):
    entries = await repo.get_audit_log(limit=100)
    return request.app.state.templates.TemplateResponse("audit.html", {
        "request": request,
        "entries": entries,
        "time_ago": _time_ago,
        "now": time.time(),
    })
