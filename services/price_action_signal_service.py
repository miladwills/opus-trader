"""
Price Action Signal Service.

Builds short-horizon price-action context that can be reused by both
Auto-Pilot candidate ranking and the live entry gate.
"""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

import config.strategy_config as cfg
from services.price_prediction_service import (
    PriceActionAnalyzer,
    SupportResistanceDetector,
    TimeframeAligner,
)

logger = logging.getLogger(__name__)


class PriceActionSignalService:
    """
    Shared smart price-action context used by both picker and runtime gates.

    Signals added here should remain lightweight and deterministic:
    - market structure break
    - liquidity sweep + wick rejection
    - multi-timeframe alignment
    - volume confirmation
    - candle-pattern scoring
    """

    def __init__(self, indicator_service, sr_detector: Optional[SupportResistanceDetector] = None):
        self.indicator_service = indicator_service
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 30
        self._sr_detector = sr_detector or SupportResistanceDetector(
            touch_threshold_pct=cfg.SR_TOUCH_THRESHOLD_PCT,
            lookback=cfg.SR_LOOKBACK_CANDLES,
        )
        self._structure_analyzer = PriceActionAnalyzer(
            swing_threshold=cfg.SMART_PRICE_ACTION_SWING_THRESHOLD
        )
        self._timeframe_aligner = TimeframeAligner(
            indicator_service=indicator_service,
            timeframes=list(cfg.SMART_PRICE_ACTION_MTF_TIMEFRAMES),
            weights=dict(cfg.SMART_PRICE_ACTION_MTF_WEIGHTS),
        )

    def _get_now_ts(self) -> float:
        return time.time()

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
    def _signed_score(direction: Optional[str], points: float) -> float:
        if direction == "bullish":
            return float(points)
        if direction == "bearish":
            return -float(points)
        return 0.0

    @staticmethod
    def _build_component(
        name: str,
        signal: str = "neutral",
        score: float = 0.0,
        summary: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "signal": signal,
            "score": round(float(score), 2),
            "summary": summary,
            "reason": summary,
            "details": details or {},
        }

    @staticmethod
    def _candle_metrics(candle: Dict[str, Any]) -> Dict[str, float]:
        open_price = float(candle.get("open") or 0.0)
        close_price = float(candle.get("close") or 0.0)
        high = float(candle.get("high") or 0.0)
        low = float(candle.get("low") or 0.0)
        body = abs(close_price - open_price)
        total_range = max(0.0, high - low)
        upper_wick = max(0.0, high - max(open_price, close_price))
        lower_wick = max(0.0, min(open_price, close_price) - low)
        return {
            "open": open_price,
            "close": close_price,
            "high": high,
            "low": low,
            "body": body,
            "range": total_range,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
        }

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def _get_closed_candles(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        candles = self.indicator_service.get_ohlcv(symbol, interval=interval, limit=limit) or []
        if len(candles) > 1 and cfg.PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES:
            return candles[:-1]
        return candles

    def _detect_candle_pattern(
        self,
        candles: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        detector = getattr(self.indicator_service, "_detect_candle_patterns", None)
        if callable(detector):
            try:
                return detector(candles)
            except Exception as exc:
                logger.debug("Pattern detection failed: %s", exc)
        return None

    def _analyze_market_structure(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if len(candles) < 25:
            return self._build_component(
                name="market_structure",
                summary="insufficient candles",
            )

        structure = self._structure_analyzer.analyze_trend_structure(candles)
        last_close = float(candles[-1].get("close") or 0.0)
        if last_close <= 0:
            return self._build_component(
                name="market_structure",
                summary="invalid price",
            )

        last_swing_high = structure.get("last_swing_high")
        last_swing_low = structure.get("last_swing_low")
        break_margin = cfg.SMART_PRICE_ACTION_BREAK_BUFFER_PCT
        signal = "neutral"
        score = 0.0
        summary = f"{structure.get('structure', 'mixed')} structure"

        if last_swing_high and last_close > float(last_swing_high[1]) * (1.0 + break_margin):
            score = cfg.SMART_PRICE_ACTION_STRUCTURE_BREAK_SCORE
            if structure.get("trend") != "bullish":
                score += cfg.SMART_PRICE_ACTION_STRUCTURE_RECLAIM_BONUS
            signal = "bullish_break"
            summary = (
                f"Bullish break above swing high {float(last_swing_high[1]):.4f} "
                f"({structure.get('structure', 'mixed')})"
            )
        elif last_swing_low and last_close < float(last_swing_low[1]) * (1.0 - break_margin):
            score = -cfg.SMART_PRICE_ACTION_STRUCTURE_BREAK_SCORE
            if structure.get("trend") != "bearish":
                score -= cfg.SMART_PRICE_ACTION_STRUCTURE_RECLAIM_BONUS
            signal = "bearish_break"
            summary = (
                f"Bearish break below swing low {float(last_swing_low[1]):.4f} "
                f"({structure.get('structure', 'mixed')})"
            )
        elif structure.get("trend") == "bullish":
            score = min(
                cfg.SMART_PRICE_ACTION_STRUCTURE_TREND_SCORE,
                float(structure.get("strength", 0)) * 0.6,
            )
            signal = "bullish_structure"
            summary = (
                f"Bullish structure HH/HL ({structure.get('higher_highs', 0)}HH/"
                f"{structure.get('higher_lows', 0)}HL)"
            )
        elif structure.get("trend") == "bearish":
            score = -min(
                cfg.SMART_PRICE_ACTION_STRUCTURE_TREND_SCORE,
                float(structure.get("strength", 0)) * 0.6,
            )
            signal = "bearish_structure"
            summary = (
                f"Bearish structure LH/LL ({structure.get('lower_highs', 0)}LH/"
                f"{structure.get('lower_lows', 0)}LL)"
            )

        return self._build_component(
            name="market_structure",
            signal=signal,
            score=score,
            summary=summary,
            details=structure,
        )

    def _analyze_liquidity_sweep(
        self,
        candles: List[Dict[str, Any]],
        levels: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if len(candles) < 3:
            return self._build_component(
                name="liquidity_sweep",
                summary="insufficient candles",
            )
        levels = levels or self._sr_detector.detect_levels(candles)

        latest = candles[-1]
        metrics = self._candle_metrics(latest)
        if metrics["range"] <= 0:
            return self._build_component(
                name="liquidity_sweep",
                summary="flat candle",
            )

        wick_ratio_min = cfg.SMART_PRICE_ACTION_WICK_BODY_MIN_RATIO
        wick_share_min = cfg.SMART_PRICE_ACTION_WICK_RANGE_MIN_RATIO
        sweep_margin = cfg.SMART_PRICE_ACTION_SWEEP_PIERCE_PCT
        reclaim_margin = cfg.SMART_PRICE_ACTION_RECLAIM_MARGIN_PCT

        nearest_support = levels.get("nearest_support") or next(
            iter(levels.get("support") or []),
            None,
        )
        nearest_resistance = levels.get("nearest_resistance") or next(
            iter(levels.get("resistance") or []),
            None,
        )
        proximity_limit = cfg.SMART_PRICE_ACTION_LIQUIDITY_PROXIMITY_PCT
        max_sweep = cfg.SMART_PRICE_ACTION_SWEEP_MAX_PCT

        if nearest_support:
            support_price = float(nearest_support.get("price") or 0.0)
            if support_price > 0:
                support_distance = abs(metrics["close"] - support_price) / max(support_price, 1e-9)
                sweep_depth = max(0.0, (support_price - metrics["low"]) / max(support_price, 1e-9))
                support_swept = metrics["low"] <= support_price * (1.0 - sweep_margin)
                support_reclaimed = metrics["close"] >= support_price * (1.0 + reclaim_margin)
                long_lower_wick = (
                    metrics["lower_wick"] >= max(metrics["body"], 1e-9) * wick_ratio_min
                    and metrics["lower_wick"] / metrics["range"] >= wick_share_min
                )
                if (
                    support_distance <= proximity_limit
                    and sweep_depth <= max_sweep
                    and support_swept
                    and support_reclaimed
                    and long_lower_wick
                ):
                    return self._build_component(
                        name="liquidity_sweep",
                        signal="bullish_sweep_rejection",
                        score=cfg.SMART_PRICE_ACTION_SWEEP_SCORE,
                        summary=(
                            f"Bullish liquidity sweep + wick rejection @ {support_price:.4f}"
                        ),
                        details={
                            "level": nearest_support,
                            "candle": latest,
                            "wick_metrics": metrics,
                        },
                    )

        if nearest_resistance:
            resistance_price = float(nearest_resistance.get("price") or 0.0)
            if resistance_price > 0:
                resistance_distance = abs(metrics["close"] - resistance_price) / max(resistance_price, 1e-9)
                sweep_height = max(0.0, (metrics["high"] - resistance_price) / max(resistance_price, 1e-9))
                resistance_swept = metrics["high"] >= resistance_price * (1.0 + sweep_margin)
                resistance_rejected = metrics["close"] <= resistance_price * (1.0 - reclaim_margin)
                long_upper_wick = (
                    metrics["upper_wick"] >= max(metrics["body"], 1e-9) * wick_ratio_min
                    and metrics["upper_wick"] / metrics["range"] >= wick_share_min
                )
                if (
                    resistance_distance <= proximity_limit
                    and sweep_height <= max_sweep
                    and resistance_swept
                    and resistance_rejected
                    and long_upper_wick
                ):
                    return self._build_component(
                        name="liquidity_sweep",
                        signal="bearish_sweep_rejection",
                        score=-cfg.SMART_PRICE_ACTION_SWEEP_SCORE,
                        summary=(
                            f"Bearish liquidity sweep + wick rejection @ {resistance_price:.4f}"
                        ),
                        details={
                            "level": nearest_resistance,
                            "candle": latest,
                            "wick_metrics": metrics,
                        },
                    )

        return self._build_component(
            name="liquidity_sweep",
            summary="no sweep rejection",
            details={"candle": latest, "wick_metrics": metrics},
        )

    def _analyze_mtf_alignment(self, symbol: str) -> Dict[str, Any]:
        try:
            alignment = self._timeframe_aligner.calculate_alignment(symbol)
        except Exception as exc:
            return self._build_component(
                name="mtf_alignment",
                summary=f"alignment failed: {exc}",
            )

        weighted_score = float(alignment.get("weighted_score") or 0.0)
        score = self._clamp(
            weighted_score * cfg.SMART_PRICE_ACTION_MTF_WEIGHT_MULTIPLIER,
            -cfg.SMART_PRICE_ACTION_MTF_SCORE_CAP,
            cfg.SMART_PRICE_ACTION_MTF_SCORE_CAP,
        )
        signal = "neutral"
        if score > 0:
            signal = "bullish"
        elif score < 0:
            signal = "bearish"

        summary = (
            f"{alignment.get('alignment', 'UNKNOWN')} MTF "
            f"(weighted={weighted_score:.1f})"
        )
        return self._build_component(
            name="mtf_alignment",
            signal=signal,
            score=score,
            summary=summary,
            details=alignment,
        )

    def _analyze_candle_pattern(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pattern_result = self._detect_candle_pattern(candles)
        if not pattern_result:
            return self._build_component(
                name="candle_pattern",
                summary="no pattern",
            )

        pattern = str(pattern_result.get("pattern") or "").strip().lower()
        signal = str(pattern_result.get("signal") or "neutral").strip().lower()
        if signal not in {"bullish", "bearish"}:
            return self._build_component(
                name="candle_pattern",
                summary=pattern or "neutral pattern",
                details=pattern_result,
            )

        pattern_weights = {
            "bullish_engulfing": 8.0,
            "bearish_engulfing": -8.0,
            "morning_star": 8.0,
            "evening_star": -8.0,
            "hammer": 6.0,
            "hanging_man": -6.0,
            "inverted_hammer": 5.0,
            "shooting_star": -7.0,
            "dragonfly_doji": 5.0,
            "gravestone_doji": -5.0,
            "piercing_line": 6.0,
            "dark_cloud_cover": -6.0,
            "three_white_soldiers": 8.0,
            "three_black_crows": -8.0,
        }
        raw_score = float(pattern_weights.get(pattern, 0.0))
        summary = pattern.replace("_", " ") if pattern else "pattern"
        return self._build_component(
            name="candle_pattern",
            signal=signal,
            score=raw_score,
            summary=summary,
            details=pattern_result,
        )

    def _analyze_volume_confirmation(
        self,
        candles: List[Dict[str, Any]],
        provisional_direction: str,
    ) -> Dict[str, Any]:
        if len(candles) < 21:
            return self._build_component(
                name="volume_confirmation",
                summary="insufficient volume history",
            )

        last_candle = candles[-1]
        historical = candles[-21:-1]
        avg_volume = sum(float(c.get("volume") or 0.0) for c in historical) / max(len(historical), 1)
        last_volume = float(last_candle.get("volume") or 0.0)
        ratio = (last_volume / avg_volume) if avg_volume > 0 else 0.0
        signal = "neutral"
        score = 0.0

        if provisional_direction in {"bullish", "bearish"}:
            if ratio >= cfg.SMART_PRICE_ACTION_VOLUME_STRONG_RATIO:
                signal = provisional_direction
                score = self._signed_score(
                    provisional_direction,
                    cfg.SMART_PRICE_ACTION_VOLUME_STRONG_SCORE,
                )
            elif ratio >= cfg.SMART_PRICE_ACTION_VOLUME_CONFIRM_RATIO:
                signal = provisional_direction
                score = self._signed_score(
                    provisional_direction,
                    cfg.SMART_PRICE_ACTION_VOLUME_CONFIRM_SCORE,
                )
            elif ratio <= cfg.SMART_PRICE_ACTION_VOLUME_WEAK_RATIO:
                signal = "neutral"
                score = -self._signed_score(
                    provisional_direction,
                    cfg.SMART_PRICE_ACTION_LOW_VOLUME_PENALTY,
                )

        summary = f"volume ratio={ratio:.2f}x"
        if signal in {"bullish", "bearish"} and score != 0:
            summary += f" confirming {signal}"
        elif ratio <= cfg.SMART_PRICE_ACTION_VOLUME_WEAK_RATIO:
            summary += " weak confirmation"

        return self._build_component(
            name="volume_confirmation",
            signal=signal,
            score=score,
            summary=summary,
            details={
                "volume_ratio": round(ratio, 3),
                "last_volume": last_volume,
                "average_volume": avg_volume,
            },
        )

    def analyze(
        self,
        symbol: str,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        symbol = str(symbol or "").strip().upper()
        if not symbol or not cfg.SMART_PRICE_ACTION_ENABLED:
            return {
                "symbol": symbol,
                "direction": "neutral",
                "net_score": 0.0,
                "bullish_score": 0.0,
                "bearish_score": 0.0,
                "components": {},
                "summary": "price action disabled",
            }

        cache_price = round(float(current_price or 0.0), 8)
        cache_key = f"price_action:{symbol}:{cache_price}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        result: Dict[str, Any] = {
            "symbol": symbol,
            "timeframe": cfg.SMART_PRICE_ACTION_TIMEFRAME,
            "direction": "neutral",
            "bias": "neutral",
            "net_score": 0.0,
            "signed_score": 0.0,
            "bullish_score": 0.0,
            "bearish_score": 0.0,
            "components": {},
            "summary": "",
            "available": False,
        }

        try:
            candles = self._get_closed_candles(
                symbol=symbol,
                interval=cfg.SMART_PRICE_ACTION_TIMEFRAME,
                limit=max(40, cfg.SMART_PRICE_ACTION_CANDLE_LIMIT),
            )
        except Exception as exc:
            result["summary"] = f"price-action fetch failed: {exc}"
            return self._set_cached(cache_key, result)

        if not candles:
            result["summary"] = "no candles"
            return self._set_cached(cache_key, result)

        if current_price is None:
            current_price = float(candles[-1].get("close") or 0.0)
        result["current_price"] = current_price

        levels = self._sr_detector.detect_levels(candles)
        components: Dict[str, Dict[str, Any]] = {
            "market_structure": self._analyze_market_structure(candles),
            "liquidity_sweep": self._analyze_liquidity_sweep(candles, levels),
            "mtf_alignment": self._analyze_mtf_alignment(symbol),
            "candle_pattern": self._analyze_candle_pattern(candles),
        }

        provisional_net = sum(
            float(component.get("score") or 0.0) for component in components.values()
        )
        provisional_direction = "neutral"
        if provisional_net >= cfg.SMART_PRICE_ACTION_DIRECTION_THRESHOLD:
            provisional_direction = "bullish"
        elif provisional_net <= -cfg.SMART_PRICE_ACTION_DIRECTION_THRESHOLD:
            provisional_direction = "bearish"

        components["volume_confirmation"] = self._analyze_volume_confirmation(
            candles,
            provisional_direction=provisional_direction,
        )

        bullish_score = 0.0
        bearish_score = 0.0
        summary_parts: List[str] = []
        for component in components.values():
            score = float(component.get("score") or 0.0)
            if score > 0:
                bullish_score += score
            elif score < 0:
                bearish_score += abs(score)
            if component.get("score"):
                summary_parts.append(str(component.get("summary") or component.get("name")))

        net_score = bullish_score - bearish_score
        direction = "neutral"
        if net_score >= cfg.SMART_PRICE_ACTION_DIRECTION_THRESHOLD:
            direction = "bullish"
        elif net_score <= -cfg.SMART_PRICE_ACTION_DIRECTION_THRESHOLD:
            direction = "bearish"

        result.update(
            {
                "available": True,
                "direction": direction,
                "bias": direction,
                "net_score": round(net_score, 2),
                "signed_score": round(net_score, 2),
                "bullish_score": round(bullish_score, 2),
                "bearish_score": round(bearish_score, 2),
                "components": components,
                "levels": levels,
                "summary": "; ".join(summary_parts) if summary_parts else "mixed price action",
            }
        )
        result.update(components)
        return self._set_cached(cache_key, result)

    def evaluate_side(
        self,
        context: Dict[str, Any],
        side: str,
    ) -> Dict[str, Any]:
        normalized_side = str(side or "").strip().lower()
        bullish_score = float(context.get("bullish_score") or 0.0)
        bearish_score = float(context.get("bearish_score") or 0.0)
        if bullish_score == 0.0 and bearish_score == 0.0:
            signed_score = float(
                context.get("net_score", context.get("signed_score") or 0.0)
            )
            bullish_score = max(0.0, signed_score)
            bearish_score = max(0.0, -signed_score)
        components = context.get("components") or {}

        if normalized_side == "buy":
            adverse_score = bearish_score
            supportive_score = bullish_score
            adverse_signal = "bearish"
            block_code = "PRICE_ACTION_BEARISH"
        elif normalized_side == "sell":
            adverse_score = bullish_score
            supportive_score = bearish_score
            adverse_signal = "bullish"
            block_code = "PRICE_ACTION_BULLISH"
        else:
            return {
                "blocked": False,
                "blocked_by": [],
                "reason": "unsupported side",
                "supportive_score": 0.0,
                "adverse_score": 0.0,
                "adverse_components": [],
                "supportive_components": [],
            }

        adverse_components = [
            name
            for name, component in components.items()
            if (
                (
                    adverse_signal == "bearish"
                    and float(component.get("score") or 0.0) < 0
                )
                or (
                    adverse_signal == "bullish"
                    and float(component.get("score") or 0.0) > 0
                )
            )
            and abs(float(component.get("score") or 0.0))
            >= cfg.SMART_PRICE_ACTION_COMPONENT_MIN_SCORE
        ]
        supportive_components = [
            name
            for name, component in components.items()
            if (
                (
                    normalized_side == "buy"
                    and float(component.get("score") or 0.0) > 0
                )
                or (
                    normalized_side == "sell"
                    and float(component.get("score") or 0.0) < 0
                )
            )
            and abs(float(component.get("score") or 0.0))
            >= cfg.SMART_PRICE_ACTION_COMPONENT_MIN_SCORE
        ]

        blocked = (
            adverse_score >= cfg.ENTRY_GATE_PRICE_ACTION_BLOCK_SCORE
            and (
                len(adverse_components)
                >= cfg.ENTRY_GATE_PRICE_ACTION_BLOCK_MIN_COMPONENTS
            )
        )
        if not blocked and adverse_score >= cfg.ENTRY_GATE_PRICE_ACTION_HARD_BLOCK_SCORE:
            blocked = True

        component_text = ", ".join(adverse_components[:3]) if adverse_components else "none"
        reason = (
            f"Price action {adverse_signal} score {adverse_score:.1f} "
            f"(components: {component_text})"
        )

        return {
            "blocked": blocked,
            "blocked_by": [block_code] if blocked else [],
            "reason": reason,
            "supportive_score": round(supportive_score, 2),
            "adverse_score": round(adverse_score, 2),
            "adverse_components": adverse_components,
            "supportive_components": supportive_components,
        }

    def score_mode_fit(
        self,
        context: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        net_score = float(context.get("net_score") or 0.0)
        bullish_score = float(context.get("bullish_score") or 0.0)
        bearish_score = float(context.get("bearish_score") or 0.0)

        fit_score = 0.0
        summary = "neutral fit"

        if normalized_mode == "long":
            fit_score = self._clamp(
                net_score * cfg.SMART_PRICE_ACTION_MODE_WEIGHT,
                -cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
                cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
            )
            summary = f"long fit net={net_score:.1f}"
        elif normalized_mode == "short":
            fit_score = self._clamp(
                -net_score * cfg.SMART_PRICE_ACTION_MODE_WEIGHT,
                -cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
                cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
            )
            summary = f"short fit net={net_score:.1f}"
        elif normalized_mode in {"neutral", "neutral_classic_bybit"}:
            directional_pressure = max(bullish_score, bearish_score)
            fit_score = cfg.SMART_PRICE_ACTION_NEUTRAL_BASE_SCORE - (
                directional_pressure * cfg.SMART_PRICE_ACTION_NEUTRAL_PENALTY_WEIGHT
            ) - (
                abs(net_score) * cfg.SMART_PRICE_ACTION_NEUTRAL_NET_PENALTY_WEIGHT
            )
            if context.get("direction") == "neutral":
                fit_score += cfg.SMART_PRICE_ACTION_NEUTRAL_BALANCE_BONUS
            else:
                fit_score -= (
                    directional_pressure * cfg.SMART_PRICE_ACTION_NEUTRAL_PENALTY_WEIGHT
                )
            fit_score = self._clamp(
                fit_score,
                -cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
                cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
            )
            summary = f"neutral fit pressure={directional_pressure:.1f}"
        elif normalized_mode in {"scalp_pnl", "scalp_market"}:
            impulse = max(bullish_score, bearish_score)
            fit_score = (
                impulse * cfg.SMART_PRICE_ACTION_SCALP_WEIGHT
            )
            if context.get("direction") == "neutral":
                fit_score += cfg.SMART_PRICE_ACTION_SCALP_BALANCE_BONUS
            fit_score = self._clamp(
                fit_score,
                -cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
                cfg.SMART_PRICE_ACTION_MODE_SCORE_CAP,
            )
            summary = f"scalp fit impulse={impulse:.1f}"

        return {
            "mode": normalized_mode,
            "score": round(fit_score, 2),
            "summary": summary,
            "direction": context.get("direction", context.get("bias", "neutral")),
            "bias": context.get("direction", context.get("bias", "neutral")),
            "net_score": round(net_score, 2),
        }

    def score_for_mode(
        self,
        mode: str,
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Backward-compatible alias used by Auto-Pilot ranking tests/callers.
        """
        normalized_analysis = dict(analysis or {})
        if "net_score" not in normalized_analysis and "signed_score" in normalized_analysis:
            normalized_analysis["net_score"] = normalized_analysis.get("signed_score")
        if "direction" not in normalized_analysis:
            normalized_analysis["direction"] = normalized_analysis.get("bias", "neutral")
        if "bullish_score" not in normalized_analysis or "bearish_score" not in normalized_analysis:
            signed_score = float(normalized_analysis.get("net_score") or 0.0)
            normalized_analysis.setdefault("bullish_score", max(0.0, signed_score))
            normalized_analysis.setdefault("bearish_score", max(0.0, -signed_score))
        return self.score_mode_fit(context=normalized_analysis, mode=mode)
