# Walkthrough - Risk Audit and Hardening

I have completed a comprehensive risk audit and hardening of the crypto trading bot. The focus was on stability, churn prevention, and margin safety.

## Changes Made

### 1. Critical Stability Fixes
- **`NameError` Fix**: Resolved `NameError: bot_id` in `services/grid_bot_service_lf.py`'s `_emergency_partial_close`.
- **Hard-Fail Strengthening**: Updated `_hard_fail_close` to ensure bot status is persisted as `error` before termination.

### 2. Churn-Loss Prevention
- **Strengthened Recenter Guards**: Improved "no open positions" checks in `recenter_if_needed`.
- **Trailing Recentering Refinements**: Added 0.5% minimum deviation and toggle respect to `recenter_if_trailing`.

### 3. Unified Auto-Margin Reserve
- **Centralized Helper**: Implemented `_calculate_auto_margin_reserve` across all services.
- **Equity-Aware Handling**: `usable_investment` now respects `available_equity` while preserving `reserve_usd`.
- **Small-Cap Protection**: Integrated `SMALL_CAPITAL_AUTO_MARGIN_CAPS` and config safety clamping.

### 4. Scoped Cancel Logic (LF)
- **Bot-Isolated Cancellation**: Replaced global `cancel_all_orders` with `_cancel_non_reducing_bot_orders` in LF flows.
- **`reduceOnly` Preservation**: Cancellation routines now explicitly skip exit orders, preventing collateral damage to take-profit/stop-loss exits.
- **Rate-Limit Awareness**: Integrated 2s backoff on 10001 errors and a 50-order safety cap.

## Results
- **Robust Exit Path**: `reduceOnly` orders are safe from mass-cancellation events.
- **Deterministic Sizing**: Reserves are correctly calculated and enforced even during drawdowns.
- **Cleaner Config**: Removed duplicate definitions of `EMERGENCY_PARTIAL_CLOSE_LIQ_PCT`.

##- **Verification Results**:
  - **Logic Audit**: Verified logic handles 0 division and safely updates min_trigger_pct.
  - **Compilation**: Passed.

### Phase 9: Scalp PnL Enhancement (Recenter on Close)
- **Feature**: Added "Recenter on Close" to `_run_scalp_pnl_cycle`.
- **Logic**: 
  - If `positions_closed > 0` (TP hit), forces `scalp_grid_center = 0`.
  - Next cycle step immediately re-initializes center to `last_price`.
- **Benefit**: Ensures the grid wraps around the new price immediately after a trade, rather than waiting for >1% drift.
- **Implementation**: Applied to both `grid_bot_service.py` and `grid_bot_service_lf.py`.
Confirmed that `last_price` is correctly fetched and compared in all three critical code paths.

### Phase 8: Auto-Margin Leverage Awareness
- **Problem**: Auto-Margin Guard was triggering immediately on high-leverage positions because the default trigger (15%) was higher than the natural liquidation distance for high leverage (e.g., 9x leverage = ~11% distance).
- **Fix Implemented**:
  - Updated `_auto_margin_guard` in `grid_bot_service.py` and `grid_bot_service_lf.py`.
  - Updated `margin_monitor_service_lf.py` (Standalone Monitor).
  - **Logic**: Dynamically lowers the trigger if leverage is high.
    - Formula: `clean_trigger = max(1.0, (100.0 / leverage) - 2.5)`
    - Example: For 9x leverage (11.1% dist), trigger becomes ~8.6%.
  - **Result**: Prevents false positive margin dumps on normal position entry.
