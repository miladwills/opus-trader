"""
Bybit Control Center - Strategy Configuration

Contains strategy and risk management constants for grid trading.
"""

import os
from typing import Dict, Any

# =============================================================================
# Runner Loop Timing (NEW - Part 2)
# =============================================================================
# Fast risk check for UPnL SL, slower full grid cycle for order management
GRID_TICK_SECONDS = 2  # Full bot cycle interval — fast enough for responsive trading
RISK_TICK_SECONDS = 1  # Fast risk check interval (UPnL SL only)

# =============================================================================
# Multi-Timeframe Data (Fast Execution + Regime)
# =============================================================================
EXECUTION_TF = "1m"
REGIME_TF_PRIMARY = "15m"
REGIME_TF_SECONDARY = "5m"

INDICATOR_CACHE_TTL_1M = 15  # Fresh 1m data for momentum checks
INDICATOR_CACHE_TTL_5M15M = 45  # Fresh enough for 5m fast trigger + 15m scoring

# Grid trading parameters
GRID_STEP_PCT = 0.0037  # 0.37% per level

# Default leverage and investment
DEFAULT_LEVERAGE = 3
DEFAULT_INVESTMENT_USDT = 50.0

# Small capital adaptive tuning (opt-in)
SMALL_CAPITAL_MODE_ENABLED = True
SMALL_CAPITAL_INVEST_USDT_THRESHOLD = 50
SMALL_CAPITAL_PARTIAL_TP_MAX_SKIPS = 3
SMALL_CAPITAL_SYMBOL_PROFILES = {
    "ETHUSDT": "ETH",
    "BTCUSDT": "MAJOR",
    "BNBUSDT": "MAJOR",
    "SOLUSDT": "MAJOR",
    "XRPUSDT": "MAJOR",
    "ADAUSDT": "MAJOR",
    "DOTUSDT": "MAJOR",
    "LINKUSDT": "MAJOR",
    "AVAXUSDT": "MAJOR",
    "UNIUSDT": "MAJOR",
    "SUIUSDT": "MAJOR",
    "ICPUSDT": "MAJOR",
    "TAOUSDT": "MAJOR",
    "SEIUSDT": "MAJOR",
    "TRXUSDT": "MAJOR",
    "HYPEUSDT": "MAJOR",
}
SMALL_CAPITAL_DEFAULT_PROFILE = "ALTCOIN"
SMALL_CAPITAL_AUTO_MARGIN_CAPS = {
    "MEME": 0.0,
}

# Auto margin reserve - leave this amount available for auto margin feature
AUTO_MARGIN_RESERVE_USDT = 1.5  # Fixed reserve (used if % is disabled)
AUTO_MARGIN_RESERVE_PCT = 0.15  # Reserve 15% of investment for margin buffer
AUTO_MARGIN_RESERVE_USE_PCT = True  # Use percentage-based reserve (recommended)
OPENING_MARGIN_VIABILITY_RESERVE_PCT = (
    0.10  # Opening viability uses a lighter 10% reserve before exchange-side checks.
)
OPENING_MARGIN_VIABILITY_RESERVE_CAP_USDT = (
    12.0  # Bound the opening-only reserve so large bots are not over-throttled.
)

# Critical liquidation threshold - cancel far orders when liq distance drops below this
CRITICAL_LIQ_PCT = 10.0  # Decreased from 20.0 to prevent premature panic
CRITICAL_LIQ_RECOVERY_TARGET_PCT = 15.0  # Minimum liq distance to restore during emergency auto-margin recovery (was 8.0 — too close to 10% trigger, caused oscillation)

# Risk management limits
MAX_BOT_LOSS_PCT = 0.15  # 15% max loss per bot
MAX_DAILY_LOSS_PCT = 0.08  # 8% daily drawdown limit

# Position size cap - prevents position from exceeding planned notional
MAX_POSITION_PCT = (
    0.85  # Max position can be 85% of planned notional (investment × leverage)
)
DIRECTIONAL_MAX_POSITION_PCT = (
    0.90  # Directional opening adds can use a modestly higher cap than neutral/range modes.
)
MAX_POSITION_ENABLED = True  # Enable position size cap to prevent over-extension
EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_ENABLED = (
    True  # Enabled: bounded extra directional cap headroom for only strong trigger-ready continuation/trend cases.
)
EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_BONUS_PCT = (
    0.02  # Add at most 2% extra headroom when the experimental directional cap is enabled.
)
EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_SCORE_MIN = (
    74.0  # Require strong setup quality before granting experimental cap headroom.
)
EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_HARD_CEILING_PCT = (
    0.93  # Absolute experimental ceiling so directional cap stays well below full notional.
)
EXPERIMENTAL_DIRECTIONAL_POSITION_CAP_SIGNAL_CODES = (
    "early_entry",
    "good_continuation",
    "confirmed_breakout",
)
EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_ENABLED = (
    True  # Live enabled: bounded extra cap room only for already-profitable strong continuation adds.
)
EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_BONUS_PCT = (
    0.02  # Add at most 2% extra cap room for the narrow profitable-add continuation path.
)
EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_HARD_CEILING_PCT = (
    0.93  # Hard stop for profitable-add cap headroom.
)
EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_SCORE_MIN = (
    76.0  # Require stronger quality than the baseline directional cap experiment.
)
EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_EXTENSION_RATIO_MAX = (
    0.35  # Keep profitable continuation adds restricted to fresher, less-extended setups.
)
EXPERIMENTAL_PROFITABLE_CONTINUATION_ADD_CAP_HEADROOM_SIGNAL_CODES = (
    "good_continuation",
    "confirmed_breakout",
)
EXPERIMENTAL_LONG_CONTINUATION_ADD_ENABLED = (
    True  # Live enabled: bounded one near-price dynamic long continuation add for fresh profitable trends.
)
EXPERIMENTAL_LONG_CONTINUATION_ADD_NEAR_BAND_PCT = (
    0.003  # Keep the long continuation add narrowly constrained near price.
)
EXPERIMENTAL_LONG_CONTINUATION_ADD_SCORE_MIN = (
    76.0  # Require strong continuation quality before allowing the near-price long add.
)
EXPERIMENTAL_LONG_CONTINUATION_ADD_EXTENSION_RATIO_MAX = (
    0.35  # Keep the long continuation add restricted to fresher, less-extended setups.
)
EXPERIMENTAL_LONG_CONTINUATION_ADD_SIGNAL_CODES = (
    "good_continuation",
    "confirmed_breakout",
)

MODE_SCOPED_POSITION_CAPS: Dict[str, float] = {
    "long": DIRECTIONAL_MAX_POSITION_PCT,
    "short": DIRECTIONAL_MAX_POSITION_PCT,
    "scalp_market": DIRECTIONAL_MAX_POSITION_PCT,
}


def get_mode_max_position_pct(mode: str) -> float:
    normalized_mode = str(mode or "").strip().lower()
    return float(MODE_SCOPED_POSITION_CAPS.get(normalized_mode, MAX_POSITION_PCT))

# Auto grid adjustment - automatically reduce grid_count when order value is below minimum
AUTO_GRID_ADJUSTMENT_ENABLED = True  # Auto-reduce grid levels to meet $5 minimum
AUTO_GRID_ADJUSTMENT_MIN_LEVELS = 3  # Minimum levels before erroring out
AUTO_GRID_ADJUSTMENT_BUFFER = 1.1  # 10% buffer above minimum (e.g., target $5.50 not $5.00)

# =============================================================================
# Volatility-Dynamic Spacing (Smart Feature #27-B)
# =============================================================================
VOLATILITY_DYNAMIC_SPACING_ENABLED = True
VOLATILITY_SPACING_ATR_MULT = 1.1  # Spacing = 1.1 * ATR%
VOLATILITY_SPACING_MIN_PCT = 0.003  # 0.3% base min (eff. 0.12% for majors)
VOLATILITY_SPACING_MAX_PCT = 0.015  # 1.5% max spacing

# =============================================================================
# Pre-Launch Bot Validation Limits (NEW - from mytrading parity)
# =============================================================================
# These limits prevent opening new bots that would violate risk constraints

# Per-bot capital as % of total account equity
MAX_RISK_PER_BOT_PCT = 0  # 0 = disabled (allow any bot size)

# Per-symbol exposure limits
MAX_CAPITAL_PER_SYMBOL_PCT = 0  # 0 = disabled (allow any allocation)
MAX_CAPITAL_PER_SYMBOL_USDT = 0  # 0 = disabled (no absolute cap)
MAX_BOTS_PER_SYMBOL = 1  # Max 1 running bot per symbol
ENFORCE_SINGLE_RUNNING_BOT_PER_SYMBOL = True

# Portfolio concentration limits
MAX_SYMBOL_SHARE_OF_BOTS_PCT = (
    1.0  # 100% max share of total bot notional (single-bot ok)
)

# Concurrent limits
MAX_CONCURRENT_SYMBOLS = 0  # 0 = unlimited symbols
MAX_CONCURRENT_BOTS = 0  # 0 = unlimited bots

# =============================================================================
# Launch Affordability + Capital Partitioning
# =============================================================================
LAUNCH_AFFORDABILITY_ENABLED = True
LAUNCH_AUTO_RAISE_LEVERAGE = True
LAUNCH_AUTO_CAP_RUNTIME_GRIDS = True
LAUNCH_MIN_ACTIVE_OPEN_ORDERS = 4
CAPITAL_PARTITION_ENABLED = True

# =============================================================================
# Low-Balance / High-Volatility Protections
# =============================================================================
PROXIMITY_LADDER_ENABLED = True
PROXIMITY_LOW_BALANCE_INVESTMENT_THRESHOLD = 50.0
PROXIMITY_DEFAULT_OPEN_ORDER_CAP_TOTAL = 10
PROXIMITY_SCALP_OPEN_ORDER_CAP_TOTAL = 12
PROXIMITY_LOW_BALANCE_OPEN_ORDER_CAP_TOTAL = 6
PROXIMITY_LOW_BALANCE_SCALP_OPEN_ORDER_CAP_TOTAL = 12
PROXIMITY_ELEVATED_VOL_OPEN_ORDER_CAP_TOTAL = 12
PROXIMITY_HIGH_VOL_OPEN_ORDER_CAP_TOTAL = 10
PROXIMITY_EXTREME_VOL_OPEN_ORDER_CAP_TOTAL = 4

FEE_AWARE_MIN_STEP_ENABLED = True
FEE_AWARE_MIN_STEP_BUFFER_PCT = 0.0005  # 0.05% extra above round-trip fees

VOLATILITY_DERISK_ENABLED = True
VOLATILITY_DERISK_ATR_ELEVATED = 0.035
VOLATILITY_DERISK_ATR_HIGH = 0.06
VOLATILITY_DERISK_ATR_EXTREME = 0.075  # was 0.06 (same as HIGH, dead tier) — 7.5% creates proper 3-tier: 3.5% → 6.0% → 7.5%
VOLATILITY_DERISK_STEP_MULT_ELEVATED = 1.10
VOLATILITY_DERISK_STEP_MULT_HIGH = 1.30
VOLATILITY_DERISK_STEP_MULT_EXTREME = 1.60
VOLATILITY_DERISK_SIZE_MULT_ELEVATED = 0.90
VOLATILITY_DERISK_SIZE_MULT_HIGH = 0.75
VOLATILITY_DERISK_SIZE_MULT_EXTREME = 0.60
VOLATILITY_DERISK_BLOCK_NEW_ORDERS_ATR_PCT = 0.09  # was 0.12 — 12% ATR unrealistic, lowered to activate in real volatility

FAILURE_BREAKER_ENABLED = True
FAILURE_BREAKER_WINDOW_SEC = 180
FAILURE_BREAKER_MARGIN_LIMIT = 3
FAILURE_BREAKER_NOTIONAL_LIMIT = 4
FAILURE_BREAKER_ONE_SIDED_LIMIT = 2

SYMBOL_DAILY_KILL_SWITCH_ENABLED = False
SYMBOL_DAILY_KILL_SWITCH_LOSS_PCT_OF_INVESTMENT = 0.12
SYMBOL_DAILY_KILL_SWITCH_MIN_USDT = 2.5
SYMBOL_DAILY_KILL_SWITCH_MAX_USDT = 15.0
SYMBOL_DAILY_KILL_SWITCH_CLOSE_POSITION = True
SYMBOL_DAILY_KILL_SWITCH_CANCEL_ORDERS = True

# =============================================================================
# BTC Correlation Filter (NEW - from mytrading parity)
# =============================================================================
# Blocks symbols highly correlated with BTC during strong BTC trends

ENABLE_BTC_CORRELATION_FILTER = True  # Enabled — skip altcoin entries when BTC is dumping (prevents correlated losses)
MAX_ALLOWED_CORRELATION_BTC = 0.60  # Lower = stricter correlation filter
BTC_STRONG_TREND_ADX_THRESHOLD = 25.0  # BTC ADX threshold for "strong trend"
BTC_CORRELATION_LOOKBACK = 100  # Number of candles for correlation calc

# Default neutral range width (~6% total)
# Acts as the fallback floor when a mode-specific override is not defined.
DEFAULT_RANGE_WIDTH_PCT = 0.06

# Default grid-center move required before dynamic/trailing ranges are recalculated.
DEFAULT_GRID_STABILITY_THRESHOLD_PCT = 0.008  # 0.8%

# Hard min/max width for dynamic/trailing ranges
MIN_RANGE_WIDTH_PCT = 0.02  # 2%
MAX_RANGE_WIDTH_PCT = 0.15  # 15%

# Mode-specific dynamic range tuning.
# These settings make tight/neutral modes adapt faster while keeping trend modes steadier.
MODE_DYNAMIC_RANGE_SETTINGS: Dict[str, Dict[str, float]] = {
    "neutral": {
        "width_floor_pct": 0.06,  # 6.0% — wider for better fill spacing
        "recalc_threshold_pct": 0.004,  # 0.4%
    },
    "neutral_classic_bybit": {
        "width_floor_pct": 0.06,  # 6.0% — matches Bybit grid bot defaults
        "recalc_threshold_pct": DEFAULT_GRID_STABILITY_THRESHOLD_PCT,
    },
    "scalp_pnl": {
        "width_floor_pct": 0.04,  # 4.0% — tighter for scalping
        "recalc_threshold_pct": 0.003,  # 0.3%
    },
    "scalp_market": {
        "width_floor_pct": 0.04,  # 4.0%
        "recalc_threshold_pct": 0.003,  # 0.3%
    },
    "long": {
        "width_floor_pct": 0.06,  # 6.0% — wider for trend following
        "recalc_threshold_pct": 0.004,  # 0.4% — aligned with SHORT for symmetric directional responsiveness
    },
    "short": {
        "width_floor_pct": 0.06,  # 6.0%
        "recalc_threshold_pct": 0.004,  # 0.4% — faster recenter on downtrends
    },
    "__default__": {
        "width_floor_pct": DEFAULT_RANGE_WIDTH_PCT,
        "recalc_threshold_pct": DEFAULT_GRID_STABILITY_THRESHOLD_PCT,
    },
}


def get_dynamic_range_settings(mode: str) -> Dict[str, float]:
    """
    Return effective dynamic range settings for a bot mode.

    Args:
        mode: Bot mode name (e.g. neutral, long, scalp_pnl)

    Returns:
        Dict with width_floor_pct and recalc_threshold_pct.
    """
    mode_key = str(mode or "__default__").lower()
    settings = MODE_DYNAMIC_RANGE_SETTINGS.get(
        mode_key, MODE_DYNAMIC_RANGE_SETTINGS["__default__"]
    )
    return {
        "width_floor_pct": float(settings["width_floor_pct"]),
        "recalc_threshold_pct": float(settings["recalc_threshold_pct"]),
    }

# =============================================================================
# Directional Reanchor After Manual Close
# =============================================================================
DIRECTIONAL_REANCHOR_ON_MANUAL_CLOSE_ENABLED = True
DIRECTIONAL_REANCHOR_MAX_PENDING_CYCLES = 5
DIRECTIONAL_REANCHOR_MAX_PENDING_AGE_SEC = 120  # 2 minutes
DIRECTIONAL_REANCHOR_ON_FLAT_DETECTED_ENABLED = True  # Auto-reanchor when exchange confirms flat (covers external close, TP/SL fills)

# Volatility bands for ATR%
LOW_ATR_PCT = 0.01  # 1%
HIGH_ATR_PCT = 0.06  # 6%

# Multipliers for grid step adjustment
TIGHT_GRID_MULTIPLIER = 0.5  # half step when calm
WIDE_GRID_MULTIPLIER = 2.0  # double step when wild

# =============================================================================
# Coin Category Grid Settings (for Long/Short Trailing Modes)
# =============================================================================
# Major coins (high liquidity, lower volatility) use tighter spacing
# Meme coins (higher volatility) use wider spacing

# DCA step for trailing modes (replaces single DCA_BUY_STEP_PCT)
DCA_STEP_MAJOR_PCT = 0.004  # 0.4% for majors (tighter - SOL, BTC, ETH)
DCA_STEP_MEME_PCT = 0.015  # 1.5% for meme coins (wider - DOGE, PEPE, etc.)

# Grid step multipliers by coin category
GRID_STEP_MAJOR_MULT = 0.4  # 0.4x base step for majors (super tight for slow movers)
GRID_STEP_MEME_MULT = 1.0  # 1.0x base step for meme (normal)

# Major/high-volume symbols (use tighter grid spacing in trailing modes)
TRAILING_MAJOR_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "MATICUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "NEARUSDT",
    "APTUSDT",
    "SUIUSDT",
]
# Anything not in TRAILING_MAJOR_SYMBOLS uses MEME settings

# =============================================================================
# Default global TP% (fraction of bot capital) based on profile/mode
# =============================================================================
SCALP_DEFAULT_TP_PCT = 0.008  # 0.8% for scalp profile
NEUTRAL_DEFAULT_TP_PCT = 0.015  # 1.5% for neutral mode
TREND_DEFAULT_TP_PCT = 0.030  # 3.0% for trend modes (long/short with normal profile)

# =============================================================================
# Scalp Unrealized PnL Mode Configuration
# =============================================================================
# This mode scalps unrealized profit by closing positions dynamically
# and placing grid orders close to current price to follow momentum

# Profit thresholds (in USDT)
SCALP_PNL_MIN_PROFIT = 0.03  # Minimum profit to consider taking ($0.05)
SCALP_PNL_QUICK_PROFIT = 0.10  # Quick take profit in choppy markets ($0.30)
SCALP_PNL_TARGET_PROFIT = 0.15  # Target profit when trending well ($0.60)
SCALP_PNL_MAX_TARGET = 0.25  # Maximum target in strong trends ($1.00)
SCALP_PNL_BASE_POSITION_NOTIONAL_USDT = 20.0  # Base notional that maps to the default scalp targets
SCALP_PNL_POSITION_SCALE_MAX = 12.0  # Prevent oversized positions from producing absurd scalp targets

# Momentum detection thresholds
SCALP_PNL_MOMENTUM_STRONG = 0.65  # RSI above/below this = strong momentum
SCALP_PNL_MOMENTUM_WEAK = 0.50  # RSI near this = weak/neutral momentum

# Volatility thresholds for scalp behavior
SCALP_PNL_HIGH_VOLATILITY_ATR = 0.04  # ATR% above this = high volatility (choppy)
SCALP_PNL_LOW_VOLATILITY_ATR = 0.015  # ATR% below this = low volatility (calm)

# Grid placement for scalp mode (closer to price = more aggressive)
SCALP_PNL_NEAR_GRID_PCT = 0.0012  # Place grid 0.12% from current price
SCALP_PNL_FAR_GRID_PCT = 0.005  # Place grid 0.5% from current price max

# Volatility Guard (prevents scalping into wide spreads)
SCALPING_VOLATILITY_PAUSE_ENABLED = True  # Skip cycles if spread is too wide
SCALPING_ENABLED_THRESHOLD_MULTIPLIER = (
    2.0  # Max spread = 2.0 * SCALP_PNL_NEAR_GRID_PCT
)
# e.g., 0.12% * 2.0 = 0.24% max spread

# Time-based profit scaling (seconds since position opened)
SCALP_PNL_PATIENCE_SHORT = 30  # Below this: wait for minimum profit
SCALP_PNL_PATIENCE_MEDIUM = 120  # 30-120s: normal profit taking
SCALP_PNL_PATIENCE_LONG = 300  # Above 120s: more aggressive exit

# Swing detection (for choppy market detection)
SCALP_PNL_SWING_LOOKBACK = 5  # Number of candles to check for swings
SCALP_PNL_SWING_THRESHOLD = 3  # Number of direction changes = choppy

# =============================================================================
# Long Mode Quick Profit Configuration (NEW)
# =============================================================================
# Quick profit-taking for long dynamic mode - partial position closes
# Takes small profits from unrealized P&L while maintaining long bias

# Enable/disable quick profit feature
LONG_QUICK_PROFIT_ENABLED = True

# Profit thresholds (in USDT) - must be positive unrealized PnL
LONG_QUICK_PROFIT_MIN = 0.10  # Minimum profit to consider ($0.10)
LONG_QUICK_PROFIT_TARGET = 0.15  # Default target threshold ($0.15)
LONG_QUICK_PROFIT_MAX = 0.25  # Upper threshold for aggressive settings ($0.25)
LONG_QUICK_PROFIT_SCALE_BY_POSITION_NOTIONAL = True
LONG_QUICK_PROFIT_BASE_POSITION_NOTIONAL_USDT = 100.0
LONG_QUICK_PROFIT_POSITION_SCALE_MAX = 8.0

# Partial close percentage (how much of position to close)
LONG_QUICK_PROFIT_CLOSE_PCT = 0.50  # Close 50% of position on quick TP

# Cooldown between quick profit takes (seconds)
LONG_QUICK_PROFIT_COOLDOWN_SEC = 60  # Wait 60s between quick TPs

# Market-condition aware adjustments (adaptive thresholds)
LONG_QUICK_PROFIT_CHOPPY_MULT = 0.67  # Lower threshold in choppy markets (→ $0.10)
LONG_QUICK_PROFIT_TREND_MULT = 1.33  # Higher threshold when trending well (→ $0.20)

# Quick Profit Grid Recenter (fixes stranded positions after partial close)
QUICK_PROFIT_RECENTER_ENABLED = True       # Master toggle
QUICK_PROFIT_RECENTER_CANCEL_ALL = True    # Cancel all orders before rebuild
QUICK_PROFIT_RECENTER_COOLDOWN_SEC = 30    # Min seconds between recenters
QUICK_PROFIT_RECENTER_SUBSET_WIDTH_ENABLED = True
QUICK_PROFIT_RECENTER_SUBSET_WIDTH_MULT = 0.80

# Quick-profit fast-burst protection
QUICK_PROFIT_PROFIT_SPEED_ENABLED = True
QUICK_PROFIT_FAST_PROFIT_WINDOW_SECONDS = 180
QUICK_PROFIT_FAST_PROFIT_MIN_TRADE_AGE_SECONDS = 20
QUICK_PROFIT_FAST_PROFIT_MIN_USDT = 0.12
QUICK_PROFIT_FAST_PROFIT_THRESHOLD_MULTIPLIER = 1.15
QUICK_PROFIT_FAST_PROFIT_TARGET_MULTIPLIER = 0.85
QUICK_PROFIT_FAST_PROFIT_CLOSE_PCT_BONUS = 0.10
QUICK_PROFIT_FAST_PROFIT_VOLATILITY_ATR_PCT = 0.025

# =============================================================================
# Automatic Adaptive Stop-Loss Configuration (NEW - Feature #4)
# =============================================================================
# Fully automatic, volatility-based SL derived from grid range + ATR + profile
# NO MANUAL per-symbol configuration required

# Enable/disable automatic stop-loss
ENABLE_AUTOMATIC_STOP_LOSS = True  # Set False to disable all automatic SL

# Profile-based ATR multipliers for SL distance from grid boundary
SL_SAFE_ATR_MULTIPLIER = 2.0  # SAFE profile: 2.0x ATR below/above grid boundary
SL_NORMAL_ATR_MULTIPLIER = 2.5  # NORMAL profile: 2.5x ATR
SL_AGGRESSIVE_ATR_MULTIPLIER = 3.0  # AGGRESSIVE profile: 3.0x ATR

# Absolute min/max SL distance from current price (safety clamps)
SL_MIN_DISTANCE_PCT = 0.02  # Minimum 2% SL distance from current price
SL_MAX_DISTANCE_PCT = 0.10  # Maximum 10% SL distance from current price (was 0.15 — 15% at 3x lev = 45% account swing)

# SL update threshold (avoid excessive API calls)
SL_UPDATE_THRESHOLD_PCT = 0.02  # Only update SL if it changes by >2% of price

# =============================================================================
# Trend Protection Configuration (NEW - Feature #5)
# =============================================================================
# Detects strong trends and closes opposite-direction positions to prevent losses
# Uses multi-indicator confirmation: ADX, +DI/-DI, EMA slope, RSI

# Enable/disable trend protection
ENABLE_TREND_PROTECTION = False  # DEPRECATED — UPnL stoploss handles this better. Kept for backwards compat.

# Trend detection thresholds
TREND_ADX_THRESHOLD = 25.0  # ADX above this = strong trend detected
TREND_DI_DOMINANCE = 5.0  # +DI/-DI difference required for trend confirmation
TREND_RSI_THRESHOLD = 10.0  # RSI distance from 50 for trend confirmation

# Confidence scoring
TREND_MIN_CONFIDENCE_SCORE = 75  # Stricter trend confidence for closing positions

# =============================================================================
# Range Recentering & Profile Adjustments (NEW - Feature #6)
# =============================================================================
# Automatic range recentering when price approaches boundaries
# Profile-based width multipliers for SAFE/NORMAL/AGGRESSIVE

# Recentering threshold (when to recenter the grid range)
# Keep this above the midpoint so recentering means "approaching an edge",
# not "any move away from center".
RANGE_RECENTER_THRESHOLD_PCT = (
    0.60  # Recenter when price reaches the outer 40% of the range
)

# Trailing recenter configuration (for range_mode="trailing")
# These control how often and how sensitively the grid follows price in outer zones
TRAILING_RECENTER_COOLDOWN_SEC = (
    600  # Seconds between trailing recenters (default: 600 = 10 min)
)
TRAILING_RECENTER_OUTER_PCT = (
    0.07  # Outer zone trigger: 7% of width each side (smaller = less frequent)
)

# Profile-based range width multipliers
SAFE_PROFILE_RANGE_MULTIPLIER = 0.80  # SAFE: 20% narrower ranges (tighter grid)
NORMAL_PROFILE_RANGE_MULTIPLIER = 1.00  # NORMAL: Default range width
AGGRESSIVE_PROFILE_RANGE_MULTIPLIER = 1.30  # AGGRESSIVE: 30% wider ranges (more room)

# =============================================================================
# Grid Distribution Modes (NEW - Feature #7)
# =============================================================================
# Different grid order distribution patterns for directional bias

# Grid distribution modes: "balanced", "buy_heavy", "sell_heavy", "clustered"
DEFAULT_GRID_DISTRIBUTION = "clustered"  # Smart: concentrate grids near current price

# Buy/Sell ratio for heavy modes (ratio > 1.0 means more orders on heavy side)
GRID_BUY_SELL_RATIO = 1.5  # 1.5 = 60% buy, 40% sell (or vice versa)

# Clustering concentration (0-1, higher = more concentration near price)
GRID_CLUSTER_CONCENTRATION = 0.70  # 70% weight near price, 30% at extremes

# =============================================================================
# Smart Take-Profit Configuration (NEW - Feature #8)
# =============================================================================
# Automatic TP calculation based on volatility, mode, and risk profile

# Enable/disable automatic take-profit
ENABLE_AUTOMATIC_TAKE_PROFIT = True  # Set False to use manual TP targets

# Profile-based ATR multipliers for TP distance
TP_SAFE_ATR_MULTIPLIER = 1.5  # SAFE: Conservative profits
TP_NORMAL_ATR_MULTIPLIER = 2.0  # NORMAL: Balanced profits
TP_AGGRESSIVE_ATR_MULTIPLIER = 2.5  # AGGRESSIVE: Larger profit targets

# Absolute min/max TP distance from entry price
TP_MIN_DISTANCE_PCT = 0.005  # Minimum 0.5% TP distance
TP_MAX_DISTANCE_PCT = 0.10  # Maximum 10% TP distance

# =============================================================================
# Danger Zone Detection (NEW - Feature #9)
# =============================================================================
# Detect extreme market conditions and pause trading

# Enable/disable danger zone detection
ENABLE_DANGER_ZONE_DETECTION = False  # Set False to disable

# Extreme RSI thresholds
DANGER_RSI_OVERBOUGHT = 80.0  # RSI above this = overbought danger
DANGER_RSI_OVERSOLD = 20.0  # RSI below this = oversold danger

# Extreme volatility thresholds
DANGER_BBW_EXTREME_PCT = 0.08  # BBW% above 8% = extreme volatility
DANGER_ATR_EXTREME_PCT = 0.06  # ATR% above 6% = extreme volatility

# =============================================================================
# Trading Bot Audit - Safety Controls (001-trading-bot-audit)
# =============================================================================
# Added for anti-churn recentering, kill-switch, and fee-aware scalp improvements

# Global kill-switch - halts all trading when daily loss exceeds threshold
GLOBAL_KILL_SWITCH_ENABLED = (
    False  # Disabled: keep per-bot/per-symbol loss guards, but do not pause all bots
)

# Volatility freeze thresholds - pause recentering when volatility is extreme
VOLATILITY_FREEZE_ATR_PCT = 1.0  # 100% ATR threshold to freeze recentering (effectively off)
VOLATILITY_FREEZE_BBW_PCT = 1.0  # 100% BBW threshold to freeze recentering (effectively off)

# Fee-aware scalp profit settings
SCALP_FEE_MULTIPLIER = 2.5  # Multiplier for fee cost in min profit calculation
SCALP_SPREAD_THRESHOLD_PCT = 0.005  # 0.5% max spread for scalp trades
SCALP_POST_CLOSE_COOLDOWN_SEC = 30  # Cooldown after closing before new entries

# Anti-churn recenter protection
RECENTER_POSITION_BLOCK_ALL_MODES = (
    True  # Block recenter when positions open (all modes)
)
SCALP_RECENTER_MIN_DEVIATION_PCT = 0.006  # 0.60% minimum move before scalp recenter
SCALP_RECENTER_GRID_MULTIPLIER = 2.0  # Recenter only after ~2x scalp spacing
SCALP_RECENTER_COOLDOWN_SEC = 180  # Minimum 3 minutes between scalp recenters

# =============================================================================
# Safe Profile Defaults (recommended for new traders)
# =============================================================================
# To enable safe defaults, set these values instead of 0:
#   MAX_RISK_PER_BOT_PCT = 0.10        # 10% max per bot
#   MAX_CAPITAL_PER_SYMBOL_PCT = 0.25  # 25% max per symbol
#   MAX_BOTS_PER_SYMBOL = 2            # Max 2 bots per symbol
# Current values of 0 = disabled (unlimited) for backward compatibility

# =============================================================================
# Auto-Margin Presets (safe vs aggressive)
# =============================================================================
# Controlled via env AUTO_MARGIN_PRESET (conservative | aggressive)
# Default to aggressive (larger, uncapped adds) unless overridden by env.
AUTO_MARGIN_PRESET_NAME = os.getenv("AUTO_MARGIN_PRESET", "aggressive").strip().lower()

AUTO_MARGIN_PRESETS = {
    # Conservative: smaller, slower top-ups with tighter caps.
    "conservative": {
        "enabled": True,
        "min_trigger_pct": 8.0,
        "target_liq_pct": 8.0,
        "cooldown_sec": 15,
        "max_add_ratio": 0.20,    # Smaller fraction of balance per add
        "min_add_usdt": 0.1,
        "max_add_usdt": 5.0,      # Lower per-add cap
        "max_total_add_usdt": 30.0,  # Tighter total cap
        "position_idx": 0,
        "critical_pct": 2.5,
    },
    # Aggressive: faster, larger adds for active protection.
    "aggressive": {
        "enabled": True,
        "min_trigger_pct": 8.0,
        "target_liq_pct": 8.0,
        "cooldown_sec": 8,
        "max_add_ratio": 0.35,
        "min_add_usdt": 0.1,
        "max_add_usdt": 10.0,
        "max_total_add_usdt": 50.0,
        "position_idx": 0,
        "critical_pct": 2.5,
    },
}


def get_auto_margin_defaults() -> dict:
    """
    Return a copy of the configured auto-margin preset.

    Controlled by env AUTO_MARGIN_PRESET (conservative | aggressive).
    Defaults to conservative if unset/invalid.
    """
    preset = (
        AUTO_MARGIN_PRESET_NAME
        if AUTO_MARGIN_PRESET_NAME in AUTO_MARGIN_PRESETS
        else "conservative"
    )
    return dict(AUTO_MARGIN_PRESETS[preset])


# =============================================================================
# Independent Margin Monitor Service Configuration (NEW - Smart Feature #18)
# =============================================================================
# Monitors ALL open positions independently of bot status.
# Adds margin when liquidation distance drops below threshold.
# Works even when bots are paused, stopped, or in error state.

MARGIN_MONITOR_ENABLED = True  # Master toggle for margin monitor
MARGIN_MONITOR_TRIGGER_PCT = 8.0  # Add margin when pct_to_liq <= 8%
MARGIN_MONITOR_TARGET_PCT = 8.0  # Restore only to the 8% liq safety floor
MARGIN_MONITOR_CRITICAL_PCT = 2.5  # Skip cooldown when below 2.5%
MARGIN_MONITOR_COOLDOWN_SEC = 12  # Seconds between adds per position
MARGIN_MONITOR_MAX_ADD_RATIO = 0.35  # Keep balance for orders
MARGIN_MONITOR_MIN_ADD_USDT = 0.1  # Minimum add amount
MARGIN_MONITOR_MAX_ADD_USDT = 10.0  # Maximum add amount per action
MARGIN_MONITOR_ALL_POSITIONS = True  # Monitor ALL positions, not just bot positions
MARGIN_MONITOR_EMERGENCY_MAX_PCT_PER_BOT = (
    0.10  # 10% of balance per bot per rolling window
)
MARGIN_MONITOR_EMERGENCY_MAX_PCT_TOTAL = (
    0.20  # 20% of balance total per rolling window
)
MARGIN_MONITOR_EMERGENCY_WINDOW_SEC = 3600  # Rolling window for total emergency adds

# Volume spike threshold
DANGER_VOLUME_SPIKE_MULTIPLIER = 5.0  # 5x average volume = spike

# Range extreme threshold (position in grid range)
DANGER_RANGE_EXTREME_PCT = 0.95  # At 95%+ of range = at extreme

# Pause threshold (danger score 0-100)
DANGER_PAUSE_THRESHOLD_SCORE = 50  # Score >= 50 pauses trading

# =============================================================================
# Out-of-Range Behavior Options (NEW - Feature #10)
# =============================================================================
# What to do when price breaks out of grid range

# Out-of-range action: "pause", "close", "recenter", "ignore"
OUT_OF_RANGE_ACTION = "recenter"  # Default: auto-recenter the grid

# Wait time before taking action (seconds)
OUT_OF_RANGE_WAIT_SEC = 10  # Wait 10s before acting (was 60 — too slow during trends)

# Auto-close positions when out of range
OUT_OF_RANGE_CLOSE_POSITIONS = False  # True = close all positions on breakout

# =============================================================================
# Smart Bot Recovery (Auto-Healing) (NEW - Smart Feature #3)
# =============================================================================
# Automated repair strategies for out-of-range bots
RECOVERY_ENABLED_DEFAULT = True

# Range Rolling thresholds
# Don't roll if market is extremely stretched (prevent catching falling knives)
RECOVERY_ROLL_RSI_MAX = 75
RECOVERY_ROLL_RSI_MIN = 25
RECOVERY_ROLL_ADX_MAX = 45  # Don't roll into vertical parabolic moves

# Defensive Scale-Out (Stop-loss substitute for out-of-range positions)
RECOVERY_SCALE_OUT_ENABLED = True
RECOVERY_SCALE_OUT_FRACTION = 0.50  # Close 50% of position if healing fails
RECOVERY_SCALE_OUT_UPNL_THRESHOLD = -0.15  # Trigger scale-out if uPnL < -15%
RECOVERY_SCALE_OUT_COOLDOWN_SEC = 300  # 5 min between partial closes

# =============================================================================
# Price Prediction Service Configuration (ENHANCED - Feature #11)
# =============================================================================
# Advanced price prediction using patterns, S/R, divergence, MTF alignment,
# and DEEP historical analysis (1000+ candles)

# Main Prediction Settings
PREDICTION_CANDLE_LIMIT = 1000  # Fetch 1000 candles for deep analysis
PREDICTION_DEEP_ANALYSIS = True  # Enable deep historical pattern matching

# Pattern Detection Settings (ENHANCED)
PATTERN_LOOKBACK_CANDLES = 200  # Candles for chart patterns (was 50)
PATTERN_MIN_CONFIDENCE = 0.60  # Minimum pattern confidence to report (0-1)
DOUBLE_TOP_BOTTOM_TOLERANCE = 0.015  # 1.5% price tolerance for peaks/troughs
TRIANGLE_SLOPE_THRESHOLD = 0.0002  # Slope threshold for flat trendlines

# Support/Resistance Detection Settings (ENHANCED)
SR_TOUCH_THRESHOLD_PCT = 0.003  # 0.3% tolerance for level touches
SR_MIN_TOUCHES = 3  # Minimum touches to form valid S/R level
SR_LOOKBACK_CANDLES = 300  # Candles for S/R detection
SR_PROXIMITY_THRESHOLD = 0.01  # 1% for "near level" detection

# Divergence Detection Settings
DIVERGENCE_LOOKBACK = 50  # Candles for RSI/MACD divergence (was 30)
DIVERGENCE_MIN_SWING_SIZE = 0.005  # 0.5% minimum swing size for divergence

# Long-Term Trend Analysis Settings (NEW)
LONG_TERM_LOOKBACK = 1000  # Candles for long-term trend analysis
LONG_TERM_TREND_WEIGHT = 25  # Max score contribution from long-term trend
TREND_DURATION_WEIGHT = 15  # Max score from trend duration/persistence
HIGHER_TF_BIAS_WEIGHT = 20  # Max score from daily/weekly bias

# Higher Timeframe Settings (NEW)
HIGHER_TF_INTERVALS = ["60", "240", "D"]  # 1h, 4h, Daily for long-term bias
HIGHER_TF_CANDLE_LIMIT = 200  # Candles per higher timeframe

# Multi-Timeframe Alignment Settings (ENHANCED)
MTF_TIMEFRAMES = ["5", "15", "60", "240"]  # Added 4-hour timeframe
MTF_WEIGHTS = {  # Weighting for each timeframe
    "5": 0.10,  # 5-minute (10% weight)
    "15": 0.20,  # 15-minute (20% weight)
    "60": 0.30,  # 1-hour (30% weight)
    "240": 0.25,  # 4-hour (25% weight)
    "D": 0.15,  # Daily (15% weight)
}

# Prediction Output Thresholds (score -> direction mapping)
STRONG_LONG_THRESHOLD = 70  # Score >= 70 = STRONG_LONG
LONG_THRESHOLD = 35  # Score >= 35 = LONG
NEUTRAL_BAND = 20  # Score within +/-20 = NEUTRAL
SHORT_THRESHOLD = -35  # Score <= -35 = SHORT
STRONG_SHORT_THRESHOLD = -70  # Score <= -70 = STRONG_SHORT

# Prediction Scoring Weights (for integration with auto-direction)
PREDICTION_PATTERN_MAX_SCORE = 30  # Max +/- points from chart patterns
PREDICTION_DIVERGENCE_MAX_SCORE = 25  # Max +/- points from divergence
PREDICTION_SR_MAX_SCORE = 15  # Max +/- points from S/R proximity
PREDICTION_STRUCTURE_MAX_SCORE = 15  # Max +/- points from trend structure
PREDICTION_MTF_MAX_SCORE = 20  # Max +/- points from MTF alignment

# =============================================================================
# Score Normalization & Confidence Calibration (UPGRADE 2026-01-10)
# =============================================================================
# Fixes: unbounded score, inflated confidence, incomplete candle instability

# Deterministic max score for normalization (sum of all component max scores)
# Components: pattern(30) + sr(15) + divergence(25) + structure(15) + mtf(20)
#           + long_term(25) + duration(15) + higher_tf(20) = 165
PREDICTION_MAX_POSSIBLE_ABS = 165

# Normalized score thresholds (score_norm range: -100 to +100)
PREDICTION_NORM_STRONG_THRESHOLD = 60  # score_norm >= 60 for STRONG_LONG/SHORT (was 70 — too strict, most bots score 40-50)
PREDICTION_NORM_MODERATE_THRESHOLD = 40  # score_norm >= 40 for LONG/SHORT

# Confidence calculation weights
PREDICTION_CONFIDENCE_MAGNITUDE_WEIGHT = 0.6  # Weight for score magnitude
PREDICTION_CONFIDENCE_AGREEMENT_WEIGHT = 0.4  # Weight for signal agreement
PREDICTION_NEUTRAL_CONFIDENCE_CAP = 60  # Max confidence for NEUTRAL label

# Incomplete candle filtering (exclude still-forming candle by default)
PRICE_PREDICT_USE_ONLY_CLOSED_CANDLES = True

# Hysteresis buffer for label changes (prevents flip-flop near thresholds)
PREDICTION_LABEL_HYSTERESIS = 5  # Require 5-point buffer to change label

# =============================================================================
# Strong Signal Safeguards (2026-01-10)
# =============================================================================
# Defensive measures to prevent false STRONG signals and label flapping

# 1. Consensus Gate - minimum signal agreement for STRONG labels
# STRONG_LONG/SHORT only allowed if this % of signals agree with direction
MIN_STRONG_SIGNAL_CONSENSUS = 0.60  # 60% of signals must agree

# 2. Label Hysteresis - prevent rapid label flipping (anti-whipsaw)
# Once in a label, require crossing these thresholds to change
PREDICTION_HYSTERESIS_LONG_EXIT = 30  # LONG → NEUTRAL requires score < 30
PREDICTION_HYSTERESIS_SHORT_EXIT = -30  # SHORT → NEUTRAL requires score > -30
PREDICTION_HYSTERESIS_STRONG_LONG_EXIT = 60  # STRONG_LONG → LONG exit threshold
PREDICTION_HYSTERESIS_STRONG_SHORT_EXIT = -60  # STRONG_SHORT → SHORT exit threshold

# 3. Timeframe Confirmation - require consecutive STRONG signals on low TFs
# Low timeframes are noisy - require 2 consecutive STRONG predictions
STRONG_CONFIRMATION_TIMEFRAMES = ["1", "3", "5"]  # 1m, 3m, 5m need confirmation
STRONG_CONFIRMATION_REQUIRED_COUNT = 2  # Consecutive cycles needed for STRONG

# 4. Volume Safety Filter - block STRONG when liquidity is insufficient
# Low volume markets can produce misleading STRONG signals
MIN_STRONG_VOLUME_USDT = 50000.0  # Min candle volume (USDT) for STRONG signals


# =============================================================================
# Flash Crash Protection Configuration (NEW - Smart Feature #12)
# =============================================================================
# Detects extreme price moves and auto-pauses all bots, resuming after normalization

ENABLE_FLASH_CRASH_PROTECTION = True  # Enabled — auto-pauses all bots on 3%+ BTC drops (free safety net)
FLASH_CRASH_MONITOR_SYMBOL = "BTCUSDT"  # Monitor BTC only (leads the market)
FLASH_CRASH_THRESHOLD_PCT = 0.03  # 3% price move triggers protection
FLASH_CRASH_LOOKBACK_MINUTES = 5  # Time window to measure price change
FLASH_CRASH_COOLDOWN_MINUTES = 10  # Wait time after crash before auto-resume
FLASH_CRASH_NORMALIZE_BBW = 0.05  # BBW must drop below 5% to consider normalized
FLASH_CRASH_NORMALIZE_RSI_LOW = 40  # RSI must be above this to normalize
FLASH_CRASH_NORMALIZE_RSI_HIGH = 60  # RSI must be below this to normalize

# =============================================================================
# Mode Hysteresis Configuration (Anti-Whipsaw) (NEW - Smart Feature #13)
# =============================================================================
# Prevents rapid mode switching by requiring stronger signal to enter than exit

# Entry thresholds - need STRONGER signal to enter a mode
MODE_ENTER_LONG_THRESHOLD = 50  # Score >= 50 to enter long (was 30)
MODE_ENTER_SHORT_THRESHOLD = -50  # Score <= -50 to enter short (was -30)

# Exit thresholds - more tolerant to stay in mode
MODE_EXIT_LONG_THRESHOLD = -10  # Exit long when score drops below -10
MODE_EXIT_SHORT_THRESHOLD = 10  # Exit short when score rises above 10

# Stay thresholds - can stay in mode with moderate signal
MODE_STAY_LONG_THRESHOLD = 15  # Stay long if score >= 15 (was 10)
MODE_STAY_SHORT_THRESHOLD = -15  # Stay short if score <= -15 (was -10)

# Neutral band - return to neutral when within this range
MODE_NEUTRAL_BAND_WIDTH = 15  # Score within +/-15 goes neutral

# Minimum time in mode before switching (anti-whipsaw cooldown)
MODE_MIN_HOLD_SECONDS = 120  # Must be in mode 2 min before switching

# ADX requirement for mode changes
MODE_REQUIRE_ADX_FOR_CHANGE = True  # Require ADX confirmation to change modes
MODE_ADX_MIN_FOR_CHANGE = 20  # ADX must be >= 20 to change modes

# =============================================================================
# Trailing Stop-Loss Configuration (NEW - Smart Feature #14)
# =============================================================================
# Trails stop-loss behind price as position profits, locking in gains

ENABLE_TRAILING_STOP_LOSS = True  # Master toggle (enabled by default)
TRAILING_SL_ACTIVATION_PCT = 0.005  # Activate trailing after 0.5% profit
TRAILING_SL_DISTANCE_PCT = 0.003  # Trail 0.3% behind price
TRAILING_SL_STEP_PCT = 0.001  # Minimum price movement to update SL (0.1%)
TRAILING_SL_USE_ATR = True  # Use ATR-based distance instead of fixed %
TRAILING_SL_ATR_MULTIPLIER = 1.0  # ATR multiplier for trail distance
TRAILING_SL_MAX_UPDATES_PER_CYCLE = 1  # Limit API calls per bot cycle

# =============================================================================
# Funding Rate Intelligence Configuration (NEW - Smart Feature #15)
# =============================================================================
# Uses Bybit perpetual funding rates to detect crowded positions
# High positive funding = longs crowded (bearish signal)
# High negative funding = shorts crowded (bullish signal)

ENABLE_FUNDING_RATE_SIGNAL = False  # DEPRECATED — minimal usage, crowded-trade detection not validated
FUNDING_RATE_EXTREME_POSITIVE = 0.0005  # 0.05% = longs very crowded (bearish)
FUNDING_RATE_HIGH_POSITIVE = 0.0003  # 0.03% = longs crowded (mild bearish)
FUNDING_RATE_EXTREME_NEGATIVE = -0.0005  # -0.05% = shorts very crowded (bullish)
FUNDING_RATE_HIGH_NEGATIVE = -0.0003  # -0.03% = shorts crowded (mild bullish)
FUNDING_RATE_CACHE_SECONDS = 300  # Cache funding rate for 5 minutes
FUNDING_RATE_MAX_SCORE = 15  # Max +/- points from funding rate signal

# Pre-funding payment protection
FUNDING_PROTECTION_ENABLED = False  # Skip new orders near funding time
FUNDING_PROTECTION_MINUTES = 15  # Minutes before funding to pause new orders
FUNDING_PROTECTION_SKIP_UNFAVORABLE = True  # Skip if funding goes against position

# =============================================================================
# BTC Correlation Guard (NEW - Smart Feature #17)
# =============================================================================
# Pause altcoin bots when BTC is dumping to avoid cascade losses
# Altcoins typically dump 2-3x harder than BTC during corrections

BTC_GUARD_ENABLED = True  # Pauses altcoin bots if BTC dumps >2.5% in 60min
BTC_GUARD_DUMP_THRESHOLD = -0.025  # Pause if BTC drops >2.5% in lookback period
BTC_GUARD_RECOVERY_THRESHOLD = -0.015  # Resume if BTC change > -1.5%
BTC_GUARD_LOOKBACK_MINUTES = 60  # Check price change over this period
BTC_GUARD_CACHE_SECONDS = 30  # Cache BTC price data
BTC_GUARD_EXCLUDE_SYMBOLS = ["BTCUSDT"]  # Don't apply guard to BTC bots

# =============================================================================
# Volume Profile Analysis (NEW - Smart Feature #18)
# =============================================================================
# Identify high-volume price zones for better S/R detection
# High volume nodes act as strong support/resistance

VOLUME_PROFILE_ENABLED = True  # Master toggle
VOLUME_PROFILE_LOOKBACK = 100  # Candles to analyze
VOLUME_PROFILE_BINS = 20  # Price bins for volume distribution
VOLUME_PROFILE_HVN_THRESHOLD = 1.5  # High Volume Node = >1.5x avg volume
VOLUME_PROFILE_MAX_SCORE = 15  # Max +/- points from volume profile

# =============================================================================
# Open Interest Analysis (NEW - Smart Feature #19)
# =============================================================================
# Analyze OI changes to confirm trend strength
# Rising OI + Rising Price = Strong uptrend (new money entering longs)
# Rising OI + Falling Price = Strong downtrend (new money entering shorts)
# Falling OI + Rising Price = Weak rally (short covering)
# Falling OI + Falling Price = Weak selloff (long liquidations)

OI_ANALYSIS_ENABLED = True  # Master toggle
OI_LOOKBACK_PERIODS = 12  # Number of 5-min periods to analyze (1 hour)
OI_CHANGE_THRESHOLD = 0.02  # 2% OI change to trigger signal
OI_STRONG_THRESHOLD = 0.05  # 5% OI change = strong signal
OI_MAX_SCORE = 20  # Max +/- points from OI analysis
OI_CACHE_SECONDS = 60  # Cache OI data for 60 seconds

# =============================================================================
# Dynamic Position Sizing (NEW - Smart Feature #20)
# =============================================================================
# Adjust position size based on signal confidence
# Higher confidence = larger position, lower confidence = smaller position

DYNAMIC_SIZING_ENABLED = True  # Master toggle
DYNAMIC_SIZING_HIGH_CONFIDENCE = 50  # Score threshold for full size
DYNAMIC_SIZING_MEDIUM_CONFIDENCE = 30  # Score threshold for 70% size
DYNAMIC_SIZING_LOW_MULTIPLIER = 0.5  # 50% size for low confidence
DYNAMIC_SIZING_MEDIUM_MULTIPLIER = 0.7  # 70% size for medium confidence
DYNAMIC_SIZING_HIGH_MULTIPLIER = 1.0  # 100% size for high confidence

# =============================================================================
# Smart Entry Timing (NEW - Smart Feature #21)
# =============================================================================
# Wait for better entry conditions instead of entering immediately
# Reduces chasing, improves average entry price

SMART_ENTRY_ENABLED = False  # Master toggle
SMART_ENTRY_RSI_PULLBACK_LONG = 45  # For longs, wait for RSI to drop below this
SMART_ENTRY_RSI_PULLBACK_SHORT = 55  # For shorts, wait for RSI to rise above this
SMART_ENTRY_EMA_PROXIMITY_PCT = 0.005  # Enter when price within 0.5% of EMA
SMART_ENTRY_MAX_WAIT_CANDLES = 6  # Max candles to wait for entry (30 min on 5m)
SMART_ENTRY_USE_PULLBACK = True  # Wait for RSI pullback
SMART_ENTRY_USE_EMA = True  # Wait for EMA proximity

# =============================================================================
# Pullback Re-Entry (Smart Feature #35)
# =============================================================================
# After a profitable exit during a strong HTF trend (exhaustion/momentum exit),
# track pullback progress and re-enter when mean reversion eases.

PULLBACK_REENTRY_ENABLED = True
PULLBACK_REENTRY_MIN_HTF_ADX = 25.0          # 1h ADX must stay above this
PULLBACK_REENTRY_MAX_WATCH_SEC = 1800         # 30min max watch window
PULLBACK_REENTRY_RSI_ENTRY_ZONE_LONG = 50     # RSI must drop below this for long re-entry
PULLBACK_REENTRY_RSI_ENTRY_ZONE_SHORT = 50    # RSI must rise above this for short re-entry
PULLBACK_REENTRY_MIN_PULLBACK_PCT = 0.5       # Must retrace at least 0.5% from exit
PULLBACK_REENTRY_MAX_PULLBACK_PCT = 3.0       # Cancel if pullback > 3% (likely reversal)
PULLBACK_REENTRY_MR_TARGET_EXTENSION = "moderate"  # MR extension must ease to this or below
PULLBACK_REENTRY_REGIME_MUST_MATCH = True      # Regime must still match direction
PULLBACK_REENTRY_ADX_COLLAPSE_THRESHOLD = 20.0 # Cancel if HTF ADX drops below this
PULLBACK_REENTRY_MAX_PER_SESSION = 3           # Max re-entries per bot session
PULLBACK_REENTRY_COOLDOWN_AFTER_CANCEL_SEC = 300  # 5min cooldown after cancel
PULLBACK_REENTRY_DIRECTION_SCORE_MIN = 0       # Direction score must be >= this
PULLBACK_REENTRY_ENTRY_GATE_BYPASS = True      # Allow bypassing S/R entry gate
PULLBACK_REENTRY_SMART_ENTRY_BYPASS = True     # Allow bypassing smart entry RSI/EMA

# =============================================================================
# Entry Gate - Smart Entry Timing at Bot Start (NEW - Smart Feature #21b)
# =============================================================================
# Blocks bot start/orders when entry conditions are unfavorable
# Uses "Block if ANY bad" logic - blocks if ANY threshold exceeded
# Prevents entering at overbought/oversold extremes, extended prices, or
# directly into nearby support/resistance.

ENTRY_GATE_ENABLED = True  # Master toggle — blocks bad entries at extremes
ENTRY_GATE_SR_ENABLED = True  # Directional S/R guard for adverse nearby levels

# Long mode thresholds (block if exceeded - avoid buying at tops)
ENTRY_GATE_RSI_LONG_MAX = 85  # Block if RSI > 85 (parabolic overbought only)
ENTRY_GATE_BB_LONG_MAX = 0.98  # Block if BB position > 98% (extreme upper band)
ENTRY_GATE_EMA_LONG_MAX = 0.08  # Block if price > 8.0% above EMA21

# Short mode thresholds (block if below - avoid selling at bottoms)
ENTRY_GATE_RSI_SHORT_MIN = 28  # Block if RSI < 28 (deep oversold)
ENTRY_GATE_BB_SHORT_MIN = 0.05  # Block if BB position < 5% (extreme lower band)
ENTRY_GATE_EMA_SHORT_MAX = 0.03  # Block if price > 3.0% below EMA21

# Support/resistance thresholds (used even if momentum gate is off)
ENTRY_GATE_SR_PROXIMITY_PCT = 0.003  # Block if adverse level is within 0.3% (was 0.001 — 0.1% was unreachable)
ENTRY_GATE_SR_MIN_STRENGTH = 10  # Only block on maximum-strength levels
ENTRY_GATE_PRICE_ACTION_ENABLED = True  # Block strong opposing price-action confluence
ENTRY_GATE_PRICE_ACTION_BLOCK_SCORE = 20.0  # Opposing signed score needed to block (was 16 — too sensitive)
ENTRY_GATE_PRICE_ACTION_HARD_BLOCK_SCORE = 26.0  # Single-sided extreme context (was 22)
ENTRY_GATE_PRICE_ACTION_BLOCK_MIN_COMPONENTS = 3  # Require stronger confluence (was 2)

# Gate behavior
ENTRY_GATE_RECHECK_SECONDS = 30  # Recheck interval when blocked (was 60 — too slow to clear)
ENTRY_GATE_TIMEFRAME = "15"  # Timeframe for indicator checks (quality scoring)
ENTRY_GATE_FAST_TIMEFRAME = "5"  # Fast trigger detection timeframe
ENTRY_GATE_FAST_TIMEFRAME_ENABLED = True  # Feature flag for 5m fast trigger
ENTRY_GATE_FAST_CANDLE_LIMIT = 300  # 300×5m = 25h lookback (matches 100×15m)

# Dashboard/live preview behavior
ENTRY_READINESS_LIVE_PREVIEW_ENABLED = False  # Opt-in live preview for non-active bots
ENTRY_READINESS_STOPPED_PREVIEW_ENABLED = True  # Runner-bounded analysis preview for stopped bots
ENTRY_READINESS_STOPPED_PREVIEW_MAX_BOTS = 2  # Cap preview refreshes per cycle (was 6 — too many API calls)
ENTRY_READINESS_STOPPED_PREVIEW_TTL_SEC = 60  # Fresh stopped-bot analysis cache lifetime (was 30 — refresh less often)
ENTRY_READINESS_STOPPED_PREVIEW_STALE_SEC = 300  # Stopped-bot analysis becomes stale after this (was 120)
ENTRY_READINESS_STRONG_DIRECTIONAL_MODE_FIT_MIN = 2.5  # Strong Enter-now label requires aligned directional mode fit
ENTRY_READINESS_STRONG_CONTINUATION_PROMOTION_ENABLED = True  # Enabled: promote only a narrow strong continuation subset earlier
ENTRY_READINESS_STRONG_CONTINUATION_SCORE_MIN = 74.0  # Require stronger-than-baseline quality before early continuation promotion
ENTRY_READINESS_STRONG_CONTINUATION_MODE_FIT_MIN = 4.0  # Require stronger directional fit than generic ready status
ENTRY_READINESS_STRONG_CONTINUATION_EXTENSION_RATIO_MAX = 0.45  # Stay well inside late/no-chase bounds for early continuation promotion
ENTRY_READINESS_STRONG_CONTINUATION_PRICE_ACTION_MIN = 2.0  # Require meaningful directional price-action support
ENTRY_READINESS_STRONG_CONTINUATION_SUPPORTIVE_STRUCTURE_MIN = 1.0  # Require nearby supportive structure when direction labeling is still developing
ENTRY_READINESS_STRONG_CONTINUATION_CONFIRMATION_MIN = 1.0  # Require positive volume or MTF confirmation before armed->trigger promotion
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_ENABLED = True  # Enabled: allow only the cleanest directional continuation cases through moderate nearby adverse structure
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_SCORE_MIN = 72.0  # Require good quality before relaxing the structure gate
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_MODE_FIT_MIN = 3.5  # Require decent directional fit before relaxing nearby resistance/support
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_PRICE_ACTION_MIN = 2.5  # Require directional price action to stay clearly supportive
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_SUPPORTIVE_STRUCTURE_MIN = 1.0  # Require some supportive structure before relaxing adverse structure
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_CONFIRMATION_MIN = 1.0  # Require positive volume or MTF confirmation before relaxing the structure gate
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_EXTENSION_RATIO_MAX = 0.55  # Keep the relaxation inside no-chase bounds and below late continuation territory
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_MIN_DISTANCE_RATIO = 0.65  # Do not relax if adverse structure is too close to price
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_MAX_STRENGTH = 10  # Do not relax against very strong nearby adverse levels
ENTRY_GATE_EXPERIMENTAL_DIRECTIONAL_STRUCTURE_RELAX_SIGNAL_CODES = (
    "early_entry",
    "good_continuation",
    "confirmed_breakout",
)

# =============================================================================
# AI Advisor Layer v1 (read-only, bounded, cheap-first)
# =============================================================================
AI_ADVISOR_ENABLED = os.getenv("AI_ADVISOR_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AI_ADVISOR_PROVIDER = (
    os.getenv("AI_ADVISOR_PROVIDER")
    or os.getenv("OPENROUTER_PROVIDER")
    or "openrouter"
).strip().lower()
AI_ADVISOR_PRIMARY_MODEL = (
    os.getenv("AI_ADVISOR_MODEL_PRIMARY")
    or os.getenv("AI_ADVISOR_PRIMARY_MODEL")
    or os.getenv("OPENROUTER_MODEL")
    or "openai/gpt-5-nano"
).strip()
AI_ADVISOR_ESCALATION_MODEL = (
    os.getenv("AI_ADVISOR_MODEL_ESCALATION")
    or os.getenv("AI_ADVISOR_ESCALATION_MODEL")
    or "openai/gpt-5-mini"
).strip()
AI_ADVISOR_ESCALATION_ENABLED = os.getenv(
    "AI_ADVISOR_ESCALATION_ENABLED",
    "0",
).strip().lower() in {"1", "true", "yes", "on"}
AI_ADVISOR_API_KEY = (
    os.getenv("AI_ADVISOR_API_KEY")
    or os.getenv("OPENROUTER_API_KEY")
    or ""
).strip()
AI_ADVISOR_BASE_URL = (
    os.getenv("AI_ADVISOR_BASE_URL")
    or "https://openrouter.ai/api/v1"
).strip()
AI_ADVISOR_TIMEOUT_SECONDS = max(
    float(os.getenv("AI_ADVISOR_TIMEOUT_SECONDS", "8") or 8.0),
    1.0,
)
AI_ADVISOR_MAX_OUTPUT_TOKENS = max(
    int(os.getenv("AI_ADVISOR_MAX_OUTPUT_TOKENS", "180") or 180),
    64,
)
AI_ADVISOR_TEMPERATURE = min(
    max(float(os.getenv("AI_ADVISOR_TEMPERATURE", "0.1") or 0.1), 0.0),
    1.0,
)
AI_ADVISOR_MAX_CALLS_PER_SYMBOL_WINDOW = max(
    int(os.getenv("AI_ADVISOR_MAX_CALLS_PER_SYMBOL_WINDOW", "2") or 2),
    1,
)
AI_ADVISOR_CALL_WINDOW_SECONDS = max(
    int(os.getenv("AI_ADVISOR_CALL_WINDOW_SECONDS", "1800") or 1800),
    60,
)
AI_ADVISOR_DEDUPE_TTL_SECONDS = max(
    int(os.getenv("AI_ADVISOR_DEDUPE_TTL_SECONDS", "900") or 900),
    60,
)
AI_ADVISOR_PRIMARY_MIN_CONFIDENCE = min(
    max(float(os.getenv("AI_ADVISOR_PRIMARY_MIN_CONFIDENCE", "0.60") or 0.60), 0.0),
    1.0,
)
AI_ADVISOR_TRIGGER_POLICIES = (
    "initial_entry",
    "grid_opening",
)
AI_ADVISOR_HTTP_REFERER = (
    os.getenv("AI_ADVISOR_HTTP_REFERER")
    or os.getenv("OPENROUTER_SITE_URL")
    or os.getenv("OPENROUTER_HTTP_REFERER")
    or ""
).strip()
AI_ADVISOR_X_TITLE = (
    os.getenv("AI_ADVISOR_X_TITLE")
    or os.getenv("OPENROUTER_APP_NAME")
    or os.getenv("OPENROUTER_X_TITLE")
    or "Opus Trader"
).strip()
AI_ADVISOR_ANALYTICS_LOOKBACK_SECONDS = max(
    int(os.getenv("AI_ADVISOR_ANALYTICS_LOOKBACK_SECONDS", "604800") or 604800),
    3600,
)
AI_ADVISOR_ANALYTICS_DECISION_LIMIT = max(
    int(os.getenv("AI_ADVISOR_ANALYTICS_DECISION_LIMIT", "1200") or 1200),
    100,
)
AI_ADVISOR_ANALYTICS_RECENT_LIMIT = max(
    int(os.getenv("AI_ADVISOR_ANALYTICS_RECENT_LIMIT", "200") or 200),
    20,
)
AI_ADVISOR_ANALYTICS_EXECUTION_WINDOW_SECONDS = max(
    int(os.getenv("AI_ADVISOR_ANALYTICS_EXECUTION_WINDOW_SECONDS", "1800") or 1800),
    60,
)
AI_ADVISOR_ANALYTICS_OUTCOME_WINDOW_SECONDS = max(
    int(os.getenv("AI_ADVISOR_ANALYTICS_OUTCOME_WINDOW_SECONDS", "86400") or 86400),
    300,
)
AI_ADVISOR_ANALYTICS_SNAPSHOT_TTL_SECONDS = max(
    int(os.getenv("AI_ADVISOR_ANALYTICS_SNAPSHOT_TTL_SECONDS", "30") or 30),
    5,
)

# =============================================================================
# Trade Forensics Foundation (bounded lifecycle logging)
# =============================================================================
TRADE_FORENSICS_ENABLED = os.getenv("TRADE_FORENSICS_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
TRADE_FORENSICS_DECISION_DEDUPE_TTL_SECONDS = max(
    int(os.getenv("TRADE_FORENSICS_DECISION_DEDUPE_TTL_SECONDS", "300") or 300),
    30,
)
TRADE_FORENSICS_RECENT_EVENT_LIMIT = max(
    int(os.getenv("TRADE_FORENSICS_RECENT_EVENT_LIMIT", "500") or 500),
    100,
)
DECISION_SNAPSHOT_ENABLED = os.getenv("DECISION_SNAPSHOT_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
DECISION_SNAPSHOT_LOOKBACK_SECONDS = max(
    int(os.getenv("DECISION_SNAPSHOT_LOOKBACK_SECONDS", "604800") or 604800),
    3600,
)
DECISION_SNAPSHOT_EVENT_LIMIT = max(
    int(os.getenv("DECISION_SNAPSHOT_EVENT_LIMIT", "3000") or 3000),
    200,
)
DECISION_SNAPSHOT_RECENT_LIMIT = max(
    int(os.getenv("DECISION_SNAPSHOT_RECENT_LIMIT", "200") or 200),
    20,
)
DECISION_SNAPSHOT_TTL_SECONDS = max(
    int(os.getenv("DECISION_SNAPSHOT_TTL_SECONDS", "30") or 30),
    5,
)

# Smart price-action confluence used by Auto-Pilot ranking and Entry Gate
SMART_PRICE_ACTION_ENABLED = True
SMART_PRICE_ACTION_TIMEFRAME = "5"
SMART_PRICE_ACTION_CANDLE_LIMIT = 480
SMART_PRICE_ACTION_SWING_THRESHOLD = 3
SMART_PRICE_ACTION_BREAK_BUFFER_PCT = 0.0015  # 0.15% beyond swing = valid break
SMART_PRICE_ACTION_LIQUIDITY_PROXIMITY_PCT = 0.015  # Only sweep nearby levels
SMART_PRICE_ACTION_SWEEP_PIERCE_PCT = 0.0008  # Minimum sweep beyond level
SMART_PRICE_ACTION_SWEEP_MAX_PCT = 0.0060  # Ignore oversized sweeps / chaos
SMART_PRICE_ACTION_WICK_BODY_MIN_RATIO = 1.5
SMART_PRICE_ACTION_WICK_RANGE_MIN_RATIO = 0.45
SMART_PRICE_ACTION_VOLUME_CONFIRM_RATIO = 1.25
SMART_PRICE_ACTION_VOLUME_STRONG_RATIO = 1.80
SMART_PRICE_ACTION_VOLUME_WEAK_RATIO = 0.75
SMART_PRICE_ACTION_RECLAIM_MARGIN_PCT = 0.0005
SMART_PRICE_ACTION_MTF_TIMEFRAMES = ["5", "15", "60"]
SMART_PRICE_ACTION_MTF_WEIGHTS = {
    "5": 0.15,
    "15": 0.40,
    "60": 0.45,
}
SMART_PRICE_ACTION_STRUCTURE_BREAK_SCORE = 8.0
SMART_PRICE_ACTION_STRUCTURE_TREND_SCORE = 5.0
SMART_PRICE_ACTION_STRUCTURE_RECLAIM_BONUS = 3.0
SMART_PRICE_ACTION_SWEEP_SCORE = 10.0
SMART_PRICE_ACTION_MTF_WEIGHT_MULTIPLIER = 0.25
SMART_PRICE_ACTION_MTF_SCORE_CAP = 10.0
SMART_PRICE_ACTION_VOLUME_CONFIRM_SCORE = 3.0
SMART_PRICE_ACTION_VOLUME_STRONG_SCORE = 6.0
SMART_PRICE_ACTION_LOW_VOLUME_PENALTY = 2.0
SMART_PRICE_ACTION_DIRECTION_THRESHOLD = 4.0
SMART_PRICE_ACTION_COMPONENT_MIN_SCORE = 2.0
SMART_PRICE_ACTION_MODE_WEIGHT = 0.50
SMART_PRICE_ACTION_MODE_SCORE_CAP = 14.0
SMART_PRICE_ACTION_NEUTRAL_BASE_SCORE = 8.0
SMART_PRICE_ACTION_NEUTRAL_PENALTY_WEIGHT = 0.35
SMART_PRICE_ACTION_NEUTRAL_NET_PENALTY_WEIGHT = 0.15
SMART_PRICE_ACTION_NEUTRAL_BALANCE_BONUS = 4.0
SMART_PRICE_ACTION_SCALP_WEIGHT = 0.25
SMART_PRICE_ACTION_SCALP_BALANCE_BONUS = 2.0

# Unified setup-quality overlay (disabled by default for backward safety)
SETUP_QUALITY_SCORE_ENABLED = True
SETUP_QUALITY_MIN_ENTRY_SCORE = 42.0  # Was 50 — blocked 100% of entries. 42 lets "caution" band through.
SETUP_QUALITY_MIN_BREAKOUT_SCORE = 50.0  # Was 58 — too strict for breakout entries.
SETUP_QUALITY_LOGGING_ENABLED = True
SETUP_QUALITY_CAUTION_SCORE = 60.0
SETUP_QUALITY_STRONG_SCORE = 72.0
SETUP_QUALITY_PRICE_ACTION_WEIGHT = 10.0
SETUP_QUALITY_MODE_FIT_WEIGHT = 12.0
SETUP_QUALITY_SUPPORTIVE_STRUCTURE_WEIGHT = 10.0
SETUP_QUALITY_ADVERSE_STRUCTURE_WEIGHT = 16.0
SETUP_QUALITY_VOLUME_WEIGHT = 5.0
SETUP_QUALITY_MTF_WEIGHT = 5.0
SETUP_QUALITY_CANDLE_WEIGHT = 4.0
SETUP_QUALITY_ADX_WEIGHT = 4.0
SETUP_QUALITY_ATR_WEIGHT = 5.0
SETUP_QUALITY_BBW_WEIGHT = 3.0
SETUP_QUALITY_VELOCITY_WEIGHT = 5.0
SETUP_QUALITY_STRUCTURE_PROXIMITY_PCT = 0.02
SETUP_QUALITY_HIGH_ATR_PCT = 0.05
SETUP_QUALITY_HIGH_BBW_PCT = 0.08
SETUP_QUALITY_ENTRY_AGGRESSIVENESS_CAUTION = 0.85
SETUP_QUALITY_ENTRY_AGGRESSIVENESS_POOR = 0.70
SETUP_QUALITY_GRID_SPACING_MULT_CAUTION = 1.10
SETUP_QUALITY_GRID_SPACING_MULT_POOR = 1.20
SETUP_QUALITY_GRID_LEVEL_MULT_CAUTION = 0.90
SETUP_QUALITY_GRID_LEVEL_MULT_POOR = 0.75
SETUP_QUALITY_AUTO_PILOT_SCORE_WEIGHT = 0.35  # was 0.20 — heavier quality influence
SETUP_QUALITY_AUTO_PILOT_MIN_SCORE = 60.0  # Block candidates below "Good" band (<60)

# Conservative support/resistance-aware grid overlay
SR_AWARE_GRID_ENABLED = True
SR_AWARE_GRID_MIN_LEVEL_DISTANCE_PCT = 0.0030
SR_AWARE_GRID_SPACING_MULT_NEAR_ADVERSE_LEVEL = 1.15
SR_AWARE_GRID_MAX_LEVEL_REDUCTION = 2
SR_AWARE_GRID_LOGGING_ENABLED = True

# Toggleable audit diagnostics
AUDIT_DIAGNOSTICS_ENABLED = True
AUDIT_DIAGNOSTICS_EVENT_THROTTLE_SEC = 60
AUDIT_DIAGNOSTICS_SUMMARY_ENABLED = True
AUDIT_DIAGNOSTICS_HEALTH_WINDOW_SEC = 1800
AUDIT_DIAGNOSTICS_SUMMARY_TOP_N = 5
AUDIT_DIAGNOSTICS_RECENT_EVENT_LIMIT = 24
AUDIT_DIAGNOSTICS_REVIEW_WINDOWS_SEC = {
    "last_15m": 900,
    "last_1h": 3600,
}

# Passive watchdog diagnostics
WATCHDOG_DIAGNOSTICS_ENABLED = True

LOSS_ASYMMETRY_WATCHDOG_ENABLED = True
LOSS_ASYMMETRY_WATCHDOG_WINDOW_TRADES = 12
LOSS_ASYMMETRY_WATCHDOG_MIN_TRADES = 6
LOSS_ASYMMETRY_WATCHDOG_HIGH_WIN_RATE_PCT = 55.0
LOSS_ASYMMETRY_WATCHDOG_WARN_PAYOFF_RATIO = 0.8
LOSS_ASYMMETRY_WATCHDOG_WARN_PROFIT_FACTOR = 0.95
LOSS_ASYMMETRY_WATCHDOG_COOLDOWN_SEC = 900

EXIT_STACK_WATCHDOG_ENABLED = True
EXIT_STACK_WATCHDOG_WINDOW_SECONDS = 21600
EXIT_STACK_WATCHDOG_MIN_EVENTS = 4
EXIT_STACK_WATCHDOG_WARN_FORCED_EXIT_SHARE = 0.40
EXIT_STACK_WATCHDOG_COOLDOWN_SEC = 900

SMALL_BOT_SIZING_WATCHDOG_ENABLED = True
SMALL_BOT_SIZING_WATCHDOG_COOLDOWN_SEC = 300

SIGNAL_DRIFT_WATCHDOG_ENABLED = True
SIGNAL_DRIFT_WATCHDOG_COOLDOWN_SEC = 300

STATE_FLAPPING_WATCHDOG_ENABLED = True
STATE_FLAPPING_WATCHDOG_WINDOW_SEC = 180
STATE_FLAPPING_WATCHDOG_MIN_CHANGES = 4
STATE_FLAPPING_WATCHDOG_MIN_ACTIONABLE_FLIPS = 2
STATE_FLAPPING_WATCHDOG_COOLDOWN_SEC = 300

PNL_ATTRIBUTION_WATCHDOG_ENABLED = True
PNL_ATTRIBUTION_WATCHDOG_WINDOW_TRADES = 20
PNL_ATTRIBUTION_WATCHDOG_MIN_TRADES = 5
PNL_ATTRIBUTION_WATCHDOG_WARN_UNATTRIBUTED_SHARE = 0.20
PNL_ATTRIBUTION_WATCHDOG_WARN_AMBIGUOUS_SHARE = 0.10
PNL_ATTRIBUTION_WATCHDOG_COOLDOWN_SEC = 900

PROFIT_PROTECTION_WATCHDOG_ENABLED = True
PROFIT_PROTECTION_WATCHDOG_COOLDOWN_SEC = 180

# Order starvation watchdog (Phase 1)
ORDER_STARVATION_WATCHDOG_ENABLED = True
ORDER_STARVATION_WATCHDOG_COOLDOWN_SEC = 120
ORDER_STARVATION_WARN_THRESHOLD = 3
ORDER_STARVATION_ERROR_THRESHOLD = 5
ORDER_STARVATION_BLOCK_THRESHOLD = 10

# Position divergence watchdog (Phase 2)
POSITION_DIVERGENCE_WATCHDOG_ENABLED = True
POSITION_DIVERGENCE_WATCHDOG_COOLDOWN_SEC = 60
POSITION_DIVERGENCE_TOLERANCE_PCT = 0.05

# SL failure watchdog (Phase 3)
SL_FAILURE_WATCHDOG_ENABLED = True
SL_FAILURE_WATCHDOG_COOLDOWN_SEC = 120
SL_REJECTION_CRITICAL_THRESHOLD = 3

# Fill slippage watchdog (Phase 5)
FILL_SLIPPAGE_WATCHDOG_ENABLED = True
FILL_SLIPPAGE_WATCHDOG_COOLDOWN_SEC = 300
FILL_SLIPPAGE_WARN_BPS = 20
FILL_SLIPPAGE_CLUSTER_THRESHOLD = 3
FILL_SLIPPAGE_HISTORY_SIZE = 10

# Cycle SLA watchdog (Phase 9)
CYCLE_SLA_WARN_SECONDS = 30.0
CYCLE_SLA_BREACH_ALERT_COUNT = 3

# Watchdog Center Hub
WATCHDOG_HUB_ENABLED = True
WATCHDOG_HUB_ACTIVE_GRACE_SEC = 600
WATCHDOG_HUB_RECENT_WINDOW_SEC = 14400
WATCHDOG_HUB_MAX_RECENT_EVENTS = 40
WATCHDOG_HUB_RESOLVED_RETENTION_SEC = 21600

# Optional breakout-confirmed directional entry mode
BREAKOUT_CONFIRMED_ENTRY_ENABLED = True
BREAKOUT_CONFIRM_CANDLES = 1
BREAKOUT_CONFIRM_BUFFER_PCT = 0.0010
BREAKOUT_CONFIRM_REQUIRE_VOLUME = True
BREAKOUT_CONFIRM_REQUIRE_MTF_ALIGN = False
BREAKOUT_CONFIRM_DIRECTIONAL_ONLY = True

# Conservative no-chase guard for breakout-confirmed directional entries
BREAKOUT_NO_CHASE_FILTER_ENABLED = True
BREAKOUT_NO_CHASE_MAX_EXTENSION_ATR_MULT = 1.2
BREAKOUT_NO_CHASE_MAX_EXTENSION_PCT = 0.006
BREAKOUT_EXTENSION_LATE_RATIO_CAP = 0.6
BREAKOUT_NO_CHASE_LOGGING_ENABLED = True

# Conservative staged breakout invalidation de-risking for directional entries
BREAKOUT_INVALIDATION_EXIT_ENABLED = True
BREAKOUT_INVALIDATION_CONFIRM_CANDLES = 2
BREAKOUT_INVALIDATION_RECLAIM_BUFFER_PCT = 0.0010
BREAKOUT_INVALIDATION_PARTIAL_TRIM_ENABLED = True
BREAKOUT_INVALIDATION_PARTIAL_TRIM_CLOSE_PCT = 0.12
BREAKOUT_INVALIDATION_CLOSE_ON_PERSIST_ENABLED = True
BREAKOUT_INVALIDATION_PERSIST_SECONDS = 180
BREAKOUT_INVALIDATION_LOGGING_ENABLED = True

# Future moderate preset reference (inactive; do not enable automatically)
# Keep the active conservative values above unchanged until live observation
# shows the current rollout is too restrictive.
# Even under this moderate reference, keep per-bot breakout_confirmed_entry
# opt-in only and do not mass-enable it across existing bots.
# SETUP_QUALITY_MODERATE_SCORE_ENABLED = True
# SETUP_QUALITY_MODERATE_MIN_ENTRY_SCORE = 50.0
# SETUP_QUALITY_MODERATE_MIN_BREAKOUT_SCORE = 58.0
# SETUP_QUALITY_MODERATE_LOGGING_ENABLED = True
# SR_AWARE_GRID_MODERATE_ENABLED = True
# SR_AWARE_GRID_MODERATE_MIN_LEVEL_DISTANCE_PCT = 0.0025
# SR_AWARE_GRID_MODERATE_SPACING_MULT_NEAR_ADVERSE_LEVEL = 1.10
# SR_AWARE_GRID_MODERATE_MAX_LEVEL_REDUCTION = 1
# SR_AWARE_GRID_MODERATE_LOGGING_ENABLED = True
# BREAKOUT_CONFIRM_MODERATE_ENABLED = True
# BREAKOUT_CONFIRM_MODERATE_CANDLES = 1
# BREAKOUT_CONFIRM_MODERATE_BUFFER_PCT = 0.0010
# BREAKOUT_CONFIRM_MODERATE_REQUIRE_VOLUME = True
# BREAKOUT_CONFIRM_MODERATE_REQUIRE_MTF_ALIGN = False
# BREAKOUT_CONFIRM_MODERATE_DIRECTIONAL_ONLY = True

# =============================================================================
# Order Book Imbalance (NEW - Smart Feature #22)
# =============================================================================
# Analyzes bid/ask depth ratio to detect buying/selling pressure
# Heavy bids = bullish pressure (support), Heavy asks = bearish (resistance)
# Leading indicator - shows where liquidity is before price moves

ORDERBOOK_ENABLED = True  # Master toggle
ORDERBOOK_DEPTH_LEVELS = 20  # Number of price levels to analyze
ORDERBOOK_WEAK_THRESHOLD = 0.15  # 15% imbalance = weak signal
ORDERBOOK_STRONG_THRESHOLD = 0.35  # 35% imbalance = strong signal
ORDERBOOK_EXTREME_THRESHOLD = 0.55  # 55% imbalance = extreme signal
ORDERBOOK_MAX_SCORE = 15  # Max +/- points from order book
ORDERBOOK_CACHE_SECONDS = 5  # Cache for 5 seconds (order book is fast)

# =============================================================================
# Fast Execution Layer (1m) - Partial TP + Profit Lock
# =============================================================================
PARTIAL_TP_ENABLED = True
PARTIAL_TP_FRACTIONS = [0.25, 0.50, 0.25]
PARTIAL_TP_TRIGGER_ATR_MULT = 0.45
PARTIAL_TP_MIN_PROFIT_PCT = 0.002  # 0.35%
PARTIAL_TP_COOLDOWN_SEC = 120

PROFIT_LOCK_ENABLED = True
PROFIT_LOCK_ARM_PCT = 0.004  # 0.8%
PROFIT_LOCK_GIVEBACK_PCT = 0.002  # 0.35%
PROFIT_LOCK_CLOSE_FRACTION = 0.50
PROFIT_LOCK_COOLDOWN_SEC = 180
PROFIT_LOCK_FAST_ARM_ENABLED = True
PROFIT_LOCK_FAST_ARM_WINDOW_SECONDS = 180
PROFIT_LOCK_FAST_ARM_MIN_TRADE_AGE_SECONDS = 20
PROFIT_LOCK_FAST_ARM_MIN_PROFIT_PCT = 0.003
PROFIT_LOCK_FAST_ARM_THRESHOLD_MULTIPLIER = 1.10
PROFIT_LOCK_FAST_ARM_ARM_MULTIPLIER = 0.80
PROFIT_LOCK_FAST_ARM_VOLATILITY_ATR_PCT = 0.025

# =============================================================================
# Adaptive Profit Protection / Exit Advisory (Phase 7)
# =============================================================================
ADAPTIVE_PROFIT_PROTECTION_MODE = "partial_live"  # Was shadow — now actually executes partial closes on giveback
ADAPTIVE_PROFIT_PROTECTION_MIN_ARM_PROFIT_PCT = 0.004
ADAPTIVE_PROFIT_PROTECTION_MIN_GIVEBACK_PCT = 0.0015
ADAPTIVE_PROFIT_PROTECTION_GIVEBACK_SENSITIVITY = 0.90
ADAPTIVE_PROFIT_PROTECTION_ARM_ATR_MULT = 0.60
ADAPTIVE_PROFIT_PROTECTION_PARTIAL_FRACTION = 0.33
ADAPTIVE_PROFIT_PROTECTION_TREND_LOOSEN_MULT = 1.35
ADAPTIVE_PROFIT_PROTECTION_WEAK_TREND_TIGHTEN_MULT = 0.88
ADAPTIVE_PROFIT_PROTECTION_SIDEWAYS_TIGHTEN_MULT = 0.82
ADAPTIVE_PROFIT_PROTECTION_MOMENTUM_FADING_TIGHTEN_MULT = 0.88
ADAPTIVE_PROFIT_PROTECTION_COOLDOWN_SEC = 240
ADAPTIVE_PROFIT_PROTECTION_REARM_GUARD_SEC = 180
ADAPTIVE_PROFIT_PROTECTION_SHADOW_EVAL_ENABLED = True
ADAPTIVE_PROFIT_PROTECTION_SHADOW_SAVED_GIVEBACK_PCT = 0.0020

# Quick profit ATR scale factor (how much of ATR move to capture)
QUICK_PROFIT_ATR_SCALE_FACTOR = 0.60  # 60% of ATR — scalp=0.4, trend=0.8
# Trailing TP flow confirmation thresholds
TRAILING_TP_FLOW_THRESHOLD = 15  # Flow score needed to activate trailing
TRAILING_TP_FLOW_CONFIDENCE = 0.35  # Flow confidence needed to activate trailing
TRAILING_TP_FIRST_CLOSE_ENABLED = True  # Take first partial close before activating trailing
TRAILING_TP_FIRST_CLOSE_PCT = 0.50  # Close 50% on first profit, trail the remainder
# Flow-based loss cut timing
FLOW_LOSS_CUT_SUSTAINED_SEC = 45  # Seconds of sustained flow opposition before cutting (was 30 — too aggressive, false cuts on noise)
ADAPTIVE_PROFIT_PROTECTION_SHADOW_TREND_CUT_PCT = 0.0035
ADAPTIVE_PROFIT_PROTECTION_SHADOW_PREMATURE_PCT = 0.0025

FAST_EXEC_TAKER_FEE_RATE = 0.00055  # 0.055% taker fee (conservative)
FAST_EXEC_SLIPPAGE_BUFFER_PCT = 0.001  # 0.10% slippage buffer

# =============================================================================
# Partial Take-Profit Configuration (NEW - Smart Feature #16)
# =============================================================================
# Scale out of positions instead of all-or-nothing TP
# Close portions at multiple TP levels to lock in gains while letting winners run

ENABLE_PARTIAL_TAKE_PROFIT = True  # Master toggle
PARTIAL_TP_LEVELS = [  # List of (profit_pct, close_pct) tuples
    (0.003, 0.40),  # At 0.3% profit, close 40%
    (0.006, 0.35),  # At 0.6% profit, close 35% more
    (0.010, 0.25),  # At 1.0% profit, close remaining 25%
]
PARTIAL_TP_MIN_POSITION_USDT = 5.0  # Minimum remaining position value
PARTIAL_TP_COOLDOWN_SECONDS = 30  # Wait between partial closes

# =============================================================================
# Trend Reversal Protection (NEW - Smart Feature #17)
# =============================================================================
# Detects when market trend reverses against current position and auto-closes
# Prevents holding losing positions when trend flips (SHORT in uptrend, etc.)

ENABLE_TREND_REVERSAL_PROTECTION = False  # Master toggle

# =============================================================================
# Trend Exit Guard (neutral only)
# =============================================================================
TREND_EXIT_GUARD_ENABLED = False

# =============================================================================
# Margin/Order Cancellation Guards
# =============================================================================
MARGIN_BUFFER_ENABLED = True  # Prevent orders when margin is tight
EMERGENCY_CANCEL_FAR_ORDERS_ENABLED = True  # Auto-cancel distant orders on liquidation threat

# =============================================================================
# Auto-Margin Balance Preservation
# =============================================================================
# Keep a portion of free balance untouched for orders/fees.
AUTO_MARGIN_KEEP_FREE_PCT = 0.0  # Keep 0% of available balance
AUTO_MARGIN_KEEP_FREE_USDT = 0.1  # Always keep at least $0.10

# Margin monitor balance preservation (global)
MARGIN_MONITOR_KEEP_FREE_PCT = 0.02  # Keep 2% of available balance free
MARGIN_MONITOR_KEEP_FREE_USDT = 5.0  # Always keep at least $5.00 free

# Trend detection thresholds
TREND_REVERSAL_ADX_MIN = 20  # Need ADX >= 20 to confirm trend exists
TREND_REVERSAL_RSI_LONG = 55  # RSI > 55 = bullish trend (bad for shorts)
TREND_REVERSAL_RSI_SHORT = 45  # RSI < 45 = bearish trend (bad for longs)

# EMA confirmation (price vs EMA alignment)
TREND_REVERSAL_USE_EMA = True  # Use EMA for trend confirmation
TREND_REVERSAL_EMA_PERIOD = 20  # EMA period for trend detection

# Confirmation requirements
TREND_REVERSAL_CONFIRM_CANDLES = 2  # Need 2 confirming candles before action
TREND_REVERSAL_CONFIRM_SECONDS = 60  # Wait 60s after detection before acting

# Action settings
TREND_REVERSAL_CLOSE_POSITION = True  # Close the position when reversal detected
TREND_REVERSAL_SWITCH_MODE = True  # Switch bot mode to new trend direction
TREND_REVERSAL_COOLDOWN_SECONDS = 300  # 5 min cooldown before another reversal action

# =============================================================================
# Auto-Stop on Balance Target (NEW - Smart Feature #19)
# =============================================================================
# Automatically stops bot, closes position, and cancels orders when
# wallet balance reaches the target amount. Set per-bot or globally.

ENABLE_AUTO_STOP_ON_TARGET = True  # Master toggle for auto-stop feature
AUTO_STOP_DEFAULT_TARGET_USDT = 0.0  # Default target (0 = disabled)
AUTO_STOP_CLOSE_POSITION = True  # Close open position when target hit
AUTO_STOP_CANCEL_ORDERS = True  # Cancel all open orders when target hit
AUTO_STOP_USE_WALLET_BALANCE = True  # True = wallet balance, False = equity

# =============================================================================
# Liquidation Level Awareness (NEW - Smart Feature #23)
# =============================================================================
# Estimates where liquidation clusters exist based on common leverage levels
# and recent swing highs/lows (likely entry points for other traders)
# Liquidation cascades create strong price moves - predicts bounce/dump zones

LIQUIDATION_ENABLED = True  # Master toggle
LIQUIDATION_LOOKBACK_CANDLES = 50  # Candles to analyze for swing points
LIQUIDATION_DANGER_ZONE_PCT = 2.0  # % distance to be "in danger zone"
LIQUIDATION_TARGET_ZONE_PCT = 5.0  # % distance for clusters to be relevant
LIQUIDATION_MAX_SCORE = 15  # Max +/- points from liquidation levels
LIQUIDATION_CLUSTER_THRESHOLD_PCT = 0.5  # % threshold to group levels into clusters

# =============================================================================
# Session-Based Trading (NEW - Smart Feature #24)
# =============================================================================
# Adjusts trading based on market session characteristics
# Asian (00-08 UTC): Low vol, range-bound - good for grid
# European (08-16 UTC): Moderate vol, trending
# US (13-21 UTC): High vol, big moves
# EU/US Overlap (13-16 UTC): Highest vol, breakouts

SESSION_TRADING_ENABLED = True  # Master toggle
SESSION_MAX_SCORE = 10  # Max +/- points from session analysis
SESSION_REDUCE_WEEKEND = True  # Reduce position size on weekends
SESSION_WEEKEND_SIZE_MULT = 0.8  # Position size multiplier for weekends
SESSION_USE_VOLATILITY_ADJUST = True  # Adjust grid spacing by session volatility

# =============================================================================
# Mean Reversion Detector (NEW - Smart Feature #25)
# =============================================================================
# Identifies when price has deviated significantly from moving averages
# Price far above EMAs = overextended, likely pullback (bearish)
# Price far below EMAs = oversold, likely bounce (bullish)

MEAN_REVERSION_ENABLED = True  # Master toggle
MEAN_REVERSION_EMA_PERIODS = [20, 50, 100, 200]  # EMAs to analyze
MEAN_REVERSION_EXTREME_PCT = 3.0  # 3% deviation = extreme
MEAN_REVERSION_STRONG_PCT = 2.0  # 2% deviation = strong signal
MEAN_REVERSION_MODERATE_PCT = 1.0  # 1% deviation = moderate signal
MEAN_REVERSION_MAX_SCORE = 15  # Max +/- points from mean reversion
MEAN_REVERSION_USE_BB = True  # Also check Bollinger Band position
MEAN_REVERSION_USE_RSI = True  # Confirm with RSI overbought/oversold

# =============================================================================
# Whale Order Detection Settings
# =============================================================================
# Detects large orders (walls) on the order book that may act as S/R
WHALE_DETECTION_ENABLED = True  # Master toggle
WHALE_THRESHOLD_USD = 50000  # Minimum USD value for "whale" order ($50K)
WHALE_PROXIMITY_PCT = 2.0  # Max distance from price to consider (2%)
WHALE_MAX_SCORE = 20  # Max +/- points from whale detection
WHALE_CACHE_SECONDS = 5  # Cache duration (fast-moving data)

# =============================================================================
# Emergency Partial Close Settings (Smart Feature #27)
# =============================================================================
# When liquidation is near and no margin available, partially close position
# to# Emergency partial-close handles severe margin pressure or liq threat
EMERGENCY_PARTIAL_CLOSE_ENABLED = True  # Re-enabled with near-liq thresholds
EMERGENCY_PARTIAL_CLOSE_LIQ_PCT = 1.5  # Trigger when liq distance < 1.5%
EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT = 1.0  # Absolute floor trigger when liq distance < 1.0%
EMERGENCY_PARTIAL_CLOSE_QTY_PCT = 0.5  # Reduce position by 50% on each trigger
EMERGENCY_PARTIAL_CLOSE_MIN_BALANCE = (
    1.5  # Trigger if available < AUTO_MARGIN_RESERVE_USDT
)
EMERGENCY_PARTIAL_CLOSE_PCT = 25.0  # Tier 1 close size (% of position)
EMERGENCY_PARTIAL_CLOSE_TIER2_PCT = 50.0  # Tier 2 close size (% of position)
EMERGENCY_PARTIAL_CLOSE_COOLDOWN = 900  # Seconds between partial closes (15 min)
EMERGENCY_PARTIAL_CLOSE_MAX_COUNT = 3  # Max partial closes before escalation

# =============================================================================
# Smart Pause Recovery Settings (Smart Feature #28)
# =============================================================================
# When bot pauses with losing position, wait for recovery before closing
# Auto-resume when pause reason resolves
SMART_PAUSE_RECOVERY_ENABLED = True  # Master toggle
SMART_PAUSE_WAIT_FOR_PROFIT = True  # Wait for position to be profitable
SMART_PAUSE_MIN_PROFIT_PCT = 0.3  # Min profit % to close (0.3%)
SMART_PAUSE_MAX_WAIT_HOURS = 24  # Max hours to wait for recovery
SMART_PAUSE_AUTO_RESUME = True  # Auto-resume when reason resolves
SMART_PAUSE_CHECK_INTERVAL = 30  # Seconds between recovery checks

# =============================================================================
# Momentum-Aware DCA Settings (Smart Feature #29)
# =============================================================================
# Blocks DCA buy/sell orders during periods of extreme market momentum
# to avoid "buying the falling knife" in directional modes.
MOMENTUM_DCA_ENABLED = True  # Blocks DCA buys during extreme momentum (falling knife protection)
MOMENTUM_DCA_ADX_THRESHOLD = 35.0  # Block if 1m ADX > 35 (strong trend)
MOMENTUM_DCA_RSI_LONG_MIN = 30.0  # Block Long DCA if 1m RSI < 30 (falling knife)
MOMENTUM_DCA_RSI_SHORT_MAX = 70.0  # Block Short DCA if 1m RSI > 70 (rocket)
MOMENTUM_DCA_COOLDOWN_SEC = 300  # Cooldown after momentum slows (5 min)

# =============================================================================
# Auto Range Mode Settings (Smart Feature #30 - Re-numbered)
# =============================================================================
# Automatically switch range_mode based on market regime
# Strong trend → trailing (follow trend), Range-bound → dynamic (grid trading)
AUTO_RANGE_MODE_ENABLED = True  # Master toggle
AUTO_RANGE_MODE_ADX_TREND = 30  # ADX >= 30 = strong trend → trailing
AUTO_RANGE_MODE_ADX_RANGE = 20  # ADX <= 20 = range-bound → dynamic
AUTO_RANGE_MODE_BBW_NARROW = 2.0  # BBW <= 2% = tight range → dynamic
AUTO_RANGE_MODE_BBW_WIDE = 5.0  # BBW >= 5% = volatile → trailing
AUTO_RANGE_MODE_COOLDOWN = 300  # Seconds between range_mode changes (5 min)
AUTO_RANGE_MODE_DEFAULT = "dynamic"  # Default when uncertain

# =============================================================================
# Auto Neutral Mode Selection (Classic vs Dynamic)
# =============================================================================
# Automatically switch between neutral_classic_bybit (fixed range) and
# neutral (dynamic range) based on ADX/ATR thresholds with hysteresis.
AUTO_NEUTRAL_MODE_ENABLED = False
AUTO_NEUTRAL_MODE_COOLDOWN_SEC = 600  # Min seconds between mode switches
AUTO_NEUTRAL_CLASSIC_ADX_MAX = 22.0  # ADX <= this favors neutral classic
AUTO_NEUTRAL_CLASSIC_ATR_MAX = 0.04  # ATR% <= this favors neutral classic
AUTO_NEUTRAL_DYNAMIC_ADX_MIN = 28.0  # ADX >= this favors neutral dynamic
AUTO_NEUTRAL_DYNAMIC_ATR_MIN = 0.05  # ATR% >= this favors neutral dynamic

# =============================================================================
# UPnL Stop-Loss Symbol Defaults (NEW - Part 8)
# =============================================================================
# Applied when user doesn't set explicit values and upnl_stoploss_enabled=True
# Thresholds are NEGATIVE percentages (e.g., -12 means -12% loss triggers)

UPNL_STOPLOSS_SYMBOL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "ETHUSDT": {
        "max_position_pct": 85,  # Position cap for ETH — UPnL soft/hard stops handle risk
        "soft_pct": -25,  # Soft threshold: block new opens at -25%
        "hard_pct": -40,  # Hard threshold: close position at -40%
        "k1": 2.0,  # Drawdown trigger multiplier vs ATR% (15m)
        "liq_pct": 3.0,  # Hard trigger if liq distance <= 3%
        "cooldown_seconds": 300,  # 5 min cooldown after hard trigger
    },
    "__default__": {
        "max_position_pct": 85,  # Match base MAX_POSITION_PCT — UPnL soft/hard stops handle risk
        "soft_pct": -30,  # Soft threshold: block new opens at -30%
        "hard_pct": -45,  # Hard threshold: close position at -45%
        "k1": 1.5,  # Drawdown trigger multiplier vs ATR% (15m)
        "liq_pct": 3.0,  # Hard trigger if liq distance <= 3%
        "cooldown_seconds": 300,  # 5 min cooldown after hard trigger
    },
}


def get_upnl_stoploss_defaults(symbol: str) -> Dict[str, Any]:
    """
    Get UPnL stop-loss defaults for a symbol.

    Args:
        symbol: Trading pair symbol (e.g., "ETHUSDT", "FARTCOINUSDT")

    Returns:
        Dict with max_position_pct, soft_pct, hard_pct, k1, liq_pct, cooldown_seconds
    """
    return UPNL_STOPLOSS_SYMBOL_DEFAULTS.get(
        symbol, UPNL_STOPLOSS_SYMBOL_DEFAULTS["__default__"]
    )


# =============================================================================
# NEUTRAL MODE LOSS PREVENTION (neutral_classic_bybit)
# =============================================================================
# Loss-prevention features for neutral/grid mode to prevent inventory
# accumulation and breakout losses when price exits the grid range.

# -------------------------
# A) Breakout Guard
# -------------------------
# Detects when price breaks out of grid range and flattens position.
# Trigger: price outside range by threshold % for hold_seconds, or N candle closes.
NEUTRAL_BREAKOUT_GUARD_ENABLED = True  # Master toggle
NEUTRAL_BREAKOUT_THRESHOLD_PCT = 0.01  # 1.0% above upper / below lower grid
NEUTRAL_BREAKOUT_HOLD_SECONDS = 45  # Seconds price must stay outside range
NEUTRAL_BREAKOUT_CANDLE_CONFIRM = 2  # OR: consecutive 1m candle closes outside
NEUTRAL_BREAKOUT_COOLDOWN_SEC = 300  # Cooldown after flatten (5 minutes)
NEUTRAL_BREAKOUT_FLATTEN_ON_TRIGGER = True  # Flatten position when triggered

# -------------------------
# B) Inventory/Skew Cap
# -------------------------
# Limits net exposure in neutral mode to prevent one-sided inventory buildup.
# Blocks orders that worsen exposure, emergency reduces when severely exceeded.
NEUTRAL_INVENTORY_CAP_ENABLED = True  # Master toggle
NEUTRAL_INVENTORY_CAP_PCT = 0.30  # 30% of target notional (was 0.45 — 45% too aggressive for neutral mode)
NEUTRAL_INVENTORY_EMERGENCY_MULT = 1.5  # Emergency reduce if cap exceeded by 1.5x
NEUTRAL_INVENTORY_REDUCE_TO_PCT = 0.20  # Reduce to 20% of notional on emergency

# Hedge-mode per-leg caps (separate caps for long and short legs)
# In hedge mode, both legs can grow independently - net exposure can be zero
# while both legs are huge. This enables separate caps per leg.
NEUTRAL_HEDGE_LEG_CAP_ENABLED = True  # Master toggle for hedge-aware per-leg caps
# When enabled, applies NEUTRAL_INVENTORY_CAP_PCT to EACH leg independently
# (not just net exposure), preventing both legs from growing too large

# -------------------------
# C) Recenter/Range Freshness
# -------------------------
# Enhanced recentering to keep grid fresh around current price.
# Triggers on mid deviation, time interval, or boundary touch.
NEUTRAL_RECENTER_ENABLED = True  # Master toggle (enhances existing)
NEUTRAL_RECENTER_MID_DEVIATION_PCT = 0.0075  # 0.75% mid deviation triggers recenter
NEUTRAL_RECENTER_INTERVAL_SEC = 600  # Max 10 minutes between recenters
NEUTRAL_RECENTER_ON_BOUNDARY_TOUCH = True  # Recenter when price touches boundary
NEUTRAL_RECENTER_COOLDOWN_SEC = 600  # Minimum 10 minutes between recenters (was 300)

# -------------------------
# D) Max Loss / Equity Stop
# -------------------------
# Hard stop based on unrealized PnL - final safety brake.
# Stops bot when uPnL exceeds threshold (USD or % of margin).
NEUTRAL_MAX_LOSS_ENABLED = True  # Master toggle
NEUTRAL_MAX_LOSS_USD = 2.0  # Max unrealized loss in USD
NEUTRAL_MAX_LOSS_PCT = 0.08  # OR: 8% of margin
NEUTRAL_MAX_LOSS_USE_PCT = False  # False=USD mode, True=percentage mode
NEUTRAL_MAX_LOSS_COOLDOWN_SEC = 300  # Cooldown after max loss stop

# -------------------------
# E) Momentum Filter
# -------------------------
# Blocks neutral grid during strong short-term momentum (trending markets).
# Uses ADX, RSI, and Bollinger Band position to detect unsuitable conditions.
NEUTRAL_MOMENTUM_FILTER_ENABLED = True  # Master toggle
NEUTRAL_MOMENTUM_ADX_THRESHOLD = 30  # Block if 1m ADX > 30 (strong trend only)
NEUTRAL_MOMENTUM_RSI_UPPER = 72  # Block if 1m RSI > 72 (truly overbought)
NEUTRAL_MOMENTUM_RSI_LOWER = 28  # Block if 1m RSI < 28 (truly oversold)
NEUTRAL_MOMENTUM_BB_TOUCH_FILTER = True  # Block if price outside Bollinger Bands
NEUTRAL_MOMENTUM_BLOCK_ACTION = "pause_grid"  # "pause_grid" or "tighten_cap"
NEUTRAL_MOMENTUM_TIGHTEN_CAP_MULT = 0.5  # Reduce inventory cap to 50% when blocked

# =============================================================================
# NEUTRAL MODE PRESETS
# =============================================================================
# Production-ready configurations for different asset volatility profiles.
# MAJOR: BTC, ETH, SOL, BNB - less volatile, looser settings
# MEME: DOGE, SHIB, WIF, PEPE, BONK - more volatile, tighter risk controls

NEUTRAL_PRESET_ENABLED = True  # Enable preset system
NEUTRAL_DEFAULT_PRESET = "MAJOR"  # Default if not specified

NEUTRAL_PRESETS = {
    "MAJOR": {
        # Breakout Guard - more patient for stable assets
        "breakout_threshold_pct": 0.003,  # 0.3% outside range (vs 0.2%)
        "breakout_hold_seconds": 60,  # 60s hold (vs 45s)
        "breakout_cooldown_sec": 300,  # 5 min cooldown
        # Inventory Cap - larger positions allowed
        "inventory_cap_pct": 0.30,  # 30% per leg (vs 25%)
        "inventory_emergency_mult": 1.5,  # Emergency at 1.5x
        # Max Loss - percentage mode (default), higher tolerance for majors
        "max_loss_pct": 0.05,  # 5% of investment (default mode)
        "max_loss_usd": 2.50,  # $2.50 fallback if PCT disabled
        "max_loss_use_pct": True,  # Use percentage mode by default
        # Momentum Filter - more tolerant
        "momentum_adx_threshold": 28,  # ADX < 28 allowed
        "momentum_rsi_upper": 68,  # RSI < 68 allowed (vs 65)
        "momentum_rsi_lower": 32,  # RSI > 32 allowed (vs 35)
        # Recenter - less aggressive
        "recenter_mid_deviation_pct": 0.01,  # 1.0% deviation (vs 0.75%)
        "recenter_interval_sec": 900,  # 15 min max (vs 10 min)
    },
    "MEME": {
        # Breakout Guard - faster reaction for volatile assets
        "breakout_threshold_pct": 0.002,  # 0.2% outside range (tight)
        "breakout_hold_seconds": 30,  # 30s hold (fast reaction)
        "breakout_cooldown_sec": 300,  # 5 min cooldown
        # Inventory Cap - smaller positions to limit exposure
        "inventory_cap_pct": 0.20,  # 20% per leg (conservative)
        "inventory_emergency_mult": 1.3,  # Emergency at 1.3x (earlier)
        # Max Loss - percentage mode (default), tighter for protection
        "max_loss_pct": 0.03,  # 3% of investment (default mode)
        "max_loss_usd": 0.75,  # $0.75 fallback if PCT disabled
        "max_loss_use_pct": True,  # Use percentage mode by default
        # Momentum Filter - strict
        "momentum_adx_threshold": 22,  # ADX < 22
        "momentum_rsi_upper": 62,  # RSI < 62 (tight)
        "momentum_rsi_lower": 38,  # RSI > 38 (tight)
        # Recenter - more aggressive
        "recenter_mid_deviation_pct": 0.005,  # 0.5% deviation (aggressive)
        "recenter_interval_sec": 480,  # 8 min max (frequent)
    },
}

# Asset classification for auto-preset selection
NEUTRAL_MAJOR_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "MATICUSDT",
    "LINKUSDT",
]
# Anything not in MAJOR_SYMBOLS defaults to MEME preset

# =============================================================================
# NEUTRAL SUITABILITY GATE
# =============================================================================
# Gate that checks if market conditions are suitable for neutral/grid trading.
# Blocks neutral mode during trending markets to prevent losses.

NEUTRAL_GATE_ENABLED = True  # Master toggle

# 15-minute timeframe checks (primary)
NEUTRAL_GATE_ADX_15M_MAX = 32  # Block if ADX > 32 (strong trend only)
NEUTRAL_GATE_RSI_15M_UPPER = 72  # Block if RSI > 72 (truly overbought)
NEUTRAL_GATE_RSI_15M_LOWER = 28  # Block if RSI < 28 (truly oversold)
NEUTRAL_GATE_ATR_PCT_MAX = 0.04  # Block if ATR% > 4% (too volatile)

# 1-minute timeframe checks (optional, for immediate momentum)
NEUTRAL_GATE_1M_ENABLED = True  # Enable 1m momentum check
NEUTRAL_GATE_ADX_1M_MAX = 38  # Block if 1m ADX > 38 (extreme move only)

# Gate behavior
NEUTRAL_GATE_BLOCK_ACTION = "block_orders"  # "block_orders" = block new, allow closes
NEUTRAL_GATE_RECHECK_SECONDS = 60  # Recheck interval when blocked

# =============================================================================
# NEUTRAL MICRO-BIAS AWARENESS
# =============================================================================
# Detects slight directional drift to reduce inventory accumulation against
# the prevailing micro-trend. When bullish drift detected, skip some Sell
# ENTRY orders (and vice versa). EXIT orders are NEVER skipped.

NEUTRAL_MICRO_BIAS_ENABLED = True  # Master toggle

# Score thresholds (-1.0 to +1.0 scale)
NEUTRAL_MICRO_BIAS_THRESHOLD = 0.30  # Score threshold to trigger bias
NEUTRAL_MICRO_BIAS_STRONG = 0.50  # Strong bias threshold

# Skip probabilities (0.0 to 1.0)
MICRO_BIAS_SKIP_PCT_MODERATE = 0.40  # Skip 40% of counter-bias ENTRY orders
MICRO_BIAS_SKIP_PCT_STRONG = 0.70  # Skip 70% for strong bias

# Hysteresis to prevent flapping
MICRO_BIAS_HYSTERESIS_CHECKS = 2  # Require 2 consecutive readings in same direction

# Cache settings
MICRO_BIAS_CACHE_SECONDS = 10  # Recalculate bias every 10 seconds

# =============================================================================
# Smart Momentum Scanner Configuration (NEW - Smart Feature #26)
# =============================================================================
# Prioritize coins with High Momentum (ADX) + Safe Entry (RSI)
# Filter out "Pump & Dump" and "Dead Money"

SMART_MOMENTUM_ENABLED = False  # DEPRECATED — duplicates Auto-Pilot rotation logic
SMART_MOMENTUM_MIN_ADX = 30.0  # Min ADX to be considered "Fast"
SMART_MOMENTUM_MAX_RSI_LONG = 75.0  # Max RSI for safe entry (avoid tops)
SMART_MOMENTUM_MIN_VOLUME = 50_000_000.0  # Min 24h Volume (Liquidity)
SMART_MOMENTUM_PUMP_DUMP_VOLATILITY = 0.05  # 5% volatility spike = Danger

# Smart Momentum Scoring Weights & Thresholds (Audit Fix)
SMART_MOMENTUM_MAX_SCORE_MOMENTUM = 20  # ADX component
SMART_MOMENTUM_MAX_SCORE_SAFETY = 30  # RSI component
SMART_MOMENTUM_MAX_SCORE_VOLATILITY = 20  # ATR component
SMART_MOMENTUM_MAX_SCORE_VELOCITY = 15  # Velocity component

SMART_MOMENTUM_OPTIMAL_ATR_MIN = 0.005  # 0.5%
SMART_MOMENTUM_OPTIMAL_ATR_MAX = 0.05  # 5.0%
SMART_MOMENTUM_OPTIMAL_VELOCITY_MAX = 0.02  # 2.0%/hr
SMART_MOMENTUM_PUMP_RISK_VELOCITY = 0.03  # > 3.0%/hr
SMART_MOMENTUM_PUMP_RISK_VOLUME = 5_000_000  # < 5M USDT

# =============================================================================
# Auto-Pilot Rotation and universe controls
# =============================================================================
ENABLE_SMART_ROTATION = True
ENABLE_LEGACY_ROTATION = False
AUTO_PILOT_ROTATION_INTERVAL_SECONDS = 1800
AUTO_PILOT_ROTATION_SCORE_THRESHOLD = 7.0  # was 10.0 — lower bar for rotation
AUTO_PILOT_ADAPTIVE_ROTATION_ENABLED = True
AUTO_PILOT_ADAPTIVE_ROTATION_MIN_SECONDS = 900
AUTO_PILOT_ADAPTIVE_ROTATION_MAX_SECONDS = 2700
AUTO_PILOT_ROTATION_WEAK_SCORE = 65.0
AUTO_PILOT_ROTATION_HEALTHY_SCORE = 85.0

# Score-floor auto-drop: if current coin's AP score falls below this, force immediate rotation check
# Bypasses rotation interval and min hold time. Set to 0 to disable.
AUTO_PILOT_SCORE_FLOOR_DROP_THRESHOLD = 55.0  # Force rotation if live score degrades below this
AUTO_PILOT_ROTATION_HIGH_VOLATILITY_ATR_PCT = 0.035
AUTO_PILOT_VELOCITY_FACTOR_ENABLED = True
AUTO_PILOT_VELOCITY_WEIGHT = 6.0  # was 4.0 — stronger velocity signal
AUTO_PILOT_VELOCITY_REFERENCE_PER_HOUR = 0.015  # was 0.02 — more sensitive baseline
AUTO_PILOT_VELOCITY_COLLAPSE_PCT_PER_HOUR = 0.003
AUTO_PILOT_LOSS_BUDGET_GUARD_ENABLED = True
AUTO_PILOT_LOW_REMAINING_LOSS_BUDGET_PCT = 0.35
AUTO_PILOT_BLOCK_OPENINGS_BELOW_REMAINING_LOSS_PCT = 0.15
AUTO_PILOT_LOW_BUDGET_SCORE_BONUS_REQUIRED = 8.0
AUTO_PILOT_LOW_BUDGET_MAX_OPENING_NOTIONAL_MULT = 20.0
AUTO_PILOT_LOW_BUDGET_LOGGING_ENABLED = True
AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE = "default_safe"
AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL = "aggressive_full"
AUTO_PILOT_UNIVERSE_MODE = AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE
AUTO_PILOT_STRONG_FILTERS_ENABLED = True
AUTO_PILOT_EXCLUDE_INNOVATION_SYMBOLS = True
AUTO_PILOT_EXCLUDE_NEW_LISTINGS_ENABLED = True
AUTO_PILOT_NEW_LISTING_MIN_DAYS = 30
AUTO_PILOT_MAX_SCAN_SYMBOLS = 80  # was 60 — wider scan for faster movers
AUTO_PILOT_SYMBOL_BLACKLIST = (
    "BTCUSDT",
    "BANANAUSDT",
    "BANANAS31USDT",
    "FARTCOINUSDT",
    "TRUMPUSDT",
    "MELANIAUSDT",
)
AUTO_PILOT_SYMBOL_NAME_BLACKLIST_PATTERNS = (
    r"^1000[A-Z0-9]+USDT$",
    r"^1000000[A-Z0-9]+USDT$",
    r"^(?:BANANAS?|BROCCOLI|FART|TRUMP|MELANIA|MOODENG|PNUT|MUBARAK)[A-Z0-9]*USDT$",
)
AUTO_PILOT_MIN_24H_TURNOVER_USDT = 5_000_000  # Was 10M — expanded to include mid-cap gems
AUTO_PILOT_MIN_24H_VOLUME = 0
AUTO_PILOT_MIN_OPEN_INTEREST_USDT = 500_000
AUTO_PILOT_VOLATILITY_CAP_ENABLED = True
AUTO_PILOT_MIN_ATR_PCT = 0.01  # 1.0% minimum — reject dead-slow coins
AUTO_PILOT_MAX_ATR_PCT = 0.08  # was 0.05 — allow faster movers
AUTO_PILOT_MAX_INTRADAY_MOVE_PCT = 0.15  # was 0.18 — tighten pump guard
AUTO_PILOT_MAX_PRICE_VELOCITY_PER_HOUR = 0.05  # was 0.03 — widen velocity cap
# Optional aggressive mode for explicit high-risk Auto-Pilot coverage.
# This does not affect the default production-safe universe unless selected.
AUTO_PILOT_AGGRESSIVE_FULL_STRONG_FILTERS_ENABLED = True
AUTO_PILOT_AGGRESSIVE_FULL_EXCLUDE_INNOVATION_SYMBOLS = False
AUTO_PILOT_AGGRESSIVE_FULL_EXCLUDE_NEW_LISTINGS_ENABLED = False
AUTO_PILOT_AGGRESSIVE_FULL_NEW_LISTING_MIN_DAYS = 0
AUTO_PILOT_AGGRESSIVE_FULL_MAX_SCAN_SYMBOLS = 80  # Was 60 — wider aggressive scan
AUTO_PILOT_AGGRESSIVE_FULL_SYMBOL_BLACKLIST = ("BTCUSDT",)
AUTO_PILOT_AGGRESSIVE_FULL_SYMBOL_NAME_BLACKLIST_PATTERNS = ()
AUTO_PILOT_AGGRESSIVE_FULL_MIN_24H_TURNOVER_USDT = 1_000_000
AUTO_PILOT_AGGRESSIVE_FULL_MIN_24H_VOLUME = 0
AUTO_PILOT_AGGRESSIVE_FULL_MIN_OPEN_INTEREST_USDT = 100_000
AUTO_PILOT_AGGRESSIVE_FULL_VOLATILITY_CAP_ENABLED = True
AUTO_PILOT_AGGRESSIVE_FULL_MIN_ATR_PCT = 0.008  # 0.8% min for aggressive mode
AUTO_PILOT_AGGRESSIVE_FULL_MAX_ATR_PCT = 0.12
AUTO_PILOT_AGGRESSIVE_FULL_MAX_INTRADAY_MOVE_PCT = 0.40
AUTO_PILOT_AGGRESSIVE_FULL_MAX_PRICE_VELOCITY_PER_HOUR = 0.10
AUTO_PILOT_CANDIDATE_CACHE_ENABLED = True
AUTO_PILOT_CANDIDATE_CACHE_REFRESH_SECONDS = 180
AUTO_PILOT_CANDIDATE_CACHE_MAX_ITEMS = 12
AUTO_PILOT_CANDIDATE_CACHE_MAX_AGE_SECONDS = 240
AUTO_PILOT_CANDIDATE_CACHE_PERSIST_ENABLED = False

# Anti-churn protection
AUTO_PILOT_MIN_HOLD_SECONDS = 600  # 10 min minimum on a coin before rotation
AUTO_PILOT_MAX_ROTATIONS_PER_HOUR = 4  # Cap rotation churn
AUTO_PILOT_CHURN_PENALTY_PER_ROTATION = 2.0  # was 3.0 — less penalty for rotation

# ADX-based momentum bonus for Auto-Pilot scoring
AUTO_PILOT_ADX_MOMENTUM_BONUS_ENABLED = True
AUTO_PILOT_ADX_MOMENTUM_BONUS_MIN_ADX = 20.0
AUTO_PILOT_ADX_MOMENTUM_BONUS_MAX_ADX = 45.0
AUTO_PILOT_ADX_MOMENTUM_BONUS_MAX_POINTS = 8.0
AUTO_PILOT_ADX_MOMENTUM_BONUS_OVERHEATED_PENALTY = -4.0

# Universe pre-sort: blend turnover rank with momentum rank
AUTO_PILOT_UNIVERSE_MOMENTUM_SORT_ENABLED = True
AUTO_PILOT_UNIVERSE_MOMENTUM_SORT_WEIGHT = 0.35  # 35% momentum, 65% turnover

# Pending rotation timeout (prevents infinite stuck on losing coin)
AUTO_PILOT_PENDING_ROTATION_TIMEOUT_SEC = 1800  # 30 min max wait for position to flatten
AUTO_PILOT_IDLE_NO_FILL_ROTATION_SECONDS = 600  # 10 min with no fills triggers rotation

# Multi-timeframe confirmation
AUTO_PILOT_HTF_CONFIRMATION_ENABLED = True
AUTO_PILOT_HTF_INTERVAL = "60"  # 1-hour candles
AUTO_PILOT_HTF_TREND_ADX_THRESHOLD = 30  # ADX above this = hidden trend (downgrade neutral)
AUTO_PILOT_HTF_FLAT_ADX_THRESHOLD = 15  # ADX below this = truly flat (bonus for neutral)

# ADX-based grid freeze: stop accumulating one-sided entries in extreme trends
ADX_EXTREME_FREEZE_THRESHOLD = 35.0  # 1h ADX above this blocks accumulation-side entries


def normalize_auto_pilot_universe_mode(mode: Any) -> str:
    raw = str(mode or AUTO_PILOT_UNIVERSE_MODE).strip().lower()
    aliases = {
        "": AUTO_PILOT_UNIVERSE_MODE,
        "default": AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        "safe": AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        "default_safe": AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        "default-safe": AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        "production_safe": AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        "production-safe": AUTO_PILOT_UNIVERSE_MODE_DEFAULT_SAFE,
        "aggressive": AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL,
        "aggressive_full": AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL,
        "aggressive-full": AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL,
        "full": AUTO_PILOT_UNIVERSE_MODE_AGGRESSIVE_FULL,
    }
    return aliases.get(raw, AUTO_PILOT_UNIVERSE_MODE)

# =============================================================================
# Stalled-position / trend-trap overlay
# =============================================================================
STALL_OVERLAY_ENABLED = True
STALL_OVERLAY_MIN_TRADE_AGE_SECONDS = 900
STALL_OVERLAY_MIN_STALL_DURATION_SECONDS = 300
STALL_OVERLAY_REQUIRE_POSITION_CAP = True
STALL_OVERLAY_REQUIRE_TOO_STRONG = True
STALL_OVERLAY_MAX_NO_ACTION_CYCLES = 3
STALL_OVERLAY_TIGHTEN_PROFIT_LOCK_MULT = 0.85
STALL_OVERLAY_TIGHTEN_QUICK_PROFIT_MULT = 0.85
STALL_OVERLAY_PARTIAL_TRIM_ENABLED = True
STALL_OVERLAY_PARTIAL_TRIM_CLOSE_PCT = 0.12
STALL_OVERLAY_MAX_DEFENSIVE_UPNL_PCT = -0.012
STALL_OVERLAY_COOLDOWN_SECONDS = 600

# =============================================================================
# Global Risk/TP Controls
# =============================================================================
# Disable UPnL stop-loss checks globally (per-bot flags are ignored if False)
# Set to True as safe production default following validation of fast-loop fixes
ENABLE_UPNL_STOPLOSS = True
# Global unrealized PnL take-profit (USDT). 0 disables this global force-close.
GLOBAL_UNREALIZED_TP_USD = 0.0

# =============================================================================
# Smart Pause Recovery
# =============================================================================
SMART_PAUSE_RECOVERY_ENABLED = True
SMART_PAUSE_MIN_PROFIT_PCT = 0.005
SMART_PAUSE_AUTO_RESUME = True
SMART_PAUSE_CHECK_INTERVAL = 60

# =============================================================================
# Emergency Partial Close
# =============================================================================
EMERGENCY_PARTIAL_CLOSE_ENABLED = True  # Re-enabled with near-liq thresholds
EMERGENCY_PARTIAL_CLOSE_LIQ_PCT = 1.5  # Trigger when liq distance < 1.5%
EMERGENCY_PARTIAL_CLOSE_PCT = 25.0  # Tier 1 close size (% of position)
EMERGENCY_PARTIAL_CLOSE_TIER2_LIQ_PCT = 1.0  # Absolute floor trigger when liq distance < 1.0%
EMERGENCY_PARTIAL_CLOSE_TIER2_PCT = 50.0  # Tier 2 close size (% of position)
EMERGENCY_PARTIAL_CLOSE_COOLDOWN = 900  # Seconds between partial closes (15 min)
EMERGENCY_PARTIAL_CLOSE_MAX_COUNT = 3  # Max partial closes before escalation

# =============================================================================
# Symbol Training System
# =============================================================================
SYMBOL_TRAINING_ENABLED = False  # Disabled in web workers — rebuild owned by runner/offline only
SYMBOL_TRAINING_MIN_TRADES = 50
SYMBOL_TRAINING_FULL_CONFIDENCE_TRADES = 200
SYMBOL_TRAINING_MAX_BLEND = 0.60
SYMBOL_TRAINING_DECAY_FACTOR = 0.95
SYMBOL_TRAINING_ANALYSIS_INTERVAL_SEC = 1800
SYMBOL_TRAINING_STEP_MIN_MULT = 0.80
SYMBOL_TRAINING_STEP_MAX_MULT = 1.25
SYMBOL_TRAINING_OPEN_CAP_MIN_MULT = 0.50
SYMBOL_TRAINING_OPEN_CAP_MAX_MULT = 1.10
SYMBOL_TRAINING_OUTLIER_STDDEV = 3.0
SYMBOL_TRAINING_MAX_PROCESSED_IDS = 5000
SYMBOL_TRAINING_MAX_RECENT_OUTCOMES = 2000
