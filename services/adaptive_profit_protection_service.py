from __future__ import annotations

from typing import Any, Dict, Optional

import config.strategy_config as strategy_cfg


class AdaptiveProfitProtectionService:
    """Adaptive open-position profit protection advisory and live gating helper."""

    VALID_MODES = {"off", "advisory_only", "shadow", "partial_live", "full_live"}
    VALID_DECISIONS = {"wait", "watch_closely", "take_partial", "exit_now"}

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def normalize_mode(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in cls.VALID_MODES:
            return "shadow"
        return normalized

    @classmethod
    def resolve_settings(cls, bot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        source = dict(bot or {})
        mode = cls.normalize_mode(
            source.get("profit_protection_mode")
            or getattr(strategy_cfg, "ADAPTIVE_PROFIT_PROTECTION_MODE", "shadow")
        )
        return {
            "mode": mode,
            "min_arm_profit_pct": max(
                cls._safe_float(
                    source.get("profit_protection_min_arm_profit_pct"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_MIN_ARM_PROFIT_PCT",
                        0.004,
                    ),
                )
                or 0.0,
                0.0,
            ),
            "min_giveback_pct": max(
                cls._safe_float(
                    source.get("profit_protection_min_giveback_pct"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_MIN_GIVEBACK_PCT",
                        0.0015,
                    ),
                )
                or 0.0,
                0.0,
            ),
            "giveback_sensitivity": max(
                cls._safe_float(
                    source.get("profit_protection_giveback_sensitivity"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_GIVEBACK_SENSITIVITY",
                        0.90,
                    ),
                )
                or 0.0,
                0.10,
            ),
            "arm_atr_mult": max(
                cls._safe_float(
                    source.get("profit_protection_arm_atr_mult"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_ARM_ATR_MULT",
                        0.60,
                    ),
                )
                or 0.0,
                0.10,
            ),
            "partial_fraction": min(
                max(
                    cls._safe_float(
                        source.get("profit_protection_partial_fraction"),
                        getattr(
                            strategy_cfg,
                            "ADAPTIVE_PROFIT_PROTECTION_PARTIAL_FRACTION",
                            0.33,
                        ),
                    )
                    or 0.0,
                    0.05,
                ),
                0.90,
            ),
            "trend_loosen_mult": max(
                cls._safe_float(
                    source.get("profit_protection_trend_loosen_mult"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_TREND_LOOSEN_MULT",
                        1.35,
                    ),
                )
                or 0.0,
                1.0,
            ),
            "weak_trend_tighten_mult": min(
                max(
                    cls._safe_float(
                        source.get("profit_protection_weak_trend_tighten_mult"),
                        getattr(
                            strategy_cfg,
                            "ADAPTIVE_PROFIT_PROTECTION_WEAK_TREND_TIGHTEN_MULT",
                            0.88,
                        ),
                    )
                    or 0.0,
                    0.30,
                ),
                1.0,
            ),
            "sideways_tighten_mult": min(
                max(
                    cls._safe_float(
                        source.get("profit_protection_sideways_tighten_mult"),
                        getattr(
                            strategy_cfg,
                            "ADAPTIVE_PROFIT_PROTECTION_SIDEWAYS_TIGHTEN_MULT",
                            0.82,
                        ),
                    )
                    or 0.0,
                    0.30,
                ),
                1.0,
            ),
            "momentum_fading_tighten_mult": min(
                max(
                    cls._safe_float(
                        source.get("profit_protection_momentum_fading_tighten_mult"),
                        getattr(
                            strategy_cfg,
                            "ADAPTIVE_PROFIT_PROTECTION_MOMENTUM_FADING_TIGHTEN_MULT",
                            0.88,
                        ),
                    )
                    or 0.0,
                    0.30,
                ),
                1.0,
            ),
            "cooldown_sec": max(
                cls._safe_float(
                    source.get("profit_protection_cooldown_sec"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_COOLDOWN_SEC",
                        240,
                    ),
                )
                or 0.0,
                0.0,
            ),
            "rearm_guard_sec": max(
                cls._safe_float(
                    source.get("profit_protection_rearm_guard_sec"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_REARM_GUARD_SEC",
                        180,
                    ),
                )
                or 0.0,
                0.0,
            ),
            "shadow_eval_enabled": bool(
                source.get(
                    "profit_protection_shadow_eval_enabled",
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_SHADOW_EVAL_ENABLED",
                        True,
                    ),
                )
            ),
            "shadow_saved_giveback_pct": max(
                cls._safe_float(
                    source.get("profit_protection_shadow_saved_giveback_pct"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_SHADOW_SAVED_GIVEBACK_PCT",
                        0.0020,
                    ),
                )
                or 0.0,
                0.0,
            ),
            "shadow_trend_cut_pct": max(
                cls._safe_float(
                    source.get("profit_protection_shadow_trend_cut_pct"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_SHADOW_TREND_CUT_PCT",
                        0.0035,
                    ),
                )
                or 0.0,
                0.0,
            ),
            "shadow_premature_pct": max(
                cls._safe_float(
                    source.get("profit_protection_shadow_premature_pct"),
                    getattr(
                        strategy_cfg,
                        "ADAPTIVE_PROFIT_PROTECTION_SHADOW_PREMATURE_PCT",
                        0.0025,
                    ),
                )
                or 0.0,
                0.0,
            ),
        }

    @classmethod
    def evaluate(
        cls,
        *,
        bot: Optional[Dict[str, Any]],
        position_side: str,
        current_profit_pct: float,
        current_profit_usdt: float,
        peak_profit_pct: float,
        indicators: Optional[Dict[str, Any]] = None,
        regime_effective: Optional[str] = None,
        regime_confidence: Optional[str] = None,
        previous_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        settings = cls.resolve_settings(bot)
        mode = settings["mode"]
        indicators = dict(indicators or {})
        is_long = str(position_side or "").strip().lower() == "buy"
        atr_pct = max(cls._safe_float(indicators.get("atr_pct"), 0.0) or 0.0, 0.0)
        adx = max(cls._safe_float(indicators.get("adx"), 0.0) or 0.0, 0.0)
        rsi = cls._safe_float(indicators.get("rsi"), 50.0) or 50.0
        velocity = cls._safe_float(indicators.get("price_velocity"), 0.0) or 0.0
        ema_slope = cls._safe_float(indicators.get("ema_slope"), 0.0) or 0.0
        normalized_regime = str(regime_effective or "").strip().upper() or "SIDEWAYS"
        normalized_confidence = str(regime_confidence or "").strip().lower() or "low"

        profit_pct = max(cls._safe_float(current_profit_pct, 0.0) or 0.0, 0.0)
        profit_usdt = max(cls._safe_float(current_profit_usdt, 0.0) or 0.0, 0.0)
        peak_pct = max(
            cls._safe_float(peak_profit_pct, 0.0) or 0.0,
            profit_pct,
        )
        giveback_pct = max(peak_pct - profit_pct, 0.0)

        arm_threshold = max(
            settings["min_arm_profit_pct"],
            atr_pct * settings["arm_atr_mult"],
        )
        giveback_threshold = max(
            settings["min_giveback_pct"],
            atr_pct * settings["giveback_sensitivity"],
        )

        trend_score = 0
        if normalized_regime == ("UP" if is_long else "DOWN"):
            trend_score += 2
        elif normalized_regime == ("DOWN" if is_long else "UP"):
            trend_score -= 2
        elif normalized_regime == "SIDEWAYS":
            trend_score -= 1

        if normalized_confidence in {"high", "locked"} and trend_score > 0:
            trend_score += 1

        if adx >= 25:
            trend_score += 1
        elif adx <= 15:
            trend_score -= 1

        if is_long:
            trend_score += 1 if velocity > 0 else -1 if velocity < 0 else 0
            trend_score += 1 if ema_slope > 0 else -1 if ema_slope < 0 else 0
        else:
            trend_score += 1 if velocity < 0 else -1 if velocity > 0 else 0
            trend_score += 1 if ema_slope < 0 else -1 if ema_slope > 0 else 0

        # Order flow integration: tick-level trade flow adjusts trend assessment
        flow_score = cls._safe_float(indicators.get("flow_score"), 0.0) or 0.0
        flow_confidence = cls._safe_float(indicators.get("flow_confidence"), 0.0) or 0.0
        if flow_confidence >= 0.3:
            if is_long:
                # Positive flow = buying pressure (good for longs)
                if flow_score >= 25:
                    trend_score += 1
                elif flow_score <= -25:
                    trend_score -= 2  # Flow reversing AGAINST position = urgent
            else:
                # Negative flow = selling pressure (good for shorts)
                if flow_score <= -25:
                    trend_score += 1
                elif flow_score >= 25:
                    trend_score -= 2

        trend_score = max(min(trend_score, 5), -5)
        trend_bucket = (
            "strong"
            if trend_score >= 3
            else "healthy"
            if trend_score >= 1
            else "mixed"
            if trend_score == 0
            else "weak"
        )

        if is_long:
            momentum_fading = velocity <= 0 or ema_slope <= 0 or (adx < 18 and giveback_pct > 0)
            exhaustion_risk = bool(rsi >= 69 or (rsi >= 64 and giveback_pct > 0))
            # Flow reversal against long = exhaustion signal
            if flow_score <= -35 and flow_confidence >= 0.4 and profit_pct > 0:
                exhaustion_risk = True
        else:
            momentum_fading = velocity >= 0 or ema_slope >= 0 or (adx < 18 and giveback_pct > 0)
            exhaustion_risk = bool(rsi <= 31 or (rsi <= 36 and giveback_pct > 0))
            # Flow reversal against short = exhaustion signal
            if flow_score >= 35 and flow_confidence >= 0.4 and profit_pct > 0:
                exhaustion_risk = True
        momentum_state = (
            "exhausted"
            if exhaustion_risk
            else "fading"
            if momentum_fading
            else "healthy"
        )

        if trend_bucket == "strong":
            giveback_threshold *= settings["trend_loosen_mult"]
        elif trend_bucket in {"mixed", "weak"}:
            giveback_threshold *= settings["weak_trend_tighten_mult"]
        if normalized_regime == "SIDEWAYS":
            giveback_threshold *= settings["sideways_tighten_mult"]
        if momentum_fading or exhaustion_risk:
            giveback_threshold *= settings["momentum_fading_tighten_mult"]
        # Compute armed BEFORE flow tightening (was causing UnboundLocalError)
        armed = bool(profit_pct >= arm_threshold and profit_usdt > 0.0)

        # Flow reversal tightening: when tick-level trade flow moves AGAINST
        # the position direction, tighten the giveback threshold by 30% so
        # exits happen faster before the reversal deepens.
        flow_opposing = False
        if flow_confidence >= 0.35:
            if is_long and flow_score <= -20:
                flow_opposing = True
            elif not is_long and flow_score >= 20:
                flow_opposing = True
        if flow_opposing and armed:
            giveback_threshold *= 0.70

        giveback_threshold = max(giveback_threshold, settings["min_giveback_pct"])
        near_trigger = giveback_pct >= giveback_threshold * 0.70 if giveback_threshold > 0 else False
        severe_giveback = giveback_pct >= giveback_threshold * 1.35 if giveback_threshold > 0 else False

        previous = dict(previous_state or {})
        rearm_blocked = False
        last_disarmed_ts = cls._safe_float(previous.get("last_disarmed_ts"), 0.0) or 0.0
        last_disarmed_profit_pct = cls._safe_float(
            previous.get("last_disarmed_profit_pct"), 0.0
        ) or 0.0
        if (
            not bool(previous.get("armed"))
            and last_disarmed_ts > 0
            and settings["rearm_guard_sec"] > 0
            and profit_pct
            < max(arm_threshold, last_disarmed_profit_pct + max(atr_pct * 0.25, 0.0005))
        ):
            rearm_blocked = True

        decision = "wait"
        reason_family: Optional[str] = "trend_intact"
        wait_justified = True

        if not armed or rearm_blocked:
            decision = "wait"
            reason_family = "trend_intact" if trend_score > 0 else "volatility_noise_hold"
        elif giveback_pct < giveback_threshold * 0.45 and trend_bucket in {"strong", "healthy"} and not exhaustion_risk:
            decision = "wait"
            reason_family = "trend_intact"
        elif exhaustion_risk and giveback_pct >= giveback_threshold * 0.50:
            decision = "exit_now" if trend_bucket in {"mixed", "weak"} or severe_giveback else "take_partial"
            reason_family = "exhaustion_risk"
            wait_justified = False
        elif giveback_pct >= giveback_threshold:
            if trend_bucket == "strong" and normalized_regime != "SIDEWAYS" and not severe_giveback:
                decision = "take_partial"
                reason_family = "giveback_exceeded"
            elif normalized_regime == "SIDEWAYS" or trend_bucket in {"mixed", "weak"}:
                decision = "exit_now" if severe_giveback or momentum_fading else "take_partial"
                reason_family = (
                    "sideways_decay"
                    if normalized_regime == "SIDEWAYS"
                    else "giveback_exceeded"
                )
            else:
                decision = "take_partial"
                reason_family = "giveback_exceeded"
            wait_justified = False
        elif near_trigger or momentum_fading or normalized_regime == "SIDEWAYS":
            decision = "watch_closely"
            reason_family = (
                "momentum_fading"
                if momentum_fading
                else "sideways_decay"
                if normalized_regime == "SIDEWAYS"
                else "volatility_noise_hold"
            )
            wait_justified = False if near_trigger and trend_bucket in {"mixed", "weak"} else True
        else:
            decision = "wait"
            reason_family = (
                "volatility_noise_hold"
                if atr_pct > 0 and giveback_pct < giveback_threshold * 0.30
                else "trend_intact"
            )

        volatility_state = (
            "elevated"
            if atr_pct >= 0.03
            else "quiet"
            if 0 < atr_pct <= 0.01
            else "normal"
        )
        regime_state = (
            "supportive"
            if normalized_regime == ("UP" if is_long else "DOWN")
            else "sideways"
            if normalized_regime == "SIDEWAYS"
            else "adverse"
        )
        return {
            "enabled": mode != "off",
            "mode": mode,
            "position_side": "Buy" if is_long else "Sell",
            "decision": decision,
            "reason_family": reason_family,
            "wait_justified": bool(wait_justified),
            "actionable": decision in {"take_partial", "exit_now"},
            "armed": bool(armed and not rearm_blocked),
            "rearm_blocked": rearm_blocked,
            "arm_threshold_pct": round(arm_threshold, 6),
            "current_profit_pct": round(profit_pct, 6),
            "current_profit_usdt": round(profit_usdt, 6),
            "peak_profit_pct": round(peak_pct, 6),
            "giveback_pct": round(giveback_pct, 6),
            "giveback_threshold_pct": round(giveback_threshold, 6),
            "partial_fraction": round(settings["partial_fraction"], 4),
            "trend_score": int(trend_score),
            "trend_bucket": trend_bucket,
            "momentum_state": momentum_state,
            "regime_state": regime_state,
            "volatility_state": volatility_state,
            "exhaustion_risk": exhaustion_risk,
            "atr_pct": round(atr_pct, 6),
            "adx": round(adx, 4),
            "rsi": round(rsi, 4),
            "price_velocity": round(velocity, 6),
            "ema_slope": round(ema_slope, 6),
            "settings": {
                "cooldown_sec": int(settings["cooldown_sec"]),
                "rearm_guard_sec": int(settings["rearm_guard_sec"]),
                "shadow_eval_enabled": bool(settings["shadow_eval_enabled"]),
            },
            "shadow_saved_giveback_pct": round(
                settings["shadow_saved_giveback_pct"], 6
            ),
            "shadow_trend_cut_pct": round(
                settings["shadow_trend_cut_pct"], 6
            ),
            "shadow_premature_pct": round(
                settings["shadow_premature_pct"], 6
            ),
        }
