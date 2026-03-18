"""Blocker analyzer — execution blocker taxonomy and grouping."""

from collections import Counter, defaultdict
from trading_watchdog.models.verdict import Verdict


BLOCKER_LABELS = {
    "insufficient_margin": "Margin limited",
    "opening_margin_reserve": "Reserve limited",
    "qty_below_min": "Min qty",
    "notional_below_min": "Min notional",
    "position_cap_hit": "Position cap",
    "loss_budget_blocked": "Loss budget",
    "breakout_invalidation": "Breakout guard",
    "session_blocked": "Session blocked",
    "stall_blocked": "Stall guard",
    "opening_blocked": "Opening blocked",
    "reconciliation_diverged": "Reconciliation",
    "exchange_truth_stale": "Exchange stale",
    "exchange_state_untrusted": "State untrusted",
    "stale_runtime_blocker": "Stale blocker",
    "stale_balance": "Stale balance",
    "stale_snapshot": "Stale snapshot",
}

BUCKET_LABELS = {
    "viable": "Viable",
    "margin_limited": "Margin limited",
    "size_limited": "Size limited",
    "position_capped": "Position capped",
    "state_untrusted": "State untrusted",
    "blocked": "Blocked",
}


def analyze_blockers(bots):
    """Group execution blockers by type and identify dominant patterns.

    Returns dict with blocker section data and list of verdicts.
    """
    verdicts = []
    reason_counts = Counter()
    bucket_counts = Counter()
    blocked_bots = []
    blocker_by_symbol = defaultdict(list)

    running_bots = [b for b in bots if b.get("status") in ("running", "paused", "recovering", "flash_crash_paused")]

    for bot in running_bots:
        if not bot.get("execution_blocked"):
            bucket_counts["viable"] += 1
            continue

        reason = bot.get("execution_viability_reason", "unknown")
        bucket = bot.get("execution_viability_bucket", "blocked")
        symbol = bot.get("symbol", "?")
        bot_id = bot.get("id", "?")

        reason_counts[reason] += 1
        bucket_counts[bucket] += 1
        blocker_by_symbol[symbol].append(reason)
        blocked_bots.append({
            "bot_id": bot_id,
            "symbol": symbol,
            "reason": reason,
            "bucket": bucket,
            "margin_limited": bot.get("execution_margin_limited", False),
            "detail": bot.get("execution_viability_reason_text", ""),
        })

    # Top blocker
    top_reason = reason_counts.most_common(1)[0] if reason_counts else ("none", 0)
    top_bucket = bucket_counts.most_common(1)[0] if bucket_counts else ("viable", 0)

    # Verdicts
    margin_blocked = [b for b in blocked_bots if b["margin_limited"]]
    if len(margin_blocked) >= 2:
        verdicts.append(Verdict(
            key="blocker:margin_cluster",
            category="blocker",
            severity="high",
            summary=f"{len(margin_blocked)} bot(s) margin-blocked",
            evidence=[f"{b['symbol']}: {b['reason']}" for b in margin_blocked],
        ))

    capital_starved = [
        b for b in blocked_bots
        if b["reason"] in ("insufficient_margin", "opening_margin_reserve")
    ]
    if len(capital_starved) >= 3:
        verdicts.append(Verdict(
            key="blocker:capital_starvation",
            category="blocker",
            severity="critical",
            summary=f"{len(capital_starved)} bots capital-starved — systemic margin pressure",
            evidence=[f"{b['symbol']}" for b in capital_starved],
        ))

    # Grouped blocker table
    blocker_table = []
    for reason, count in reason_counts.most_common():
        blocker_table.append({
            "reason": reason,
            "label": BLOCKER_LABELS.get(reason, reason.replace("_", " ").title()),
            "count": count,
            "symbols": list({s for s, reasons in blocker_by_symbol.items() if reason in reasons}),
        })

    bucket_table = []
    for bucket in ["viable", "margin_limited", "size_limited", "position_capped", "state_untrusted", "blocked"]:
        count = bucket_counts.get(bucket, 0)
        bucket_table.append({
            "bucket": bucket,
            "label": BUCKET_LABELS.get(bucket, bucket),
            "count": count,
        })

    section_data = {
        "blocked_count": len(blocked_bots),
        "blocked_bots": blocked_bots,
        "blocker_table": blocker_table,
        "bucket_table": bucket_table,
        "top_reason": top_reason[0],
        "top_reason_count": top_reason[1],
        "top_bucket": top_bucket[0],
        "running_checked": len(running_bots),
        "blocker_by_symbol": dict(blocker_by_symbol),
    }

    return section_data, verdicts
