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


def _heartbeat_freshness(last_hb, interval_sec: int) -> dict:
    """Calculate heartbeat freshness badge for an agent."""
    if not last_hb:
        return {"label": "offline", "color": "gray", "css": "bg-slate-800 text-gray-500"}
    elapsed = time.time() - float(last_hb)
    if elapsed <= interval_sec * 1.5:
        return {"label": "fresh", "color": "emerald", "css": "bg-emerald-900/50 text-emerald-400"}
    elif elapsed <= interval_sec * 3:
        return {"label": "delayed", "color": "yellow", "css": "bg-yellow-900/50 text-yellow-400"}
    elif elapsed <= interval_sec * 6:
        return {"label": "stale", "color": "orange", "css": "bg-orange-900/50 text-orange-400"}
    else:
        return {"label": "offline", "color": "gray", "css": "bg-slate-800 text-gray-500"}


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
    now = time.time()

    # Enrich each agent with heartbeat freshness + recent activity
    for a in agents:
        a["heartbeat"] = _heartbeat_freshness(a.get("last_heartbeat_at"), a.get("interval_sec", 300))
        a["activity"] = await repo.get_agent_activity(a["agent_id"], limit=5)
        # Next expected run
        last_run = a.get("last_run_at") or 0
        interval = a.get("interval_sec", 300)
        if a.get("auto_run") and a.get("status") in ("idle", "running"):
            next_run = last_run + interval
            a["next_run_in"] = max(0, next_run - now)
        else:
            a["next_run_in"] = None

    return request.app.state.templates.TemplateResponse("agents.html", {
        "request": request,
        "agents": agents,
        "time_ago": _time_ago,
        "status_color": _status_color,
        "heartbeat_freshness": _heartbeat_freshness,
        "now": now,
    })


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
async def agent_detail_page(request: Request, agent_id: str, repo: Repository = Depends(_repo)):
    agent = await repo.get_agent(agent_id)
    if not agent:
        return RedirectResponse("/agents")

    now = time.time()
    agent["heartbeat"] = _heartbeat_freshness(agent.get("last_heartbeat_at"), agent.get("interval_sec", 300))

    last_run = agent.get("last_run_at") or 0
    interval = agent.get("interval_sec", 300)
    if agent.get("auto_run") and agent.get("status") in ("idle", "running"):
        agent["next_run_in"] = max(0, last_run + interval - now)
    else:
        agent["next_run_in"] = None

    run_stats = await repo.get_agent_run_stats(agent_id, limit=50)
    last_success = await repo.get_last_successful_run(agent_id)
    last_failure = await repo.get_last_failed_run(agent_id)
    recent_runs = await repo.get_agent_runs(agent_id, limit=20)

    last_run_duration = None
    if recent_runs and recent_runs[0].get("started_at") and recent_runs[0].get("finished_at"):
        last_run_duration = round(recent_runs[0]["finished_at"] - recent_runs[0]["started_at"], 2)

    activity = await repo.get_agent_activity(agent_id, limit=20)
    related_proposals = await repo.get_agent_related_proposals(agent_id, limit=10)
    related_cases = await repo.get_recent_cases(limit=10)

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
    if agent.get("last_run_at") and agent.get("auto_run") and agent.get("status") in ("idle", "running"):
        overdue = now - agent["last_run_at"] - interval
        if overdue > interval * 2:
            health_signals.append({"signal": "overdue", "level": "warning", "detail": f"Run overdue by {int(overdue)}s"})
    if not last_success and run_stats["total"] > 3:
        health_signals.append({"signal": "never_succeeded", "level": "warning", "detail": "No successful runs in recent history"})

    health_ok = len(health_signals) == 0
    health_level = "healthy" if health_ok else ("critical" if any(s["level"] == "critical" for s in health_signals) else "degraded")

    return request.app.state.templates.TemplateResponse("agent_detail.html", {
        "request": request,
        "agent": agent,
        "run_stats": run_stats,
        "last_success": last_success,
        "last_failure": last_failure,
        "last_run_duration": last_run_duration,
        "recent_runs": recent_runs,
        "activity": activity,
        "related_proposals": related_proposals,
        "related_cases": related_cases,
        "health_level": health_level,
        "health_signals": health_signals,
        "time_ago": _time_ago,
        "status_color": _status_color,
        "severity_color": _severity_color,
        "now": now,
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
