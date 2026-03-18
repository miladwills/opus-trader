import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from tempfile import gettempdir, mkstemp
from typing import Any, Dict, List, Optional

from config.strategy_config import (
    AUDIT_DIAGNOSTICS_ENABLED,
    AUDIT_DIAGNOSTICS_EVENT_THROTTLE_SEC,
    AUDIT_DIAGNOSTICS_HEALTH_WINDOW_SEC,
    AUDIT_DIAGNOSTICS_RECENT_EVENT_LIMIT,
    AUDIT_DIAGNOSTICS_REVIEW_WINDOWS_SEC,
    AUDIT_DIAGNOSTICS_SUMMARY_ENABLED,
    AUDIT_DIAGNOSTICS_SUMMARY_TOP_N,
)
from services.lock_service import file_lock

logger = logging.getLogger(__name__)


class AuditDiagnosticsService:
    """Append compact cycle diagnostics when the audit toggle is enabled."""

    def __init__(self, file_path: str = "storage/audit_diagnostics.jsonl"):
        self.file_path = self._resolve_file_path(file_path)
        self.lock_path = Path(str(self.file_path) + ".lock")
        self.summary_path = self.file_path.with_name("audit_diagnostics_summary.json")
        self.summary_lock_path = Path(str(self.summary_path) + ".lock")
        self.review_path = self.file_path.with_name("audit_diagnostics_review_snapshot.json")
        self._state_lock = threading.RLock()
        self._recent_events: Dict[str, Dict[str, Any]] = {}
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists():
            self.lock_path.touch()
        if not self.summary_lock_path.exists():
            self.summary_lock_path.touch()
        if not self.file_path.exists():
            self.file_path.touch()
        if self.summary_enabled() and not self.summary_path.exists():
            self.summary_path.write_text(
                json.dumps(self._default_summary(), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        if self.summary_enabled() and not self.review_path.exists():
            self.review_path.write_text(
                json.dumps(self._default_review_snapshot(), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )

    @staticmethod
    def _write_json_atomic(path, data):
        """Write JSON atomically using tempfile + os.replace (POSIX rename)."""
        fd, temp_path = mkstemp(dir=os.path.dirname(str(path)), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            os.replace(temp_path, str(path))
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    @staticmethod
    def _resolve_file_path(file_path: str) -> Path:
        requested = Path(file_path)
        if (
            str(requested) == "storage/audit_diagnostics.jsonl"
            and (
                os.environ.get("PYTEST_CURRENT_TEST")
                or "pytest" in sys.modules
            )
        ):
            raw_test_id = os.environ.get("PYTEST_CURRENT_TEST") or "pytest"
            digest = sha1(raw_test_id.encode("utf-8")).hexdigest()[:12]
            worker = str(os.environ.get("PYTEST_XDIST_WORKER") or "gw0").strip() or "gw0"
            temp_root = Path(gettempdir()) / "opus_pytest_audit_diagnostics"
            return temp_root / f"audit_{worker}_{os.getpid()}_{digest}.jsonl"
        return requested

    @staticmethod
    def enabled() -> bool:
        return bool(AUDIT_DIAGNOSTICS_ENABLED)

    @staticmethod
    def summary_enabled() -> bool:
        return bool(AUDIT_DIAGNOSTICS_SUMMARY_ENABLED)

    @staticmethod
    def default_throttle_sec() -> float:
        try:
            return max(float(AUDIT_DIAGNOSTICS_EVENT_THROTTLE_SEC), 0.0)
        except Exception:
            return 60.0

    @staticmethod
    def health_window_sec() -> float:
        try:
            return max(float(AUDIT_DIAGNOSTICS_HEALTH_WINDOW_SEC), 60.0)
        except Exception:
            return 1800.0

    @staticmethod
    def summary_top_n() -> int:
        try:
            return max(int(AUDIT_DIAGNOSTICS_SUMMARY_TOP_N), 1)
        except Exception:
            return 5

    @staticmethod
    def recent_event_limit() -> int:
        try:
            return max(int(AUDIT_DIAGNOSTICS_RECENT_EVENT_LIMIT), 8)
        except Exception:
            return 24

    @staticmethod
    def review_windows_sec() -> Dict[str, int]:
        raw = AUDIT_DIAGNOSTICS_REVIEW_WINDOWS_SEC
        if not isinstance(raw, dict):
            return {"last_15m": 900, "last_1h": 3600}
        resolved: Dict[str, int] = {}
        for key, value in raw.items():
            label = str(key or "").strip()
            if not label:
                continue
            try:
                seconds = max(int(value), 60)
            except Exception:
                continue
            resolved[label] = seconds
        if not resolved:
            return {"last_15m": 900, "last_1h": 3600}
        return resolved

    def max_recent_window_sec(self) -> float:
        windows = self.review_windows_sec().values()
        return max([self.health_window_sec(), *[float(value) for value in windows]])

    @staticmethod
    def _parse_iso_ts(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _default_summary(self) -> Dict[str, Any]:
        return {
            "version": 8,
            "updated_at": None,
            "recent_window_sec": int(self.health_window_sec()),
            "rolling_windows_sec": self.review_windows_sec(),
            "event_counts": {},
            "rollup_counters": {
                "blocker_reasons": {},
                "suppression_reasons": {},
                "symbols_by_position_cap_hit": {},
                "symbols_by_insufficient_margin_event": {},
                "symbols_by_qty_below_min": {},
                "symbols_by_capital_compression_active": {},
                "symbols_by_loss_asymmetry_warn": {},
                "watchdog_types": {},
                "watchdog_reasons": {},
                "watchdog_symbols": {},
                "watchdog_bots": {},
                "config_issue_types": {},
                "config_issues_by_ui_path": {},
                "bots_by_config_integrity_issue": {},
                "experiment_tags": {},
                "experiment_trigger_ready": {},
                "experiment_executed": {},
                "experiment_blocked": {},
                "experiment_profit": {},
                "experiment_loss": {},
                "experiment_neutral": {},
                "experiment_combinations": {},
            },
            "rollups": {},
            "per_bot_health": {},
            "bot_review_snapshot": {},
            "health_status_counts": {},
        }

    def _default_review_snapshot(self) -> Dict[str, Any]:
        return {
            "version": 3,
            "updated_at": None,
            "rolling_windows_sec": self.review_windows_sec(),
            "bots": {},
        }

    @staticmethod
    def _increment_counter(counter: Dict[str, int], key: Optional[str], amount: int = 1) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            return
        counter[normalized] = int(counter.get(normalized, 0) or 0) + int(amount)

    def _read_summary(self) -> Dict[str, Any]:
        if not self.summary_path.exists():
            return self._default_summary()
        try:
            payload = json.loads(self.summary_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return self._default_summary()
        if not isinstance(payload, dict):
            return self._default_summary()
        summary = self._default_summary()
        summary.update(payload)
        summary["version"] = self._default_summary()["version"]
        summary["rolling_windows_sec"] = self.review_windows_sec()
        summary["recent_window_sec"] = int(self.health_window_sec())
        summary["event_counts"] = dict(summary.get("event_counts") or {})
        summary["rollup_counters"] = dict(summary.get("rollup_counters") or {})
        for key in self._default_summary()["rollup_counters"]:
            summary["rollup_counters"].setdefault(key, {})
        summary["per_bot_health"] = dict(summary.get("per_bot_health") or {})
        return summary

    def get_summary_snapshot(self) -> Dict[str, Any]:
        if not self.summary_enabled():
            return self._default_summary()
        try:
            with file_lock(self.summary_lock_path, exclusive=False):
                return self._read_summary()
        except Exception:
            return self._default_summary()

    def get_review_snapshot(self) -> Dict[str, Any]:
        payload = self._default_review_snapshot()
        if not self.summary_enabled() or not self.review_path.exists():
            return payload
        try:
            with file_lock(self.summary_lock_path, exclusive=False):
                raw = json.loads(self.review_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return payload
        if not isinstance(raw, dict):
            return payload
        payload.update(raw)
        payload["version"] = self._default_review_snapshot()["version"]
        payload["rolling_windows_sec"] = self.review_windows_sec()
        payload["bots"] = dict(payload.get("bots") or {})
        return payload

    @staticmethod
    def _top_items(counter: Dict[str, Any], limit: int) -> list:
        items = [
            {"key": str(key), "count": int(value or 0)}
            for key, value in (counter or {}).items()
            if str(key).strip() and int(value or 0) > 0
        ]
        items.sort(key=lambda item: (-item["count"], item["key"]))
        return items[:limit]

    def _get_event_ts(self, record: Dict[str, Any]) -> datetime:
        parsed = self._parse_iso_ts(record.get("timestamp")) or self._parse_iso_ts(
            record.get("recorded_at")
        )
        return parsed or datetime.now(timezone.utc)

    def _push_recent_event(
        self,
        health: Dict[str, Any],
        event_key: str,
        event_ts: datetime,
    ) -> int:
        recent = health.get("_recent_events")
        if not isinstance(recent, dict):
            recent = {}
            health["_recent_events"] = recent
        entries = recent.get(event_key)
        if not isinstance(entries, list):
            entries = []
        now_ts = event_ts.timestamp()
        window_start = now_ts - self.max_recent_window_sec()
        kept = []
        for value in entries:
            try:
                if float(value) >= window_start:
                    kept.append(float(value))
            except Exception:
                continue
        kept.append(now_ts)
        limit = self.recent_event_limit()
        if len(kept) > limit:
            kept = kept[-limit:]
        recent[event_key] = kept
        return len(kept)

    def _recent_count(self, health: Dict[str, Any], event_key: str) -> int:
        recent = health.get("_recent_events")
        entries = recent.get(event_key) if isinstance(recent, dict) else []
        return len(entries) if isinstance(entries, list) else 0

    def _trim_recent_events(self, health: Dict[str, Any], now_ts: datetime) -> None:
        recent = health.get("_recent_events")
        if not isinstance(recent, dict):
            return
        max_window = self.max_recent_window_sec()
        window_start = now_ts.timestamp() - max_window
        limit = self.recent_event_limit()
        cleaned: Dict[str, Any] = {}
        for key, values in recent.items():
            if not isinstance(values, list):
                continue
            kept = []
            for value in values:
                try:
                    if float(value) >= window_start:
                        kept.append(float(value))
                except Exception:
                    continue
            if kept:
                cleaned[key] = kept[-limit:]
        health["_recent_events"] = cleaned

    @staticmethod
    def _summarize_blockers(record: Dict[str, Any]) -> list:
        reasons = []
        for blocker in record.get("blocker_stack") or []:
            if not isinstance(blocker, dict):
                continue
            code = str(blocker.get("code") or "").strip().lower()
            reason = str(blocker.get("reason") or "").strip().lower()
            if code and reason:
                reasons.append(f"{code}:{reason}")
            elif code:
                reasons.append(code)
            elif reason:
                reasons.append(reason)
        return reasons

    @staticmethod
    def _summarize_suppression_reason(record: Dict[str, Any]) -> Optional[str]:
        event_type = str(record.get("event_type") or "").strip()
        if event_type == "position_cap_hit":
            return f"position_cap_hit:{record.get('suppression_kind') or 'unknown'}"
        if event_type == "position_cap_suppression_started":
            return "position_cap_suppression_started"
        if event_type == "insufficient_margin_event":
            return f"insufficient_margin:{record.get('attempted_action') or 'unknown'}"
        if event_type == "qty_below_min":
            action = record.get("attempted_action") or "unknown"
            opening_kind = record.get("opening_kind") or "unknown"
            return f"qty_below_min:{action}:{opening_kind}"
        if event_type == "failure_breaker_armed":
            return f"failure_breaker:{record.get('reason') or 'unknown'}"
        if event_type == "failure_breaker_cooldown_started":
            return f"failure_breaker_cooldown:{record.get('reason') or 'unknown'}"
        if event_type == "capital_starved_opening_block":
            return f"capital_starved:{record.get('reason') or 'unknown'}"
        if event_type == "capital_starved_block_activated":
            return f"capital_starved_block:{record.get('reason') or 'unknown'}"
        if event_type in ("opening_orders_suppressed", "add_follow_through_blocked"):
            return str(record.get("primary_reason") or event_type)
        return None

    @staticmethod
    def _config_integrity_issue_types() -> set[str]:
        return {
            "config_roundtrip_mismatch",
            "config_field_dropped",
            "config_field_normalized_unexpectedly",
            "config_ui_path_mismatch",
            "config_runtime_mismatch",
            "settings_version_conflict",
            "save_success_but_unchanged",
            "stale_render_after_save",
        }

    @staticmethod
    def _summarize_experiment_tags(record: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        raw_tags = record.get("experiment_tags")
        values = raw_tags if isinstance(raw_tags, (list, tuple, set)) else [raw_tags]
        for item in values:
            tag = str(item or "").strip().lower()
            if tag and tag not in tags:
                tags.append(tag)
        return sorted(tags)

    @staticmethod
    def _experiment_combination_key(tags: List[str]) -> Optional[str]:
        normalized = [
            str(tag or "").strip().lower()
            for tag in list(tags or [])
            if str(tag or "").strip()
        ]
        normalized = sorted(dict.fromkeys(normalized))
        if len(normalized) < 2:
            return None
        return " + ".join(normalized)

    def _refresh_top_rollups(self, summary: Dict[str, Any]) -> None:
        counters = summary.get("rollup_counters") or {}
        limit = self.summary_top_n()
        summary["rollups"] = {
            "top_blocker_reasons": self._top_items(
                counters.get("blocker_reasons") or {},
                limit,
            ),
            "top_suppression_reasons": self._top_items(
                counters.get("suppression_reasons") or {},
                limit,
            ),
            "top_symbols_by_position_cap_hit": self._top_items(
                counters.get("symbols_by_position_cap_hit") or {},
                limit,
            ),
            "top_symbols_by_insufficient_margin_event": self._top_items(
                counters.get("symbols_by_insufficient_margin_event") or {},
                limit,
            ),
            "top_symbols_by_qty_below_min": self._top_items(
                counters.get("symbols_by_qty_below_min") or {},
                limit,
            ),
            "top_symbols_by_capital_compression_active": self._top_items(
                counters.get("symbols_by_capital_compression_active") or {},
                limit,
            ),
            "top_symbols_by_loss_asymmetry_severity": self._top_items(
                counters.get("symbols_by_loss_asymmetry_warn") or {},
                limit,
            ),
            "top_watchdog_types": self._top_items(
                counters.get("watchdog_types") or {},
                limit,
            ),
            "top_watchdog_reasons": self._top_items(
                counters.get("watchdog_reasons") or {},
                limit,
            ),
            "top_watchdog_symbols": self._top_items(
                counters.get("watchdog_symbols") or {},
                limit,
            ),
            "top_watchdog_bots": self._top_items(
                counters.get("watchdog_bots") or {},
                limit,
            ),
            "top_config_issue_types": self._top_items(
                counters.get("config_issue_types") or {},
                limit,
            ),
            "top_config_issue_ui_paths": self._top_items(
                counters.get("config_issues_by_ui_path") or {},
                limit,
            ),
            "top_bots_by_config_integrity_issue": self._top_items(
                counters.get("bots_by_config_integrity_issue") or {},
                limit,
            ),
            "top_experiment_tags": self._top_items(
                counters.get("experiment_tags") or {},
                limit,
            ),
            "top_experiment_trigger_ready": self._top_items(
                counters.get("experiment_trigger_ready") or {},
                limit,
            ),
            "top_experiment_executed": self._top_items(
                counters.get("experiment_executed") or {},
                limit,
            ),
            "top_experiment_blocked": self._top_items(
                counters.get("experiment_blocked") or {},
                limit,
            ),
            "top_experiment_profit": self._top_items(
                counters.get("experiment_profit") or {},
                limit,
            ),
            "top_experiment_loss": self._top_items(
                counters.get("experiment_loss") or {},
                limit,
            ),
            "top_experiment_combinations": self._top_items(
                counters.get("experiment_combinations") or {},
                limit,
            ),
        }

    def _score_health_bottlenecks(self, health: Dict[str, Any]) -> list:
        candidates = []
        if health.get("capital_starved_active"):
            candidates.append(("capital_starved_opening_block", 100))
        if health.get("cap_pressure_active"):
            candidates.append(("position_cap_hit", 90 + self._recent_count(health, "position_cap_hit")))
        if health.get("capital_compression_active"):
            candidates.append(("capital_compression_active", 60))
        for key in (
            "failure_breaker_armed",
            "opening_orders_suppressed",
            "add_follow_through_blocked",
            "opening_orders_cancelled_by_cap",
            "insufficient_margin_event",
            "qty_below_min",
        ):
            count = self._recent_count(health, key)
            if count > 0:
                candidates.append((key, count))
        config_issue_count = int(health.get("config_integrity_issue_count_recent") or 0)
        if config_issue_count > 0:
            candidates.append(
                (
                    health.get("config_integrity_top_issue") or "config_roundtrip_mismatch",
                    config_issue_count,
                )
            )
        loss_state = str(health.get("loss_asymmetry_state") or "").strip()
        if loss_state and loss_state != "harvest_positive_or_flat":
            candidates.append((f"loss_asymmetry:{loss_state}", 1))
        watchdog_type = str(health.get("watchdog_last_type") or "").strip()
        watchdog_count = int(health.get("watchdog_event_count_recent") or 0)
        if watchdog_type and watchdog_count > 0:
            candidates.append((f"watchdog:{watchdog_type}", watchdog_count))
        candidates.sort(key=lambda item: (-item[1], item[0]))
        return [name for name, _ in candidates[:3]]

    def _recent_count_window(
        self,
        health: Dict[str, Any],
        event_key: str,
        window_sec: int,
    ) -> int:
        recent = health.get("_recent_events")
        entries = recent.get(event_key) if isinstance(recent, dict) else []
        if not isinstance(entries, list):
            return 0
        now_dt = self._parse_iso_ts(health.get("last_event_at")) or datetime.now(timezone.utc)
        window_start = now_dt.timestamp() - float(max(int(window_sec), 60))
        count = 0
        for value in entries:
            try:
                if float(value) >= window_start:
                    count += 1
            except Exception:
                continue
        return count

    def _build_rolling_counters(self, health: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
        mapping = {
            "position_cap_hit_recent": ("position_cap_hit", "position_cap_suppression_started"),
            "insufficient_margin_recent": "insufficient_margin_event",
            "qty_below_min_recent": "qty_below_min",
            "opening_orders_placed_recent": ("opening_orders_placed", "opening_follow_through_restored"),
            "opening_orders_blocked_recent": ("opening_orders_suppressed", "add_follow_through_blocked"),
            "quick_profit_rebuild_recent": ("quick_profit_rebuild_happened", "quick_profit_rebuild_completed"),
            "add_follow_through_recent": ("add_follow_through_happened", "opening_follow_through_restored"),
            "watchdog_event_recent": "watchdog_event",
            "config_integrity_issue_recent": (
                "config_roundtrip_mismatch",
                "config_field_dropped",
                "config_field_normalized_unexpectedly",
                "config_ui_path_mismatch",
                "config_runtime_mismatch",
                "settings_version_conflict",
                "save_success_but_unchanged",
                "stale_render_after_save",
            ),
            "settings_version_conflict_recent": "settings_version_conflict",
        }
        payload: Dict[str, Dict[str, int]] = {}
        for label, seconds in self.review_windows_sec().items():
            payload[label] = {
                counter_name: (
                    sum(
                        self._recent_count_window(health, single_key, seconds)
                        for single_key in event_key
                    )
                    if isinstance(event_key, tuple)
                    else self._recent_count_window(health, event_key, seconds)
                )
                for counter_name, event_key in mapping.items()
            }
        return payload

    @staticmethod
    def _cap_headroom_state(health: Dict[str, Any]) -> str:
        if health.get("cap_pressure_active"):
            return "suppressed"
        if int(health.get("cap_hit_count_recent") or 0) > 0:
            return "tight"
        return "clear"

    @staticmethod
    def _margin_viability_state(health: Dict[str, Any]) -> str:
        if health.get("capital_starved_active"):
            return "starved"
        if health.get("capital_compression_active"):
            return "compressed"
        if int(health.get("margin_fail_count_recent") or 0) > 0:
            return "stressed"
        if int(health.get("qty_below_min_count_recent") or 0) > 0:
            return "min_size_limited"
        return "viable"

    @staticmethod
    def _config_integrity_state(health: Dict[str, Any]) -> str:
        count = int(health.get("config_integrity_issue_count_recent") or 0)
        if count >= 3:
            return "degraded"
        if count > 0:
            return "watch"
        if health.get("last_config_roundtrip_matches_intent") is False:
            return "mismatch"
        return "clean"

    def _build_recent_actions(
        self,
        rolling_counters: Dict[str, Dict[str, int]],
    ) -> Dict[str, Dict[str, int]]:
        last_15m = dict((rolling_counters or {}).get("last_15m") or {})
        suppressions = {
            "position_cap_hit": int(last_15m.get("position_cap_hit_recent") or 0),
            "insufficient_margin": int(last_15m.get("insufficient_margin_recent") or 0),
            "qty_below_min": int(last_15m.get("qty_below_min_recent") or 0),
            "opening_orders_blocked": int(last_15m.get("opening_orders_blocked_recent") or 0),
            "config_integrity_issues": int(last_15m.get("config_integrity_issue_recent") or 0),
        }
        positives = {
            "opening_orders_placed": int(last_15m.get("opening_orders_placed_recent") or 0),
            "quick_profit_rebuild": int(last_15m.get("quick_profit_rebuild_recent") or 0),
            "add_follow_through": int(last_15m.get("add_follow_through_recent") or 0),
        }
        return {
            "recent_suppressions": {k: v for k, v in suppressions.items() if v > 0},
            "recent_positive_actions": {k: v for k, v in positives.items() if v > 0},
        }

    def _build_last_rebuild_marker(self, health: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        state = str(health.get("last_recenter_state") or "").strip()
        if not state:
            return None
        return {
            "state": state,
            "at": health.get("last_quick_profit_rebuild_at") or health.get("last_recenter_at"),
        }

    def _build_bot_review_snapshot(self, health: Dict[str, Any]) -> Dict[str, Any]:
        rolling_counters = self._build_rolling_counters(health)
        recent_actions = self._build_recent_actions(rolling_counters)
        return {
            "bot_id": health.get("bot_id"),
            "symbol": health.get("symbol"),
            "mode": health.get("mode"),
            "current_operational_status": health.get("health_status") or "OK",
            "top_bottleneck": ((health.get("top_bottlenecks") or [None])[0]),
            "cap_headroom_state": self._cap_headroom_state(health),
            "margin_viability_state": self._margin_viability_state(health),
            "follow_through_state": health.get("last_follow_through_state"),
            "recenter_state": health.get("last_recenter_state"),
            "config_integrity_state": self._config_integrity_state(health),
            "config_integrity_issue_count_recent": int(
                health.get("config_integrity_issue_count_recent") or 0
            ),
            "config_integrity_top_issue": health.get("config_integrity_top_issue"),
            "watchdog_state": (
                {
                    "type": health.get("watchdog_last_type"),
                    "reason": health.get("watchdog_last_reason"),
                    "severity": health.get("watchdog_last_severity"),
                    "count_recent": int(health.get("watchdog_event_count_recent") or 0),
                }
                if health.get("watchdog_last_type")
                else None
            ),
            "last_config_integrity_event": health.get("last_config_integrity_event"),
            "last_config_save_ui_path": health.get("last_config_save_ui_path"),
            "settings_version_conflicts_total": int(
                health.get("settings_version_conflicts_total") or 0
            ),
            "settings_version_conflicts_stale": int(
                health.get("settings_version_conflicts_stale") or 0
            ),
            "settings_version_conflicts_missing": int(
                health.get("settings_version_conflicts_missing") or 0
            ),
            "last_settings_version_conflict_ts": health.get("last_settings_version_conflict_ts"),
            "last_settings_version_conflict_source": health.get(
                "last_settings_version_conflict_source"
            ),
            "last_config_roundtrip_matches_intent": health.get(
                "last_config_roundtrip_matches_intent"
            ),
            "last_transition_event": health.get("last_transition_event"),
            "recent_suppressions": recent_actions["recent_suppressions"],
            "recent_positive_actions": recent_actions["recent_positive_actions"],
            "experiment_state": (
                {
                    "active_tags": list(health.get("last_experiment_tags") or []),
                    "last_event_type": health.get("last_experiment_event_type"),
                    "last_seen_at": health.get("last_experiment_seen_at"),
                    "last_outcome_kind": health.get("last_experiment_outcome_kind"),
                    "last_outcome_tags": list(
                        health.get("last_experiment_outcome_tags") or []
                    ),
                    "last_realized_pnl": health.get("last_experiment_realized_pnl"),
                }
                if health.get("last_experiment_tags")
                else None
            ),
            "rolling_counters": rolling_counters,
            "last_significant_rebuild_marker": self._build_last_rebuild_marker(health),
            "updated_at": health.get("last_event_at"),
        }

    def _refresh_bot_review_snapshot(self, summary: Dict[str, Any]) -> None:
        snapshot: Dict[str, Any] = {}
        for bot_id, health in (summary.get("per_bot_health") or {}).items():
            if not isinstance(health, dict):
                continue
            snapshot[str(bot_id)] = self._build_bot_review_snapshot(health)
        summary["bot_review_snapshot"] = snapshot

    def _write_review_snapshot(self, summary: Dict[str, Any]) -> None:
        payload = self._default_review_snapshot()
        payload["updated_at"] = summary.get("updated_at")
        payload["bots"] = dict(summary.get("bot_review_snapshot") or {})
        self._write_json_atomic(self.review_path, payload)

    def _resolve_health_status(self, health: Dict[str, Any]) -> str:
        cap_hits = self._recent_count(health, "position_cap_hit")
        margin_fails = self._recent_count(health, "insufficient_margin_event")
        qty_hits = self._recent_count(health, "qty_below_min")
        breaker_hits = self._recent_count(health, "failure_breaker_armed")
        opening_suppressed = self._recent_count(health, "opening_orders_suppressed")
        config_issue_count = int(health.get("config_integrity_issue_count_recent") or 0)
        watchdog_count = int(health.get("watchdog_event_count_recent") or 0)
        watchdog_severity = str(health.get("watchdog_last_severity") or "").strip().upper()
        if health.get("capital_starved_active") or breaker_hits > 0:
            return "BLOCKED"
        if (
            health.get("cap_pressure_active")
            or opening_suppressed >= 2
            or cap_hits >= 3
            or margin_fails >= 2
            or health.get("capital_compression_active")
            or watchdog_severity in ("ERROR", "CRITICAL")
            or config_issue_count >= 3
        ):
            return "DEGRADED"
        if (
            qty_hits > 0
            or cap_hits > 0
            or margin_fails > 0
            or watchdog_count > 0
            or config_issue_count > 0
            or health.get("loss_asymmetry_state")
        ):
            return "WATCH"
        return "OK"

    def _update_bot_health(self, summary: Dict[str, Any], record: Dict[str, Any]) -> None:
        bot_id = str(record.get("bot_id") or "").strip()
        if not bot_id:
            return
        event_type = str(record.get("event_type") or "").strip()
        event_ts = self._get_event_ts(record)
        per_bot = summary.setdefault("per_bot_health", {})
        health = per_bot.get(bot_id)
        if not isinstance(health, dict):
            health = {}
            per_bot[bot_id] = health

        self._trim_recent_events(health, event_ts)
        health["bot_id"] = bot_id
        health["symbol"] = str(record.get("symbol") or health.get("symbol") or "").strip().upper()
        health["mode"] = str(record.get("mode") or health.get("mode") or "").strip().lower() or None
        health["last_event_at"] = event_ts.isoformat()
        health["recent_window_sec"] = int(self.health_window_sec())
        health["last_transition_event"] = health.get("last_transition_event")

        if event_type == "capital_compression_snapshot":
            health["capital_compression_active"] = bool(record.get("capital_compression_active"))
            if record.get("capital_compression_active"):
                self._push_recent_event(health, event_type, event_ts)
        elif event_type == "position_cap_hit":
            self._push_recent_event(health, event_type, event_ts)
            health["cap_pressure_active"] = True
            health["last_follow_through_state"] = "blocked_position_cap"
        elif event_type == "cap_pressure_cleared":
            health["cap_pressure_active"] = False
            health["last_follow_through_state"] = "cap_pressure_cleared"
            health["last_cap_pressure_cleared_at"] = event_ts.isoformat()
        elif event_type == "insufficient_margin_event":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "blocked_insufficient_margin"
        elif event_type == "qty_below_min":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "blocked_qty_below_min"
        elif event_type == "failure_breaker_armed":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "failure_breaker_armed"
        elif event_type == "capital_starved_opening_block":
            self._push_recent_event(health, event_type, event_ts)
            health["capital_starved_active"] = True
            health["capital_starved_reason"] = record.get("reason")
            health["last_follow_through_state"] = "capital_starved_opening_block"
        elif event_type == "capital_starved_block_cleared":
            health["capital_starved_active"] = False
            health["capital_starved_reason"] = None
            health["last_follow_through_state"] = "capital_starved_block_cleared"
            health["last_transition_event"] = event_type
        elif event_type == "capital_starved_block_activated":
            self._push_recent_event(health, event_type, event_ts)
            health["last_transition_event"] = event_type
        elif event_type == "failure_breaker_cooldown_started":
            self._push_recent_event(health, event_type, event_ts)
            health["failure_breaker_active"] = True
            health["last_transition_event"] = event_type
        elif event_type == "failure_breaker_cooldown_cleared":
            health["failure_breaker_active"] = False
            health["last_transition_event"] = event_type
            health["last_follow_through_state"] = "failure_breaker_cooldown_cleared"
        elif event_type == "position_cap_suppression_started":
            self._push_recent_event(health, event_type, event_ts)
            health["cap_pressure_active"] = True
            health["last_transition_event"] = event_type
        elif event_type == "position_cap_suppression_cleared":
            health["cap_pressure_active"] = False
            health["last_transition_event"] = event_type
        elif event_type == "quick_profit_rebuild_started":
            health["last_transition_event"] = event_type
            health["last_recenter_state"] = "quick_profit_rebuild_started"
        elif event_type == "quick_profit_rebuild_completed":
            self._push_recent_event(health, event_type, event_ts)
            health["last_transition_event"] = event_type
            health["last_recenter_state"] = "quick_profit_rebuild_completed"
            health["last_quick_profit_rebuild_at"] = event_ts.isoformat()
        elif event_type == "opening_follow_through_restored":
            self._push_recent_event(health, event_type, event_ts)
            health["last_transition_event"] = event_type
            health["last_follow_through_state"] = "opening_follow_through_restored"
        elif event_type == "opening_orders_cancelled_by_cap":
            self._push_recent_event(health, event_type, event_ts)
            health["cap_pressure_active"] = True
            health["last_follow_through_state"] = "opening_orders_cancelled_by_cap"
        elif event_type == "opening_orders_suppressed":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "opening_orders_suppressed"
        elif event_type == "add_follow_through_blocked":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "add_follow_through_blocked"
        elif event_type == "opening_orders_placed":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "opening_orders_placed"
            health["last_opening_orders_placed_at"] = event_ts.isoformat()
        elif event_type == "add_follow_through_happened":
            self._push_recent_event(health, event_type, event_ts)
            health["last_follow_through_state"] = "add_follow_through_happened"
        elif event_type == "recenter_happened":
            self._push_recent_event(health, event_type, event_ts)
            health["last_recenter_state"] = "recenter_happened"
            health["last_recenter_at"] = event_ts.isoformat()
        elif event_type == "quick_profit_rebuild_happened":
            self._push_recent_event(health, event_type, event_ts)
            health["last_recenter_state"] = "quick_profit_rebuild_happened"
            health["last_quick_profit_rebuild_at"] = event_ts.isoformat()
        elif event_type == "config_save_roundtrip":
            health["last_config_save_ui_path"] = record.get("ui_path")
            health["last_config_roundtrip_matches_intent"] = bool(
                record.get("persisted_matches_intent", False)
            )
            health["last_config_roundtrip_at"] = event_ts.isoformat()
            health["last_config_roundtrip"] = {
                "ui_path": record.get("ui_path"),
                "changed_fields": list(record.get("changed_fields") or []),
                "normalized_fields": list(record.get("normalized_fields") or []),
                "dropped_fields": list(record.get("dropped_fields") or []),
                "persisted_matches_intent": bool(record.get("persisted_matches_intent", False)),
            }
        elif event_type in self._config_integrity_issue_types():
            self._push_recent_event(health, event_type, event_ts)
            health["last_config_integrity_event"] = event_type
            health["last_config_save_ui_path"] = record.get("ui_path") or health.get(
                "last_config_save_ui_path"
            )
            health["config_integrity_top_issue"] = event_type
            if event_type == "settings_version_conflict":
                conflict_reason = (
                    str(record.get("conflict_reason") or "").strip().lower()
                    or "unknown"
                )
                health["settings_version_conflicts_total"] = int(
                    health.get("settings_version_conflicts_total") or 0
                ) + 1
                if conflict_reason == "stale_incoming_version":
                    health["settings_version_conflicts_stale"] = int(
                        health.get("settings_version_conflicts_stale") or 0
                    ) + 1
                elif conflict_reason == "missing_incoming_version":
                    health["settings_version_conflicts_missing"] = int(
                        health.get("settings_version_conflicts_missing") or 0
                    ) + 1
                health["last_settings_version_conflict_ts"] = event_ts.isoformat()
                health["last_settings_version_conflict_source"] = record.get("ui_path") or health.get(
                    "last_settings_version_conflict_source"
                )
            if record.get("fields"):
                health["last_config_integrity_fields"] = list(record.get("fields") or [])
            elif record.get("dropped_fields"):
                health["last_config_integrity_fields"] = list(record.get("dropped_fields") or [])
            elif record.get("normalized_fields"):
                health["last_config_integrity_fields"] = list(record.get("normalized_fields") or [])
        elif event_type == "loss_asymmetry_snapshot":
            self._push_recent_event(health, event_type, event_ts)
            health["loss_asymmetry_state"] = record.get("summary")
            health["loss_asymmetry_severity"] = record.get("severity")
        elif event_type == "watchdog_event":
            watchdog_type = str(record.get("watchdog_type") or "").strip().lower()
            event_key = f"watchdog:{watchdog_type or 'unknown'}"
            self._push_recent_event(health, "watchdog_event", event_ts)
            self._push_recent_event(health, event_key, event_ts)
            health["watchdog_last_type"] = watchdog_type or None
            health["watchdog_last_reason"] = record.get("reason")
            health["watchdog_last_severity"] = str(record.get("severity") or "").strip().upper() or None
        experiment_tags = self._summarize_experiment_tags(record)
        experiment_outcome_kind = (
            str(record.get("experiment_outcome_kind") or "").strip().lower() or None
        )
        if experiment_tags:
            health["last_experiment_tags"] = experiment_tags
            health["last_experiment_event_type"] = event_type
            health["last_experiment_seen_at"] = event_ts.isoformat()
        if experiment_tags and experiment_outcome_kind:
            health["last_experiment_outcome_kind"] = experiment_outcome_kind
            health["last_experiment_outcome_tags"] = list(
                record.get("experiment_outcome_tags") or []
            )
            health["last_experiment_outcome_at"] = event_ts.isoformat()
            if record.get("realized_pnl") is not None:
                health["last_experiment_realized_pnl"] = record.get("realized_pnl")

        health["cap_hit_count_recent"] = self._recent_count(health, "position_cap_hit")
        health["margin_fail_count_recent"] = self._recent_count(health, "insufficient_margin_event")
        health["qty_below_min_count_recent"] = self._recent_count(health, "qty_below_min")
        health["failure_breaker_armed_count_recent"] = self._recent_count(health, "failure_breaker_armed")
        health["opening_orders_suppressed_count_recent"] = self._recent_count(health, "opening_orders_suppressed")
        health["opening_orders_cancelled_by_cap_count_recent"] = self._recent_count(
            health,
            "opening_orders_cancelled_by_cap",
        )
        health["opening_orders_placed_count_recent"] = self._recent_count(health, "opening_orders_placed")
        health["add_follow_through_count_recent"] = self._recent_count(
            health,
            "add_follow_through_happened",
        )
        health["add_follow_through_blocked_count_recent"] = self._recent_count(
            health,
            "add_follow_through_blocked",
        )
        health["config_integrity_issue_count_recent"] = sum(
            self._recent_count(health, event_type)
            for event_type in self._config_integrity_issue_types()
        )
        health["watchdog_event_count_recent"] = self._recent_count(health, "watchdog_event")
        health["rolling_counters"] = self._build_rolling_counters(health)
        health["top_bottlenecks"] = self._score_health_bottlenecks(health)
        health["health_status"] = self._resolve_health_status(health)

    def _refresh_health_status_counts(self, summary: Dict[str, Any]) -> None:
        counts: Dict[str, int] = {}
        for health in (summary.get("per_bot_health") or {}).values():
            if not isinstance(health, dict):
                continue
            status = str(health.get("health_status") or "OK").strip().upper() or "OK"
            counts[status] = int(counts.get(status, 0) or 0) + 1
        summary["health_status_counts"] = counts

    def _apply_event_to_summary(self, summary: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
        event_type = str(record.get("event_type") or record.get("event") or "").strip()
        symbol = str(record.get("symbol") or "").strip().upper()
        self._increment_counter(summary.setdefault("event_counts", {}), event_type)
        rollup_counters = summary.setdefault("rollup_counters", {})
        for reason in self._summarize_blockers(record):
            self._increment_counter(rollup_counters.setdefault("blocker_reasons", {}), reason)
        suppression_reason = self._summarize_suppression_reason(record)
        if suppression_reason:
            self._increment_counter(
                rollup_counters.setdefault("suppression_reasons", {}),
                suppression_reason,
            )
        if event_type == "position_cap_hit":
            self._increment_counter(
                rollup_counters.setdefault("symbols_by_position_cap_hit", {}),
                symbol,
            )
        elif event_type == "insufficient_margin_event":
            self._increment_counter(
                rollup_counters.setdefault("symbols_by_insufficient_margin_event", {}),
                symbol,
            )
        elif event_type == "qty_below_min":
            self._increment_counter(
                rollup_counters.setdefault("symbols_by_qty_below_min", {}),
                symbol,
            )
        elif event_type == "capital_compression_snapshot" and record.get("capital_compression_active"):
            self._increment_counter(
                rollup_counters.setdefault("symbols_by_capital_compression_active", {}),
                symbol,
            )
        elif event_type == "loss_asymmetry_snapshot" and str(record.get("severity") or "").upper() in ("WARN", "ERROR", "CRITICAL"):
            self._increment_counter(
                rollup_counters.setdefault("symbols_by_loss_asymmetry_warn", {}),
                symbol,
            )
        elif event_type == "watchdog_event":
            self._increment_counter(
                rollup_counters.setdefault("watchdog_types", {}),
                str(record.get("watchdog_type") or "unknown").strip().lower() or "unknown",
            )
            self._increment_counter(
                rollup_counters.setdefault("watchdog_reasons", {}),
                str(record.get("reason") or "watch").strip().lower() or "watch",
            )
            self._increment_counter(
                rollup_counters.setdefault("watchdog_symbols", {}),
                symbol or "unknown",
            )
            self._increment_counter(
                rollup_counters.setdefault("watchdog_bots", {}),
                str(record.get("bot_id") or "unknown").strip() or "unknown",
            )
        if event_type in self._config_integrity_issue_types():
            self._increment_counter(
                rollup_counters.setdefault("config_issue_types", {}),
                event_type,
            )
            self._increment_counter(
                rollup_counters.setdefault("config_issues_by_ui_path", {}),
                str(record.get("ui_path") or "unknown").strip().lower() or "unknown",
            )
            self._increment_counter(
                rollup_counters.setdefault("bots_by_config_integrity_issue", {}),
                str(record.get("bot_id") or "unknown").strip() or "unknown",
            )
        experiment_tags = self._summarize_experiment_tags(record)
        for tag in experiment_tags:
            self._increment_counter(
                rollup_counters.setdefault("experiment_tags", {}),
                tag,
            )
        combination_key = self._experiment_combination_key(experiment_tags)
        if combination_key:
            self._increment_counter(
                rollup_counters.setdefault("experiment_combinations", {}),
                combination_key,
            )
        outcome_kind = str(record.get("experiment_outcome_kind") or "").strip().lower()
        outcome_counter_key = {
            "trigger_ready": "experiment_trigger_ready",
            "executed": "experiment_executed",
            "blocked": "experiment_blocked",
            "profit": "experiment_profit",
            "loss": "experiment_loss",
            "neutral": "experiment_neutral",
        }.get(outcome_kind)
        if outcome_counter_key:
            for tag in experiment_tags:
                self._increment_counter(
                    rollup_counters.setdefault(outcome_counter_key, {}),
                    tag,
                )
        self._update_bot_health(summary, record)
        self._refresh_top_rollups(summary)
        self._refresh_health_status_counts(summary)
        self._refresh_bot_review_snapshot(summary)
        summary["updated_at"] = self._get_event_ts(record).isoformat()
        return summary

    def _update_summary(self, record: Dict[str, Any]) -> None:
        if not self.summary_enabled():
            return
        try:
            with file_lock(self.summary_lock_path, exclusive=True):
                summary = self._read_summary()
                summary = self._apply_event_to_summary(summary, record)
                self._write_json_atomic(self.summary_path, summary)
                self._write_review_snapshot(summary)
        except Exception as exc:
            logger.warning("Failed to update audit diagnostics summary: %s", exc)

    def record_event(
        self,
        payload: Optional[Dict[str, Any]],
        *,
        throttle_key: Optional[str] = None,
        throttle_sec: Optional[float] = None,
    ) -> bool:
        if not self.enabled() or not payload:
            return False
        record = dict(payload)
        fingerprint_payload = dict(record)
        fingerprint_payload.pop("timestamp", None)
        fingerprint_payload.pop("recorded_at", None)
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        record.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        event_type = str(record.get("event_type") or record.get("event") or "").strip()
        symbol = str(record.get("symbol") or "").strip().upper()
        bot_id = str(record.get("bot_id") or "").strip()
        base_key = throttle_key or f"{event_type}:{bot_id}:{symbol}"
        fingerprint = json.dumps(
            fingerprint_payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        now_ts = time.monotonic()
        throttle_window = self.default_throttle_sec() if throttle_sec is None else max(float(throttle_sec), 0.0)
        with self._state_lock:
            previous = self._recent_events.get(base_key)
            if (
                previous
                and previous.get("fingerprint") == fingerprint
                and (now_ts - float(previous.get("ts") or 0.0)) < throttle_window
            ):
                return False
            self._recent_events[base_key] = {
                "fingerprint": fingerprint,
                "ts": now_ts,
            }
        try:
            with file_lock(self.lock_path, exclusive=True):
                with open(self.file_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._update_summary(record)
            return True
        except Exception as exc:
            logger.warning("Failed to append audit diagnostics: %s", exc)
            return False

    def record_cycle(self, payload: Optional[Dict[str, Any]]) -> None:
        self.record_event(payload)

    def get_recent_events(
        self,
        *,
        event_type: Optional[str] = None,
        since_seconds: Optional[float] = None,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if limit <= 0 or not self.file_path.exists():
            return []
        cutoff_ts = None
        if since_seconds is not None:
            try:
                cutoff_ts = time.time() - max(float(since_seconds), 0.0)
            except Exception:
                cutoff_ts = None
        normalized_event_type = str(event_type or "").strip()
        normalized_bot_id = str(bot_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        matched: List[Dict[str, Any]] = []
        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    raw = str(line or "").strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except Exception:
                        continue
                    if normalized_event_type and str(record.get("event_type") or "").strip() != normalized_event_type:
                        continue
                    if normalized_bot_id and str(record.get("bot_id") or "").strip() != normalized_bot_id:
                        continue
                    if normalized_symbol and str(record.get("symbol") or "").strip().upper() != normalized_symbol:
                        continue
                    if cutoff_ts is not None:
                        event_dt = self._get_event_ts(record)
                        if event_dt.timestamp() < cutoff_ts:
                            continue
                    matched.append(record)
        except Exception as exc:
            logger.warning("Failed to read recent audit diagnostics: %s", exc)
            return []
        if len(matched) > limit:
            matched = matched[-limit:]
        return matched
