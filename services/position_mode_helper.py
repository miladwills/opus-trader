"""
Utilities for mapping Bybit position mode (hedge vs one-way) to positionIdx.
"""

from typing import Optional


def resolve_position_idx(position_mode: Optional[str], side: str, reduce_only: bool) -> Optional[int]:
    """
    Map (mode, side, reduce_only) -> positionIdx expected by Bybit.

    - Hedge mode:
        * Opening: Buy -> 1 (long leg), Sell -> 2 (short leg)
        * Reduce-only: Buy closes short -> 2, Sell closes long -> 1
    - One-way: return None (omit positionIdx or use 0)

    Args:
        position_mode: "hedge" or "one_way"
        side: "Buy" or "Sell"
        reduce_only: True if the order is reduce-only

    Returns:
        positionIdx (int) or None if one-way/unknown
    """
    if not position_mode or position_mode == "one_way":
        return None

    side_lower = side.lower()
    if position_mode == "hedge":
        if side_lower == "buy":
            return 2 if reduce_only else 1
        if side_lower == "sell":
            return 1 if reduce_only else 2

    return None
