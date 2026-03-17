# Implementation Batch 2: Critical Safety Features

**Date**: 2025-12-04
**Status**: ✅ COMPLETED

---

## Overview

Batch 2 implements the **TOP PRIORITY** critical safety features from mytrading parity analysis:

1. **Feature #4**: Automatic Adaptive Stop-Loss (FULLY AUTOMATIC, volatility-based)
2. **Feature #5**: Trend Protection Service (multi-indicator confidence scoring)
3. **Feature #6**: Range Recentering & Profile-Based Range Adjustment

These features provide:
- **100% automatic stop-loss** (no manual per-symbol configuration)
- **Trend-based position protection** (closes positions opposing strong trends)
- **Smart range management** (automatic recentering + profile-based width adjustments)

---

## Feature #4: Automatic Adaptive Stop-Loss

### What It Does

Calculates and sets stop-loss orders automatically based on:
- Volatility (ATR%, BBW%)
- Grid boundaries (lower/upper)
- Risk profile (SAFE/NORMAL/AGGRESSIVE)
- Bot allocation and leverage

**NO manual per-symbol SL configuration required.**

### Implementation Details

**New Files:**
- `services/stop_loss_service.py` (387 lines)

**Modified Files:**
- `config/strategy_config.py`: Added 7 SL configuration parameters
- `app.py`: Initialize and wire StopLossService
- `services/grid_bot_service.py`: Integrated SL calculation + placement in bot cycle

**Key Methods:**
```python
calculate_stop_loss()  # Calculate SL price based on volatility + profile
set_stop_loss()        # Place SL order via Bybit API
should_update_stop_loss()  # Determine if SL needs updating (avoid spam)
```

### Configuration Parameters

**Added to `strategy_config.py`:**

```python
# Feature #4: Automatic Adaptive Stop-Loss Configuration
ENABLE_AUTOMATIC_STOP_LOSS = True   # Enable/disable automatic SL

# Profile-based ATR multipliers for SL distance from grid boundary
SL_SAFE_ATR_MULTIPLIER = 1.5        # SAFE: 1.5x ATR
SL_NORMAL_ATR_MULTIPLIER = 2.0      # NORMAL: 2.0x ATR
SL_AGGRESSIVE_ATR_MULTIPLIER = 2.5  # AGGRESSIVE: 2.5x ATR

# Absolute min/max SL distance from current price (safety clamps)
SL_MIN_DISTANCE_PCT = 0.02          # Minimum 2% SL distance
SL_MAX_DISTANCE_PCT = 0.15          # Maximum 15% SL distance

# SL update threshold (avoid excessive API calls)
SL_UPDATE_THRESHOLD_PCT = 0.02      # Only update SL if it changes by >2%
```

### How It Works

**SL Calculation Strategy:**

1. **For neutral/long modes**: SL placed **below** grid lower boundary
   - Distance = `grid_lower - (ATR × profile_multiplier)`
   - Example: SAFE profile = `lower - (ATR × 1.5)`

2. **For short mode**: SL placed **above** grid upper boundary
   - Distance = `grid_upper + (ATR × profile_multiplier)`

3. **For scalp modes**: Tight SL very close to price
   - Uses 0.5x of normal multiplier
   - Max 1-5% distance from entry

4. **Max loss % backup**: Ensures SL doesn't allow >10-15% loss of bot capital

5. **Clamps**: Final SL distance clamped between 2% and 15% from current price

**Update Logic:**
- Only updates SL if it moves by >2% of price (avoid API spam)
- Logs all SL calculations with reasons

**Integration in Bot Cycle:**
- Runs **after** grid orders placed/cancelled
- Runs **after** trend protection check
- Only runs if position exists
- Gracefully handles API failures

### Testing Checklist

- [ ] Verify SL calculated correctly for SAFE profile (1.5x ATR)
- [ ] Verify SL calculated correctly for NORMAL profile (2.0x ATR)
- [ ] Verify SL calculated correctly for AGGRESSIVE profile (2.5x ATR)
- [ ] Check SL placed below lower bound for neutral/long modes
- [ ] Check SL placed above upper bound for short mode
- [ ] Verify SL respects 2% minimum distance
- [ ] Verify SL respects 15% maximum distance
- [ ] Check SL only updates when change >2%
- [ ] Verify logs show SL price, method, distance %
- [ ] Test with missing ATR/BBW (should fallback gracefully)

---

## Feature #5: Trend Protection Service

### What It Does

Detects strong trends using multi-indicator confirmation and closes positions that oppose the trend direction.

**Strategy:**
- Uses **4 indicators** for trend detection: ADX, +DI/-DI, EMA alignment, RSI
- Calculates **confidence score (0-100)** based on signal strength
- Closes opposite-direction positions when confidence >= threshold (default 60)

### Implementation Details

**New Files:**
- `services/trend_protection_service.py` (335 lines)

**Modified Files:**
- `config/strategy_config.py`: Added 5 trend protection parameters
- `app.py`: Initialize and wire TrendProtectionService
- `services/grid_bot_service.py`: Integrated trend detection + position closure

**Key Methods:**
```python
detect_trend()          # Multi-indicator trend detection with confidence scoring
should_close_position() # Determine if position opposes trend
```

### Configuration Parameters

**Added to `strategy_config.py`:**

```python
# Feature #5: Trend Protection Configuration
ENABLE_TREND_PROTECTION = True      # Enable/disable trend protection

# Trend detection thresholds
TREND_ADX_THRESHOLD = 25.0          # ADX above this = strong trend
TREND_DI_DOMINANCE = 5.0            # +DI/-DI difference for confirmation
TREND_RSI_THRESHOLD = 10.0          # RSI distance from 50 for confirmation

# Confidence scoring
TREND_MIN_CONFIDENCE_SCORE = 60     # Min score (0-100) to close positions
```

### How It Works

**Confidence Scoring System (0-100 points):**

1. **ADX Signal (max 30 points)**:
   - Checks if ADX >= 25 (trend exists)
   - Scale: ADX 25-40+ = 0-30 points
   - **Early return if ADX < 25** (no trend = score 0)

2. **Directional Indicators (max 25 points)**:
   - Checks +DI vs -DI difference
   - If `+DI - (-DI) >= 5.0` → **UPTREND**
   - If `-DI - (+DI) >= 5.0` → **DOWNTREND**
   - Scale: DI diff 5-20+ = 0-25 points

3. **EMA Alignment (max 20 points)**:
   - **Uptrend**: Check if `price > EMA20 > EMA50`
   - **Downtrend**: Check if `price < EMA20 < EMA50`
   - Full alignment = 20 points, partial = 10 points

4. **RSI Momentum (max 25 points)**:
   - **Uptrend**: RSI > 50, distance from 50 >= 10
   - **Downtrend**: RSI < 50, distance from 50 >= 10
   - Scale: RSI distance 10-30+ = 0-25 points

**Position Closure Logic:**
- Long position + downtrend (confidence >= 60) → **CLOSE**
- Short position + uptrend (confidence >= 60) → **CLOSE**
- Position aligned with trend → **HOLD**

**Integration in Bot Cycle:**
- Runs **before** stop-loss logic (more aggressive protection)
- Runs **after** grid management
- Logs trend detection with confidence score and all signals
- Closes position via market order if trend opposes position

### Testing Checklist

- [ ] Verify ADX check blocks detection if ADX < 25
- [ ] Check +DI/-DI determines trend direction correctly
- [ ] Verify EMA alignment scoring (full vs partial)
- [ ] Check RSI momentum scoring
- [ ] Verify confidence score calculated correctly (0-100)
- [ ] Test long position closure on strong downtrend
- [ ] Test short position closure on strong uptrend
- [ ] Check logs show confidence score + all signal values
- [ ] Verify position NOT closed if confidence < 60
- [ ] Test with missing indicators (should handle gracefully)

---

## Feature #6: Range Recentering & Profile-Based Adjustment

### What It Does

Enhances the existing `RangeEngineService` with:
1. **Automatic recentering**: Detects when price approaches range boundaries and recenters grid
2. **Profile-based width adjustments**: Applies SAFE/NORMAL/AGGRESSIVE multipliers to range width

**Strategy:**
- Monitors price position within grid range (0-1, where 0.5 = center)
- Recenters if price reaches 70%+ toward either boundary
- Adjusts range width based on risk profile

### Implementation Details

**Modified Files:**
- `services/range_engine_service.py`: Added 3 new methods (225 lines total)
- `config/strategy_config.py`: Added 4 range recentering parameters

**New Methods:**
```python
should_recenter_range()            # Check if recentering needed
apply_profile_adjustment()         # Apply profile multiplier to width
build_neutral_range_with_profile() # Enhanced range builder (all-in-one)
```

**Existing Method** (unchanged):
```python
build_neutral_range()  # Original volatility-based range builder
```

### Configuration Parameters

**Added to `strategy_config.py`:**

```python
# Feature #6: Range Recentering & Profile Adjustments
RANGE_RECENTER_THRESHOLD_PCT = 0.70  # Recenter when price reaches 70% to boundary

# Profile-based range width multipliers
SAFE_PROFILE_RANGE_MULTIPLIER = 0.80     # SAFE: 20% narrower ranges
NORMAL_PROFILE_RANGE_MULTIPLIER = 1.00   # NORMAL: Default width
AGGRESSIVE_PROFILE_RANGE_MULTIPLIER = 1.30  # AGGRESSIVE: 30% wider ranges
```

### How It Works

**Recentering Logic:**

1. Calculate price position in range: `position = (price - lower) / (upper - lower)`
   - 0.0 = at lower bound
   - 0.5 = perfectly centered
   - 1.0 = at upper bound

2. **Recenter triggers**:
   - Price **breaks below** lower bound → RECENTER
   - Price **breaks above** upper bound → RECENTER
   - Price position < 30% (0.30) → RECENTER (too close to lower)
   - Price position > 70% (0.70) → RECENTER (too close to upper)

3. If no recentering needed, return **existing range** unchanged (stability)

**Profile Adjustment Logic:**

- SAFE profile: `range_width × 0.80` (20% narrower, tighter grid)
- NORMAL profile: `range_width × 1.00` (no adjustment)
- AGGRESSIVE profile: `range_width × 1.30` (30% wider, more room)

**Enhanced Range Builder** (`build_neutral_range_with_profile`):

```python
# Step 1: Check if recentering needed (if existing range provided)
# Step 2: Calculate base range width from volatility (ATR/BBW)
# Step 3: Apply profile-based multiplier
# Step 4: Recalculate bounds around current price
# Returns: { lower, upper, width_pct, recentered, recenter_reason, profile_multiplier }
```

### Integration Notes

**This feature is implemented but NOT YET wired into grid_bot_service.py.**

To use it, replace calls to `range_engine.build_neutral_range()` with:

```python
range_result = self.range_engine.build_neutral_range_with_profile(
    last_price=last_price,
    atr_pct=atr_pct,
    bbw_pct=bbw_pct,
    profile=profile,  # "safe", "normal", or "aggressive"
    existing_lower=bot.get("lower_bound"),  # For recentering check
    existing_upper=bot.get("upper_bound"),
    recenter_threshold_pct=0.70,
)

if range_result.get("recentered"):
    logger.info(f"Grid recentered: {range_result.get('recenter_reason')}")
    lower_bound = range_result["lower"]
    upper_bound = range_result["upper"]
else:
    # Keep existing bounds
    lower_bound = range_result["lower"]
    upper_bound = range_result["upper"]
```

### Testing Checklist

- [ ] Verify recentering triggers when price < 30% position
- [ ] Verify recentering triggers when price > 70% position
- [ ] Verify recentering triggers when price breaks below lower
- [ ] Verify recentering triggers when price breaks above upper
- [ ] Check NO recentering when price 30-70% (comfortable middle)
- [ ] Verify SAFE profile multiplier = 0.80
- [ ] Verify NORMAL profile multiplier = 1.00
- [ ] Verify AGGRESSIVE profile multiplier = 1.30
- [ ] Check combined method returns all expected fields
- [ ] Verify logs show recenter reason when triggered

---

## Summary of Changes

### New Files Created

1. `services/stop_loss_service.py` (387 lines) - Feature #4
2. `services/trend_protection_service.py` (335 lines) - Feature #5

### Files Modified

| File | Lines Changed | Features |
|------|--------------|----------|
| `config/strategy_config.py` | +23 | All 3 features |
| `app.py` | +23 | Import + init services |
| `services/grid_bot_service.py` | +79 | Wire SL + Trend Protection |
| `services/range_engine_service.py` | +230 | Range recentering + profiles |

### Configuration Parameters Added

**Total: 19 new parameters**

- Feature #4 (Stop-Loss): 7 parameters
- Feature #5 (Trend Protection): 5 parameters
- Feature #6 (Range Recentering): 4 parameters
- Feature #6 (Profile Multipliers): 3 parameters

---

## Key Configuration to Review Before Live Trading

### Stop-Loss Settings (Feature #4)

**Conservative (recommended for initial testing)**:
```python
SL_SAFE_ATR_MULTIPLIER = 2.0       # Wider SL for SAFE (instead of 1.5)
SL_NORMAL_ATR_MULTIPLIER = 2.5     # Wider SL for NORMAL (instead of 2.0)
SL_AGGRESSIVE_ATR_MULTIPLIER = 3.0 # Wider SL for AGGRESSIVE (instead of 2.5)
```

**Current defaults** (more aggressive):
```python
SL_SAFE_ATR_MULTIPLIER = 1.5
SL_NORMAL_ATR_MULTIPLIER = 2.0
SL_AGGRESSIVE_ATR_MULTIPLIER = 2.5
```

### Trend Protection Settings (Feature #5)

**Conservative (fewer trend closures)**:
```python
TREND_MIN_CONFIDENCE_SCORE = 75    # Require higher confidence (instead of 60)
```

**Aggressive (more trend closures)**:
```python
TREND_MIN_CONFIDENCE_SCORE = 50    # Lower confidence threshold
```

**Current default**:
```python
TREND_MIN_CONFIDENCE_SCORE = 60    # Balanced (medium confidence)
```

### Range Recentering Settings (Feature #6)

**More stable (less frequent recentering)**:
```python
RANGE_RECENTER_THRESHOLD_PCT = 0.80  # Wait until price reaches 80% (instead of 70%)
```

**More responsive (frequent recentering)**:
```python
RANGE_RECENTER_THRESHOLD_PCT = 0.60  # Recenter at 60% threshold
```

**Current default**:
```python
RANGE_RECENTER_THRESHOLD_PCT = 0.70  # Recenter at 70% (balanced)
```

---

## Next Steps

### For User Testing

1. **Start with conservative settings** (wider SLs, higher confidence threshold)
2. **Test on low-risk symbols** first (e.g., BTCUSDT)
3. **Monitor logs** for:
   - SL calculation reasons and prices
   - Trend protection triggers and confidence scores
   - Range recentering events
4. **Gradually tighten** settings after confirming behavior

### Remaining Batch 2 Features (Not Yet Implemented)

- Feature #7: Grid Mode Variations (buy_heavy, sell_heavy, clustered)
- Feature #8: Smart Take-Profit Service
- Feature #9: Danger Zone Detection
- Feature #10: Out-of-Range Behavior Options
- Feature #11: Volatility Range Filters
- Feature #12: Pattern Gate Triggers

### Integration TODO

**Feature #6 (Range Recentering) needs wiring**:
- Update `grid_bot_service.py` to use `build_neutral_range_with_profile()` instead of `build_neutral_range()`
- Pass `profile` parameter from bot config
- Pass existing bounds for recentering check
- Log recentering events

---

## File Reference

### Stop-Loss Service
- **Service**: `opus_trader/services/stop_loss_service.py`
- **Config**: `opus_trader/config/strategy_config.py` (lines 103-122)
- **Wiring**: `opus_trader/app.py` (lines 120-128), `grid_bot_service.py` (lines 1291-1368)

### Trend Protection Service
- **Service**: `opus_trader/services/trend_protection_service.py`
- **Config**: `opus_trader/config/strategy_config.py` (lines 124-139)
- **Wiring**: `opus_trader/app.py` (lines 130-136), `grid_bot_service.py` (lines 1216-1289)

### Range Recentering
- **Service**: `opus_trader/services/range_engine_service.py` (methods 90-313)
- **Config**: `opus_trader/config/strategy_config.py` (lines 141-153)
- **Wiring**: NOT YET WIRED (TODO in next batch)

---

## Log Examples

### Stop-Loss Logs
```
✅ Bot abc123: Updated SL to $45678.50 (2.15% from price, method=below_grid_lower)
Bot abc123: SL unchanged (current=$45678.50, new=$45690.00)
⚠️ Bot abc123: Failed to set SL: set_trading_stop not implemented
```

### Trend Protection Logs
```
🔍 Bot abc123: Strong downtrend detected (confidence=75/100, signals={'adx': 28, 'di': 20, 'ema': 20, 'rsi': 7})
⚠️ Bot abc123: TREND PROTECTION TRIGGERED - Long position against strong downtrend (confidence=75/100, PnL=$-5.50)
✅ Bot abc123: Closed Buy position due to trend protection (PnL=$-5.50, trend=down, confidence=75)
Bot abc123: Position aligned with uptrend (confidence=65/100)
```

### Range Recentering Logs
```
🔄 Range recentering triggered: Price too close to upper bound (position=82.3%, distance=1.15%)
Range recentering not needed: Price centered (position=55.2% in range)
🔄 Range recentering triggered: Price $50123.00 broke above upper bound $50000.00
```
