"""
Bybit Control Center - Take-Profit Service

Automatically calculates take-profit targets based on volatility, mode, and risk profile.
Similar to stop_loss_service.py but for profit taking.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TakeProfitService:
    """
    Service for calculating automatic adaptive take-profit levels.
    """

    def __init__(
        self,
        safe_tp_multiplier: float = 1.5,
        normal_tp_multiplier: float = 2.0,
        aggressive_tp_multiplier: float = 2.5,
        min_tp_pct: float = 0.003,
        max_tp_pct: float = 0.10,
    ):
        """
        Initialize take-profit service.

        Args:
            safe_tp_multiplier: ATR multiplier for SAFE profile
            normal_tp_multiplier: ATR multiplier for NORMAL profile
            aggressive_tp_multiplier: ATR multiplier for AGGRESSIVE profile
            min_tp_pct: Minimum TP distance (0.5%)
            max_tp_pct: Maximum TP distance (10%)
        """
        self.safe_tp_multiplier = safe_tp_multiplier
        self.normal_tp_multiplier = normal_tp_multiplier
        self.aggressive_tp_multiplier = aggressive_tp_multiplier
        self.min_tp_pct = min_tp_pct
        self.max_tp_pct = max_tp_pct

    def calculate_take_profit(
        self,
        symbol: str,
        mode: str,
        current_price: float,
        grid_lower: float,
        grid_upper: float,
        atr_pct: Optional[float],
        bbw_pct: Optional[float],
        profile: str = "normal",
        bot_investment: float = 0,
        bot_leverage: float = 1,
    ) -> Dict[str, Any]:
        """
        Calculate automatic take-profit level.

        Strategy:
        1. Use volatility (ATR/BBW) as base for TP distance
        2. Apply profile multiplier (SAFE=conservative, AGGRESSIVE=wider targets)
        3. Mode-specific adjustments:
           - Neutral: TP at mid-range movement
           - Long: TP above entry (toward upper bound)
           - Short: TP below entry (toward lower bound)
           - Scalp: Tight TP (small frequent profits)
        4. Clamp between min/max percentages

        Args:
            symbol: Trading symbol
            mode: Bot mode ("neutral", "long", "short", "scalp_pnl", "scalp_market")
            current_price: Current market price
            grid_lower: Grid lower boundary
            grid_upper: Grid upper boundary
            atr_pct: Average True Range as percentage
            bbw_pct: Bollinger Band Width as percentage
            profile: Risk profile ("safe", "normal", "aggressive")
            bot_investment: Bot investment amount (for absolute TP calc)
            bot_leverage: Bot leverage

        Returns:
            Dict with:
            - tp_pct: Take-profit as percentage of investment
            - tp_price_distance_pct: TP distance from current price (%)
            - tp_method: Calculation method used
            - reasons: List of calculation steps
            - enabled: Whether TP should be used
        """
        reasons = []

        # STEP 1: Determine TP multiplier based on profile
        if profile.lower() == "safe":
            tp_multiplier = self.safe_tp_multiplier  # Conservative profits
            reasons.append(f"SAFE profile: {tp_multiplier}x ATR multiplier")
        elif profile.lower() == "aggressive":
            tp_multiplier = self.aggressive_tp_multiplier  # Larger profits
            reasons.append(f"AGGRESSIVE profile: {tp_multiplier}x ATR multiplier")
        else:
            tp_multiplier = self.normal_tp_multiplier  # Balanced
            reasons.append(f"NORMAL profile: {tp_multiplier}x ATR multiplier")

        # STEP 2: Get volatility base
        volatility_pct = atr_pct if atr_pct is not None else bbw_pct

        if volatility_pct is None or volatility_pct <= 0:
            # No volatility data - use default based on mode
            if mode in ("scalp_pnl", "scalp_market"):
                tp_price_distance_pct = 0.005  # 0.5% for scalp — tighter for small capital
                tp_method = "default_scalp_no_volatility"
                reasons.append("No volatility data, using scalp default 0.5%")
            elif mode == "neutral":
                tp_price_distance_pct = 0.015  # 1.5% for neutral
                tp_method = "default_neutral_no_volatility"
                reasons.append("No volatility data, using neutral default 1.5%")
            else:
                tp_price_distance_pct = 0.025  # 2.5% for directional
                tp_method = "default_directional_no_volatility"
                reasons.append("No volatility data, using directional default 2.5%")
        else:
            # STEP 3: Calculate TP distance from volatility
            base_tp_distance = volatility_pct * tp_multiplier

            # STEP 4: Mode-specific adjustments
            if mode in ("scalp_pnl", "scalp_market"):
                # Scalp: Very tight TP (smaller multiplier)
                tp_price_distance_pct = base_tp_distance * 0.5  # Half of normal
                tp_method = "volatility_scalp"
                reasons.append(f"Scalp mode: {base_tp_distance*100:.3f}% × 0.5 = {tp_price_distance_pct*100:.3f}%")

            elif mode == "neutral":
                # Neutral: Standard TP based on grid width
                grid_width_pct = (grid_upper - grid_lower) / current_price if current_price > 0 else 0
                # TP at some fraction of grid width movement
                tp_price_distance_pct = min(base_tp_distance, grid_width_pct * 0.3)  # 30% of grid width max
                tp_method = "volatility_neutral_gridbound"
                reasons.append(f"Neutral mode: min({base_tp_distance*100:.3f}%, grid_width*0.3={grid_width_pct*0.3*100:.3f}%)")

            elif mode in ("long", "short"):
                # Directional: More aggressive TP (aiming for trend profits)
                tp_price_distance_pct = base_tp_distance * 1.2  # 20% more aggressive
                tp_method = "volatility_directional"
                reasons.append(f"Directional mode: {base_tp_distance*100:.3f}% × 1.2 = {tp_price_distance_pct*100:.3f}%")

            else:
                # Unknown mode - use base
                tp_price_distance_pct = base_tp_distance
                tp_method = "volatility_base"
                reasons.append(f"Unknown mode '{mode}', using base {base_tp_distance*100:.3f}%")

        # STEP 5: Clamp between min/max
        tp_price_distance_pct = max(self.min_tp_pct, min(tp_price_distance_pct, self.max_tp_pct))
        reasons.append(f"Clamped to {tp_price_distance_pct*100:.3f}% (min={self.min_tp_pct*100}%, max={self.max_tp_pct*100}%)")

        # STEP 6: Convert to percentage of investment (capital-based TP)
        # TP% = (price_distance% × leverage)
        # Example: 2% price move × 3x leverage = 6% profit on investment
        if bot_leverage > 0:
            tp_pct_of_investment = tp_price_distance_pct * bot_leverage
            reasons.append(f"TP of investment: {tp_price_distance_pct*100:.3f}% × {bot_leverage}x leverage = {tp_pct_of_investment*100:.2f}%")
        else:
            tp_pct_of_investment = tp_price_distance_pct  # Fallback if leverage unknown
            reasons.append(f"TP of investment: {tp_pct_of_investment*100:.2f}% (leverage unknown)")

        return {
            "tp_pct": round(tp_pct_of_investment, 4),  # TP as % of investment
            "tp_price_distance_pct": round(tp_price_distance_pct, 4),  # TP distance from price
            "tp_method": tp_method,
            "reasons": reasons,
            "enabled": True,
        }

    def calculate_tp_usdt_target(
        self,
        bot_investment: float,
        tp_pct: float,
    ) -> float:
        """
        Convert TP percentage to absolute USDT target.

        Args:
            bot_investment: Bot investment amount (USDT)
            tp_pct: Take-profit percentage (e.g., 0.02 = 2%)

        Returns:
            TP target in USDT
        """
        return bot_investment * tp_pct

    def should_take_profit(
        self,
        unrealized_pnl: float,
        tp_target_usdt: float,
        price_moved_pct: float,
        tp_price_distance_pct: float,
        allow_early_exit: bool = True,
    ) -> Dict[str, Any]:
        """
        Determine if position should be closed for profit.

        Args:
            unrealized_pnl: Current unrealized PnL (USDT)
            tp_target_usdt: TP target (USDT)
            price_moved_pct: How much price has moved from entry (%)
            tp_price_distance_pct: Expected TP distance (%)
            allow_early_exit: Allow taking profit slightly below target

        Returns:
            Dict with:
            - should_close: bool (True if should take profit)
            - reason: str (explanation)
            - pnl: float (unrealized PnL)
            - target: float (TP target)
        """
        # Check if profit target reached
        if unrealized_pnl >= tp_target_usdt:
            return {
                "should_close": True,
                "reason": f"TP target reached: ${unrealized_pnl:.2f} >= ${tp_target_usdt:.2f}",
                "pnl": unrealized_pnl,
                "target": tp_target_usdt,
            }

        # Check if price moved expected distance
        if abs(price_moved_pct) >= tp_price_distance_pct:
            return {
                "should_close": True,
                "reason": f"Price moved expected distance: {abs(price_moved_pct)*100:.3f}% >= {tp_price_distance_pct*100:.3f}%",
                "pnl": unrealized_pnl,
                "target": tp_target_usdt,
            }

        # Early exit if close to target (95%+) and allow_early_exit enabled
        if allow_early_exit and tp_target_usdt > 0:
            progress = unrealized_pnl / tp_target_usdt
            if progress >= 0.95:
                return {
                    "should_close": True,
                    "reason": f"Near TP target: ${unrealized_pnl:.2f} ({progress*100:.1f}% of ${tp_target_usdt:.2f})",
                    "pnl": unrealized_pnl,
                    "target": tp_target_usdt,
                }

        # Not yet ready to take profit
        return {
            "should_close": False,
            "reason": f"TP not reached: ${unrealized_pnl:.2f} < ${tp_target_usdt:.2f} ({(unrealized_pnl/max(tp_target_usdt,0.01))*100:.1f}%)",
            "pnl": unrealized_pnl,
            "target": tp_target_usdt,
        }

    def calculate_partial_take_profit(
        self,
        entry_price: float,
        current_price: float,
        position_side: str,
        position_size: float,
        position_value_usdt: float,
        partial_tp_state: Optional[Dict[str, Any]] = None,
        tp_levels: Optional[list] = None,
        min_position_usdt: float = 5.0,
        cooldown_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Calculate partial take-profit for scaling out of positions.

        Takes profit at multiple levels instead of all-or-nothing:
        - Level 1: At 0.5% profit, close 30%
        - Level 2: At 1.0% profit, close 40%
        - Level 3: At 2.0% profit, close remaining 30%

        Args:
            entry_price: Position entry price
            current_price: Current market price
            position_side: "Buy" (long) or "Sell" (short)
            position_size: Current position size (quantity)
            position_value_usdt: Position value in USDT
            partial_tp_state: Previous partial TP state dict (tracks levels hit)
            tp_levels: List of (profit_pct, close_pct) tuples
            min_position_usdt: Minimum remaining position value
            cooldown_seconds: Time between partial closes

        Returns:
            Dict with:
            - should_close: bool - whether to close a portion
            - close_qty: float - quantity to close (0 if shouldn't close)
            - close_pct: float - percentage being closed
            - level_hit: int - which TP level was hit (0, 1, 2, ...)
            - profit_pct: float - current profit percentage
            - reason: str
            - new_state: Dict - updated partial TP state
        """
        import time

        # Default TP levels if not provided
        if tp_levels is None:
            from config.strategy_config import PARTIAL_TP_LEVELS
            tp_levels = PARTIAL_TP_LEVELS

        # Initialize state if not provided
        if partial_tp_state is None:
            partial_tp_state = {
                "levels_hit": [],  # List of level indices already hit
                "last_close_time": 0,
                "total_closed_pct": 0,
            }

        # Validate inputs
        if entry_price <= 0 or current_price <= 0 or position_size <= 0:
            return {
                "should_close": False,
                "close_qty": 0,
                "close_pct": 0,
                "level_hit": -1,
                "profit_pct": 0,
                "reason": "Invalid position data",
                "new_state": partial_tp_state,
            }

        # Calculate profit percentage
        is_long = position_side == "Buy"
        if is_long:
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price

        # Check cooldown
        now = time.time()
        last_close = partial_tp_state.get("last_close_time", 0)
        if now - last_close < cooldown_seconds:
            return {
                "should_close": False,
                "close_qty": 0,
                "close_pct": 0,
                "level_hit": -1,
                "profit_pct": profit_pct,
                "reason": f"Cooldown: {cooldown_seconds - (now - last_close):.0f}s remaining",
                "new_state": partial_tp_state,
            }

        # Check which levels have been hit
        levels_hit = partial_tp_state.get("levels_hit", [])

        for level_idx, (level_profit_pct, level_close_pct) in enumerate(tp_levels):
            # Skip already-hit levels
            if level_idx in levels_hit:
                continue

            # Check if this level is reached
            if profit_pct >= level_profit_pct:
                # Calculate quantity to close
                close_qty = position_size * level_close_pct

                # Check if remaining position would be too small
                remaining_value = position_value_usdt * (1 - level_close_pct)
                if remaining_value < min_position_usdt:
                    # Close everything instead
                    close_qty = position_size
                    level_close_pct = 1.0

                # Update state
                new_state = {
                    "levels_hit": levels_hit + [level_idx],
                    "last_close_time": now,
                    "total_closed_pct": partial_tp_state.get("total_closed_pct", 0) + level_close_pct,
                }

                return {
                    "should_close": True,
                    "close_qty": close_qty,
                    "close_pct": level_close_pct,
                    "level_hit": level_idx,
                    "profit_pct": profit_pct,
                    "reason": f"Partial TP level {level_idx + 1}: {profit_pct*100:.2f}% >= {level_profit_pct*100:.2f}%, close {level_close_pct*100:.0f}%",
                    "new_state": new_state,
                }

        # No level hit
        return {
            "should_close": False,
            "close_qty": 0,
            "close_pct": 0,
            "level_hit": -1,
            "profit_pct": profit_pct,
            "reason": f"Profit {profit_pct*100:.2f}% below next TP level",
            "new_state": partial_tp_state,
        }
