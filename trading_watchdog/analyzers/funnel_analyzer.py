"""Funnel analyzer — opportunity funnel from watch to execution."""

from collections import Counter
from trading_watchdog.models.verdict import Verdict


def analyze_funnel(bots, trade_logs=None):
    """Build opportunity funnel rollup.

    Returns dict with funnel section data and list of verdicts.
    """
    verdicts = []

    running = [b for b in bots if b.get("status") in ("running", "paused", "recovering", "flash_crash_paused")]

    stages = Counter()
    exec_blocked_at_stage = Counter()
    blocker_reasons = Counter()
    has_position = 0

    for bot in running:
        stage = bot.get("stable_readiness_stage", "unknown")
        stages[stage] += 1

        if bot.get("execution_blocked"):
            exec_blocked_at_stage[stage] += 1
            reason = bot.get("execution_viability_reason", "unknown")
            blocker_reasons[reason] += 1

        pos_val = bot.get("position_value", 0) or 0
        if pos_val > 0:
            has_position += 1

    # Funnel stages
    funnel = {
        "watch": stages.get("watch", 0),
        "armed": stages.get("armed", 0),
        "trigger_ready": stages.get("trigger_ready", 0),
        "late": stages.get("late", 0),
        "blocked": stages.get("blocked", 0),
        "executing": has_position,
        "total_running": len(running),
    }

    # Blocked at each stage
    blocked_at = {
        "watch": exec_blocked_at_stage.get("watch", 0),
        "armed": exec_blocked_at_stage.get("armed", 0),
        "trigger_ready": exec_blocked_at_stage.get("trigger_ready", 0),
    }

    top_blocker = blocker_reasons.most_common(1)
    top_blocker_reason = top_blocker[0][0] if top_blocker else "none"
    top_blocker_count = top_blocker[0][1] if top_blocker else 0

    # Conversion rates (safe division)
    total_running = len(running) or 1
    funnel_rates = {
        "watch_pct": round(funnel["watch"] / total_running * 100, 1),
        "armed_pct": round(funnel["armed"] / total_running * 100, 1),
        "trigger_pct": round(funnel["trigger_ready"] / total_running * 100, 1),
        "executing_pct": round(has_position / total_running * 100, 1),
        "blocked_pct": round(sum(exec_blocked_at_stage.values()) / total_running * 100, 1),
    }

    # Verdicts
    total_blocked = sum(exec_blocked_at_stage.values())
    if total_blocked > 0 and total_blocked >= len(running) * 0.5:
        verdicts.append(Verdict(
            key="funnel:majority_blocked",
            category="funnel",
            severity="high",
            summary=f"{total_blocked}/{len(running)} running bots execution-blocked ({funnel_rates['blocked_pct']}%)",
            evidence=[f"top_blocker={top_blocker_reason} ({top_blocker_count}x)"],
        ))

    if funnel["trigger_ready"] > 0 and blocked_at["trigger_ready"] == funnel["trigger_ready"]:
        verdicts.append(Verdict(
            key="funnel:all_trigger_blocked",
            category="funnel",
            severity="critical",
            summary=f"All {funnel['trigger_ready']} trigger-ready bots are execution-blocked",
            evidence=[f"top_blocker={top_blocker_reason}"],
        ))

    if has_position == 0 and len(running) > 0:
        verdicts.append(Verdict(
            key="funnel:zero_executing",
            category="funnel",
            severity="medium" if len(running) < 5 else "high",
            summary=f"0 of {len(running)} running bots have active positions",
            evidence=["No positions open across running fleet"],
        ))

    section_data = {
        "funnel": funnel,
        "funnel_rates": funnel_rates,
        "blocked_at_stage": blocked_at,
        "top_blocker_reason": top_blocker_reason,
        "top_blocker_count": top_blocker_count,
        "blocker_reasons": dict(blocker_reasons.most_common(5)),
    }

    return section_data, verdicts
