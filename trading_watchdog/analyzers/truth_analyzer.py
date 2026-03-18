"""Truth analyzer — detects display/readiness truth mismatches."""

from trading_watchdog.models.verdict import Verdict


def analyze_truth(bots):
    """Check readiness truth alignment across all bots.

    Returns dict with truth section data and list of verdicts.
    """
    verdicts = []
    score_stage_mismatches = []
    null_score_bots = []
    stability_issues = []
    hard_invalidated = []

    for bot in bots:
        bot_id = bot.get("id", "?")
        symbol = bot.get("symbol", "?")
        stage = bot.get("stable_readiness_stage", "")
        score = bot.get("display_readiness_score")
        reason = bot.get("stable_readiness_reason", "")
        stability_state = bot.get("readiness_stability_state", "")
        is_hard_inv = bot.get("readiness_hard_invalidated", False)
        flip_suppressed = bot.get("readiness_flip_suppressed", False)
        status = bot.get("status", "")

        # Null score tracking
        if score is None:
            null_score_bots.append({
                "bot_id": bot_id,
                "symbol": symbol,
                "stage": stage,
                "reason": reason,
                "status": status,
            })

        # Score shown for non-actionable blocked/late stages
        if score is not None and stage in ("blocked", "late"):
            score_stage_mismatches.append({
                "bot_id": bot_id,
                "symbol": symbol,
                "stage": stage,
                "score": score,
            })
            verdicts.append(Verdict(
                key=f"truth:score_stage_mismatch:{bot_id}",
                category="truth",
                severity="high",
                summary=f"Score {score} displayed for {stage} bot {symbol}",
                evidence=[f"stage={stage}, score={score}, reason={reason}"],
                affected_bot_id=bot_id,
                affected_symbol=symbol,
            ))

        # Score present for score-clear reasons
        score_clear_reasons = {
            "preview_disabled", "preview_limited", "stale_snapshot",
            "stop_cleanup_pending", "stopped_preview_unavailable",
        }
        if score is not None and reason in score_clear_reasons:
            score_stage_mismatches.append({
                "bot_id": bot_id,
                "symbol": symbol,
                "stage": stage,
                "score": score,
                "reason": reason,
            })
            verdicts.append(Verdict(
                key=f"truth:score_clear_violation:{bot_id}",
                category="truth",
                severity="high",
                summary=f"Score {score} shown despite {reason} for {symbol}",
                evidence=[f"reason={reason} should clear score, but score={score}"],
                affected_bot_id=bot_id,
                affected_symbol=symbol,
            ))

        # Hard invalidated tracking
        if is_hard_inv:
            hard_invalidated.append({
                "bot_id": bot_id,
                "symbol": symbol,
                "reason": reason,
            })

        # Stability issues (stuck in promoting/holding)
        if stability_state in ("promoting", "holding"):
            stability_issues.append({
                "bot_id": bot_id,
                "symbol": symbol,
                "state": stability_state,
                "flip_suppressed": flip_suppressed,
            })

    section_data = {
        "score_stage_mismatch_count": len(score_stage_mismatches),
        "score_stage_mismatches": score_stage_mismatches,
        "null_score_count": len(null_score_bots),
        "null_score_bots": null_score_bots,
        "stability_issue_count": len(stability_issues),
        "stability_issues": stability_issues,
        "hard_invalidated_count": len(hard_invalidated),
        "hard_invalidated": hard_invalidated,
        "total_checked": len(bots),
    }

    return section_data, verdicts
