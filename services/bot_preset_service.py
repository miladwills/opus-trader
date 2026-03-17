from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config.strategy_config import NEUTRAL_MAJOR_SYMBOLS
from services.custom_bot_preset_service import CustomBotPresetService
from services.order_sizing_viability import build_order_sizing_viability


class BotPresetService:
    """Conservative preset catalog and recommendation helper for new bot creation."""

    PRESET_ORDER = (
        "manual_blank",
        "eth_conservative",
        "small_balance_safe",
        "sleep_session",
        "high_volatility_safe",
    )
    DEFAULT_SLEEP_DURATION_HOURS = 2
    SMALL_BUDGET_USDT = 75.0
    MODERATE_BUDGET_USDT = 150.0
    NON_MAJOR_MIN_NOTIONAL_SENSITIVE_BUDGET_USDT = 125.0
    MAJOR_MIN_NOTIONAL_SENSITIVE_BUDGET_USDT = 90.0
    HIGH_VOLATILITY_SYMBOLS = {
        "DOGEUSDT",
        "PEPEUSDT",
        "WIFUSDT",
        "BONKUSDT",
        "FLOKIUSDT",
        "SHIBUSDT",
        "BRETTUSDT",
        "FARTCOINUSDT",
        "HYPEUSDT",
        "TRUMPUSDT",
    }

    def __init__(
        self,
        *,
        custom_preset_service: Optional[Any] = None,
        audit_diagnostics_service: Optional[Any] = None,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.custom_preset_service = custom_preset_service
        self.audit_diagnostics_service = audit_diagnostics_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def list_presets(self) -> Dict[str, Any]:
        generated_at = self.now_fn().isoformat()
        built_in_items = [self._build_builtin_preset(preset_id) for preset_id in self.PRESET_ORDER]
        custom_items = self._list_custom_preset_items()
        return {
            "generated_at": generated_at,
            "default_preset": "manual_blank",
            "built_in_items": built_in_items,
            "custom_items": custom_items,
            "items": built_in_items + custom_items,
        }

    def get_preset(self, preset_id: str) -> Dict[str, Any]:
        custom = self._get_custom_preset_item(preset_id)
        if custom is not None:
            return custom
        return self._build_builtin_preset(preset_id)

    def _build_builtin_preset(self, preset_id: str) -> Dict[str, Any]:
        normalized = self._normalize_preset_id(preset_id)
        settings = self._build_settings(normalized)
        reasons = self._preset_reasons(normalized)
        return {
            "preset_id": normalized,
            "preset_type": "built_in",
            "name": self._preset_name(normalized),
            "description": self._preset_description(normalized),
            "reasons": reasons[:4],
            "settings": settings,
            "key_fields": self._key_fields(settings),
        }

    def recommend(
        self,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = dict(payload or {})
        symbol = str(payload.get("symbol") or "").strip().upper()
        mode = str(payload.get("mode") or "neutral").strip().lower()
        risk_level = str(payload.get("risk_level") or "").strip().lower()
        investment = self._safe_float(payload.get("investment"), 0.0)
        signal_context = self._build_signal_context(
            symbol=symbol,
            mode=mode,
            investment=investment,
            risk_level=risk_level,
            wants_session=bool(payload.get("session_timer_enabled")) or bool(payload.get("session_stop_at")),
        )
        recommendation = self._select_recommendation(signal_context)
        sizing_guard = self._apply_sizing_guard(
            recommendation=recommendation,
            payload=payload,
            signal_context=signal_context,
        )
        preset_id = recommendation["recommended_preset"]
        preset = self.get_preset(preset_id)
        sizing_viability = self._evaluate_preset_sizing_viability(
            payload=payload,
            preset=preset,
            signal_context=signal_context,
        )
        self._record_event(
            event_type="bot_preset_auto_recommended_phase2",
            preset_name=preset_id,
            symbol=symbol,
            mode=mode,
            key_fields=[item["field"] for item in preset.get("key_fields", [])],
            metadata={
                "reason": recommendation["reason"],
                "confidence": recommendation["confidence"],
                "investment": investment,
                "matched_signals": recommendation["matched_signals"],
                "preset_type": recommendation["preset_type"],
                "sizing_guard_applied": bool(sizing_guard),
            },
        )
        if recommendation["preset_type"] == "custom":
            self._record_event(
                event_type="custom_bot_preset_recommended",
                preset_name=preset_id,
                symbol=symbol,
                mode=mode,
                key_fields=[item["field"] for item in preset.get("key_fields", [])],
                metadata={
                    "matched_signals": recommendation["matched_signals"],
                    "confidence": recommendation["confidence"],
                    "preset_type": "custom",
                },
            )
        return {
            "generated_at": self.now_fn().isoformat(),
            "recommended_preset": preset_id,
            "preset_type": recommendation["preset_type"],
            "confidence": recommendation["confidence"],
            "reason": recommendation["reason"],
            "reasons": recommendation["reasons"][:4],
            "matched_signals": recommendation["matched_signals"][:5],
            "prefill_settings": dict(preset.get("settings") or {}),
            "alternative_presets": self._build_alternatives(
                selected_preset=preset_id,
                signal_context=signal_context,
            ),
            "preset": preset,
            "sizing_viability": sizing_viability,
            "sizing_guard": sizing_guard,
        }

    def _select_recommendation(self, signal_context: Dict[str, Any]) -> Dict[str, Any]:
        built_in = self._recommend_from_signals(signal_context)
        custom = self._recommend_custom_preset(signal_context)
        if custom and self._should_prefer_custom(custom, built_in, signal_context):
            return custom
        return built_in

    def record_created_from_preset(
        self,
        *,
        preset_name: str,
        preset_source: Any,
        bot: Dict[str, Any],
        key_fields: List[str],
    ) -> None:
        self._record_event(
            event_type="bot_created_from_preset",
            preset_name=preset_name,
            symbol=str(bot.get("symbol") or "").strip().upper(),
            mode=str(bot.get("mode") or "").strip().lower(),
            key_fields=key_fields,
            metadata={"preset_source": str(preset_source or "").strip().lower() or "manual"},
        )

    def record_recommendation_overridden(
        self,
        *,
        selected_preset: str,
        recommended_preset: str,
        symbol: str,
        mode: str,
        investment: Any,
    ) -> None:
        self._record_event(
            event_type="bot_preset_recommendation_overridden",
            preset_name=selected_preset,
            symbol=symbol,
            mode=mode,
            key_fields=[],
            metadata={
                "recommended_preset": recommended_preset,
                "investment": self._safe_float(investment, 0.0),
            },
        )

    def record_custom_applied_to_new_form(
        self,
        *,
        preset_id: str,
        source: Any = None,
        symbol: Any = None,
        mode: Any = None,
    ) -> bool:
        preset = self._get_custom_preset_item(preset_id)
        if preset is None:
            return False
        diagnostics_service = self.audit_diagnostics_service
        enabled_check = getattr(diagnostics_service, "enabled", None)
        is_enabled = enabled_check() if callable(enabled_check) else True
        if diagnostics_service is None or not is_enabled:
            return False
        payload = {
            "event_type": "custom_bot_preset_applied_to_new_form",
            "severity": "INFO",
            "timestamp": self.now_fn().isoformat(),
            "preset_id": str(preset.get("preset_id") or "") or None,
            "preset_name": str(preset.get("name") or "") or None,
            "preset_type": "custom",
            "target_flow": "new_bot_form",
            "symbol": str(symbol or "").strip().upper() or None,
            "mode": str(mode or "").strip().lower() or None,
            "key_fields": [item["field"] for item in list(preset.get("key_fields") or []) if item.get("field")],
            "source": str(source or "").strip().lower() or "manual",
            "requires_fresh_session_times": bool(
                dict(preset.get("session_time_safety") or {}).get("requires_time_selection")
            ),
        }
        diagnostics_service.record_event(payload, throttle_sec=0.0)
        return True

    def validate_new_bot_session_time_requirement(
        self,
        *,
        preset_id: str,
        session_timer_enabled: Any,
        session_start_at: Any,
        session_stop_at: Any,
    ) -> Dict[str, Any] | None:
        preset = self._get_custom_preset_item(preset_id)
        if preset is None:
            return None
        session_time_safety = dict(preset.get("session_time_safety") or {})
        if not session_time_safety.get("requires_time_selection"):
            return None
        if not bool(session_timer_enabled):
            return None

        normalized_start = self._normalize_session_datetime_value(session_start_at)
        normalized_stop = self._normalize_session_datetime_value(session_stop_at)
        if not normalized_start or not normalized_stop:
            return self._fresh_session_time_error(preset)

        try:
            start_dt = datetime.fromisoformat(normalized_start.replace("Z", "+00:00"))
            stop_dt = datetime.fromisoformat(normalized_stop.replace("Z", "+00:00"))
        except ValueError:
            return self._fresh_session_time_error(preset)

        if stop_dt <= start_dt or stop_dt <= self.now_fn():
            return self._fresh_session_time_error(preset)
        return None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalize_preset_id(self, preset_id: str) -> str:
        normalized = str(preset_id or "").strip().lower()
        if normalized not in self.PRESET_ORDER:
            return "manual_blank"
        return normalized

    def _list_custom_preset_items(self) -> List[Dict[str, Any]]:
        service = self.custom_preset_service
        if service is None:
            return []
        items = []
        for preset in service.list_presets():
            items.append(self._build_custom_preset_item(preset))
        return self._sort_custom_preset_items(items)

    def _get_custom_preset_item(self, preset_id: str) -> Dict[str, Any] | None:
        service = self.custom_preset_service
        if service is None:
            return None
        preset = service.get_preset(preset_id)
        if not preset:
            return None
        return self._build_custom_preset_item(preset)

    def _build_custom_preset_item(self, preset: Dict[str, Any]) -> Dict[str, Any]:
        fields = dict(preset.get("fields") or {})
        settings, session_time_safety = self._materialize_custom_settings(fields)
        symbol_hint = str(preset.get("symbol_hint") or "").strip().upper()
        mode_hint = str(preset.get("mode_hint") or "").strip().lower()
        source_bot_id = str(preset.get("source_bot_id") or "").strip()
        reasons = ["saved from existing bot", "custom preset stays editable before save"]
        if symbol_hint:
            reasons.insert(0, f"symbol hint {symbol_hint}")
        if mode_hint and len(reasons) < 4:
            reasons.append(f"mode hint {mode_hint}")
        if session_time_safety.get("requires_time_selection"):
            reasons.insert(0, "pick fresh session time before save")
        elif session_time_safety.get("duration_min"):
            reasons.insert(0, f"session window refreshes to {session_time_safety['duration_min']} min")
        description = "Custom preset"
        if symbol_hint or mode_hint:
            hint_bits = [bit for bit in [symbol_hint, mode_hint] if bit]
            description = f"Custom preset from {' / '.join(hint_bits)}"
        return {
            "preset_id": str(preset.get("preset_id") or ""),
            "preset_type": "custom",
            "name": str(preset.get("preset_name") or "Custom Preset"),
            "description": description,
            "reasons": reasons[:4],
            "settings": settings,
            "fields": fields,
            "key_fields": CustomBotPresetService.build_key_fields(fields),
            "source_bot_id": source_bot_id or None,
            "symbol_hint": symbol_hint or None,
            "mode_hint": mode_hint or None,
            "created_at": preset.get("created_at"),
            "updated_at": preset.get("updated_at"),
            "session_oriented": bool(fields.get("session_timer_enabled")),
            "session_time_safety": session_time_safety,
        }

    def _sort_custom_preset_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            list(items or []),
            key=lambda item: (
                0 if bool(item.get("session_oriented")) else 1,
                -self._parse_sortable_timestamp(item.get("updated_at")),
                str(item.get("name") or "").lower(),
                str(item.get("preset_id") or "").lower(),
            ),
        )

    def _build_signal_context(
        self,
        *,
        symbol: str,
        mode: str,
        investment: float,
        risk_level: str,
        wants_session: bool,
    ) -> Dict[str, Any]:
        symbol_class = self._classify_symbol(symbol)
        manual_mode = mode in {"scalp_pnl", "scalp_market"} or risk_level in {"manual", "custom"}
        budget_small = 0.0 < investment <= self.SMALL_BUDGET_USDT
        budget_moderate = self.SMALL_BUDGET_USDT < investment <= self.MODERATE_BUDGET_USDT
        min_notional_sensitive = (
            0.0 < investment <= self.MAJOR_MIN_NOTIONAL_SENSITIVE_BUDGET_USDT
            if symbol_class == "major"
            else 0.0 < investment <= self.NON_MAJOR_MIN_NOTIONAL_SENSITIVE_BUDGET_USDT
        )
        leverage_sensitive = min_notional_sensitive or risk_level == "low"
        return {
            "symbol": symbol,
            "mode": mode,
            "investment": investment,
            "risk_level": risk_level,
            "wants_session": wants_session,
            "symbol_class": symbol_class,
            "manual_mode": manual_mode,
            "budget_small": budget_small,
            "budget_moderate": budget_moderate,
            "min_notional_sensitive": min_notional_sensitive,
            "leverage_sensitive": leverage_sensitive,
            "major_symbol": symbol_class == "major",
            "high_vol_symbol": symbol_class == "high_vol",
            "non_major_symbol": symbol_class == "non_major",
            "ambiguous_inputs": not symbol and investment <= 0.0,
        }

    def _recommend_from_signals(self, signal_context: Dict[str, Any]) -> Dict[str, Any]:
        matched_signals: List[str] = []
        reasons: List[str] = []
        preset_id = "manual_blank"
        confidence = "low"

        if signal_context.get("manual_mode"):
            matched_signals.extend(["manual_mode_bias", "avoid_false_precision"])
            reasons.extend(
                [
                    "manual or scalp setup requested",
                    "creation-time preset should stay optional",
                ]
            )
            confidence = "medium"
        elif signal_context.get("wants_session"):
            preset_id = "sleep_session"
            matched_signals.extend(
                [
                    "time_bounded_session_intent",
                    "green_grace_stop_bias",
                    "no_new_entries_before_stop",
                ]
            )
            reasons.extend(
                [
                    "time-bounded usage requested",
                    "bounded stop behavior is safer at creation time",
                    "blocks new entries before stop",
                ]
            )
            confidence = "high"
        elif signal_context.get("budget_small") or signal_context.get("min_notional_sensitive"):
            preset_id = "small_balance_safe"
            matched_signals.extend(
                [
                    "capital_guard_bias",
                    "min_notional_sensitivity",
                    "reduce_dense_grid_pressure",
                ]
            )
            reasons.extend(
                [
                    "budget is small for a dense startup",
                    "min-notional sensitivity is likely",
                    "fewer balanced grids are safer",
                ]
            )
            confidence = "high" if signal_context.get("budget_small") else "medium"
        elif signal_context.get("major_symbol") and (
            signal_context.get("budget_moderate")
            or signal_context.get("risk_level") == "low"
            or signal_context.get("investment", 0.0) > self.MODERATE_BUDGET_USDT
        ):
            preset_id = "eth_conservative"
            matched_signals.extend(
                [
                    "major_symbol_safe_default",
                    "balanced_distribution_bias",
                    "advisor_keep_current_style",
                ]
            )
            reasons.extend(
                [
                    "major symbol with usable startup budget",
                    "conservative default is safer than dense tuning",
                    "balanced distribution keeps startup explainable",
                ]
            )
            confidence = "high" if signal_context.get("symbol") == "ETHUSDT" else "medium"
        elif signal_context.get("high_vol_symbol") or signal_context.get("non_major_symbol"):
            preset_id = "high_volatility_safe"
            matched_signals.extend(
                [
                    "volatility_guard_bias",
                    "non_major_symbol_class",
                    "reduce_dense_structure_startup",
                ]
            )
            reasons.extend(
                [
                    "symbol class looks more volatile than majors",
                    "startup should avoid dense aggressive structure",
                    "safer volatility guard is preferred",
                ]
            )
            confidence = "high" if signal_context.get("high_vol_symbol") else "medium"
        else:
            matched_signals.extend(["insufficient_creation_evidence", "manual_review_bias"])
            reasons.extend(
                [
                    "inputs are too weak for a precise preset",
                    "manual blank is safer than a weak match",
                ]
            )
            confidence = "low"

        reason = reasons[0]
        return {
            "recommended_preset": preset_id,
            "preset_type": "built_in",
            "confidence": confidence,
            "reason": reason,
            "reasons": reasons[:4],
            "matched_signals": matched_signals[:5],
        }

    def _recommend_custom_preset(self, signal_context: Dict[str, Any]) -> Dict[str, Any] | None:
        best_match = None
        service = self.custom_preset_service
        if service is None:
            return None
        for raw_preset in service.list_presets():
            preset = self._build_custom_preset_item(raw_preset)
            candidate = self._evaluate_custom_preset(preset, signal_context)
            if candidate is None:
                continue
            if best_match is None or candidate["score"] > best_match["score"]:
                best_match = candidate
        if best_match is None:
            return None
        return {
            "recommended_preset": best_match["preset_id"],
            "preset_type": "custom",
            "confidence": best_match["confidence"],
            "reason": best_match["reason"],
            "reasons": best_match["reasons"][:4],
            "matched_signals": best_match["matched_signals"][:5],
            "score": best_match["score"],
        }

    def _should_prefer_custom(
        self,
        custom_candidate: Dict[str, Any],
        built_in_candidate: Dict[str, Any],
        signal_context: Dict[str, Any],
    ) -> bool:
        custom_score = int(custom_candidate.get("score") or 0)
        if custom_score < 6:
            return False
        if built_in_candidate.get("recommended_preset") == "manual_blank" and custom_score >= 5:
            return True
        if signal_context.get("wants_session"):
            return "custom_session_intent_match" in custom_candidate.get("matched_signals", []) and custom_score >= 6
        if signal_context.get("symbol"):
            return "custom_symbol_exact_match" in custom_candidate.get("matched_signals", []) and custom_score >= 7
        return custom_score >= 7

    def _evaluate_custom_preset(
        self,
        preset: Dict[str, Any],
        signal_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        fields = dict(preset.get("fields") or {})
        symbol_hint = str(preset.get("symbol_hint") or "").strip().upper()
        mode_hint = str(preset.get("mode_hint") or "").strip().lower()
        symbol = str(signal_context.get("symbol") or "").strip().upper()
        mode = str(signal_context.get("mode") or "").strip().lower()
        score = 0
        matched_signals: List[str] = []
        reasons: List[str] = []

        leverage = self._safe_float(fields.get("leverage"), 0.0)
        grid_count = int(fields.get("grid_count") or 0)
        distribution = str(fields.get("grid_distribution") or "").strip().lower()
        session_oriented = bool(fields.get("session_timer_enabled"))
        conservative_shape = leverage > 0 and leverage <= 3.0 and 0 < grid_count <= 10 and distribution in {"", "balanced", "clustered"}
        if leverage > 4.0 or grid_count > 14:
            return None

        if symbol_hint:
            if symbol and symbol_hint == symbol:
                score += 4
                matched_signals.append("custom_symbol_exact_match")
                reasons.append(f"custom preset already matches {symbol}")
            elif symbol and symbol_hint != symbol:
                return None
        elif symbol:
            matched_signals.append("custom_symbol_open_fit")

        if mode_hint:
            if mode and mode_hint == mode:
                score += 2
                matched_signals.append("custom_mode_exact_match")
                reasons.append(f"mode hint matches {mode}")
            elif mode and mode_hint != mode:
                return None

        if signal_context.get("wants_session"):
            if not session_oriented:
                return None
            score += 4
            matched_signals.append("custom_session_intent_match")
            reasons.append("session-oriented custom preset matches bounded runtime intent")
        elif session_oriented:
            score += 1
            matched_signals.append("custom_session_capable")

        if signal_context.get("budget_small") and conservative_shape:
            score += 2
            matched_signals.append("custom_small_budget_safe")
            reasons.append("custom preset keeps startup pressure conservative for smaller capital")
        elif signal_context.get("major_symbol") and conservative_shape:
            score += 1
            matched_signals.append("custom_major_symbol_safe")
            reasons.append("custom preset stays conservative for a major symbol")
        elif signal_context.get("high_vol_symbol") and conservative_shape and distribution == "balanced":
            score += 2
            matched_signals.append("custom_high_vol_safety_bias")
            reasons.append("custom preset avoids dense startup structure for a volatile symbol")

        if conservative_shape:
            score += 1
            matched_signals.append("custom_conservative_shape")
        if fields.get("session_time_selection_required"):
            matched_signals.append("custom_session_requires_fresh_time")
            reasons.append("session timestamps are sanitized and require fresh selection")
        elif fields.get("session_duration_min"):
            matched_signals.append("custom_session_duration_refresh")

        if score < 5:
            return None

        confidence = "high" if score >= 8 else "medium"
        reason = reasons[0] if reasons else "custom preset is a stronger fit than the generic built-ins"
        return {
            "preset_id": str(preset.get("preset_id") or ""),
            "score": score,
            "confidence": confidence,
            "reason": reason,
            "reasons": reasons[:4] or ["custom preset is a stronger fit than the generic built-ins"],
            "matched_signals": matched_signals[:5],
        }

    def _build_alternatives(
        self,
        *,
        selected_preset: str,
        signal_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        custom_candidate = self._recommend_custom_preset(signal_context)
        if custom_candidate and custom_candidate.get("recommended_preset") != selected_preset:
            preset = self.get_preset(custom_candidate["recommended_preset"])
            candidates.append(
                {
                    "preset_id": custom_candidate["recommended_preset"],
                    "name": preset["name"],
                    "reason": custom_candidate["reason"],
                }
            )
        if selected_preset != "manual_blank":
            preset = self.get_preset("manual_blank")
            candidates.append(
                {
                    "preset_id": "manual_blank",
                    "name": preset["name"],
                    "reason": preset["reasons"][0] if preset.get("reasons") else preset.get("description"),
                }
            )
        if signal_context.get("wants_session") and selected_preset != "eth_conservative":
            preset = self.get_preset("eth_conservative")
            candidates.append(
                {
                    "preset_id": "eth_conservative",
                    "name": preset["name"],
                    "reason": preset["reasons"][0] if preset.get("reasons") else preset.get("description"),
                }
            )
        elif signal_context.get("major_symbol") and selected_preset != "small_balance_safe":
            preset = self.get_preset("small_balance_safe")
            candidates.append(
                {
                    "preset_id": "small_balance_safe",
                    "name": preset["name"],
                    "reason": preset["reasons"][0] if preset.get("reasons") else preset.get("description"),
                }
            )
        elif signal_context.get("non_major_symbol") and selected_preset != "high_volatility_safe":
            preset = self.get_preset("high_volatility_safe")
            candidates.append(
                {
                    "preset_id": "high_volatility_safe",
                    "name": preset["name"],
                    "reason": preset["reasons"][0] if preset.get("reasons") else preset.get("description"),
                }
            )
        elif selected_preset != "eth_conservative":
            preset = self.get_preset("eth_conservative")
            candidates.append(
                {
                    "preset_id": "eth_conservative",
                    "name": preset["name"],
                    "reason": preset["reasons"][0] if preset.get("reasons") else preset.get("description"),
                }
            )

        seen = set()
        alternatives: List[Dict[str, Any]] = []
        for candidate in candidates:
            preset_id = str(candidate.get("preset_id") or "").strip().lower()
            if not preset_id or preset_id == selected_preset or preset_id in seen:
                continue
            seen.add(preset_id)
            alternatives.append(candidate)
            if len(alternatives) >= 2:
                break
        return alternatives

    def _materialize_custom_settings(self, fields: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        settings = dict(fields or {})
        session_enabled = bool(settings.get("session_timer_enabled"))
        duration_min = int(settings.get("session_duration_min") or 0) if settings.get("session_duration_min") else 0
        requires_time_selection = bool(settings.get("session_time_selection_required"))
        session_time_safety = {
            "sanitized": bool(session_enabled and (duration_min or requires_time_selection)),
            "duration_min": duration_min or None,
            "requires_time_selection": requires_time_selection,
        }
        settings.pop("session_duration_min", None)
        settings.pop("session_time_selection_required", None)
        if not session_enabled:
            settings["session_start_at"] = None
            settings["session_stop_at"] = None
            return settings, session_time_safety
        settings["session_start_at"] = None
        if duration_min > 0:
            stop_at = self.now_fn().replace(microsecond=0) + timedelta(minutes=duration_min)
            settings["session_stop_at"] = stop_at.isoformat()
        else:
            settings["session_stop_at"] = None
        return settings, session_time_safety

    def _apply_sizing_guard(
        self,
        *,
        recommendation: Dict[str, Any],
        payload: Dict[str, Any],
        signal_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        current_preset_id = str(recommendation.get("recommended_preset") or "").strip().lower()
        if not current_preset_id:
            return None

        current_preset = self.get_preset(current_preset_id)
        current_viability = self._evaluate_preset_sizing_viability(
            payload=payload,
            preset=current_preset,
            signal_context=signal_context,
        )
        if not current_viability or current_viability.get("viable"):
            return None

        candidate_ids = [current_preset_id]
        for item in self._build_alternatives(
            selected_preset=current_preset_id,
            signal_context=signal_context,
        ):
            candidate_id = str(item.get("preset_id") or "").strip().lower()
            if candidate_id and candidate_id not in candidate_ids:
                candidate_ids.append(candidate_id)
        if "manual_blank" not in candidate_ids:
            candidate_ids.append("manual_blank")

        fallback_preset = None
        fallback_viability = None
        for candidate_id in candidate_ids[1:]:
            candidate = self.get_preset(candidate_id)
            viability = self._evaluate_preset_sizing_viability(
                payload=payload,
                preset=candidate,
                signal_context=signal_context,
            )
            if viability and viability.get("viable"):
                fallback_preset = candidate
                fallback_viability = viability
                break

        guard_reason = self._build_sizing_guard_reason(current_viability)
        guard = {
            "blocked_preset_id": current_preset_id,
            "blocked_preset_name": str(current_preset.get("name") or current_preset_id),
            "blocked_reason": current_viability.get("blocked_reason"),
            "blocked_reasons": list(current_viability.get("blocked_reasons") or []),
            "blocked_viability": current_viability,
        }
        if fallback_preset is None:
            recommendation["recommended_preset"] = "manual_blank"
            recommendation["preset_type"] = "built_in"
            recommendation["confidence"] = "low"
            recommendation["reason"] = guard_reason
            recommendation["reasons"] = [
                guard_reason,
                "adjust capital, leverage, or grid count before using a preset",
            ]
            recommendation["matched_signals"] = [
                "exchange_order_sizing_guard",
                *[
                    signal
                    for signal in list(recommendation.get("matched_signals") or [])
                    if signal != "exchange_order_sizing_guard"
                ],
            ][:5]
            guard["fallback_preset_id"] = "manual_blank"
            guard["fallback_viability"] = self._evaluate_preset_sizing_viability(
                payload=payload,
                preset=self.get_preset("manual_blank"),
                signal_context=signal_context,
            )
            return guard

        recommendation["recommended_preset"] = str(fallback_preset.get("preset_id") or current_preset_id)
        recommendation["preset_type"] = str(fallback_preset.get("preset_type") or "built_in")
        recommendation["confidence"] = "medium"
        recommendation["reason"] = guard_reason
        recommendation["reasons"] = [
            guard_reason,
            f"switched to {fallback_preset.get('name') or recommendation['recommended_preset']} because the original slice size was below exchange minimums",
        ]
        recommendation["matched_signals"] = [
            "exchange_order_sizing_guard",
            *[
                signal
                for signal in list(recommendation.get("matched_signals") or [])
                if signal != "exchange_order_sizing_guard"
            ],
        ][:5]
        guard["fallback_preset_id"] = recommendation["recommended_preset"]
        guard["fallback_preset_name"] = str(fallback_preset.get("name") or recommendation["recommended_preset"])
        guard["fallback_viability"] = fallback_viability
        return guard

    def _evaluate_preset_sizing_viability(
        self,
        *,
        payload: Dict[str, Any],
        preset: Dict[str, Any],
        signal_context: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        reference_price = self._safe_float(
            payload.get("reference_price")
            or payload.get("mark_price")
            or payload.get("last_price"),
            0.0,
        )
        min_notional = self._safe_float(
            payload.get("min_notional") or payload.get("min_order_value"),
            0.0,
        )
        min_qty = self._safe_float(
            payload.get("min_qty") or payload.get("min_order_qty"),
            0.0,
        )
        if reference_price <= 0 or (min_notional <= 0 and min_qty <= 0):
            return None

        settings = dict(preset.get("settings") or {})
        grid_count = self._safe_int(
            settings.get("target_grid_count") or settings.get("grid_count"),
            0,
        )
        if grid_count <= 0:
            grid_count = self._safe_int(signal_context.get("grid_count"), 10) or 10
        leverage = self._safe_float(settings.get("leverage"), 0.0)
        if leverage <= 0:
            leverage = self._safe_float(payload.get("leverage"), 0.0)

        return build_order_sizing_viability(
            symbol=signal_context.get("symbol"),
            reference_price=reference_price,
            price_source=payload.get("price_source") or ("mark_price" if payload.get("mark_price") else "last_price"),
            leverage=leverage,
            investment=signal_context.get("investment"),
            order_splits=grid_count,
            min_notional=min_notional,
            min_qty=min_qty,
        )

    @staticmethod
    def _build_sizing_guard_reason(viability: Dict[str, Any]) -> str:
        estimated_qty = viability.get("estimated_per_order_qty")
        min_qty = viability.get("min_qty")
        estimated_notional = viability.get("estimated_per_order_notional")
        effective_min_notional = viability.get("effective_min_order_notional")
        if "below_min_qty" in list(viability.get("blocked_reasons") or []):
            if estimated_qty is not None and min_qty is not None:
                return (
                    f"per-order qty would be {estimated_qty:.6f}, below exchange min qty {min_qty:.6f}"
                )
            return "per-order qty would fall below the exchange minimum quantity"
        if estimated_notional is not None and effective_min_notional is not None:
            return (
                f"per-order notional would be ${estimated_notional:.2f}, below the effective minimum ${effective_min_notional:.2f}"
            )
        return "preset order slices would fall below exchange minimum order size"

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _fresh_session_time_error(self, preset: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "error": "Pick fresh session start and stop times before saving this custom preset bot.",
            "blocked_reason": "fresh_session_times_required",
            "preset_id": str(preset.get("preset_id") or "") or None,
            "preset_name": str(preset.get("name") or "") or None,
            "preset_type": "custom",
            "target_flow": "new_bot_form",
        }

    @staticmethod
    def _normalize_session_datetime_value(value: Any) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat()

    @staticmethod
    def _parse_sortable_timestamp(value: Any) -> float:
        raw = str(value or "").strip()
        if not raw:
            return float("-inf")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.timestamp()

    def _classify_symbol(self, symbol: str) -> str:
        if not symbol:
            return "unknown"
        if symbol in NEUTRAL_MAJOR_SYMBOLS:
            return "major"
        if symbol in self.HIGH_VOLATILITY_SYMBOLS:
            return "high_vol"
        return "non_major"

    def _build_settings(self, preset_id: str) -> Dict[str, Any]:
        base = {
            "range_mode": "fixed",
            "leverage": 3.0,
            "grid_count": 10,
            "target_grid_count": 10,
            "grid_distribution": "clustered",
            "neutral_volatility_gate_threshold_pct": 5.0,
            "session_timer_enabled": False,
            "session_start_at": None,
            "session_stop_at": None,
            "session_no_new_entries_before_stop_min": 15,
            "session_end_mode": "hard_stop",
            "session_green_grace_min": 5,
            "session_cancel_pending_orders_on_end": True,
            "session_reduce_only_on_end": False,
        }
        if preset_id == "eth_conservative":
            base.update(
                {
                    "leverage": 3.0,
                    "grid_count": 10,
                    "target_grid_count": 10,
                    "grid_distribution": "balanced",
                }
            )
        elif preset_id == "small_balance_safe":
            base.update(
                {
                    "leverage": 3.0,
                    "grid_count": 6,
                    "target_grid_count": 6,
                    "grid_distribution": "balanced",
                }
            )
        elif preset_id == "sleep_session":
            stop_at = self.now_fn().replace(microsecond=0) + timedelta(hours=self.DEFAULT_SLEEP_DURATION_HOURS)
            base.update(
                {
                    "leverage": 3.0,
                    "grid_count": 8,
                    "target_grid_count": 8,
                    "grid_distribution": "balanced",
                    "session_timer_enabled": True,
                    "session_start_at": None,
                    "session_stop_at": stop_at.isoformat(),
                    "session_no_new_entries_before_stop_min": 20,
                    "session_end_mode": "green_grace_then_stop",
                    "session_green_grace_min": 15,
                    "session_cancel_pending_orders_on_end": True,
                    "session_reduce_only_on_end": True,
                }
            )
        elif preset_id == "high_volatility_safe":
            base.update(
                {
                    "leverage": 2.0,
                    "grid_count": 6,
                    "target_grid_count": 6,
                    "grid_distribution": "balanced",
                    "neutral_volatility_gate_threshold_pct": 4.0,
                }
            )
        return base

    @staticmethod
    def _preset_name(preset_id: str) -> str:
        names = {
            "eth_conservative": "ETH Conservative",
            "small_balance_safe": "Small Balance Safe",
            "sleep_session": "Sleep Session",
            "high_volatility_safe": "High Volatility Safe",
            "manual_blank": "Manual Blank",
        }
        return names.get(preset_id, "Manual Blank")

    @staticmethod
    def _preset_description(preset_id: str) -> str:
        descriptions = {
            "eth_conservative": "Conservative major-coin defaults for new grid bots.",
            "small_balance_safe": "Safer small-budget setup with fewer grids.",
            "sleep_session": "Bounded session defaults for limited runtime operation.",
            "high_volatility_safe": "Safer defaults for higher-volatility symbols.",
            "manual_blank": "Leave the form on editable baseline defaults.",
        }
        return descriptions.get(preset_id, "Leave the form on editable baseline defaults.")

    @staticmethod
    def _preset_reasons(preset_id: str) -> List[str]:
        reasons = {
            "eth_conservative": [
                "major-coin posture",
                "balanced distribution",
                "keeps leverage conservative",
            ],
            "small_balance_safe": [
                "small balance sensitive to min notional",
                "reduces grid pressure",
                "keeps distribution balanced",
            ],
            "sleep_session": [
                "bounded runtime window",
                "blocks new entries before stop",
                "green grace then stop",
            ],
            "high_volatility_safe": [
                "higher-volatility symbol posture",
                "reduced grid density",
                "tighter volatility gate",
            ],
            "manual_blank": [
                "editable baseline defaults",
                "no preset lock-in",
                "safer when evidence is incomplete",
            ],
        }
        return list(reasons.get(preset_id, reasons["manual_blank"]))

    @classmethod
    def _key_fields(cls, settings: Dict[str, Any]) -> List[Dict[str, Any]]:
        fields = (
            "leverage",
            "grid_count",
            "grid_distribution",
            "session_timer_enabled",
            "session_end_mode",
            "session_stop_at",
        )
        items: List[Dict[str, Any]] = []
        for field in fields:
            if field not in settings:
                continue
            value = settings.get(field)
            if field == "session_end_mode" and not settings.get("session_timer_enabled"):
                continue
            if field == "session_stop_at" and not value:
                continue
            items.append(
                {
                    "field": field,
                    "label": cls._field_label(field),
                    "value": value,
                }
            )
        return items

    @staticmethod
    def _field_label(field: str) -> str:
        labels = {
            "leverage": "Leverage",
            "grid_count": "Grid count",
            "grid_distribution": "Grid distribution",
            "session_timer_enabled": "Session timer",
            "session_end_mode": "Session end mode",
            "session_stop_at": "Session stop",
        }
        return labels.get(field, field.replace("_", " "))

    def _record_event(
        self,
        *,
        event_type: str,
        preset_name: str,
        symbol: str,
        mode: str,
        key_fields: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        diagnostics_service = self.audit_diagnostics_service
        enabled_check = getattr(diagnostics_service, "enabled", None)
        is_enabled = enabled_check() if callable(enabled_check) else True
        if diagnostics_service is None or not is_enabled:
            return
        payload = {
            "event_type": event_type,
            "severity": "INFO",
            "timestamp": self.now_fn().isoformat(),
            "preset_name": preset_name,
            "symbol": symbol or None,
            "mode": mode or None,
            "key_fields": list(key_fields or []),
        }
        payload.update(dict(metadata or {}))
        diagnostics_service.record_event(payload, throttle_sec=0.0)
