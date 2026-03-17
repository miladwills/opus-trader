"""Data models for Platform Watchdog."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProbeResult:
    probe_name: str
    timestamp: float
    success: bool
    latency_ms: float
    status: str  # ok, degraded, down, timeout, error
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Incident:
    incident_id: str
    opened_at: float
    severity: str  # critical, high, medium, low
    category: str  # process, execution, risk, latency, api, stream, storage
    component: str  # runner, trader, bridge, stream, bybit, storage
    pattern_key: str | None
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    status: str = "open"  # open, acknowledged, resolved, auto_resolved
    closed_at: float | None = None
    hit_count: int = 1
    probe_name: str | None = None


@dataclass
class HealthSnapshot:
    timestamp: float
    overall_score: float
    overall_status: str  # healthy, degraded, unhealthy, critical
    components: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class LatencySample:
    probe_name: str
    timestamp: float
    latency_ms: float
    endpoint: str | None = None
    status_code: int | None = None
