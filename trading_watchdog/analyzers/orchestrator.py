"""Analysis orchestrator — runs all analyzers and builds WatchdogSnapshot."""

import logging
from trading_watchdog.config import SEVERITY_PENALTY
from trading_watchdog.models.verdict import WatchdogSnapshot
from trading_watchdog.collectors.bridge_collector import BridgeCollector
from trading_watchdog.collectors.storage_collector import StorageCollector
from trading_watchdog.analyzers.truth_analyzer import analyze_truth
from trading_watchdog.analyzers.readiness_analyzer import analyze_readiness
from trading_watchdog.analyzers.blocker_analyzer import analyze_blockers
from trading_watchdog.analyzers.drift_analyzer import analyze_drift
from trading_watchdog.analyzers.fit_analyzer import analyze_fit
from trading_watchdog.analyzers.funnel_analyzer import analyze_funnel
from trading_watchdog.analyzers.experiment_analyzer import analyze_experiments

log = logging.getLogger("tw.orchestrator")


class AnalysisOrchestrator:
    """Coordinates data collection and analysis."""

    def __init__(self):
        self.bridge = BridgeCollector()
        self.storage = StorageCollector()
        self._last_snapshot = None

    def run(self):
        """Execute full analysis cycle. Returns WatchdogSnapshot."""
        snapshot = WatchdogSnapshot()

        # 1. Collect
        bridge_data = self.bridge.collect()
        storage_data = self.storage.collect_all()

        bridge_meta = self.bridge.get_bridge_meta(bridge_data)
        snapshot.bridge_fresh = bridge_meta.get("fresh", False)
        snapshot.bridge_age_sec = bridge_meta.get("age_sec", -1)
        snapshot.storage_fresh = all(
            v.get("fresh", False) for v in storage_data.values()
            if isinstance(v, dict) and "fresh" in v
        )

        # Extract data
        bots = self.bridge.get_bots_runtime(bridge_data) if bridge_data else []
        positions = self.bridge.get_positions(bridge_data) if bridge_data else {}
        summary = self.bridge.get_summary(bridge_data) if bridge_data else {}

        storage_bots = storage_data.get("bots", {}).get("bots", [])
        risk_state = storage_data.get("risk_state", {}).get("data", {})
        symbol_pnl = storage_data.get("symbol_pnl", {}).get("data", {})
        trade_logs = storage_data.get("trade_logs", {}).get("trades", [])

        # If no bridge bots, try storage bots as fallback (limited data)
        if not bots and storage_bots:
            bots = storage_bots
            log.warning("Using storage bots fallback (bridge unavailable)")

        snapshot.total_bots = len(bots)
        snapshot.running_bots = sum(
            1 for b in bots
            if b.get("status") in ("running", "paused", "recovering", "flash_crash_paused")
        )

        # Account data
        if summary:
            account = summary.get("account", {})
            snapshot.account = {
                "equity": account.get("equity"),
                "available_balance": account.get("available_balance"),
                "unrealized_pnl": account.get("unrealized_pnl"),
                "realized_pnl": account.get("realized_pnl"),
                "daily_loss_pct": summary.get("daily_loss_pct"),
                "kill_switch": summary.get("kill_switch_triggered", False),
                "today_pnl": summary.get("today_pnl", {}),
            }

        # 2. Analyze
        all_verdicts = []

        try:
            truth_data, truth_verdicts = analyze_truth(bots)
            snapshot.truth = truth_data
            all_verdicts.extend(truth_verdicts)
        except Exception as e:
            log.error("Truth analysis failed: %s", e)
            snapshot.truth = {"error": str(e)}

        try:
            readiness_data, readiness_verdicts = analyze_readiness(bots)
            snapshot.readiness = readiness_data
            all_verdicts.extend(readiness_verdicts)
        except Exception as e:
            log.error("Readiness analysis failed: %s", e)
            snapshot.readiness = {"error": str(e)}

        try:
            blocker_data, blocker_verdicts = analyze_blockers(bots)
            snapshot.blockers = blocker_data
            all_verdicts.extend(blocker_verdicts)
        except Exception as e:
            log.error("Blocker analysis failed: %s", e)
            snapshot.blockers = {"error": str(e)}

        try:
            drift_data, drift_verdicts = analyze_drift(bots, bridge_meta, risk_state)
            snapshot.drift = drift_data
            all_verdicts.extend(drift_verdicts)
        except Exception as e:
            log.error("Drift analysis failed: %s", e)
            snapshot.drift = {"error": str(e)}

        try:
            fit_data, fit_verdicts = analyze_fit(bots, symbol_pnl, trade_logs)
            snapshot.symbol_fit = fit_data
            all_verdicts.extend(fit_verdicts)
        except Exception as e:
            log.error("Fit analysis failed: %s", e)
            snapshot.symbol_fit = {"error": str(e)}

        try:
            funnel_data, funnel_verdicts = analyze_funnel(bots, trade_logs)
            snapshot.funnel = funnel_data
            all_verdicts.extend(funnel_verdicts)
        except Exception as e:
            log.error("Funnel analysis failed: %s", e)
            snapshot.funnel = {"error": str(e)}

        try:
            exp_data, exp_verdicts = analyze_experiments(bots, trade_logs)
            snapshot.experiments = exp_data
            all_verdicts.extend(exp_verdicts)
        except Exception as e:
            log.error("Experiment analysis failed: %s", e)
            snapshot.experiments = {"error": str(e)}

        # 3. Finalize
        snapshot.verdicts = sorted(all_verdicts, key=lambda v: v.severity_rank)
        snapshot.compute_health(SEVERITY_PENALTY)

        # Build overview
        snapshot.overview = self._build_overview(snapshot)

        self._last_snapshot = snapshot
        return snapshot

    def _build_overview(self, snap):
        """Build compact overview from all sections."""
        blocker_count = snap.blockers.get("blocked_count", 0)
        top_blocker = snap.blockers.get("top_reason", "none")
        setup_blocked = snap.readiness.get("setup_ready_blocked", 0)
        poor_fit = snap.symbol_fit.get("poor_fit_count", 0)
        repeat_fail = snap.symbol_fit.get("repeat_blocked_count", 0)
        drift_count = (
            snap.drift.get("stale_preview_count", 0) +
            snap.drift.get("runtime_stale_count", 0)
        )

        return {
            "health_score": snap.health_score,
            "health_label": snap.health_label,
            "total_bots": snap.total_bots,
            "running_bots": snap.running_bots,
            "setup_ready_blocked": setup_blocked,
            "top_blocker": top_blocker,
            "blocker_count": blocker_count,
            "poor_fit_count": poor_fit,
            "repeat_fail_count": repeat_fail,
            "drift_risk_count": drift_count,
            "verdict_count": len(snap.verdicts),
            "critical_count": sum(1 for v in snap.verdicts if v.severity == "critical"),
            "high_count": sum(1 for v in snap.verdicts if v.severity == "high"),
        }

    @property
    def last_snapshot(self):
        return self._last_snapshot
