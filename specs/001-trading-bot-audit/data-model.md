# Data Model: Trading Bot Audit and Safety Improvements

**Feature**: 001-trading-bot-audit  
**Date**: 2026-01-15

## Overview

This audit primarily modifies behavior of existing entities rather than creating new ones. The changes below document additions to existing data structures stored in JSON files.

---

## Entity Modifications

### 1. Bot Configuration (storage/bots.json)

**Existing Entity**: Each bot object in the bots array.

**New Fields**:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `last_recenter_ts` | float (Unix timestamp) | 0 | Last successful recenter timestamp for anti-churn |
| `reduce_only_mode` | boolean | false | When true, bot only closes positions, no new entries |
| `auto_stop_paused` | boolean | false | Bot paused by auto-stop, risk management still active |

**Validation Rules**:
- `last_recenter_ts`: Must be non-negative, 0 means never recentered
- `reduce_only_mode`: Only set true when auto-stop triggers with losing position
- `auto_stop_paused`: Mutually exclusive with normal "running" status

**State Transitions**:
```
running → reduce_only_mode (auto-stop with losing position)
running → stopped (auto-stop with profitable position)
reduce_only_mode → stopped (all positions closed)
reduce_only_mode → running (user manually resumes)
```

---

### 2. Risk State (storage/risk_state.json)

**Existing Entity**: Global risk tracking object.

**New Fields**:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `kill_switch_triggered` | boolean | false | Global kill-switch has fired |
| `kill_switch_triggered_at` | float (Unix timestamp) | null | When kill-switch fired |
| `daily_loss_pct` | float | 0.0 | Current day's loss percentage |
| `last_daily_reset` | string (ISO date) | null | Date of last daily counter reset |

**Validation Rules**:
- `kill_switch_triggered`: Once true, stays true until manually reset
- `daily_loss_pct`: Recalculated each cycle, reset at midnight UTC
- Persists across restarts to prevent bypass

---

### 3. Strategy Configuration (config/strategy_config.py)

**New Constants**:

| Constant | Type | Default | Purpose |
|----------|------|---------|---------|
| `GLOBAL_KILL_SWITCH_ENABLED` | bool | False | Master toggle for global kill-switch |
| `VOLATILITY_FREEZE_ATR_PCT` | float | 0.03 | ATR% threshold to freeze recentering (3%) |
| `VOLATILITY_FREEZE_BBW_PCT` | float | 0.08 | BBW% threshold to freeze recentering (8%) |
| `SCALP_FEE_MULTIPLIER` | float | 2.5 | Multiplier for fee-aware min profit |
| `SCALP_SPREAD_THRESHOLD_PCT` | float | 0.005 | Max spread for scalp trades (0.5%) |
| `SCALP_POST_CLOSE_COOLDOWN_SEC` | int | 30 | Cooldown after closing before new entries |
| `RECENTER_POSITION_BLOCK_ALL_MODES` | bool | True | Block recenter while positions open (all modes) |

**Safe Profile Defaults** (optional preset):

| Constant | Current | Safe Default |
|----------|---------|--------------|
| `MAX_RISK_PER_BOT_PCT` | 0 | 0.10 |
| `MAX_CAPITAL_PER_SYMBOL_PCT` | 0 | 0.25 |
| `MAX_BOTS_PER_SYMBOL` | 0 | 2 |

---

### 4. Bot Runtime Response (API response from /api/bots/runtime)

**New Response Fields**:

| Field | Type | Purpose |
|-------|------|---------|
| `trend_direction` | enum | Structured market direction: "bullish" \| "bearish" \| "neutral" \| "unknown" |
| `reduce_only_mode` | boolean | Whether bot is in reduce-only mode |
| `last_recenter_ts` | float | For debugging/display |

**Replaces**: Parsing `trend_status` freeform text for direction.

---

## No New Entities Required

This audit modifies existing structures rather than creating new database tables or collections. All changes are additive fields to existing JSON objects.

---

## Migration Notes

### Backward Compatibility

1. **Existing bots.json**: Missing new fields default to safe values:
   - `last_recenter_ts` → 0 (allows immediate recenter if needed)
   - `reduce_only_mode` → false
   - `auto_stop_paused` → false

2. **Existing risk_state.json**: Missing fields default to:
   - `kill_switch_triggered` → false
   - Other fields → null/0

3. **strategy_config.py**: New constants have backward-compatible defaults:
   - `GLOBAL_KILL_SWITCH_ENABLED = False` (no behavior change)
   - Existing disabled limits (0) remain valid

### Migration Script

No migration script required - services should handle missing fields with defaults.
