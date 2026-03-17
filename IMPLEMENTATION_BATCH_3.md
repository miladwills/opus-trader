# Implementation Batch 3: Advanced Grid & Position Management

**Date**: 2025-12-05
**Status**: ✅ COMPLETE - ALL FEATURES WIRED

---

## Overview

Batch 3 wires the remaining Step 2 features into the bot execution cycle:

1. **Feature #6**: Range Recentering & Profile-Based Adjustment (from Batch 2 - was implemented but not wired)
2. **Feature #7**: Grid Distribution Modes (buy_heavy, sell_heavy, clustered)
3. **Feature #8**: Smart Take-Profit Service (automatic TP calculation)
4. **Feature #9**: Danger Zone Detection (extreme market condition detection)
5. **Feature #10**: Out-of-Range Behavior Options (configurable breakout handling)

All features are **config-driven** and **safe by default**.

---

## Wiring Strategy

### Safety Guarantees

1. **All features OFF by default OR safe defaults**:
   - Range recentering: NORMAL profile (1.0x) = current behavior
   - Grid distribution: "balanced" = current behavior
   - Take-profit: calculated but doesn't interfere with exits
   - Danger zones: only acts at high scores (50+)
   - Out-of-range: "recenter" = similar to current dynamic mode

2. **No changes to existing working features**:
   - Batch 1 (pre-launch validation, BTC correlation, multi-TF ADX) - untouched
   - Batch 2 (auto SL, trend protection) - already wired, untouched

3. **Small, focused diffs**:
   - Each feature wired in isolation
   - Config guards around all new logic
   - Comprehensive logging for decisions

---

## Feature #6: Range Recentering & Profile-Based Adjustment

### Status: ✅ WIRED

### What It Does

Enhances range calculation with:
- Automatic recentering when price approaches boundaries (70% threshold)
- Profile-based width adjustments (SAFE=0.8x, NORMAL=1.0x, AGGRESSIVE=1.3x)

### Implementation

**Service**: Already exists in `range_engine_service.py`
- `build_neutral_range_with_profile()` - Enhanced range builder
- `should_recenter_range()` - Recentering detection
- `apply_profile_adjustment()` - Profile multipliers

**Wiring Location**: `grid_bot_service.py` lines 368-404 (range calculation)

**Changes**:
1. Replace `range_engine.build_neutral_range()` with `build_neutral_range_with_profile()`
2. Pass profile, existing bounds, and recenter threshold
3. Log recentering events

**Config Flags**:
```python
RANGE_RECENTER_THRESHOLD_PCT = 0.70  # Recenter at 70% to boundary
SAFE_PROFILE_RANGE_MULTIPLIER = 0.80
NORMAL_PROFILE_RANGE_MULTIPLIER = 1.00
AGGRESSIVE_PROFILE_RANGE_MULTIPLIER = 1.30
```

---

## Feature #7: Grid Distribution Modes

### Status: ✅ WIRED

### What It Does

Supports different grid order distributions:
- **balanced**: Equal spacing (current behavior)
- **buy_heavy**: More buy orders (60%), fewer sell (40%) - bullish bias
- **sell_heavy**: More sell orders (60%), fewer buy (40%) - bearish bias
- **clustered**: Orders concentrated near price (70% weight)

### Implementation

**Service**: Already exists in `grid_engine_service.py`
- `build_levels_with_distribution()` - Distribution-aware grid builder

**Wiring Location**: `grid_bot_service.py` line 439 (grid level generation)

**Config Flags**:
```python
DEFAULT_GRID_DISTRIBUTION = "balanced"
GRID_BUY_SELL_RATIO = 1.5
GRID_CLUSTER_CONCENTRATION = 0.70
```

---

## Feature #8: Smart Take-Profit Service

### Status: ✅ WIRED

### What It Does

Automatically calculates TP targets based on:
- Volatility (ATR%, BBW%)
- Mode (neutral/directional/scalp)
- Risk profile (SAFE/NORMAL/AGGRESSIVE)

### Implementation

**Service**: Already exists in `take_profit_service.py`
- `calculate_take_profit()` - TP calculation
- `should_take_profit()` - Exit decision logic

**Wiring Location**: After grid placement, before trend protection (~line 1200)

**Config Flags**:
```python
ENABLE_AUTOMATIC_TAKE_PROFIT = True
TP_SAFE_ATR_MULTIPLIER = 1.5
TP_NORMAL_ATR_MULTIPLIER = 2.0
TP_AGGRESSIVE_ATR_MULTIPLIER = 2.5
TP_MIN_DISTANCE_PCT = 0.005
TP_MAX_DISTANCE_PCT = 0.10
```

---

## Feature #9: Danger Zone Detection

### Status: ✅ WIRED

### What It Does

Detects extreme market conditions with severity scoring:
- **Zone 1**: Extreme RSI (overbought >80, oversold <20) - max 30 pts
- **Zone 2**: Extreme volatility (BBW >8%, ATR >6%) - max 25 pts
- **Zone 3**: Volume spikes (>5x average) - max 20 pts
- **Zone 4**: Price at range extremes (>95%) - 15 pts

**Actions** based on danger score:
- Score 70+: HALT trading
- Score 50-69: Pause entries, close positions
- Score 30-49: Reduce size, tighten SL
- Score 10-29: Caution

### Implementation

**Service**: Already exists in `danger_zone_service.py`
- `detect_danger_zones()` - Multi-factor danger detection
- `should_pause_trading()` - Action recommendation

**Wiring Location**: After indicator fetch, before regime filter (~line 172)

**Config Flags**:
```python
ENABLE_DANGER_ZONE_DETECTION = True
DANGER_PAUSE_THRESHOLD_SCORE = 50
DANGER_RSI_OVERBOUGHT = 80.0
DANGER_RSI_OVERSOLD = 20.0
DANGER_BBW_EXTREME_PCT = 0.08
DANGER_ATR_EXTREME_PCT = 0.06
DANGER_VOLUME_SPIKE_MULTIPLIER = 5.0
DANGER_RANGE_EXTREME_PCT = 0.95
```

---

## Feature #10: Out-of-Range Behavior Options

### Status: ✅ WIRED

### What It Does

Configurable handling when price breaks grid range:
- **"recenter"**: Auto-recenter grid (default, similar to dynamic mode)
- **"pause"**: Pause bot, cancel orders
- **"close"**: Close positions + pause (if enabled)
- **"ignore"**: Log only

Includes 60-second wait period to filter false breakouts.

### Implementation

**Enhancement**: Existing out-of-range logic at lines 413-424

**Changes**:
1. Add timestamp tracking for out-of-range events
2. Implement wait period logic
3. Implement action dispatch based on config

**Config Flags**:
```python
OUT_OF_RANGE_ACTION = "recenter"
OUT_OF_RANGE_WAIT_SEC = 60
OUT_OF_RANGE_CLOSE_POSITIONS = False
```

---

## Wiring Progress

- [x] Feature #6: Range Recentering - ✅ WIRED (lines 432-457)
- [x] Feature #7: Grid Distribution - ✅ WIRED (lines 540-575)
- [x] Feature #8: Smart Take-Profit - ✅ WIRED (lines 1427-1530)
- [x] Feature #9: Danger Zone Detection - ✅ WIRED (lines 173-227)
- [x] Feature #10: Out-of-Range Behavior - ✅ WIRED (lines 517-629)

---

## Testing Checklist

### Feature #6 (Range Recentering)
- [ ] NORMAL profile maintains current behavior (1.0x multiplier)
- [ ] SAFE profile narrows ranges (0.8x multiplier)
- [ ] AGGRESSIVE profile widens ranges (1.3x multiplier)
- [ ] Recentering triggers at 70% threshold
- [ ] Logs show recenter reason when triggered
- [ ] No recentering when price in middle 30-70%

### Feature #7 (Grid Distribution)
- [ ] "balanced" mode = current grid behavior
- [ ] "buy_heavy" creates 60/40 buy/sell ratio
- [ ] "sell_heavy" creates 40/60 buy/sell ratio
- [ ] "clustered" concentrates orders near price
- [ ] Logs show distribution stats

### Feature #8 (Smart Take-Profit)
- [ ] TP calculated based on profile + ATR
- [ ] Scalp mode uses tighter TP (0.5x)
- [ ] Neutral mode respects grid width
- [ ] Directional mode more aggressive (1.2x)
- [ ] TP respects min/max distance
- [ ] Logs show TP calculation details

### Feature #9 (Danger Zones)
- [ ] Detects extreme RSI (>80, <20)
- [ ] Detects extreme volatility (BBW >8%, ATR >6%)
- [ ] Detects volume spikes (>5x avg)
- [ ] Detects range extremes (>95%)
- [ ] Pauses at score >= 50
- [ ] Logs danger level + warnings

### Feature #10 (Out-of-Range)
- [ ] "recenter" action recenters grid
- [ ] "pause" action pauses bot
- [ ] "close" action closes positions (if enabled)
- [ ] "ignore" action logs only
- [ ] 60s wait period prevents false breakouts
- [ ] Logs out-of-range events with action taken

---

## Configuration Summary

**Total new config parameters used**: 21

All parameters have safe defaults that maintain current behavior or are conservative.

---

## File Changes

### Modified Files
1. ✅ `app.py` - Initialized TakeProfitService and DangerZoneService (lines 35-43, 55-56, 150-181)
2. ✅ `grid_bot_service.py` - Wired all 5 features into bot cycle:
   - Feature #6: Range Recentering (lines 432-457)
   - Feature #7: Grid Distribution (lines 540-575)
   - Feature #9: Danger Zone Detection (lines 173-227)
   - Feature #8: Smart Take-Profit (lines 1427-1530)
   - Feature #10: Out-of-Range Behavior (lines 517-629)
3. ✅ `IMPLEMENTATION_BATCH_3.md` - Updated progress tracking
4. ⏳ `STEP2_PROGRESS.md` - Pending: Mark features as WIRED

### No Changes To
- ✅ Batch 1 features (pre-launch validation, BTC correlation, multi-TF ADX) - untouched
- ✅ Batch 2 wired features (auto SL, trend protection) - untouched
- ✅ Core trading logic, indicators, or risk formulas - untouched
- ✅ Database schema or storage formats - untouched
