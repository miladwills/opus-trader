from __future__ import annotations

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import config.strategy_config as strategy_cfg
from services.audit_diagnostics_service import AuditDiagnosticsService
from services.lock_service import file_lock
from services.performance_baseline_service import PerformanceBaselineService


class WatchdogHubService:
    """Read-only active-state registry and snapshot builder for watchdog diagnostics."""

    _FUNNEL_ACTIVE_STATUSES = {"running", "recovering"}
    _STRUCTURAL_BLOCK_REASONS = {"notional_below_min", "qty_below_min"}
    _FUNNEL_REASON_LABELS = {
        "insufficient_margin": "Margin",
        "opening_margin_reserve": "Reserve",
        "position_cap_hit": "Pos cap",
        "notional_below_min": "Min notional",
        "qty_below_min": "Min qty",
        "structure_gate": "Structure",
        "breakout_invalidation": "Breakout",
        "opening_guard": "Open guard",
        "other": "Other",
    }
    _SEVERITY_ORDER = {
        "CRITICAL": 0,
        "ERROR": 1,
        "WARN": 2,
        "INFO": 3,
    }
    _WATCHDOG_META = {
        "loss_asymmetry": {
            "label": "Loss Asymmetry",
            "explanation": "Flags payoff imbalance where larger losses overwhelm smaller wins.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.LOSS_ASYMMETRY_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                1800,
            ),
        },
        "exit_stack": {
            "label": "Exit Stack",
            "explanation": "Tracks forced exits and weak favorable-capture patterns in recent closes.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.EXIT_STACK_WATCHDOG_WINDOW_SECONDS or 0),
                1800,
            ),
        },
        "small_bot_sizing": {
            "label": "Small-Bot Sizing",
            "explanation": "Shows otherwise-valid setups choked by size, margin, or position-cap pressure.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.SMALL_BOT_SIZING_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                900,
            ),
        },
        "signal_drift": {
            "label": "Signal Drift",
            "explanation": "Detects disagreement between scanner, readiness, runtime blockers, and gate state.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.SIGNAL_DRIFT_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                900,
            ),
        },
        "state_flapping": {
            "label": "State Flapping",
            "explanation": "Highlights unstable actionable/wait or signal-class oscillation.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.STATE_FLAPPING_WATCHDOG_WINDOW_SEC or 0),
                300,
            ),
        },
        "pnl_attribution": {
            "label": "PnL Attribution",
            "explanation": "Surfaces attribution gaps and known fee/funding drag when the data exists.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.PNL_ATTRIBUTION_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                1800,
            ),
        },
        "profit_protection": {
            "label": "Profit Protection",
            "explanation": "Highlights adaptive exit-advisory states and live/shadow profit-protection outcomes.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.PROFIT_PROTECTION_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                900,
            ),
        },
        "order_starvation": {
            "label": "Order Starvation",
            "explanation": "Flags bots with consecutive order placement failures that may be silently starved.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.ORDER_STARVATION_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                600,
            ),
        },
        "position_divergence": {
            "label": "Position Divergence",
            "explanation": "Detects mismatch between persisted position size and exchange truth.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.POSITION_DIVERGENCE_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                300,
            ),
        },
        "sl_failure": {
            "label": "SL Failure",
            "explanation": "Flags repeated stop-loss placement rejections leaving positions unprotected.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.SL_FAILURE_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                600,
            ),
        },
        "fill_slippage": {
            "label": "Fill Slippage",
            "explanation": "Tracks fill price deviation from expected and detects slippage clusters.",
            "active_ttl_sec": lambda: max(
                int(strategy_cfg.FILL_SLIPPAGE_WATCHDOG_COOLDOWN_SEC or 0) * 2,
                900,
            ),
        },
    }
    _CONFIG_VISIBILITY = {
        "loss_asymmetry": [
            ("enabled", "LOSS_ASYMMETRY_WATCHDOG_ENABLED"),
            ("cooldown_sec", "LOSS_ASYMMETRY_WATCHDOG_COOLDOWN_SEC"),
            ("window_trades", "LOSS_ASYMMETRY_WATCHDOG_WINDOW_TRADES"),
            ("min_trades", "LOSS_ASYMMETRY_WATCHDOG_MIN_TRADES"),
            ("warn_payoff_ratio", "LOSS_ASYMMETRY_WATCHDOG_WARN_PAYOFF_RATIO"),
            ("warn_profit_factor", "LOSS_ASYMMETRY_WATCHDOG_WARN_PROFIT_FACTOR"),
        ],
        "exit_stack": [
            ("enabled", "EXIT_STACK_WATCHDOG_ENABLED"),
            ("cooldown_sec", "EXIT_STACK_WATCHDOG_COOLDOWN_SEC"),
            ("window_seconds", "EXIT_STACK_WATCHDOG_WINDOW_SECONDS"),
            ("min_events", "EXIT_STACK_WATCHDOG_MIN_EVENTS"),
            ("warn_forced_exit_share", "EXIT_STACK_WATCHDOG_WARN_FORCED_EXIT_SHARE"),
        ],
        "small_bot_sizing": [
            ("enabled", "SMALL_BOT_SIZING_WATCHDOG_ENABLED"),
            ("cooldown_sec", "SMALL_BOT_SIZING_WATCHDOG_COOLDOWN_SEC"),
        ],
        "signal_drift": [
            ("enabled", "SIGNAL_DRIFT_WATCHDOG_ENABLED"),
            ("cooldown_sec", "SIGNAL_DRIFT_WATCHDOG_COOLDOWN_SEC"),
        ],
        "state_flapping": [
            ("enabled", "STATE_FLAPPING_WATCHDOG_ENABLED"),
            ("cooldown_sec", "STATE_FLAPPING_WATCHDOG_COOLDOWN_SEC"),
            ("window_sec", "STATE_FLAPPING_WATCHDOG_WINDOW_SEC"),
            ("min_changes", "STATE_FLAPPING_WATCHDOG_MIN_CHANGES"),
            ("min_actionable_flips", "STATE_FLAPPING_WATCHDOG_MIN_ACTIONABLE_FLIPS"),
        ],
        "pnl_attribution": [
            ("enabled", "PNL_ATTRIBUTION_WATCHDOG_ENABLED"),
            ("cooldown_sec", "PNL_ATTRIBUTION_WATCHDOG_COOLDOWN_SEC"),
            ("window_trades", "PNL_ATTRIBUTION_WATCHDOG_WINDOW_TRADES"),
            ("min_trades", "PNL_ATTRIBUTION_WATCHDOG_MIN_TRADES"),
            ("warn_unattributed_share", "PNL_ATTRIBUTION_WATCHDOG_WARN_UNATTRIBUTED_SHARE"),
            ("warn_ambiguous_share", "PNL_ATTRIBUTION_WATCHDOG_WARN_AMBIGUOUS_SHARE"),
        ],
        "profit_protection": [
            ("enabled", "PROFIT_PROTECTION_WATCHDOG_ENABLED"),
            ("cooldown_sec", "PROFIT_PROTECTION_WATCHDOG_COOLDOWN_SEC"),
        ],
        "order_starvation": [
            ("enabled", "ORDER_STARVATION_WATCHDOG_ENABLED"),
            ("cooldown_sec", "ORDER_STARVATION_WATCHDOG_COOLDOWN_SEC"),
            ("warn_threshold", "ORDER_STARVATION_WARN_THRESHOLD"),
            ("block_threshold", "ORDER_STARVATION_BLOCK_THRESHOLD"),
        ],
        "position_divergence": [
            ("enabled", "POSITION_DIVERGENCE_WATCHDOG_ENABLED"),
            ("cooldown_sec", "POSITION_DIVERGENCE_WATCHDOG_COOLDOWN_SEC"),
            ("tolerance_pct", "POSITION_DIVERGENCE_TOLERANCE_PCT"),
        ],
        "sl_failure": [
            ("enabled", "SL_FAILURE_WATCHDOG_ENABLED"),
            ("cooldown_sec", "SL_FAILURE_WATCHDOG_COOLDOWN_SEC"),
            ("critical_threshold", "SL_REJECTION_CRITICAL_THRESHOLD"),
        ],
        "fill_slippage": [
            ("enabled", "FILL_SLIPPAGE_WATCHDOG_ENABLED"),
            ("cooldown_sec", "FILL_SLIPPAGE_WATCHDOG_COOLDOWN_SEC"),
            ("warn_bps", "FILL_SLIPPAGE_WARN_BPS"),
            ("cluster_threshold", "FILL_SLIPPAGE_CLUSTER_THRESHOLD"),
        ],
    }

    def __init__(
        self,
        audit_diagnostics_service: Optional[AuditDiagnosticsService] = None,
        file_path: str = "storage/watchdog_active_state.json",
        performance_baseline_service: Optional[PerformanceBaselineService] = None,
    ) -> None:
        self.audit_diagnostics_service = audit_diagnostics_service or AuditDiagnosticsService()
        self.performance_baseline_service = performance_baseline_service
        self.file_path = Path(file_path)
        self.bot_registry_path = self.file_path.with_name("bots.json")
        self.lock_path = Path(str(self.file_path) + ".lock")
        self._state_lock = threading.RLock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.file_path.exists():
            self._write_state(self._default_state())

    @staticmethod
    def enabled() -> bool:
        return bool(
            getattr(strategy_cfg, "WATCHDOG_DIAGNOSTICS_ENABLED", False)
            and getattr(strategy_cfg, "WATCHDOG_HUB_ENABLED", True)
        )

    @staticmethod
    def active_grace_sec() -> int:
        try:
            return max(int(strategy_cfg.WATCHDOG_HUB_ACTIVE_GRACE_SEC or 0), 60)
        except Exception:
            return 600

    @staticmethod
    def recent_window_sec() -> int:
        try:
            return max(int(strategy_cfg.WATCHDOG_HUB_RECENT_WINDOW_SEC or 0), 300)
        except Exception:
            return 14400

    @staticmethod
    def max_recent_events() -> int:
        try:
            return max(int(strategy_cfg.WATCHDOG_HUB_MAX_RECENT_EVENTS or 0), 10)
        except Exception:
            return 40

    @staticmethod
    def resolved_retention_sec() -> int:
        try:
            return max(int(strategy_cfg.WATCHDOG_HUB_RESOLVED_RETENTION_SEC or 0), 600)
        except Exception:
            return 21600

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_ts(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _normalized_severity(cls, value: Any) -> str:
        normalized = str(value or "INFO").strip().upper()
        if normalized not in cls._SEVERITY_ORDER:
            return "INFO"
        return normalized

    @staticmethod
    def _sanitize_scalar(value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, (bool, int, str)) or value is None:
            return value
        return str(value)

    @classmethod
    def _sanitize_mapping(cls, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in dict(payload or {}).items():
            if value is None:
                continue
            if isinstance(value, dict):
                nested = {
                    str(nested_key): cls._sanitize_scalar(nested_value)
                    for nested_key, nested_value in value.items()
                    if nested_value is not None
                }
                if nested:
                    cleaned[str(key)] = nested
            elif isinstance(value, (list, tuple)):
                items = [cls._sanitize_scalar(item) for item in value if item is not None]
                if items:
                    cleaned[str(key)] = items[:12]
            else:
                cleaned[str(key)] = cls._sanitize_scalar(value)
        return cleaned

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "issues": {},
        }

    def _read_state(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            return self._default_state()
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return self._default_state()
        if not isinstance(payload, dict):
            return self._default_state()
        state = self._default_state()
        state.update(payload)
        issues = {}
        for key, value in dict(state.get("issues") or {}).items():
            if isinstance(value, dict):
                issues[str(key)] = dict(value)
        state["issues"] = issues
        return state

    def _write_state(self, state: Dict[str, Any]) -> None:
        payload = dict(state or self._default_state())
        payload["issues"] = dict(payload.get("issues") or {})
        self.file_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _active_key(payload: Dict[str, Any]) -> str:
        return ":".join(
            [
                str(payload.get("watchdog_type") or "unknown").strip().lower() or "unknown",
                str(payload.get("bot_id") or "na").strip() or "na",
                str(payload.get("symbol") or "na").strip().upper() or "na",
                str(payload.get("reason") or "watch").strip().lower() or "watch",
            ]
        )

    @classmethod
    def _runtime_signal_blocker(cls, bot: Dict[str, Any]) -> Optional[str]:
        if bot.get("_capital_starved_block_opening_orders"):
            return str(bot.get("capital_starved_reason") or "capital_starved")
        if bot.get("_small_capital_block_opening_orders"):
            return str(bot.get("last_skip_reason") or "qty_below_min")
        if bot.get("_watchdog_position_cap_active"):
            return "position_cap_hit"
        if bot.get("_breakout_invalidation_block_opening_orders"):
            return "breakout_invalidation"
        return None

    @classmethod
    def _state_flapping_reason_active(cls, bot: Dict[str, Any], reason: str) -> bool:
        history = bot.get("_watchdog_signal_transition_history")
        if not isinstance(history, list):
            return False
        window_sec = max(int(strategy_cfg.STATE_FLAPPING_WATCHDOG_WINDOW_SEC or 0), 30)
        min_changes = max(int(strategy_cfg.STATE_FLAPPING_WATCHDOG_MIN_CHANGES or 0), 3)
        min_actionable_flips = max(int(strategy_cfg.STATE_FLAPPING_WATCHDOG_MIN_ACTIONABLE_FLIPS or 0), 1)
        now_ts = cls._now().timestamp()
        recent = [
            item
            for item in history
            if isinstance(item, dict) and (now_ts - float(item.get("ts") or 0.0)) <= window_sec
        ]
        if len(recent) < min_changes:
            return False
        actionable_flips = 0
        gate_flips = 0
        distinct_signal_count = 0
        distinct_signals = set()
        for index in range(1, len(recent)):
            prev_item = recent[index - 1]
            curr_item = recent[index]
            distinct_signals.add(str(prev_item.get("signal_code") or ""))
            distinct_signals.add(str(curr_item.get("signal_code") or ""))
            if bool(prev_item.get("actionable")) != bool(curr_item.get("actionable")):
                actionable_flips += 1
            if bool(prev_item.get("gate_blocked")) != bool(curr_item.get("gate_blocked")):
                gate_flips += 1
        distinct_signal_count = len([item for item in distinct_signals if item])
        normalized_reason = str(reason or "").strip().lower()
        if normalized_reason == "actionable_wait_flapping":
            return actionable_flips >= min_actionable_flips
        if normalized_reason == "gate_pass_fail_flapping":
            return gate_flips >= min_actionable_flips
        if normalized_reason == "signal_class_flapping":
            return distinct_signal_count >= 3
        return False

    @classmethod
    def _is_issue_active_in_runtime(cls, issue: Dict[str, Any], bot: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(bot, dict):
            return False
        watchdog_type = str(issue.get("watchdog_type") or "").strip().lower()
        reason = str(issue.get("reason") or "").strip().lower()
        runtime_blocker = cls._runtime_signal_blocker(bot)
        entry_status = str(bot.get("entry_ready_status") or "").strip().lower()
        analysis_status = str(bot.get("analysis_ready_status") or "").strip().lower()
        setup_status = str(bot.get("setup_ready_status") or analysis_status).strip().lower()
        live_gate_status = str(bot.get("live_gate_status") or "").strip().lower()
        execution_blocked = bool(bot.get("execution_blocked")) or (
            str(bot.get("execution_viability_status") or "").strip().lower()
            == "blocked"
        )
        execution_reason = str(bot.get("execution_viability_reason") or "").strip().lower()
        gate_blocked = bool(bot.get("_entry_gate_blocked"))
        signal_executable = bool(bot.get("entry_signal_executable"))
        if watchdog_type == "small_bot_sizing":
            if reason == "setup_blocked_by_min_size":
                return runtime_blocker in {"qty_below_min", "notional_below_min"}
            if reason == "valid_setup_blocked_by_margin":
                return runtime_blocker in {"insufficient_margin", "capital_starved"}
            if reason == "position_cap_limiting_exposure":
                return runtime_blocker == "position_cap_hit"
            if reason == "blocked_by_runtime_guard":
                return runtime_blocker == "breakout_invalidation"
            if reason in {"capital_compression_active", "small_bot_pressure"}:
                summary = dict(bot.get("watchdog_bottleneck_summary") or {})
                return bool(summary.get("capital_compression_active"))
            return False
        if watchdog_type == "signal_drift":
            if reason == "scanner_runtime_disagree":
                return bool(bot.get("scanner_recommendation_differs")) and signal_executable
            if reason == "ready_but_runtime_blocked":
                return entry_status == "ready" and bool(runtime_blocker) and not execution_blocked
            if reason == "analysis_runtime_disagree":
                return setup_status != "ready" and entry_status == "ready" and not execution_blocked
            if reason == "signal_executable_but_gate_blocked":
                return signal_executable and gate_blocked
            if reason == "readiness_without_signal_class":
                return entry_status == "ready" and not bot.get("entry_signal_code") and not execution_blocked
            if reason == "blocked_without_runtime_blocker":
                return execution_blocked and not runtime_blocker and not execution_reason and live_gate_status == "on"
            return False
        if watchdog_type == "state_flapping":
            return cls._state_flapping_reason_active(bot, reason)
        if watchdog_type == "profit_protection":
            decision = str(bot.get("profit_protection_decision") or "").strip().lower()
            actionable = bool(bot.get("profit_protection_actionable"))
            shadow_status = str(bot.get("profit_protection_shadow_status") or "").strip().lower()
            if reason == "take_partial_advised":
                return actionable and decision == "take_partial"
            if reason == "exit_now_advised":
                return actionable and decision == "exit_now"
            if reason == "shadow_triggered":
                return shadow_status == "triggered"
            return False
        return False

    @classmethod
    def _is_runtime_watchdog(cls, watchdog_type: str) -> bool:
        return watchdog_type in {
            "small_bot_sizing",
            "signal_drift",
            "state_flapping",
            "profit_protection",
        }

    @staticmethod
    def _active_issue_registry_status(
        issue: Dict[str, Any],
        registry_lookup: Optional[Dict[str, Dict[str, Any]]],
    ) -> str:
        if not isinstance(registry_lookup, dict):
            return "unknown"
        bot_id = str(issue.get("bot_id") or "").strip()
        if not bot_id:
            return "valid"
        bot = registry_lookup.get(bot_id)
        if not isinstance(bot, dict):
            return "missing_bot"
        issue_symbol = str(issue.get("symbol") or "").strip().upper()
        bot_symbol = str(bot.get("symbol") or "").strip().upper()
        if issue_symbol and bot_symbol and issue_symbol != bot_symbol:
            return "symbol_mismatch"
        return "valid"

    def _load_registry_lookup(self) -> Dict[str, Dict[str, Any]]:
        if not self.bot_registry_path.exists():
            return {}
        try:
            payload = json.loads(self.bot_registry_path.read_text(encoding="utf-8") or "[]")
        except Exception:
            return {}
        if not isinstance(payload, list):
            return {}
        return {
            str(bot.get("id") or "").strip(): dict(bot)
            for bot in payload
            if isinstance(bot, dict) and str(bot.get("id") or "").strip()
        }

    @classmethod
    def _watchdog_label(cls, watchdog_type: str) -> str:
        meta = cls._WATCHDOG_META.get(watchdog_type) or {}
        return str(meta.get("label") or watchdog_type.replace("_", " ").title())

    @classmethod
    def _watchdog_explanation(cls, watchdog_type: str) -> str:
        meta = cls._WATCHDOG_META.get(watchdog_type) or {}
        return str(meta.get("explanation") or "")

    @classmethod
    def _active_ttl_sec(cls, watchdog_type: str) -> int:
        meta = cls._WATCHDOG_META.get(watchdog_type) or {}
        resolver = meta.get("active_ttl_sec")
        try:
            return max(int(resolver() if callable(resolver) else resolver or 0), cls.active_grace_sec())
        except Exception:
            return cls.active_grace_sec()

    @staticmethod
    def _derive_blocker_type(payload: Dict[str, Any]) -> Optional[str]:
        metrics = dict(payload.get("compact_metrics") or {})
        runtime_blocker = str(metrics.get("runtime_blocker") or "").strip().lower()
        if runtime_blocker:
            return runtime_blocker
        reason = str(payload.get("reason") or "").strip().lower()
        if "margin" in reason:
            return "insufficient_margin"
        if "cap" in reason:
            return "position_cap_hit"
        if "min_size" in reason or "compression" in reason:
            return "qty_below_min"
        if "drift" in reason:
            return "signal_drift"
        if "flapping" in reason:
            return "state_flapping"
        return None

    @staticmethod
    def _derive_actionable_state(payload: Dict[str, Any]) -> str:
        watchdog_type = str(payload.get("watchdog_type") or "").strip().lower()
        blocker_type = WatchdogHubService._derive_blocker_type(payload)
        if watchdog_type == "small_bot_sizing" and blocker_type:
            return "blocking_execution"
        if watchdog_type == "signal_drift":
            return "contract_mismatch"
        if watchdog_type == "state_flapping":
            return "unstable_runtime_state"
        if watchdog_type == "profit_protection":
            return "review_exit_advisory"
        return "review_recent_window"

    def _resolve_issue(self, issue: Dict[str, Any], now_dt: datetime, reason: str) -> None:
        issue["is_active"] = False
        issue["resolved_at"] = now_dt.isoformat()
        issue["resolution_reason"] = str(reason or "resolved").strip().lower()

    def _prune_state(
        self,
        state: Dict[str, Any],
        now_dt: datetime,
        runtime_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        registry_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        issues = dict(state.get("issues") or {})
        pruned: Dict[str, Any] = {}
        retention_sec = self.resolved_retention_sec()
        for active_key, issue in issues.items():
            if not isinstance(issue, dict):
                continue
            watchdog_type = str(issue.get("watchdog_type") or "").strip().lower()
            last_seen_dt = self._parse_ts(issue.get("last_seen")) or now_dt
            first_seen_dt = self._parse_ts(issue.get("first_seen")) or last_seen_dt
            if bool(issue.get("is_active")):
                age_sec = max((now_dt - last_seen_dt).total_seconds(), 0.0)
                registry_age_sec = max((now_dt - first_seen_dt).total_seconds(), 0.0)
                registry_status = self._active_issue_registry_status(issue, registry_lookup)
                if (
                    registry_status == "missing_bot"
                    and registry_age_sec > self.active_grace_sec()
                ):
                    self._resolve_issue(issue, now_dt, "bot_missing")
                elif (
                    registry_status == "symbol_mismatch"
                    and registry_age_sec > self.active_grace_sec()
                ):
                    self._resolve_issue(issue, now_dt, "bot_symbol_mismatch")
                elif self._is_runtime_watchdog(watchdog_type) and runtime_lookup is not None:
                    bot_id = str(issue.get("bot_id") or "").strip()
                    bot = (runtime_lookup or {}).get(bot_id)
                    if not self._is_issue_active_in_runtime(issue, bot):
                        self._resolve_issue(issue, now_dt, "runtime_cleared")
                elif not self._is_runtime_watchdog(watchdog_type):
                    if age_sec > self._active_ttl_sec(watchdog_type):
                        self._resolve_issue(issue, now_dt, "expired")
            resolved_at_dt = self._parse_ts(issue.get("resolved_at"))
            if resolved_at_dt is not None:
                age_from_resolution = max((now_dt - resolved_at_dt).total_seconds(), 0.0)
                if age_from_resolution > retention_sec:
                    continue
            pruned[str(active_key)] = issue
        state["issues"] = pruned
        state["updated_at"] = now_dt.isoformat()
        return state

    def record_watchdog_event(self, payload: Optional[Dict[str, Any]]) -> bool:
        if not self.enabled() or not isinstance(payload, dict):
            return False
        if str(payload.get("event_type") or "").strip() != "watchdog_event":
            return False
        normalized = {
            "watchdog_type": str(payload.get("watchdog_type") or "").strip().lower() or "unknown",
            "severity": self._normalized_severity(payload.get("severity")),
            "timestamp": str(payload.get("timestamp") or self._now().isoformat()),
            "bot_id": str(payload.get("bot_id") or "").strip() or None,
            "symbol": str(payload.get("symbol") or "").strip().upper() or None,
            "reason": str(payload.get("reason") or "watch").strip().lower() or "watch",
            "compact_metrics": self._sanitize_mapping(payload.get("compact_metrics")),
            "suggested_action": str(payload.get("suggested_action") or "").strip() or None,
            "source_context": self._sanitize_mapping(payload.get("source_context")),
        }
        normalized["active_key"] = self._active_key(normalized)
        normalized["blocker_type"] = self._derive_blocker_type(normalized)
        normalized["actionable_state"] = self._derive_actionable_state(normalized)
        event_dt = self._parse_ts(normalized["timestamp"]) or self._now()
        with self._state_lock:
            with file_lock(self.lock_path, exclusive=True):
                state = self._read_state()
                issue = dict(state.get("issues", {}).get(normalized["active_key"]) or {})
                occurrence_count = int(issue.get("occurrence_count") or 0) + 1
                issue.update(normalized)
                issue["watchdog_label"] = self._watchdog_label(normalized["watchdog_type"])
                issue["first_seen"] = issue.get("first_seen") or event_dt.isoformat()
                issue["last_seen"] = event_dt.isoformat()
                issue["occurrence_count"] = occurrence_count
                issue["is_active"] = True
                issue["resolved_at"] = None
                issue["resolution_reason"] = None
                state.setdefault("issues", {})[normalized["active_key"]] = issue
                state = self._prune_state(state, event_dt)
                self._write_state(state)
        return True

    def sync_runtime_bots(self, runtime_bots: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        if not self.enabled():
            return self._default_state()
        runtime_lookup = None
        if runtime_bots:
            runtime_lookup = {
                str(bot.get("id") or "").strip(): dict(bot)
                for bot in list(runtime_bots or [])
                if isinstance(bot, dict) and str(bot.get("id") or "").strip()
            }
        registry_lookup = runtime_lookup or self._load_registry_lookup()
        now_dt = self._now()
        with self._state_lock:
            with file_lock(self.lock_path, exclusive=True):
                state = self._read_state()
                state = self._prune_state(
                    state,
                    now_dt,
                    runtime_lookup=runtime_lookup,
                    registry_lookup=registry_lookup,
                )
                self._write_state(state)
                return state

    @classmethod
    def _matches_filters(cls, item: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        severity = str(filters.get("severity") or "").strip().upper()
        watchdog_type = str(filters.get("watchdog_type") or "").strip().lower()
        bot_id = str(filters.get("bot_id") or "").strip()
        symbol = str(filters.get("symbol") or "").strip().upper()
        active_only = filters.get("active_only")
        if severity and str(item.get("severity") or "").strip().upper() != severity:
            return False
        if watchdog_type and str(item.get("watchdog_type") or "").strip().lower() != watchdog_type:
            return False
        if bot_id and str(item.get("bot_id") or "").strip() != bot_id:
            return False
        if symbol and str(item.get("symbol") or "").strip().upper() != symbol:
            return False
        if active_only is True and not bool(item.get("is_active")):
            return False
        return True

    def _collect_recent_events(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        audit_service = getattr(self, "audit_diagnostics_service", None)
        if audit_service is None:
            return []
        limit = min(
            max(int(filters.get("recent_limit") or self.max_recent_events()), 1),
            max(self.max_recent_events(), 10),
        )
        recent = audit_service.get_recent_events(
            event_type="watchdog_event",
            since_seconds=max(float(filters.get("recent_window_sec") or self.recent_window_sec()), 60.0),
            bot_id=filters.get("bot_id"),
            symbol=filters.get("symbol"),
            limit=limit,
        )
        normalized: List[Dict[str, Any]] = []
        for item in reversed(recent):
            watchdog_type = str(item.get("watchdog_type") or "").strip().lower()
            payload = {
                "event_key": self._active_key(item),
                "watchdog_type": watchdog_type,
                "watchdog_label": self._watchdog_label(watchdog_type),
                "severity": self._normalized_severity(item.get("severity")),
                "timestamp": item.get("timestamp") or item.get("recorded_at"),
                "bot_id": str(item.get("bot_id") or "").strip() or None,
                "symbol": str(item.get("symbol") or "").strip().upper() or None,
                "reason": str(item.get("reason") or "watch").strip().lower() or "watch",
                "compact_metrics": self._sanitize_mapping(item.get("compact_metrics")),
                "suggested_action": str(item.get("suggested_action") or "").strip() or None,
                "source_context": self._sanitize_mapping(item.get("source_context")),
                "is_active": False,
            }
            if not self._matches_filters(payload, filters):
                continue
            normalized.append(payload)
        return normalized[-limit:]

    def _baseline_dt_for_filters(self, filters: Dict[str, Any]) -> Optional[datetime]:
        service = getattr(self, "performance_baseline_service", None)
        if service is None:
            return None
        bot_id = str(filters.get("bot_id") or "").strip()
        if bot_id:
            return service.get_effective_started_at(bot_id=bot_id)
        return service.get_global_started_at()

    def _apply_baseline_filter(
        self,
        items: List[Dict[str, Any]],
        *,
        baseline_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        if baseline_dt is None:
            return list(items or [])
        filtered: List[Dict[str, Any]] = []
        for item in list(items or []):
            item_dt = (
                self._parse_ts(item.get("timestamp"))
                or self._parse_ts(item.get("last_seen"))
                or self._parse_ts(item.get("first_seen"))
            )
            if item_dt is None or item_dt < baseline_dt:
                continue
            filtered.append(item)
        return filtered

    def reset_scope(self, *, bot_id: Optional[str] = None) -> Dict[str, Any]:
        normalized_bot_id = str(bot_id or "").strip()
        with self._state_lock:
            with file_lock(self.lock_path, exclusive=True):
                state = self._read_state()
                retained = {}
                removed_count = 0
                for active_key, issue in dict(state.get("issues") or {}).items():
                    issue_bot_id = str((issue or {}).get("bot_id") or "").strip()
                    if normalized_bot_id:
                        if issue_bot_id == normalized_bot_id:
                            removed_count += 1
                            continue
                    else:
                        removed_count += 1
                        continue
                    retained[str(active_key)] = issue
                state["issues"] = retained
                state["updated_at"] = self._now().isoformat()
                self._write_state(state)
        return {
            "ok": True,
            "scope": "bot" if normalized_bot_id else "global",
            "bot_id": normalized_bot_id or None,
            "removed_issue_count": removed_count,
        }

    def _build_watchdog_cards(self, active_issues: List[Dict[str, Any]], recent_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cards = []
        active_by_type: Dict[str, List[Dict[str, Any]]] = {}
        for issue in active_issues:
            active_by_type.setdefault(str(issue.get("watchdog_type") or "unknown"), []).append(issue)
        recent_by_type: Dict[str, List[Dict[str, Any]]] = {}
        for event in recent_events:
            recent_by_type.setdefault(str(event.get("watchdog_type") or "unknown"), []).append(event)
        for watchdog_type in self._WATCHDOG_META:
            active_items = active_by_type.get(watchdog_type, [])
            recent_items = recent_by_type.get(watchdog_type, [])
            latest = active_items[0] if active_items else (recent_items[0] if recent_items else None)
            cards.append(
                {
                    "watchdog_type": watchdog_type,
                    "label": self._watchdog_label(watchdog_type),
                    "explanation": self._watchdog_explanation(watchdog_type),
                    "current_status": "ACTIVE" if active_items else ("RECENT" if recent_items else "QUIET"),
                    "active_issue_count": len(active_items),
                    "affected_bots_count": len(
                        {str(item.get("bot_id") or "") for item in active_items if item.get("bot_id")}
                    ),
                    "affected_symbols_count": len(
                        {str(item.get("symbol") or "") for item in active_items if item.get("symbol")}
                    ),
                    "most_recent_trigger": {
                        "timestamp": latest.get("last_seen") if active_items else latest.get("timestamp") if latest else None,
                        "reason": latest.get("reason") if latest else None,
                        "severity": latest.get("severity") if latest else None,
                        "bot_id": latest.get("bot_id") if latest else None,
                        "symbol": latest.get("symbol") if latest else None,
                    },
                    "config": self.get_watchdog_config(watchdog_type),
                }
            )
        return cards

    def get_watchdog_config(self, watchdog_type: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for key, attr_name in self._CONFIG_VISIBILITY.get(str(watchdog_type or "").strip().lower(), []):
            payload[key] = getattr(strategy_cfg, attr_name, None)
        return payload

    def _build_overview(self, active_issues: List[Dict[str, Any]], recent_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        severity_counts = Counter(str(issue.get("severity") or "INFO").strip().upper() for issue in active_issues)
        affected_bots = {str(issue.get("bot_id") or "") for issue in active_issues if issue.get("bot_id")}
        affected_symbols = {str(issue.get("symbol") or "") for issue in active_issues if issue.get("symbol")}
        blocker_counts = Counter(
            str(issue.get("blocker_type") or "warning_only").strip().lower()
            for issue in active_issues
            if issue.get("blocker_type") or issue.get("actionable_state") == "blocking_execution"
        )
        watchdog_counts = Counter(str(issue.get("watchdog_type") or "unknown") for issue in active_issues)
        noisy_watchdogs = Counter(str(event.get("watchdog_type") or "unknown") for event in recent_events)
        top_blocker = blocker_counts.most_common(1)[0][0] if blocker_counts else None
        top_watchdog = watchdog_counts.most_common(1)[0][0] if watchdog_counts else None
        noisy_watchdog = noisy_watchdogs.most_common(1)[0][0] if noisy_watchdogs else top_watchdog
        return {
            "total_active_issues": len(active_issues),
            "active_counts": {
                "critical": int(severity_counts.get("CRITICAL", 0)),
                "high": int(severity_counts.get("ERROR", 0)),
                "medium": int(severity_counts.get("WARN", 0)),
                "low": int(severity_counts.get("INFO", 0)),
            },
            "affected_bots_count": len(affected_bots),
            "affected_symbols_count": len(affected_symbols),
            "top_blocker_category": top_blocker,
            "top_watchdog_category": top_watchdog,
            "most_noisy_watchdog": noisy_watchdog,
            "top_blocker_categories": [
                {"key": key, "count": count} for key, count in blocker_counts.most_common(5)
            ],
            "top_watchdog_categories": [
                {"key": key, "count": count} for key, count in watchdog_counts.most_common(6)
            ],
        }

    def _build_insights(self, active_issues: List[Dict[str, Any]], recent_events: List[Dict[str, Any]]) -> List[str]:
        insights: List[str] = []
        if active_issues:
            blocker_counts = Counter(
                str(issue.get("blocker_type") or "").strip().lower()
                for issue in active_issues
                if issue.get("blocker_type")
            )
            if blocker_counts:
                blocker, _ = blocker_counts.most_common(1)[0]
                insights.append(f"Most common current blocker: {blocker.replace('_', ' ')}")
            symbol_counts = Counter(
                str(issue.get("symbol") or "").strip().upper()
                for issue in active_issues
                if issue.get("symbol")
            )
            if symbol_counts:
                symbol, _ = symbol_counts.most_common(1)[0]
                insights.append(f"Most affected symbol: {symbol}")
        noisy_watchdogs = Counter(str(event.get("watchdog_type") or "unknown") for event in recent_events)
        if noisy_watchdogs:
            watchdog_type, _ = noisy_watchdogs.most_common(1)[0]
            insights.append(f"Most active recent watchdog: {self._watchdog_label(watchdog_type)}")
        return insights[:3]

    @classmethod
    def _runtime_bot_matches_filters(cls, bot: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        if not isinstance(bot, dict):
            return False
        bot_id = str(bot.get("id") or "").strip()
        symbol = str(bot.get("symbol") or "").strip().upper()
        if not bot_id or not symbol or symbol == "AUTO-PILOT":
            return False
        filter_bot_id = str(filters.get("bot_id") or "").strip()
        filter_symbol = str(filters.get("symbol") or "").strip().upper()
        if filter_bot_id and bot_id != filter_bot_id:
            return False
        if filter_symbol and symbol != filter_symbol:
            return False
        return True

    @classmethod
    def _normalize_snapshot_stage(cls, bot: Dict[str, Any]) -> str:
        timing_status = str(
            bot.get("stable_readiness_stage")
            or bot.get("setup_timing_status")
            or ""
        ).strip().lower()
        if timing_status == "trigger_ready":
            return "trigger_ready"
        if timing_status == "armed":
            return "armed"
        if timing_status == "late":
            return "late"
        if bool(
            bot.get("stable_readiness_actionable")
            or bot.get("setup_timing_actionable")
        ):
            return "trigger_ready"
        if bool(
            bot.get("stable_readiness_near_trigger")
            or bot.get("setup_timing_near_trigger")
        ):
            return "armed"
        return "watch"

    @classmethod
    def _blocked_reason_from_event(cls, record: Dict[str, Any]) -> str:
        if not isinstance(record, dict):
            return "other"
        primary_reason = str(record.get("primary_reason") or "").strip().lower()
        skipped_reasons = record.get("skipped_reasons")
        candidates: List[str] = []
        if isinstance(skipped_reasons, dict):
            candidates.extend(
                [
                    str(key or "").strip().lower()
                    for key in skipped_reasons.keys()
                    if str(key or "").strip()
                ]
            )
        if primary_reason:
            candidates.append(primary_reason)
        for candidate in candidates:
            if candidate == "opening_margin_reserve":
                return "opening_margin_reserve"
            if candidate in cls._STRUCTURAL_BLOCK_REASONS:
                return candidate
            if candidate in {"position_cap_hit", "opening_orders_cancelled_by_cap"} or "position_cap" in candidate:
                return "position_cap_hit"
            if candidate in {"insufficient_margin", "capital_starved", "margin_limited"}:
                return "insufficient_margin"
            if "breakout" in candidate:
                return "breakout_invalidation"
            if "structure" in candidate or candidate in {"entry_gate", "structure_gate"}:
                return "structure_gate"
            if "guard" in candidate:
                return "opening_guard"
        return "other"

    @classmethod
    def _blocked_reason_label(cls, reason: str) -> str:
        normalized = str(reason or "").strip().lower() or "other"
        return cls._FUNNEL_REASON_LABELS.get(normalized, cls._FUNNEL_REASON_LABELS["other"])

    @staticmethod
    def _compact_mode_label(mode: Any) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized == "neutral_classic_bybit":
            return "neutral classic"
        return normalized or "unknown"

    @classmethod
    def _build_opportunity_funnel(
        cls,
        runtime_bots: Optional[List[Dict[str, Any]]],
        *,
        filters: Dict[str, Any],
        audit_service: Optional[AuditDiagnosticsService],
        baseline_dt: Optional[datetime],
        fallback_updated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        filtered_bots = [
            dict(bot)
            for bot in list(runtime_bots or [])
            if cls._runtime_bot_matches_filters(bot, filters)
            and str(bot.get("status") or "").strip().lower() in cls._FUNNEL_ACTIVE_STATUSES
        ]

        snapshot_counts = Counter()
        for bot in filtered_bots:
            snapshot_counts[cls._normalize_snapshot_stage(bot)] += 1

        structural_rows = []
        for bot in filtered_bots:
            reason = str(
                bot.get("execution_viability_reason")
                or bot.get("capital_starved_reason")
                or bot.get("last_skip_reason")
                or ""
            ).strip().lower()
            if reason not in cls._STRUCTURAL_BLOCK_REASONS:
                continue
            symbol = str(bot.get("symbol") or "").strip().upper()
            mode = cls._compact_mode_label(bot.get("mode"))
            structural_rows.append(
                {
                    "symbol": symbol or None,
                    "mode": mode,
                    "reason": reason,
                    "reason_label": cls._blocked_reason_label(reason),
                    "label": f"{symbol} · {mode}",
                }
            )
        structural_rows.sort(key=lambda item: (item["symbol"] or "", item["mode"], item["reason"]))

        window_sec = max(int(filters.get("recent_window_sec") or cls.recent_window_sec()), 60)
        executed_events: List[Dict[str, Any]] = []
        blocked_events: List[Dict[str, Any]] = []
        if audit_service is not None:
            executed_events = audit_service.get_recent_events(
                event_type="opening_orders_placed",
                since_seconds=window_sec,
                bot_id=filters.get("bot_id"),
                symbol=filters.get("symbol"),
                limit=400,
            )
            blocked_events = audit_service.get_recent_events(
                event_type="opening_orders_suppressed",
                since_seconds=window_sec,
                bot_id=filters.get("bot_id"),
                symbol=filters.get("symbol"),
                limit=400,
            )
        if baseline_dt is not None and audit_service is not None:
            executed_events = [
                item for item in executed_events if audit_service._get_event_ts(item) >= baseline_dt
            ]
            blocked_events = [
                item for item in blocked_events if audit_service._get_event_ts(item) >= baseline_dt
            ]

        blocker_counts: Counter[str] = Counter()
        failure_rows: Dict[str, Dict[str, Any]] = {}
        for record in blocked_events:
            reason = cls._blocked_reason_from_event(record)
            blocker_counts[reason] += 1
            symbol = str(record.get("symbol") or "").strip().upper() or "UNKNOWN"
            mode = cls._compact_mode_label(record.get("mode"))
            key = f"{symbol} · {mode}"
            row = failure_rows.setdefault(
                key,
                {
                    "symbol": symbol,
                    "mode": mode,
                    "count": 0,
                    "reason_counts": Counter(),
                    "label": key,
                },
            )
            row["count"] += 1
            row["reason_counts"][reason] += 1
        repeat_failures = []
        for row in failure_rows.values():
            top_reason = row["reason_counts"].most_common(1)[0][0] if row["reason_counts"] else "other"
            repeat_failures.append(
                {
                    "symbol": row["symbol"],
                    "mode": row["mode"],
                    "count": int(row["count"] or 0),
                    "reason": top_reason,
                    "reason_label": cls._blocked_reason_label(top_reason),
                    "label": row["label"],
                }
            )
        repeat_failures.sort(key=lambda item: (-item["count"], item["label"]))

        opportunities = len(executed_events) + len(blocked_events)
        conversion_rate = (
            round((len(executed_events) / opportunities) * 100.0, 1)
            if opportunities > 0
            else None
        )
        return {
            "updated_at": fallback_updated_at,
            "snapshot": {
                "watch": int(snapshot_counts.get("watch", 0)),
                "armed": int(snapshot_counts.get("armed", 0)),
                "trigger_ready": int(snapshot_counts.get("trigger_ready", 0)),
                "late": int(snapshot_counts.get("late", 0)),
                "bot_count": len(filtered_bots),
                "included_statuses": sorted(cls._FUNNEL_ACTIVE_STATUSES),
            },
            "follow_through": {
                "window_sec": window_sec,
                "executed": len(executed_events),
                "blocked": len(blocked_events),
                "opportunities": opportunities,
                "trigger_to_execute_rate": conversion_rate,
            },
            "blocked_reasons": [
                {
                    "key": key,
                    "label": cls._blocked_reason_label(key),
                    "count": count,
                }
                for key, count in blocker_counts.most_common(5)
            ],
            "repeat_failures": repeat_failures[:4],
            "structural_untradeable": structural_rows[:4],
        }

    @classmethod
    def _build_experiment_attribution(
        cls,
        *,
        filters: Dict[str, Any],
        audit_service: Optional[AuditDiagnosticsService],
        baseline_dt: Optional[datetime],
        fallback_updated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        window_sec = max(int(filters.get("recent_window_sec") or cls.recent_window_sec()), 60)
        payload = {
            "updated_at": fallback_updated_at,
            "window_sec": window_sec,
            "experiments": [],
            "combinations": [],
            "headline": {
                "most_trigger_ready": None,
                "most_executed": None,
                "most_blocked": None,
                "best_net_pnl": None,
                "worst_net_pnl": None,
            },
        }
        if audit_service is None:
            return payload

        event_types = (
            "entry_signal_state_changed",
            "opening_orders_placed",
            "opening_orders_suppressed",
            "experiment_trade_outcome",
        )
        records: List[Dict[str, Any]] = []
        for event_type in event_types:
            records.extend(
                audit_service.get_recent_events(
                    event_type=event_type,
                    since_seconds=window_sec,
                    bot_id=filters.get("bot_id"),
                    symbol=filters.get("symbol"),
                    limit=300,
                )
            )
        if baseline_dt is not None:
            records = [
                item for item in records if audit_service._get_event_ts(item) >= baseline_dt
            ]

        def _normalized_tags(record: Dict[str, Any]) -> List[str]:
            raw_tags = record.get("experiment_tags")
            values = raw_tags if isinstance(raw_tags, (list, tuple, set)) else [raw_tags]
            tags = []
            for item in values:
                tag = str(item or "").strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
            return sorted(tags)

        def _bucket(store: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
            return store.setdefault(
                key,
                {
                    "key": key,
                    "trigger_ready": 0,
                    "executed_opens": 0,
                    "executed_adds": 0,
                    "executed_total": 0,
                    "blocked": 0,
                    "profit": 0,
                    "loss": 0,
                    "neutral": 0,
                    "net_realized_pnl": 0.0,
                    "outcome_events": 0,
                },
            )

        experiments: Dict[str, Dict[str, Any]] = {}
        combinations: Dict[str, Dict[str, Any]] = {}
        for record in records:
            tags = _normalized_tags(record)
            if not tags:
                continue
            outcome_kind = str(record.get("experiment_outcome_kind") or "").strip().lower()
            event_type = str(record.get("event_type") or "").strip()
            executed_opens = 0
            executed_adds = 0
            blocked = 0
            trigger_ready = 0
            profit = 0
            loss = 0
            neutral = 0
            net_realized_pnl = 0.0
            if event_type == "entry_signal_state_changed" and outcome_kind == "trigger_ready":
                trigger_ready = 1
            elif event_type == "opening_orders_placed" and outcome_kind == "executed":
                executed_opens = max(int(record.get("initial_opening_orders_placed") or 0), 0)
                executed_adds = max(int(record.get("add_follow_through_placed") or 0), 0)
                if executed_opens <= 0 and executed_adds <= 0:
                    executed_opens = max(
                        int(record.get("buy_orders_placed") or 0)
                        + int(record.get("sell_orders_placed") or 0),
                        1,
                    )
            elif event_type == "opening_orders_suppressed" and outcome_kind == "blocked":
                blocked = max(
                    int(record.get("opening_buy_candidates") or 0)
                    + int(record.get("opening_sell_candidates") or 0),
                    1,
                )
            elif event_type == "experiment_trade_outcome":
                realized_pnl = float(record.get("realized_pnl") or 0.0)
                net_realized_pnl = realized_pnl
                if outcome_kind == "profit":
                    profit = 1
                elif outcome_kind == "loss":
                    loss = 1
                else:
                    neutral = 1
            else:
                continue

            combo_key = " + ".join(tags) if len(tags) > 1 else None
            for key in tags:
                row = _bucket(experiments, key)
                row["trigger_ready"] += trigger_ready
                row["executed_opens"] += executed_opens
                row["executed_adds"] += executed_adds
                row["executed_total"] += executed_opens + executed_adds
                row["blocked"] += blocked
                row["profit"] += profit
                row["loss"] += loss
                row["neutral"] += neutral
                row["net_realized_pnl"] = round(
                    float(row.get("net_realized_pnl") or 0.0) + net_realized_pnl,
                    4,
                )
                row["outcome_events"] += profit + loss + neutral
            if combo_key:
                row = _bucket(combinations, combo_key)
                row["trigger_ready"] += trigger_ready
                row["executed_opens"] += executed_opens
                row["executed_adds"] += executed_adds
                row["executed_total"] += executed_opens + executed_adds
                row["blocked"] += blocked
                row["profit"] += profit
                row["loss"] += loss
                row["neutral"] += neutral
                row["net_realized_pnl"] = round(
                    float(row.get("net_realized_pnl") or 0.0) + net_realized_pnl,
                    4,
                )
                row["outcome_events"] += profit + loss + neutral

        experiment_rows = list(experiments.values())
        experiment_rows.sort(
            key=lambda item: (
                -int(item.get("executed_total") or 0),
                -int(item.get("trigger_ready") or 0),
                int(item.get("blocked") or 0),
                str(item.get("key") or ""),
            )
        )
        combination_rows = list(combinations.values())
        combination_rows.sort(
            key=lambda item: (
                -int(item.get("executed_total") or 0),
                -int(item.get("trigger_ready") or 0),
                int(item.get("blocked") or 0),
                str(item.get("key") or ""),
            )
        )
        payload["experiments"] = experiment_rows[:8]
        payload["combinations"] = combination_rows[:6]
        if experiment_rows:
            payload["headline"]["most_trigger_ready"] = max(
                experiment_rows,
                key=lambda item: (int(item.get("trigger_ready") or 0), str(item.get("key") or "")),
            ).get("key")
            payload["headline"]["most_executed"] = max(
                experiment_rows,
                key=lambda item: (int(item.get("executed_total") or 0), str(item.get("key") or "")),
            ).get("key")
            payload["headline"]["most_blocked"] = max(
                experiment_rows,
                key=lambda item: (int(item.get("blocked") or 0), str(item.get("key") or "")),
            ).get("key")
            payload["headline"]["best_net_pnl"] = max(
                experiment_rows,
                key=lambda item: (float(item.get("net_realized_pnl") or 0.0), str(item.get("key") or "")),
            ).get("key")
            payload["headline"]["worst_net_pnl"] = min(
                experiment_rows,
                key=lambda item: (float(item.get("net_realized_pnl") or 0.0), str(item.get("key") or "")),
            ).get("key")
        return payload

    def build_snapshot(
        self,
        *,
        runtime_bots: Optional[List[Dict[str, Any]]] = None,
        filters: Optional[Dict[str, Any]] = None,
        include_registry: bool = False,
    ) -> Dict[str, Any]:
        filters = dict(filters or {})
        active_only = filters.get("active_only")
        if isinstance(active_only, str):
            active_only = active_only.strip().lower() not in {"0", "false", "no"}
        elif active_only is None:
            active_only = False
        filters["active_only"] = bool(active_only)
        if runtime_bots is not None:
            state = self.sync_runtime_bots(runtime_bots)
        else:
            now_dt = self._now()
            registry_lookup = self._load_registry_lookup()
            with self._state_lock:
                with file_lock(self.lock_path, exclusive=True):
                    state = self._read_state()
                    state = self._prune_state(state, now_dt, registry_lookup=registry_lookup)
                    self._write_state(state)
        issues = [dict(item) for item in dict(state.get("issues") or {}).values() if isinstance(item, dict)]
        issues.sort(
            key=lambda item: (
                not bool(item.get("is_active")),
                self._SEVERITY_ORDER.get(str(item.get("severity") or "INFO").upper(), 9),
                -(self._parse_ts(item.get("last_seen")) or self._now()).timestamp(),
                str(item.get("watchdog_type") or ""),
                str(item.get("bot_id") or ""),
            )
        )
        baseline_dt = self._baseline_dt_for_filters(filters)
        filtered_registry = [item for item in issues if self._matches_filters(item, filters)]
        filtered_registry = self._apply_baseline_filter(
            filtered_registry,
            baseline_dt=baseline_dt,
        )
        active_issues = [item for item in filtered_registry if bool(item.get("is_active"))]
        recent_events = self._apply_baseline_filter(
            self._collect_recent_events(filters),
            baseline_dt=baseline_dt,
        )
        experiment_attribution = self._build_experiment_attribution(
            filters=filters,
            audit_service=getattr(self, "audit_diagnostics_service", None),
            baseline_dt=baseline_dt,
            fallback_updated_at=state.get("updated_at"),
        )
        cards = self._build_watchdog_cards(active_issues, recent_events)
        bots = sorted(
            {
                str(item.get("bot_id") or "")
                for item in filtered_registry + recent_events
                if item.get("bot_id")
            }
        )
        symbols = sorted(
            {
                str(item.get("symbol") or "")
                for item in filtered_registry + recent_events
                if item.get("symbol")
            }
        )
        opportunity_funnel = self._build_opportunity_funnel(
            runtime_bots,
            filters=filters,
            audit_service=getattr(self, "audit_diagnostics_service", None),
            baseline_dt=baseline_dt,
            fallback_updated_at=state.get("updated_at"),
        )
        opportunity_funnel["experiment_breakdown"] = list(
            experiment_attribution.get("experiments") or []
        )
        opportunity_funnel["experiment_combinations"] = list(
            experiment_attribution.get("combinations") or []
        )
        payload = {
            "updated_at": state.get("updated_at"),
            "overview": self._build_overview(active_issues, recent_events),
            "active_issues": active_issues,
            "recent_events": recent_events,
            "opportunity_funnel": opportunity_funnel,
            "experiment_attribution": experiment_attribution,
            "watchdog_cards": cards,
            "watchdog_configs": {
                watchdog_type: self.get_watchdog_config(watchdog_type)
                for watchdog_type in self._WATCHDOG_META
            },
            "available_filters": {
                "severities": ["CRITICAL", "ERROR", "WARN", "INFO"],
                "watchdog_types": list(self._WATCHDOG_META.keys()),
                "bots": bots,
                "symbols": symbols,
            },
            "active_registry_counts": {
                "active": len([item for item in issues if item.get("is_active")]),
                "resolved_recent": len([item for item in issues if not item.get("is_active")]),
            },
            "insights": self._build_insights(active_issues, recent_events),
            "config": {
                "enabled": self.enabled(),
                "active_grace_sec": self.active_grace_sec(),
                "recent_window_sec": self.recent_window_sec(),
                "max_recent_events": self.max_recent_events(),
                "resolved_retention_sec": self.resolved_retention_sec(),
                "baseline_started_at": baseline_dt.isoformat() if baseline_dt else None,
            },
        }
        if include_registry:
            payload["issue_registry"] = filtered_registry
        return payload
