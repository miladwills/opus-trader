"""Health scoring: combines probe results into per-component and overall scores."""

from __future__ import annotations
import logging
import time
from ..models import HealthSnapshot
from ..storage.repo import Repository

logger = logging.getLogger("watchdog.scorer")

COMPONENT_WEIGHTS = {
    "runner_process": 0.25,
    "trader_process": 0.15,
    "bridge_health": 0.25,
    "api_latency": 0.15,
    "error_rate": 0.20,
}

SEVERITY_PENALTY = {
    "critical": 30,
    "high": 15,
    "medium": 5,
    "low": 2,
}


def _status_from_score(score: float) -> str:
    if score >= 90:
        return "healthy"
    elif score >= 70:
        return "degraded"
    elif score >= 40:
        return "unhealthy"
    else:
        return "critical"


class HealthScorer:
    def __init__(self, repo: Repository):
        self._repo = repo

    async def compute(self) -> HealthSnapshot:
        components: dict[str, dict] = {}

        # 1. Runner process health
        runner_score = await self._score_runner()
        components["runner_process"] = runner_score

        # 2. Trader process health
        trader_score = await self._score_trader()
        components["trader_process"] = trader_score

        # 3. Bridge health
        bridge_score = await self._score_bridge()
        components["bridge_health"] = bridge_score

        # 4. API latency
        latency_score = await self._score_latency()
        components["api_latency"] = latency_score

        # 5. Error rate
        error_score = await self._score_errors()
        components["error_rate"] = error_score

        overall = sum(
            components[k]["score"] * COMPONENT_WEIGHTS[k]
            for k in COMPONENT_WEIGHTS
        )
        overall = round(max(0, min(100, overall)), 1)

        snap = HealthSnapshot(
            timestamp=time.time(),
            overall_score=overall,
            overall_status=_status_from_score(overall),
            components=components,
        )
        await self._repo.store_health_snapshot(snap)
        return snap

    async def _score_runner(self) -> dict:
        probes = await self._repo.get_all_latest_probes()
        score = 100.0
        details = {}

        # Systemd check
        proc = probes.get("proc_runner")
        if proc:
            details["systemd"] = proc.status
            if proc.status != "ok":
                score -= 50
        else:
            score -= 25
            details["systemd"] = "no_data"

        # Lock file check
        lock = probes.get("file_runner_lock")
        if lock:
            details["lock"] = lock.status
            if lock.status != "ok":
                score -= 30
        else:
            score -= 15
            details["lock"] = "no_data"

        # Log freshness
        logs = probes.get("file_log_fresh")
        if logs:
            runner_age = logs.detail.get("runner_age", 999)
            details["log_age_sec"] = runner_age
            if runner_age > 120:
                score -= 20
            elif runner_age > 60:
                score -= 10
        else:
            details["log_age_sec"] = None

        score = max(0, min(100, score))
        return {"score": score, "status": _status_from_score(score), **details}

    async def _score_trader(self) -> dict:
        probes = await self._repo.get_all_latest_probes()
        score = 100.0
        details = {}

        proc = probes.get("proc_trader")
        if proc:
            details["systemd"] = proc.status
            if proc.status != "ok":
                score -= 60
        else:
            score -= 30
            details["systemd"] = "no_data"

        bootstrap = probes.get("http_bootstrap")
        if bootstrap:
            details["bootstrap"] = bootstrap.status
            if bootstrap.status == "timeout":
                score -= 40
            elif bootstrap.status in ("error", "down"):
                score -= 50
            elif bootstrap.status == "degraded":
                score -= 15
        else:
            score -= 20
            details["bootstrap"] = "no_data"

        score = max(0, min(100, score))
        return {"score": score, "status": _status_from_score(score), **details}

    async def _score_bridge(self) -> dict:
        probes = await self._repo.get_all_latest_probes()
        score = 100.0
        details = {}

        diag = probes.get("http_bridge_diag")
        if diag and diag.success:
            details["producer_alive"] = diag.detail.get("producer_alive", False)
            if not details["producer_alive"]:
                score -= 50
            stale_count = diag.detail.get("stale_count", 0)
            total = diag.detail.get("total_sections", 6)
            details["stale_count"] = stale_count
            details["total_sections"] = total
            if total > 0:
                stale_ratio = stale_count / total
                score -= stale_ratio * 50
        else:
            # Try file probe fallback
            file_probe = probes.get("file_bridge")
            if file_probe and file_probe.success:
                details["source"] = "file_probe"
                details["stale_count"] = file_probe.detail.get("stale_count", 0)
                bridge_age = file_probe.detail.get("bridge_age_sec", 999)
                if bridge_age > 30:
                    score -= 60
                elif bridge_age > 15:
                    score -= 30
            else:
                score -= 70
                details["source"] = "no_data"

        score = max(0, min(100, score))
        return {"score": score, "status": _status_from_score(score), **details}

    async def _score_latency(self) -> dict:
        samples = await self._repo.get_recent_latencies("http_bootstrap", window_sec=300)
        if not samples:
            return {"score": 50, "status": "degraded", "p50": None, "p95": None, "sample_count": 0}
        samples_sorted = sorted(samples)
        p50 = samples_sorted[len(samples_sorted) // 2]
        p95_idx = int(len(samples_sorted) * 0.95)
        p95 = samples_sorted[min(p95_idx, len(samples_sorted) - 1)]
        # Score: 100 if p95 < 2000ms, linear degrade to 0 at p95 > 10000ms
        if p95 <= 2000:
            score = 100.0
        elif p95 >= 10000:
            score = 0.0
        else:
            score = 100 - ((p95 - 2000) / 8000) * 100
        score = max(0, min(100, score))
        return {
            "score": round(score, 1),
            "status": _status_from_score(score),
            "p50": round(p50, 0),
            "p95": round(p95, 0),
            "sample_count": len(samples),
        }

    async def _score_errors(self) -> dict:
        counts = await self._repo.count_open_incidents_by_severity()
        score = 100.0
        for severity, count in counts.items():
            penalty = SEVERITY_PENALTY.get(severity, 5)
            score -= penalty * count
        score = max(0, min(100, score))
        return {
            "score": round(score, 1),
            "status": _status_from_score(score),
            "open_counts": counts,
        }
