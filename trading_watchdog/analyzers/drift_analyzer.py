"""Drift analyzer — staleness and display-truth drift detection."""

import time
from trading_watchdog.models.verdict import Verdict


def analyze_drift(bots, bridge_meta, risk_state=None):
    """Detect staleness and drift risks.

    Returns dict with drift section data and list of verdicts.
    """
    verdicts = []
    stale_previews = []
    preview_disabled = []
    preview_unavailable = []
    runtime_stale = []
    kill_switch_active = False

    for bot in bots:
        bot_id = bot.get("id", "?")
        symbol = bot.get("symbol", "?")
        reason = bot.get("stable_readiness_reason", "")
        source_kind = bot.get("readiness_source_kind", "")
        status = bot.get("status", "")
        exec_stale = bot.get("execution_viability_stale_data", False)

        if reason == "stale_snapshot" or "stale" in source_kind:
            stale_previews.append({"bot_id": bot_id, "symbol": symbol, "reason": reason, "status": status})

        if reason == "preview_disabled":
            preview_disabled.append({"bot_id": bot_id, "symbol": symbol, "status": status})

        if reason in ("preview_limited", "stopped_preview_unavailable"):
            preview_unavailable.append({"bot_id": bot_id, "symbol": symbol, "reason": reason, "status": status})

        if exec_stale and status in ("running", "paused", "recovering"):
            runtime_stale.append({"bot_id": bot_id, "symbol": symbol})

    # Bridge freshness
    bridge_fresh = bridge_meta.get("fresh", False)
    bridge_age = bridge_meta.get("age_sec", -1)

    if not bridge_fresh and bridge_age > 0:
        verdicts.append(Verdict(
            key="drift:bridge_stale",
            category="drift",
            severity="critical" if bridge_age > 30 else "high",
            summary=f"Runtime bridge stale ({bridge_age:.0f}s old)",
            evidence=[f"bridge_age={bridge_age:.1f}s"],
        ))

    # Risk state drift
    if risk_state and isinstance(risk_state, dict):
        kill_switch_active = risk_state.get("global_kill_switch", False) or risk_state.get("kill_switch_triggered", False)
        if kill_switch_active:
            verdicts.append(Verdict(
                key="drift:kill_switch_active",
                category="drift",
                severity="critical",
                summary="Global kill switch is ACTIVE",
                evidence=["risk_state.global_kill_switch=True"],
            ))

    if stale_previews:
        verdicts.append(Verdict(
            key="drift:stale_previews",
            category="drift",
            severity="low" if len(stale_previews) <= 2 else "medium",
            summary=f"{len(stale_previews)} bot(s) with stale readiness previews",
            evidence=[f"{s['symbol']} ({s['status']})" for s in stale_previews],
        ))

    if runtime_stale:
        verdicts.append(Verdict(
            key="drift:runtime_stale_active",
            category="drift",
            severity="high",
            summary=f"{len(runtime_stale)} running bot(s) with stale execution data",
            evidence=[f"{s['symbol']}" for s in runtime_stale],
        ))

    section_data = {
        "stale_preview_count": len(stale_previews),
        "stale_previews": stale_previews,
        "preview_disabled_count": len(preview_disabled),
        "preview_disabled": preview_disabled,
        "preview_unavailable_count": len(preview_unavailable),
        "preview_unavailable": preview_unavailable,
        "runtime_stale_count": len(runtime_stale),
        "runtime_stale": runtime_stale,
        "bridge_fresh": bridge_fresh,
        "bridge_age_sec": bridge_age,
        "kill_switch_active": kill_switch_active,
    }

    return section_data, verdicts
