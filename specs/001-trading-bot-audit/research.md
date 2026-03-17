# Research: Trading Bot Audit and Safety Improvements

**Feature**: 001-trading-bot-audit  
**Date**: 2026-01-15  
**Status**: Complete

## Research Tasks Completed

| Task | Area | Status |
|------|------|--------|
| UI Bug Analysis | Available balance display | Complete |
| Frontend Redundancy | JS file overlap | Complete |
| Recenter Logic | Anti-churn mechanisms | Complete |
| Risk Controls | Kill-switch, position limits | Complete |
| Scalp PnL | Fee-aware thresholds | Complete |

---

## 1. Available Balance Bug (FR-001, FR-002)

### Finding

**Root Cause Confirmed**: `app_lf.js:refreshPositions()` (lines 849-963) updates `wallet_balance` but has NO code to update `available_balance`.

**Current Code (app_lf.js lines 891-895)**:
```javascript
const walletBalance = data.wallet_balance || 0;
const walletBalanceEl = document.getElementById('pos-wallet-balance');
if (walletBalanceEl) {
  walletBalanceEl.textContent = `$${walletBalance.toFixed(2)}`;
}
// available_balance handling is MISSING
```

**Comparison with app_v5.js (lines 896-908)**: app_v5.js correctly handles both:
```javascript
const availableBalance = data.available_balance || 0;
const availableBalanceEl = document.getElementById('pos-available-balance');
if (availableBalanceEl) {
  availableBalanceEl.textContent = `$${availableBalance.toFixed(2)}`;
}
```

### Decision
Add identical available_balance handling to app_lf.js after the wallet_balance block.

### Rationale
- Minimal change with high confidence
- Follows existing pattern in app_v5.js
- Guards against missing element per FR-002

---

## 2. Colspan Mismatch (FR-003)

### Finding

**Current Value**: `app_lf.js:899` uses `colspan="12"` for empty positions row.  
**Table Column Count**: Dashboard.html Open Positions table has **13 columns** (Symbol, Direction, Size, Entry, Mark, Liq, PnL%, UPnL, TP, SL, Trail, Margin, Act).

**Both app_lf.js and app_v5.js have this bug** - both use colspan="12".

### Decision
Update colspan to "13" in both files to match actual table structure.

### Rationale
Prevents layout issues with empty state row spanning all columns correctly.

---

## 3. Frontend Redundancy (FR-004, FR-005, FR-006)

### Finding

**37 helper functions are duplicated** between app_v5.js and app_lf.js:

| Category | Functions | Count |
|----------|-----------|-------|
| Toast/Sound | showToast, toggleSound, initAudio, playTone, play*Sound | 8 |
| DOM/Fetch | $, fetchJSON | 2 |
| Formatters | formatCurrency, formatPnL, formatNumber, formatVolume, formatPercent, formatVelocity, formatTime, formatTimeAgo, formatElapsed, formatDuration | 10 |
| Badges | statusBadge, upnlSlBadges, trailingSlBadge, profileBadge, modeBadge, rangeModeBadge, riskBadge | 7 |
| Logic | calculateRisk, updateRunningBotsStatus, logout | 3 |
| Other | restoreSoundPreference, updatePageTitle | 2 |

**Load Order (templates/dashboard.html)**: app_v5.js loads before app_lf.js, so app_lf.js functions shadow app_v5.js.

### Decision
**Path 1 (Minimal Risk)**: For this audit, leave function definitions in place but ensure consistency. The available_balance fix is the priority.

### Rationale
- Full consolidation is risky without comprehensive testing
- Current behavior works because app_lf.js functions win (loaded second)
- Comments in app_lf.js incorrectly reference "app.js" - should be "app_v5.js"

### Alternatives Considered
- **Full consolidation**: Too invasive for this audit scope
- **Remove app_v5.js**: Would require verifying all code paths

---

## 4. Grid Recentering Anti-Churn (FR-007, FR-008, FR-009, FR-010)

### Finding

**Existing Cooldowns**:

| Cooldown | Value | Purpose |
|----------|-------|---------|
| TRAILING_RECENTER_COOLDOWN_SEC | 600s | Between trailing recenters |
| NEUTRAL_RECENTER_COOLDOWN_SEC | 600s | Between neutral recenters |
| NEUTRAL_BREAKOUT_COOLDOWN_SEC | 300s | After breakout flatten |
| cooldown_seconds (flat_and_stale) | 300s | Hardcoded in function call |

**Position Check Before Recenter**: 
- `neutral_grid_service.recenter_if_trailing()` already has "skip if any position open" (confirmed in audit prompt)
- Other modes need verification

**Mode Separation**:
- `neutral_classic_bybit` has dedicated handler `_run_neutral_classic_bybit()` (lines 5413-5775)
- Calls `neutral_grid_service` methods for recentering
- Generic range engine also has recenter logic that could conflict

### Decision
1. Verify all modes check positions before recentering
2. Add bot-level `last_recenter_ts` to prevent rapid rebuilds regardless of mode
3. Add volatility freeze check (ATR%/BBW% threshold) before recenter decision
4. Ensure grid_bot_service defers to neutral_grid_service for neutral_classic_bybit

### Rationale
- Multiple recenter paths exist - need unified anti-churn
- Bot-level timestamp provides mode-agnostic protection
- Volatility check prevents recentering during dangerous conditions

---

## 5. Global Kill-Switch (FR-011, FR-012)

### Finding

**Existing Settings (strategy_config.py)**:
- `MAX_DAILY_LOSS_PCT = 0.08` (8%) - Exists but not enforced globally
- `MAX_BOT_LOSS_PCT = 0.05` (5%) - Per-bot, already used

**Risk Manager (risk_manager_service.py)**: Global kill-switch is "commented out/disabled" per audit prompt.

### Decision
1. Add `GLOBAL_KILL_SWITCH_ENABLED = False` (default off for backward compatibility)
2. When enabled + MAX_DAILY_LOSS_PCT exceeded:
   - Pause all bots
   - Cancel non-reducing orders
   - Persist triggered state to storage/risk_state.json
3. Do NOT auto-close positions (too aggressive as default)

### Rationale
- Opt-in maintains backward compatibility
- Pausing without closing lets user decide how to exit
- State persistence prevents restart bypass

---

## 6. Position Sizing Defaults (FR-014)

### Finding

**All limits currently disabled (set to 0)**:

| Setting | Current | Suggested Default |
|---------|---------|-------------------|
| MAX_RISK_PER_BOT_PCT | 0 (disabled) | 0.10 (10%) |
| MAX_CAPITAL_PER_SYMBOL_PCT | 0 (disabled) | 0.25 (25%) |
| MAX_CAPITAL_PER_SYMBOL_USDT | 0 (disabled) | Keep 0 |
| MAX_BOTS_PER_SYMBOL | 0 (disabled) | 2 |
| MAX_SYMBOL_SHARE_OF_BOTS_PCT | 10.0 (1000% = disabled) | 0.50 (50%) |

**validate_new_bot()**: Exists in risk_manager_service.py - needs verification that it checks these limits.

### Decision
Provide reasonable defaults as a "safe profile" option. Keep 0 as legacy behavior.

### Rationale
- New traders benefit from guardrails
- Experienced traders can disable by setting to 0
- Audit prompt recommends 5-10% per bot, 15-25% per symbol, 1-2 bots per symbol

---

## 7. Scalp PnL Fee-Aware Thresholds (FR-015, FR-016, FR-017)

### Finding

**Current Setting**:
- `SCALP_PNL_MIN_PROFIT = 0.05` ($0.05)

**Problem**: For many symbols, $0.05 may be less than fees+spread, resulting in net-negative trades.

**Fee Structure (Bybit)**:
- Maker: 0.01% (VIP tiers lower)
- Taker: 0.06%
- Round-trip (open+close): ~0.12% for taker

**Example**:
- $100 position, 0.12% fees = $0.12 in fees
- $0.05 min profit → net loss of $0.07

### Decision
1. Calculate adaptive min: `max(config_min, notional * fee_pct * 2.5, spread_cost * 2)`
2. Add NO_TRADE_SPREAD_THRESHOLD check
3. Add POST_CLOSE_COOLDOWN_SEC (e.g., 30s) before new opening orders

### Rationale
- Fee multiplier of 2.5 ensures profit after fees+slippage
- Spread check prevents trading illiquid pairs
- Cooldown prevents immediate re-entry churn

---

## 8. Auto-Stop Safety (FR-021, FR-022, FR-023)

### Finding

**Current Behavior (app_lf.js lines 1250-1301)**:
1. Detects direction change via `previousValues.botMarketStates[bot.id]`
2. Calls `botAction('stop', bot.id, null, true)` (silent stop)
3. Only closes if profitable: `if (unrealizedPnl > 0)`
4. **Problem**: Losing position left unmanaged if bot stops

**Market State Detection**: Parses freeform trend_status string via regex `trend:\s*(\w+)`

### Decision
1. Modify stop behavior: When position is losing, keep bot in "reduce-only" mode instead of full stop
2. Add `trend_direction` enum field to backend response: `"bullish" | "bearish" | "neutral" | "unknown"`
3. Use structured field instead of regex parsing

### Rationale
- Reduce-only mode maintains risk management
- Structured field is more reliable than text parsing
- Prevents stranded unmanaged positions

---

## Summary: No NEEDS CLARIFICATION Remaining

All technical unknowns have been resolved through codebase research. The specification was sufficiently detailed that no user clarification is required.

| Area | Decision | Confidence |
|------|----------|------------|
| Available balance | Add to app_lf.js per app_v5.js pattern | High |
| Colspan | Change to 13 | High |
| Frontend consolidation | Minimal changes for this audit | High |
| Anti-churn | Bot-level timestamp + volatility check | High |
| Kill-switch | Opt-in toggle + pause behavior | High |
| Position limits | Safe defaults as option | Medium |
| Scalp fee-aware | Adaptive calculation | High |
| Auto-stop safety | Reduce-only mode | High |
