"""Log pattern definitions for incident detection."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class LogPattern:
    key: str
    regex: str
    severity: str  # critical, high, medium, low
    category: str  # process, execution, risk, latency, api, stream, storage
    component: str  # runner, trader, bridge, stream, bybit, storage
    summary_template: str
    cooldown_sec: float = 60.0
    auto_resolve_sec: float = 300.0


PATTERNS: list[LogPattern] = [
    LogPattern(
        key="unhandled_main_loop",
        regex=r"Unhandled error in main loop: (.+)",
        severity="critical",
        category="process",
        component="runner",
        summary_template="Unhandled error in runner main loop",
        cooldown_sec=60,
        auto_resolve_sec=600,
    ),
    LogPattern(
        key="cycle_sla_breach",
        regex=r"Cycle SLA breach #(\d+) \((\d+\.?\d*)s",
        severity="high",
        category="latency",
        component="runner",
        summary_template="Runner cycle SLA breach",
        cooldown_sec=120,
        auto_resolve_sec=300,
    ),
    LogPattern(
        key="bot_error_state",
        regex=r"Persisted bot error state after cycle exception",
        severity="high",
        category="execution",
        component="runner",
        summary_template="Bot persisted to error state after exception",
        cooldown_sec=60,
        auto_resolve_sec=600,
    ),
    LogPattern(
        key="order_router_failed",
        regex=r"\[(\S+)\] Order router action failed",
        severity="high",
        category="execution",
        component="runner",
        summary_template="Order router action failed",
        cooldown_sec=60,
        auto_resolve_sec=300,
    ),
    LogPattern(
        key="margin_exception",
        regex=r"MarginMonitor add-margin exception",
        severity="high",
        category="risk",
        component="runner",
        summary_template="Margin monitor add-margin exception",
        cooldown_sec=120,
        auto_resolve_sec=600,
    ),
    LogPattern(
        key="order_router_timeout",
        regex=r"ORDER_ROUTER_TIMEOUT_RESOLVED",
        severity="medium",
        category="execution",
        component="runner",
        summary_template="Order router timeout resolved",
        cooldown_sec=30,
        auto_resolve_sec=180,
    ),
    LogPattern(
        key="snapshot_timeout",
        regex=r"Dashboard snapshot timeout for (\S+)",
        severity="medium",
        category="api",
        component="trader",
        summary_template="Dashboard snapshot timeout",
        cooldown_sec=60,
        auto_resolve_sec=180,
    ),
    LogPattern(
        key="snapshot_error",
        regex=r"Dashboard snapshot error for (\S+)",
        severity="medium",
        category="api",
        component="trader",
        summary_template="Dashboard snapshot error",
        cooldown_sec=60,
        auto_resolve_sec=180,
    ),
    LogPattern(
        key="cache_lock_timeout",
        regex=r"cache_lock timed out",
        severity="medium",
        category="storage",
        component="storage",
        summary_template="Bot storage cache_lock contention",
        cooldown_sec=30,
        auto_resolve_sec=120,
    ),
    LogPattern(
        key="request_timeout",
        regex=r"Request timeout",
        severity="medium",
        category="latency",
        component="bybit",
        summary_template="Bybit API request timeout",
        cooldown_sec=30,
        auto_resolve_sec=120,
    ),
    LogPattern(
        key="recv_window",
        regex=r"recv_window|timestamp.*ahead|timestamp.*behind",
        severity="medium",
        category="latency",
        component="bybit",
        summary_template="Bybit recv_window / clock skew error",
        cooldown_sec=60,
        auto_resolve_sec=180,
    ),
    LogPattern(
        key="ws_disconnect",
        regex=r"ping/pong timed out|connection reset|WebSocket.*closed|stream.*reconnect",
        severity="medium",
        category="stream",
        component="stream",
        summary_template="WebSocket stream disconnection",
        cooldown_sec=30,
        auto_resolve_sec=120,
    ),
]
