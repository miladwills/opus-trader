"""HTML page routes rendered with Jinja2."""

from __future__ import annotations
import time
from dataclasses import asdict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..auth import verify_credentials
from ..storage.repo import Repository
from .. import db as _db

router = APIRouter(dependencies=[Depends(verify_credentials)])


async def _repo() -> Repository:
    conn = await _db.get_db()
    return Repository(conn)


def _time_ago(ts: float) -> str:
    diff = time.time() - ts
    if diff < 60:
        return f"{int(diff)}s ago"
    elif diff < 3600:
        return f"{int(diff / 60)}m ago"
    elif diff < 86400:
        return f"{int(diff / 3600)}h ago"
    else:
        return f"{int(diff / 86400)}d ago"


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, repo: Repository = Depends(_repo)):
    health = await repo.get_latest_health()
    incidents = await repo.get_recent_incidents(10)
    probes = await repo.get_all_latest_probes()
    health_history = await repo.get_health_history(2.0)
    return request.app.state.templates.TemplateResponse("dashboard.html", {
        "request": request,
        "health": asdict(health) if health else None,
        "incidents": [asdict(i) for i in incidents],
        "probes": {k: asdict(v) for k, v in probes.items()},
        "health_history": [{"ts": h.timestamp, "score": h.overall_score} for h in health_history],
        "time_ago": _time_ago,
        "now": time.time(),
    })


@router.get("/incidents", response_class=HTMLResponse)
async def incidents_page(request: Request, repo: Repository = Depends(_repo)):
    incidents = await repo.get_recent_incidents(100)
    return request.app.state.templates.TemplateResponse("incidents.html", {
        "request": request,
        "incidents": [asdict(i) for i in incidents],
        "time_ago": _time_ago,
        "now": time.time(),
    })


@router.get("/probes", response_class=HTMLResponse)
async def probes_page(request: Request, repo: Repository = Depends(_repo)):
    probes = await repo.get_all_latest_probes()
    return request.app.state.templates.TemplateResponse("probes.html", {
        "request": request,
        "probes": {k: asdict(v) for k, v in probes.items()},
        "time_ago": _time_ago,
        "now": time.time(),
    })


@router.get("/bridge", response_class=HTMLResponse)
async def bridge_page(request: Request, repo: Repository = Depends(_repo)):
    probes = await repo.get_all_latest_probes()
    bridge_http = probes.get("http_bridge_diag")
    bridge_file = probes.get("file_bridge")
    return request.app.state.templates.TemplateResponse("bridge.html", {
        "request": request,
        "bridge_http": asdict(bridge_http) if bridge_http else None,
        "bridge_file": asdict(bridge_file) if bridge_file else None,
        "time_ago": _time_ago,
        "now": time.time(),
    })


@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request, repo: Repository = Depends(_repo)):
    probes = await repo.get_all_latest_probes()
    return request.app.state.templates.TemplateResponse("system.html", {
        "request": request,
        "probes": {k: asdict(v) for k, v in probes.items()},
        "time_ago": _time_ago,
        "now": time.time(),
    })


@router.get("/debug", response_class=HTMLResponse)
async def debug_page(request: Request, repo: Repository = Depends(_repo)):
    probes = await repo.get_all_latest_probes()
    health = await repo.get_latest_health()
    return request.app.state.templates.TemplateResponse("debug.html", {
        "request": request,
        "probes": {k: asdict(v) for k, v in probes.items()},
        "health": asdict(health) if health else None,
        "now": time.time(),
    })
