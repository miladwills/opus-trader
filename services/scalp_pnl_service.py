"""
Bybit Control Center - Scalp PnL Service

Intelligent unrealized profit scalping that:
1. Takes quick profits ($0.2-$0.3) in choppy/volatile markets
2. Holds for larger targets ($0.6+) when trending
3. Places grid orders close to current price to follow momentum
4. Adapts dynamically based on market conditions
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
from enum import Enum

from config.strategy_config import (
    SCALP_PNL_MIN_PROFIT,
    SCALP_PNL_QUICK_PROFIT,
    SCALP_PNL_TARGET_PROFIT,
    SCALP_PNL_MAX_TARGET,
    SCALP_PNL_BASE_POSITION_NOTIONAL_USDT,
    SCALP_PNL_POSITION_SCALE_MAX,
    SCALP_PNL_MOMENTUM_STRONG,
    SCALP_PNL_MOMENTUM_WEAK,
    SCALP_PNL_HIGH_VOLATILITY_ATR,
    SCALP_PNL_LOW_VOLATILITY_ATR,
    SCALP_PNL_NEAR_GRID_PCT,
    SCALP_PNL_FAR_GRID_PCT,
    SCALP_PNL_SWING_LOOKBACK,
    SCALP_PNL_SWING_THRESHOLD,
    # 001-trading-bot-audit FR-015, FR-016, FR-017
    SCALP_FEE_MULTIPLIER,
    SCALP_SPREAD_THRESHOLD_PCT,
    SCALP_POST_CLOSE_COOLDOWN_SEC,
)

logger = logging.getLogger(__name__)


class MarketCondition(Enum):
    """Market condition classification for scalp decisions."""

    TRENDING_UP = "trending_up"  # Strong upward momentum, hold longer
    TRENDING_DOWN = "trending_down"  # Strong downward momentum, hold longer
    CHOPPY = "choppy"  # High volatility swings, quick exit
    CALM = "calm"  # Low volatility, normal scalp
    UNKNOWN = "unknown"


class ScalpPnlService:
    """
    Service for intelligent unrealized profit scalping.

    This service analyzes market conditions and position PnL to decide:
    - When to take profit (exit positions)
    - Where to place next grid orders (follow momentum)
    - How aggressive to be based on volatility
    """

    def __init__(
        self,
        min_profit: float = SCALP_PNL_MIN_PROFIT,
        quick_profit: float = SCALP_PNL_QUICK_PROFIT,
        target_profit: float = SCALP_PNL_TARGET_PROFIT,
        max_target: float = SCALP_PNL_MAX_TARGET,
    ):
        """
        Initialize the scalp PnL service.

        Args:
            min_profit: Minimum profit to consider taking ($0.20 default)
            quick_profit: Quick profit target for choppy markets ($0.30 default)
            target_profit: Normal target profit ($0.60 default)
            max_target: Maximum profit target for strong trends ($1.00 default)
        """
        self.min_profit = min_profit
        self.quick_profit = quick_profit
        self.target_profit = target_profit
        self.max_target = max_target

        # Track recent price movements for swing detection
        self._price_history: Dict[str, List[float]] = {}
        self._last_directions: Dict[str, List[str]] = {}
        self._last_close_ts: Dict[str, float] = {}

    def adapt_targets_to_atr(self, atr_pct: float, investment: float, last_price: float) -> Dict[str, float]:
        """
        Dynamically scale profit targets based on ATR and position size.
        
        Low ATR (calm market) = lower TP targets = faster exits
        High ATR (volatile) = higher TP targets = ride the move
        
        Also scales with investment size - $5 investment can't target $0.60 profit.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if atr_pct is None or atr_pct <= 0:
            return {
                "min_profit": self.min_profit,
                "quick_profit": self.quick_profit,
                "target_profit": self.target_profit,
                "max_target": self.max_target,
            }
        
        # Base: ATR 1% = default targets ($0.30 quick, $0.60 target)
        # Scale linearly with ATR
        BASE_ATR = 0.01  # 1% ATR = baseline
        atr_ratio = atr_pct / BASE_ATR  # <1 = calm, >1 = volatile
        atr_ratio = max(0.15, min(3.0, atr_ratio))  # Clamp 0.15x to 3x
        
        # Also scale with investment size (smaller investment = smaller targets)
        # Base investment = $20. At $10 investment, targets should be ~2x smaller
        BASE_INVESTMENT = 20.0
        inv_ratio = max(0.1, min(2.0, investment / BASE_INVESTMENT))
        
        # Combined scaling factor
        scale = atr_ratio * inv_ratio
        
        targets = {
            "min_profit": max(0.01, 0.05 * scale),
            "quick_profit": max(0.03, 0.30 * scale),
            "target_profit": max(0.05, 0.60 * scale),
            "max_target": max(0.10, 1.00 * scale),
        }
        
        logger.debug(
            f"Scalp ATR-adaptive TP: ATR={atr_pct*100:.2f}%, inv=${investment:.0f}, "
            f"scale={scale:.2f}x -> min=${targets['min_profit']:.3f}, "
            f"quick=${targets['quick_profit']:.3f}, target=${targets['target_profit']:.3f}"
        )
        return targets

    def calculate_adaptive_min_profit(
        self,
        notional: float,
        spread_pct: float = 0.0,
        fee_pct: float = 0.0006,  # Default taker fee 0.06%
        base_min_profit: Optional[float] = None,
    ) -> float:
        """
        Calculate adaptive minimum profit based on fees and spread.

        001-trading-bot-audit FR-015: Fee-aware minimum profit calculation.

        Formula: max(config_min, notional * fee_pct * multiplier, spread_cost * 2)

        Args:
            notional: Trade notional value in USDT
            spread_pct: Current bid-ask spread as percentage
            fee_pct: Fee rate (e.g., 0.0006 for 0.06% taker fee)

        Returns:
            Minimum profit threshold in USDT
        """
        # Config minimum
        config_min = base_min_profit if base_min_profit is not None else self.min_profit

        # Fee-based minimum (round-trip fees with multiplier for safety margin)
        fee_cost = notional * fee_pct * 2  # Round-trip (open + close)
        fee_min = fee_cost * SCALP_FEE_MULTIPLIER

        # Spread-based minimum (avoid getting eaten by spread)
        spread_cost = notional * spread_pct
        spread_min = spread_cost * 2  # 2x spread for safety

        adaptive_min = max(config_min, fee_min, spread_min)

        logger.debug(
            "Adaptive min profit: config=%.2f, fee_min=%.2f (notional=%.0f, fee=%.4f%%), "
            "spread_min=%.2f (spread=%.4f%%) -> %.2f",
            config_min,
            fee_min,
            notional,
            fee_pct * 100,
            spread_min,
            spread_pct * 100,
            adaptive_min,
        )

        return adaptive_min

    def calculate_position_scaled_targets(
        self,
        position_notional: float,
        market_analysis: Optional[Dict[str, Any]] = None,
        base_targets: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Scale scalp profit targets by live position notional.

        The default fixed dollar targets are appropriate only for small
        positions. Larger live positions should require proportionally larger
        profits before closing.
        """
        safe_notional = max(float(position_notional or 0.0), 0.0)
        scale = 1.0
        if safe_notional > 0 and SCALP_PNL_BASE_POSITION_NOTIONAL_USDT > 0:
            scale = safe_notional / SCALP_PNL_BASE_POSITION_NOTIONAL_USDT
        scale = max(1.0, min(scale, SCALP_PNL_POSITION_SCALE_MAX))

        market_analysis = market_analysis or {}
        bt = base_targets or {
            "min_profit": self.min_profit,
            "quick_profit": self.quick_profit,
            "target_profit": self.target_profit,
            "max_target": self.max_target,
        }
        
        base_recommended = float(
            market_analysis.get("recommended_profit_target", bt["target_profit"])
            or bt["target_profit"]
        )

        scaled_min = max(bt["min_profit"], bt["min_profit"] * scale)
        scaled_quick = max(bt["quick_profit"], bt["quick_profit"] * scale)
        scaled_target = max(bt["target_profit"], bt["target_profit"] * scale)
        scaled_max = max(bt["max_target"], bt["max_target"] * scale)
        scaled_recommended = max(base_recommended * scale, scaled_min)

        return {
            "scale": scale,
            "min_profit": scaled_min,
            "quick_profit": scaled_quick,
            "target_profit": scaled_target,
            "max_target": scaled_max,
            "recommended_target": scaled_recommended,
            "position_notional": safe_notional,
        }

    def should_skip_trade(
        self,
        symbol: str,
        spread_pct: float,
        volume_24h: float = 0,
        regime: str = "neutral",
    ) -> Tuple[bool, str]:
        """
        Check if trade should be skipped due to poor market conditions.

        001-trading-bot-audit FR-016: No-trade state detection.

        Args:
            symbol: Trading symbol
            spread_pct: Current bid-ask spread as percentage
            volume_24h: 24h volume in USDT (0 = unknown)
            regime: Market regime (e.g., "neutral", "too_strong", "trending")

        Returns:
            Tuple of (should_skip: bool, reason: str)
        """
        # Check spread threshold
        if spread_pct > SCALP_SPREAD_THRESHOLD_PCT:
            return (
                True,
                f"Spread too wide: {spread_pct * 100:.3f}% > {SCALP_SPREAD_THRESHOLD_PCT * 100:.2f}%",
            )

        # Check regime
        if regime in ("too_strong", "extreme_trend"):
            return True, f"Regime too strong for scalp: {regime}"

        # Check volume (if provided) - skip very illiquid
        if volume_24h > 0 and volume_24h < 100000:  # Less than $100k daily volume
            return True, f"Volume too low: ${volume_24h:,.0f}"

        return False, ""

    def is_in_cooldown(self, symbol: str) -> Tuple[bool, float]:
        """
        Check if symbol is in post-close cooldown.

        001-trading-bot-audit FR-017: Post-close cooldown enforcement.

        Args:
            symbol: Trading symbol

        Returns:
            Tuple of (in_cooldown: bool, remaining_seconds: float)
        """
        import time

        last_close = self._last_close_ts.get(symbol, 0)
        elapsed = time.time() - last_close
        remaining = SCALP_POST_CLOSE_COOLDOWN_SEC - elapsed

        if remaining > 0:
            return True, remaining
        return False, 0

    def record_close(self, symbol: str) -> None:
        """
        Record a position close for cooldown tracking.

        Args:
            symbol: Trading symbol that was closed
        """
        import time

        self._last_close_ts[symbol] = time.time()
        logger.debug("[%s] Position close recorded, cooldown started", symbol)

    def analyze_market_condition(
        self,
        symbol: str,
        indicators: Dict[str, Any],
        recent_prices: Optional[List[float]] = None,
        base_targets: Optional[Dict[str, float]] = None,
    ) -> Tuple[MarketCondition, Dict[str, Any]]:
        """
        Analyze market conditions to determine scalp strategy.

        Args:
            symbol: Trading symbol
            indicators: Technical indicators dict from IndicatorService
            recent_prices: Optional list of recent close prices
            base_targets: Optional dynamically scaled targets dict

        Returns:
            Tuple of (MarketCondition, analysis_details_dict)
        """
        bt = base_targets or {
            "target_profit": self.target_profit,
            "quick_profit": self.quick_profit,
            "max_target": self.max_target,
        }

        analysis = {
            "condition": MarketCondition.UNKNOWN,
            "rsi": None,
            "adx": None,
            "atr_pct": None,
            "momentum_direction": None,  # "up", "down", "neutral"
            "momentum_strength": 0.0,  # 0-1 scale
            "volatility_level": "normal",  # "low", "normal", "high"
            "is_choppy": False,
            "recommended_profit_target": bt["target_profit"],
            "recommended_grid_distance": SCALP_PNL_NEAR_GRID_PCT,
            "should_follow_trend": True,
        }

        # Extract indicators
        rsi = indicators.get("rsi")
        adx = indicators.get("adx")
        atr_pct = indicators.get("atr_pct")
        macd_histogram = indicators.get("macd_histogram")
        ema_cross = indicators.get("ema_cross")
        price_vs_ema = indicators.get("price_vs_ema")
        volume_trend = indicators.get("volume_trend")

        analysis["rsi"] = rsi
        analysis["adx"] = adx
        analysis["atr_pct"] = atr_pct

        # =============================================================================
        # 1. VOLATILITY ANALYSIS
        # =============================================================================
        if atr_pct is not None:
            if atr_pct >= SCALP_PNL_HIGH_VOLATILITY_ATR:
                analysis["volatility_level"] = "high"
            elif atr_pct <= SCALP_PNL_LOW_VOLATILITY_ATR:
                analysis["volatility_level"] = "low"
            else:
                analysis["volatility_level"] = "normal"

        # =============================================================================
        # 2. SWING/CHOPPINESS DETECTION
        # =============================================================================
        is_choppy = self._detect_choppiness(symbol, recent_prices, indicators)
        analysis["is_choppy"] = is_choppy

        # =============================================================================
        # 3. MOMENTUM ANALYSIS
        # =============================================================================
        momentum_score = 0.0  # -1 to +1 scale

        # RSI contribution
        if rsi is not None:
            if rsi >= 60:
                momentum_score += 0.3 * ((rsi - 50) / 50)  # Bullish
            elif rsi <= 40:
                momentum_score -= 0.3 * ((50 - rsi) / 50)  # Bearish

        # MACD histogram contribution
        if macd_histogram is not None:
            if macd_histogram > 0:
                momentum_score += min(0.25, macd_histogram * 10)
            else:
                momentum_score += max(-0.25, macd_histogram * 10)

        # EMA cross contribution
        if ema_cross == "bullish":
            momentum_score += 0.2
        elif ema_cross == "bearish":
            momentum_score -= 0.2

        # Price vs EMA contribution
        if price_vs_ema == "above":
            momentum_score += 0.15
        elif price_vs_ema == "below":
            momentum_score -= 0.15

        # ADX amplifies momentum
        if adx is not None and adx >= 20:
            momentum_score *= 1 + (adx - 20) / 100

        # Normalize to -1 to +1
        momentum_score = max(-1.0, min(1.0, momentum_score))
        analysis["momentum_strength"] = abs(momentum_score)

        if momentum_score > 0.2:
            analysis["momentum_direction"] = "up"
        elif momentum_score < -0.2:
            analysis["momentum_direction"] = "down"
        else:
            analysis["momentum_direction"] = "neutral"

        # =============================================================================
        # 4. DETERMINE MARKET CONDITION
        # =============================================================================
        if is_choppy or (
            analysis["volatility_level"] == "high" and abs(momentum_score) < 0.3
        ):
            # High volatility with no clear direction = choppy
            analysis["condition"] = MarketCondition.CHOPPY
            analysis["recommended_profit_target"] = bt["quick_profit"]
            analysis["recommended_grid_distance"] = SCALP_PNL_NEAR_GRID_PCT
            analysis["should_follow_trend"] = False  # Just scalp both sides

        elif momentum_score >= 0.4 and adx is not None and adx >= 20:
            # Strong upward trend
            analysis["condition"] = MarketCondition.TRENDING_UP
            analysis["recommended_profit_target"] = bt["target_profit"]
            if momentum_score >= 0.6:
                analysis["recommended_profit_target"] = bt["max_target"]
            analysis["recommended_grid_distance"] = SCALP_PNL_FAR_GRID_PCT
            analysis["should_follow_trend"] = True

        elif momentum_score <= -0.4 and adx is not None and adx >= 20:
            # Strong downward trend
            analysis["condition"] = MarketCondition.TRENDING_DOWN
            analysis["recommended_profit_target"] = bt["target_profit"]
            if momentum_score <= -0.6:
                analysis["recommended_profit_target"] = bt["max_target"]
            analysis["recommended_grid_distance"] = SCALP_PNL_FAR_GRID_PCT
            analysis["should_follow_trend"] = True

        elif analysis["volatility_level"] == "low":
            # Low volatility, calm market
            analysis["condition"] = MarketCondition.CALM
            analysis["recommended_profit_target"] = bt["target_profit"]
            analysis["recommended_grid_distance"] = SCALP_PNL_NEAR_GRID_PCT
            analysis["should_follow_trend"] = True

        else:
            # Default: normal conditions
            analysis["condition"] = MarketCondition.CALM
            analysis["recommended_profit_target"] = (
                bt["quick_profit"] + (bt["target_profit"] - bt["quick_profit"]) / 2
            )
            analysis["recommended_grid_distance"] = (
                SCALP_PNL_NEAR_GRID_PCT + SCALP_PNL_FAR_GRID_PCT
            ) / 2
            analysis["should_follow_trend"] = True

        return analysis["condition"], analysis

    def should_take_profit(
        self,
        unrealized_pnl: float,
        market_analysis: Dict[str, Any],
        position_side: str,  # "Buy" or "Sell"
        position_age_seconds: Optional[float] = None,
        position_notional: float = 0.0,
        base_targets: Optional[Dict[str, float]] = None,
    ) -> Tuple[bool, str]:
        """
        Determine if we should take profit on a position.

        Args:
            unrealized_pnl: Current unrealized PnL in USDT
            market_analysis: Analysis dict from analyze_market_condition
            position_side: "Buy" (long) or "Sell" (short)
            position_age_seconds: How long position has been open

        Returns:
            Tuple of (should_exit, reason_string)
        """
        if unrealized_pnl <= 0:
            return False, "Position not in profit"

        scaled_targets = self.calculate_position_scaled_targets(
            position_notional=position_notional,
            market_analysis=market_analysis,
            base_targets=base_targets,
        )
        min_profit = scaled_targets["min_profit"]
        quick_profit = scaled_targets["quick_profit"]
        recommended_target = scaled_targets["recommended_target"]

        if unrealized_pnl < min_profit:
            return False, f"Below minimum profit ${min_profit:.2f}"

        condition = market_analysis.get("condition", MarketCondition.UNKNOWN)
        momentum_direction = market_analysis.get("momentum_direction")
        is_choppy = market_analysis.get("is_choppy", False)
        momentum_strength = market_analysis.get("momentum_strength", 0)

        # =============================================================================
        # CHOPPY MARKET: Take profit quickly
        # =============================================================================
        if is_choppy or condition == MarketCondition.CHOPPY:
            if unrealized_pnl >= quick_profit:
                return (
                    True,
                    f"Choppy market - taking quick profit ${unrealized_pnl:.2f}",
                )

        # =============================================================================
        # TRENDING MARKET: Hold longer if momentum aligns with position
        # =============================================================================
        if condition in (MarketCondition.TRENDING_UP, MarketCondition.TRENDING_DOWN):
            position_aligned = (
                condition == MarketCondition.TRENDING_UP and position_side == "Buy"
            ) or (
                condition == MarketCondition.TRENDING_DOWN and position_side == "Sell"
            )

            if position_aligned:
                # Position aligned with trend — HOLD LONGER
                if unrealized_pnl >= recommended_target:
                    return (
                        True,
                        f"Taking trend profit ${unrealized_pnl:.2f} (target: ${recommended_target:.2f})",
                    )
            else:
                # Position against trend — exit early
                if unrealized_pnl >= quick_profit:
                    return (
                        True,
                        f"Taking quick profit ${unrealized_pnl:.2f} (position against trend)",
                    )

        # =============================================================================
        # NORMAL MARKET: Standard profit taking
        # =============================================================================
        if unrealized_pnl >= recommended_target:
            return (
                True,
                f"Hit target profit ${unrealized_pnl:.2f} (target: ${recommended_target:.2f})",
            )

        # Progressive profit taking after passing minimum
        if unrealized_pnl >= min_profit:
            # Calculate dynamic threshold based on how far we are from target
            denom = max(recommended_target - min_profit, 1e-9)
            progress = (unrealized_pnl - min_profit) / denom

            # If we're more than 50% to target and momentum is weak, take it
            if progress >= 0.5 and momentum_strength < 0.3:
                return (
                    True,
                    f"Taking profit ${unrealized_pnl:.2f} (weak momentum, {progress * 100:.0f}% to target)",
                )

            # If position is old (>2 min) and in profit, be more willing to exit
            if (
                position_age_seconds
                and position_age_seconds > 60
                and unrealized_pnl >= min_profit
            ):
                return (
                    True,
                    f"Taking aged profit ${unrealized_pnl:.2f} (position {position_age_seconds:.0f}s old)",
                )

        return (
            False,
            f"Waiting for target (current: ${unrealized_pnl:.2f}, target: ${recommended_target:.2f})",
        )

    def get_scalp_grid_levels(
        self,
        last_price: float,
        market_analysis: Dict[str, Any],
        tick_size: float,
        grid_count: int = 0,
        force_balanced: bool = False,
    ) -> Tuple[List[float], List[float]]:
        """
        Get grid levels optimized for scalp mode.

        Places orders close to current price using the specified grid_count.

        Args:
            last_price: Current market price (or grid center)
            market_analysis: Analysis dict from analyze_market_condition
            tick_size: Price tick size for rounding
            grid_count: Number of grid levels to generate (0 = default 10)
            force_balanced: Ignore momentum skew and split levels evenly

        Returns:
            Tuple of (buy_levels, sell_levels)
        """
        grid_distance = market_analysis.get(
            "recommended_grid_distance", SCALP_PNL_NEAR_GRID_PCT
        )
        momentum_direction = market_analysis.get("momentum_direction", "neutral")

        # Use grid_count from bot settings, default to 10 if not specified
        total_levels = grid_count if grid_count > 0 else 10

        # Split between buy and sell based on momentum
        if force_balanced:
            num_buys = total_levels // 2
            num_sells = total_levels - num_buys
        elif momentum_direction == "up":
            # Trending up: more buys to catch dips
            num_buys = int(total_levels * 0.6)
            num_sells = total_levels - num_buys
        elif momentum_direction == "down":
            # Trending down: more sells to catch rallies
            num_sells = int(total_levels * 0.6)
            num_buys = total_levels - num_sells
        else:
            # Neutral: split evenly
            num_buys = total_levels // 2
            num_sells = total_levels - num_buys

        buy_levels = []
        sell_levels = []

        # =============================================================================
        # Generate grid levels at fixed intervals from center price
        # =============================================================================

        # Generate buy levels (below price)
        for i in range(1, num_buys + 1):
            level = last_price * (1 - grid_distance * i)
            buy_levels.append(level)

        # Generate sell levels (above price)
        for i in range(1, num_sells + 1):
            level = last_price * (1 + grid_distance * i)
            sell_levels.append(level)

        # Round to tick size
        buy_levels = [
            self._round_to_tick(p, tick_size, round_down=True) for p in buy_levels
        ]
        sell_levels = [
            self._round_to_tick(p, tick_size, round_down=False) for p in sell_levels
        ]

        # Sort and dedupe
        buy_levels = sorted(set(buy_levels), reverse=True)
        sell_levels = sorted(set(sell_levels))

        return buy_levels, sell_levels

    def get_recommended_side(
        self,
        market_analysis: Dict[str, Any],
    ) -> Optional[str]:
        """
        Get recommended position side based on market analysis.

        Args:
            market_analysis: Analysis dict from analyze_market_condition

        Returns:
            "Buy", "Sell", or None (for neutral/both sides)
        """
        condition = market_analysis.get("condition")
        momentum_direction = market_analysis.get("momentum_direction")
        is_choppy = market_analysis.get("is_choppy", False)

        if is_choppy or condition == MarketCondition.CHOPPY:
            return None  # Trade both sides in choppy markets

        if condition == MarketCondition.TRENDING_UP and momentum_direction == "up":
            return "Buy"
        elif (
            condition == MarketCondition.TRENDING_DOWN and momentum_direction == "down"
        ):
            return "Sell"

        return None  # Neutral, trade both sides

    def _detect_choppiness(
        self,
        symbol: str,
        recent_prices: Optional[List[float]],
        indicators: Dict[str, Any],
    ) -> bool:
        """
        Detect if market is choppy (swinging up and down frequently).

        Args:
            symbol: Trading symbol
            recent_prices: List of recent close prices
            indicators: Technical indicators

        Returns:
            True if market is choppy
        """
        # Method 1: ADX-based choppiness
        adx = indicators.get("adx")
        if adx is not None and adx < 15:
            return True  # Low ADX = no clear trend = choppy

        # Method 2: Price swing detection
        if recent_prices and len(recent_prices) >= SCALP_PNL_SWING_LOOKBACK:
            prices = recent_prices[-SCALP_PNL_SWING_LOOKBACK:]
            direction_changes = 0

            for i in range(2, len(prices)):
                # Compare direction of previous move vs current move
                prev_direction = "up" if prices[i - 1] > prices[i - 2] else "down"
                curr_direction = "up" if prices[i] > prices[i - 1] else "down"

                if prev_direction != curr_direction:
                    direction_changes += 1

            if direction_changes >= SCALP_PNL_SWING_THRESHOLD:
                return True  # Many direction changes = choppy

        # Method 3: Check if RSI is bouncing around middle
        rsi = indicators.get("rsi")
        if rsi is not None and 45 <= rsi <= 55:
            # RSI in dead zone with high volatility = choppy
            atr_pct = indicators.get("atr_pct")
            if atr_pct and atr_pct >= SCALP_PNL_HIGH_VOLATILITY_ATR * 0.8:
                return True

        return False

    def _round_to_tick(
        self, price: float, tick_size: float, round_down: bool = True
    ) -> float:
        """Round price to tick size."""
        if tick_size <= 0:
            return price

        import math

        if round_down:
            result = math.floor(price / tick_size) * tick_size
        else:
            result = math.ceil(price / tick_size) * tick_size

        # Determine precision from tick_size
        tick_str = f"{tick_size:.10f}".rstrip("0")
        precision = len(tick_str.split(".")[1]) if "." in tick_str else 0

        return round(result, precision)

    def update_price_history(self, symbol: str, price: float) -> None:
        """
        Update price history for swing detection.

        Args:
            symbol: Trading symbol
            price: Current price
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = []

        self._price_history[symbol].append(price)

        # Keep only last 20 prices
        if len(self._price_history[symbol]) > 20:
            self._price_history[symbol] = self._price_history[symbol][-20:]

    def get_price_history(self, symbol: str) -> List[float]:
        """Get price history for a symbol."""
        return self._price_history.get(symbol, [])

