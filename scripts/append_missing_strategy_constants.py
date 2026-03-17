#!/usr/bin/env python3
"""
Safely append missing strategy constants required by newer services.

Behavior:
- Does not overwrite existing constants (preserves tuned values).
- Appends only constants that are missing.
- Creates a timestamped backup before writing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

TARGET_PATH = Path("/var/www/config/strategy_config.py")

SESSION_NAMES = [
    "SESSION_TRADING_ENABLED",
    "SESSION_MAX_SCORE",
    "SESSION_REDUCE_WEEKEND",
    "SESSION_WEEKEND_SIZE_MULT",
    "SESSION_USE_VOLATILITY_ADJUST",
]

MEAN_REVERSION_NAMES = [
    "MEAN_REVERSION_ENABLED",
    "MEAN_REVERSION_EMA_PERIODS",
    "MEAN_REVERSION_EXTREME_PCT",
    "MEAN_REVERSION_STRONG_PCT",
    "MEAN_REVERSION_MODERATE_PCT",
    "MEAN_REVERSION_MAX_SCORE",
    "MEAN_REVERSION_USE_BB",
    "MEAN_REVERSION_USE_RSI",
]

WHALE_NAMES = [
    "WHALE_DETECTION_ENABLED",
    "WHALE_THRESHOLD_USD",
    "WHALE_PROXIMITY_PCT",
    "WHALE_MAX_SCORE",
    "WHALE_CACHE_SECONDS",
]

SMART_PAUSE_NAMES = [
    "SMART_PAUSE_RECOVERY_ENABLED",
    "SMART_PAUSE_WAIT_FOR_PROFIT",
    "SMART_PAUSE_MIN_PROFIT_PCT",
    "SMART_PAUSE_MAX_WAIT_HOURS",
    "SMART_PAUSE_AUTO_RESUME",
    "SMART_PAUSE_CHECK_INTERVAL",
]

EMERGENCY_PARTIAL_CLOSE_NAMES = [
    "EMERGENCY_PARTIAL_CLOSE_ENABLED",
    "EMERGENCY_PARTIAL_CLOSE_LIQ_PCT",
    "EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT",
    "EMERGENCY_PARTIAL_CLOSE_QTY_PCT",
    "EMERGENCY_PARTIAL_CLOSE_MIN_BALANCE",
    "EMERGENCY_PARTIAL_CLOSE_PCT",
    "EMERGENCY_PARTIAL_CLOSE_TIER2_PCT",
    "EMERGENCY_PARTIAL_CLOSE_COOLDOWN",
    "EMERGENCY_PARTIAL_CLOSE_MAX_COUNT",
]

BLOCKS = [
    ("SESSION", SESSION_NAMES),
    ("MEAN_REVERSION", MEAN_REVERSION_NAMES),
    ("WHALE", WHALE_NAMES),
    ("SMART_PAUSE", SMART_PAUSE_NAMES),
    ("EMERGENCY_PARTIAL_CLOSE", EMERGENCY_PARTIAL_CLOSE_NAMES),
]

DEFINITIONS = {
    "SESSION_TRADING_ENABLED": "SESSION_TRADING_ENABLED = True  # Master toggle",
    "SESSION_MAX_SCORE": "SESSION_MAX_SCORE = 10  # Max +/- points from session analysis",
    "SESSION_REDUCE_WEEKEND": "SESSION_REDUCE_WEEKEND = True  # Reduce position size on weekends",
    "SESSION_WEEKEND_SIZE_MULT": "SESSION_WEEKEND_SIZE_MULT = 0.8  # Position size multiplier for weekends",
    "SESSION_USE_VOLATILITY_ADJUST": "SESSION_USE_VOLATILITY_ADJUST = True  # Adjust grid spacing by session volatility",
    "MEAN_REVERSION_ENABLED": "MEAN_REVERSION_ENABLED = True  # Master toggle",
    "MEAN_REVERSION_EMA_PERIODS": "MEAN_REVERSION_EMA_PERIODS = [20, 50, 100, 200]  # EMAs to analyze",
    "MEAN_REVERSION_EXTREME_PCT": "MEAN_REVERSION_EXTREME_PCT = 3.0  # 3% deviation = extreme",
    "MEAN_REVERSION_STRONG_PCT": "MEAN_REVERSION_STRONG_PCT = 2.0  # 2% deviation = strong signal",
    "MEAN_REVERSION_MODERATE_PCT": "MEAN_REVERSION_MODERATE_PCT = 1.0  # 1% deviation = moderate signal",
    "MEAN_REVERSION_MAX_SCORE": "MEAN_REVERSION_MAX_SCORE = 15  # Max +/- points from mean reversion",
    "MEAN_REVERSION_USE_BB": "MEAN_REVERSION_USE_BB = True  # Also check Bollinger Band position",
    "MEAN_REVERSION_USE_RSI": "MEAN_REVERSION_USE_RSI = True  # Confirm with RSI overbought/oversold",
    "WHALE_DETECTION_ENABLED": "WHALE_DETECTION_ENABLED = True  # Master toggle",
    "WHALE_THRESHOLD_USD": "WHALE_THRESHOLD_USD = 50000  # Minimum USD value for \"whale\" order ($50K)",
    "WHALE_PROXIMITY_PCT": "WHALE_PROXIMITY_PCT = 2.0  # Max distance from price to consider (2%)",
    "WHALE_MAX_SCORE": "WHALE_MAX_SCORE = 20  # Max +/- points from whale detection",
    "WHALE_CACHE_SECONDS": "WHALE_CACHE_SECONDS = 5  # Cache duration (fast-moving data)",
    "SMART_PAUSE_RECOVERY_ENABLED": "SMART_PAUSE_RECOVERY_ENABLED = True  # Master toggle",
    "SMART_PAUSE_WAIT_FOR_PROFIT": "SMART_PAUSE_WAIT_FOR_PROFIT = True  # Wait for position to be profitable",
    "SMART_PAUSE_MIN_PROFIT_PCT": "SMART_PAUSE_MIN_PROFIT_PCT = 0.3  # Min profit % to close (0.3%)",
    "SMART_PAUSE_MAX_WAIT_HOURS": "SMART_PAUSE_MAX_WAIT_HOURS = 24  # Max hours to wait for recovery",
    "SMART_PAUSE_AUTO_RESUME": "SMART_PAUSE_AUTO_RESUME = True  # Auto-resume when reason resolves",
    "SMART_PAUSE_CHECK_INTERVAL": "SMART_PAUSE_CHECK_INTERVAL = 30  # Seconds between recovery checks",
    "EMERGENCY_PARTIAL_CLOSE_ENABLED": "EMERGENCY_PARTIAL_CLOSE_ENABLED = True  # Master toggle",
    "EMERGENCY_PARTIAL_CLOSE_LIQ_PCT": (
        "EMERGENCY_PARTIAL_CLOSE_LIQ_PCT = (\n"
        "    12.0  # Tier 1: Trigger when liq distance < 12% (increased from 10%)\n"
        ")"
    ),
    "EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT": (
        "EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT = (\n"
        "    4.0  # Tier 2: Trigger when liq distance < 4% (less aggressive)\n"
        ")"
    ),
    "EMERGENCY_PARTIAL_CLOSE_QTY_PCT": "EMERGENCY_PARTIAL_CLOSE_QTY_PCT = 0.5  # Reduce position by 50% on each trigger",
    "EMERGENCY_PARTIAL_CLOSE_MIN_BALANCE": (
        "EMERGENCY_PARTIAL_CLOSE_MIN_BALANCE = (\n"
        "    1.5  # Trigger if available < AUTO_MARGIN_RESERVE_USDT\n"
        ")"
    ),
    "EMERGENCY_PARTIAL_CLOSE_PCT": "EMERGENCY_PARTIAL_CLOSE_PCT = 20.0  # Tier 1: Close 20% of position",
    "EMERGENCY_PARTIAL_CLOSE_TIER2_PCT": "EMERGENCY_PARTIAL_CLOSE_TIER2_PCT = 35.0  # Tier 2: Close 35% of position",
    "EMERGENCY_PARTIAL_CLOSE_COOLDOWN": "EMERGENCY_PARTIAL_CLOSE_COOLDOWN = 60  # Seconds between partial closes",
    "EMERGENCY_PARTIAL_CLOSE_MAX_COUNT": "EMERGENCY_PARTIAL_CLOSE_MAX_COUNT = 10  # Death spiral protection: max closes before full close + stop",
}

ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]+)\s*(?::[^=]+)?=", re.MULTILINE)


def get_defined_names(config_text: str) -> set[str]:
    return {m.group(1) for m in ASSIGNMENT_RE.finditer(config_text)}


def build_append_text(missing_names: set[str]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [
        "",
        "# =============================================================================",
        f"# AUTO-APPENDED MISSING FEATURE CONSTANTS ({timestamp})",
        "# =============================================================================",
    ]

    for block_title, ordered_names in BLOCKS:
        block_missing = [name for name in ordered_names if name in missing_names]
        if not block_missing:
            continue
        parts.extend(["", f"# {block_title} (auto-appended)"])
        parts.extend(DEFINITIONS[name] for name in block_missing)

    return "\n".join(parts) + "\n"


def main() -> int:
    if not TARGET_PATH.exists():
        raise FileNotFoundError(f"Target file not found: {TARGET_PATH}")

    original = TARGET_PATH.read_text(encoding="utf-8")
    defined_names = get_defined_names(original)

    ordered_targets = [name for _, names in BLOCKS for name in names]
    missing = [name for name in ordered_targets if name not in defined_names]

    if not missing:
        print("No missing constants found. No changes made.")
        return 0

    backup_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = TARGET_PATH.with_suffix(TARGET_PATH.suffix + f".bak_{backup_suffix}")
    backup_path.write_text(original, encoding="utf-8")

    append_text = build_append_text(set(missing))
    with TARGET_PATH.open("a", encoding="utf-8") as f:
        if not original.endswith("\n"):
            f.write("\n")
        f.write(append_text)

    print(f"Backup created: {backup_path}")
    print(f"Appended {len(missing)} missing constants:")
    for name in missing:
        print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
