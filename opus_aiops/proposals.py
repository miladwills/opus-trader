"""Proposal approval workflow and execution for AI Ops.

Flow:
  1. Agent/rule creates proposal candidate
  2. Fix agent moves candidate to pending (validates allowlist)
  3. Promotion gate validates and gates
  4. Operator approves or rejects via UI/API
  5. If approved, allowlisted action executes
  6. Execution result recorded
  7. Audit trail written
"""

from __future__ import annotations
import datetime
import logging
import time

from .models import AuditEntry, ActionExecution
from .repo import Repository
from .actions import execute_action, is_action_allowed

logger = logging.getLogger("aiops.proposals")


async def approve_proposal(
    proposal_id: str,
    actor: str,
    repo: Repository,
    context: dict,
) -> dict:
    """Approve a pending proposal and execute its action."""
    prop = await repo.get_proposal(proposal_id)
    if not prop:
        return {"ok": False, "error": "Proposal not found"}
    if prop["status"] != "pending":
        return {"ok": False, "error": f"Proposal is '{prop['status']}', not pending"}

    action_type = prop["action_type"]
    if not is_action_allowed(action_type):
        await repo.update_proposal_status(
            proposal_id,
            status="rejected",
            rejected_by="system",
            rejected_at=time.time(),
            gate_reason=f"Action '{action_type}' no longer allowlisted",
        )
        return {"ok": False, "error": f"Action '{action_type}' not in allowlist"}

    # Mark approved
    now = time.time()
    await repo.update_proposal_status(
        proposal_id,
        status="approved",
        approved_by=actor,
        approved_at=now,
    )
    await _audit(repo, actor, "proposal_approved", "proposal", proposal_id)

    # Execute the action
    execution = ActionExecution(
        proposal_id=proposal_id,
        action_type=action_type,
        action_params=prop.get("action_params", {}),
        started_at=time.time(),
        status="running",
    )
    exec_id = await repo.record_execution(execution)

    await repo.update_proposal_status(
        proposal_id,
        execution_started_at=time.time(),
    )

    result = await execute_action(action_type, prop.get("action_params", {}), context)

    finished_at = time.time()
    exec_status = result["status"]
    await repo.update_execution(
        exec_id,
        finished_at=finished_at,
        status=exec_status,
        result=result.get("result", ""),
        error=result.get("error"),
    )

    final_status = "executed" if exec_status == "completed" else "failed"
    await repo.update_proposal_status(
        proposal_id,
        status=final_status,
        execution_result=result.get("result", "") or result.get("error", ""),
        execution_finished_at=finished_at,
    )

    await _audit(repo, actor, f"proposal_{final_status}", "proposal", proposal_id, {
        "action_type": action_type,
        "execution_status": exec_status,
    })

    return {
        "ok": True,
        "proposal_id": proposal_id,
        "execution_status": exec_status,
        "result": result.get("result", ""),
        "error": result.get("error"),
    }


async def reject_proposal(
    proposal_id: str,
    actor: str,
    reason: str,
    repo: Repository,
) -> dict:
    """Reject a pending proposal."""
    prop = await repo.get_proposal(proposal_id)
    if not prop:
        return {"ok": False, "error": "Proposal not found"}
    if prop["status"] != "pending":
        return {"ok": False, "error": f"Proposal is '{prop['status']}', not pending"}

    await repo.update_proposal_status(
        proposal_id,
        status="rejected",
        rejected_by=actor,
        rejected_at=time.time(),
        gate_reason=reason or "Rejected by operator",
    )
    await _audit(repo, actor, "proposal_rejected", "proposal", proposal_id, {"reason": reason})
    return {"ok": True, "proposal_id": proposal_id}


async def _audit(repo: Repository, actor: str, action: str, target_type: str, target_id: str, detail: dict | None = None):
    seq = await repo.get_next_audit_seq()
    date_str = datetime.date.today().strftime("%Y%m%d")
    await repo.create_audit_entry(AuditEntry(
        entry_id=f"AUD-{date_str}-{seq:04d}",
        timestamp=time.time(),
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
    ))
