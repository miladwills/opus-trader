from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


class RuntimeStateIntegrityWatchdogService:
    """Arbitrate dashboard runtime truth and preserve bounded last-known-good state."""

    HOLD_LAST_GOOD_SEC = 20.0
    START_ACCEPTED_SEC = 3.0
    START_PENDING_SEC = 15.0
    START_STALLED_SEC = 40.0
    START_RETENTION_SEC = 180.0
    OSCILLATION_WINDOW_SEC = 30.0
    OSCILLATION_MIN_FLIPS = 2

    _RUNNING_STATUSES = {
        "running",
        "recovering",
        "paused",
        "flash_crash_paused",
    }

    def __init__(
        self,
        *,
        hold_last_good_sec: Optional[float] = None,
        start_pending_sec: Optional[float] = None,
        start_stalled_sec: Optional[float] = None,
        oscillation_window_sec: Optional[float] = None,
        runner_heartbeat_stale_sec: Optional[float] = None,
    ) -> None:
        if hold_last_good_sec is not None:
            self.HOLD_LAST_GOOD_SEC = max(float(hold_last_good_sec), 1.0)
        if start_pending_sec is not None:
            self.START_PENDING_SEC = max(float(start_pending_sec), 1.0)
        if start_stalled_sec is not None:
            self.START_STALLED_SEC = max(float(start_stalled_sec), self.START_PENDING_SEC)
        if oscillation_window_sec is not None:
            self.OSCILLATION_WINDOW_SEC = max(float(oscillation_window_sec), 5.0)
        self.RUNNER_HEARTBEAT_STALE_SEC = max(
            float(runner_heartbeat_stale_sec if runner_heartbeat_stale_sec is not None else 20.0),
            5.0,
        )
        self._lock = threading.RLock()
        self._last_good_payload: Optional[Dict[str, Any]] = None
        self._last_good_summary: Dict[str, Any] = {}
        self._last_summary: Dict[str, Any] = self._default_summary()
        self._pending_starts: Dict[str, Dict[str, Any]] = {}
        self._bot_transition_history: Dict[str, List[Dict[str, Any]]] = {}
        self._last_observed_bot_state: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _copy(value: Any) -> Any:
        return copy.deepcopy(value)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _parse_iso_ts(cls, value: Any) -> float:
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @classmethod
    def _payload_snapshot_ts(cls, payload: Optional[Dict[str, Any]]) -> float:
        raw = dict(payload or {}) if isinstance(payload, dict) else {}
        return max(
            cls._safe_float(raw.get("snapshot_published_at"), 0.0),
            cls._safe_float(raw.get("snapshot_produced_at"), 0.0),
        )

    @staticmethod
    def _default_summary() -> Dict[str, Any]:
        return {
            "status": "healthy",
            "runtime_integrity_state": "healthy",
            "runtime_state_source": "unavailable",
            "runtime_state_age_sec": None,
            "bridge_state_age_sec": None,
            "runner_heartbeat_age_sec": None,
            "app_heartbeat_age_sec": 0.0,
            "bridge_age_ms": None,
            "runtime_snapshot_age_ms": None,
            "runtime_publish_age_ms": None,
            "selected_runtime_publish_at": None,
            "selected_runtime_publish_ts": None,
            "selected_readiness_generated_at": None,
            "selected_readiness_age_ms": None,
            "bridge_action": "unavailable",
            "bridge_rejected_reason": None,
            "held_last_good": False,
            "rebuilt_from_app": False,
            "last_known_good_runtime_at": None,
            "last_known_good_age_sec": None,
            "stale_guard_active": False,
            "stale_guard_reason": None,
            "divergence_detected": False,
            "divergence_reasons": [],
            "oscillation_detected": False,
            "ready_state_oscillation": False,
            "bot_visibility_oscillation": False,
            "dropped_as_stale": False,
            "dropped_reason": None,
            "resync_requested": False,
            "no_active_bot_stable": True,
            "preserved_from_last_known_good": False,
            "startup_pending": False,
            "startup_stalled": False,
            "startup_pending_count": 0,
            "startup_stalled_count": 0,
            "held_bot_count": 0,
            "selected_bot_count": 0,
            "selected_runtime_truth_count": 0,
            "effective_bot_count": 0,
            "effective_ready_count": 0,
            "selected_snapshot_ts": None,
            "selected_snapshot_epoch": None,
            "selected_stale_data": False,
            "selected_error": None,
            "candidate_sources": [],
            "divergence": {
                "detected": False,
                "missing_bot_ids": [],
                "status_conflicts": [],
                "readiness_conflicts": [],
                "malformed_sources": [],
            },
            "oscillation": {
                "visible_flips": 0,
                "ready_flips": 0,
                "affected_bot_ids": [],
            },
            "startup": {
                "pending_bot_ids": [],
                "stalled_bot_ids": [],
            },
        }

    @staticmethod
    def _runtime_truth_count(bots: List[Dict[str, Any]]) -> int:
        total = 0
        for bot in list(bots or []):
            if not isinstance(bot, dict):
                continue
            setup_status = str(
                bot.get("setup_timing_status")
                or bot.get("setup_ready_status")
                or bot.get("analysis_ready_status")
                or bot.get("entry_ready_status")
                or ""
            ).strip()
            execution_status = str(bot.get("execution_viability_status") or "").strip()
            has_score = (
                bot.get("setup_ready_score") is not None
                or bot.get("analysis_ready_score") is not None
            )
            if setup_status or execution_status or has_score:
                total += 1
        return total

    @staticmethod
    def _ready_visible(bot: Dict[str, Any]) -> bool:
        setup_status = str(
            bot.get("setup_timing_status")
            or bot.get("setup_ready_status")
            or bot.get("analysis_ready_status")
            or ""
        ).strip().lower()
        return setup_status in {"ready", "trigger_ready", "armed", "late", "watch", "wait", "caution"}

    def _normalize_candidate(
        self,
        payload: Optional[Dict[str, Any]],
        *,
        candidate_name: str,
        now_ts: float,
    ) -> Dict[str, Any]:
        raw = dict(payload or {}) if isinstance(payload, dict) else {}
        bots_raw = raw.get("bots")
        bots_list = list(bots_raw or []) if isinstance(bots_raw, list) else []
        valid_bots_shape = isinstance(bots_raw, list) and all(
            isinstance(bot, dict) for bot in bots_list
        )
        snapshot_published_at = self._safe_float(raw.get("snapshot_published_at"), 0.0)
        snapshot_produced_at = self._safe_float(raw.get("snapshot_produced_at"), 0.0)
        snapshot_ts = (
            snapshot_published_at
            if snapshot_published_at > 0
            else (snapshot_produced_at if snapshot_produced_at > 0 else 0.0)
        )
        snapshot_age_sec = (
            round(max(now_ts - snapshot_ts, 0.0), 3) if snapshot_ts > 0 else None
        )
        snapshot_epoch = self._safe_int(raw.get("snapshot_epoch"), 0)
        stale_data = bool(raw.get("stale_data"))
        snapshot_source = str(
            raw.get("runtime_state_source")
            or raw.get("snapshot_source")
            or candidate_name
        ).strip() or candidate_name
        runtime_publish_ts = max(
            self._safe_float(raw.get("runtime_publish_ts"), 0.0),
            self._parse_iso_ts(raw.get("runtime_publish_at")),
        )
        readiness_latency = (
            dict(raw.get("readiness_latency") or {})
            if isinstance(raw.get("readiness_latency"), dict)
            else {}
        )
        latest_readiness_generated_ts = max(
            self._safe_float(readiness_latency.get("latest_readiness_generated_ts"), 0.0),
            self._parse_iso_ts(readiness_latency.get("latest_readiness_generated_at")),
        )
        error = str(raw.get("error") or "").strip() or None
        runtime_truth_count = self._runtime_truth_count(bots_list) if valid_bots_shape else 0
        malformed = not valid_bots_shape
        partial = (
            valid_bots_shape
            and len(bots_list) > 0
            and runtime_truth_count == 0
            and snapshot_source != "storage_fallback"
        )
        trust_rank = 0
        if not malformed and not stale_data:
            trust_rank = 4 if candidate_name == "bridge" else 3
        elif not malformed:
            trust_rank = 2 if candidate_name == "bridge" else 1
        if snapshot_source in {"storage_fallback", "app_runtime_storage_fallback"}:
            trust_rank = max(trust_rank - 2, 0)
        return {
            "name": candidate_name,
            "payload": raw,
            "bots": bots_list,
            "valid": not malformed,
            "partial": partial,
            "stale_data": stale_data,
            "error": error,
            "snapshot_ts": snapshot_ts or None,
            "snapshot_epoch": snapshot_epoch or None,
            "snapshot_age_sec": snapshot_age_sec,
            "snapshot_source": snapshot_source,
            "runtime_truth_count": runtime_truth_count,
            "bot_count": len(bots_list) if valid_bots_shape else 0,
            "trust_rank": trust_rank,
            "runtime_publish_ts": runtime_publish_ts or None,
            "latest_readiness_generated_ts": latest_readiness_generated_ts or None,
            "readiness_latency": readiness_latency,
        }

    @classmethod
    def _compare_candidates(
        cls,
        bridge_candidate: Dict[str, Any],
        app_candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        malformed_sources = [
            item["name"]
            for item in (bridge_candidate, app_candidate)
            if item and not bool(item.get("valid"))
        ]
        if not bridge_candidate.get("valid") or not app_candidate.get("valid"):
            return {
                "detected": bool(malformed_sources),
                "missing_bot_ids": [],
                "status_conflicts": [],
                "readiness_conflicts": [],
                "malformed_sources": malformed_sources,
            }

        bridge_lookup = {
            str(bot.get("id") or "").strip(): bot
            for bot in bridge_candidate.get("bots") or []
            if str(bot.get("id") or "").strip()
        }
        app_lookup = {
            str(bot.get("id") or "").strip(): bot
            for bot in app_candidate.get("bots") or []
            if str(bot.get("id") or "").strip()
        }
        bridge_ids = set(bridge_lookup)
        app_ids = set(app_lookup)
        missing_bot_ids = sorted((bridge_ids ^ app_ids))
        status_conflicts: List[str] = []
        readiness_conflicts: List[str] = []
        for bot_id in sorted(bridge_ids & app_ids):
            bridge_bot = bridge_lookup[bot_id]
            app_bot = app_lookup[bot_id]
            bridge_status = str(bridge_bot.get("status") or "").strip().lower()
            app_status = str(app_bot.get("status") or "").strip().lower()
            if bridge_status and app_status and bridge_status != app_status:
                status_conflicts.append(bot_id)
            bridge_ready = str(
                bridge_bot.get("setup_timing_status")
                or bridge_bot.get("setup_ready_status")
                or bridge_bot.get("analysis_ready_status")
                or bridge_bot.get("entry_ready_status")
                or ""
            ).strip().lower()
            app_ready = str(
                app_bot.get("setup_timing_status")
                or app_bot.get("setup_ready_status")
                or app_bot.get("analysis_ready_status")
                or app_bot.get("entry_ready_status")
                or ""
            ).strip().lower()
            if bridge_ready and app_ready and bridge_ready != app_ready:
                readiness_conflicts.append(bot_id)
        return {
            "detected": bool(
                missing_bot_ids or status_conflicts or readiness_conflicts or malformed_sources
            ),
            "missing_bot_ids": missing_bot_ids[:10],
            "status_conflicts": status_conflicts[:10],
            "readiness_conflicts": readiness_conflicts[:10],
            "malformed_sources": malformed_sources,
        }

    def _choose_candidate(
        self,
        bridge_candidate: Dict[str, Any],
        app_candidate: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        rejected: List[Dict[str, Any]] = []

        if bridge_candidate.get("valid") and not bridge_candidate.get("partial") and not bridge_candidate.get("stale_data"):
            if app_candidate.get("valid") and app_candidate.get("snapshot_ts") and bridge_candidate.get("snapshot_ts"):
                if (
                    app_candidate["snapshot_ts"] > bridge_candidate["snapshot_ts"]
                    and app_candidate.get("runtime_truth_count", 0)
                    > bridge_candidate.get("runtime_truth_count", 0)
                    and bridge_candidate.get("snapshot_age_sec") is not None
                    and bridge_candidate["snapshot_age_sec"] > 1.5
                ):
                    rejected.append(
                        {
                            "source": "bridge",
                            "reason": "older_than_app_rebuild",
                        }
                    )
                    return app_candidate, rejected
            return bridge_candidate, rejected

        if bridge_candidate.get("valid") and bridge_candidate.get("partial"):
            rejected.append({"source": "bridge", "reason": "partial_payload"})
        elif bridge_candidate.get("valid") and bridge_candidate.get("stale_data"):
            rejected.append({"source": "bridge", "reason": "stale"})
        elif bridge_candidate.get("payload"):
            rejected.append({"source": "bridge", "reason": "invalid_shape"})

        if app_candidate.get("valid") and not app_candidate.get("partial") and not app_candidate.get("stale_data"):
            return app_candidate, rejected

        if app_candidate.get("valid") and app_candidate.get("partial"):
            rejected.append({"source": "app", "reason": "partial_payload"})
        elif app_candidate.get("valid") and app_candidate.get("stale_data"):
            rejected.append({"source": "app", "reason": "stale"})
        elif app_candidate.get("payload"):
            rejected.append({"source": "app", "reason": "invalid_shape"})

        if bridge_candidate.get("valid"):
            return bridge_candidate, rejected
        if app_candidate.get("valid"):
            return app_candidate, rejected
        return None, rejected

    def _candidate_regresses(
        self,
        candidate: Optional[Dict[str, Any]],
        *,
        last_good_payload: Optional[Dict[str, Any]],
        last_good_summary: Dict[str, Any],
        now_ts: float,
    ) -> Tuple[bool, Optional[str]]:
        if candidate is None:
            return True, "no_valid_candidate"
        if not candidate.get("valid"):
            return True, "invalid_shape"
        if not last_good_payload:
            return False, None

        last_snapshot_ts = self._safe_float(last_good_summary.get("selected_snapshot_ts"), 0.0)
        candidate_snapshot_ts = self._safe_float(candidate.get("snapshot_ts"), 0.0)
        if (
            candidate_snapshot_ts > 0
            and last_snapshot_ts > 0
            and candidate_snapshot_ts + 0.0001 < last_snapshot_ts
        ):
            return True, "older_snapshot"

        last_good_age = (
            max(now_ts - last_snapshot_ts, 0.0) if last_snapshot_ts > 0 else float("inf")
        )
        if last_good_age > self.HOLD_LAST_GOOD_SEC:
            return False, None

        last_truth_count = self._safe_int(last_good_summary.get("selected_runtime_truth_count"), 0)
        candidate_truth_count = self._safe_int(candidate.get("runtime_truth_count"), 0)
        if candidate.get("stale_data"):
            if (
                candidate.get("bot_count", 0) == 0
                or candidate_truth_count == 0
                or candidate_truth_count < last_truth_count
            ):
                return True, "stale_partial_regression"
        if candidate.get("partial") and last_truth_count > 0:
                return True, "partial_payload"
        return False, None

    @staticmethod
    def _derive_bridge_action(
        *,
        selected_candidate: Optional[Dict[str, Any]],
        rejected: List[Dict[str, Any]],
        held_last_good: bool = False,
    ) -> Tuple[str, Optional[str]]:
        if held_last_good:
            return "held_last_good", None
        rejected_bridge = [
            item
            for item in list(rejected or [])
            if str(item.get("source") or "").strip().lower() == "bridge"
        ]
        bridge_reason = (
            str(rejected_bridge[0].get("reason") or "").strip().lower() or None
            if rejected_bridge
            else None
        )
        if selected_candidate is None:
            return "unavailable", bridge_reason
        selected_name = str(selected_candidate.get("name") or "").strip().lower()
        if selected_name == "bridge":
            return "accepted", bridge_reason
        if selected_name == "app":
            return "rebuilt_from_app", bridge_reason or "bridge_unavailable"
        return "unavailable", bridge_reason

    def _hold_last_good(
        self,
        *,
        last_good_payload: Dict[str, Any],
        last_good_summary: Dict[str, Any],
        now_ts: float,
        dropped_reason: str,
        candidate_sources: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        held = self._copy(last_good_payload)
        held_error = held.get("error") or dropped_reason
        held["stale_data"] = True
        held["error"] = str(held_error)
        summary = self._default_summary()
        summary.update(self._copy(last_good_summary))
        summary.update(
            {
                "status": "stale_guard" if dropped_reason != "older_snapshot" else "degraded",
                "runtime_state_source": "held_last_good",
                "stale_guard_active": True,
                "stale_guard_reason": dropped_reason,
                "dropped_as_stale": True,
                "dropped_reason": dropped_reason,
                "resync_requested": True,
                "preserved_from_last_known_good": True,
                "app_heartbeat_age_sec": 0.0,
                "candidate_sources": candidate_sources,
            }
        )
        last_good_ts = self._safe_float(last_good_summary.get("selected_snapshot_ts"), 0.0)
        if last_good_ts > 0:
            summary["runtime_state_age_sec"] = round(max(now_ts - last_good_ts, 0.0), 3)
            summary["last_known_good_age_sec"] = summary["runtime_state_age_sec"]
        held["runtime_integrity"] = summary
        return held

    def _classify_start_state(
        self,
        *,
        bot: Optional[Dict[str, Any]],
        pending_entry: Dict[str, Any],
        now_ts: float,
    ) -> str:
        accepted_at_ts = self._safe_float(pending_entry.get("accepted_at_ts"), 0.0)
        age_sec = max(now_ts - accepted_at_ts, 0.0) if accepted_at_ts > 0 else 0.0
        if age_sec <= self.START_ACCEPTED_SEC:
            return "accepted"
        if not isinstance(bot, dict):
            if age_sec <= self.START_PENDING_SEC:
                return "pending_runner_pickup"
            return "stalled"
        status = str(bot.get("status") or "").strip().lower()
        if status not in self._RUNNING_STATUSES:
            if age_sec <= self.START_PENDING_SEC:
                return "pending_runner_pickup"
            return "stalled"
        last_run_ts = self._parse_iso_ts(bot.get("last_run_at"))
        started_ts = self._parse_iso_ts(bot.get("started_at"))
        if last_run_ts > 0 and last_run_ts + 0.5 >= max(accepted_at_ts, started_ts):
            return "runtime_active"
        if age_sec <= self.START_PENDING_SEC:
            return "pending_runner_pickup"
        return "stalled"

    def _annotate_startup_state(
        self,
        bots: List[Dict[str, Any]],
        *,
        last_good_payload: Optional[Dict[str, Any]],
        now_ts: float,
        summary: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        bot_list = [dict(bot) for bot in list(bots or []) if isinstance(bot, dict)]
        by_id = {
            str(bot.get("id") or "").strip(): bot
            for bot in bot_list
            if str(bot.get("id") or "").strip()
        }
        last_good_lookup = {
            str(bot.get("id") or "").strip(): dict(bot)
            for bot in list((last_good_payload or {}).get("bots") or [])
            if isinstance(bot, dict) and str(bot.get("id") or "").strip()
        }
        startup_pending_ids: List[str] = []
        startup_stalled_ids: List[str] = []
        held_bot_count = 0
        to_drop: List[str] = []

        for bot_id, entry in list(self._pending_starts.items()):
            accepted_at_ts = self._safe_float(entry.get("accepted_at_ts"), 0.0)
            if accepted_at_ts > 0 and (now_ts - accepted_at_ts) > self.START_RETENTION_SEC:
                to_drop.append(bot_id)
                continue
            current_bot = by_id.get(bot_id)
            start_state = self._classify_start_state(
                bot=current_bot,
                pending_entry=entry,
                now_ts=now_ts,
            )
            if start_state == "runtime_active":
                to_drop.append(bot_id)
                continue

            target_bot = current_bot
            held_from_state = False
            if target_bot is None:
                target_bot = dict(entry.get("bot_snapshot") or last_good_lookup.get(bot_id) or {})
                if target_bot:
                    held_from_state = True
                    target_bot.setdefault("id", bot_id)
                    target_bot.setdefault("symbol", entry.get("symbol"))
                    target_bot.setdefault("status", "running")
                    bot_list.append(target_bot)
                    by_id[bot_id] = target_bot
                    held_bot_count += 1
            if not isinstance(target_bot, dict) or not target_bot:
                continue

            target_bot["runtime_start_state"] = start_state
            target_bot["runtime_start_lifecycle"] = (
                "startup_stalled" if start_state == "stalled" else start_state
            )
            target_bot["startup_pending"] = start_state in {"accepted", "pending_runner_pickup"}
            target_bot["startup_stalled"] = start_state == "stalled"
            target_bot["runtime_state_held"] = held_from_state
            target_bot["runtime_state_held_reason"] = "startup_pending" if held_from_state else None
            target_bot["runtime_state_integrity"] = (
                "stalled" if start_state == "stalled" else "startup_pending"
            )

            if start_state in {"accepted", "pending_runner_pickup"}:
                startup_pending_ids.append(bot_id)
            elif start_state == "stalled":
                startup_stalled_ids.append(bot_id)

        for bot_id in to_drop:
            self._pending_starts.pop(bot_id, None)

        summary["startup_pending_count"] = len(startup_pending_ids)
        summary["startup_stalled_count"] = len(startup_stalled_ids)
        summary["startup_pending"] = bool(startup_pending_ids)
        summary["startup_stalled"] = bool(startup_stalled_ids)
        summary["held_bot_count"] = held_bot_count
        summary["startup"] = {
            "pending_bot_ids": startup_pending_ids[:10],
            "stalled_bot_ids": startup_stalled_ids[:10],
        }
        return bot_list

    def _record_oscillation(
        self,
        bots: List[Dict[str, Any]],
        *,
        now_ts: float,
        summary: Dict[str, Any],
    ) -> None:
        current_lookup = {
            str(bot.get("id") or "").strip(): bot
            for bot in list(bots or [])
            if isinstance(bot, dict) and str(bot.get("id") or "").strip()
        }
        candidate_ids = set(current_lookup) | set(self._last_observed_bot_state)
        visible_flips = 0
        ready_flips = 0
        affected: List[str] = []

        for bot_id in candidate_ids:
            visible = bot_id in current_lookup
            ready_visible = self._ready_visible(current_lookup.get(bot_id) or {})
            previous = self._last_observed_bot_state.get(bot_id)
            if previous is not None:
                if bool(previous.get("visible")) != visible:
                    self._bot_transition_history.setdefault(bot_id, []).append(
                        {"ts": now_ts, "kind": "visible"}
                    )
                elif bool(previous.get("ready_visible")) != ready_visible:
                    self._bot_transition_history.setdefault(bot_id, []).append(
                        {"ts": now_ts, "kind": "ready"}
                    )
            self._last_observed_bot_state[bot_id] = {
                "visible": visible,
                "ready_visible": ready_visible,
            }

        cutoff = now_ts - self.OSCILLATION_WINDOW_SEC
        for bot_id, history in list(self._bot_transition_history.items()):
            recent = [
                item
                for item in list(history or [])
                if isinstance(item, dict) and self._safe_float(item.get("ts"), 0.0) >= cutoff
            ]
            if recent:
                self._bot_transition_history[bot_id] = recent[-8:]
            else:
                self._bot_transition_history.pop(bot_id, None)
                continue
            visible_count = sum(1 for item in recent if item.get("kind") == "visible")
            ready_count = sum(1 for item in recent if item.get("kind") == "ready")
            if visible_count >= self.OSCILLATION_MIN_FLIPS or ready_count >= self.OSCILLATION_MIN_FLIPS:
                visible_flips += visible_count
                ready_flips += ready_count
                affected.append(bot_id)

        summary["oscillation"] = {
            "visible_flips": visible_flips,
            "ready_flips": ready_flips,
            "affected_bot_ids": affected[:10],
        }
        summary["oscillation_detected"] = bool(affected)
        summary["bot_visibility_oscillation"] = visible_flips >= self.OSCILLATION_MIN_FLIPS
        summary["ready_state_oscillation"] = ready_flips >= self.OSCILLATION_MIN_FLIPS

    def record_start_accepted(self, bot: Optional[Dict[str, Any]]) -> None:
        if not isinstance(bot, dict):
            return
        bot_id = str(bot.get("id") or "").strip()
        if not bot_id:
            return
        accepted_at_ts = self._parse_iso_ts(bot.get("started_at")) or time.time()
        with self._lock:
            self._pending_starts[bot_id] = {
                "bot_id": bot_id,
                "symbol": str(bot.get("symbol") or "").strip().upper() or None,
                "accepted_at": datetime.fromtimestamp(
                    accepted_at_ts, tz=timezone.utc
                ).isoformat(),
                "accepted_at_ts": accepted_at_ts,
                "bot_snapshot": {
                    "id": bot_id,
                    "symbol": bot.get("symbol"),
                    "mode": bot.get("mode"),
                    "status": bot.get("status") or "running",
                    "started_at": bot.get("started_at"),
                    "last_run_at": bot.get("last_run_at"),
                },
            }

    def register_start(self, bot: Optional[Dict[str, Any]], *, action: str = "start") -> None:
        self.record_start_accepted(bot)

    def should_probe_direct_runtime(
        self,
        bridge_payload: Optional[Dict[str, Any]],
    ) -> bool:
        candidate = self._normalize_candidate(
            bridge_payload,
            candidate_name="bridge",
            now_ts=time.time(),
        )
        if not candidate.get("valid"):
            return True
        if candidate.get("partial") or candidate.get("stale_data"):
            return True
        # A fresh runner bridge is authoritative enough to surface pending-start
        # state via resolve_runtime_bots(); forcing an app-side rebuild here
        # only re-enters stopped-preview/readiness work on the dashboard path.
        return False

    def get_last_summary(self) -> Dict[str, Any]:
        with self._lock:
            return self._copy(self._last_summary)

    def resolve_bots_payload(
        self,
        *,
        bridge_payload: Optional[Dict[str, Any]],
        direct_payload: Optional[Dict[str, Any]],
        runner_heartbeat_age_sec: Optional[float],
        runner_active: bool,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        runner_health = {
            "runner_heartbeat_age_sec": runner_heartbeat_age_sec,
            "runner_active": bool(runner_active),
        }
        return self.resolve_runtime_bots(
            bridge_payload=bridge_payload,
            app_payload=direct_payload,
            runner_health=runner_health,
            now_ts=now_ts,
        )

    def resolve_runtime_bots(
        self,
        *,
        bridge_payload: Optional[Dict[str, Any]],
        app_payload: Optional[Dict[str, Any]],
        runner_health: Optional[Dict[str, Any]] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        now_ts = float(now_ts if now_ts is not None else time.time())
        bridge_candidate = self._normalize_candidate(
            bridge_payload,
            candidate_name="bridge",
            now_ts=now_ts,
        )
        app_candidate = self._normalize_candidate(
            app_payload,
            candidate_name="app",
            now_ts=now_ts,
        )
        divergence = self._compare_candidates(bridge_candidate, app_candidate)
        candidate_sources = [
            {
                "source": item["name"],
                "selected_source": item["snapshot_source"],
                "valid": bool(item["valid"]),
                "partial": bool(item["partial"]),
                "stale_data": bool(item["stale_data"]),
                "snapshot_age_sec": item["snapshot_age_sec"],
                "snapshot_ts": item["snapshot_ts"],
                "snapshot_epoch": item["snapshot_epoch"],
                "runtime_truth_count": item["runtime_truth_count"],
                "bot_count": item["bot_count"],
                "error": item["error"],
                "runtime_publish_ts": item.get("runtime_publish_ts"),
                "latest_readiness_generated_ts": item.get("latest_readiness_generated_ts"),
            }
            for item in (bridge_candidate, app_candidate)
            if item.get("payload") or item.get("valid")
        ]

        with self._lock:
            selected_candidate, rejected = self._choose_candidate(
                bridge_candidate,
                app_candidate,
            )
            last_good_payload = self._copy(self._last_good_payload)
            last_good_summary = self._copy(self._last_good_summary)
            should_hold, dropped_reason = self._candidate_regresses(
                selected_candidate,
                last_good_payload=last_good_payload,
                last_good_summary=last_good_summary,
                now_ts=now_ts,
            )
            if should_hold and last_good_payload:
                held = self._hold_last_good(
                    last_good_payload=last_good_payload,
                    last_good_summary=last_good_summary,
                    now_ts=now_ts,
                    dropped_reason=dropped_reason or "stale_regression",
                    candidate_sources=candidate_sources,
                )
                held_summary = dict(held.get("runtime_integrity") or {})
                bridge_action, bridge_rejected_reason = self._derive_bridge_action(
                    selected_candidate=selected_candidate,
                    rejected=rejected,
                    held_last_good=True,
                )
                held_summary["divergence_detected"] = bool(divergence.get("detected"))
                held_summary["divergence_reasons"] = [
                    reason
                    for reason, values in (
                        ("bot_membership_mismatch", divergence.get("missing_bot_ids")),
                        ("bot_status_conflict", divergence.get("status_conflicts")),
                        ("readiness_conflict", divergence.get("readiness_conflicts")),
                        ("malformed_source", divergence.get("malformed_sources")),
                    )
                    if values
                ]
                held_summary["divergence"] = divergence
                held_summary["candidate_sources"] = candidate_sources
                held_summary["bridge_action"] = bridge_action
                held_summary["bridge_rejected_reason"] = bridge_rejected_reason
                held_summary["held_last_good"] = True
                held_summary["rebuilt_from_app"] = False
                held_summary["runner_heartbeat_age_sec"] = (
                    self._safe_float(runner_health.get("runner_heartbeat_age_sec"), 0.0)
                    if isinstance(runner_health, dict)
                    and runner_health.get("runner_heartbeat_age_sec") is not None
                    else None
                )
                bots = self._annotate_startup_state(
                    list(held.get("bots") or []),
                    last_good_payload=last_good_payload,
                    now_ts=now_ts,
                    summary=held_summary,
                )
                held["bots"] = bots
                self._record_oscillation(bots, now_ts=now_ts, summary=held_summary)
                held_summary["effective_bot_count"] = len(list(bots or []))
                held_summary["effective_ready_count"] = sum(
                    1 for bot in list(bots or []) if self._ready_visible(bot)
                )
                held_summary["no_active_bot_stable"] = not held_summary.get("bot_visibility_oscillation")
                held_summary["runtime_integrity_state"] = held_summary.get("status")
                if held_summary.get("startup_stalled_count"):
                    held_summary["status"] = "startup_stalled"
                elif held_summary.get("divergence_detected"):
                    held_summary["status"] = "divergent"
                held_summary["runtime_integrity_state"] = held_summary.get("status")
                held["bridge_age_ms"] = held_summary.get("bridge_age_ms")
                held["runtime_snapshot_age_ms"] = held_summary.get("runtime_snapshot_age_ms")
                held["runtime_integrity_state"] = held_summary.get("runtime_integrity_state")
                held["held_last_good"] = True
                held["rebuilt_from_app"] = False
                held["runtime_integrity"] = held_summary
                self._last_summary = self._copy(held_summary)
                return held

            selected_payload = self._copy(selected_candidate.get("payload") if selected_candidate else {})
            selected_bots = list(selected_candidate.get("bots") or [])
            bridge_action, bridge_rejected_reason = self._derive_bridge_action(
                selected_candidate=selected_candidate,
                rejected=rejected,
            )
            summary = self._default_summary()
            summary.update(
                {
                    "runtime_state_source": (
                        selected_candidate.get("snapshot_source")
                        if selected_candidate
                        else "unavailable"
                    ),
                    "runtime_state_age_sec": (
                        selected_candidate.get("snapshot_age_sec")
                        if selected_candidate
                        else None
                    ),
                    "bridge_state_age_sec": bridge_candidate.get("snapshot_age_sec"),
                    "runner_heartbeat_age_sec": (
                        self._safe_float(runner_health.get("runner_heartbeat_age_sec"), 0.0)
                        if isinstance(runner_health, dict)
                        and runner_health.get("runner_heartbeat_age_sec") is not None
                        else bridge_candidate.get("snapshot_age_sec")
                    ),
                    "app_heartbeat_age_sec": 0.0,
                    "bridge_age_ms": (
                        round(max((bridge_candidate.get("snapshot_age_sec") or 0.0), 0.0) * 1000.0, 2)
                        if bridge_candidate.get("snapshot_age_sec") is not None
                        else None
                    ),
                    "runtime_snapshot_age_ms": (
                        round(max(now_ts - float(selected_candidate.get("runtime_publish_ts") or 0.0), 0.0) * 1000.0, 2)
                        if selected_candidate and selected_candidate.get("runtime_publish_ts")
                        else None
                    ),
                    "runtime_publish_age_ms": (
                        round(max(now_ts - float(selected_candidate.get("runtime_publish_ts") or 0.0), 0.0) * 1000.0, 2)
                        if selected_candidate and selected_candidate.get("runtime_publish_ts")
                        else None
                    ),
                    "selected_runtime_publish_at": (
                        datetime.fromtimestamp(
                            float(selected_candidate.get("runtime_publish_ts") or 0.0),
                            tz=timezone.utc,
                        ).isoformat()
                        if selected_candidate and selected_candidate.get("runtime_publish_ts")
                        else None
                    ),
                    "selected_runtime_publish_ts": (
                        selected_candidate.get("runtime_publish_ts") if selected_candidate else None
                    ),
                    "selected_readiness_generated_at": (
                        datetime.fromtimestamp(
                            float(selected_candidate.get("latest_readiness_generated_ts") or 0.0),
                            tz=timezone.utc,
                        ).isoformat()
                        if selected_candidate and selected_candidate.get("latest_readiness_generated_ts")
                        else None
                    ),
                    "selected_readiness_age_ms": (
                        round(
                            max(
                                now_ts - float(selected_candidate.get("latest_readiness_generated_ts") or 0.0),
                                0.0,
                            )
                            * 1000.0,
                            2,
                        )
                        if selected_candidate and selected_candidate.get("latest_readiness_generated_ts")
                        else None
                    ),
                    "bridge_action": bridge_action,
                    "bridge_rejected_reason": bridge_rejected_reason,
                    "held_last_good": False,
                    "rebuilt_from_app": bridge_action == "rebuilt_from_app",
                    "last_known_good_runtime_at": (
                        datetime.fromtimestamp(
                            self._safe_float(last_good_summary.get("selected_snapshot_ts"), 0.0),
                            tz=timezone.utc,
                        ).isoformat()
                        if self._safe_float(last_good_summary.get("selected_snapshot_ts"), 0.0) > 0
                        else None
                    ),
                    "last_known_good_age_sec": (
                        round(
                            max(
                                now_ts - self._safe_float(last_good_summary.get("selected_snapshot_ts"), 0.0),
                                0.0,
                            ),
                            3,
                        )
                        if self._safe_float(last_good_summary.get("selected_snapshot_ts"), 0.0) > 0
                        else None
                    ),
                    "stale_guard_active": False,
                    "divergence_detected": bool(divergence.get("detected")),
                    "divergence_reasons": [
                        reason
                        for reason, values in (
                            ("bot_membership_mismatch", divergence.get("missing_bot_ids")),
                            ("bot_status_conflict", divergence.get("status_conflicts")),
                            ("readiness_conflict", divergence.get("readiness_conflicts")),
                            ("malformed_source", divergence.get("malformed_sources")),
                        )
                        if values
                    ],
                    "dropped_as_stale": False,
                    "dropped_reason": None,
                    "resync_requested": bool(
                        not selected_candidate
                        or not selected_candidate.get("valid")
                        or selected_candidate.get("stale_data")
                        or divergence.get("detected")
                    ),
                    "selected_bot_count": len(selected_bots),
                    "selected_runtime_truth_count": (
                        selected_candidate.get("runtime_truth_count") if selected_candidate else 0
                    ),
                    "selected_snapshot_ts": (
                        selected_candidate.get("snapshot_ts") if selected_candidate else None
                    ),
                    "selected_snapshot_epoch": (
                        selected_candidate.get("snapshot_epoch") if selected_candidate else None
                    ),
                    "selected_stale_data": (
                        bool(selected_candidate.get("stale_data")) if selected_candidate else True
                    ),
                    "selected_error": (
                        selected_candidate.get("error") if selected_candidate else "runtime_unavailable"
                    ),
                    "candidate_sources": candidate_sources + rejected,
                    "divergence": divergence,
                }
            )

            if selected_candidate is None:
                selected_payload = {
                    "bots": [],
                    "stale_data": True,
                    "error": "runtime_state_unavailable",
                }
                summary["status"] = "degraded"
            elif selected_candidate.get("stale_data"):
                summary["status"] = "degraded"
            elif divergence.get("detected"):
                summary["status"] = "divergent"
            else:
                summary["status"] = "healthy"

            bots = self._annotate_startup_state(
                selected_bots,
                last_good_payload=last_good_payload,
                now_ts=now_ts,
                summary=summary,
            )
            if summary.get("startup_stalled_count"):
                summary["status"] = "startup_stalled"

            self._record_oscillation(bots, now_ts=now_ts, summary=summary)
            if summary.get("oscillation_detected") and summary["status"] == "healthy":
                summary["status"] = "oscillating"
            summary["runtime_integrity_state"] = summary["status"]
            summary["effective_bot_count"] = len(list(bots or []))
            summary["effective_ready_count"] = sum(
                1 for bot in list(bots or []) if self._ready_visible(bot)
            )
            summary["no_active_bot_stable"] = not summary.get("bot_visibility_oscillation")

            selected_payload["bots"] = bots
            selected_payload["bridge_age_ms"] = summary.get("bridge_age_ms")
            selected_payload["runtime_snapshot_age_ms"] = summary.get("runtime_snapshot_age_ms")
            selected_payload["runtime_integrity_state"] = summary.get("runtime_integrity_state")
            selected_payload["held_last_good"] = summary.get("held_last_good")
            selected_payload["rebuilt_from_app"] = summary.get("rebuilt_from_app")
            selected_payload["runtime_integrity"] = summary

            if selected_candidate and selected_candidate.get("valid") and not selected_candidate.get("stale_data"):
                self._last_good_payload = self._copy(selected_payload)
                self._last_good_summary = self._copy(summary)

            self._last_summary = self._copy(summary)
            return selected_payload
