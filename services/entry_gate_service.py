"""
Entry Gate Service.

Determines if market conditions are favorable for entering a position.
Blocks entry when conditions indicate a bad entry point, including momentum
extremes or nearby adverse support/resistance.
"""

import logging
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

import config.strategy_config as cfg
from services.price_action_signal_service import PriceActionSignalService
from services.price_prediction_service import SupportResistanceDetector

logger = logging.getLogger(__name__)


class EntryGateService:
    """
    Gate service that checks if conditions are favorable for long/short entry.

    Longs are blocked by overbought/extended conditions or nearby resistance.
    Shorts are blocked by oversold/extended conditions or nearby support.
    """

    def __init__(self, indicator_service):
        self.indicator_service = indicator_service
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 30
        self._sr_detector = SupportResistanceDetector(
            touch_threshold_pct=cfg.SR_TOUCH_THRESHOLD_PCT,
            lookback=cfg.SR_LOOKBACK_CANDLES,
        )
        self.price_action_service = PriceActionSignalService(
            indicator_service,
            sr_detector=self._sr_detector,
        )

    def _get_now_ts(self) -> float:
        return time.time()

    @staticmethod
    def _is_directional_entry_gate_active(bot: Optional[Dict[str, Any]] = None) -> bool:
        """Operator-facing directional entry gate contract."""
        return bool(
            getattr(cfg, "ENTRY_GATE_ENABLED", False)
            and bool((bot or {}).get("entry_gate_enabled", True))
        )

    def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        cached = self._cache.get(key)
        if not cached:
            return None
        if self._get_now_ts() - cached.get("ts", 0) >= self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return deepcopy(cached.get("value"))

    def _set_cached(self, key: str, value: Dict[str, Any]) -> Dict[str, Any]:
        self._cache[key] = {
            "ts": self._get_now_ts(),
            "value": deepcopy(value),
        }
        return deepcopy(value)

    @staticmethod
    def _normalize_level(
        level: Dict[str, Any],
        current_price: float,
        level_type: str,
    ) -> Optional[Dict[str, Any]]:
        if not level or current_price <= 0:
            return None
        try:
            level_price = float(level.get("price") or 0.0)
        except (TypeError, ValueError):
            level_price = 0.0
        if level_price <= 0:
            return None
        normalized = dict(level)
        normalized["type"] = level_type
        normalized["distance_pct"] = abs(level_price - current_price) / current_price
        return normalized

    def _get_structure_levels(
        self,
        symbol: str,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        cache_price = round(float(current_price or 0.0), 8)
        cache_key = f"structure:{symbol}:{cfg.ENTRY_GATE_TIMEFRAME}:{cache_price}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result: Dict[str, Any] = {
            "nearest_support": None,
            "nearest_resistance": None,
            "levels": [],
            "error": None,
        }

        try:
            candles = self.indicator_service.get_ohlcv(
                symbol,
                cfg.ENTRY_GATE_TIMEFRAME,
                limit=max(cfg.SR_LOOKBACK_CANDLES, 200),
            )
        except Exception as exc:
            result["error"] = str(exc)
            return self._set_cached(cache_key, result)

        if not candles:
            result["error"] = "no_candles"
            return self._set_cached(cache_key, result)

        resolved_price = current_price
        if resolved_price is None:
            try:
                resolved_price = float(candles[-1].get("close") or 0.0)
            except (TypeError, ValueError):
                resolved_price = 0.0
        if not resolved_price or resolved_price <= 0:
            result["error"] = "invalid_price"
            return self._set_cached(cache_key, result)

        sr_levels = self._sr_detector.detect_levels(candles)
        combined_levels: List[Dict[str, Any]] = []
        for raw_level in (sr_levels.get("support", []) or []) + (
            sr_levels.get("resistance", []) or []
        ):
            try:
                raw_price = float(raw_level.get("price") or 0.0)
            except (TypeError, ValueError):
                raw_price = 0.0
            normalized = self._normalize_level(
                raw_level,
                current_price=resolved_price,
                level_type="support" if 0 < raw_price < resolved_price else "resistance",
            )
            if normalized:
                combined_levels.append(normalized)

        support_levels = [level for level in combined_levels if level["type"] == "support"]
        resistance_levels = [
            level for level in combined_levels if level["type"] == "resistance"
        ]

        result["levels"] = combined_levels
        if support_levels:
            result["nearest_support"] = min(
                support_levels, key=lambda level: level.get("distance_pct", 1.0)
            )
        if resistance_levels:
            result["nearest_resistance"] = min(
                resistance_levels, key=lambda level: level.get("distance_pct", 1.0)
            )
        return self._set_cached(cache_key, result)

    def get_price_action_context(
        self,
        symbol: str,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            return self.price_action_service.analyze(
                symbol=symbol,
                current_price=current_price,
            )
        except Exception as exc:
            logger.debug("[%s] Price-action context failed: %s", symbol, exc)
            return {
                "symbol": symbol,
                "direction": "neutral",
                "net_score": 0.0,
                "bullish_score": 0.0,
                "bearish_score": 0.0,
                "components": {},
                "summary": f"price-action unavailable: {exc}",
            }

    def evaluate_price_action_side(
        self,
        symbol: str,
        side: str,
        current_price: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or self.get_price_action_context(
            symbol=symbol,
            current_price=current_price,
        )
        return self.price_action_service.evaluate_side(context=context, side=side)

    def score_price_action_mode(
        self,
        symbol: str,
        mode: str,
        current_price: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or self.get_price_action_context(
            symbol=symbol,
            current_price=current_price,
        )
        return self.price_action_service.score_mode_fit(context=context, mode=mode)

    def get_structure_context(
        self,
        symbol: str,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self._get_structure_levels(symbol, current_price=current_price)

    def _get_closed_candles(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        candles = self.indicator_service.get_ohlcv(symbol, interval=interval, limit=limit) or []
        if len(candles) > 1 and getattr(cfg, "PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES", False):
            return candles[:-1]
        return candles

    @staticmethod
    def _mode_to_side(mode: str) -> Optional[str]:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode == "long":
            return "buy"
        if normalized_mode == "short":
            return "sell"
        return None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_experiment_tags(*values: Any) -> List[str]:
        tags: List[str] = []
        for value in values:
            if isinstance(value, (list, tuple, set)):
                items = value
            else:
                items = [value]
            for item in items:
                tag = str(item or "").strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
        return sorted(tags)

    @classmethod
    def _merge_experiment_details(cls, *values: Any) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            for key, detail in value.items():
                tag = str(key or "").strip().lower()
                if not tag:
                    continue
                if isinstance(detail, dict):
                    existing = merged.get(tag)
                    if isinstance(existing, dict):
                        combined = dict(existing)
                        combined.update(detail)
                        merged[tag] = combined
                    else:
                        merged[tag] = dict(detail)
                elif detail is not None:
                    merged[tag] = detail
        return merged

    @classmethod
    def _attach_experiment(
        cls,
        payload: Optional[Dict[str, Any]],
        *,
        tag: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        updated = dict(payload or {})
        updated["experiment_tags"] = cls._normalize_experiment_tags(
            updated.get("experiment_tags"),
            [tag],
        )
        merged_details = cls._merge_experiment_details(
            updated.get("experiment_details"),
            {tag: details or {}},
        )
        if merged_details:
            updated["experiment_details"] = merged_details
        return updated

    def _maybe_relax_directional_structure_block(
        self,
        *,
        mode: str,
        side: str,
        structure_result: Optional[Dict[str, Any]],
        setup_quality: Optional[Dict[str, Any]],
        breakout_confirmation: Optional[Dict[str, Any]] = None,
        entry_signal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        adjusted = deepcopy(structure_result or {})
        if not bool(
            getattr(cfg, "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_ENABLED", False)
        ):
            return adjusted

        normalized_mode = str(mode or "").strip().lower()
        normalized_side = str(side or "").strip().lower()
        expected_side = "buy" if normalized_mode == "long" else "sell" if normalized_mode == "short" else None
        if expected_side is None or normalized_side != expected_side:
            return adjusted

        blocked_by = [
            str(code or "").strip().upper()
            for code in (adjusted.get("blocked_by") or [])
            if str(code or "").strip()
        ]
        structure_codes = {"RESISTANCE_NEARBY", "SUPPORT_NEARBY"}
        if not blocked_by or any(code not in structure_codes for code in blocked_by):
            return adjusted

        quality = dict(setup_quality or {})
        if not quality or not bool(quality.get("entry_allowed", True)):
            return adjusted

        breakout_state = dict(breakout_confirmation or {})
        if bool(breakout_state.get("required")) and not bool(
            breakout_state.get("confirmed", False)
        ):
            return adjusted

        signal = dict(
            entry_signal
            or self.classify_directional_entry_signal(
                mode=normalized_mode,
                setup_quality=quality,
                breakout_confirmation=breakout_state or None,
            )
        )
        eligible_codes = {
            str(code or "").strip().lower()
            for code in getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_SIGNAL_CODES",
                ("early_entry", "good_continuation", "confirmed_breakout"),
            )
            if str(code or "").strip()
        }
        signal_code = str(signal.get("code") or "").strip().lower()
        if signal_code not in eligible_codes or bool(signal.get("late")):
            return adjusted

        components = dict(quality.get("components") or {})
        component_points = dict(quality.get("component_points") or {})
        score = self._safe_float(quality.get("score"), 0.0)
        mode_fit_score = self._safe_float(
            (components.get("mode_fit") or {}).get("score"),
            0.0,
        )
        price_action_component = self._safe_float(
            component_points.get("price_action"),
            0.0,
        )
        supportive_structure_component = self._safe_float(
            component_points.get("supportive_structure"),
            0.0,
        )
        confirmation_component = max(
            self._safe_float(component_points.get("volume"), 0.0),
            self._safe_float(component_points.get("mtf"), 0.0),
        )
        extension_ratio = self._safe_float(signal.get("extension_ratio"), 0.0)

        if score < float(
            getattr(cfg, "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_SCORE_MIN", 80.0)
            or 80.0
        ):
            return adjusted
        if mode_fit_score < float(
            getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_MODE_FIT_MIN",
                4.5,
            )
            or 4.5
        ):
            return adjusted
        if price_action_component < float(
            getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_PRICE_ACTION_MIN",
                2.5,
            )
            or 2.5
        ):
            return adjusted
        if supportive_structure_component < float(
            getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_SUPPORTIVE_STRUCTURE_MIN",
                1.0,
            )
            or 1.0
        ):
            return adjusted
        if confirmation_component < float(
            getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_CONFIRMATION_MIN",
                1.0,
            )
            or 1.0
        ):
            return adjusted
        if extension_ratio > float(
            getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_EXTENSION_RATIO_MAX",
                0.55,
            )
            or 0.55
        ):
            return adjusted

        scores = dict(adjusted.get("scores") or {})
        adverse_level = dict(scores.get("adverse_level") or {})
        distance_pct = self._safe_float(adverse_level.get("distance_pct"), 0.0)
        strength = int(self._safe_float(adverse_level.get("strength"), 0.0))
        proximity_limit = self._safe_float(getattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01), 0.01)
        min_distance = proximity_limit * float(
            getattr(
                cfg,
                "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_MIN_DISTANCE_RATIO",
                0.65,
            )
            or 0.65
        )
        max_strength = int(
            self._safe_float(
                getattr(
                    cfg,
                    "ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_MAX_STRENGTH",
                    7,
                ),
                7.0,
            )
        )
        if (
            distance_pct <= 0
            or distance_pct > proximity_limit
            or distance_pct < min_distance
            or strength > max_strength
        ):
            return adjusted

        scores["experimental_structure_relaxation"] = {
            "applied": True,
            "signal_code": signal_code,
            "distance_pct": round(distance_pct, 6),
            "strength": strength,
        }
        adjusted["scores"] = scores
        adjusted["suitable"] = True
        adjusted["blocked_by"] = []
        adjusted["reason"] = "Experimental directional structure relaxation applied"
        return self._attach_experiment(
            adjusted,
            tag="exp_directional_structure_relax_used",
            details={
                "signal_code": signal_code,
                "distance_pct": round(distance_pct, 6),
                "strength": strength,
            },
        )

    @classmethod
    def _score_directional_component(cls, side: str, value: Any, cap: float) -> float:
        if cap <= 0:
            return 0.0
        raw_value = cls._clamp(float(value or 0.0), -cap, cap) / cap
        if side == "sell":
            raw_value *= -1.0
        return cls._clamp(raw_value, -1.0, 1.0)

    @classmethod
    def _score_structure_level(
        cls,
        level: Optional[Dict[str, Any]],
        proximity_pct: float,
    ) -> float:
        if not level or proximity_pct <= 0:
            return 0.0
        strength = cls._clamp(float(level.get("strength") or 0.0) / 10.0, 0.0, 1.0)
        distance_pct = max(0.0, float(level.get("distance_pct") or 0.0))
        proximity = cls._clamp(1.0 - (distance_pct / proximity_pct), 0.0, 1.0)
        return round(strength * proximity, 4)

    @staticmethod
    def _summarize_quality_components(
        component_points: Dict[str, float],
        limit: int = 4,
    ) -> str:
        significant = [
            (name, points)
            for name, points in component_points.items()
            if abs(float(points or 0.0)) >= 1.0
        ]
        significant.sort(key=lambda item: abs(item[1]), reverse=True)
        if not significant:
            return "mixed confluence"
        return ", ".join(f"{name}={points:+.1f}" for name, points in significant[:limit])

    def _classify_setup_quality(self, score: float) -> Dict[str, Any]:
        score = float(score or 0.0)
        if score >= getattr(cfg, "SETUP_QUALITY_STRONG_SCORE", 72.0):
            return {
                "band": "strong",
                "entry_aggressiveness_mult": 1.0,
                "grid_spacing_mult": 1.0,
                "grid_level_mult": 1.0,
            }
        if score >= getattr(cfg, "SETUP_QUALITY_CAUTION_SCORE", 60.0):
            return {
                "band": "good",
                "entry_aggressiveness_mult": 1.0,
                "grid_spacing_mult": 1.0,
                "grid_level_mult": 1.0,
            }
        if score >= getattr(cfg, "SETUP_QUALITY_MIN_ENTRY_SCORE", 52.0):
            return {
                "band": "caution",
                "entry_aggressiveness_mult": getattr(
                    cfg,
                    "SETUP_QUALITY_ENTRY_AGGRESSIVENESS_CAUTION",
                    0.85,
                ),
                "grid_spacing_mult": getattr(
                    cfg,
                    "SETUP_QUALITY_GRID_SPACING_MULT_CAUTION",
                    1.10,
                ),
                "grid_level_mult": getattr(
                    cfg,
                    "SETUP_QUALITY_GRID_LEVEL_MULT_CAUTION",
                    0.90,
                ),
            }
        return {
            "band": "poor",
            "entry_aggressiveness_mult": getattr(
                cfg,
                "SETUP_QUALITY_ENTRY_AGGRESSIVENESS_POOR",
                0.70,
            ),
            "grid_spacing_mult": getattr(
                cfg,
                "SETUP_QUALITY_GRID_SPACING_MULT_POOR",
                1.20,
            ),
            "grid_level_mult": getattr(
                cfg,
                "SETUP_QUALITY_GRID_LEVEL_MULT_POOR",
                0.75,
            ),
        }

    def get_setup_quality(
        self,
        symbol: str,
        mode: str,
        current_price: Optional[float] = None,
        indicators: Optional[Dict[str, Any]] = None,
        structure: Optional[Dict[str, Any]] = None,
        price_action_context: Optional[Dict[str, Any]] = None,
        side_result: Optional[Dict[str, Any]] = None,
        suppress_components: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        result: Dict[str, Any] = {
            "enabled": bool(getattr(cfg, "SETUP_QUALITY_SCORE_ENABLED", False)),
            "symbol": symbol,
            "mode": normalized_mode,
            "side": self._mode_to_side(normalized_mode),
            "score": 50.0,
            "normalized_score": 0.5,
            "entry_allowed": True,
            "breakout_ready": True,
            "band": "disabled",
            "entry_aggressiveness_mult": 1.0,
            "grid_spacing_mult": 1.0,
            "grid_level_mult": 1.0,
            "summary": "setup quality disabled",
            "components": {},
            "component_points": {},
            "structure": structure or {},
        }

        if normalized_mode not in {
            "long",
            "short",
            "neutral",
            "neutral_classic_bybit",
            "scalp_pnl",
            "scalp_market",
        }:
            result["summary"] = f"unsupported mode {normalized_mode}"
            return result

        if not result["enabled"]:
            return result

        side = result["side"]
        if side is None:
            if normalized_mode in {"neutral", "neutral_classic_bybit"}:
                side = "neutral"
            else:
                side = "buy"
            result["side"] = side

        indicators = indicators or {}
        if current_price is None:
            try:
                current_price = float(indicators.get("close") or 0.0)
            except (TypeError, ValueError):
                current_price = 0.0
        close_price = self._safe_float(indicators.get("close"), 0.0)
        ema_21_value = self._safe_float(indicators.get("ema_21"), 0.0)
        price_vs_ema_pct = None
        if ema_21_value > 0 and close_price > 0:
            price_vs_ema_pct = (close_price - ema_21_value) / ema_21_value

        if structure is None:
            structure = self._get_structure_levels(symbol, current_price=current_price)
        result["structure"] = structure

        if price_action_context is None:
            price_action_context = self.get_price_action_context(
                symbol=symbol,
                current_price=current_price,
            )

        if side_result is None and side in {"buy", "sell"}:
            side_result = self.evaluate_price_action_side(
                symbol=symbol,
                side=side,
                current_price=current_price,
                context=price_action_context,
            )

        mode_fit = self.score_price_action_mode(
            symbol=symbol,
            mode=normalized_mode,
            current_price=current_price,
            context=price_action_context,
        )

        score = 50.0
        component_points: Dict[str, float] = {}
        suppressed_components = {
            str(component or "").strip().lower()
            for component in (suppress_components or [])
            if str(component or "").strip()
        }
        components = (price_action_context or {}).get("components") or {}
        proximity_pct = max(
            float(getattr(cfg, "SETUP_QUALITY_STRUCTURE_PROXIMITY_PCT", 0.02) or 0.02),
            float(getattr(cfg, "ENTRY_GATE_SR_PROXIMITY_PCT", 0.01) or 0.01),
        )

        supportive_level = None
        adverse_level = None
        if normalized_mode == "long":
            supportive_level = (structure or {}).get("nearest_support")
            adverse_level = (structure or {}).get("nearest_resistance")
        elif normalized_mode == "short":
            supportive_level = (structure or {}).get("nearest_resistance")
            adverse_level = (structure or {}).get("nearest_support")

        supportive_alignment = self._score_structure_level(supportive_level, proximity_pct)
        adverse_alignment = self._score_structure_level(adverse_level, proximity_pct)
        if supportive_alignment > 0:
            component_points["supportive_structure"] = round(
                supportive_alignment
                * float(getattr(cfg, "SETUP_QUALITY_SUPPORTIVE_STRUCTURE_WEIGHT", 10.0)),
                2,
            )
            score += component_points["supportive_structure"]
        if adverse_alignment > 0 and "adverse_structure" not in suppressed_components:
            component_points["adverse_structure"] = round(
                -adverse_alignment
                * float(getattr(cfg, "SETUP_QUALITY_ADVERSE_STRUCTURE_WEIGHT", 16.0)),
                2,
            )
            score += component_points["adverse_structure"]

        side_supportive = float((side_result or {}).get("supportive_score") or 0.0)
        side_adverse = float((side_result or {}).get("adverse_score") or 0.0)
        side_net = side_supportive - side_adverse
        if side == "sell":
            side_net *= -1.0
        component_points["price_action"] = round(
            self._score_directional_component(
                "buy",
                side_net,
                float(getattr(cfg, "ENTRY_GATE_PRICE_ACTION_HARD_BLOCK_SCORE", 22.0)),
            )
            * float(getattr(cfg, "SETUP_QUALITY_PRICE_ACTION_WEIGHT", 10.0)),
            2,
        )
        score += component_points["price_action"]

        component_points["mode_fit"] = round(
            self._score_directional_component(
                "buy",
                mode_fit.get("score"),
                float(getattr(cfg, "SMART_PRICE_ACTION_MODE_SCORE_CAP", 14.0)),
            )
            * float(getattr(cfg, "SETUP_QUALITY_MODE_FIT_WEIGHT", 12.0)),
            2,
        )
        score += component_points["mode_fit"]

        volume_component = components.get("volume_confirmation") or {}
        component_points["volume"] = round(
            self._score_directional_component(
                side,
                volume_component.get("score"),
                float(getattr(cfg, "SMART_PRICE_ACTION_VOLUME_STRONG_SCORE", 6.0)),
            )
            * float(getattr(cfg, "SETUP_QUALITY_VOLUME_WEIGHT", 5.0)),
            2,
        )
        score += component_points["volume"]

        mtf_component = components.get("mtf_alignment") or {}
        component_points["mtf"] = round(
            self._score_directional_component(
                side,
                mtf_component.get("score"),
                float(getattr(cfg, "SMART_PRICE_ACTION_MTF_SCORE_CAP", 10.0)),
            )
            * float(getattr(cfg, "SETUP_QUALITY_MTF_WEIGHT", 5.0)),
            2,
        )
        score += component_points["mtf"]

        candle_component = components.get("candle_pattern") or {}
        component_points["candle"] = round(
            self._score_directional_component(side, candle_component.get("score"), 8.0)
            * float(getattr(cfg, "SETUP_QUALITY_CANDLE_WEIGHT", 4.0)),
            2,
        )
        score += component_points["candle"]

        adx = self._clamp(float(indicators.get("adx") or 0.0), 0.0, 60.0)
        adx_weight = float(getattr(cfg, "SETUP_QUALITY_ADX_WEIGHT", 4.0))
        if normalized_mode in {"long", "short", "scalp_pnl", "scalp_market"}:
            if adx > 0:
                adx_norm = (adx - 18.0) / 18.0
                component_points["adx"] = round(
                    self._clamp(adx_norm, -1.0, 1.0) * adx_weight,
                    2,
                )
                score += component_points["adx"]
        elif normalized_mode in {"neutral", "neutral_classic_bybit"} and adx > 0:
            adx_norm = (adx - 18.0) / 18.0
            component_points["adx"] = round(
                -self._clamp(adx_norm, 0.0, 1.0) * adx_weight,
                2,
            )
            score += component_points["adx"]

        atr_pct = abs(float(indicators.get("atr_pct") or 0.0))
        high_atr_pct = max(
            float(getattr(cfg, "SETUP_QUALITY_HIGH_ATR_PCT", 0.05) or 0.05),
            1e-9,
        )
        if atr_pct > 0:
            atr_penalty = self._clamp(atr_pct / high_atr_pct, 0.0, 1.5) - 0.5
            component_points["atr"] = round(
                -self._clamp(atr_penalty, 0.0, 1.0)
                * float(getattr(cfg, "SETUP_QUALITY_ATR_WEIGHT", 5.0)),
                2,
            )
            score += component_points["atr"]

        bbw_pct = abs(float(indicators.get("bbw_pct") or 0.0))
        high_bbw_pct = max(
            float(getattr(cfg, "SETUP_QUALITY_HIGH_BBW_PCT", 0.08) or 0.08),
            1e-9,
        )
        if bbw_pct > 0:
            bbw_penalty = self._clamp(bbw_pct / high_bbw_pct, 0.0, 1.5) - 0.5
            component_points["bbw"] = round(
                -self._clamp(bbw_penalty, 0.0, 1.0)
                * float(getattr(cfg, "SETUP_QUALITY_BBW_WEIGHT", 3.0)),
                2,
            )
            score += component_points["bbw"]

        velocity = float(indicators.get("price_velocity") or 0.0)
        velocity_reference = max(
            float(getattr(cfg, "AUTO_PILOT_VELOCITY_REFERENCE_PER_HOUR", 0.015) or 0.015),
            1e-9,
        )
        velocity_norm = self._clamp(velocity / velocity_reference, -1.0, 1.0)
        velocity_points = 0.0
        if side == "buy":
            velocity_points = velocity_norm
        elif side == "sell":
            velocity_points = -velocity_norm
        elif side == "neutral":
            velocity_points = -abs(velocity_norm)
        component_points["velocity"] = round(
            velocity_points * float(getattr(cfg, "SETUP_QUALITY_VELOCITY_WEIGHT", 5.0)),
            2,
        )
        score += component_points["velocity"]

        # ---------------------------------------------------------------------
        # NEW CORE METRICS (RSI, BB Position, EMA Extension)
        # ---------------------------------------------------------------------
        bb_result = {}
        if normalized_mode in ("long", "short"):
            # RSI Extension Penalty/Bonus
            rsi = float(indicators.get("rsi") or 50.0)
            if normalized_mode == "long":
                rsi_max = float(getattr(cfg, "ENTRY_GATE_RSI_LONG_MAX", 70.0))
                if rsi > rsi_max:
                    penalty = (rsi - rsi_max) / 10.0
                    component_points["rsi_ext"] = round(-self._clamp(penalty * 10.0, 0.0, 25.0), 2)
                elif rsi < 50.0:
                    bonus = ((50.0 - rsi) / 20.0) * 3.0
                    component_points["rsi_ext"] = round(self._clamp(bonus, 0.0, 5.0), 2)
            else:
                rsi_min = float(getattr(cfg, "ENTRY_GATE_RSI_SHORT_MIN", 30.0))
                if rsi < rsi_min:
                    penalty = (rsi_min - rsi) / 10.0
                    component_points["rsi_ext"] = round(-self._clamp(penalty * 10.0, 0.0, 25.0), 2)
                elif rsi > 50.0:
                    bonus = ((rsi - 50.0) / 20.0) * 3.0
                    component_points["rsi_ext"] = round(self._clamp(bonus, 0.0, 5.0), 2)
            if "rsi_ext" in component_points:
                score += component_points["rsi_ext"]

            # BB Position Penalty
            if hasattr(self, "indicator_service") and self.indicator_service:
                try:
                    bb_result = self.indicator_service.calculate_bollinger_bands(
                        symbol, interval=cfg.ENTRY_GATE_TIMEFRAME, period=20, std_dev=2.0
                    )
                except Exception:
                    pass
            if bb_result.get("success"):
                bb_pos = bb_result.get("bb_position", 50.0) / 100.0
                if normalized_mode == "long" and bb_pos > float(getattr(cfg, "ENTRY_GATE_BB_LONG_MAX", 0.95)):
                    penalty = (bb_pos - getattr(cfg, "ENTRY_GATE_BB_LONG_MAX", 0.95)) * 10.0
                    component_points["bb_ext"] = round(-self._clamp(penalty * 12.0, 0.0, 25.0), 2)
                    score += component_points["bb_ext"]
                elif normalized_mode == "short" and bb_pos < float(getattr(cfg, "ENTRY_GATE_BB_SHORT_MIN", 0.05)):
                    penalty = (getattr(cfg, "ENTRY_GATE_BB_SHORT_MIN", 0.05) - bb_pos) * 10.0
                    component_points["bb_ext"] = round(-self._clamp(penalty * 12.0, 0.0, 25.0), 2)
                    score += component_points["bb_ext"]

            # EMA Extension Penalty
            ema_21 = ema_21_value
            if ema_21 > 0 and close_price > 0 and price_vs_ema_pct is not None:
                if normalized_mode == "long":
                    ema_max = float(getattr(cfg, "ENTRY_GATE_EMA_LONG_MAX", 0.02))
                    if price_vs_ema_pct > ema_max:
                        penalty = (price_vs_ema_pct - ema_max) / 0.01
                        component_points["ema_ext"] = round(-self._clamp(penalty * 8.0, 0.0, 25.0), 2)
                        score += component_points["ema_ext"]
                elif normalized_mode == "short":
                    # For short, extending below the EMA negatively
                    # e.g. -3% is < -2%, we want the magnitude
                    ema_min = -float(getattr(cfg, "ENTRY_GATE_EMA_SHORT_MAX", 0.02))
                    if price_vs_ema_pct < ema_min:
                        penalty = (ema_min - price_vs_ema_pct) / 0.01  # e.g (-0.02 - -0.03)/0.01 = 1.0
                        component_points["ema_ext"] = round(-self._clamp(penalty * 8.0, 0.0, 25.0), 2)
                        score += component_points["ema_ext"]

        score = round(self._clamp(score, 0.0, 100.0), 2)
        quality_profile = self._classify_setup_quality(score)
        summary = self._summarize_quality_components(component_points)

        result.update(
            {
                "score": score,
                "normalized_score": round(score / 100.0, 4),
                "entry_allowed": score
                >= float(getattr(cfg, "SETUP_QUALITY_MIN_ENTRY_SCORE", 52.0)),
                "breakout_ready": score
                >= float(getattr(cfg, "SETUP_QUALITY_MIN_BREAKOUT_SCORE", 60.0)),
                "band": quality_profile["band"],
                "entry_aggressiveness_mult": quality_profile[
                    "entry_aggressiveness_mult"
                ],
                "grid_spacing_mult": quality_profile["grid_spacing_mult"],
                "grid_level_mult": quality_profile["grid_level_mult"],
                "summary": summary,
                "components": {
                    "price_action_context": price_action_context or {},
                    "price_action_side": side_result or {},
                    "mode_fit": mode_fit,
                    "supportive_level": supportive_level,
                    "adverse_level": adverse_level,
                    "indicators": {
                        "adx": indicators.get("adx"),
                        "atr_pct": indicators.get("atr_pct"),
                        "bbw_pct": indicators.get("bbw_pct"),
                        "price_velocity": indicators.get("price_velocity"),
                        "close": close_price or None,
                        "ema_21": ema_21_value or None,
                        "price_vs_ema_pct": price_vs_ema_pct,
                        "bb_position": bb_result.get("bb_position")
                        if bb_result.get("success")
                        else None,
                        "rsi": indicators.get("rsi"),
                    },
                },
                "component_points": component_points,
            }
        )

        if result["enabled"] and getattr(cfg, "SETUP_QUALITY_LOGGING_ENABLED", False):
            logger.debug(
                "[%s] SETUP_QUALITY mode=%s score=%.1f band=%s summary=%s",
                symbol,
                normalized_mode,
                score,
                result["band"],
                summary,
            )

        return result

    def classify_directional_entry_signal(
        self,
        *,
        mode: str,
        setup_quality: Optional[Dict[str, Any]] = None,
        breakout_confirmation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in {"long", "short"}:
            return {
                "code": "unsupported",
                "label": "Preview limited",
                "phase": "unknown",
                "detail": "Directional signal classification is unavailable for this mode.",
                "preferred": False,
                "late": False,
                "executable": False,
                "aligned": False,
                "extension_ratio": 0.0,
            }

        quality = dict(setup_quality or {})
        components = dict(quality.get("components") or {})
        component_points = dict(quality.get("component_points") or {})
        indicators = dict(components.get("indicators") or {})
        breakout = dict(breakout_confirmation or {})
        band = str(quality.get("band") or "").strip().lower()
        score = self._safe_float(quality.get("score"), 0.0)
        entry_allowed = bool(quality.get("entry_allowed", True))
        breakout_required = bool(breakout.get("required"))
        breakout_confirmed = bool(breakout.get("confirmed"))
        price_action_direction = str(
            (components.get("price_action_context") or {}).get("direction") or ""
        ).strip().lower()
        mode_fit_score = self._safe_float(
            (components.get("mode_fit") or {}).get("score"),
            0.0,
        )
        aligned_direction = "bullish" if normalized_mode == "long" else "bearish"
        aligned = price_action_direction == aligned_direction
        continuation_score = score >= float(
            getattr(cfg, "SETUP_QUALITY_CAUTION_SCORE", 60.0) or 60.0
        )
        strong_score = score >= float(
            getattr(cfg, "SETUP_QUALITY_STRONG_SCORE", 72.0) or 72.0
        )

        price_vs_ema_pct = abs(
            self._safe_float(indicators.get("price_vs_ema_pct"), 0.0)
        )
        bb_position = self._safe_float(indicators.get("bb_position"), None)
        bb_ratio = 0.0
        if bb_position is not None:
            bb_norm = bb_position / 100.0
            if normalized_mode == "long":
                bb_limit = max(
                    self._safe_float(getattr(cfg, "ENTRY_GATE_BB_LONG_MAX", 0.95), 0.95),
                    1e-9,
                )
                bb_ratio = bb_norm / bb_limit
            else:
                bb_limit = self._safe_float(
                    getattr(cfg, "ENTRY_GATE_BB_SHORT_MIN", 0.05),
                    0.05,
                )
                bb_ratio = (
                    (1.0 - bb_norm) / max(1.0 - bb_limit, 1e-9)
                    if bb_limit < 1.0
                    else 0.0
                )

        ema_limit = self._safe_float(
            getattr(
                cfg,
                "ENTRY_GATE_EMA_LONG_MAX" if normalized_mode == "long" else "ENTRY_GATE_EMA_SHORT_MAX",
                0.02,
            ),
            0.02,
        )
        ema_ratio = price_vs_ema_pct / max(abs(ema_limit), 1e-9)

        breakout_extension_ratio = 0.0
        breakout_extension_pct = self._safe_float(
            breakout.get("no_chase_extension_pct"),
            0.0,
        )
        breakout_extension_limit = self._safe_float(
            getattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_PCT", 0.006),
            0.006,
        )
        if breakout_extension_pct > 0 and breakout_extension_limit > 0:
            breakout_extension_ratio = breakout_extension_pct / breakout_extension_limit

        extension_ratio = round(
            max(0.0, ema_ratio, bb_ratio, breakout_extension_ratio),
            4,
        )

        # Capped ratio for late classification — breakout extension alone should not cause late.
        # The no-chase guard (no_chase_blocked) already blocks overly extended breakout entries.
        breakout_late_cap = self._safe_float(
            getattr(cfg, "BREAKOUT_EXTENSION_LATE_RATIO_CAP", 0.6), 0.6,
        )
        capped_breakout_ratio = min(breakout_extension_ratio, breakout_late_cap)
        late_extension_ratio = round(
            max(0.0, ema_ratio, bb_ratio, capped_breakout_ratio), 4,
        )

        mildly_extended = extension_ratio >= 0.6
        late = late_extension_ratio >= 0.85
        price_action_component = self._safe_float(
            component_points.get("price_action"),
            0.0,
        )
        supportive_structure_component = self._safe_float(
            component_points.get("supportive_structure"),
            0.0,
        )
        volume_component = self._safe_float(
            component_points.get("volume"),
            0.0,
        )
        mtf_component = self._safe_float(
            component_points.get("mtf"),
            0.0,
        )

        result = {
            "code": "continuation_entry",
            "label": "Continuation entry",
            "phase": "continuation",
            "detail": "Executable, but momentum is already underway.",
            "preferred": False,
            "late": late,
            "executable": entry_allowed and not bool(breakout.get("no_chase_blocked")),
            "aligned": aligned,
            "extension_ratio": extension_ratio,
        }

        if breakout_required and breakout_confirmed:
            result.update(
                {
                    "code": "confirmed_breakout" if not late else "late_continuation",
                    "label": (
                        "Confirmed breakout"
                        if not late
                        else "Late breakout continuation"
                    ),
                    "phase": "breakout" if not late else "late",
                    "detail": (
                        "Breakout confirmation is in place and still inside no-chase bounds."
                        if not late
                        else "Breakout confirmed, but the move is already extended."
                    ),
                    "preferred": not late,
                    "late": late,
                }
            )
            return result

        strong_continuation_promotion = bool(
            getattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_PROMOTION_ENABLED", False)
        )
        strong_continuation_score = score >= float(
            getattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_SCORE_MIN", 74.0)
            or 74.0
        )
        strong_continuation_mode_fit = mode_fit_score >= float(
            getattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_MODE_FIT_MIN", 4.0)
            or 4.0
        )
        strong_continuation_extension = extension_ratio <= float(
            getattr(
                cfg,
                "ENTRY_READINESS_STRONG_CONTINUATION_EXTENSION_RATIO_MAX",
                0.45,
            )
            or 0.45
        )
        strong_continuation_price_action = price_action_component >= float(
            getattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_PRICE_ACTION_MIN", 2.0)
            or 2.0
        )
        strong_continuation_structure = supportive_structure_component >= float(
            getattr(
                cfg,
                "ENTRY_READINESS_STRONG_CONTINUATION_SUPPORTIVE_STRUCTURE_MIN",
                1.0,
            )
            or 1.0
        )
        strong_continuation_confirmation = max(
            volume_component,
            mtf_component,
        ) >= float(
            getattr(cfg, "ENTRY_READINESS_STRONG_CONTINUATION_CONFIRMATION_MIN", 1.0)
            or 1.0
        )
        if (
            strong_continuation_promotion
            and not breakout_required
            and strong_continuation_score
            and strong_continuation_mode_fit
            and strong_continuation_extension
            and strong_continuation_price_action
            and strong_continuation_confirmation
            and (aligned or strong_continuation_structure)
            and not late
        ):
            result.update(
                {
                    "code": "good_continuation",
                    "label": "Good continuation entry",
                    "phase": "continuation",
                    "detail": "Strong continuation remains tradable before the move gets extended.",
                    "preferred": True,
                    "late": False,
                }
            )
            return self._attach_experiment(
                result,
                tag="exp_strong_continuation_promotion_used",
                details={
                    "score": round(score, 4),
                    "mode_fit_score": round(mode_fit_score, 4),
                    "extension_ratio": round(extension_ratio, 6),
                    "price_action_component": round(price_action_component, 4),
                    "supportive_structure_component": round(
                        supportive_structure_component,
                        4,
                    ),
                    "confirmation_component": round(
                        max(volume_component, mtf_component),
                        4,
                    ),
                },
            )

        if strong_score and aligned and mode_fit_score >= float(
            getattr(cfg, "ENTRY_READINESS_STRONG_DIRECTIONAL_MODE_FIT_MIN", 2.5) or 2.5
        ) and not mildly_extended:
            result.update(
                {
                    "code": "early_entry",
                    "label": "Early entry window",
                    "phase": "early",
                    "detail": "Strong directional confluence with limited extension.",
                    "preferred": True,
                    "late": False,
                }
            )
            return result

        if continuation_score and aligned and not late:
            result.update(
                {
                    "code": "good_continuation",
                    "label": "Good continuation entry",
                    "phase": "continuation",
                    "detail": "Trend continuation remains tradable, but this is not an early pullback entry.",
                    "preferred": True,
                    "late": False,
                }
            )
            return result

        if late:
            result.update(
                {
                    "code": "late_continuation",
                    "label": "Late continuation",
                    "phase": "late",
                    "detail": "Move is already extended; waiting for a pullback is safer.",
                    "preferred": False,
                    "late": True,
                }
            )
            return result

        if not aligned and band == "strong":
            result["detail"] = "Executable, but directional confluence is not fully aligned."
        elif band == "good":
            result["detail"] = "Executable, but this remains a continuation entry rather than an early setup."
        return result

    def check_breakout_confirmation(
        self,
        symbol: str,
        mode: str,
        current_price: Optional[float] = None,
        structure: Optional[Dict[str, Any]] = None,
        price_action_context: Optional[Dict[str, Any]] = None,
        setup_quality: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        result: Dict[str, Any] = {
            "required": False,
            "confirmed": True,
            "reason": "breakout confirmation disabled",
            "level_price": None,
            "level_type": None,
            "required_close": None,
            "confirm_candles": int(getattr(cfg, "BREAKOUT_CONFIRM_CANDLES", 2) or 2),
            "volume_confirmed": None,
            "mtf_confirmed": None,
            "block_code": None,
            "no_chase_filtered": False,
            "no_chase_blocked": False,
            "no_chase_reason": None,
            "no_chase_reference_price": None,
            "no_chase_extension_pct": 0.0,
            "no_chase_extension_atr_mult": None,
        }

        if not getattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", False):
            return result
        if (
            getattr(cfg, "BREAKOUT_CONFIRM_DIRECTIONAL_ONLY", True)
            and normalized_mode not in {"long", "short"}
        ):
            return result

        result["required"] = True
        side = self._mode_to_side(normalized_mode)
        structure = structure or self._get_structure_levels(
            symbol,
            current_price=current_price,
        )
        price_action_context = price_action_context or self.get_price_action_context(
            symbol=symbol,
            current_price=current_price,
        )
        setup_quality = setup_quality or self.get_setup_quality(
            symbol=symbol,
            mode=normalized_mode,
            current_price=current_price,
            structure=structure,
            price_action_context=price_action_context,
        )

        if not setup_quality.get("breakout_ready", True):
            result["confirmed"] = False
            result["reason"] = (
                "Setup quality "
                f"{setup_quality.get('score', 0):.1f} below breakout minimum "
                f"{float(getattr(cfg, 'SETUP_QUALITY_MIN_BREAKOUT_SCORE', 60.0)):.1f}"
            )
            return result

        market_structure = ((price_action_context or {}).get("components") or {}).get(
            "market_structure",
            {},
        )
        structure_details = market_structure.get("details") or {}
        candidate_levels: List[Dict[str, Any]] = []
        if normalized_mode == "long":
            resistance = (structure or {}).get("nearest_resistance")
            if resistance and float(resistance.get("price") or 0.0) > 0:
                candidate_levels.append(
                    {
                        "type": "resistance",
                        "price": float(resistance.get("price") or 0.0),
                    }
                )
            swing_high = structure_details.get("last_swing_high")
            if swing_high and len(swing_high) >= 2:
                candidate_levels.append(
                    {
                        "type": "swing_high",
                        "price": float(swing_high[1] or 0.0),
                    }
                )
            breakout_level = max(
                (level for level in candidate_levels if level["price"] > 0.0),
                key=lambda level: level["price"],
                default=None,
            )
        else:
            support = (structure or {}).get("nearest_support")
            if support and float(support.get("price") or 0.0) > 0:
                candidate_levels.append(
                    {
                        "type": "support",
                        "price": float(support.get("price") or 0.0),
                    }
                )
            swing_low = structure_details.get("last_swing_low")
            if swing_low and len(swing_low) >= 2:
                candidate_levels.append(
                    {
                        "type": "swing_low",
                        "price": float(swing_low[1] or 0.0),
                    }
                )
            breakout_level = min(
                (level for level in candidate_levels if level["price"] > 0.0),
                key=lambda level: level["price"],
                default=None,
            )

        if not breakout_level:
            result["confirmed"] = False
            result["reason"] = "No structure breakout level available"
            return result

        candles = self._get_closed_candles(
            symbol=symbol,
            interval=cfg.ENTRY_GATE_TIMEFRAME,
            limit=max(40, result["confirm_candles"] + 5),
        )
        if len(candles) < result["confirm_candles"]:
            result["confirmed"] = False
            result["reason"] = "Insufficient closed candles for breakout confirmation"
            return result

        recent_candles = candles[-result["confirm_candles"] :]
        level_price = float(breakout_level["price"] or 0.0)
        buffer_pct = float(getattr(cfg, "BREAKOUT_CONFIRM_BUFFER_PCT", 0.0015) or 0.0015)
        if normalized_mode == "long":
            required_close = level_price * (1.0 + buffer_pct)
            candle_confirmed = all(
                float(candle.get("close") or 0.0) >= required_close
                for candle in recent_candles
            )
        else:
            required_close = level_price * (1.0 - buffer_pct)
            candle_confirmed = all(
                float(candle.get("close") or 0.0) <= required_close
                for candle in recent_candles
            )

        volume_component = ((price_action_context or {}).get("components") or {}).get(
            "volume_confirmation",
            {},
        )
        volume_score = float(volume_component.get("score") or 0.0)
        volume_confirmed = volume_score > 0 if normalized_mode == "long" else volume_score < 0
        if not getattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_VOLUME", True):
            volume_confirmed = True

        mtf_component = ((price_action_context or {}).get("components") or {}).get(
            "mtf_alignment",
            {},
        )
        mtf_score = float(mtf_component.get("score") or 0.0)
        mtf_confirmed = mtf_score > 0 if normalized_mode == "long" else mtf_score < 0
        if not getattr(cfg, "BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN", False):
            mtf_confirmed = True

        result.update(
            {
                "confirmed": bool(candle_confirmed and volume_confirmed and mtf_confirmed),
                "reason": "Breakout confirmed"
                if (candle_confirmed and volume_confirmed and mtf_confirmed)
                else "Breakout not confirmed",
                "level_price": round(level_price, 8),
                "level_type": breakout_level["type"],
                "required_close": round(required_close, 8),
                "volume_confirmed": volume_confirmed,
                "mtf_confirmed": mtf_confirmed,
            }
        )
        if not candle_confirmed:
            result["reason"] = (
                f"Need {result['confirm_candles']} closed candles beyond {required_close:.6f}"
            )
        elif not volume_confirmed:
            result["reason"] = "Breakout volume confirmation missing"
        elif not mtf_confirmed:
            result["reason"] = "Breakout MTF alignment missing"
        elif getattr(cfg, "BREAKOUT_NO_CHASE_FILTER_ENABLED", False):
            current_extension_price = self._safe_float(
                current_price,
                self._safe_float(recent_candles[-1].get("close"), 0.0),
            )
            reference_price = float(required_close or level_price or 0.0)
            extension = 0.0
            if current_extension_price > 0:
                if normalized_mode == "long":
                    extension = max(0.0, current_extension_price - reference_price)
                else:
                    extension = max(0.0, reference_price - current_extension_price)

            extension_pct = (
                extension / max(reference_price, 1e-9) if reference_price > 0 else 0.0
            )
            atr_pct = self._safe_float(
                (((setup_quality or {}).get("components") or {}).get("indicators") or {}).get(
                    "atr_pct"
                ),
                0.0,
            )
            extension_atr_mult = None
            if atr_pct > 0:
                extension_atr_mult = extension_pct / max(atr_pct, 1e-9)

            max_extension_pct = max(
                0.0,
                float(getattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_PCT", 0.004) or 0.0),
            )
            max_extension_atr_mult = max(
                0.0,
                float(
                    getattr(cfg, "BREAKOUT_NO_CHASE_MAX_EXTENSION_ATR_MULT", 0.8) or 0.0
                ),
            )
            too_far_pct = max_extension_pct > 0 and extension_pct > max_extension_pct
            too_far_atr = (
                extension_atr_mult is not None
                and max_extension_atr_mult > 0
                and extension_atr_mult > max_extension_atr_mult
            )

            result["no_chase_reference_price"] = round(reference_price, 8)
            result["no_chase_extension_pct"] = round(extension_pct, 6)
            result["no_chase_extension_atr_mult"] = (
                round(extension_atr_mult, 4)
                if extension_atr_mult is not None
                else None
            )

            if too_far_pct or too_far_atr:
                result["confirmed"] = False
                result["block_code"] = "BREAKOUT_CHASE_TOO_FAR"
                result["no_chase_filtered"] = True
                result["no_chase_blocked"] = True
                reason_parts = [
                    "Breakout entry blocked: no-chase extension too far from breakout confirmation"
                ]
                reason_parts.append(f"extension_pct={extension_pct * 100:.2f}%")
                if extension_atr_mult is not None:
                    reason_parts.append(f"extension_atr={extension_atr_mult:.2f}x")
                result["reason"] = " ".join(reason_parts)
                result["no_chase_reason"] = result["reason"]
                if getattr(cfg, "BREAKOUT_NO_CHASE_LOGGING_ENABLED", False):
                    logger.info(
                        "[%s] BREAKOUT no-chase blocked (%s): level=%.6f ref=%.6f current=%.6f ext_pct=%.4f ext_atr=%s",
                        symbol,
                        normalized_mode,
                        level_price,
                        reference_price,
                        current_extension_price or 0.0,
                        extension_pct,
                        f"{extension_atr_mult:.2f}x"
                        if extension_atr_mult is not None
                        else "n/a",
                    )
        return result

    def check_breakout_invalidation(
        self,
        symbol: str,
        mode: str,
        reference_level: float,
        reference_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        confirm_candles = max(
            1,
            int(getattr(cfg, "BREAKOUT_INVALIDATION_CONFIRM_CANDLES", 2) or 2),
        )
        reclaim_buffer_pct = max(
            self._safe_float(
                getattr(cfg, "BREAKOUT_INVALIDATION_RECLAIM_BUFFER_PCT", 0.0010),
                0.0010,
            ),
            0.0,
        )
        result: Dict[str, Any] = {
            "eligible": False,
            "invalidated": False,
            "reason": "breakout invalidation disabled",
            "reference_level": None,
            "reference_type": reference_type,
            "confirm_candles": confirm_candles,
            "reclaim_buffer_pct": reclaim_buffer_pct,
            "required_close": None,
            "latest_close": None,
        }

        if not getattr(cfg, "BREAKOUT_INVALIDATION_EXIT_ENABLED", False):
            return result
        if normalized_mode not in {"long", "short"}:
            return result

        safe_reference_level = self._safe_float(reference_level, 0.0)
        if safe_reference_level <= 0:
            result["reason"] = "No breakout reference level available"
            return result

        candles = self._get_closed_candles(
            symbol=symbol,
            interval=cfg.ENTRY_GATE_TIMEFRAME,
            limit=max(40, confirm_candles + 5),
        )
        if len(candles) < confirm_candles:
            result["eligible"] = True
            result["reference_level"] = round(safe_reference_level, 8)
            result["reason"] = "Insufficient closed candles for breakout invalidation"
            return result

        recent_candles = candles[-confirm_candles:]
        latest_close = self._safe_float(recent_candles[-1].get("close"), 0.0)
        if normalized_mode == "long":
            required_close = safe_reference_level * (1.0 - reclaim_buffer_pct)
            invalidated = all(
                self._safe_float(candle.get("close"), 0.0) <= required_close
                for candle in recent_candles
            )
            reason = (
                "Breakout invalidation detected: reclaim below broken resistance"
                if invalidated
                else "Breakout still holding above broken resistance"
            )
        else:
            required_close = safe_reference_level * (1.0 + reclaim_buffer_pct)
            invalidated = all(
                self._safe_float(candle.get("close"), 0.0) >= required_close
                for candle in recent_candles
            )
            reason = (
                "Breakout invalidation detected: reclaim above broken support"
                if invalidated
                else "Breakout still holding below broken support"
            )

        result.update(
            {
                "eligible": True,
                "invalidated": bool(invalidated),
                "reason": reason,
                "reference_level": round(safe_reference_level, 8),
                "required_close": round(required_close, 8),
                "latest_close": round(latest_close, 8) if latest_close > 0 else None,
            }
        )
        return result

    def check_side_open(
        self,
        symbol: str,
        side: str,
        current_price: Optional[float] = None,
        indicators: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Check whether opening a specific side is safe with respect to nearby
        adverse market structure.
        """
        normalized_side = (side or "").lower()
        if normalized_side not in ("buy", "sell"):
            return {
                "suitable": True,
                "reason": f"Unsupported side {side}",
                "blocked_by": [],
                "scores": {},
                "thresholds": {},
                "side": side,
            }

        if not (
            cfg.ENTRY_GATE_SR_ENABLED or getattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False)
        ):
            return {
                "suitable": True,
                "reason": "Side gate disabled",
                "blocked_by": [],
                "scores": {},
                "thresholds": {},
                "side": side,
            }

        if current_price is None and indicators:
            try:
                current_price = float(indicators.get("close") or 0.0)
            except (TypeError, ValueError):
                current_price = 0.0

        structure = self._get_structure_levels(symbol, current_price=current_price)
        nearest_support = structure.get("nearest_support")
        nearest_resistance = structure.get("nearest_resistance")

        adverse_level = nearest_resistance if normalized_side == "buy" else nearest_support
        blocked_by: List[str] = []
        reasons: List[str] = []

        if cfg.ENTRY_GATE_SR_ENABLED and adverse_level:
            strength = int(adverse_level.get("strength") or 0)
            distance_pct = float(adverse_level.get("distance_pct") or 0.0)
            if (
                strength >= cfg.ENTRY_GATE_SR_MIN_STRENGTH
                and distance_pct <= cfg.ENTRY_GATE_SR_PROXIMITY_PCT
            ):
                if normalized_side == "buy":
                    blocked_by.append("RESISTANCE_NEARBY")
                    reasons.append(
                        "Resistance "
                        f"{distance_pct * 100:.2f}% away @ {adverse_level.get('price', 0):.4f} "
                        f"(strength={strength})"
                    )
                else:
                    blocked_by.append("SUPPORT_NEARBY")
                    reasons.append(
                        "Support "
                        f"{distance_pct * 100:.2f}% away @ {adverse_level.get('price', 0):.4f} "
                        f"(strength={strength})"
                    )

        price_action_context: Optional[Dict[str, Any]] = None
        price_action_result: Optional[Dict[str, Any]] = None
        if getattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False):
            try:
                price_action_context = self.get_price_action_context(
                    symbol=symbol,
                    current_price=current_price,
                )
                price_action_result = self.evaluate_price_action_side(
                    symbol=symbol,
                    side=side,
                    current_price=current_price,
                    context=price_action_context,
                )
            except Exception as exc:
                logger.debug("[%s] Price-action gate analysis failed: %s", symbol, exc)
                price_action_context = None
                price_action_result = None

        if price_action_result:
            if price_action_result.get("blocked_by"):
                blocked_by.extend(price_action_result["blocked_by"])
                reasons.append(price_action_result.get("reason", "price action blocked"))

        scores = {
            "current_price": current_price,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "adverse_level": adverse_level,
        }
        if price_action_context:
            scores["price_action"] = price_action_context
        if price_action_result:
            scores["price_action_side"] = price_action_result
        thresholds = {
            "sr_proximity_pct": cfg.ENTRY_GATE_SR_PROXIMITY_PCT,
            "sr_min_strength": cfg.ENTRY_GATE_SR_MIN_STRENGTH,
        }
        if getattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False):
            thresholds["price_action_block_score"] = getattr(
                cfg,
                "ENTRY_GATE_PRICE_ACTION_BLOCK_SCORE",
                16.0,
            )
            thresholds["price_action_hard_block_score"] = getattr(
                cfg,
                "ENTRY_GATE_PRICE_ACTION_HARD_BLOCK_SCORE",
                22.0,
            )

        return {
            "suitable": len(blocked_by) == 0,
            "reason": "; ".join(reasons) if reasons else "Side entry conditions favorable",
            "blocked_by": blocked_by,
            "scores": scores,
            "thresholds": thresholds,
            "side": side,
        }

    def check_entry(
        self,
        symbol: str,
        mode: str,
        indicators: Optional[Dict[str, Any]] = None,
        bot: Optional[Dict[str, Any]] = None,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Check if entry conditions are favorable for the given mode.

        Returns a combined result from the legacy momentum gate and the new
        directional support/resistance check.
        """
        if mode not in ("long", "short"):
            return {
                "suitable": True,
                "reason": f"Gate only applies to long/short (mode={mode})",
                "blocked_by": [],
                "scores": {},
                "thresholds": {},
                "mode": mode,
            }

        directional_gate_active = self._is_directional_entry_gate_active(bot)
        if not directional_gate_active:
            return {
                "suitable": True,
                "reason": "Directional entry gate disabled",
                "blocked_by": [],
                "scores": {"gate_active": False},
                "thresholds": {},
                "mode": mode,
            }

        breakout_mode_enabled = bool(
            directional_gate_active
            and getattr(cfg, "BREAKOUT_CONFIRMED_ENTRY_ENABLED", False)
            and bool((bot or {}).get("breakout_confirmed_entry", False))
        )

        thresholds: Dict[str, Any] = {
            "sr_proximity_pct": cfg.ENTRY_GATE_SR_PROXIMITY_PCT,
            "sr_min_strength": cfg.ENTRY_GATE_SR_MIN_STRENGTH,
        }
        if getattr(cfg, "ENTRY_GATE_PRICE_ACTION_ENABLED", False):
            thresholds["price_action_block_score"] = getattr(
                cfg, "ENTRY_GATE_PRICE_ACTION_BLOCK_SCORE", 16.0
            )
        if mode == "long":
            thresholds.update(
                {
                    "rsi_max": cfg.ENTRY_GATE_RSI_LONG_MAX,
                    "bb_max": cfg.ENTRY_GATE_BB_LONG_MAX,
                    "ema_max": cfg.ENTRY_GATE_EMA_LONG_MAX,
                }
            )
        else:
            thresholds.update(
                {
                    "rsi_min": cfg.ENTRY_GATE_RSI_SHORT_MIN,
                    "bb_min": cfg.ENTRY_GATE_BB_SHORT_MIN,
                    "ema_max": cfg.ENTRY_GATE_EMA_SHORT_MAX,
                }
            )

        if indicators is None:
            try:
                indicators = self.indicator_service.compute_indicators(
                    symbol, interval=cfg.ENTRY_GATE_TIMEFRAME, limit=100
                )
            except Exception as exc:
                logger.warning("[%s] Failed to fetch indicators: %s", symbol, exc)
                indicators = {}

        bb_position = None
        if cfg.ENTRY_GATE_ENABLED:
            try:
                bb_result = self.indicator_service.calculate_bollinger_bands(
                    symbol, interval=cfg.ENTRY_GATE_TIMEFRAME, period=20, std_dev=2.0
                )
                if bb_result.get("success"):
                    bb_position = bb_result.get("bb_position")
            except Exception as exc:
                logger.debug("[%s] Failed to fetch BB position: %s", symbol, exc)

        rsi = indicators.get("rsi") if indicators else None
        ema_21 = indicators.get("ema_21") if indicators else None
        indicator_close = indicators.get("close") if indicators else None
        execution_price = current_price
        if execution_price is None or float(execution_price or 0.0) <= 0:
            try:
                execution_price = float(indicator_close or 0.0)
            except (TypeError, ValueError):
                execution_price = 0.0
        close = execution_price

        price_vs_ema_pct = None
        if ema_21 and close and ema_21 > 0:
            price_vs_ema_pct = (close - ema_21) / ema_21

        scores: Dict[str, Any] = {
            "rsi": rsi,
            "bb_position": bb_position,
            "price_vs_ema_pct": price_vs_ema_pct,
            "close": close,
            "indicator_close": indicator_close,
            "ema_21": ema_21,
            "breakout_mode_enabled": breakout_mode_enabled,
        }
        blocked_by: List[str] = []
        reasons: List[str] = []

        if cfg.ENTRY_GATE_ENABLED:
            if mode == "long":
                if rsi is not None and rsi > thresholds["rsi_max"]:
                    logger.debug(f"[{symbol}] RSI={rsi:.1f}>{thresholds['rsi_max']} (overbought, scoring penalty instead of hard block)")
                if bb_position is not None and bb_position > thresholds["bb_max"] * 100:
                    logger.debug(f"[{symbol}] BB={bb_position:.0f}%>{thresholds['bb_max']*100:.0f}% (near upper band, scoring penalty instead of hard block)")
                if (
                    price_vs_ema_pct is not None
                    and price_vs_ema_pct > thresholds["ema_max"]
                ):
                    logger.debug(f"[{symbol}] Price {price_vs_ema_pct * 100:.1f}% above EMA21 (extended, scoring penalty instead of hard block)")
            else:
                if rsi is not None and rsi < thresholds["rsi_min"]:
                    logger.debug(f"[{symbol}] RSI={rsi:.1f}<{thresholds['rsi_min']} (oversold, scoring penalty instead of hard block)")
                if bb_position is not None and bb_position < thresholds["bb_min"] * 100:
                    logger.debug(f"[{symbol}] BB={bb_position:.0f}%<{thresholds['bb_min']*100:.0f}% (near lower band, scoring penalty instead of hard block)")
                if (
                    price_vs_ema_pct is not None
                    and price_vs_ema_pct < -thresholds["ema_max"]
                ):
                    logger.debug(f"[{symbol}] Price {abs(price_vs_ema_pct) * 100:.1f}% below EMA21 (extended, scoring penalty instead of hard block)")

        structure_result = self.check_side_open(
            symbol=symbol,
            side="Buy" if mode == "long" else "Sell",
            current_price=close,
            indicators=indicators,
        )
        structure_scores = structure_result.get("scores", {})
        if structure_scores:
            scores["structure_result"] = structure_result
            scores["nearest_support"] = structure_scores.get("nearest_support")
            scores["nearest_resistance"] = structure_scores.get("nearest_resistance")
            scores["adverse_level"] = structure_scores.get("adverse_level")
            if structure_scores.get("price_action") is not None:
                scores["price_action"] = structure_scores.get("price_action")
            if structure_scores.get("price_action_side") is not None:
                scores["price_action_side"] = structure_scores.get("price_action_side")

        setup_quality = self.get_setup_quality(
            symbol=symbol,
            mode=mode,
            current_price=close,
            indicators=indicators,
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
                if str(code or "").strip().upper()
                in {"RESISTANCE_NEARBY", "SUPPORT_NEARBY"}
            ],
        )
        scores["setup_quality"] = setup_quality
        if setup_quality.get("enabled"):
            thresholds["setup_quality_min_entry_score"] = getattr(
                cfg,
                "SETUP_QUALITY_MIN_ENTRY_SCORE",
                52.0,
            )
            thresholds["setup_quality_min_breakout_score"] = getattr(
                cfg,
                "SETUP_QUALITY_MIN_BREAKOUT_SCORE",
                60.0,
            )
            if not setup_quality.get("entry_allowed", True):
                blocked_by.append("SETUP_QUALITY_LOW")
                reasons.append(
                    "Setup quality "
                    f"{float(setup_quality.get('score') or 0.0):.2f} below "
                    f"{float(thresholds['setup_quality_min_entry_score']):.1f}"
                )

        breakout_confirmation = {
            "required": False,
            "confirmed": True,
            "reason": "breakout confirmation disabled",
        }
        if breakout_mode_enabled:
            breakout_confirmation = self.check_breakout_confirmation(
                symbol=symbol,
                mode=mode,
                current_price=close,
                structure={
                    "nearest_support": structure_scores.get("nearest_support"),
                    "nearest_resistance": structure_scores.get("nearest_resistance"),
                    "adverse_level": structure_scores.get("adverse_level"),
                },
                price_action_context=structure_scores.get("price_action"),
                setup_quality=setup_quality,
            )
            scores["breakout_confirmation"] = breakout_confirmation
            thresholds["breakout_confirm_candles"] = getattr(
                cfg, "BREAKOUT_CONFIRM_CANDLES", 2
            )
            thresholds["breakout_confirm_buffer_pct"] = getattr(
                cfg, "BREAKOUT_CONFIRM_BUFFER_PCT", 0.0015
            )
            thresholds["breakout_no_chase_filter_enabled"] = bool(
                getattr(cfg, "BREAKOUT_NO_CHASE_FILTER_ENABLED", False)
            )
            if thresholds["breakout_no_chase_filter_enabled"]:
                thresholds["breakout_no_chase_max_extension_pct"] = getattr(
                    cfg,
                    "BREAKOUT_NO_CHASE_MAX_EXTENSION_PCT",
                    0.004,
                )
                thresholds["breakout_no_chase_max_extension_atr_mult"] = getattr(
                    cfg,
                    "BREAKOUT_NO_CHASE_MAX_EXTENSION_ATR_MULT",
                    0.8,
                )
            if not breakout_confirmation.get("confirmed", True):
                blocked_by.append(
                    breakout_confirmation.get("block_code") or "BREAKOUT_NOT_CONFIRMED"
                )
                reasons.append(
                    breakout_confirmation.get("reason", "Breakout confirmation required")
                )
        entry_signal = self.classify_directional_entry_signal(
            mode=mode,
            setup_quality=setup_quality,
            breakout_confirmation=breakout_confirmation,
        )
        structure_result = self._maybe_relax_directional_structure_block(
            mode=mode,
            side="Buy" if mode == "long" else "Sell",
            structure_result=structure_result,
            setup_quality=setup_quality,
            breakout_confirmation=breakout_confirmation,
            entry_signal=entry_signal,
        )
        scores["entry_signal"] = entry_signal
        scores["structure_result"] = structure_result
        if structure_result.get("blocked_by"):
            blocked_by.extend(structure_result["blocked_by"])
            reasons.append(structure_result["reason"])

        suitable = len(blocked_by) == 0
        reason = "; ".join(reasons) if reasons else "Entry conditions favorable"

        # Logging moved to caller (_evaluate_directional_entry_gate) to
        # enable reason-change deduplication and reduce log spam.

        experiment_tags = self._normalize_experiment_tags(
            entry_signal.get("experiment_tags"),
            structure_result.get("experiment_tags"),
        )
        experiment_details = self._merge_experiment_details(
            entry_signal.get("experiment_details"),
            structure_result.get("experiment_details"),
        )

        payload = {
            "suitable": suitable,
            "reason": reason,
            "blocked_by": blocked_by,
            "scores": scores,
            "thresholds": thresholds,
            "mode": mode,
        }
        if experiment_tags:
            payload["experiment_tags"] = experiment_tags
        if experiment_details:
            payload["experiment_details"] = experiment_details
        return payload

    def should_recheck(self, bot: Dict[str, Any]) -> bool:
        blocked_until = bot.get("_entry_gate_blocked_until", 0)
        now = self._get_now_ts()
        return now >= blocked_until

    def set_blocked(self, bot: Dict[str, Any], reason: str) -> None:
        now = self._get_now_ts()
        bot["_entry_gate_blocked"] = True
        bot["_entry_gate_blocked_until"] = now + cfg.ENTRY_GATE_RECHECK_SECONDS
        bot["_entry_gate_blocked_reason"] = reason

    def clear_blocked(self, bot: Dict[str, Any]) -> None:
        bot["_entry_gate_blocked"] = False
        bot.pop("_entry_gate_blocked_until", None)
        bot.pop("_entry_gate_blocked_reason", None)

    def get_status(self, bot: Dict[str, Any]) -> Dict[str, Any]:
        now = self._get_now_ts()
        blocked_until = bot.get("_entry_gate_blocked_until", 0)
        blocked = bot.get("_entry_gate_blocked", False) and now < blocked_until

        return {
            "blocked": blocked,
            "reason": bot.get("_entry_gate_blocked_reason", ""),
            "blocked_until": blocked_until,
            "time_remaining": max(0, blocked_until - now) if blocked else 0,
        }
