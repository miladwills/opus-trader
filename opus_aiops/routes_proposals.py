"""API routes for proposal approval workflow."""

from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body
from .auth import verify_credentials
from .repo import Repository
from .proposals import approve_proposal, reject_proposal
from . import db as _db

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


async def _repo() -> Repository:
    conn = await _db.get_db()
    return Repository(conn)


def _get_context():
    from .main import _collector, _triage_engine
    conn_holder = {}

    async def _make_ctx():
        conn = await _db.get_db()
        return {
            "collector": _collector,
            "triage_engine": _triage_engine,
            "repo": Repository(conn),
        }
    return _make_ctx


# --- Proposal list & detail ---

@router.get("", dependencies=[Depends(verify_credentials)])
async def list_proposals(
    limit: int = 50,
    status: str | None = None,
    repo: Repository = Depends(_repo),
):
    return await repo.get_recent_proposals(min(limit, 200), status)


@router.get("/pending", dependencies=[Depends(verify_credentials)])
async def pending_proposals(repo: Repository = Depends(_repo)):
    return await repo.get_pending_proposals()


@router.get("/stats", dependencies=[Depends(verify_credentials)])
async def proposal_stats(repo: Repository = Depends(_repo)):
    return await repo.get_proposal_stats()


@router.get("/{proposal_id}", dependencies=[Depends(verify_credentials)])
async def proposal_detail(proposal_id: str, repo: Repository = Depends(_repo)):
    prop = await repo.get_proposal(proposal_id)
    if not prop:
        raise HTTPException(404, "Proposal not found")
    return prop


# --- Approve / Reject ---

@router.post("/{proposal_id}/approve")
async def approve(
    proposal_id: str,
    user: str = Depends(verify_credentials),
    repo: Repository = Depends(_repo),
):
    from .main import _collector, _triage_engine
    context = {
        "collector": _collector,
        "triage_engine": _triage_engine,
        "repo": repo,
    }
    result = await approve_proposal(proposal_id, user, repo, context)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/{proposal_id}/reject")
async def reject(
    proposal_id: str,
    reason: str = Body("", embed=True),
    user: str = Depends(verify_credentials),
    repo: Repository = Depends(_repo),
):
    result = await reject_proposal(proposal_id, user, reason or "Operator rejected", repo)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


# --- Execution history ---

@router.get("/executions/recent", dependencies=[Depends(verify_credentials)])
async def recent_executions(limit: int = 20, repo: Repository = Depends(_repo)):
    return await repo.get_recent_executions(min(limit, 100))
