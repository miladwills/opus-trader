"""Readiness analyzer — stage distribution and readiness metrics."""

from collections import Counter
from trading_watchdog.models.verdict import Verdict


STAGE_ORDER = ["trigger_ready", "armed", "watch", "late", "blocked"]


def analyze_readiness(bots):
    """Compute readiness stage distribution and metrics.

    Returns dict with readiness section data and list of verdicts.
    """
    verdicts = []
    stage_counts = Counter()
    actionable_count = 0
    near_trigger_count = 0
    late_count = 0
    no_stage_count = 0

    running_bots = [b for b in bots if b.get("status") in ("running", "paused", "recovering", "flash_crash_paused")]
    stopped_bots = [b for b in bots if b.get("status") in ("stopped", "risk_stopped", "error")]

    for bot in bots:
        stage = bot.get("stable_readiness_stage", "")
        if stage:
            stage_counts[stage] += 1
        else:
            no_stage_count += 1

        if bot.get("stable_readiness_actionable"):
            actionable_count += 1
        if bot.get("stable_readiness_near_trigger"):
            near_trigger_count += 1
        if bot.get("stable_readiness_late"):
            late_count += 1

    # Build ordered distribution
    distribution = []
    for stage in STAGE_ORDER:
        count = stage_counts.get(stage, 0)
        distribution.append({"stage": stage, "count": count})
    # Add any stages not in STAGE_ORDER
    for stage, count in stage_counts.items():
        if stage not in STAGE_ORDER:
            distribution.append({"stage": stage, "count": count})

    # Verdicts
    blocked_armed = [
        b for b in running_bots
        if b.get("stable_readiness_stage") == "armed"
        and b.get("execution_blocked")
    ]
    if blocked_armed:
        verdicts.append(Verdict(
            key="readiness:armed_but_blocked",
            category="readiness",
            severity="high",
            summary=f"{len(blocked_armed)} bot(s) armed but execution-blocked",
            evidence=[f"{b.get('symbol')}: {b.get('execution_viability_reason', '?')}" for b in blocked_armed],
        ))

    trigger_blocked = [
        b for b in running_bots
        if b.get("stable_readiness_stage") == "trigger_ready"
        and b.get("execution_blocked")
    ]
    if trigger_blocked:
        verdicts.append(Verdict(
            key="readiness:trigger_ready_but_blocked",
            category="readiness",
            severity="critical",
            summary=f"{len(trigger_blocked)} bot(s) trigger-ready but execution-blocked",
            evidence=[f"{b.get('symbol')}: {b.get('execution_viability_reason', '?')}" for b in trigger_blocked],
        ))

    if late_count > 0:
        verdicts.append(Verdict(
            key="readiness:late_entries",
            category="readiness",
            severity="medium",
            summary=f"{late_count} bot(s) in late readiness stage",
            evidence=[f"{b.get('symbol')}" for b in bots if b.get("stable_readiness_late")],
        ))

    section_data = {
        "distribution": distribution,
        "stage_counts": dict(stage_counts),
        "actionable_count": actionable_count,
        "near_trigger_count": near_trigger_count,
        "late_count": late_count,
        "no_stage_count": no_stage_count,
        "running_count": len(running_bots),
        "stopped_count": len(stopped_bots),
        "total": len(bots),
        "setup_ready_blocked": len(blocked_armed) + len(trigger_blocked),
    }

    return section_data, verdicts
