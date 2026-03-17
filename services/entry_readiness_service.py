"""
Entry readiness preview service.

Builds a read-only entry readiness snapshot for dashboard/runtime consumers
without mutating bot state or affecting trading execution.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import config.strategy_config as cfg
from services.entry_gate_service import EntryGateService
from services.neutral_suitability_service import NeutralSuitabilityService


class EntryReadinessService:
    """Lightweight preview-only entry readiness evaluator."""

    DIRECTIONAL_MODES = {"long", "short"}
    NEUTRAL_MODES = {"neutral", "neutral_classic_bybit"}
    SCALP_MODES = {"scalp_market", "scalp_pnl"}
    AUTO_PILOT_PLACEHOLDER = "AUTO-PILOT"
    RUNTIME_ACTIVE_STATUSES = {
        "running",
        "paused",
        "recovering",
        "flash_crash_paused",
    }

    def __init__(
        self,
        indicator_service: Optional[Any],
        cache_ttl_seconds: int = 15,
        entry_gate_service: Optional[EntryGateService] = None,
        neutral_suitability_service: Optional[NeutralSuitabilityService] = None,
        live_preview_enabled: bool = False,
        stopped_preview_enabled: bool = False,
        market_data_provider: Optional[Any] = None,
    ):
        self.indicator_service = indicator_service
        self.cache_ttl_seconds = max(int(cache_ttl_seconds or 0), 1)
        self.live_preview_enabled = bool(live_preview_enabled)
        self.stopped_preview_enabled = bool(stopped_preview_enabled)
        self.market_data_provider = market_data_provider
        self.entry_gate_service = entry_gate_service or (
            EntryGateService(indicator_service) if indicator_service else None
        )
        self.neutral_suitability_service = neutral_suitability_service or (
            NeutralSuitabilityService(indicator_service) if indicator_service else None
        )
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._indicator_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _iso_from_ts(value: Optional[float]) -> Optional[str]:
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return None
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    @classmethod
    def _parse_timestamp(cls, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return numeric if numeric > 0 else None
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @classmethod
    def _record_market_data_context(
        cls,
        context: Optional[Dict[str, Any]],
        *,
        source: str,
        transport: Optional[str],
        price: Optional[float],
        timestamp: Optional[float],
        timestamp_source: Optional[str] = None,
        exchange_ts: Optional[float] = None,
    ) -> None:
        if context is None:
            return
        if price is None or price <= 0:
            return
        context["market_data_source"] = str(source or "").strip().lower() or "unknown"
        context["market_data_transport"] = (
            str(transport or "").strip().lower() or None
        )
        context["market_data_price"] = round(float(price), 8)
        if timestamp is not None and timestamp > 0:
            context["market_data_ts"] = float(timestamp)
            context["market_data_at"] = cls._iso_from_ts(timestamp)
        if timestamp_source:
            context["market_data_ts_source"] = str(timestamp_source).strip().lower()
        if exchange_ts is not None and exchange_ts > 0:
            context["market_data_exchange_ts"] = float(exchange_ts)
            context["market_data_exchange_at"] = cls._iso_from_ts(exchange_ts)

    @staticmethod
    def _attach_market_data_context(
        payload: Dict[str, Any],
        market_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = dict(payload or {})
        for key, value in dict(market_context or {}).items():
            if value is not None:
                result[key] = value
        return result

    def evaluate_bot(
        self,
        bot: Optional[Dict[str, Any]],
        *,
        allow_stopped_analysis_preview: Optional[bool] = None,
    ) -> Dict[str, Any]:
        started_at_ts = self._get_now_ts()
        eval_started_at = datetime.now(timezone.utc).isoformat()
        safe_bot = dict(bot or {})
        symbol = str(safe_bot.get("symbol") or "").strip().upper()
        mode = str(safe_bot.get("mode") or "").strip().lower()
        status = str(safe_bot.get("status") or "").strip().lower()
        cleanup_pending = status == "stop_cleanup_pending" or bool(
            safe_bot.get("stop_cleanup_pending")
        )
        market_context: Dict[str, Any] = {}
        if allow_stopped_analysis_preview is None:
            allow_stopped_analysis_preview = (
                self.stopped_preview_enabled or self.live_preview_enabled
            )

        if cleanup_pending:
            pending_detail = str(safe_bot.get("last_error") or "").strip() or (
                "Stop cleanup is still pending. No new trading should occur until "
                "orders are cleared and the position is flat."
            )
            live_result = self._build_result(
                status="watch",
                reason="stop_cleanup_pending",
                reason_text="Stop cleanup pending",
                detail=pending_detail,
                mode=mode or None,
                direction="none",
                source="stop_cleanup_pending",
            )
            analysis_result = dict(live_result)
        else:
            live_result = self._evaluate_live_readiness(
                safe_bot,
                symbol=symbol,
                mode=mode,
                status=status,
                market_context=market_context,
            )
            analysis_result = self._evaluate_analysis_readiness(
                safe_bot,
                symbol=symbol,
                mode=mode,
                status=status,
                allow_stopped_analysis_preview=bool(allow_stopped_analysis_preview),
                market_context=market_context,
            )
        analysis_payload = self._build_analysis_payload(analysis_result)
        timing_payload = self._build_setup_timing_payload(
            result=analysis_result,
            analysis_payload=analysis_payload,
        )
        result = dict(live_result)
        result.update(analysis_payload)
        result.update(timing_payload)
        result.update(self._build_setup_readiness_payload(analysis_payload))
        if cleanup_pending:
            result.update(
                self._build_stop_cleanup_execution_payload(
                    detail=str(live_result.get("entry_ready_detail") or "").strip()
                )
            )
        else:
            result.update(self._build_execution_viability_payload(safe_bot, mode=mode))
        result.update(self._build_live_gate_payload(safe_bot, mode))
        result["readiness_source_kind"] = (
            "stop_cleanup_pending"
            if cleanup_pending
            else self._derive_readiness_source_kind(
                status=status,
                analysis_payload=analysis_payload,
            )
        )
        result["readiness_fallback_used"] = bool(
            analysis_payload.get("analysis_ready_fallback_used")
        )
        finished_at_ts = self._get_now_ts()
        finished_at_iso = datetime.now(timezone.utc).isoformat()
        if not market_context:
            for source_payload in (analysis_result, live_result):
                if not isinstance(source_payload, dict):
                    continue
                for key in (
                    "market_data_ts",
                    "market_data_at",
                    "market_data_source",
                    "market_data_transport",
                    "market_data_price",
                    "market_data_ts_source",
                    "market_data_exchange_ts",
                    "market_data_exchange_at",
                ):
                    value = source_payload.get(key)
                    if value is not None:
                        market_context[key] = value
        market_ts = self._parse_timestamp(market_context.get("market_data_ts"))
        market_provider_ts = self._parse_timestamp(market_context.get("market_provider_ts"))
        result.update(market_context)
        result["readiness_eval_started_at"] = eval_started_at
        result["readiness_eval_finished_at"] = finished_at_iso
        result["readiness_evaluated_at"] = finished_at_iso
        result["readiness_generated_at"] = finished_at_iso
        result["readiness_eval_duration_ms"] = round(
            max(finished_at_ts - started_at_ts, 0.0) * 1000.0,
            2,
        )
        result["readiness_eval_ms"] = result["readiness_eval_duration_ms"]
        result["readiness_stage"] = timing_payload.get("setup_timing_status")

        # Order flow overlay: annotate readiness with tick-level flow data
        flow_score = safe_bot.get("flow_score")
        flow_signal = safe_bot.get("flow_signal")
        flow_confidence = safe_bot.get("flow_confidence")
        if flow_score is not None:
            result["flow_score"] = flow_score
            result["flow_signal"] = flow_signal
            result["flow_confidence"] = flow_confidence
            # Promote watch→armed when flow strongly confirms direction
            current_status = str(result.get("entry_ready_status") or "").strip().lower()
            if current_status == "watch" and mode in ("long", "short"):
                flow_confirms = (
                    (mode == "long" and float(flow_score or 0) >= 30 and float(flow_confidence or 0) >= 0.4)
                    or (mode == "short" and float(flow_score or 0) <= -30 and float(flow_confidence or 0) >= 0.4)
                )
                if flow_confirms:
                    result["entry_ready_status"] = "armed"
                    result["entry_ready_reason"] = "flow_momentum"
                    result["entry_ready_reason_text"] = f"Flow {flow_signal} (score {float(flow_score):.0f})"
                    result["entry_ready_detail"] = (
                        f"Tick-level trade flow confirms {mode} direction. "
                        f"Score={float(flow_score):.0f}, confidence={float(flow_confidence or 0):.0%}"
                    )
        result["readiness_source"] = (
            analysis_payload.get("analysis_ready_source")
            or live_result.get("entry_ready_source")
        )
        result["market_data_age_ms"] = (
            round(max(started_at_ts - market_ts, 0.0) * 1000.0, 2)
            if market_ts is not None and market_ts > 0
            else None
        )
        result["market_to_readiness_eval_start_ms"] = result["market_data_age_ms"]
        result["market_to_readiness_eval_finished_ms"] = (
            round(max(finished_at_ts - market_ts, 0.0) * 1000.0, 2)
            if market_ts is not None and market_ts > 0
            else None
        )
        result["market_provider_age_ms"] = (
            round(max(started_at_ts - market_provider_ts, 0.0) * 1000.0, 2)
            if market_provider_ts is not None and market_provider_ts > 0
            else None
        )
        market_transport = str(result.get("market_data_transport") or "").strip().lower()
        provider_transport = str(result.get("market_provider_transport") or "").strip().lower()
        stream_transport = provider_transport or market_transport
        if stream_transport.startswith("stream_"):
            result["ticker_provider_updated_at"] = (
                result.get("market_provider_at") or result.get("market_data_at")
            )
            result["ticker_provider_age_ms"] = (
                result["market_provider_age_ms"]
                if result.get("market_provider_age_ms") is not None
                else result.get("market_data_age_ms")
            )
            result["ticker_used_at_eval"] = result.get("market_data_at")
            result["fresher_ticker_available"] = bool(
                result.get("market_data_refreshed_just_in_time")
            )
        return result

    @staticmethod
    def _build_stop_cleanup_execution_payload(detail: str) -> Dict[str, Any]:
        execution_detail = (
            "Stop cleanup is pending. Execution readiness is informational only until "
            "the symbol is flat and open orders are cleared."
        )
        if detail:
            execution_detail = f"{execution_detail} Current state: {detail}"
        updated_at = datetime.now(timezone.utc).isoformat()
        return {
            "execution_blocked": True,
            "execution_viability_status": "blocked",
            "execution_viability_reason": "stop_cleanup_pending",
            "execution_viability_reason_text": "Stop cleanup pending",
            "execution_viability_bucket": "blocked",
            "execution_margin_limited": False,
            "execution_viability_detail": execution_detail,
            "execution_viability_source": "stop_cleanup_pending",
            "execution_viability_diagnostic_reason": "stop_cleanup_pending",
            "execution_viability_diagnostic_text": "Stop cleanup pending",
            "execution_viability_diagnostic_detail": execution_detail,
            "execution_viability_stale_data": True,
            "execution_available_margin_usdt": None,
            "execution_required_margin_usdt": None,
            "execution_order_notional_usdt": None,
            "execution_viability_updated_at": updated_at,
        }

    def _evaluate_live_readiness(
        self,
        safe_bot: Dict[str, Any],
        *,
        symbol: str,
        mode: str,
        status: str,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        blocked_budget = bool(
            safe_bot.get("_auto_pilot_loss_budget_block_openings")
            or safe_bot.get("auto_pilot_opening_blocked_by_loss_budget")
            or str(safe_bot.get("auto_pilot_loss_budget_state") or "").strip().lower()
            == "blocked"
        )
        if blocked_budget:
            return self._build_result(
                status="blocked",
                reason="loss_budget_blocked",
                reason_text="Loss budget blocked",
                detail=self._format_loss_budget_detail(safe_bot),
                mode=mode or None,
                direction="none",
                source="runtime_loss_budget",
            )

        if symbol == self.AUTO_PILOT_PLACEHOLDER:
            detail = "Awaiting Auto-Pilot symbol pick"
            top_candidate = str(
                safe_bot.get("auto_pilot_top_candidate_symbol") or ""
            ).strip().upper()
            top_mode = str(safe_bot.get("auto_pilot_top_candidate_mode") or "").strip().lower()
            if top_candidate:
                detail = f"Awaiting Auto-Pilot symbol pick; top candidate {top_candidate}"
                if top_mode:
                    detail = f"{detail} ({top_mode})"
            result = self._build_result(
                status="watch",
                reason="awaiting_symbol_pick",
                reason_text="Awaiting symbol pick",
                detail=detail,
                mode=top_mode or (mode or None),
                direction="none",
                source="auto_pilot_placeholder",
            )
            return self._overlay_low_budget_watch(safe_bot, result)

        if not status or status in self.RUNTIME_ACTIVE_STATUSES:
            runtime_result = self._evaluate_from_runtime_state(
                safe_bot,
                symbol,
                mode,
            )
            if runtime_result is not None:
                runtime_result = self._overlay_runtime_execution_blocker(
                    safe_bot,
                    runtime_result,
                    mode=mode,
                )
                return self._overlay_low_budget_watch(safe_bot, runtime_result)

        if mode in self.DIRECTIONAL_MODES and not self._is_directional_entry_gate_active(
            safe_bot
        ):
            global_disabled = not getattr(cfg, "ENTRY_GATE_ENABLED", False)
            return self._overlay_low_budget_watch(
                safe_bot,
                self._build_entry_gate_disabled_result(
                    mode=mode or None,
                    direction=mode or "none",
                    detail=(
                        "Directional entry gate disabled globally"
                        if global_disabled
                        else "Directional entry gate disabled for this bot"
                    ),
                    global_disabled=global_disabled,
                ),
            )

        if mode in (self.NEUTRAL_MODES | self.SCALP_MODES) and not safe_bot.get(
            "entry_gate_enabled",
            True,
        ):
            return self._overlay_low_budget_watch(
                safe_bot,
                self._build_entry_gate_disabled_result(
                    mode=mode or None,
                    direction="none",
                    detail="Entry gate disabled for this bot",
                ),
            )

        if not self.live_preview_enabled:
            return self._overlay_low_budget_watch(
                safe_bot,
                self._build_result(
                    status="watch",
                    reason="preview_disabled",
                    reason_text="Preview disabled",
                    detail=(
                        "Live preview is disabled for stopped bots. "
                        "This is not a trade block; wait for a fresh runtime snapshot or enable live preview."
                    ),
                    mode=mode or None,
                    direction="none",
                    source="runtime_only",
                ),
            )

        if not symbol or not mode:
            return self._build_result(
                status="watch",
                reason="preview_unavailable",
                reason_text="Preview unavailable",
                detail="Missing symbol or mode",
                mode=mode or None,
                direction="none",
                source="incomplete_context",
            )

        if self.entry_gate_service is None:
            return self._build_result(
                status="watch",
                reason="preview_unavailable",
                reason_text="Preview unavailable",
                detail="Indicator service unavailable",
                mode=mode,
                direction="none",
                source="service_unavailable",
            )

        if mode in self.DIRECTIONAL_MODES:
            result = self._evaluate_directional(
                safe_bot,
                symbol,
                mode,
                market_context=market_context,
            )
        elif mode in self.NEUTRAL_MODES:
            result = self._evaluate_neutral(
                safe_bot,
                symbol,
                mode,
                market_context=market_context,
            )
        elif mode in self.SCALP_MODES:
            result = self._evaluate_scalp(
                safe_bot,
                symbol,
                mode,
                market_context=market_context,
            )
        else:
            result = self._build_result(
                status="watch",
                reason="preview_limited",
                reason_text="Preview limited",
                detail=(
                    f"Mode {mode} is not supported by readiness preview. "
                    "Use live runtime state for a trading decision."
                ),
                mode=mode,
                direction="none",
                source="unsupported_mode",
            )

        result = self._overlay_runtime_execution_blocker(
            safe_bot,
            result,
            mode=mode,
        )
        return self._overlay_low_budget_watch(safe_bot, result)

    def _evaluate_analysis_readiness(
        self,
        bot: Dict[str, Any],
        *,
        symbol: str,
        mode: str,
        status: str,
        allow_stopped_analysis_preview: bool,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not symbol or not mode:
            return self._build_result(
                status="watch",
                reason="preview_unavailable",
                reason_text="Preview unavailable",
                detail="Missing symbol or mode",
                mode=mode or None,
                direction="none",
                source="incomplete_context",
            )

        if not status or status in self.RUNTIME_ACTIVE_STATUSES:
            runtime_result = self._evaluate_analysis_from_runtime_state(bot, mode)
            if runtime_result is not None:
                if self._should_use_fresh_active_directional_analysis(
                    bot,
                    mode=mode,
                    runtime_result=runtime_result,
                ):
                    fresh_result = self._evaluate_directional_analysis(
                        bot,
                        symbol,
                        mode,
                        market_context=market_context,
                    )
                    return self._mark_analysis_fallback(
                        fresh_result,
                        runtime_result=runtime_result,
                    )
                return runtime_result

        if not allow_stopped_analysis_preview:
            return self._build_result(
                status="watch",
                reason="preview_disabled",
                reason_text="Preview disabled",
                detail=(
                    "Stopped-bot analysis preview is currently unavailable. "
                    "This is not a trade block; wait for a fresh runtime snapshot or enable bounded preview."
                ),
                mode=mode or None,
                direction="none",
                source="runtime_only",
            )

        if self.entry_gate_service is None:
            return self._build_result(
                status="watch",
                reason="preview_unavailable",
                reason_text="Preview unavailable",
                detail="Indicator service unavailable",
                mode=mode,
                direction="none",
                source="service_unavailable",
            )

        if mode in self.DIRECTIONAL_MODES:
            return self._evaluate_directional_analysis(
                bot,
                symbol,
                mode,
                market_context=market_context,
            )
        if mode in self.NEUTRAL_MODES:
            analysis_bot = dict(bot)
            analysis_bot["entry_gate_enabled"] = True
            return self._evaluate_neutral(
                analysis_bot,
                symbol,
                mode,
                market_context=market_context,
            )
        if mode in self.SCALP_MODES:
            analysis_bot = dict(bot)
            analysis_bot["entry_gate_enabled"] = True
            return self._evaluate_scalp(
                analysis_bot,
                symbol,
                mode,
                market_context=market_context,
            )
        return self._build_result(
            status="watch",
            reason="preview_limited",
            reason_text="Preview limited",
            detail=(
                f"Mode {mode} is not supported by readiness preview. "
                "Use live runtime state for a trading decision."
            ),
            mode=mode,
            direction="none",
            source="unsupported_mode",
        )

    def _evaluate_analysis_from_runtime_state(
        self,
        bot: Dict[str, Any],
        mode: str,
    ) -> Optional[Dict[str, Any]]:
        if mode in self.DIRECTIONAL_MODES:
            blocked_reason = str(bot.get("_entry_gate_blocked_reason") or "").strip()
            if self._is_directional_entry_gate_active(bot) and bot.get("_entry_gate_blocked") and blocked_reason:
                mapped = self._map_reason_text(blocked_reason)
                return self._build_result(
                    status="blocked",
                    reason=mapped["code"],
                    reason_text=mapped["text"],
                    detail=blocked_reason,
                    score=self._safe_float(bot.get("setup_quality_score"), None),
                    mode=mode,
                    direction=mode,
                    source="runtime_entry_gate",
                )
            return self._build_runtime_setup_quality_result(
                bot,
                mode=mode,
                direction=mode,
            )

        if mode in self.NEUTRAL_MODES:
            gate_reason = str(bot.get("_gate_blocked_reason") or "").strip()
            if (
                bool(bot.get("entry_gate_enabled", True))
                and bot.get("_nlp_block_opening_orders")
                and gate_reason
                and not gate_reason.startswith("BYPASSED:")
            ):
                mapped = self._map_reason_text(gate_reason)
                return self._build_result(
                    status="blocked",
                    reason=mapped["code"],
                    reason_text=mapped["text"],
                    detail=gate_reason,
                    score=self._safe_float(bot.get("setup_quality_score"), None),
                    mode=mode,
                    direction="neutral",
                    source="runtime_neutral_gate",
                )
            return self._build_runtime_setup_quality_result(
                bot,
                mode=mode,
                direction="neutral",
            )

        if mode in self.SCALP_MODES:
            direction = str(bot.get("scalp_signal_direction") or "").strip().lower()
            if direction not in {"long", "short"}:
                direction = "none"
            return self._build_runtime_setup_quality_result(
                bot,
                mode=mode,
                direction=direction,
                ready_status="watch",
                ready_reason="preview_limited",
                ready_reason_text="Preview limited",
                ready_detail="Scalp readiness reuses runtime setup quality only",
                source="runtime_scalp_preview",
            )

        return None

    def _evaluate_directional_analysis(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mode: str,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._is_directional_entry_gate_active(bot):
            return self._evaluate_directional(
                bot,
                symbol,
                mode,
                market_context=market_context,
            )

        breakout_required = bool(
            getattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", False)
            and bool(bot.get("breakout_confirmed_entry", False))
        )
        cache_key = f"directional_analysis:{symbol}:{mode}:{int(breakout_required)}"
        cached = self._get_cached(self._cache, cache_key)
        if cached is not None:
            return cached

        # Pullback watch: surface as "armed" with pullback-specific reason
        if bot.get("_pullback_watch_active") and bot.get("_pullback_watch_direction") == mode:
            pb_depth = float(bot.get("_pullback_watch_pullback_depth_pct") or 0)
            pb_ext = str(bot.get("_pullback_watch_peak_extension") or "tracking")
            pb_ago = ""
            _pb_at = bot.get("_pullback_watch_activated_at")
            if _pb_at:
                try:
                    pb_ago = f", {int(time.time() - float(_pb_at))}s ago"
                except (TypeError, ValueError):
                    pass
            pb_result = self._build_result(
                status="armed",
                reason="pullback_watch",
                reason_text=f"Pullback watch ({pb_depth:.1f}% depth)",
                detail=f"HTF trend intact. Waiting for {pb_ext} extension to ease{pb_ago}.",
                score=None,
                mode=mode,
                direction=mode,
                source="analysis_pullback_watch",
            )
            if market_context:
                pb_result = self._attach_market_data_context(pb_result, market_context)
            return self._set_cached(self._cache, cache_key, pb_result)

        indicators = self._get_indicator_snapshot(
            symbol=symbol,
            interval=cfg.ENTRY_GATE_TIMEFRAME,
            limit=100,
        )
        current_price = self._resolve_current_price(
            symbol=symbol,
            bot=bot,
            indicators=indicators,
            market_context=market_context,
        )
        structure_result = self.entry_gate_service.check_side_open(
            symbol=symbol,
            side="Buy" if mode == "long" else "Sell",
            current_price=current_price,
            indicators=indicators or None,
        )
        structure_scores = structure_result.get("scores") or {}
        setup_quality = self.entry_gate_service.get_setup_quality(
            symbol=symbol,
            mode=mode,
            current_price=current_price,
            indicators=indicators or None,
            structure={
                "nearest_support": structure_scores.get("nearest_support"),
                "nearest_resistance": structure_scores.get("nearest_resistance"),
                "adverse_level": structure_scores.get("adverse_level"),
            },
            price_action_context=structure_scores.get("price_action"),
            side_result=structure_scores.get("price_action_side"),
            suppress_components=[
                "adverse_structure"
                for code in (structure_result.get("blocked_by") or [])
                if str(code or "").strip().upper() in {"RESISTANCE_NEARBY", "SUPPORT_NEARBY"}
            ],
        )
        score = self._safe_float((setup_quality or {}).get("score"), None)

        breakout_confirmation = {
            "required": bool(breakout_required),
            "confirmed": not bool(breakout_required),
        }
        entry_signal = self.entry_gate_service.classify_directional_entry_signal(
            mode=mode,
            setup_quality=setup_quality,
            breakout_confirmation=breakout_confirmation,
        )
        relax_structure_block = getattr(
            self.entry_gate_service,
            "_maybe_relax_directional_structure_block",
            None,
        )
        if callable(relax_structure_block):
            structure_result = relax_structure_block(
                mode=mode,
                side="Buy" if mode == "long" else "Sell",
                structure_result=structure_result,
                setup_quality=setup_quality,
                breakout_confirmation=breakout_confirmation,
                entry_signal=entry_signal,
            )

        if not structure_result.get("suitable", True):
            reason = self._map_side_gate_reason(structure_result)
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="blocked",
                        reason=reason["code"],
                        reason_text=reason["text"],
                        detail=structure_result.get("reason") or reason["text"],
                        score=score,
                        mode=mode,
                        direction=mode,
                        source="analysis_structure",
                    ),
                    market_context,
                ),
            )

        if breakout_required:
            breakout_confirmation = self.entry_gate_service.check_breakout_confirmation(
                symbol=symbol,
                mode=mode,
                current_price=current_price,
                structure={
                    "nearest_support": structure_scores.get("nearest_support"),
                    "nearest_resistance": structure_scores.get("nearest_resistance"),
                    "adverse_level": structure_scores.get("adverse_level"),
                },
                price_action_context=structure_scores.get("price_action"),
                setup_quality=setup_quality,
            )
            if not breakout_confirmation.get("confirmed", True):
                reason = self._map_directional_block_reason(
                    {
                        "blocked_by": [
                            breakout_confirmation.get("block_code")
                            or "BREAKOUT_NOT_CONFIRMED"
                        ],
                        "reason": breakout_confirmation.get("reason"),
                    }
                )
                return self._set_cached(
                    self._cache,
                    cache_key,
                    self._attach_market_data_context(
                        self._attach_setup_quality_context(
                            self._build_result(
                                status="blocked",
                                reason=reason["code"],
                                reason_text=reason["text"],
                                detail=breakout_confirmation.get("reason")
                                or reason["text"],
                                score=score,
                                mode=mode,
                                direction=mode,
                                source="analysis_breakout",
                            ),
                            setup_quality=setup_quality,
                        ),
                        market_context,
                    ),
                )

        watch_reason = self._watch_reason_from_setup_quality(
            setup_quality,
            breakout_required=breakout_required,
        )
        if watch_reason is not None:
            # Check if 5m fast trigger can promote watch → armed
            fast_trigger = self._check_fast_trigger(
                symbol=symbol,
                direction=mode,
                score_15m=score,
            )
            if fast_trigger and fast_trigger.get("promoted"):
                fast_result = self._build_result(
                    status="armed",
                    reason="fast_trigger_armed",
                    reason_text="5m momentum aligned",
                    detail=fast_trigger.get("detail")
                    or "Fast timeframe confirms direction",
                    score=score,
                    mode=mode,
                    direction=mode,
                    source="analysis_fast_trigger",
                )
                fast_result["_entry_signal_code"] = "continuation_entry"
                fast_result["_entry_signal_phase"] = "armed"
                return self._set_cached(
                    self._cache,
                    cache_key,
                    self._attach_market_data_context(
                        self._attach_setup_quality_context(
                            fast_result,
                            setup_quality=setup_quality,
                        ),
                        market_context,
                    ),
                )
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._attach_setup_quality_context(
                        self._build_result(
                            status="watch",
                            reason=watch_reason["code"],
                            reason_text=watch_reason["text"],
                            detail=(setup_quality or {}).get("summary")
                            or "Waiting for stronger setup",
                            score=score,
                            mode=mode,
                            direction=mode,
                            source="analysis_setup_quality",
                        ),
                        setup_quality=setup_quality,
                    ),
                    market_context,
                ),
            )

        entry_signal = self.entry_gate_service.classify_directional_entry_signal(
            mode=mode,
            setup_quality=setup_quality,
            breakout_confirmation=breakout_confirmation,
        )
        return self._set_cached(
            self._cache,
            cache_key,
            self._attach_market_data_context(
                self._attach_setup_quality_context(
                    self._decorate_directional_ready_result(
                        self._build_result(
                        status="ready",
                        reason="ready",
                        reason_text="Entry allowed now",
                        detail=(setup_quality or {}).get("summary")
                        or "Entry conditions are executable right now.",
                        score=score,
                        mode=mode,
                        direction=mode,
                        source="analysis_directional",
                        ),
                        signal=entry_signal,
                    ),
                    setup_quality=setup_quality,
                ),
                market_context,
            ),
        )

    def _evaluate_from_runtime_state(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mode: str,
    ) -> Optional[Dict[str, Any]]:
        if not symbol or not mode:
            return None
        if mode in self.DIRECTIONAL_MODES:
            return self._evaluate_directional_runtime(bot, mode)
        if mode in self.NEUTRAL_MODES:
            return self._evaluate_neutral_runtime(bot, mode)
        if mode in self.SCALP_MODES:
            return self._evaluate_scalp_runtime(bot, mode)
        return None

    def _evaluate_directional_runtime(
        self,
        bot: Dict[str, Any],
        mode: str,
    ) -> Optional[Dict[str, Any]]:
        if not self._is_directional_entry_gate_active(bot):
            global_disabled = not getattr(cfg, "ENTRY_GATE_ENABLED", False)
            return self._build_entry_gate_disabled_result(
                mode=mode,
                direction=mode,
                detail=(
                    "Directional entry gate disabled globally"
                    if global_disabled
                    else "Directional entry gate disabled for this bot"
                ),
                global_disabled=global_disabled,
            )

        blocked_reason = str(bot.get("_entry_gate_blocked_reason") or "").strip()
        if bot.get("_entry_gate_blocked") and blocked_reason:
            mapped = self._map_reason_text(blocked_reason)
            return self._build_result(
                status="blocked",
                reason=mapped["code"],
                reason_text=mapped["text"],
                detail=blocked_reason,
                score=self._safe_float(bot.get("setup_quality_score"), None),
                mode=mode,
                direction=mode,
                source="runtime_entry_gate",
            )

        return self._build_runtime_setup_quality_result(
            bot,
            mode=mode,
            direction=mode,
        )

    def _evaluate_neutral_runtime(
        self,
        bot: Dict[str, Any],
        mode: str,
    ) -> Optional[Dict[str, Any]]:
        if not bot.get("entry_gate_enabled", True):
            return self._build_entry_gate_disabled_result(
                mode=mode,
                direction="neutral",
                detail="Neutral entry gate disabled for this bot",
            )

        gate_reason = str(bot.get("_gate_blocked_reason") or "").strip()
        if (
            bot.get("_nlp_block_opening_orders")
            and gate_reason
            and not gate_reason.startswith("BYPASSED:")
        ):
            mapped = self._map_reason_text(gate_reason)
            return self._build_result(
                status="blocked",
                reason=mapped["code"],
                reason_text=mapped["text"],
                detail=gate_reason,
                score=self._safe_float(bot.get("setup_quality_score"), None),
                mode=mode,
                direction="neutral",
                source="runtime_neutral_gate",
            )

        buy_skip = bool(bot.get("_entry_structure_skip_buy"))
        sell_skip = bool(bot.get("_entry_structure_skip_sell"))
        buy_reason = str(bot.get("_entry_structure_buy_reason") or "").strip()
        sell_reason = str(bot.get("_entry_structure_sell_reason") or "").strip()
        if buy_skip or sell_skip:
            if buy_skip and sell_skip:
                detail = "; ".join(
                    part for part in [buy_reason, sell_reason] if part
                ) or "Both neutral entry sides are blocked"
                return self._build_result(
                    status="blocked",
                    reason="no_trade_zone",
                    reason_text="No-trade zone",
                    detail=detail,
                    score=self._safe_float(bot.get("setup_quality_score"), None),
                    mode=mode,
                    direction="none",
                    source="runtime_structure_gate",
                )

            blocked_reason = buy_reason if buy_skip else sell_reason
            mapped = self._map_reason_text(blocked_reason)
            return self._build_result(
                status="watch",
                reason=mapped["code"],
                reason_text=mapped["text"],
                detail=blocked_reason or "Neutral entry is currently one-sided",
                score=self._safe_float(bot.get("setup_quality_score"), None),
                mode=mode,
                direction="short" if buy_skip else "long",
                source="runtime_structure_bias",
            )

        return self._build_runtime_setup_quality_result(
            bot,
            mode=mode,
            direction="neutral",
        )

    def _evaluate_scalp_runtime(
        self,
        bot: Dict[str, Any],
        mode: str,
    ) -> Optional[Dict[str, Any]]:
        if not bot.get("entry_gate_enabled", True):
            return self._build_result(
                status="watch",
                reason="entry_gate_disabled",
                reason_text="Gate disabled",
                detail="Scalp entry gate disabled for this bot",
                mode=mode,
                direction="none",
                source="entry_gate_disabled",
            )
        direction = str(bot.get("scalp_signal_direction") or "").strip().lower()
        if direction not in {"long", "short"}:
            direction = "none"
        return self._build_runtime_setup_quality_result(
            bot,
            mode=mode,
            direction=direction,
            ready_status="watch",
            ready_reason="preview_limited",
            ready_reason_text="Preview limited",
            ready_detail=(
                "Scalp readiness reuses runtime setup quality only"
            ),
            source="runtime_scalp_preview",
        )

    def _build_runtime_setup_quality_result(
        self,
        bot: Dict[str, Any],
        *,
        mode: str,
        direction: str,
        ready_status: str = "ready",
        ready_reason: str = "ready",
        ready_reason_text: str = "Enter now",
        ready_detail: str = "Runtime setup quality clear",
        source: str = "runtime_setup_quality",
    ) -> Optional[Dict[str, Any]]:
        enabled = bot.get("setup_quality_enabled")
        score = self._safe_float(bot.get("setup_quality_score"), None)
        band = str(bot.get("setup_quality_band") or "").strip().lower()
        summary = str(bot.get("setup_quality_summary") or "").strip()
        breakout_ready = bot.get("setup_quality_breakout_ready")

        if enabled is None and score is None and not band and breakout_ready is None and not summary:
            return None

        if band == "caution":
            return self._build_result(
                status="watch",
                reason="low_setup_quality",
                reason_text="Wait for stronger setup",
                detail=summary or "Setup is not clean enough yet; watch for stronger structure.",
                score=score,
                mode=mode,
                direction=direction or "none",
                source=source,
            )

        if breakout_ready is False:
            return self._attach_runtime_directional_analysis_context(
                self._build_result(
                    status="watch",
                    reason="waiting_for_confirmation",
                    reason_text="Wait for confirmation",
                    detail=summary or "Setup is close, but confirmation is still missing.",
                    score=score,
                    mode=mode,
                    direction=direction or "none",
                    source=source,
                ),
                bot=bot,
            )

        base_result = self._build_result(
            status=ready_status,
            reason=ready_reason,
            reason_text=(
                "Entry allowed now" if ready_reason == "ready" else ready_reason_text
            ),
            detail=summary
            or (
                "Entry conditions are executable right now."
                if ready_reason == "ready"
                else ready_detail
            ),
            score=score,
            mode=mode,
            direction=direction or "none",
            source=source,
        )
        if mode in self.DIRECTIONAL_MODES and ready_reason == "ready":
            base_result = self._decorate_directional_ready_result(
                base_result,
                signal=self._get_runtime_entry_signal(bot),
            )
        return self._attach_runtime_directional_analysis_context(
            base_result,
            bot=bot,
        )

    def _evaluate_directional(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mode: str,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._is_directional_entry_gate_active(bot):
            global_disabled = not getattr(cfg, "ENTRY_GATE_ENABLED", False)
            return self._build_entry_gate_disabled_result(
                mode=mode,
                direction=mode,
                detail=(
                    "Directional entry gate disabled globally"
                    if global_disabled
                    else "Directional entry gate disabled for this bot"
                ),
                global_disabled=global_disabled,
            )

        breakout_required = bool(
            getattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", False)
            and bool(bot.get("breakout_confirmed_entry", False))
        )
        cache_key = f"directional:{symbol}:{mode}:{int(breakout_required)}"
        cached = self._get_cached(self._cache, cache_key)
        if cached is not None:
            return cached

        indicators = self._get_indicator_snapshot(
            symbol=symbol,
            interval=cfg.ENTRY_GATE_TIMEFRAME,
            limit=100,
        )
        current_price = self._resolve_current_price(
            symbol=symbol,
            bot=bot,
            indicators=indicators,
            market_context=market_context,
        )
        gate_result = self.entry_gate_service.check_entry(
            symbol=symbol,
            mode=mode,
            indicators=indicators or None,
            bot={"breakout_confirmed_entry": breakout_required},
            current_price=current_price,
        )
        setup_quality = ((gate_result or {}).get("scores") or {}).get(
            "setup_quality",
            {},
        )
        score = self._safe_float((setup_quality or {}).get("score"), None)

        if not gate_result.get("suitable", True):
            reason = self._map_directional_block_reason(gate_result)
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="blocked",
                        reason=reason["code"],
                        reason_text=reason["text"],
                        detail=gate_result.get("reason") or reason["text"],
                        score=score,
                        mode=mode,
                        direction=mode,
                        source="entry_gate",
                    ),
                    market_context,
                ),
            )

        watch_reason = self._watch_reason_from_setup_quality(
            setup_quality,
            breakout_required=breakout_required,
        )
        if watch_reason is not None:
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._attach_setup_quality_context(
                        self._build_result(
                            status="watch",
                            reason=watch_reason["code"],
                            reason_text=watch_reason["text"],
                            detail=(setup_quality or {}).get("summary")
                            or "Waiting for stronger setup",
                            score=score,
                            mode=mode,
                            direction=mode,
                            source="setup_quality",
                        ),
                        setup_quality=setup_quality,
                    ),
                    market_context,
                ),
            )

        entry_signal = ((gate_result or {}).get("scores") or {}).get("entry_signal") or {}
        return self._set_cached(
            self._cache,
            cache_key,
            self._attach_market_data_context(
                self._attach_setup_quality_context(
                    self._decorate_directional_ready_result(
                        self._build_result(
                        status="ready",
                        reason="ready",
                        reason_text="Entry allowed now",
                        detail=gate_result.get("reason")
                        or "Entry conditions are executable right now.",
                        score=score,
                        mode=mode,
                        direction=mode,
                        source="entry_gate",
                        ),
                        signal=entry_signal,
                    ),
                    setup_quality=setup_quality,
                ),
                market_context,
            ),
        )

    def _evaluate_neutral(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mode: str,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entry_gate_enabled = bool(bot.get("entry_gate_enabled", True))
        preset = str(bot.get("neutral_preset") or "").strip().upper()
        cache_key = f"neutral:{symbol}:{mode}:{int(entry_gate_enabled)}:{preset}"
        cached = self._get_cached(self._cache, cache_key)
        if cached is not None:
            return cached

        indicators_15m = self._get_indicator_snapshot(symbol=symbol, interval="15", limit=100)
        indicators_1m = None
        if getattr(cfg, "NEUTRAL_GATE_1M_ENABLED", False):
            indicators_1m = self._get_indicator_snapshot(symbol=symbol, interval="1", limit=50)

        gate_result = {"suitable": True, "reason": "Neutral gate clear", "blocked_by": []}
        if self.neutral_suitability_service is not None:
            gate_result = self.neutral_suitability_service.check_suitability(
                symbol=symbol,
                preset=preset or None,
                indicators_15m=indicators_15m or None,
                indicators_1m=indicators_1m or None,
            )

        current_price = self._resolve_current_price(
            symbol=symbol,
            bot=bot,
            indicators=indicators_15m,
            market_context=market_context,
        )
        buy_result = self.entry_gate_service.check_side_open(
            symbol=symbol,
            side="Buy",
            current_price=current_price,
            indicators=indicators_15m or None,
        )
        sell_result = self.entry_gate_service.check_side_open(
            symbol=symbol,
            side="Sell",
            current_price=current_price,
            indicators=indicators_15m or None,
        )
        setup_quality = self.entry_gate_service.get_setup_quality(
            symbol=symbol,
            mode=mode,
            current_price=current_price,
            indicators=indicators_15m or None,
        )
        score = self._safe_float((setup_quality or {}).get("score"), None)

        if entry_gate_enabled and not gate_result.get("suitable", True):
            reason = self._map_neutral_gate_reason(gate_result)
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="blocked",
                        reason=reason["code"],
                        reason_text=reason["text"],
                        detail=gate_result.get("reason") or reason["text"],
                        score=score,
                        mode=mode,
                        direction="neutral",
                        source="neutral_gate",
                    ),
                    market_context,
                ),
            )

        buy_blocked = not buy_result.get("suitable", True)
        sell_blocked = not sell_result.get("suitable", True)
        if entry_gate_enabled and buy_blocked and sell_blocked:
            detail = "; ".join(
                part
                for part in [
                    f"Long: {buy_result.get('reason')}" if buy_result.get("reason") else "",
                    f"Short: {sell_result.get('reason')}" if sell_result.get("reason") else "",
                ]
                if part
            ) or "Both neutral entry sides are blocked"
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="blocked",
                        reason="no_trade_zone",
                        reason_text="No-trade zone",
                        detail=detail,
                        score=score,
                        mode=mode,
                        direction="none",
                        source="structure_gate",
                    ),
                    market_context,
                ),
            )

        if entry_gate_enabled and buy_blocked != sell_blocked:
            blocked_result = buy_result if buy_blocked else sell_result
            reason = self._map_side_gate_reason(blocked_result)
            direction = "short" if buy_blocked else "long"
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="watch",
                        reason=reason["code"],
                        reason_text=reason["text"],
                        detail=blocked_result.get("reason") or reason["text"],
                        score=score,
                        mode=mode,
                        direction=direction,
                        source="structure_bias",
                    ),
                    market_context,
                ),
            )

        watch_reason = self._watch_reason_from_setup_quality(
            setup_quality,
            breakout_required=False,
        )
        if watch_reason is not None:
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="watch",
                        reason=watch_reason["code"],
                        reason_text=watch_reason["text"],
                        detail=(setup_quality or {}).get("summary") or "Neutral setup needs stronger structure",
                        score=score,
                        mode=mode,
                        direction="neutral",
                        source="setup_quality",
                    ),
                    market_context,
                ),
            )

        detail = "Neutral structure clear"
        if not entry_gate_enabled:
            detail = "Neutral entry gate disabled for this bot"
        return self._set_cached(
            self._cache,
            cache_key,
            self._attach_market_data_context(
                (
                    self._build_entry_gate_disabled_result(
                        mode=mode,
                        direction="neutral",
                        detail=detail,
                    )
                    if not entry_gate_enabled
                    else self._build_result(
                        status="ready",
                        reason="ready",
                        reason_text="Enter now",
                        detail=detail,
                        score=score,
                        mode=mode,
                        direction="neutral",
                        source="neutral_gate",
                    )
                ),
                market_context,
            ),
        )

    def _evaluate_scalp(
        self,
        bot: Dict[str, Any],
        symbol: str,
        mode: str,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not bot.get("entry_gate_enabled", True):
            return self._build_entry_gate_disabled_result(
                mode=mode,
                direction="none",
                detail="Scalp entry gate disabled for this bot",
            )
        cache_key = f"scalp:{symbol}:{mode}"
        cached = self._get_cached(self._cache, cache_key)
        if cached is not None:
            return cached

        indicators = self._get_indicator_snapshot(
            symbol=symbol,
            interval=cfg.ENTRY_GATE_TIMEFRAME,
            limit=100,
        )
        current_price = self._resolve_current_price(
            symbol=symbol,
            bot=bot,
            indicators=indicators,
            market_context=market_context,
        )
        setup_quality = self.entry_gate_service.get_setup_quality(
            symbol=symbol,
            mode=mode,
            current_price=current_price,
            indicators=indicators or None,
        )
        score = self._safe_float((setup_quality or {}).get("score"), None)
        direction = str(
            bot.get("scalp_signal_direction")
            or ((setup_quality or {}).get("components") or {})
            .get("price_action_context", {})
            .get("direction")
            or "none"
        ).strip().lower()
        if direction not in {"long", "short", "buy", "sell", "bullish", "bearish"}:
            direction = "none"
        elif direction in {"buy", "bullish"}:
            direction = "long"
        elif direction in {"sell", "bearish"}:
            direction = "short"

        watch_reason = self._watch_reason_from_setup_quality(
            setup_quality,
            breakout_required=False,
        )
        if watch_reason is not None:
            return self._set_cached(
                self._cache,
                cache_key,
                self._attach_market_data_context(
                    self._build_result(
                        status="watch",
                        reason=watch_reason["code"],
                        reason_text=watch_reason["text"],
                        detail=(setup_quality or {}).get("summary") or "Scalp setup still building",
                        score=score,
                        mode=mode,
                        direction=direction,
                        source="setup_quality",
                    ),
                    market_context,
                ),
            )

        return self._set_cached(
            self._cache,
            cache_key,
            self._attach_market_data_context(
                self._build_result(
                    status="watch",
                    reason="preview_limited",
                    reason_text="Preview limited",
                    detail="Scalp readiness preview is limited to setup quality and structure context",
                    score=score,
                    mode=mode,
                    direction=direction,
                    source="preview_limited",
                ),
                market_context,
            ),
        )

    def _overlay_low_budget_watch(
        self,
        bot: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        state = str(bot.get("auto_pilot_loss_budget_state") or "").strip().lower()
        if state != "low" or str(result.get("entry_ready_status") or "").strip().lower() == "blocked":
            return result
        if not bool(bot.get("auto_pilot", False)):
            return result
        return self._build_result(
            status="watch",
            reason="loss_budget_low",
            reason_text="Loss budget low",
            detail=self._format_loss_budget_detail(bot),
            score=self._safe_float(result.get("entry_ready_score"), None),
            mode=result.get("entry_ready_mode"),
            direction=result.get("entry_ready_direction") or "none",
            source="runtime_loss_budget",
        )

    def _overlay_runtime_execution_blocker(
        self,
        bot: Dict[str, Any],
        result: Dict[str, Any],
        *,
        mode: str,
    ) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return result
        if str(result.get("entry_ready_status") or "").strip().lower() == "blocked":
            return result
        blocker = self._get_runtime_opening_blocker(bot, mode=mode)
        if blocker is None:
            return result
        if not bool(blocker.get("overlay_entry_block", True)):
            return result
        detail_prefix = blocker["detail"]
        existing_detail = str(result.get("entry_ready_detail") or "").strip()
        if existing_detail:
            detail_prefix = f"{detail_prefix} Setup snapshot: {existing_detail}"
        payload = self._build_result(
            status="blocked",
            reason=blocker["reason"],
            reason_text=blocker["reason_text"],
            detail=detail_prefix,
            score=self._safe_float(result.get("entry_ready_score"), None),
            mode=result.get("entry_ready_mode"),
            direction=result.get("entry_ready_direction") or "none",
            source=blocker["source"],
        )
        return self._copy_analysis_context(result, payload)

    @staticmethod
    def _build_stale_inactive_runtime_blocker(
        *,
        label: str,
        detail: str,
        source: str,
    ) -> Dict[str, Any]:
        stale_detail = (
            f"Saved {label} is stale for this inactive bot, so it is not treated "
            "as a live opening blocker."
        )
        if detail:
            stale_detail = f"{stale_detail} Last saved state: {detail}"
        return {
            "reason": "stale_runtime_blocker",
            "reason_text": "Saved blocker stale",
            "detail": stale_detail,
            "source": source,
            "overlay_entry_block": False,
            "execution_blocked": False,
            "execution_status": "viable",
            "execution_reason": "openings_clear",
            "execution_reason_text": "Opening clear",
            "execution_bucket": "viable",
            "execution_margin_limited": False,
            "diagnostic_reason": "stale_runtime_blocker",
            "diagnostic_reason_text": "Saved blocker stale",
            "diagnostic_detail": stale_detail,
            "stale_data": True,
        }

    @staticmethod
    def _get_exchange_truth_runtime_blocker(
        bot: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(bot, dict):
            return None
        reconcile = dict(bot.get("exchange_reconciliation") or {})
        reconcile_status = str(reconcile.get("status") or "").strip().lower()
        mismatches = [
            str(item or "").strip().lower()
            for item in list(reconcile.get("mismatches") or [])
            if str(item or "").strip()
        ]
        if reconcile_status in {
            "diverged",
            "error_with_exchange_persist_divergence",
        } or mismatches:
            mismatch_label = ", ".join(mismatches[:3]) if mismatches else None
            detail = (
                "Exchange reconciliation detected divergence between exchange truth "
                "and local bot assumptions, so new opening orders stay blocked until "
                "truth is re-established."
            )
            if mismatch_label:
                detail = f"{detail} Detected mismatch: {mismatch_label}."
            return {
                "reason": "reconciliation_diverged",
                "reason_text": "Reconciliation diverged",
                "detail": detail,
                "source": "exchange_reconciliation",
                "overlay_entry_block": False,
                "execution_blocked": True,
                "execution_status": "blocked",
                "execution_reason": "reconciliation_diverged",
                "execution_reason_text": "Reconciliation diverged",
                "execution_bucket": "state_untrusted",
                "execution_margin_limited": False,
                "diagnostic_reason": "reconciliation_diverged",
                "diagnostic_reason_text": "Reconciliation diverged",
                "diagnostic_detail": detail,
                "stale_data": False,
            }

        stale_parts = []
        if bool(bot.get("position_assumption_stale")):
            stale_parts.append("position assumptions")
        if bool(bot.get("order_assumption_stale")):
            stale_parts.append("open-order assumptions")
        if stale_parts:
            detail = (
                "Local exchange assumptions are stale, so new opening orders stay "
                "blocked until exchange truth is rechecked."
            )
            detail = f"{detail} Stale assumptions: {', '.join(stale_parts)}."
            return {
                "reason": "exchange_truth_stale",
                "reason_text": "Exchange truth stale",
                "detail": detail,
                "source": "exchange_reconciliation",
                "overlay_entry_block": False,
                "execution_blocked": True,
                "execution_status": "blocked",
                "execution_reason": "exchange_truth_stale",
                "execution_reason_text": "Exchange truth stale",
                "execution_bucket": "state_untrusted",
                "execution_margin_limited": False,
                "diagnostic_reason": "exchange_truth_stale",
                "diagnostic_reason_text": "Exchange truth stale",
                "diagnostic_detail": detail,
                "stale_data": False,
            }

        marker = dict(bot.get("ambiguous_execution_follow_up") or {})
        marker_status = str(marker.get("status") or "").strip().lower()
        if bool(marker.get("pending")) or marker_status == "still_unresolved" or bool(
            marker.get("truth_check_expired")
        ):
            detail = (
                "A previous exchange action still has an unresolved truth check, so "
                "new opening orders stay blocked until the exchange outcome is clear."
            )
            action = str(marker.get("action") or "").strip().lower()
            reason = str(
                marker.get("exchange_effect_reason")
                or marker.get("reason")
                or marker.get("diagnostic_reason")
                or ""
            ).strip().lower()
            context = ", ".join(
                item
                for item in (action, reason or marker_status or None)
                if item
            )
            if context:
                detail = f"{detail} Pending context: {context}."
            return {
                "reason": "exchange_state_untrusted",
                "reason_text": "Exchange state untrusted",
                "detail": detail,
                "source": "ambiguous_execution_follow_up",
                "overlay_entry_block": False,
                "execution_blocked": True,
                "execution_status": "blocked",
                "execution_reason": "exchange_state_untrusted",
                "execution_reason_text": "Exchange state untrusted",
                "execution_bucket": "state_untrusted",
                "execution_margin_limited": False,
                "diagnostic_reason": "exchange_state_untrusted",
                "diagnostic_reason_text": "Exchange state untrusted",
                "diagnostic_detail": detail,
                "stale_data": False,
            }
        return None

    def _get_runtime_opening_blocker(
        self,
        bot: Dict[str, Any],
        *,
        mode: str,
    ) -> Optional[Dict[str, str]]:
        if not bot:
            return None
        status = str(bot.get("status") or "").strip().lower()
        inactive_status = bool(status) and status not in self.RUNTIME_ACTIVE_STATUSES
        exchange_truth_blocker = self._get_exchange_truth_runtime_blocker(bot)
        if exchange_truth_blocker is not None:
            return exchange_truth_blocker
        blocked_budget = bool(
            bot.get("_auto_pilot_loss_budget_block_openings")
            or bot.get("auto_pilot_opening_blocked_by_loss_budget")
            or str(bot.get("auto_pilot_loss_budget_state") or "").strip().lower()
            == "blocked"
        )
        if blocked_budget:
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="loss-budget block",
                    detail=self._format_loss_budget_detail(bot),
                    source="runtime_loss_budget_stale",
                )
            return {
                "reason": "loss_budget_blocked",
                "reason_text": "Loss budget blocked",
                "detail": self._format_loss_budget_detail(bot),
                "source": "runtime_loss_budget",
            }
        if bot.get("_capital_starved_block_opening_orders"):
            reason = str(bot.get("capital_starved_reason") or "").strip().lower()
            warning_text = str(bot.get("_capital_starved_warning_text") or "").strip()
            summary = bot.get("watchdog_bottleneck_summary")
            summary_active = None
            if isinstance(summary, dict) and "capital_starved_active" in summary:
                summary_active = bool(summary.get("capital_starved_active"))
            detail_metrics = self._capital_starved_execution_metrics(bot)
            if (
                summary_active is False
                and status
                and status not in self.RUNTIME_ACTIVE_STATUSES
            ):
                stale_detail = (
                    "Saved capital check is stale for this stopped bot, so it is not "
                    "treated as a live opening blocker."
                )
                if warning_text:
                    stale_detail = f"{stale_detail} Last saved check: {warning_text}"
                return {
                    "reason": "stale_balance",
                    "reason_text": "Stale balance",
                    "detail": stale_detail,
                    "source": "runtime_margin_guard_stale",
                    "overlay_entry_block": False,
                    "execution_blocked": False,
                    "execution_status": "viable",
                    "execution_reason": "openings_clear",
                    "execution_reason_text": "Opening clear",
                    "execution_bucket": "viable",
                    "execution_margin_limited": False,
                    "diagnostic_reason": "stale_balance",
                    "diagnostic_reason_text": "Stale balance",
                    "diagnostic_detail": stale_detail,
                    "stale_data": True,
                    **detail_metrics,
                }
            if reason == "qty_below_min":
                return {
                    "reason": "qty_below_min",
                    "reason_text": "Min qty too high",
                    "detail": warning_text
                    or "Bot size compresses below the exchange minimum quantity, so a new entry cannot be placed right now.",
                    "source": "runtime_qty_floor",
                    "execution_bucket": "size_limited",
                    "execution_margin_limited": False,
                    "diagnostic_reason": "qty_below_min",
                    "diagnostic_reason_text": "Min qty too high",
                    **detail_metrics,
                }
            if reason == "notional_below_min":
                return {
                    "reason": "notional_below_min",
                    "reason_text": "Budget below first order",
                    "detail": warning_text
                    or "Bot budget compresses below the exchange minimum notional for the first opening order.",
                    "source": "runtime_notional_floor",
                    "execution_bucket": "size_limited",
                    "execution_margin_limited": False,
                    "diagnostic_reason": "notional_below_min",
                    "diagnostic_reason_text": "Budget below first order",
                    **detail_metrics,
                }
            if reason == "opening_margin_reserve":
                return {
                    "reason": "opening_margin_reserve",
                    "reason_text": "Reserve limited",
                    "detail": warning_text
                    or "A new entry is deferred because the opening reserve is keeping funds free for margin safety.",
                    "source": "runtime_opening_margin_reserve",
                    "execution_bucket": "margin_limited",
                    "execution_margin_limited": True,
                    "diagnostic_reason": "opening_margin_reserve",
                    "diagnostic_reason_text": "Reserve limited",
                    **detail_metrics,
                }
            return {
                "reason": "insufficient_margin",
                "reason_text": "Insufficient margin",
                "detail": warning_text
                or "A new entry is blocked because available opening margin is below the required amount.",
                "source": "runtime_margin_guard",
                "execution_bucket": "margin_limited",
                "execution_margin_limited": True,
                "diagnostic_reason": "insufficient_free_margin",
                "diagnostic_reason_text": "Margin low",
                **detail_metrics,
            }
        if bot.get("_small_capital_block_opening_orders"):
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="minimum-quantity blocker",
                    detail=(
                        "Bot size was previously compressed below exchange minimum "
                        "order size requirements."
                    ),
                    source="runtime_small_capital_stale",
                )
            return {
                "reason": "qty_below_min",
                "reason_text": "Min qty too high",
                "detail": "Bot size currently compresses below exchange minimums, so a fresh entry is not executable.",
                "source": "runtime_small_capital",
                "execution_bucket": "size_limited",
                "execution_margin_limited": False,
                "diagnostic_reason": "qty_below_min",
                "diagnostic_reason_text": "Min qty too high",
            }
        if (
            mode in self.DIRECTIONAL_MODES
            and bool(bot.get("_watchdog_position_cap_active"))
        ):
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="position-cap blocker",
                    detail="Opening exposure was previously capped for this bot.",
                    source="runtime_position_cap_stale",
                )
            return {
                "reason": "position_cap_hit",
                "reason_text": "Position cap hit",
                "detail": "Directional setup may be valid, but opening exposure is already capped for this bot.",
                "source": "runtime_position_cap",
            }
        if bool(bot.get("_breakout_invalidation_block_opening_orders")):
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="breakout invalidation guard",
                    detail=str(bot.get("breakout_invalidation_reason") or "").strip(),
                    source="runtime_breakout_invalidation_stale",
                )
            return {
                "reason": "breakout_invalidated",
                "reason_text": "Breakout invalidated",
                "detail": str(bot.get("breakout_invalidation_reason") or "").strip()
                or "New opening orders stay blocked while the breakout invalidation guard is active.",
                "source": "runtime_breakout_invalidation",
            }
        if bool(bot.get("_session_timer_block_opening_orders")):
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="session-timer block",
                    detail="New opening orders were previously blocked by the session timer window.",
                    source="runtime_session_timer_stale",
                )
            return {
                "reason": "session_blocked",
                "reason_text": "Session blocked",
                "detail": "New opening orders are currently blocked by the session timer window.",
                "source": "runtime_session_timer",
            }
        if bool(bot.get("_stall_overlay_block_opening_orders")):
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="stall-overlay guard",
                    detail="New opening orders were previously blocked by the stall overlay guard.",
                    source="runtime_stall_overlay_stale",
                )
            return {
                "reason": "stall_blocked",
                "reason_text": "Stall blocked",
                "detail": "New opening orders are temporarily blocked by the stall overlay guard.",
                "source": "runtime_stall_overlay",
            }
        if bool(bot.get("_block_opening_orders")):
            if inactive_status:
                return self._build_stale_inactive_runtime_blocker(
                    label="opening-order block",
                    detail="A saved runtime guard previously blocked new opening orders.",
                    source="runtime_opening_block_stale",
                )
            return {
                "reason": "opening_blocked",
                "reason_text": "Opening blocked",
                "detail": "New opening orders are currently blocked by a runtime safety guard.",
                "source": "runtime_opening_block",
            }
        return None

    def _capital_starved_execution_metrics(
        self,
        bot: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "available_margin_usdt": self._safe_float(
                bot.get("capital_starved_available_opening_margin_usdt"),
                None,
            ),
            "required_margin_usdt": self._safe_float(
                bot.get("capital_starved_required_margin_usdt"),
                None,
            ),
            "order_notional_usdt": self._safe_float(
                bot.get("capital_starved_order_notional_usdt"),
                None,
            ),
        }

    @staticmethod
    def _copy_analysis_context(
        source: Dict[str, Any],
        target: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = dict(target or {})
        for key in (
            "_analysis_band",
            "_analysis_summary",
            "_analysis_mode_fit_score",
            "_analysis_price_action_direction",
            "_analysis_entry_signal",
            "_analysis_fallback_used",
            "_analysis_fallback_reason",
            "_analysis_fallback_source",
        ):
            if key in source:
                payload[key] = source.get(key)
        return payload

    @staticmethod
    def _format_loss_budget_detail(bot: Dict[str, Any]) -> str:
        remaining_pct = EntryReadinessService._safe_float(
            bot.get("auto_pilot_remaining_loss_budget_pct"),
            None,
        )
        remaining_usdt = EntryReadinessService._safe_float(
            bot.get("auto_pilot_remaining_loss_budget_usdt"),
            None,
        )
        loss_budget_usdt = EntryReadinessService._safe_float(
            bot.get("auto_pilot_loss_budget_usdt"),
            None,
        )
        if remaining_pct is None and remaining_usdt is None and loss_budget_usdt is None:
            return "Remaining Auto-Pilot loss budget blocks new openings"
        parts = []
        if remaining_pct is not None:
            parts.append(f"remaining {remaining_pct * 100.0:.2f}%")
        if remaining_usdt is not None and loss_budget_usdt is not None:
            parts.append(f"(${remaining_usdt:.2f} / ${loss_budget_usdt:.2f})")
        return "Auto-Pilot loss budget " + " ".join(parts).strip()

    def _build_entry_gate_disabled_result(
        self,
        *,
        mode: Optional[str],
        direction: str,
        detail: str,
        global_disabled: bool = False,
    ) -> Dict[str, Any]:
        return self._build_result(
            status="watch",
            reason="entry_gate_disabled",
            reason_text="Gate off globally" if global_disabled else "Gate off for this bot",
            detail=f"{detail}. Live trading will ignore entry-gate checks until it is enabled.",
            mode=mode,
            direction=direction,
            source=(
                "entry_gate_disabled_global"
                if global_disabled
                else "entry_gate_disabled_bot"
            ),
        )

    @staticmethod
    def _is_directional_entry_gate_active(bot: Dict[str, Any]) -> bool:
        return bool(
            getattr(cfg, "ENTRY_GATE_ENABLED", False)
            and bool(bot.get("entry_gate_enabled", True))
        )

    def _resolve_current_price(
        self,
        *,
        symbol: str,
        bot: Dict[str, Any],
        indicators: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[float]:
        bot_snapshot = self._get_bot_price_snapshot(bot)
        market_snapshot = self._get_market_price_snapshot(symbol)
        selected_snapshot = None
        refresh_reason = None
        status = str(bot.get("status") or "").strip().lower()

        if (
            status in self.RUNTIME_ACTIVE_STATUSES
            and self._should_prefer_market_snapshot(
                bot_snapshot=bot_snapshot,
                market_snapshot=market_snapshot,
            )
        ):
            selected_snapshot = market_snapshot
            refresh_reason = self._market_snapshot_refresh_reason(
                bot_snapshot=bot_snapshot,
                market_snapshot=market_snapshot,
            )
        elif isinstance(bot_snapshot, dict):
            selected_snapshot = bot_snapshot
        elif isinstance(market_snapshot, dict):
            selected_snapshot = market_snapshot
            refresh_reason = "bot_price_missing"

        if isinstance(selected_snapshot, dict):
            self._record_market_snapshot_diagnostics(
                market_context,
                bot_snapshot=bot_snapshot,
                market_snapshot=market_snapshot,
                selected_snapshot=selected_snapshot,
                refresh_reason=refresh_reason,
            )
            selected_price = EntryReadinessService._safe_float(
                selected_snapshot.get("price"),
                None,
            )
            if selected_price is not None and selected_price > 0:
                return selected_price

        indicator_price = EntryReadinessService._safe_float(
            (indicators or {}).get("close"),
            None,
        )
        if indicator_price is not None and indicator_price > 0:
            self._record_market_data_context(
                market_context,
                source="indicator_close",
                transport=(indicators or {}).get("_indicator_transport") or "indicator_snapshot",
                price=indicator_price,
                timestamp=self._parse_timestamp(
                    (indicators or {}).get("_indicator_close_ts")
                    or (indicators or {}).get("_indicator_last_open_ts")
                ),
                timestamp_source="indicator_last_candle",
            )
            return indicator_price
        return None

    def _get_bot_price_snapshot(self, bot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        bot_price = EntryReadinessService._safe_float(bot.get("current_price"), None)
        if bot_price is None or bot_price <= 0:
            return None
        bot_ts = None
        bot_ts_source = None
        for key in (
            "current_price_updated_at",
            "mark_price_updated_at",
            "last_price_updated_at",
            "price_updated_at",
        ):
            bot_ts = self._parse_timestamp(bot.get(key))
            if bot_ts is not None:
                bot_ts_source = key
                break
        return {
            "price": bot_price,
            "received_at": bot_ts,
            "timestamp_source": bot_ts_source,
            "exchange_ts": self._parse_timestamp(
                bot.get("current_price_exchange_ts")
                or bot.get("current_price_exchange_at")
            ),
            "source": str(bot.get("current_price_source") or "bot_current_price"),
            "transport": str(bot.get("current_price_transport") or "runtime_bot"),
        }

    @classmethod
    def _snapshot_timestamp(cls, snapshot: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(snapshot, dict):
            return None
        for key in ("received_at", "timestamp", "ts"):
            value = cls._parse_timestamp(snapshot.get(key))
            if value is not None:
                return value
        return None

    def _should_prefer_market_snapshot(
        self,
        *,
        bot_snapshot: Optional[Dict[str, Any]],
        market_snapshot: Optional[Dict[str, Any]],
    ) -> bool:
        if not isinstance(market_snapshot, dict):
            return False
        market_ts = self._snapshot_timestamp(market_snapshot)
        if market_ts is None:
            return False
        if not isinstance(bot_snapshot, dict):
            return True
        bot_ts = self._snapshot_timestamp(bot_snapshot)
        if bot_ts is None:
            return True
        return market_ts > (bot_ts + 0.001)

    def _market_snapshot_refresh_reason(
        self,
        *,
        bot_snapshot: Optional[Dict[str, Any]],
        market_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        if not isinstance(market_snapshot, dict):
            return "provider_unavailable"
        if not isinstance(bot_snapshot, dict):
            return "bot_price_missing"
        if self._snapshot_timestamp(bot_snapshot) is None:
            return "bot_timestamp_missing"
        return "provider_newer_than_bot"

    def _record_market_snapshot_diagnostics(
        self,
        context: Optional[Dict[str, Any]],
        *,
        bot_snapshot: Optional[Dict[str, Any]],
        market_snapshot: Optional[Dict[str, Any]],
        selected_snapshot: Optional[Dict[str, Any]],
        refresh_reason: Optional[str],
    ) -> None:
        selected = (
            dict(selected_snapshot or {})
            if isinstance(selected_snapshot, dict)
            else {}
        )
        self._record_market_data_context(
            context,
            source=str(selected.get("source") or "unknown"),
            transport=selected.get("transport"),
            price=self._safe_float(selected.get("price"), None),
            timestamp=self._snapshot_timestamp(selected),
            timestamp_source=selected.get("timestamp_source"),
            exchange_ts=self._parse_timestamp(selected.get("exchange_ts")),
        )
        if context is None:
            return
        bot_ts = self._snapshot_timestamp(bot_snapshot)
        provider_ts = self._snapshot_timestamp(market_snapshot)
        if bot_ts is not None:
            context["bot_current_price_ts"] = float(bot_ts)
            context["bot_current_price_at"] = self._iso_from_ts(bot_ts)
            context["bot_current_price_source"] = str(
                (bot_snapshot or {}).get("source") or "bot_current_price"
            )
        if provider_ts is not None:
            context["market_provider_ts"] = float(provider_ts)
            context["market_provider_at"] = self._iso_from_ts(provider_ts)
            context["market_provider_source"] = str(
                (market_snapshot or {}).get("source") or "market_data_provider"
            )
            context["market_provider_transport"] = str(
                (market_snapshot or {}).get("transport") or "market_data_provider"
            )
            exchange_ts = self._parse_timestamp((market_snapshot or {}).get("exchange_ts"))
            if exchange_ts is not None:
                context["market_provider_exchange_ts"] = float(exchange_ts)
                context["market_provider_exchange_at"] = self._iso_from_ts(exchange_ts)
        context["market_data_refreshed_just_in_time"] = bool(refresh_reason)
        if refresh_reason:
            context["market_data_refresh_reason"] = str(refresh_reason)
        if bot_ts is not None and provider_ts is not None:
            context["market_data_refresh_delta_ms"] = round(
                (provider_ts - bot_ts) * 1000.0,
                2,
            )

    def _get_market_price_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        provider = getattr(self, "market_data_provider", None)
        normalized_symbol = str(symbol or "").strip().upper()
        if provider is None or not normalized_symbol:
            return None
        try:
            if callable(provider):
                value = provider(normalized_symbol)
                price = self._safe_float(value, None)
                if price and price > 0:
                    return {
                        "price": price,
                        "source": "market_data_provider",
                        "transport": "callable",
                    }
                return None
            if hasattr(provider, "get_last_price_metadata"):
                metadata = provider.get_last_price_metadata(normalized_symbol)
                if isinstance(metadata, dict):
                    return metadata
            if hasattr(provider, "get_ticker_rows"):
                rows = provider.get_ticker_rows([normalized_symbol])
                if isinstance(rows, dict):
                    row = dict(rows.get(normalized_symbol) or {})
                    price = self._safe_float(row.get("lastPrice"), None)
                    if price is None or price <= 0:
                        bid = self._safe_float(row.get("bid1Price"), None)
                        ask = self._safe_float(row.get("ask1Price"), None)
                        if bid and ask:
                            price = (bid + ask) / 2.0
                        else:
                            price = bid or ask
                    if price and price > 0:
                        return {
                            "price": price,
                            "received_at": row.get("_received_at"),
                            "exchange_ts": row.get("ts") or row.get("time"),
                            "source": "ticker_rows",
                            "transport": "stream_ticker",
                        }
            if hasattr(provider, "get_last_price"):
                value = provider.get_last_price(normalized_symbol)
                price = self._safe_float(value, None)
                if price and price > 0:
                    return {
                        "price": price,
                        "source": "get_last_price",
                        "transport": "market_data_provider",
                    }
        except Exception:
            return None
        return None

    def _check_fast_trigger(
        self,
        symbol: str,
        direction: str,
        score_15m: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Check 5m indicators for early momentum alignment.
        Can promote watch → armed when 5m momentum supports the direction
        and the 15m quality score meets the minimum threshold.
        Returns a dict with promotion info, or None if no promotion.
        """
        if not getattr(cfg, "ENTRY_GATE_FAST_TIMEFRAME_ENABLED", False):
            return None
        # Require score above caution band (60+), not just minimum (50)
        min_score = self._safe_float(
            getattr(cfg, "SETUP_QUALITY_CAUTION_SCORE", 60.0), 60.0
        )
        if score_15m is None or score_15m < min_score:
            return None
        fast_tf = getattr(cfg, "ENTRY_GATE_FAST_TIMEFRAME", "5")
        fast_limit = int(getattr(cfg, "ENTRY_GATE_FAST_CANDLE_LIMIT", 300))
        indicators_5m = self._get_indicator_snapshot(
            symbol=symbol,
            interval=fast_tf,
            limit=fast_limit,
        )
        if not indicators_5m:
            return None
        ema9 = self._safe_float(indicators_5m.get("ema_9"), None)
        ema21 = self._safe_float(indicators_5m.get("ema_21"), None)
        rsi = self._safe_float(indicators_5m.get("rsi"), None)
        velocity = self._safe_float(indicators_5m.get("price_velocity"), None)
        if ema9 is None or ema21 is None or rsi is None or velocity is None:
            return None
        # Require meaningful EMA gap (not just barely crossed) and velocity
        ema_gap_pct = abs(ema9 - ema21) / max(ema21, 1e-9)
        min_ema_gap = 0.001  # 0.1% gap minimum
        min_velocity = 0.003  # 0.3%/hr minimum
        if direction == "long":
            ema_aligned = ema9 > ema21 and ema_gap_pct >= min_ema_gap
            vel_aligned = velocity >= min_velocity
            rsi_ok = 35 < rsi < 70
        elif direction == "short":
            ema_aligned = ema9 < ema21 and ema_gap_pct >= min_ema_gap
            vel_aligned = velocity <= -min_velocity
            rsi_ok = 30 < rsi < 65
        else:
            return None
        if ema_aligned and vel_aligned and rsi_ok:
            return {
                "promoted": True,
                "reason": "fast_5m_momentum",
                "detail": f"5m EMA cross + velocity aligned ({fast_tf}m trigger)",
                "ema9": ema9,
                "ema21": ema21,
                "rsi": rsi,
                "velocity": velocity,
            }
        return None

    def _get_indicator_snapshot(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> Dict[str, Any]:
        cache_key = f"{symbol}:{interval}:{limit}"
        cached = self._get_cached(self._indicator_cache, cache_key)
        if cached is not None:
            return cached
        if self.indicator_service is None:
            return {}
        try:
            indicators = self.indicator_service.compute_indicators(
                symbol,
                interval=interval,
                limit=limit,
            ) or {}
        except Exception:
            indicators = {}
        if isinstance(indicators, dict) and hasattr(self.indicator_service, "get_ohlcv"):
            try:
                candles = self.indicator_service.get_ohlcv(symbol, interval=interval, limit=1)
            except Exception:
                candles = []
            if candles:
                last_candle = dict(candles[-1] or {})
                open_time = last_candle.get("open_time")
                open_ts = (
                    open_time.timestamp()
                    if isinstance(open_time, datetime)
                    else self._parse_timestamp(open_time)
                )
                if open_ts is not None and open_ts > 0:
                    indicators["_indicator_last_open_ts"] = open_ts
                    indicators["_indicator_last_open_at"] = self._iso_from_ts(open_ts)
                    interval_sec = max(int(self._safe_float(interval, 0.0) or 0), 1) * 60
                    indicators["_indicator_close_ts"] = open_ts + interval_sec
                    indicators["_indicator_close_at"] = self._iso_from_ts(
                        open_ts + interval_sec
                    )
                    indicators["_indicator_transport"] = "indicator_ohlcv"
        return self._set_cached(self._indicator_cache, cache_key, indicators)

    def _build_result(
        self,
        *,
        status: str,
        reason: str,
        reason_text: str,
        detail: str,
        mode: Optional[str],
        direction: str,
        source: str,
        score: Optional[float] = None,
    ) -> Dict[str, Any]:
        return {
            "entry_ready_status": status,
            "entry_ready_reason": reason,
            "entry_ready_reason_text": reason_text,
            "entry_ready_detail": detail,
            "entry_ready_score": round(score, 2) if score is not None else None,
            "entry_ready_direction": direction or "none",
            "entry_ready_mode": mode or "none",
            "entry_ready_updated_at": datetime.now(timezone.utc).isoformat(),
            "entry_ready_source": source,
        }

    def _decorate_directional_ready_result(
        self,
        result: Dict[str, Any],
        *,
        signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = dict(result or {})
        signal_payload = dict(signal or {})
        label = str(signal_payload.get("label") or "").strip()
        detail = str(signal_payload.get("detail") or "").strip()
        code = str(signal_payload.get("code") or "").strip().lower()
        phase = str(signal_payload.get("phase") or "").strip().lower() or None
        if label:
            payload["entry_ready_reason"] = code or payload.get("entry_ready_reason")
            payload["entry_ready_reason_text"] = label
        if detail:
            payload["entry_ready_detail"] = detail
        payload["_analysis_entry_signal"] = {
            "code": code or None,
            "label": label or None,
            "detail": detail or None,
            "phase": phase,
            "preferred": bool(signal_payload.get("preferred", False)),
            "late": bool(signal_payload.get("late", False)),
            "executable": bool(signal_payload.get("executable", False)),
            "experiment_tags": list(signal_payload.get("experiment_tags") or []),
            "experiment_details": dict(signal_payload.get("experiment_details") or {}),
        }
        if payload["_analysis_entry_signal"]["experiment_tags"]:
            payload["entry_ready_experiment_tags"] = list(
                payload["_analysis_entry_signal"]["experiment_tags"]
            )
        return payload

    def _get_runtime_entry_signal(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "code": bot.get("entry_signal_code"),
            "label": bot.get("entry_signal_label"),
            "phase": bot.get("entry_signal_phase"),
            "detail": bot.get("entry_signal_detail"),
            "preferred": bool(bot.get("entry_signal_preferred", False)),
            "late": bool(bot.get("entry_signal_late", False)),
            "executable": bool(bot.get("entry_signal_executable", False)),
            "experiment_tags": list(bot.get("entry_signal_experiment_tags") or []),
            "experiment_details": dict(
                bot.get("entry_signal_experiment_details") or {}
            ),
        }

    def _should_use_fresh_active_directional_analysis(
        self,
        bot: Dict[str, Any],
        *,
        mode: str,
        runtime_result: Dict[str, Any],
    ) -> bool:
        if mode not in self.DIRECTIONAL_MODES:
            return False
        if self.entry_gate_service is None:
            return False
        source = str(runtime_result.get("entry_ready_source") or "").strip().lower()
        if source != "runtime_setup_quality":
            return False
        status = str(runtime_result.get("entry_ready_status") or "").strip().lower()
        if status != "ready":
            return False

        enabled = bot.get("setup_quality_enabled")
        score = self._safe_float(bot.get("setup_quality_score"), None)
        band = str(bot.get("setup_quality_band") or "").strip().lower()
        summary = str(bot.get("setup_quality_summary") or "").strip()
        breakout_ready = bot.get("setup_quality_breakout_ready")
        signal = self._get_runtime_entry_signal(bot)
        signal_code = str(signal.get("code") or "").strip().lower()
        signal_label = str(signal.get("label") or "").strip()
        signal_detail = str(signal.get("detail") or "").strip()

        runtime_cleared = (
            enabled is False
            and score is None
            and not band
            and breakout_ready is None
            and not summary
            and not signal_code
            and not signal_label
            and not signal_detail
        )
        runtime_incomplete = (
            score is None
            and not band
            and breakout_ready is None
            and not summary
            and not signal_code
        )
        return runtime_cleared or runtime_incomplete

    def _mark_analysis_fallback(
        self,
        result: Dict[str, Any],
        *,
        runtime_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = dict(result or {})
        payload["_analysis_fallback_used"] = True
        payload["_analysis_fallback_reason"] = "runtime_analysis_missing"
        payload["_analysis_fallback_source"] = str(
            runtime_result.get("entry_ready_source") or ""
        ).strip().lower() or None
        return payload

    def _build_analysis_payload(self, result: Dict[str, Any]) -> Dict[str, Any]:
        status = str(result.get("entry_ready_status") or "").strip().lower()
        reason = str(result.get("entry_ready_reason") or "").strip().lower()
        source = str(result.get("entry_ready_source") or "").strip().lower()
        direction = str(result.get("entry_ready_direction") or "").strip().lower()
        mode = result.get("entry_ready_mode")
        detail = result.get("entry_ready_detail")
        reason_text = result.get("entry_ready_reason_text")
        score = result.get("entry_ready_score")
        signal = dict(result.get("_analysis_entry_signal") or {})
        signal_code = str(signal.get("code") or "").strip().lower()
        if status == "ready" and direction in {"long", "short"}:
            if signal_code in {"early_entry", "good_continuation", "confirmed_breakout"}:
                reason = signal_code
                reason_text = str(signal.get("label") or reason_text).strip() or reason_text
                detail = str(signal.get("detail") or detail).strip() or detail
            else:
                downgraded = self._analysis_ready_requires_stronger_setup(
                    result=result,
                    status=status,
                    direction=direction,
                    score=score,
                )
                if signal_code in {"continuation_entry", "late_continuation"}:
                    downgraded = True
                    reason = signal_code
                    reason_text = str(signal.get("label") or "Watch for pullback").strip()
                    detail = str(signal.get("detail") or detail).strip() or detail
                elif not signal_code:
                    # No signal classification at all — cannot trust "ready" status
                    downgraded = True
                if downgraded:
                    status = "watch"
                    if not signal_code:
                        reason = "watch_setup"
                        reason_text = "Watch for stronger setup"
                        detail = (
                            f"{detail} Stronger directional confirmation is still preferred before entering."
                            if str(detail or "").strip()
                            else "Setup is acceptable, but not strong enough for a high-conviction entry label."
                        )
        severity = "INFO"
        if reason == "stale_snapshot" or status == "blocked":
            severity = "WARN"
        next_action = "Review the detail before acting."
        if status == "ready":
            next_action = "Analytically actionable now."
        elif reason == "watch_setup":
            next_action = "Watch for stronger directional confirmation before entering."
        elif reason == "late_continuation":
            next_action = "Wait for pullback or consolidation before entering."
        elif reason == "continuation_entry":
            next_action = "Tradable, but patience for a cleaner continuation is preferred."
        elif reason == "preview_disabled":
            next_action = "Enable live preview or rely on a fresh runtime snapshot."
        elif reason == "stale_snapshot":
            next_action = "Wait for a fresh runtime snapshot."
        elif reason == "preview_limited":
            next_action = "Use live runtime state for a trading decision."
        elif status == "blocked":
            next_action = "Wait until this blocker clears."
        elif status == "watch":
            next_action = "Watch for stronger confirmation before entering."
        return {
            "analysis_ready_status": status,
            "analysis_ready_reason": reason,
            "analysis_ready_detail": detail,
            "analysis_ready_source": source,
            "analysis_ready_severity": severity,
            "analysis_ready_next": next_action,
            "analysis_ready_reason_text": reason_text,
            "analysis_ready_score": score,
            "analysis_ready_direction": direction,
            "analysis_ready_mode": mode,
            "analysis_ready_updated_at": result.get("entry_ready_updated_at"),
            "analysis_ready_fallback_used": bool(result.get("_analysis_fallback_used")),
            "analysis_ready_fallback_reason": result.get("_analysis_fallback_reason"),
            "analysis_ready_fallback_source": result.get("_analysis_fallback_source"),
        }

    def _build_setup_readiness_payload(
        self,
        analysis_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "setup_ready": str(
                analysis_payload.get("analysis_ready_status") or ""
            ).strip().lower()
            == "ready",
            "setup_ready_status": analysis_payload.get("analysis_ready_status"),
            "setup_ready_reason": analysis_payload.get("analysis_ready_reason"),
            "setup_ready_reason_text": analysis_payload.get(
                "analysis_ready_reason_text"
            ),
            "setup_ready_detail": analysis_payload.get("analysis_ready_detail"),
            "setup_ready_source": analysis_payload.get("analysis_ready_source"),
            "setup_ready_severity": analysis_payload.get("analysis_ready_severity"),
            "setup_ready_next": analysis_payload.get("analysis_ready_next"),
            "setup_ready_score": analysis_payload.get("analysis_ready_score"),
            "setup_ready_direction": analysis_payload.get("analysis_ready_direction"),
            "setup_ready_mode": analysis_payload.get("analysis_ready_mode"),
            "setup_ready_updated_at": analysis_payload.get(
                "analysis_ready_updated_at"
            ),
            "setup_ready_fallback_used": bool(
                analysis_payload.get("analysis_ready_fallback_used")
            ),
            "setup_ready_fallback_reason": analysis_payload.get(
                "analysis_ready_fallback_reason"
            ),
            "setup_ready_fallback_source": analysis_payload.get(
                "analysis_ready_fallback_source"
            ),
        }

    def _build_setup_timing_payload(
        self,
        *,
        result: Dict[str, Any],
        analysis_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        timing = self._derive_setup_timing_state(
            result=result,
            analysis_payload=analysis_payload,
        )
        payload = {
            "analysis_timing_status": timing["status"],
            "analysis_timing_reason": timing["reason"],
            "analysis_timing_reason_text": timing["reason_text"],
            "analysis_timing_detail": timing["detail"],
            "analysis_timing_next": timing["next"],
            "analysis_timing_source": analysis_payload.get("analysis_ready_source"),
            "analysis_timing_updated_at": analysis_payload.get("analysis_ready_updated_at"),
            "analysis_timing_score": analysis_payload.get("analysis_ready_score"),
            "analysis_timing_direction": analysis_payload.get("analysis_ready_direction"),
            "analysis_timing_mode": analysis_payload.get("analysis_ready_mode"),
            "analysis_timing_actionable": timing["status"] == "trigger_ready",
            "analysis_timing_near_trigger": timing["status"] == "armed",
            "analysis_timing_late": timing["status"] == "late",
            "setup_timing_status": timing["status"],
            "setup_timing_reason": timing["reason"],
            "setup_timing_reason_text": timing["reason_text"],
            "setup_timing_detail": timing["detail"],
            "setup_timing_next": timing["next"],
            "setup_timing_source": analysis_payload.get("analysis_ready_source"),
            "setup_timing_updated_at": analysis_payload.get("analysis_ready_updated_at"),
            "setup_timing_score": analysis_payload.get("analysis_ready_score"),
            "setup_timing_direction": analysis_payload.get("analysis_ready_direction"),
            "setup_timing_mode": analysis_payload.get("analysis_ready_mode"),
            "setup_timing_actionable": timing["status"] == "trigger_ready",
            "setup_timing_near_trigger": timing["status"] == "armed",
            "setup_timing_late": timing["status"] == "late",
        }
        return payload

    def _derive_setup_timing_state(
        self,
        *,
        result: Dict[str, Any],
        analysis_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        status = str(analysis_payload.get("analysis_ready_status") or "").strip().lower()
        reason = str(analysis_payload.get("analysis_ready_reason") or "").strip().lower()
        reason_text = str(
            analysis_payload.get("analysis_ready_reason_text") or ""
        ).strip()
        detail = str(analysis_payload.get("analysis_ready_detail") or "").strip()
        direction = str(
            analysis_payload.get("analysis_ready_direction") or ""
        ).strip().lower()
        score = self._safe_float(analysis_payload.get("analysis_ready_score"), None)
        signal = dict(result.get("_analysis_entry_signal") or {})
        signal_code = str(signal.get("code") or "").strip().lower()
        signal_label = str(signal.get("label") or "").strip()
        signal_detail = str(signal.get("detail") or "").strip()
        signal_late = bool(signal.get("late", False))
        signal_phase = str(signal.get("phase") or "").strip().lower()

        stage_status = status or "watch"
        stage_reason = reason or "watch_setup"
        stage_reason_text = reason_text or "Watch for stronger setup"
        stage_detail = detail or "Waiting for stronger setup."
        stage_next = str(analysis_payload.get("analysis_ready_next") or "").strip()

        limited_reasons = {
            "preview_disabled",
            "preview_limited",
            "stale_snapshot",
            "entry_gate_disabled",
            "awaiting_symbol_pick",
        }

        if status == "blocked":
            if reason == "breakout_extended":
                stage_status = "late"
                stage_reason = "breakout_extended"
                stage_reason_text = reason_text or "Late / decayed"
                stage_detail = (
                    detail
                    or "The breakout is too extended to treat as a fresh trigger."
                )
                stage_next = "Wait for a reset, pullback, or new base before entering."
            elif direction in {"long", "short"} and reason == "breakout_not_confirmed" and (
                signal_code == "continuation_entry"
                or self._should_surface_armed_directional_setup(
                    result=result,
                    analysis_payload=analysis_payload,
                    signal_code=signal_code,
                    direction=direction,
                    score=score,
                )
            ):
                stage_status = "armed"
                stage_reason = reason
                stage_reason_text = reason_text or "Armed for confirmation"
                stage_detail = (
                    signal_detail
                    or detail
                    or "Directional confluence is strong, but confirmation is still pending."
                )
                stage_next = "Developing opportunity. Watch for the final breakout trigger before entering."
            else:
                stage_status = "blocked"
                stage_next = stage_next or "Wait until this blocker clears."
        elif reason in limited_reasons:
            stage_status = "watch"
        elif direction in {"long", "short"}:
            if status == "ready":
                if signal_code in {"late_continuation"} or signal_late or signal_phase == "late":
                    stage_status = "late"
                    stage_reason = signal_code or reason or "late_continuation"
                    stage_reason_text = signal_label or reason_text or "Late / decayed"
                    stage_detail = (
                        signal_detail
                        or detail
                        or "The move is already extended; waiting for a reset is safer."
                    )
                    stage_next = "Wait for a pullback, consolidation, or fresh reclaim before entering."
                elif signal_code in {"continuation_entry"}:
                    stage_status = "armed"
                    stage_reason = signal_code
                    stage_reason_text = signal_label or "Armed continuation"
                    stage_detail = (
                        signal_detail
                        or detail
                        or "Directional structure is building toward a likely trigger."
                    )
                    stage_next = "Developing opportunity. Watch for the final trigger before entering."
                else:
                    stage_status = "trigger_ready"
                    stage_reason = signal_code or reason or "trigger_ready"
                    stage_reason_text = signal_label or reason_text or "Trigger ready"
                    stage_detail = (
                        signal_detail
                        or detail
                        or "Entry conditions are actionable now."
                    )
                    stage_next = "Actionable now."
            elif status == "watch":
                if reason == "late_continuation" or signal_code == "late_continuation" or signal_late:
                    stage_status = "late"
                    stage_reason = signal_code or reason or "late_continuation"
                    stage_reason_text = signal_label or reason_text or "Late / decayed"
                    stage_detail = (
                        signal_detail
                        or detail
                        or "The move is already extended; waiting for a reset is safer."
                    )
                    stage_next = "Wait for a pullback, consolidation, or fresh reclaim before entering."
                elif self._should_surface_armed_directional_setup(
                    result=result,
                    analysis_payload=analysis_payload,
                    signal_code=signal_code,
                    direction=direction,
                    score=score,
                ):
                    stage_status = "armed"
                    stage_reason = signal_code or reason or "armed_setup"
                    stage_reason_text = signal_label or reason_text or "Armed setup"
                    stage_detail = (
                        signal_detail
                        or detail
                        or "Directional confluence is building toward a likely trigger."
                    )
                    stage_next = "Developing opportunity. Watch for the final trigger before entering."

        return {
            "status": stage_status,
            "reason": stage_reason,
            "reason_text": stage_reason_text,
            "detail": stage_detail,
            "next": stage_next,
        }

    def _should_surface_armed_directional_setup(
        self,
        *,
        result: Dict[str, Any],
        analysis_payload: Dict[str, Any],
        signal_code: str,
        direction: str,
        score: Optional[float],
    ) -> bool:
        if str(direction or "").strip().lower() not in {"long", "short"}:
            return False
        reason = str(analysis_payload.get("analysis_ready_reason") or "").strip().lower()
        if reason in {
            "low_setup_quality",
            "setup_quality_too_low",
            "preview_disabled",
            "preview_limited",
            "stale_snapshot",
            "entry_gate_disabled",
            "awaiting_symbol_pick",
            "trend_too_strong",
            "no_trade_zone",
        }:
            return False
        if signal_code == "continuation_entry":
            return True
        if reason not in {
            "waiting_for_confirmation",
            "breakout_not_confirmed",
            "watch_setup",
            "waiting_for_better_structure",
        }:
            return False
        return not self._analysis_ready_requires_stronger_setup(
            result=result,
            status="ready",
            direction=direction,
            score=score,
        )

    def _build_execution_viability_payload(
        self,
        bot: Dict[str, Any],
        *,
        mode: str,
    ) -> Dict[str, Any]:
        blocker = self._get_runtime_opening_blocker(bot, mode=mode)
        updated_at = datetime.now(timezone.utc).isoformat()
        if blocker is None:
            return {
                "execution_blocked": False,
                "execution_viability_status": "viable",
                "execution_viability_reason": "openings_clear",
                "execution_viability_reason_text": "Opening clear",
                "execution_viability_bucket": "viable",
                "execution_margin_limited": False,
                "execution_viability_detail": "No runtime opening blocker is currently active.",
                "execution_viability_source": "runtime_opening_clear",
                "execution_viability_diagnostic_reason": None,
                "execution_viability_diagnostic_text": None,
                "execution_viability_diagnostic_detail": None,
                "execution_viability_stale_data": False,
                "execution_available_margin_usdt": None,
                "execution_required_margin_usdt": None,
                "execution_order_notional_usdt": None,
                "execution_viability_updated_at": updated_at,
            }
        blocked = bool(blocker.get("execution_blocked", True))
        status = str(
            blocker.get("execution_status") or ("blocked" if blocked else "viable")
        ).strip().lower()
        reason = str(
            blocker.get("execution_reason") or blocker.get("reason") or ""
        ).strip().lower() or "opening_blocked"
        reason_text = str(
            blocker.get("execution_reason_text") or blocker.get("reason_text") or ""
        ).strip() or "Opening blocked"
        bucket = str(blocker.get("execution_bucket") or "").strip().lower()
        if not bucket:
            bucket = "blocked"
            if reason == "insufficient_margin":
                bucket = "margin_limited"
            elif reason == "opening_margin_reserve":
                bucket = "margin_limited"
            elif reason in {"qty_below_min", "notional_below_min"}:
                bucket = "size_limited"
            elif reason == "position_cap_hit":
                bucket = "position_capped"
        return {
            "execution_blocked": blocked,
            "execution_viability_status": status,
            "execution_viability_reason": reason,
            "execution_viability_reason_text": reason_text,
            "execution_viability_bucket": bucket,
            "execution_margin_limited": bool(
                blocker.get(
                    "execution_margin_limited",
                    reason in {"insufficient_margin", "opening_margin_reserve"},
                )
            ),
            "execution_viability_detail": blocker["detail"],
            "execution_viability_source": blocker["source"],
            "execution_viability_diagnostic_reason": str(
                blocker.get("diagnostic_reason") or reason or ""
            ).strip().lower()
            or None,
            "execution_viability_diagnostic_text": str(
                blocker.get("diagnostic_reason_text") or reason_text or ""
            ).strip()
            or None,
            "execution_viability_diagnostic_detail": str(
                blocker.get("diagnostic_detail") or blocker["detail"] or ""
            ).strip()
            or None,
            "execution_viability_stale_data": bool(blocker.get("stale_data", False)),
            "execution_available_margin_usdt": self._safe_float(
                blocker.get("available_margin_usdt"),
                None,
            ),
            "execution_required_margin_usdt": self._safe_float(
                blocker.get("required_margin_usdt"),
                None,
            ),
            "execution_order_notional_usdt": self._safe_float(
                blocker.get("order_notional_usdt"),
                None,
            ),
            "execution_viability_updated_at": updated_at,
        }

    def _derive_readiness_source_kind(
        self,
        *,
        status: str,
        analysis_payload: Dict[str, Any],
    ) -> str:
        if bool(analysis_payload.get("analysis_ready_fallback_used")):
            return "fresh_fallback"
        source = str(analysis_payload.get("analysis_ready_source") or "").strip().lower()
        if source.startswith("runtime"):
            return "runtime"
        if source in {"stopped_preview_stale", "bounded_preview_disabled"}:
            return "stopped_preview"
        if str(status or "").strip().lower() in self.RUNTIME_ACTIVE_STATUSES:
            return "fresh_analysis"
        return "stopped_preview"

    def _analysis_ready_requires_stronger_setup(
        self,
        *,
        result: Dict[str, Any],
        status: str,
        direction: str,
        score: Optional[float],
    ) -> bool:
        if str(status or "").strip().lower() != "ready":
            return False
        if str(direction or "").strip().lower() not in {"long", "short"}:
            return False
        strong_score = float(getattr(cfg, "SETUP_QUALITY_STRONG_SCORE", 72.0) or 72.0)
        numeric_score = self._safe_float(score, None)
        if numeric_score is None:
            return True
        if numeric_score < strong_score:
            return True

        band = str(result.get("_analysis_band") or "").strip().lower()
        if band and band != "strong":
            return True

        mode_fit_min = float(
            getattr(cfg, "ENTRY_READINESS_STRONG_DIRECTIONAL_MODE_FIT_MIN", 2.5) or 2.5
        )
        mode_fit_score = self._safe_float(result.get("_analysis_mode_fit_score"), None)
        if mode_fit_score is None or mode_fit_score < mode_fit_min:
            return True

        price_action_direction = str(
            result.get("_analysis_price_action_direction") or ""
        ).strip().lower()
        if price_action_direction:
            if direction == "long" and price_action_direction != "bullish":
                return True
            if direction == "short" and price_action_direction != "bearish":
                return True

        summary = str(result.get("_analysis_summary") or "").strip().lower()
        if not summary or summary == "mixed confluence":
            return True
        return False

    def _attach_setup_quality_context(
        self,
        result: Dict[str, Any],
        *,
        setup_quality: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = dict(result or {})
        quality = dict(setup_quality or {})
        payload["_analysis_band"] = str(quality.get("band") or "").strip().lower() or None
        payload["_analysis_summary"] = quality.get("summary")
        components = dict((quality.get("components") or {}))
        mode_fit = dict((components.get("mode_fit") or {}))
        price_action_context = dict((components.get("price_action_context") or {}))
        payload["_analysis_mode_fit_score"] = self._safe_float(
            mode_fit.get("score"),
            None,
        )
        payload["_analysis_price_action_direction"] = str(
            price_action_context.get("direction") or ""
        ).strip().lower() or None
        if quality.get("entry_signal") is not None:
            payload["_analysis_entry_signal"] = dict(quality.get("entry_signal") or {})
        return payload

    def _attach_runtime_directional_analysis_context(
        self,
        result: Dict[str, Any],
        *,
        bot: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = dict(result or {})
        payload["_analysis_band"] = str(bot.get("setup_quality_band") or "").strip().lower() or None
        payload["_analysis_summary"] = bot.get("setup_quality_summary")
        payload["_analysis_mode_fit_score"] = self._safe_float(
            bot.get("readiness_price_action_mode_fit_score"),
            None,
        )
        payload["_analysis_price_action_direction"] = str(
            bot.get("readiness_price_action_direction") or ""
        ).strip().lower() or None
        payload["_analysis_entry_signal"] = self._get_runtime_entry_signal(bot)
        return payload

    def _build_live_gate_payload(
        self,
        bot: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        updated_at = datetime.now(timezone.utc).isoformat()
        bot_gate_enabled = bool(bot.get("entry_gate_enabled", True))
        global_master_applicable = mode in self.DIRECTIONAL_MODES
        global_master_enabled = (
            bool(getattr(cfg, "ENTRY_GATE_ENABLED", False))
            if global_master_applicable
            else True
        )
        status = "off"
        reason = "gate_off"
        reason_text = "Gate off"
        detail = "Live entry gate is disabled."
        source = "entry_gate_disabled_bot"
        if mode in self.DIRECTIONAL_MODES:
            if not getattr(cfg, "ENTRY_GATE_ENABLED", False):
                status = "off_global"
                reason = "gate_off_global"
                reason_text = "Gate off globally"
                detail = "Directional live entry gate is disabled globally."
                source = "entry_gate_disabled_global"
            elif not bot_gate_enabled:
                status = "off_bot"
                reason = "gate_off_bot"
                reason_text = "Gate off for this bot"
                detail = "Directional live entry gate is disabled for this bot."
                source = "entry_gate_disabled_bot"
            else:
                status = "on"
                reason = "gate_on"
                reason_text = "Gate on"
                detail = "Directional live entry gate is active."
                source = "entry_gate_active"
        elif mode in (self.NEUTRAL_MODES | self.SCALP_MODES):
            if bot_gate_enabled:
                status = "on"
                reason = "gate_on"
                reason_text = "Gate on"
                detail = "Live entry gate is active for this bot."
                source = "entry_gate_active"
            else:
                status = "off_bot"
                reason = "gate_off_bot"
                reason_text = "Gate off for this bot"
                detail = "Live entry gate is disabled for this bot."
                source = "entry_gate_disabled_bot"
        return {
            "live_gate_status": status,
            "live_gate_reason": reason,
            "live_gate_reason_text": reason_text,
            "live_gate_detail": detail,
            "live_gate_source": source,
            "live_gate_bot_enabled": bot_gate_enabled,
            "live_gate_global_master_applicable": global_master_applicable,
            "live_gate_global_master_enabled": global_master_enabled,
            "live_gate_contract_active": status == "on",
            "live_gate_updated_at": updated_at,
        }

    def _watch_reason_from_setup_quality(
        self,
        setup_quality: Optional[Dict[str, Any]],
        *,
        breakout_required: bool = False,
    ) -> Optional[Dict[str, str]]:
        quality = dict(setup_quality or {})
        if not quality.get("enabled"):
            return None
        if not quality.get("entry_allowed", True):
            return {
                "code": "setup_quality_too_low",
                "text": "Setup quality too low",
            }
        if str(quality.get("band") or "").strip().lower() == "caution":
            return {
                "code": "low_setup_quality",
                "text": "Low setup quality",
            }
        if breakout_required and not quality.get("breakout_ready", True):
            return {
                "code": "waiting_for_confirmation",
                "text": "Waiting for confirmation",
            }
        return None

    @staticmethod
    def _map_directional_block_reason(gate_result: Dict[str, Any]) -> Dict[str, str]:
        blocked_by = {
            str(code or "").strip().upper()
            for code in (gate_result or {}).get("blocked_by", [])
        }
        reason_text = str((gate_result or {}).get("reason") or "").strip().lower()
        if "BREAKOUT_NOT_CONFIRMED" in blocked_by:
            return {"code": "breakout_not_confirmed", "text": "Breakout not confirmed"}
        if blocked_by & {"BREAKOUT_CHASE_TOO_FAR", "BREAKOUT_EXTENDED", "NO_CHASE_FILTER"}:
            return {"code": "breakout_extended", "text": "Breakout extended"}
        if "RESISTANCE_NEARBY" in blocked_by:
            return {"code": "near_resistance", "text": "Near resistance"}
        if "SUPPORT_NEARBY" in blocked_by:
            return {"code": "near_support", "text": "Near support"}
        if "SETUP_QUALITY_LOW" in blocked_by:
            return {"code": "setup_quality_too_low", "text": "Setup quality too low"}
        if {"PRICE_ACTION_BEARISH", "PRICE_ACTION_BULLISH"} & blocked_by:
            return {"code": "structure_weak", "text": "Structure against entry"}
        if blocked_by & {
            "RSI_OVERBOUGHT",
            "RSI_OVERSOLD",
            "BB_HIGH",
            "BB_LOW",
            "EMA_EXTENDED",
        }:
            return {"code": "no_trade_zone", "text": "No-trade zone"}
        if "breakout" in reason_text:
            return {"code": "breakout_not_confirmed", "text": "Breakout not confirmed"}
        return {"code": "waiting_for_confirmation", "text": "Waiting for confirmation"}

    @staticmethod
    def _map_side_gate_reason(side_result: Dict[str, Any]) -> Dict[str, str]:
        blocked_by = {
            str(code or "").strip().upper()
            for code in (side_result or {}).get("blocked_by", [])
        }
        if "RESISTANCE_NEARBY" in blocked_by:
            return {"code": "near_resistance", "text": "Near resistance"}
        if "SUPPORT_NEARBY" in blocked_by:
            return {"code": "near_support", "text": "Near support"}
        if {"PRICE_ACTION_BEARISH", "PRICE_ACTION_BULLISH"} & blocked_by:
            return {"code": "structure_weak", "text": "Structure against entry"}
        return {"code": "waiting_for_better_structure", "text": "Waiting for better structure"}

    @staticmethod
    def _map_neutral_gate_reason(gate_result: Dict[str, Any]) -> Dict[str, str]:
        blocked_by = {
            str(code or "").strip().upper()
            for code in (gate_result or {}).get("blocked_by", [])
        }
        if blocked_by & {"ADX_15M", "ADX_1M"}:
            return {"code": "trend_too_strong", "text": "Trend too strong"}
        if "ATR_HIGH" in blocked_by:
            return {"code": "no_trade_zone", "text": "No-trade zone"}
        if blocked_by & {"RSI_OVERBOUGHT", "RSI_OVERSOLD"}:
            return {"code": "no_trade_zone", "text": "No-trade zone"}
        return {"code": "waiting_for_better_structure", "text": "Waiting for better structure"}

    @staticmethod
    def _map_reason_text(reason: str) -> Dict[str, str]:
        text = str(reason or "").strip().lower()
        if "loss budget" in text:
            return {"code": "loss_budget_blocked", "text": "Loss budget blocked"}
        if "position cap" in text:
            return {"code": "position_cap_hit", "text": "Position cap hit"}
        if "stale balance" in text or "saved capital check is stale" in text:
            return {"code": "stale_balance", "text": "Stale balance"}
        if "reserve limited" in text or ("reserve" in text and "opening margin" in text):
            return {"code": "opening_margin_reserve", "text": "Reserve limited"}
        if "margin" in text:
            return {"code": "insufficient_margin", "text": "Insufficient margin"}
        if "notional" in text or ("order $" in text and "below min $" in text):
            return {"code": "notional_below_min", "text": "Budget below first order"}
        if "below min" in text or "minimum" in text:
            return {"code": "qty_below_min", "text": "Min qty too high"}
        if "resistance" in text:
            return {"code": "near_resistance", "text": "Near resistance"}
        if "support" in text:
            return {"code": "near_support", "text": "Near support"}
        if "no-chase" in text or "extended" in text:
            return {"code": "breakout_extended", "text": "Breakout extended"}
        if "invalidation" in text:
            return {"code": "breakout_invalidated", "text": "Breakout invalidated"}
        if "breakout" in text or "closed candles" in text or "volume confirmation" in text:
            return {"code": "breakout_not_confirmed", "text": "Breakout not confirmed"}
        if "setup quality" in text or "weak setup" in text:
            return {"code": "setup_quality_too_low", "text": "Setup quality too low"}
        if "adx" in text or "trending" in text or "trend" in text:
            return {"code": "trend_too_strong", "text": "Trend too strong"}
        if "no-trade" in text or "no trade" in text:
            return {"code": "no_trade_zone", "text": "No-trade zone"}
        if "price action" in text or "structure" in text:
            return {"code": "structure_weak", "text": "Structure against entry"}
        return {"code": "waiting_for_better_structure", "text": "Waiting for better structure"}

    def _get_cached(
        self,
        store: Dict[str, Dict[str, Any]],
        key: str,
    ) -> Optional[Dict[str, Any]]:
        cached = store.get(key)
        if not cached:
            return None
        if self._get_now_ts() - cached.get("ts", 0.0) >= self.cache_ttl_seconds:
            store.pop(key, None)
            return None
        return copy.deepcopy(cached.get("value"))

    def _set_cached(
        self,
        store: Dict[str, Dict[str, Any]],
        key: str,
        value: Dict[str, Any],
    ) -> Dict[str, Any]:
        store[key] = {
            "ts": self._get_now_ts(),
            "value": copy.deepcopy(value),
        }
        return copy.deepcopy(value)

    @staticmethod
    def _safe_float(value: Any, default: Optional[float]) -> Optional[float]:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_now_ts() -> float:
        return time.time()
