"""Experiment analyzer — experiment attribution rollups if available."""

from collections import Counter, defaultdict
from trading_watchdog.models.verdict import Verdict


def analyze_experiments(bots, trade_logs=None):
    """Analyze experiment attribution if present.

    Returns dict with experiment section data and list of verdicts.
    Signal is marked unavailable if no experiment attribution exists.
    """
    verdicts = []
    experiment_bots = []
    tag_counts = Counter()
    tag_outcomes = defaultdict(lambda: {"count": 0, "blocked": 0, "with_position": 0})

    has_experiment_data = False

    for bot in bots:
        exp_tags = bot.get("runtime_experiment_tags") or bot.get("experiment_tags") or []
        exp_state = bot.get("experiment_attribution_state", "none")

        if exp_state == "present" or exp_tags:
            has_experiment_data = True
            experiment_bots.append({
                "bot_id": bot.get("id", "?"),
                "symbol": bot.get("symbol", "?"),
                "tags": exp_tags,
                "blocked": bot.get("execution_blocked", False),
                "has_position": (bot.get("position_value", 0) or 0) > 0,
            })
            for tag in exp_tags:
                tag_counts[tag] += 1
                tag_outcomes[tag]["count"] += 1
                if bot.get("execution_blocked"):
                    tag_outcomes[tag]["blocked"] += 1
                if (bot.get("position_value", 0) or 0) > 0:
                    tag_outcomes[tag]["with_position"] += 1

    if not has_experiment_data:
        return {
            "available": False,
            "note": "No experiment attribution data found in current bots",
            "experiment_count": 0,
        }, verdicts

    # Build tag summary
    tag_summary = []
    for tag, count in tag_counts.most_common():
        outcomes = tag_outcomes[tag]
        tag_summary.append({
            "tag": tag,
            "count": count,
            "blocked": outcomes["blocked"],
            "with_position": outcomes["with_position"],
        })

    # Verdicts for experiments with high block rate
    for tag_info in tag_summary:
        if tag_info["count"] >= 2 and tag_info["blocked"] >= tag_info["count"] * 0.5:
            verdicts.append(Verdict(
                key=f"experiment:high_block_rate:{tag_info['tag']}",
                category="experiment",
                severity="medium",
                summary=f"Experiment '{tag_info['tag']}': {tag_info['blocked']}/{tag_info['count']} blocked",
                evidence=[f"block_rate={tag_info['blocked']}/{tag_info['count']}"],
            ))

    section_data = {
        "available": True,
        "experiment_count": len(experiment_bots),
        "experiment_bots": experiment_bots,
        "tag_summary": tag_summary,
        "tag_counts": dict(tag_counts),
    }

    return section_data, verdicts
