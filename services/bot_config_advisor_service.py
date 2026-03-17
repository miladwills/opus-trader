from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from services.bot_triage_action_service import BotTriageSettingsConflictError


class BotConfigAdvisorApplyBlockedError(ValueError):
    def __init__(self, *, bot_id: str, blocked_reason: str, payload: Dict[str, Any]) -> None:
        super().__init__(blocked_reason)
        self.bot_id = bot_id
        self.blocked_reason = blocked_reason
        self.payload = dict(payload or {})


class BotConfigAdvisorService:
    """Read-only, rule-based config tuning recommendations built from live diagnostics."""

    VERDICT_PRIORITY = {
        "REDUCE_RISK": 0,
        "WIDEN_STRUCTURE": 1,
        "REVIEW_MANUALLY": 2,
        "KEEP_CURRENT": 3,
    }
    CONFIDENCE_PRIORITY = {
        "high": 0,
        "medium": 1,
        "low": 2,
    }
    SUPPORTED_APPLY_FIELDS = {
        "leverage",
        "grid_count",
        "target_grid_count",
        "grid_distribution",
        "session_timer_enabled",
        "session_start_at",
        "session_stop_at",
        "session_no_new_entries_before_stop_min",
        "session_end_mode",
        "session_green_grace_min",
        "session_cancel_pending_orders_on_end",
        "session_reduce_only_on_end",
    }
    ADVISORY_ONLY_FIELDS = ("range_posture", "step_posture")
    SESSION_PRESET_FIELDS = (
        "session_timer_enabled",
        "session_start_at",
        "session_stop_at",
        "session_no_new_entries_before_stop_min",
        "session_end_mode",
        "session_green_grace_min",
        "session_cancel_pending_orders_on_end",
        "session_reduce_only_on_end",
    )
    DEFAULT_SLEEP_DURATION_HOURS = 2

    def __init__(
        self,
        *,
        bot_triage_service: Any,
        bot_storage: Optional[Any] = None,
        bot_manager: Optional[Any] = None,
        runtime_settings_service: Optional[Any] = None,
        config_integrity_watchdog_service: Optional[Any] = None,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.bot_triage_service = bot_triage_service
        self.bot_storage = bot_storage
        self.bot_manager = bot_manager
        self.runtime_settings_service = runtime_settings_service
        self.config_integrity_watchdog_service = config_integrity_watchdog_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def build_snapshot(
        self,
        *,
        runtime_bots: Optional[Iterable[Dict[str, Any]]] = None,
        stale_data: bool = False,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = self.bot_triage_service.collect_context(runtime_bots=runtime_bots)
        generated_at = str(context.get("generated_at") or self.now_fn().isoformat())
        bots = list(context.get("bots") or [])
        review_lookup = dict(context.get("review_lookup") or {})
        active_by_bot = dict(context.get("active_by_bot") or {})
        queue_lookup = self._queue_lookup()

        items: List[Dict[str, Any]] = []
        summary_counts = {verdict: 0 for verdict in self.VERDICT_PRIORITY}
        for bot in bots:
            bot_id = str(bot.get("id") or "").strip()
            triage_analysis = self.bot_triage_service.build_analysis(
                bot=bot,
                review=review_lookup.get(bot_id, {}),
                active_issues=active_by_bot.get(bot_id, []),
                generated_at=generated_at,
            )
            item = self._build_item(
                bot=dict(bot),
                triage_analysis=triage_analysis,
                generated_at=generated_at,
                queued_apply=queue_lookup.get(bot_id),
            )
            items.append(item)
            summary_counts[item["tuning_verdict"]] = int(
                summary_counts.get(item["tuning_verdict"], 0) or 0
            ) + 1

        items.sort(key=self._sort_key)
        payload = {
            "generated_at": generated_at,
            "total_bots": len(items),
            "summary_counts": summary_counts,
            "items": items,
        }
        if stale_data:
            payload["stale_data"] = True
            payload["error"] = str(error or "bots_runtime_stale")
        return payload

    def _build_item(
        self,
        *,
        bot: Dict[str, Any],
        triage_analysis: Dict[str, Any],
        generated_at: str,
        queued_apply: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        checks = dict(triage_analysis.get("checks") or {})
        triage_item = dict(triage_analysis.get("item") or {})
        current_settings = self._build_current_settings(bot)
        tuning = self._determine_tuning(
            bot=bot,
            checks=checks,
            triage_item=triage_item,
            current_settings=current_settings,
        )
        apply_plan = self._build_apply_plan(
            bot=bot,
            tuning_verdict=tuning["tuning_verdict"],
            current_settings=current_settings,
            recommended_settings=tuning["recommended_settings"],
        )
        is_flat_now = self._is_flat_now(bot)
        active_queue = dict(queued_apply or {}) if isinstance(queued_apply, dict) else None
        return {
            "bot_id": str(bot.get("id") or "").strip() or None,
            "symbol": str(bot.get("symbol") or "").strip().upper() or None,
            "mode": str(bot.get("mode") or "").strip().lower() or None,
            "tuning_verdict": tuning["tuning_verdict"],
            "confidence": tuning["confidence"],
            "current_settings": current_settings,
            "recommended_settings": tuning["recommended_settings"],
            "reasons": tuning["reasons"][:4],
            "rationale": tuning["rationale"],
            "suggested_preset": tuning["suggested_preset"],
            "supports_apply": bool(apply_plan.get("supports_apply")),
            "is_flat_now": is_flat_now,
            "can_apply_now": bool(apply_plan.get("supports_apply")) and is_flat_now and not active_queue,
            "can_queue_until_flat": bool(apply_plan.get("supports_apply")) and not is_flat_now and not active_queue,
            "applicable_fields": list(apply_plan.get("applicable_fields") or []),
            "advisory_only_fields": list(apply_plan.get("advisory_only_fields") or []),
            "queued_apply": active_queue,
            "source_signals": self._build_source_signals(
                bot=bot,
                checks=checks,
                triage_item=triage_item,
                confidence=tuning["confidence"],
            ),
            "generated_at": generated_at,
        }

    def preview_apply(
        self,
        bot_id: str,
        *,
        runtime_bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        stored_bot, effective_bot = self._resolve_bot_state(bot_id, runtime_bot=runtime_bot)
        item = self.get_recommendation_for_bot(bot_id, runtime_bot=runtime_bot)
        preview = self._build_apply_preview(bot=effective_bot, item=item)
        return {
            "ok": True,
            "bot_id": str(stored_bot.get("id") or "").strip() or None,
            "preview": preview,
        }

    def apply_recommendation(
        self,
        bot_id: str,
        *,
        incoming_settings_version: Any,
        runtime_bot: Optional[Dict[str, Any]] = None,
        ui_path: str = "config_advisor",
    ) -> Dict[str, Any]:
        stored_bot, effective_bot = self._resolve_bot_state(bot_id, runtime_bot=runtime_bot)
        item = self.get_recommendation_for_bot(bot_id, runtime_bot=runtime_bot)
        preview = self._build_apply_preview(bot=effective_bot, item=item)
        now_iso = self.now_fn().isoformat()
        advisory_only_fields = list(preview.get("advisory_only_fields") or [])
        applicable_fields = list(preview.get("applicable_fields") or [])
        self._record_action(
            event_type="config_advisor_apply_attempt",
            bot=effective_bot,
            fields_applied=applicable_fields,
            advisory_only_fields=advisory_only_fields,
            metadata={
                "recommendation_type": item.get("tuning_verdict"),
            },
        )
        if not preview.get("supports_apply"):
            blocked_payload = self._build_blocked_payload(
                bot=effective_bot,
                preview=preview,
                blocked_reason="no_supported_changes",
            )
            self._record_action(
                event_type="config_advisor_apply_blocked",
                bot=effective_bot,
                fields_applied=[],
                advisory_only_fields=advisory_only_fields,
                metadata={"blocked_reason": "no_supported_changes"},
            )
            raise BotConfigAdvisorApplyBlockedError(
                bot_id=str(effective_bot.get("id") or "").strip(),
                blocked_reason="no_supported_changes",
                payload=blocked_payload,
            )
        if not preview.get("is_flat_now", False):
            blocked_payload = self._build_blocked_payload(
                bot=effective_bot,
                preview=preview,
                blocked_reason="requires_flat_state",
            )
            self._record_action(
                event_type="config_advisor_apply_blocked",
                bot=effective_bot,
                fields_applied=[],
                advisory_only_fields=advisory_only_fields,
                metadata={"blocked_reason": "requires_flat_state"},
            )
            raise BotConfigAdvisorApplyBlockedError(
                bot_id=str(effective_bot.get("id") or "").strip(),
                blocked_reason="requires_flat_state",
                payload=blocked_payload,
            )
        try:
            self._ensure_settings_version(
                stored_bot,
                incoming_settings_version,
                ui_path=ui_path,
            )
        except BotTriageSettingsConflictError:
            self._record_action(
                event_type="config_advisor_apply_blocked",
                bot=effective_bot,
                fields_applied=[],
                advisory_only_fields=advisory_only_fields,
                metadata={"blocked_reason": "settings_version_conflict"},
            )
            raise

        applicable_changes = dict(preview.get("applicable_changes_map") or {})
        merged = copy.deepcopy(stored_bot)
        merged.update(applicable_changes)
        saved_bot = self.bot_manager.create_or_update_bot(merged)
        persisted_bot = self.bot_storage.get_bot(str(saved_bot.get("id") or "").strip()) or saved_bot
        config_integrity_audit = None
        watchdog_service = self.config_integrity_watchdog_service
        if watchdog_service is not None:
            config_integrity_audit = watchdog_service.record_save_roundtrip(
                merged,
                saved_bot,
                persisted_bot=persisted_bot,
                previous_bot=stored_bot,
                ui_path=ui_path,
            )
        self._record_action(
            event_type="config_advisor_apply_success",
            bot=saved_bot,
            fields_applied=applicable_fields,
            advisory_only_fields=advisory_only_fields,
            metadata={
                "recommendation_type": item.get("tuning_verdict"),
            },
        )
        return {
            "ok": True,
            "bot_id": str(saved_bot.get("id") or "").strip() or None,
            "applied_fields": applicable_fields,
            "skipped_advisory_fields": advisory_only_fields,
            "blocked_reason": None,
            "new_settings_version": self._safe_int(saved_bot.get("settings_version"), 0),
            "generated_at": str(item.get("generated_at") or now_iso),
            "applied_at": now_iso,
            "config_integrity_audit": config_integrity_audit,
        }

    def queue_apply(
        self,
        bot_id: str,
        *,
        runtime_bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        stored_bot, effective_bot = self._resolve_bot_state(bot_id, runtime_bot=runtime_bot)
        item = self.get_recommendation_for_bot(bot_id, runtime_bot=runtime_bot)
        preview = self._build_apply_preview(bot=effective_bot, item=item)
        advisory_only_fields = list(preview.get("advisory_only_fields") or [])
        applicable_fields = list(preview.get("applicable_fields") or [])
        self._record_action(
            event_type="config_advisor_queue_attempt",
            bot=effective_bot,
            fields_applied=applicable_fields,
            advisory_only_fields=advisory_only_fields,
            metadata={"recommendation_type": item.get("tuning_verdict")},
        )
        if preview.get("is_flat_now", False):
            blocked_payload = self._build_queue_response(
                bot=effective_bot,
                state="blocked",
                queued_fields=applicable_fields,
                advisory_only_fields=advisory_only_fields,
                blocked_reason="already_flat_apply_now",
                queued_at=None,
            )
            raise BotConfigAdvisorApplyBlockedError(
                bot_id=str(effective_bot.get("id") or "").strip(),
                blocked_reason="already_flat_apply_now",
                payload=blocked_payload,
            )
        if not preview.get("supports_apply"):
            blocked_payload = self._build_queue_response(
                bot=effective_bot,
                state="blocked",
                queued_fields=[],
                advisory_only_fields=advisory_only_fields,
                blocked_reason="no_supported_changes",
                queued_at=None,
            )
            raise BotConfigAdvisorApplyBlockedError(
                bot_id=str(effective_bot.get("id") or "").strip(),
                blocked_reason="no_supported_changes",
                payload=blocked_payload,
            )
        queued_at = self.now_fn().isoformat()
        entry = {
            "state": "waiting_for_flat",
            "recommendation_type": item.get("tuning_verdict"),
            "base_settings_version": self._safe_int(stored_bot.get("settings_version"), 0),
            "applicable_changes": list(preview.get("applicable_changes") or []),
            "advisory_only_changes": list(preview.get("advisory_only_changes") or []),
            "queued_at": queued_at,
            "generated_at": preview.get("generated_at"),
            "symbol": effective_bot.get("symbol"),
            "blocked_reason": None,
        }
        self.runtime_settings_service.set_bot_config_advisor_queued_apply(bot_id, entry)
        self._record_action(
            event_type="config_advisor_queue_created",
            bot=effective_bot,
            fields_applied=applicable_fields,
            advisory_only_fields=advisory_only_fields,
            metadata={"state": "waiting_for_flat"},
        )
        return self._build_queue_response(
            bot=effective_bot,
            state="waiting_for_flat",
            queued_fields=applicable_fields,
            advisory_only_fields=advisory_only_fields,
            blocked_reason=None,
            queued_at=queued_at,
        )

    def cancel_queued_apply(self, bot_id: str) -> Dict[str, Any]:
        stored_bot = self._require_bot(bot_id)
        queue_entry = self._queue_lookup().get(str(bot_id or "").strip())
        queued_fields = list((queue_entry or {}).get("queued_fields") or [])
        advisory_only_fields = list((queue_entry or {}).get("advisory_only_fields") or [])
        self.runtime_settings_service.clear_bot_config_advisor_queued_apply(bot_id)
        self._record_action(
            event_type="config_advisor_queue_canceled",
            bot=stored_bot,
            fields_applied=queued_fields,
            advisory_only_fields=advisory_only_fields,
            metadata={"state": "canceled"},
        )
        return self._build_queue_response(
            bot=stored_bot,
            state="canceled",
            queued_fields=queued_fields,
            advisory_only_fields=advisory_only_fields,
            blocked_reason=None,
            queued_at=(queue_entry or {}).get("queued_at"),
        )

    def list_queued_applies(self) -> Dict[str, Any]:
        generated_at = self.now_fn().isoformat()
        items = []
        for bot_id, entry in self._queue_lookup().items():
            items.append(
                {
                    "bot_id": bot_id,
                    "state": entry.get("state"),
                    "queued_fields": list(entry.get("queued_fields") or []),
                    "advisory_only_fields": list(entry.get("advisory_only_fields") or []),
                    "blocked_reason": entry.get("blocked_reason"),
                    "queued_at": entry.get("queued_at"),
                    "applied_at": entry.get("applied_at"),
                    "updated_at": entry.get("updated_at"),
                }
            )
        items.sort(key=lambda item: (str(item.get("state") or ""), str(item.get("bot_id") or "")))
        return {
            "generated_at": generated_at,
            "total": len(items),
            "items": items,
        }

    def process_queued_applies(
        self,
        *,
        runtime_bots: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        runtime_lookup = {
            str(bot.get("id") or "").strip(): dict(bot)
            for bot in (runtime_bots or [])
            if isinstance(bot, dict) and str(bot.get("id") or "").strip()
        }
        for bot_id, entry in self._queue_lookup().items():
            state = str(entry.get("state") or "").strip().lower()
            if state not in {"queued", "waiting_for_flat"}:
                continue
            try:
                stored_bot = self._require_bot(bot_id)
            except ValueError:
                failed_entry = dict(entry)
                failed_entry["state"] = "failed"
                failed_entry["blocked_reason"] = "bot_not_found"
                failed_entry["failed_at"] = self.now_fn().isoformat()
                self.runtime_settings_service.set_bot_config_advisor_queued_apply(bot_id, failed_entry)
                results.append({"bot_id": bot_id, "state": "failed", "reason": "bot_not_found"})
                continue
            runtime_bot = runtime_lookup.get(bot_id)
            if not runtime_bot:
                continue
            effective_bot = self._merge_bot_state(stored_bot, runtime_bot=runtime_bot)
            if not self._is_flat_now(effective_bot):
                continue
            queued_fields = list(entry.get("queued_fields") or [])
            advisory_only_fields = list(entry.get("advisory_only_fields") or [])
            self._record_action(
                event_type="config_advisor_queue_apply_attempt",
                bot=effective_bot,
                fields_applied=queued_fields,
                advisory_only_fields=advisory_only_fields,
                metadata={"state": state},
            )
            validation_error = self._validate_queued_entry(stored_bot=stored_bot, entry=entry)
            if validation_error:
                blocked_entry = dict(entry)
                blocked_entry["state"] = "blocked"
                blocked_entry["blocked_reason"] = validation_error
                self.runtime_settings_service.set_bot_config_advisor_queued_apply(bot_id, blocked_entry)
                self._record_action(
                    event_type="config_advisor_queue_apply_blocked",
                    bot=effective_bot,
                    fields_applied=[],
                    advisory_only_fields=advisory_only_fields,
                    metadata={"reason": validation_error},
                )
                results.append({"bot_id": bot_id, "state": "blocked", "reason": validation_error})
                continue
            try:
                merged = copy.deepcopy(stored_bot)
                merged.update(
                    {
                        str(item.get("field")): item.get("to")
                        for item in list(entry.get("applicable_changes") or [])
                        if str(item.get("field") or "")
                    }
                )
                saved_bot = self.bot_manager.create_or_update_bot(merged)
                persisted_bot = self.bot_storage.get_bot(str(saved_bot.get("id") or "").strip()) or saved_bot
                watchdog_service = self.config_integrity_watchdog_service
                if watchdog_service is not None:
                    watchdog_service.record_save_roundtrip(
                        merged,
                        saved_bot,
                        persisted_bot=persisted_bot,
                        previous_bot=stored_bot,
                        ui_path="config_advisor_queue",
                    )
            except Exception as exc:
                failed_entry = dict(entry)
                failed_entry["state"] = "failed"
                failed_entry["blocked_reason"] = "apply_failed"
                failed_entry["failed_at"] = self.now_fn().isoformat()
                self.runtime_settings_service.set_bot_config_advisor_queued_apply(bot_id, failed_entry)
                self._record_action(
                    event_type="config_advisor_queue_apply_failed",
                    bot=effective_bot,
                    fields_applied=[],
                    advisory_only_fields=advisory_only_fields,
                    metadata={"reason": str(exc) or "apply_failed"},
                )
                results.append({"bot_id": bot_id, "state": "failed", "reason": "apply_failed"})
                continue
            self.runtime_settings_service.clear_bot_config_advisor_queued_apply(bot_id)
            self._record_action(
                event_type="config_advisor_queue_apply_success",
                bot=saved_bot,
                fields_applied=queued_fields,
                advisory_only_fields=advisory_only_fields,
                metadata={"state": "applied"},
            )
            results.append({"bot_id": bot_id, "state": "applied"})
        return results

    def get_recommendation_for_bot(
        self,
        bot_id: str,
        *,
        runtime_bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        stored_bot, effective_bot = self._resolve_bot_state(bot_id, runtime_bot=runtime_bot)
        context = self.bot_triage_service.collect_context(runtime_bots=[effective_bot])
        generated_at = str(context.get("generated_at") or self.now_fn().isoformat())
        review_lookup = dict(context.get("review_lookup") or {})
        active_by_bot = dict(context.get("active_by_bot") or {})
        triage_analysis = self.bot_triage_service.build_analysis(
            bot=effective_bot,
            review=review_lookup.get(str(effective_bot.get("id") or "").strip(), {}),
            active_issues=active_by_bot.get(str(effective_bot.get("id") or "").strip(), []),
            generated_at=generated_at,
        )
        return self._build_item(
            bot=effective_bot,
            triage_analysis=triage_analysis,
            generated_at=generated_at,
            queued_apply=self._queue_lookup().get(str(stored_bot.get("id") or "").strip()),
        )

    def _determine_tuning(
        self,
        *,
        bot: Dict[str, Any],
        checks: Dict[str, Any],
        triage_item: Dict[str, Any],
        current_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        hard_review = any(
            checks.get(name)
            for name in (
                "config_review",
                "mixed_signals_review",
                "ambiguous_pnl_review",
                "partial_data_review",
                "blocked_unknown_review",
            )
        )
        soft_review = any(
            checks.get(name)
            for name in (
                "ai_review",
                "watch_state_review",
            )
        )
        blocker_stress = any(
            checks.get(name)
            for name in (
                "margin_loop_pause",
                "min_size_loop_pause",
                "opening_loop_pause",
                "capital_compression_reduce",
                "position_cap_reduce",
            )
        )
        loss_behavior = any(
            checks.get(name)
            for name in (
                "loss_asymmetry_pause",
                "emergency_exit_pause",
                "negative_pnl_warning_pause",
            )
        )
        dense_structure = self._is_dense_structure(bot, checks, current_settings)
        cost_drag = bool(checks.get("cost_drag_reduce")) or dense_structure and self._safe_float(
            checks.get("total_pnl"), 0.0
        ) <= 0.0

        recommended = dict(current_settings)
        reasons: List[str] = []
        confidence = "medium"
        suggested_preset = "none"
        tuning_verdict = "KEEP_CURRENT"

        if hard_review:
            tuning_verdict = "REVIEW_MANUALLY"
            reasons = self._build_review_reasons(checks)
            confidence = "low" if checks.get("partial_data_review") else "medium"
        elif blocker_stress:
            tuning_verdict = "REDUCE_RISK"
            recommended = self._build_reduce_risk_settings(bot, current_settings, checks)
            reasons = self._build_reduce_risk_reasons(checks, current_settings)
            confidence = self._derive_reduce_confidence(checks)
            suggested_preset = "reduce_risk"
        elif cost_drag:
            tuning_verdict = "WIDEN_STRUCTURE"
            recommended = self._build_widen_structure_settings(bot, current_settings)
            reasons = self._build_widen_structure_reasons(checks, current_settings)
            confidence = "high" if checks.get("cost_drag_reduce") and dense_structure else "medium"
        elif loss_behavior or soft_review:
            tuning_verdict = "REVIEW_MANUALLY"
            reasons = self._build_review_reasons(checks)
            if not reasons and loss_behavior:
                reasons = ["loss behavior needs manual review"]
            confidence = "medium"
        else:
            tuning_verdict = "KEEP_CURRENT"
            reasons = [
                "runtime stable",
                "no repeated blocker patterns",
                "current config still aligned",
            ]
            confidence = "high"

        recommended["session_timer"] = self._recommended_session_timer(bot, tuning_verdict)
        if suggested_preset == "none" and recommended.get("session_timer") == "recommend_sleep_session_preset":
            suggested_preset = "sleep_session" if tuning_verdict == "KEEP_CURRENT" else suggested_preset

        rationale = self._build_rationale(
            tuning_verdict=tuning_verdict,
            recommended_settings=recommended,
            current_settings=current_settings,
            reasons=reasons,
        )
        return {
            "tuning_verdict": tuning_verdict,
            "confidence": confidence,
            "recommended_settings": recommended,
            "reasons": reasons[:4],
            "rationale": rationale,
            "suggested_preset": suggested_preset,
        }

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

    def _build_current_settings(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        grid_count = max(self._safe_int(bot.get("grid_count"), 0), 0) or None
        target_grid_count = self._safe_int(bot.get("target_grid_count"), 0)
        if target_grid_count <= 0:
            target_grid_count = grid_count
        payload = {
            "leverage": round(self._safe_float(bot.get("leverage"), 0.0), 4) or None,
            "grid_count": grid_count,
            "target_grid_count": target_grid_count,
            "grid_distribution": str(bot.get("grid_distribution") or "balanced").strip().lower() or "balanced",
            "range_posture": self._current_range_posture(bot),
            "step_posture": self._current_step_posture(bot),
            "session_timer": "enabled" if bool(bot.get("session_timer_enabled")) else "disabled",
        }
        if "target_grid_count" not in bot and target_grid_count == grid_count:
            payload.pop("target_grid_count", None)
        return payload

    def _build_reduce_risk_settings(
        self,
        bot: Dict[str, Any],
        current_settings: Dict[str, Any],
        checks: Dict[str, Any],
    ) -> Dict[str, Any]:
        recommended = dict(current_settings)
        current_leverage = self._safe_float(current_settings.get("leverage"), 0.0)
        current_grid_count = self._safe_int(current_settings.get("grid_count"), 0)
        current_target_grid_count = self._safe_int(
            current_settings.get("target_grid_count"), current_grid_count
        )

        if current_leverage > 3.0:
            recommended["leverage"] = 3.0
        if current_grid_count > 8:
            recommended["grid_count"] = 8
        if "target_grid_count" in recommended and current_target_grid_count > 8:
            recommended["target_grid_count"] = 8
        if str(current_settings.get("grid_distribution") or "").strip().lower() == "clustered":
            recommended["grid_distribution"] = "balanced"
        if checks.get("opening_loop_pause") or checks.get("min_size_loop_pause"):
            recommended["step_posture"] = "increase"
        else:
            recommended["step_posture"] = "keep"
        recommended["range_posture"] = "keep"
        return recommended

    def _build_widen_structure_settings(
        self,
        bot: Dict[str, Any],
        current_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        recommended = dict(current_settings)
        recommended["range_posture"] = "widen"
        recommended["step_posture"] = "increase"
        if str(current_settings.get("grid_distribution") or "").strip().lower() == "clustered":
            recommended["grid_distribution"] = "balanced"
        return recommended

    def _current_range_posture(self, bot: Dict[str, Any]) -> str:
        range_pct = self._safe_float(bot.get("effective_range_pct"), 0.0)
        if range_pct <= 0.0:
            lower = self._safe_float(bot.get("lower_price") or bot.get("grid_lower_price"), 0.0)
            upper = self._safe_float(bot.get("upper_price") or bot.get("grid_upper_price"), 0.0)
            if lower > 0.0 and upper > lower:
                range_pct = (upper / lower) - 1.0
        if range_pct <= 0.0:
            return "unknown"
        if range_pct < 0.05:
            return "tight"
        if range_pct > 0.20:
            return "wide"
        return "standard"

    def _current_step_posture(self, bot: Dict[str, Any]) -> str:
        effective_step_pct = self._safe_float(bot.get("effective_step_pct"), 0.0)
        fee_aware_min_step_pct = self._safe_float(bot.get("fee_aware_min_step_pct"), 0.0)
        grid_count = max(self._safe_int(bot.get("target_grid_count"), 0), self._safe_int(bot.get("grid_count"), 0))
        if effective_step_pct > 0.0 and fee_aware_min_step_pct > 0.0:
            if effective_step_pct <= fee_aware_min_step_pct * 1.2:
                return "dense"
            if effective_step_pct >= fee_aware_min_step_pct * 1.8:
                return "wide"
            return "standard"
        if grid_count >= 14:
            return "dense"
        if 0 < grid_count <= 6:
            return "wide"
        return "standard"

    def _recommended_session_timer(self, bot: Dict[str, Any], tuning_verdict: str) -> str:
        if bool(bot.get("session_timer_enabled")):
            return "keep_enabled"
        runtime_status = str(bot.get("status") or "").strip().lower()
        if tuning_verdict == "KEEP_CURRENT" and runtime_status == "running":
            return "recommend_sleep_session_preset"
        return "keep_disabled"

    def _build_reduce_risk_reasons(
        self,
        checks: Dict[str, Any],
        current_settings: Dict[str, Any],
    ) -> List[str]:
        reasons: List[str] = []
        if checks.get("margin_loop_pause"):
            reasons.append("repeated insufficient margin")
        if checks.get("min_size_loop_pause"):
            reasons.append("repeated min-size rejection")
        if checks.get("capital_compression_reduce"):
            reasons.append("capital compression active")
        if checks.get("opening_loop_pause"):
            reasons.append("blocked opening loop")
        if checks.get("position_cap_reduce") and len(reasons) < 4:
            reasons.append("position cap pressure")
        if (
            str(current_settings.get("grid_distribution") or "").strip().lower() == "clustered"
            and len(reasons) < 4
        ):
            reasons.append("avoid concentrated distribution")
        return reasons[:4] or ["reduce risk conservatively"]

    def _build_widen_structure_reasons(
        self,
        checks: Dict[str, Any],
        current_settings: Dict[str, Any],
    ) -> List[str]:
        reasons: List[str] = []
        if checks.get("cost_drag_reduce"):
            reasons.append("cost drag from dense structure")
        if str(current_settings.get("step_posture") or "") == "dense":
            reasons.append("dense grid behavior")
        if str(current_settings.get("grid_distribution") or "").strip().lower() == "clustered":
            reasons.append("clustered distribution near price")
        reasons.append("increase spacing to reduce churn")
        return reasons[:4]

    def _build_review_reasons(self, checks: Dict[str, Any]) -> List[str]:
        reasons: List[str] = []
        if checks.get("config_review"):
            reasons.append("config integrity needs review")
        if checks.get("mixed_signals_review"):
            reasons.append("mixed runtime diagnostics")
        if checks.get("ambiguous_pnl_review"):
            reasons.append("PnL attribution ambiguous")
        if checks.get("partial_data_review"):
            reasons.append("runtime data incomplete")
        if checks.get("blocked_unknown_review") and len(reasons) < 4:
            reasons.append("blocked state unclear")
        if checks.get("ai_review") and len(reasons) < 4:
            reasons.append("AI advisor signal is noisy")
        if checks.get("watch_state_review") and len(reasons) < 4:
            reasons.append("runtime health needs manual review")
        return reasons[:4] or ["manual review is safer than false precision"]

    def _build_rationale(
        self,
        *,
        tuning_verdict: str,
        recommended_settings: Dict[str, Any],
        current_settings: Dict[str, Any],
        reasons: List[str],
    ) -> str:
        if tuning_verdict == "REDUCE_RISK":
            return "Lower size-related settings only where repeated blocker evidence is already present."
        if tuning_verdict == "WIDEN_STRUCTURE":
            return "Widen structure before reducing size when dense spacing appears to be the primary drag."
        if tuning_verdict == "REVIEW_MANUALLY":
            return "Diagnostics are too mixed or incomplete for an exact read-only tune recommendation."
        if recommended_settings.get("session_timer") == "recommend_sleep_session_preset":
            return "Current config looks stable; only a session timer preset is worth considering."
        return "Current config matches the observed runtime state closely enough to keep unchanged."

    def _derive_reduce_confidence(self, checks: Dict[str, Any]) -> str:
        repeated_signals = 0
        if checks.get("margin_loop_pause"):
            repeated_signals += 1
        if checks.get("min_size_loop_pause"):
            repeated_signals += 1
        if checks.get("opening_loop_pause"):
            repeated_signals += 1
        if checks.get("capital_compression_reduce"):
            repeated_signals += 1
        if checks.get("position_cap_reduce"):
            repeated_signals += 1
        return "high" if repeated_signals >= 2 else "medium"

    def _is_dense_structure(
        self,
        bot: Dict[str, Any],
        checks: Dict[str, Any],
        current_settings: Dict[str, Any],
    ) -> bool:
        if str(current_settings.get("step_posture") or "") == "dense":
            return True
        grid_count = self._safe_int(current_settings.get("target_grid_count") or current_settings.get("grid_count"), 0)
        if grid_count >= 14:
            return True
        spacing_mult = self._safe_float(bot.get("sr_aware_grid_spacing_mult"), 1.0)
        if 0.0 < spacing_mult < 1.0:
            return True
        return False

    def _build_source_signals(
        self,
        *,
        bot: Dict[str, Any],
        checks: Dict[str, Any],
        triage_item: Dict[str, Any],
        confidence: str,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "triage_verdict": triage_item.get("verdict"),
            "triage_severity": triage_item.get("severity"),
            "runtime_status": checks.get("runtime_status"),
            "health_status": checks.get("health_status"),
            "margin_viability_state": checks.get("margin_state"),
            "cap_headroom_state": checks.get("cap_state"),
            "config_integrity_state": checks.get("config_state"),
            "total_pnl": checks.get("total_pnl"),
            "effective_step_pct": round(self._safe_float(bot.get("effective_step_pct"), 0.0), 6) or None,
            "effective_range_pct": round(self._safe_float(bot.get("effective_range_pct"), 0.0), 6) or None,
            "confidence_basis": confidence,
        }
        active_watchdogs = list(checks.get("active_watchdogs") or [])
        if active_watchdogs:
            payload["watchdog_active"] = [
                f"{item.get('type')}:{item.get('reason')}"
                for item in active_watchdogs[:3]
                if item.get("type") and item.get("reason")
            ]
        recent_suppressions = dict(checks.get("recent_suppressions") or {})
        if recent_suppressions:
            payload["recent_suppressions"] = recent_suppressions
        return {
            str(key): value
            for key, value in payload.items()
            if value not in (None, "", [], {})
        }

    def _build_apply_plan(
        self,
        *,
        bot: Dict[str, Any],
        tuning_verdict: str,
        current_settings: Dict[str, Any],
        recommended_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        applicable_changes: List[Dict[str, Any]] = []
        advisory_only_changes: List[Dict[str, Any]] = []

        for field in ("leverage", "grid_count", "target_grid_count", "grid_distribution"):
            if field == "target_grid_count" and "target_grid_count" not in current_settings:
                continue
            if field not in recommended_settings:
                continue
            from_value = current_settings.get(field)
            to_value = recommended_settings.get(field)
            if from_value == to_value:
                continue
            applicable_changes.append(
                {
                    "field": field,
                    "from": from_value,
                    "to": to_value,
                    "label": self._field_label(field),
                }
            )

        if recommended_settings.get("session_timer") == "recommend_sleep_session_preset":
            session_changes = self._build_sleep_session_changes(bot)
            for field, to_value in session_changes.items():
                from_value = bot.get(field)
                if from_value == to_value:
                    continue
                applicable_changes.append(
                    {
                        "field": field,
                        "from": from_value,
                        "to": to_value,
                        "label": self._field_label(field),
                    }
                )

        for field in self.ADVISORY_ONLY_FIELDS:
            if field not in recommended_settings:
                continue
            from_value = current_settings.get(field)
            to_value = recommended_settings.get(field)
            if from_value == to_value:
                continue
            advisory_only_changes.append(
                {
                    "field": field,
                    "from": from_value,
                    "to": to_value,
                    "label": self._field_label(field),
                }
            )

        applicable_fields = [str(item.get("field") or "") for item in applicable_changes if item.get("field")]
        advisory_only_fields = [str(item.get("field") or "") for item in advisory_only_changes if item.get("field")]
        return {
            "supports_apply": len(applicable_changes) > 0,
            "applicable_changes": applicable_changes,
            "applicable_fields": applicable_fields,
            "applicable_changes_map": {
                str(item.get("field")): item.get("to")
                for item in applicable_changes
                if str(item.get("field") or "")
            },
            "advisory_only_changes": advisory_only_changes,
            "advisory_only_fields": advisory_only_fields,
            "recommendation_type": tuning_verdict,
        }

    def _build_apply_preview(
        self,
        *,
        bot: Dict[str, Any],
        item: Dict[str, Any],
    ) -> Dict[str, Any]:
        apply_plan = self._build_apply_plan(
            bot=bot,
            tuning_verdict=str(item.get("tuning_verdict") or ""),
            current_settings=dict(item.get("current_settings") or {}),
            recommended_settings=dict(item.get("recommended_settings") or {}),
        )
        is_flat_now = self._is_flat_now(bot)
        blocked_reason = None
        if not apply_plan.get("supports_apply"):
            blocked_reason = "no_supported_changes"
        elif not is_flat_now:
            blocked_reason = "requires_flat_state"
        return {
            "title": "Apply Recommended Tune",
            "recommendation_type": str(item.get("tuning_verdict") or "").strip().upper() or None,
            "applicable_changes": list(apply_plan.get("applicable_changes") or []),
            "applicable_fields": list(apply_plan.get("applicable_fields") or []),
            "applicable_changes_map": dict(apply_plan.get("applicable_changes_map") or {}),
            "advisory_only_changes": list(apply_plan.get("advisory_only_changes") or []),
            "advisory_only_fields": list(apply_plan.get("advisory_only_fields") or []),
            "supports_apply": bool(apply_plan.get("supports_apply")),
            "requires_flat_state": True,
            "is_flat_now": is_flat_now,
            "blocked_reason": blocked_reason,
            "generated_at": str(item.get("generated_at") or self.now_fn().isoformat()),
            "summary_lines": self._build_apply_summary_lines(
                applicable_changes=list(apply_plan.get("applicable_changes") or []),
                advisory_only_changes=list(apply_plan.get("advisory_only_changes") or []),
                is_flat_now=is_flat_now,
            ),
        }

    def _build_apply_summary_lines(
        self,
        *,
        applicable_changes: List[Dict[str, Any]],
        advisory_only_changes: List[Dict[str, Any]],
        is_flat_now: bool,
    ) -> List[str]:
        lines: List[str] = []
        if applicable_changes:
            lines.append("This will change:")
            for item in applicable_changes[:8]:
                lines.append(
                    f"{item.get('label')} {self._format_value(item.get('from'))} -> {self._format_value(item.get('to'))}"
                )
        else:
            lines.append("No concrete supported config fields are available to apply.")
        if advisory_only_changes:
            lines.append("Advisory only, not auto-applied:")
            for item in advisory_only_changes[:6]:
                lines.append(
                    f"{item.get('label')} {self._format_value(item.get('from'))} -> {self._format_value(item.get('to'))}"
                )
        if not is_flat_now:
            lines.append("Bot must be flat before applying recommended tune.")
        return lines

    def _build_blocked_payload(
        self,
        *,
        bot: Dict[str, Any],
        preview: Dict[str, Any],
        blocked_reason: str,
    ) -> Dict[str, Any]:
        return {
            "ok": False,
            "bot_id": str(bot.get("id") or "").strip() or None,
            "applied_fields": [],
            "skipped_advisory_fields": list(preview.get("advisory_only_fields") or []),
            "blocked_reason": blocked_reason,
            "new_settings_version": self._safe_int(bot.get("settings_version"), 0),
            "generated_at": str(preview.get("generated_at") or self.now_fn().isoformat()),
            "applied_at": None,
        }

    def _build_queue_response(
        self,
        *,
        bot: Dict[str, Any],
        state: str,
        queued_fields: List[str],
        advisory_only_fields: List[str],
        blocked_reason: Optional[str],
        queued_at: Optional[str],
        applied_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": blocked_reason is None,
            "bot_id": str(bot.get("id") or "").strip() or None,
            "state": str(state or "").strip().lower() or "waiting_for_flat",
            "queued_fields": list(queued_fields or []),
            "advisory_only_fields": list(advisory_only_fields or []),
            "blocked_reason": blocked_reason,
            "queued_at": queued_at,
            "applied_at": applied_at,
            "updated_at": self.now_fn().isoformat(),
        }

    def _build_sleep_session_changes(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        now_dt = self.now_fn()
        stop_at = now_dt.replace(microsecond=0)
        stop_at = stop_at.replace(microsecond=0) + timedelta(hours=self.DEFAULT_SLEEP_DURATION_HOURS)
        return {
            "session_timer_enabled": True,
            "session_start_at": bot.get("session_start_at"),
            "session_stop_at": stop_at.isoformat(),
            "session_no_new_entries_before_stop_min": 20,
            "session_end_mode": "green_grace_then_stop",
            "session_green_grace_min": 15,
            "session_cancel_pending_orders_on_end": True,
            "session_reduce_only_on_end": True,
        }

    def _resolve_bot_state(
        self,
        bot_id: str,
        *,
        runtime_bot: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        stored_bot = self._require_bot(bot_id)
        effective_bot = self._merge_bot_state(stored_bot, runtime_bot=runtime_bot)
        return stored_bot, effective_bot

    @staticmethod
    def _merge_bot_state(
        stored_bot: Dict[str, Any],
        *,
        runtime_bot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged = dict(stored_bot)
        if isinstance(runtime_bot, dict):
            merged.update(dict(runtime_bot))
        return merged

    def _require_bot(self, bot_id: str) -> Dict[str, Any]:
        if self.bot_storage is None or not hasattr(self.bot_storage, "get_bot"):
            raise ValueError("bot_storage_unavailable")
        bot = self.bot_storage.get_bot(bot_id)
        if not bot:
            raise ValueError("bot_not_found")
        return dict(bot)

    def _queue_lookup(self) -> Dict[str, Dict[str, Any]]:
        service = self.runtime_settings_service
        if service is None or not hasattr(service, "get_bot_config_advisor_queued_applies"):
            return {}
        try:
            payload = service.get_bot_config_advisor_queued_applies()
        except Exception:
            return {}
        return {
            str(bot_id): dict(entry)
            for bot_id, entry in dict(payload or {}).items()
            if str(bot_id).strip() and isinstance(entry, dict)
        }

    def _is_flat_now(self, bot: Dict[str, Any]) -> bool:
        position_size = max(
            abs(self._safe_float(bot.get("position_size"), 0.0)),
            abs(self._safe_float(bot.get("size"), 0.0)),
            abs(self._safe_float(bot.get("position_qty"), 0.0)),
            abs(self._safe_float(bot.get("current_position_size"), 0.0)),
        )
        if position_size > 0.0:
            return False
        position_side = str(bot.get("position_side") or bot.get("side") or "").strip().lower()
        if position_side and position_side not in {"flat", "none"}:
            return False
        unrealized_pnl = abs(self._safe_float(bot.get("unrealized_pnl"), 0.0))
        if unrealized_pnl > 0.000001:
            return False
        return True

    def _validate_queued_entry(
        self,
        *,
        stored_bot: Dict[str, Any],
        entry: Dict[str, Any],
    ) -> Optional[str]:
        if self._safe_int(stored_bot.get("settings_version"), 0) != self._safe_int(
            entry.get("base_settings_version"), 0
        ):
            return "settings_version_conflict"
        for item in list(entry.get("applicable_changes") or []):
            field = str(item.get("field") or "").strip()
            if not field:
                continue
            if stored_bot.get(field) != item.get("from"):
                return "unsupported_drift"
        return None

    def _ensure_settings_version(
        self,
        bot: Dict[str, Any],
        incoming_settings_version: Any,
        *,
        ui_path: str,
    ) -> None:
        current_settings_version = self._safe_int(bot.get("settings_version"), 0)
        try:
            normalized_incoming = int(incoming_settings_version)
        except (TypeError, ValueError):
            normalized_incoming = None
        if normalized_incoming is None or normalized_incoming != current_settings_version:
            conflict_reason = (
                "missing_incoming_version"
                if normalized_incoming is None
                else "stale_incoming_version"
            )
            watchdog_service = self.config_integrity_watchdog_service
            if watchdog_service is not None:
                watchdog_service.record_settings_version_conflict(
                    bot,
                    bot,
                    ui_path=ui_path,
                    conflict_reason=conflict_reason,
                    incoming_settings_version=normalized_incoming,
                    current_settings_version=current_settings_version,
                )
            raise BotTriageSettingsConflictError(
                bot_id=str(bot.get("id") or "").strip(),
                current_settings_version=current_settings_version,
                incoming_settings_version=normalized_incoming,
                conflict_reason=conflict_reason,
            )

    def _record_action(
        self,
        *,
        event_type: str,
        bot: Dict[str, Any],
        fields_applied: List[str],
        advisory_only_fields: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        diagnostics_service = getattr(self.bot_manager, "audit_diagnostics_service", None)
        enabled_check = getattr(diagnostics_service, "enabled", None)
        is_enabled = enabled_check() if callable(enabled_check) else True
        if diagnostics_service is None or not is_enabled:
            return
        payload = {
            "event_type": event_type,
            "severity": "INFO",
            "timestamp": self.now_fn().isoformat(),
            "bot_id": str(bot.get("id") or "").strip() or None,
            "symbol": str(bot.get("symbol") or "").strip().upper() or None,
            "fields_applied": list(fields_applied or []),
            "advisory_only_fields": list(advisory_only_fields or []),
        }
        payload.update(dict(metadata or {}))
        diagnostics_service.record_event(payload, throttle_sec=0.0)

    @staticmethod
    def _format_value(value: Any) -> str:
        if value in (None, ""):
            return "off"
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, float):
            return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
        return str(value)

    @staticmethod
    def _field_label(field: str) -> str:
        labels = {
            "leverage": "Leverage",
            "grid_count": "Grid count",
            "target_grid_count": "Target grid count",
            "grid_distribution": "Grid distribution",
            "range_posture": "Range posture",
            "step_posture": "Step posture",
            "session_timer_enabled": "Session timer",
            "session_start_at": "Session start",
            "session_stop_at": "Session stop",
            "session_no_new_entries_before_stop_min": "No new entries before stop",
            "session_end_mode": "Session end mode",
            "session_green_grace_min": "Green grace minutes",
            "session_cancel_pending_orders_on_end": "Cancel pending orders on end",
            "session_reduce_only_on_end": "Reduce-only on end",
        }
        return labels.get(field, field.replace("_", " "))

    @classmethod
    def _sort_key(cls, item: Dict[str, Any]) -> tuple[Any, ...]:
        return (
            cls.VERDICT_PRIORITY.get(str(item.get("tuning_verdict") or ""), 99),
            cls.CONFIDENCE_PRIORITY.get(str(item.get("confidence") or ""), 99),
            str(item.get("symbol") or ""),
            str(item.get("bot_id") or ""),
        )
