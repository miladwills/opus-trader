"""Allowlisted action bridge for AI Ops.

Only safe, non-trading operational actions are permitted.
Every action is:
  - explicitly allowlisted
  - approval-gated (caller must supply approved proposal_id)
  - audited
  - isolated from trading execution paths

NEVER ALLOWED: order placement, cancel orders, close positions,
bot start/stop in trader, config mutation in trader, direct writes
to trader storage, exchange interaction.
"""

from __future__ import annotations
import logging
import time

logger = logging.getLogger("aiops.actions")


# ---------------------------------------------------------------------------
# Action registry — exhaustive allowlist
# ---------------------------------------------------------------------------

ALLOWED_ACTIONS: dict[str, dict] = {
    "refresh_collection": {
        "description": "Trigger an immediate AI Ops data collection cycle",
        "risk": "none",
        "reversible": True,
    },
    "rerun_triage": {
        "description": "Rerun triage engine against latest snapshot",
        "risk": "none",
        "reversible": True,
    },
    "collect_diagnostics": {
        "description": "Collect a diagnostics bundle from all evidence sources",
        "risk": "none",
        "reversible": True,
    },
    "refresh_probes": {
        "description": "Trigger a re-fetch of watchdog probe results",
        "risk": "none",
        "reversible": True,
    },
    "recheck_health": {
        "description": "Trigger a re-fetch of watchdog health status",
        "risk": "none",
        "reversible": True,
    },
    "mark_manual_followup": {
        "description": "Mark a triage case for manual operator follow-up",
        "risk": "none",
        "reversible": True,
        "params": ["case_id"],
    },
    "export_evidence": {
        "description": "Export current evidence snapshot as a bundle",
        "risk": "none",
        "reversible": True,
    },
}

# Actions that are NEVER allowed — checked defensively
FORBIDDEN_PREFIXES = (
    "order_", "cancel_", "close_", "bot_start", "bot_stop",
    "config_mutate", "storage_write", "exchange_",
    "trader_restart", "runner_restart", "position_",
)


def is_action_allowed(action_type: str) -> bool:
    """Check if an action type is in the allowlist."""
    if any(action_type.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return False
    return action_type in ALLOWED_ACTIONS


def get_action_info(action_type: str) -> dict | None:
    """Get metadata for an allowed action."""
    return ALLOWED_ACTIONS.get(action_type)


async def execute_action(action_type: str, params: dict, context: dict) -> dict:
    """Execute an allowlisted action.

    Args:
        action_type: Must be in ALLOWED_ACTIONS
        params: Action-specific parameters
        context: Contains 'collector', 'triage_engine', 'repo' references

    Returns:
        {"status": "completed"|"failed", "result": str, "error": str|None}
    """
    if not is_action_allowed(action_type):
        return {
            "status": "failed",
            "result": "",
            "error": f"Action '{action_type}' is not in the allowlist",
        }

    handler = _ACTION_HANDLERS.get(action_type)
    if not handler:
        return {
            "status": "failed",
            "result": "",
            "error": f"No handler implemented for '{action_type}'",
        }

    try:
        result = await handler(params, context)
        return {"status": "completed", "result": result, "error": None}
    except Exception as exc:
        logger.error("Action %s failed: %s", action_type, exc)
        return {"status": "failed", "result": "", "error": str(exc)}


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

async def _handle_refresh_collection(params: dict, ctx: dict) -> str:
    collector = ctx.get("collector")
    if not collector:
        return "Collector not available"
    snapshot = await collector.collect()
    return f"Collection completed, health_score={snapshot.health_score}"


async def _handle_rerun_triage(params: dict, ctx: dict) -> str:
    engine = ctx.get("triage_engine")
    collector = ctx.get("collector")
    if not engine or not collector:
        return "Engine or collector not available"
    snap = collector.latest_snapshot
    if not snap:
        return "No snapshot available"
    cases = engine.evaluate(snap)
    return f"Triage rerun: {len(cases)} case(s) evaluated"


async def _handle_collect_diagnostics(params: dict, ctx: dict) -> str:
    collector = ctx.get("collector")
    if not collector:
        return "Collector not available"
    snap = collector.latest_snapshot
    if not snap:
        return "No snapshot available"
    diag = {
        "health_score": snap.health_score,
        "health_status": snap.health_status,
        "source_errors": snap.source_errors,
        "bridge_stale_count": snap.bridge_stale_count,
        "active_incidents_count": len(snap.active_incidents) if snap.active_incidents else 0,
        "collection_timing": snap.collection_timing,
        "collected_at": time.time(),
    }
    return f"Diagnostics: {diag}"


async def _handle_refresh_probes(params: dict, ctx: dict) -> str:
    collector = ctx.get("collector")
    if not collector:
        return "Collector not available"
    # Force medium lane refresh on next tick by resetting its timestamp
    collector._last_medium = 0
    return "Probe refresh scheduled for next collection tick"


async def _handle_recheck_health(params: dict, ctx: dict) -> str:
    collector = ctx.get("collector")
    if not collector:
        return "Collector not available"
    collector._last_fast = 0
    return "Health recheck scheduled for next collection tick"


async def _handle_mark_manual_followup(params: dict, ctx: dict) -> str:
    repo = ctx.get("repo")
    if not repo:
        return "Repository not available"
    case_id = params.get("case_id", "")
    if not case_id:
        return "Missing case_id parameter"
    ok = await repo.update_case_status(case_id, "acknowledged", reason="Marked for manual follow-up via action bridge")
    return f"Case {case_id} marked for follow-up" if ok else f"Case {case_id} not found"


async def _handle_export_evidence(params: dict, ctx: dict) -> str:
    collector = ctx.get("collector")
    if not collector:
        return "Collector not available"
    snap = collector.latest_snapshot
    if not snap:
        return "No snapshot available"
    # Build a compact evidence summary
    summary = {
        "timestamp": snap.timestamp,
        "health": {"score": snap.health_score, "status": snap.health_status},
        "runner_active": snap.runner_active,
        "bridge_stale": snap.bridge_stale_sections,
        "incidents": len(snap.active_incidents) if snap.active_incidents else 0,
        "source_errors": snap.source_errors,
    }
    return f"Evidence exported: {summary}"


_ACTION_HANDLERS = {
    "refresh_collection": _handle_refresh_collection,
    "rerun_triage": _handle_rerun_triage,
    "collect_diagnostics": _handle_collect_diagnostics,
    "refresh_probes": _handle_refresh_probes,
    "recheck_health": _handle_recheck_health,
    "mark_manual_followup": _handle_mark_manual_followup,
    "export_evidence": _handle_export_evidence,
}
