"""Verdict and incident model for Trading Watchdog."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


CATEGORIES = ("truth", "readiness", "blocker", "funnel", "fit", "drift", "experiment")
SEVERITIES = ("critical", "high", "medium", "low", "info")


@dataclass
class Verdict:
    """Single watchdog finding."""
    key: str
    category: str  # truth, readiness, blocker, funnel, fit, drift, experiment
    severity: str  # critical, high, medium, low, info
    summary: str
    evidence: list = field(default_factory=list)
    affected_bot_id: Optional[str] = None
    affected_symbol: Optional[str] = None
    freshness_at: str = ""
    status: str = "active"  # active, resolved, stale

    def __post_init__(self):
        if not self.freshness_at:
            self.freshness_at = datetime.now(timezone.utc).isoformat()
        if self.category not in CATEGORIES:
            raise ValueError(f"Invalid category: {self.category}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"Invalid severity: {self.severity}")

    def to_dict(self):
        return asdict(self)

    @property
    def severity_rank(self):
        return SEVERITIES.index(self.severity)


@dataclass
class WatchdogSnapshot:
    """Complete watchdog analysis result."""
    collected_at: str = ""
    bridge_fresh: bool = False
    bridge_age_sec: float = -1
    storage_fresh: bool = False

    # Overview
    health_score: int = 100
    health_label: str = "unknown"
    total_bots: int = 0
    running_bots: int = 0

    # Verdicts
    verdicts: list = field(default_factory=list)

    # Section data
    overview: dict = field(default_factory=dict)
    truth: dict = field(default_factory=dict)
    readiness: dict = field(default_factory=dict)
    blockers: dict = field(default_factory=dict)
    funnel: dict = field(default_factory=dict)
    symbol_fit: dict = field(default_factory=dict)
    drift: dict = field(default_factory=dict)
    experiments: dict = field(default_factory=dict)

    # Account
    account: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.collected_at:
            self.collected_at = datetime.now(timezone.utc).isoformat()

    def compute_health(self, severity_penalty):
        """Compute health score from verdicts."""
        score = 100
        for v in self.verdicts:
            score -= severity_penalty.get(v.severity, 0)
        self.health_score = max(0, min(100, score))
        if self.health_score >= 80:
            self.health_label = "good"
        elif self.health_score >= 60:
            self.health_label = "fair"
        elif self.health_score >= 40:
            self.health_label = "poor"
        else:
            self.health_label = "critical"

    def to_dict(self):
        d = asdict(self)
        d["verdicts"] = [v.to_dict() for v in self.verdicts]
        return d
