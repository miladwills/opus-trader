"""
AdaptiveConfigService

Computes runtime-adjusted parameters for small-capital bots.
"""

from typing import Any, Dict, Optional

from config.strategy_config import (
    SMALL_CAPITAL_SYMBOL_PROFILES,
    SMALL_CAPITAL_DEFAULT_PROFILE,
    SMALL_CAPITAL_AUTO_MARGIN_CAPS,
)


class AdaptiveConfigService:
    """
    Compute adaptive configuration for small capital risk tuning.
    """

    @staticmethod
    def _clamp(value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    def _symbol_profile(self, symbol: str) -> str:
        profile = SMALL_CAPITAL_SYMBOL_PROFILES.get(symbol, SMALL_CAPITAL_DEFAULT_PROFILE)
        return (profile or SMALL_CAPITAL_DEFAULT_PROFILE).upper()

    def compute_effective_config(
        self,
        symbol: str,
        invest_usdt: float,
        leverage: float,
        target_levels: int,
        instrument: Dict[str, Any],
        atr_5m_pct: Optional[float],
        atr_15m_pct: Optional[float],
        liq_distance_pct: Optional[float],
    ) -> Dict[str, Any]:
        invest_usdt = max(float(invest_usdt or 0.0), 0.0)
        leverage = max(float(leverage or 1.0), 1.0)
        target_levels = int(target_levels or 0)
        if target_levels <= 0:
            target_levels = 1

        min_notional_value = float(instrument.get("min_notional_value") or 5.0)
        per_order_notional_target = max(min_notional_value * 1.2, min_notional_value)
        notional_budget = invest_usdt * leverage

        max_levels_by_budget = 0
        if per_order_notional_target > 0:
            max_levels_by_budget = int(notional_budget // per_order_notional_target)

        if max_levels_by_budget <= 0:
            effective_levels = 1
            budget_too_small = True
        else:
            effective_levels = min(target_levels, max_levels_by_budget)
            budget_too_small = False

        per_order_notional = notional_budget / effective_levels if effective_levels > 0 else 0.0

        profile = self._symbol_profile(symbol)
        effective_step_pct = None
        if atr_5m_pct and atr_5m_pct > 0:
            if profile == "ETH":
                effective_step_pct = self._clamp(0.25 * atr_5m_pct, 0.002, 0.008)
            else:
                effective_step_pct = self._clamp(0.35 * atr_5m_pct, 0.004, 0.018)

        effective_range_pct = None
        if effective_step_pct is not None and effective_levels > 0:
            effective_range_pct = effective_step_pct * effective_levels / 2.0

        max_total_add_usdt = float(SMALL_CAPITAL_AUTO_MARGIN_CAPS.get(profile, 0.0) or 0.0)
        allowed_modes = ("TRAILING_LONG", "PAUSE") if profile == "MEME" else None

        return {
            "profile": profile,
            "per_order_notional_target": per_order_notional_target,
            "per_order_notional": per_order_notional,
            "notional_budget": notional_budget,
            "target_levels": target_levels,
            "effective_levels": effective_levels,
            "effective_step_pct": effective_step_pct,
            "effective_range_pct": effective_range_pct,
            "atr_5m_pct": atr_5m_pct,
            "atr_15m_pct": atr_15m_pct,
            "liq_distance_pct": liq_distance_pct,
            "budget_too_small": budget_too_small,
            "max_total_add_usdt": max_total_add_usdt,
            "allowed_modes": allowed_modes,
        }
