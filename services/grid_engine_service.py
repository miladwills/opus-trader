"""
Bybit Control Center - Grid Engine Service

Builds discrete grid levels for grid trading strategies.
Enhanced with grid mode variations: buy_heavy, sell_heavy, clustered.
"""

import logging
import math
from typing import List, Optional, Dict, Any, Tuple
from config.strategy_config import GRID_STEP_PCT

logger = logging.getLogger(__name__)


class GridEngineService:
    """
    Service for computing grid trading levels.
    """

    def __init__(self, grid_step_pct: float = GRID_STEP_PCT):
        """
        Initialize the grid engine service.

        Args:
            grid_step_pct: Percentage step between grid levels (e.g., 0.0037 for 0.37%)
        """
        self.grid_step_pct = grid_step_pct

    def build_levels(
        self,
        lower: float,
        upper: float,
        grid_step_pct: Optional[float] = None,
    ) -> List[float]:
        """
        Build a list of price levels from lower to upper using geometric spacing.

        The levels are spaced by multiplying each level by (1 + step).
        This ensures consistent percentage distance between levels.

        Args:
            lower: Lower bound of the grid
            upper: Upper bound of the grid
            grid_step_pct: Optional per-call step override. If None, use self.grid_step_pct.

        Returns:
            List of price levels sorted ascending, empty list if invalid bounds
        """
        # Use provided step or fall back to instance default
        step = grid_step_pct if grid_step_pct is not None else self.grid_step_pct

        # Validate inputs
        if lower <= 0 or upper <= lower or step <= 0:
            return []

        levels = []
        multiplier = 1.0 + step

        # Start at lower bound
        price = lower
        levels.append(price)

        # Build levels geometrically
        while True:
            next_price = price * multiplier

            # Check if we've reached or exceeded upper bound
            if next_price >= upper:
                # Add the upper bound as final level if not already close
                if levels[-1] < upper * 0.9999:  # Avoid duplicates
                    levels.append(upper)
                break

            levels.append(next_price)
            price = next_price

            # Safety limit to prevent infinite loops
            if len(levels) > 10000:
                break

        # Round to 8 decimal places and ensure sorted
        levels = [round(level, 8) for level in levels]

        # Deduplicate and sort
        unique = sorted(set(levels))
        return unique

    def estimate_grid_count(
        self,
        lower: float,
        upper: float,
        grid_step_pct: Optional[float] = None,
    ) -> int:
        """
        Estimate the number of grid levels for given bounds.

        Args:
            lower: Lower bound of the grid
            upper: Upper bound of the grid
            grid_step_pct: Optional per-call step override.

        Returns:
            Number of grid levels
        """
        return len(self.build_levels(lower, upper, grid_step_pct=grid_step_pct))

    def _clamp_reference_price(
        self,
        lower: float,
        upper: float,
        current_price: float,
    ) -> float:
        if current_price <= lower:
            return lower
        if current_price >= upper:
            return upper
        return current_price

    def _allocate_side_counts(
        self,
        total_levels: int,
        lower: float,
        upper: float,
        reference_price: float,
        buy_bias: float = 1.0,
        sell_bias: float = 1.0,
    ) -> Tuple[int, int]:
        if total_levels <= 0:
            return 0, 0

        ref = self._clamp_reference_price(lower, upper, reference_price)
        buy_span = math.log(ref / lower) if ref > lower > 0 else 0.0
        sell_span = math.log(upper / ref) if upper > ref > 0 else 0.0

        if buy_span <= 0 and sell_span <= 0:
            return total_levels, 0
        if buy_span <= 0:
            return 0, total_levels
        if sell_span <= 0:
            return total_levels, 0

        buy_weight = buy_span * max(float(buy_bias), 0.01)
        sell_weight = sell_span * max(float(sell_bias), 0.01)
        total_weight = buy_weight + sell_weight
        if total_weight <= 0:
            buy_count = total_levels // 2
        else:
            buy_count = int(round(total_levels * (buy_weight / total_weight)))

        if total_levels == 1:
            return (1, 0) if buy_count >= 1 else (0, 1)

        buy_count = max(1, min(total_levels - 1, buy_count))
        sell_count = total_levels - buy_count
        return buy_count, sell_count

    def _build_segment_levels(
        self,
        lower: float,
        upper: float,
        count: int,
        side: str,
        cluster_concentration: float = 0.0,
    ) -> List[float]:
        if count <= 0 or lower <= 0 or upper <= lower:
            return []

        log_lower = math.log(lower)
        log_upper = math.log(upper)
        concentration = max(0.0, min(float(cluster_concentration or 0.0), 1.0))
        gamma = 1.0 + (concentration * 2.0)
        levels: List[float] = []

        for idx in range(count):
            if count == 1:
                base_fraction = 0.5
            elif side == "buy":
                base_fraction = idx / count
            else:
                base_fraction = (idx + 1) / count

            if concentration > 0:
                if side == "buy":
                    fraction = 1.0 - math.pow(1.0 - base_fraction, gamma)
                else:
                    fraction = math.pow(base_fraction, gamma)
            else:
                fraction = base_fraction

            fraction = max(0.0, min(1.0, fraction))
            level = math.exp(log_lower + ((log_upper - log_lower) * fraction))
            levels.append(round(level, 8))

        return levels

    def _restore_level_budget(
        self,
        levels: List[float],
        base_levels: List[float],
        target_total: int,
        lower: float,
        upper: float,
    ) -> List[float]:
        restored = sorted(
            {
                round(level, 8)
                for level in levels
                if lower <= level <= upper
            }
        )
        if len(restored) >= target_total:
            return restored[:target_total]

        existing = set(restored)
        for level in base_levels:
            rounded = round(level, 8)
            if rounded < lower or rounded > upper or rounded in existing:
                continue
            restored.append(rounded)
            existing.add(rounded)
            if len(restored) >= target_total:
                break

        return sorted(restored)

    def build_levels_with_distribution(
        self,
        lower: float,
        upper: float,
        current_price: float,
        distribution: str = "balanced",
        grid_step_pct: Optional[float] = None,
        buy_sell_ratio: float = 1.5,
        cluster_concentration: float = 0.70,
    ) -> Dict[str, Any]:
        """
        Build grid levels with different distribution patterns.

        Distribution modes:
        - "balanced": Equal spacing (default, same as build_levels)
        - "buy_heavy": More buy orders (below price) than sell orders (bullish bias)
        - "sell_heavy": More sell orders (above price) than buy orders (bearish bias)
        - "clustered": Orders concentrated near current price, fewer at extremes

        Args:
            lower: Lower bound of the grid
            upper: Upper bound of the grid
            current_price: Current market price (for splitting buy/sell and clustering)
            distribution: Distribution mode ("balanced", "buy_heavy", "sell_heavy", "clustered")
            grid_step_pct: Optional per-call step override
            buy_sell_ratio: Ratio for heavy modes (e.g., 1.5 = 60% buy, 40% sell)
            cluster_concentration: Concentration factor for clustered mode (0-1)

        Returns:
            Dict with:
            - levels: List[float] (all price levels)
            - buy_levels: List[float] (levels below current price)
            - sell_levels: List[float] (levels above current price)
            - distribution: str (mode used)
            - total_count: int
            - buy_count: int
            - sell_count: int
        """
        step = grid_step_pct if grid_step_pct is not None else self.grid_step_pct
        distribution_lower = distribution.lower()
        base_levels = self.build_levels(lower, upper, grid_step_pct=step)
        if not base_levels:
            return {
                "levels": [],
                "buy_levels": [],
                "sell_levels": [],
                "distribution": "balanced",
                "total_count": 0,
                "buy_count": 0,
                "sell_count": 0,
            }

        target_total = len(base_levels)
        reference_price = self._clamp_reference_price(lower, upper, current_price)

        # Balanced distribution (default)
        if distribution_lower == "balanced":
            levels = base_levels
            buy_levels = [l for l in levels if l < current_price]
            sell_levels = [l for l in levels if l > current_price]

            return {
                "levels": levels,
                "buy_levels": buy_levels,
                "sell_levels": sell_levels,
                "distribution": "balanced",
                "total_count": len(levels),
                "buy_count": len(buy_levels),
                "sell_count": len(sell_levels),
            }

        # Buy-heavy distribution (bullish bias)
        elif distribution_lower == "buy_heavy":
            buy_count, sell_count = self._allocate_side_counts(
                target_total,
                lower,
                upper,
                reference_price,
                buy_bias=buy_sell_ratio,
                sell_bias=1.0,
            )
            buy_levels = self._build_segment_levels(
                lower,
                reference_price,
                buy_count,
                "buy",
            )
            sell_levels = self._build_segment_levels(
                reference_price,
                upper,
                sell_count,
                "sell",
            )
            levels = self._restore_level_budget(
                buy_levels + sell_levels,
                base_levels,
                target_total,
                lower,
                upper,
            )
            buy_levels = [l for l in levels if l < current_price]
            sell_levels = [l for l in levels if l > current_price]

            logger.debug(
                f"Buy-heavy grid: {len(buy_levels)} buy levels, "
                f"{len(sell_levels)} sell levels (base_total={target_total})"
            )

            return {
                "levels": levels,
                "buy_levels": buy_levels,
                "sell_levels": sell_levels,
                "distribution": "buy_heavy",
                "total_count": len(levels),
                "buy_count": len(buy_levels),
                "sell_count": len(sell_levels),
                "buy_sell_ratio": len(buy_levels) / max(len(sell_levels), 1),
            }

        # Sell-heavy distribution (bearish bias)
        elif distribution_lower == "sell_heavy":
            buy_count, sell_count = self._allocate_side_counts(
                target_total,
                lower,
                upper,
                reference_price,
                buy_bias=1.0,
                sell_bias=buy_sell_ratio,
            )
            buy_levels = self._build_segment_levels(
                lower,
                reference_price,
                buy_count,
                "buy",
            )
            sell_levels = self._build_segment_levels(
                reference_price,
                upper,
                sell_count,
                "sell",
            )
            levels = self._restore_level_budget(
                buy_levels + sell_levels,
                base_levels,
                target_total,
                lower,
                upper,
            )
            buy_levels = [l for l in levels if l < current_price]
            sell_levels = [l for l in levels if l > current_price]

            logger.debug(
                f"Sell-heavy grid: {len(buy_levels)} buy levels, "
                f"{len(sell_levels)} sell levels (base_total={target_total})"
            )

            return {
                "levels": levels,
                "buy_levels": buy_levels,
                "sell_levels": sell_levels,
                "distribution": "sell_heavy",
                "total_count": len(levels),
                "buy_count": len(buy_levels),
                "sell_count": len(sell_levels),
                "buy_sell_ratio": len(buy_levels) / max(len(sell_levels), 1),
            }

        # Clustered distribution (orders concentrated near price)
        elif distribution_lower == "clustered":
            buy_count, sell_count = self._allocate_side_counts(
                target_total,
                lower,
                upper,
                reference_price,
            )
            buy_levels = self._build_segment_levels(
                lower,
                reference_price,
                buy_count,
                "buy",
                cluster_concentration=cluster_concentration,
            )
            sell_levels = self._build_segment_levels(
                reference_price,
                upper,
                sell_count,
                "sell",
                cluster_concentration=cluster_concentration,
            )
            clustered_levels = self._restore_level_budget(
                buy_levels + sell_levels,
                base_levels,
                target_total,
                lower,
                upper,
            )
            buy_levels = [l for l in clustered_levels if l < current_price]
            sell_levels = [l for l in clustered_levels if l > current_price]

            logger.debug(
                f"Clustered grid: {len(clustered_levels)} levels (from {len(base_levels)} base), "
                f"concentration={cluster_concentration}"
            )

            return {
                "levels": clustered_levels,
                "buy_levels": buy_levels,
                "sell_levels": sell_levels,
                "distribution": "clustered",
                "total_count": len(clustered_levels),
                "buy_count": len(buy_levels),
                "sell_count": len(sell_levels),
                "concentration": cluster_concentration,
            }

        # Unknown distribution - fallback to balanced
        else:
            logger.warning(f"Unknown grid distribution '{distribution}', falling back to balanced")
            return self.build_levels_with_distribution(
                lower=lower,
                upper=upper,
                current_price=current_price,
                distribution="balanced",
                grid_step_pct=step,
            )
