from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


class BotTriageService:
    """Build compact per-bot operational triage from existing runtime and diagnostics data."""

    VERDICT_PRIORITY = {
        "PAUSE": 0,
        "REDUCE": 1,
        "REVIEW": 2,
        "KEEP": 3,
    }
    SEVERITY_PRIORITY = {
        "high": 0,
        "medium": 1,
        "low": 2,
    }
    HIGH_WATCHDOG_SEVERITIES = {"ERROR", "CRITICAL"}
    SIGNAL_REVIEW_TYPES = {"signal_drift", "state_flapping"}
    CAPITAL_STRESS_REASONS = {
        "capital_compression_active",
        "small_bot_pressure",
        "position_cap_limiting_exposure",
        "valid_setup_blocked_by_margin",
        "setup_blocked_by_min_size",
    }
    PNL_ATTRIBUTION_REVIEW_REASONS = {"ambiguous_attribution", "attribution_gap"}
    PNL_ATTRIBUTION_REDUCE_REASONS = {"known_cost_drag_material"}

    def __init__(
        self,
        watchdog_hub_service: Optional[Any] = None,
        runtime_settings_service: Optional[Any] = None,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.watchdog_hub_service = watchdog_hub_service
        self.runtime_settings_service = runtime_settings_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def build_snapshot(
        self,
        *,
        runtime_bots: Optional[Iterable[Dict[str, Any]]] = None,
        stale_data: bool = False,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = self.collect_context(runtime_bots=runtime_bots)
        generated_at = str(context.get("generated_at") or self._event_timestamp())
        now_dt = self.now_fn()
        bots = list(context.get("bots") or [])
        review_lookup = dict(context.get("review_lookup") or {})
        active_by_bot = dict(context.get("active_by_bot") or {})
        override_lookup = self._override_lookup()

        items: List[Dict[str, Any]] = []
        summary_counts = {verdict: 0 for verdict in self.VERDICT_PRIORITY}
        suppressed_count = 0
        for bot in bots:
            analysis = self.build_analysis(
                bot=bot,
                review=review_lookup.get(str(bot.get("id") or "").strip(), {}),
                active_issues=active_by_bot.get(str(bot.get("id") or "").strip(), []),
                generated_at=generated_at,
            )
            item = dict(analysis.get("item") or {})
            if self._is_suppressed(item, override_lookup.get(str(item.get("bot_id") or "").strip()), now_dt):
                suppressed_count += 1
                continue
            items.append(item)
            summary_counts[item["verdict"]] = int(summary_counts.get(item["verdict"], 0) or 0) + 1

        items.sort(key=self._sort_key)
        payload = {
            "generated_at": generated_at,
            "total_bots": len(items),
            "suppressed_count": suppressed_count,
            "summary_counts": summary_counts,
            "items": items,
        }
        if stale_data:
            payload["stale_data"] = True
            payload["error"] = str(error or "bots_runtime_stale")
        return payload

    def collect_context(
        self,
        *,
        runtime_bots: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        generated_at = self._event_timestamp()
        bots = [dict(bot) for bot in (runtime_bots or []) if isinstance(bot, dict)]
        review_lookup = self._review_lookup()
        active_by_bot = self._group_active_issues_by_bot(
            self._active_watchdog_issues(bots),
            bots,
        )
        return {
            "generated_at": generated_at,
            "bots": bots,
            "review_lookup": review_lookup,
            "active_by_bot": active_by_bot,
        }

    def build_analysis(
        self,
        *,
        bot: Dict[str, Any],
        review: Optional[Dict[str, Any]] = None,
        active_issues: Optional[List[Dict[str, Any]]] = None,
        generated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        generated_at = generated_at or self._event_timestamp()
        checks = self._build_checks(bot, review or {}, active_issues or [])
        verdict, severity = self._classify(checks)
        reasons = self._build_reasons(checks, verdict)
        item = self._build_item_from_analysis(
            bot=bot,
            generated_at=generated_at,
            verdict=verdict,
            severity=severity,
            reasons=reasons,
            checks=checks,
        )
        return {
            "checks": checks,
            "verdict": verdict,
            "severity": severity,
            "reasons": reasons,
            "item": item,
        }

    def _build_item(
        self,
        *,
        bot: Dict[str, Any],
        review: Dict[str, Any],
        active_issues: List[Dict[str, Any]],
        generated_at: str,
    ) -> Dict[str, Any]:
        analysis = self.build_analysis(
            bot=bot,
            review=review,
            active_issues=active_issues,
            generated_at=generated_at,
        )
        return dict(analysis.get("item") or {})

    def _build_item_from_analysis(
        self,
        *,
        bot: Dict[str, Any],
        generated_at: str,
        verdict: str,
        severity: str,
        reasons: List[str],
        checks: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "bot_id": str(bot.get("id") or "").strip() or None,
            "symbol": str(bot.get("symbol") or "").strip().upper() or None,
            "mode": str(bot.get("mode") or "").strip().lower() or None,
            "verdict": verdict,
            "severity": severity,
            "reasons": reasons[:4],
            "suggested_action": self._build_suggested_action(checks, verdict),
            "source_signals": self._build_source_signals(checks),
            "generated_at": generated_at,
        }

    def _build_checks(
        self,
        bot: Dict[str, Any],
        review: Dict[str, Any],
        active_issues: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        health_status = str(
            review.get("current_operational_status") or "OK"
        ).strip().upper() or "OK"
        config_state = str(
            review.get("config_integrity_state") or "clean"
        ).strip().lower() or "clean"
        margin_state = str(
            review.get("margin_viability_state") or "viable"
        ).strip().lower() or "viable"
        cap_state = str(
            review.get("cap_headroom_state") or "clear"
        ).strip().lower() or "clear"
        recent_suppressions = dict(review.get("recent_suppressions") or {})
        recent_positive_actions = dict(review.get("recent_positive_actions") or {})
        watchdog_state = dict(review.get("watchdog_state") or {})
        active_watchdogs = [
            {
                "type": str(issue.get("watchdog_type") or "").strip().lower(),
                "reason": str(issue.get("reason") or "").strip().lower(),
                "severity": str(issue.get("severity") or "INFO").strip().upper(),
            }
            for issue in active_issues
            if isinstance(issue, dict)
        ]
        active_watchdog_types = {
            item["type"] for item in active_watchdogs if item.get("type")
        }
        active_watchdog_reasons = {
            item["reason"] for item in active_watchdogs if item.get("reason")
        }
        runtime_status = str(bot.get("status") or "").strip().lower()
        last_skip_reason = str(bot.get("last_skip_reason") or "").strip().lower()
        total_pnl = self._safe_float(bot.get("total_pnl"), 0.0)
        capital_summary = dict(bot.get("watchdog_bottleneck_summary") or {})
        ai_last_error = str(bot.get("ai_advisor_last_error") or "").strip()
        ai_last_status = str(bot.get("ai_advisor_last_status") or "").strip().lower()
        ai_error_count = int(bot.get("ai_advisor_error_count", 0) or 0)
        ai_timeout_count = int(bot.get("ai_advisor_timeout_count", 0) or 0)
        has_high_exit_stack = any(
            item["type"] == "exit_stack"
            and item["severity"] in self.HIGH_WATCHDOG_SEVERITIES
            for item in active_watchdogs
        )
        has_loss_asymmetry = "loss_asymmetry" in active_watchdog_types
        capital_compression_active = bool(capital_summary.get("capital_compression_active"))
        if margin_state in {"compressed", "stressed"}:
            capital_compression_active = True
        if active_watchdog_reasons & {"capital_compression_active", "small_bot_pressure"}:
            capital_compression_active = True
        position_cap_pressure = bool(bot.get("watchdog_position_cap_active", False))
        if cap_state == "tight":
            position_cap_pressure = True
        if int(recent_suppressions.get("position_cap_hit") or 0) >= 2:
            position_cap_pressure = True
        if "position_cap_limiting_exposure" in active_watchdog_reasons:
            position_cap_pressure = True
        repeated_margin_blocks = margin_state == "starved" or int(
            recent_suppressions.get("insufficient_margin") or 0
        ) >= 2
        if "valid_setup_blocked_by_margin" in active_watchdog_reasons:
            repeated_margin_blocks = True
        repeated_min_size_blocks = int(recent_suppressions.get("qty_below_min") or 0) >= 2
        if "setup_blocked_by_min_size" in active_watchdog_reasons:
            repeated_min_size_blocks = True
        if last_skip_reason in {"qty_below_min", "notional_below_min"} and health_status == "BLOCKED":
            repeated_min_size_blocks = True
        opening_loop_blocked = (
            int(recent_suppressions.get("opening_orders_blocked") or 0) >= 3
            and int(recent_positive_actions.get("opening_orders_placed") or 0) == 0
        )
        strong_negative_pnl = total_pnl <= -25.0
        config_issue = config_state in {"watch", "degraded", "mismatch"}
        mixed_runtime_signals = bool(active_watchdog_types & self.SIGNAL_REVIEW_TYPES)
        if str(watchdog_state.get("type") or "").strip().lower() in self.SIGNAL_REVIEW_TYPES:
            mixed_runtime_signals = True
        ambiguous_pnl_attribution = bool(
            active_watchdog_reasons & self.PNL_ATTRIBUTION_REVIEW_REASONS
        )
        cost_drag_active = bool(
            active_watchdog_reasons & self.PNL_ATTRIBUTION_REDUCE_REASONS
        )
        ai_noisy = bool(bot.get("ai_advisor_enabled", False)) and (
            ai_error_count > 0
            or ai_timeout_count > 0
            or bool(ai_last_error)
            or ai_last_status in {"error", "timeout"}
        )
        partial_evidence = bool(bot.get("runtime_snapshot_stale"))
        if not review and not active_watchdogs:
            partial_evidence = True

        return {
            "bot_id": str(bot.get("id") or "").strip() or None,
            "symbol": str(bot.get("symbol") or "").strip().upper() or None,
            "mode": str(bot.get("mode") or "").strip().lower() or None,
            "runtime_status": runtime_status or None,
            "health_status": health_status,
            "config_state": config_state,
            "margin_state": margin_state,
            "cap_state": cap_state,
            "total_pnl": round(total_pnl, 4),
            "recent_suppressions": {
                str(key): int(value or 0)
                for key, value in recent_suppressions.items()
                if int(value or 0) > 0
            },
            "recent_positive_actions": {
                str(key): int(value or 0)
                for key, value in recent_positive_actions.items()
                if int(value or 0) > 0
            },
            "watchdog_state": watchdog_state,
            "active_watchdogs": active_watchdogs,
            "active_watchdog_types": sorted(active_watchdog_types),
            "active_watchdog_reasons": sorted(active_watchdog_reasons),
            "loss_asymmetry_pause": has_loss_asymmetry,
            "margin_loop_pause": repeated_margin_blocks,
            "min_size_loop_pause": repeated_min_size_blocks,
            "opening_loop_pause": opening_loop_blocked,
            "emergency_exit_pause": has_high_exit_stack,
            "negative_pnl_warning_pause": strong_negative_pnl
            and (health_status in {"BLOCKED", "DEGRADED"} or len(active_watchdogs) >= 2),
            "capital_compression_reduce": capital_compression_active,
            "position_cap_reduce": position_cap_pressure,
            "cost_drag_reduce": cost_drag_active,
            "config_review": config_issue,
            "config_review_high": config_state in {"degraded", "mismatch"},
            "mixed_signals_review": mixed_runtime_signals,
            "ambiguous_pnl_review": ambiguous_pnl_attribution,
            "ai_review": ai_noisy,
            "partial_data_review": partial_evidence,
            "watch_state_review": health_status in {"WATCH", "DEGRADED"},
            "blocked_unknown_review": health_status == "BLOCKED"
            and not any(
                [
                    has_loss_asymmetry,
                    repeated_margin_blocks,
                    repeated_min_size_blocks,
                    opening_loop_blocked,
                    has_high_exit_stack,
                ]
            ),
            "suggest_session_timer": (
                not bool(bot.get("session_timer_enabled", False))
                and runtime_status == "running"
                and not any(
                    [
                        has_loss_asymmetry,
                        repeated_margin_blocks,
                        repeated_min_size_blocks,
                        has_high_exit_stack,
                    ]
                )
            ),
            "ai_status": ai_last_status or None,
            "ai_error_count": ai_error_count,
            "ai_timeout_count": ai_timeout_count,
            "ai_last_error": ai_last_error or None,
        }

    def _classify(self, checks: Dict[str, Any]) -> tuple[str, str]:
        pause_verdict = any(
            checks.get(name)
            for name in (
                "loss_asymmetry_pause",
                "margin_loop_pause",
                "min_size_loop_pause",
                "opening_loop_pause",
                "emergency_exit_pause",
                "negative_pnl_warning_pause",
            )
        )
        if pause_verdict:
            return "PAUSE", "high"

        reduce_verdict = any(
            checks.get(name)
            for name in (
                "capital_compression_reduce",
                "position_cap_reduce",
                "cost_drag_reduce",
            )
        )
        if reduce_verdict:
            severity = "high" if (
                checks.get("position_cap_reduce")
                and checks.get("total_pnl", 0.0) < 0.0
            ) else "medium"
            return "REDUCE", severity

        review_verdict = any(
            checks.get(name)
            for name in (
                "config_review",
                "mixed_signals_review",
                "ambiguous_pnl_review",
                "ai_review",
                "partial_data_review",
                "watch_state_review",
                "blocked_unknown_review",
            )
        )
        if review_verdict:
            severity = "high" if checks.get("config_review_high") else "medium"
            return "REVIEW", severity

        return "KEEP", "low"

    def _build_reasons(self, checks: Dict[str, Any], verdict: str) -> List[str]:
        reasons: List[str] = []
        if verdict == "PAUSE":
            if checks.get("loss_asymmetry_pause"):
                reasons.append("strong loss asymmetry")
            if checks.get("margin_loop_pause"):
                reasons.append("repeated insufficient margin")
            if checks.get("min_size_loop_pause"):
                reasons.append("repeated min-size rejection")
            if checks.get("opening_loop_pause"):
                reasons.append("opening loop staying blocked")
            if checks.get("emergency_exit_pause"):
                reasons.append("forced exits dominating")
            if checks.get("negative_pnl_warning_pause"):
                reasons.append("negative pnl with repeated warnings")
        elif verdict == "REDUCE":
            if checks.get("capital_compression_reduce"):
                reasons.append("capital compression active")
            if checks.get("position_cap_reduce"):
                reasons.append("position cap pressure")
            if checks.get("cost_drag_reduce"):
                reasons.append("cost drag is material")
            if checks.get("margin_state") == "stressed":
                reasons.append("capital still viable but stressed")
        elif verdict == "REVIEW":
            if checks.get("config_review_high"):
                reasons.append("config integrity degraded")
            elif checks.get("config_review"):
                reasons.append("config integrity needs review")
            if checks.get("mixed_signals_review"):
                reasons.append("mixed runtime diagnostics")
            if checks.get("ambiguous_pnl_review"):
                reasons.append("PnL attribution ambiguous")
            if checks.get("ai_review"):
                reasons.append("AI advisor state noisy")
            if checks.get("partial_data_review"):
                reasons.append("runtime snapshot stale")
            if checks.get("blocked_unknown_review") and len(reasons) < 2:
                reasons.append("blocked state needs review")
            if checks.get("watch_state_review") and len(reasons) < 2:
                reasons.append("runtime health needs review")
        else:
            reasons.extend(
                [
                    "runtime stable",
                    "no severe watchdog issues",
                ]
            )
            if checks.get("config_state") == "clean":
                reasons.append("config integrity clean")
        if not reasons:
            reasons.append("diagnostics incomplete")
        return reasons[:4]

    @staticmethod
    def _build_suggested_action(checks: Dict[str, Any], verdict: str) -> str:
        if verdict == "PAUSE":
            if checks.get("loss_asymmetry_pause") or checks.get("emergency_exit_pause"):
                return "pause bot and review payoff"
            return "pause bot and inspect repeated blockers"
        if verdict == "REDUCE":
            if checks.get("position_cap_reduce") or checks.get("capital_compression_reduce"):
                return "reduce leverage / grid count"
            return "reduce bot size and monitor"
        if verdict == "REVIEW":
            if checks.get("config_review"):
                return "review config integrity"
            if checks.get("partial_data_review"):
                return "refresh diagnostics and review"
            if checks.get("suggest_session_timer"):
                return "review setup and use session timer only"
            return "review diagnostics before changing settings"
        if checks.get("suggest_session_timer"):
            return "keep as-is and use session timer only"
        return "keep as-is and monitor"

    @classmethod
    def _build_source_signals(cls, checks: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "runtime_status": checks.get("runtime_status"),
            "health_status": checks.get("health_status"),
            "config_integrity_state": checks.get("config_state"),
        }
        if checks.get("margin_state") != "viable":
            payload["margin_viability_state"] = checks.get("margin_state")
        if checks.get("cap_state") != "clear":
            payload["cap_headroom_state"] = checks.get("cap_state")
        if checks.get("active_watchdogs"):
            payload["watchdog_active"] = [
                f"{item.get('type')}:{item.get('reason')}"
                for item in checks.get("active_watchdogs")[:3]
                if item.get("type") and item.get("reason")
            ]
        if checks.get("recent_suppressions"):
            payload["recent_suppressions"] = dict(checks.get("recent_suppressions") or {})
        if checks.get("ai_review"):
            payload["ai"] = {
                "status": checks.get("ai_status"),
                "errors": checks.get("ai_error_count"),
                "timeouts": checks.get("ai_timeout_count"),
            }
        if checks.get("total_pnl") is not None:
            payload["total_pnl"] = checks.get("total_pnl")
        return {
            str(key): value
            for key, value in payload.items()
            if value not in (None, "", [], {})
        }

    def _active_watchdog_issues(self, runtime_bots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        service = self.watchdog_hub_service
        if service is None or not hasattr(service, "build_snapshot"):
            return []
        try:
            payload = service.build_snapshot(runtime_bots=runtime_bots)
        except Exception:
            return []
        return [
            dict(item)
            for item in list((payload or {}).get("active_issues") or [])
            if isinstance(item, dict)
        ]

    def _review_lookup(self) -> Dict[str, Dict[str, Any]]:
        service = getattr(self.watchdog_hub_service, "audit_diagnostics_service", None)
        if service is None or not hasattr(service, "get_review_snapshot"):
            return {}
        try:
            payload = service.get_review_snapshot()
        except Exception:
            return {}
        bots = dict((payload or {}).get("bots") or {})
        return {
            str(bot_id): dict(snapshot)
            for bot_id, snapshot in bots.items()
            if str(bot_id).strip() and isinstance(snapshot, dict)
        }

    @staticmethod
    def _group_active_issues_by_bot(
        active_issues: Iterable[Dict[str, Any]],
        runtime_bots: Iterable[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        by_bot: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        symbol_lookup: Dict[str, List[str]] = defaultdict(list)
        for bot in runtime_bots:
            bot_id = str(bot.get("id") or "").strip()
            symbol = str(bot.get("symbol") or "").strip().upper()
            if bot_id:
                symbol_lookup[symbol].append(bot_id)
        for issue in active_issues:
            bot_id = str(issue.get("bot_id") or "").strip()
            symbol = str(issue.get("symbol") or "").strip().upper()
            if bot_id:
                by_bot[bot_id].append(issue)
                continue
            if symbol and len(symbol_lookup.get(symbol) or []) == 1:
                by_bot[symbol_lookup[symbol][0]].append(issue)
        return by_bot

    @classmethod
    def _sort_key(cls, item: Dict[str, Any]) -> tuple[Any, ...]:
        return (
            cls.VERDICT_PRIORITY.get(str(item.get("verdict") or ""), 99),
            cls.SEVERITY_PRIORITY.get(str(item.get("severity") or ""), 99),
            0
            if str((item.get("source_signals") or {}).get("runtime_status") or "").strip().lower()
            in {"running", "paused", "recovering", "flash_crash_paused"}
            else 1,
            cls._safe_float((item.get("source_signals") or {}).get("total_pnl"), 0.0),
            str(item.get("symbol") or ""),
            str(item.get("bot_id") or ""),
        )

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _event_timestamp(self) -> str:
        return self.now_fn().isoformat()

    def _override_lookup(self) -> Dict[str, Dict[str, Any]]:
        service = self.runtime_settings_service
        if service is None or not hasattr(service, "get_bot_triage_overrides"):
            return {}
        try:
            payload = service.get_bot_triage_overrides()
        except Exception:
            return {}
        return {
            str(bot_id): dict(entry)
            for bot_id, entry in dict(payload or {}).items()
            if str(bot_id).strip() and isinstance(entry, dict)
        }

    def _is_suppressed(
        self,
        item: Dict[str, Any],
        override: Optional[Dict[str, Any]],
        now_dt: datetime,
    ) -> bool:
        if not isinstance(override, dict):
            return False
        if str(override.get("verdict") or "").strip().upper() != str(item.get("verdict") or "").strip().upper():
            return False
        mode = str(override.get("mode") or "").strip().lower()
        if mode == "dismissed":
            return True
        if mode == "snoozed":
            until_dt = self._parse_iso(override.get("snooze_until"))
            return until_dt is not None and until_dt > now_dt
        return False

    @staticmethod
    def _parse_iso(value: Any) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
