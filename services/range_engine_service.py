"""
Bybit Control Center - Range Engine Service

Builds neutral trading ranges based on price and volatility.
Enhanced with automatic recentering and profile-based width adjustments.
"""

import logging
from typing import Optional, Dict, Any
from config.strategy_config import (
    DEFAULT_RANGE_WIDTH_PCT,
    MIN_RANGE_WIDTH_PCT,
    MAX_RANGE_WIDTH_PCT,
)

logger = logging.getLogger(__name__)


class RangeEngineService:
    """
    Service for computing neutral trading ranges with automatic recentering.
    """

    def __init__(self, default_width_pct: float = DEFAULT_RANGE_WIDTH_PCT):
        """
        Initialize the range engine service.

        Args:
            default_width_pct: Default total width of the neutral range (e.g., 0.06 for 6%)
        """
        self.default_width_pct = default_width_pct

    def build_neutral_range(
        self,
        last_price: float,
        atr_pct: Optional[float],
        bbw_pct: Optional[float],
        width_floor_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Build a neutral trading range centered around the last price.

        The range width is determined by volatility indicators:
        - Uses ATR% * 3.0 if available and larger than default
        - Falls back to BBW% * 1.5 if ATR not available
        - Uses default_width_pct as minimum
        - Clamps width between MIN_RANGE_WIDTH_PCT and MAX_RANGE_WIDTH_PCT

        Args:
            last_price: Current price of the asset
            atr_pct: Average True Range as percentage of price
            bbw_pct: Bollinger Band Width as percentage
            width_floor_pct: Optional per-call floor for total range width

        Returns:
            Dict with lower bound, upper bound, and width percentage
        """
        if last_price <= 0:
            return {
                "lower": 0.0,
                "upper": 0.0,
                "width_pct": 0.0
            }

        # Start with the configured floor for this calculation.
        width_pct = (
            float(width_floor_pct)
            if width_floor_pct is not None
            else self.default_width_pct
        )

        # Adjust based on ATR if available
        if atr_pct is not None and atr_pct > 0:
            atr_based_width = atr_pct * 3.0
            width_pct = max(width_pct, atr_based_width)

        # Adjust based on BBW if ATR not available or BBW suggests wider
        elif bbw_pct is not None and bbw_pct > 0:
            bbw_based_width = bbw_pct * 1.5
            width_pct = max(width_pct, bbw_based_width)

        # Clamp between min and max
        width_pct = max(MIN_RANGE_WIDTH_PCT, min(width_pct, MAX_RANGE_WIDTH_PCT))

        # Calculate range bounds
        half = last_price * width_pct / 2.0
        lower = max(0.0, last_price - half)
        upper = last_price + half

        return {
            "lower": round(lower, 8),
            "upper": round(upper, 8),
            "width_pct": round(width_pct, 4)
        }

    def should_recenter_range(
        self,
        current_price: float,
        current_lower: float,
        current_upper: float,
        recenter_threshold_pct: float = 0.70,
    ) -> Dict[str, Any]:
        """
        Determine if the grid range should be recentered based on price position.

        Strategy:
        - If price reaches 70%+ of the way to either bound, recenter
        - This prevents price from hitting range boundaries and breaking grid logic

        Args:
            current_price: Current market price
            current_lower: Current grid lower boundary
            current_upper: Current grid upper boundary
            recenter_threshold_pct: Threshold for recentering (0-1, default 0.70 = 70%)

        Returns:
            Dict with:
            - should_recenter: bool (True if recentering needed)
            - reason: str (explanation)
            - price_position_pct: float (where price is in the range, 0-1)
        """
        if current_lower >= current_upper or current_price <= 0:
            return {
                "should_recenter": False,
                "reason": "Invalid range or price",
                "price_position_pct": 0.5,
            }

        try:
            normalized_threshold = float(recenter_threshold_pct)
        except (TypeError, ValueError):
            normalized_threshold = 0.70
        # Keep the threshold above the midpoint so "near edge" never degrades
        # into "anything outside the exact center".
        normalized_threshold = max(0.55, min(normalized_threshold, 0.90))

        # Calculate where price is in the range (0 = lower, 1 = upper, 0.5 = middle)
        range_width = current_upper - current_lower
        price_from_lower = current_price - current_lower
        price_position_pct = price_from_lower / range_width

        # Price below lower bound
        if current_price < current_lower:
            return {
                "should_recenter": True,
                "reason": f"Price ${current_price:.8f} broke below lower bound ${current_lower:.8f}",
                "price_position_pct": price_position_pct,
            }

        # Price above upper bound
        if current_price > current_upper:
            return {
                "should_recenter": True,
                "reason": f"Price ${current_price:.8f} broke above upper bound ${current_upper:.8f}",
                "price_position_pct": price_position_pct,
            }

        # Price near lower bound (below threshold)
        if price_position_pct < (1 - normalized_threshold):
            distance_to_lower_pct = (current_price - current_lower) / current_price
            return {
                "should_recenter": True,
                "reason": (
                    f"Price too close to lower bound "
                    f"(position={price_position_pct*100:.1f}%, distance={distance_to_lower_pct*100:.2f}%)"
                ),
                "price_position_pct": price_position_pct,
            }

        # Price near upper bound (above threshold)
        if price_position_pct > normalized_threshold:
            distance_to_upper_pct = (current_upper - current_price) / current_price
            return {
                "should_recenter": True,
                "reason": (
                    f"Price too close to upper bound "
                    f"(position={price_position_pct*100:.1f}%, distance={distance_to_upper_pct*100:.2f}%)"
                ),
                "price_position_pct": price_position_pct,
            }

        # Price comfortably in middle
        return {
            "should_recenter": False,
            "reason": f"Price centered (position={price_position_pct*100:.1f}% in range)",
            "price_position_pct": price_position_pct,
        }

    def apply_profile_adjustment(
        self,
        base_width_pct: float,
        profile: str = "normal",
    ) -> Dict[str, Any]:
        """
        Adjust range width based on risk profile.

        Strategy:
        - SAFE: Narrower ranges (0.80x), tighter grid, more conservative
        - NORMAL: Default ranges (1.0x)
        - AGGRESSIVE: Wider ranges (1.30x), more breathing room

        Args:
            base_width_pct: Base range width percentage (from volatility calc)
            profile: Risk profile ("safe", "normal", "aggressive")

        Returns:
            Dict with:
            - adjusted_width_pct: float (profile-adjusted width)
            - profile: str (profile used)
            - multiplier: float (adjustment multiplier applied)
        """
        profile_lower = profile.lower()

        # Profile multipliers
        if profile_lower == "safe":
            multiplier = 0.80  # 20% narrower ranges
        elif profile_lower == "aggressive":
            multiplier = 1.30  # 30% wider ranges
        else:
            multiplier = 1.00  # NORMAL: no adjustment

        adjusted_width_pct = base_width_pct * multiplier

        # Still respect min/max bounds
        adjusted_width_pct = max(MIN_RANGE_WIDTH_PCT, min(adjusted_width_pct, MAX_RANGE_WIDTH_PCT))

        return {
            "adjusted_width_pct": round(adjusted_width_pct, 4),
            "profile": profile,
            "multiplier": multiplier,
        }

    def build_neutral_range_with_profile(
        self,
        last_price: float,
        atr_pct: Optional[float],
        bbw_pct: Optional[float],
        profile: str = "normal",
        existing_lower: Optional[float] = None,
        existing_upper: Optional[float] = None,
        recenter_threshold_pct: float = 0.70,
        width_floor_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Build neutral range with profile-based adjustments and automatic recentering.

        This is the enhanced version that combines:
        1. Volatility-based width calculation
        2. Profile-based width adjustment (SAFE/NORMAL/AGGRESSIVE)
        3. Automatic recentering if price approaches boundaries

        Args:
            last_price: Current market price
            atr_pct: Average True Range as percentage
            bbw_pct: Bollinger Band Width as percentage
            profile: Risk profile ("safe", "normal", "aggressive")
            existing_lower: Existing grid lower bound (for recentering check)
            existing_upper: Existing grid upper bound (for recentering check)
            recenter_threshold_pct: Threshold for recentering (default 0.70)
            width_floor_pct: Optional per-call floor for total range width

        Returns:
            Dict with:
            - lower: float (lower boundary)
            - upper: float (upper boundary)
            - width_pct: float (total width percentage)
            - profile: str (profile used)
            - recentered: bool (whether range was recentered)
            - recenter_reason: Optional[str] (why recentering happened)
        """
        result = {
            "recentered": False,
            "recenter_reason": None,
            "profile": profile,
        }

        # Step 1: Check if recentering needed
        if existing_lower is not None and existing_upper is not None:
            recenter_check = self.should_recenter_range(
                current_price=last_price,
                current_lower=existing_lower,
                current_upper=existing_upper,
                recenter_threshold_pct=recenter_threshold_pct,
            )

            if not recenter_check.get("should_recenter"):
                # No recentering needed - return existing range
                logger.debug(f"Range recentering not needed: {recenter_check.get('reason')}")
                result.update({
                    "lower": existing_lower,
                    "upper": existing_upper,
                    "width_pct": round((existing_upper - existing_lower) / last_price, 4),
                    "recentered": False,
                })
                return result
            else:
                # Recentering needed
                result["recentered"] = True
                result["recenter_reason"] = recenter_check.get("reason")
                logger.info(f"🔄 Range recentering triggered: {recenter_check.get('reason')}")

        # Step 2: Build new range with volatility
        base_range = self.build_neutral_range(
            last_price=last_price,
            atr_pct=atr_pct,
            bbw_pct=bbw_pct,
            width_floor_pct=width_floor_pct,
        )

        # Step 3: Apply profile-based adjustment
        profile_adjustment = self.apply_profile_adjustment(
            base_width_pct=base_range["width_pct"],
            profile=profile,
        )

        adjusted_width_pct = profile_adjustment["adjusted_width_pct"]

        # Recalculate bounds with adjusted width
        half = last_price * adjusted_width_pct / 2.0
        lower = max(0.0, last_price - half)
        upper = last_price + half

        result.update({
            "lower": round(lower, 8),
            "upper": round(upper, 8),
            "width_pct": adjusted_width_pct,
            "profile_multiplier": profile_adjustment["multiplier"],
        })

        return result
