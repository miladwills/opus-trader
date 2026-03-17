# Quickstart: Trading Bot Audit Implementation

**Feature**: 001-trading-bot-audit  
**Branch**: `001-trading-bot-audit`

## Prerequisites

- Python 3.8+ with Flask development environment
- Access to the trading bot codebase
- Funded Bybit account (for verification)

## Implementation Order

Complete tasks in this order to minimize risk and enable incremental testing:

### Phase 1: UI Bug Fixes (P1 - Critical)

**Priority**: Do first - immediate user-visible fix

1. **Fix Available Balance Display** (FR-001, FR-002)
   - File: `static/js/app_lf.js`
   - Location: After line 895 in `refreshPositions()`
   - Add available_balance handling identical to app_v5.js pattern

2. **Fix Colspan Mismatch** (FR-003)
   - File: `static/js/app_lf.js`
   - Location: Line 899
   - Change `colspan="12"` to `colspan="13"`

3. **Bump Cache-Buster**
   - File: `templates/dashboard.html`
   - Update version query param on JS includes

**Verification**: Load dashboard, confirm "Avail" shows correct balance, no layout issues.

---

### Phase 2: Frontend Cleanup (P2)

**Priority**: After Phase 1 verification passes

1. **Update Comments** (FR-006)
   - File: `static/js/app_lf.js`
   - Replace references to "app.js" with "app_v5.js"

**Note**: Full consolidation (FR-004, FR-005) deferred - high risk, low immediate value.

**Verification**: No console errors, all dashboard sections update.

---

### Phase 3: Anti-Churn Recentering (P1 - Critical)

**Priority**: After Phase 2 - core trading safety

1. **Add Recenter Timestamp to Bot State** (FR-007)
   - File: `services/grid_bot_service.py`
   - Add `last_recenter_ts` field to bot dict after recentering

2. **Enforce Cooldown Check** (FR-007)
   - Before any recenter, check: `time.time() - bot.get('last_recenter_ts', 0) > MIN_RECENTER_INTERVAL`

3. **Verify Position Check for All Modes** (FR-008)
   - Files: `grid_bot_service.py`, `neutral_grid_service.py`
   - Ensure dynamic/trailing/scalp modes skip recenter when positions open

4. **Add Volatility Freeze** (FR-009)
   - File: `services/grid_bot_service.py`
   - Add check: if ATR% > threshold OR BBW% > threshold, skip recenter

5. **Ensure Mode Separation** (FR-010)
   - Verify `neutral_classic_bybit` only uses `neutral_grid_service` for recentering

**Verification**: Monitor logs during volatile period, confirm no recenter spam.

---

### Phase 4: Auto-Stop Safety (P1 - Critical)

**Priority**: After Phase 3

1. **Add Reduce-Only Mode** (FR-022)
   - File: `static/js/app_lf.js`
   - Modify auto-stop logic to set `reduce_only_mode` instead of full stop when position losing

2. **Add Trend Direction Field** (FR-023)
   - File: `app.py` - `/api/bots/runtime` endpoint
   - Add `trend_direction` enum field to response

3. **Use Structured Field** (FR-023)
   - File: `static/js/app_lf.js`
   - Replace regex parsing with `bot.trend_direction` field

**Verification**: Trigger direction change with losing position, confirm bot enters reduce-only mode.

---

### Phase 5: Risk Controls (P2)

**Priority**: After core safety fixes

1. **Add Kill-Switch Toggle** (FR-011)
   - File: `config/strategy_config.py`
   - Add: `GLOBAL_KILL_SWITCH_ENABLED = False`

2. **Implement Kill-Switch Logic** (FR-012)
   - File: `services/risk_manager_service.py`
   - Check daily drawdown against `MAX_DAILY_LOSS_PCT`
   - If exceeded and enabled: pause all bots, cancel non-reducing orders

3. **Update Position Limit Defaults** (FR-014)
   - File: `config/strategy_config.py`
   - Set reasonable non-zero defaults (commented safe profile)

4. **Verify validate_new_bot()** (FR-014)
   - File: `services/risk_manager_service.py`
   - Ensure limits are checked at bot creation

**Verification**: Enable kill-switch, simulate loss, confirm all bots pause.

---

### Phase 6: Scalp PnL Improvements (P2)

**Priority**: After Phase 5

1. **Add Fee-Aware Calculation** (FR-015)
   - File: `services/scalp_pnl_service.py`
   - Calculate: `max(config_min, notional * fee_pct * 2.5, spread * 2)`

2. **Add No-Trade State** (FR-016)
   - File: `services/scalp_pnl_service.py`
   - Return no-trade when spread too wide or illiquid

3. **Add Post-Close Cooldown** (FR-017)
   - File: `services/scalp_pnl_service.py`
   - Track last close timestamp, enforce cooldown before new entries

**Verification**: Check logs for fee-aware profit calculations.

---

### Phase 7: Neutral Classic Improvements (P3)

**Priority**: After Phase 6

1. **Enforce NLP Decisions** (FR-018)
   - File: `services/grid_bot_service.py`
   - Verify NLP block result prevents order placement

2. **Tighten Inventory Cap** (FR-019)
   - File: `services/neutral_loss_prevention_service.py`
   - Reduce cap when ADX indicates strong trend

3. **Verify Candle Timeframe** (FR-020)
   - File: `services/neutral_loss_prevention_service.py`
   - Confirm breakout guard uses correct timeframe

**Verification**: Trigger breakout conditions, confirm orders blocked.

---

### Phase 8: Consistent UPnL Stop-Loss (P3)

**Priority**: After Phase 7

1. **Audit All Modes** (FR-013)
   - Files: `grid_bot_service.py`, `stop_loss_service.py`
   - Verify UPnL SL triggers in neutral_classic, scalp_pnl, dynamic, trailing

2. **Verify Badge Display** (FR-013)
   - File: `static/js/app_lf.js`
   - Confirm upnlSlBadges() shows correct info for all modes

**Verification**: Configure UPnL SL, verify triggers in each mode.

---

## Post-Implementation Checklist

From AGENTS.md verification requirements:

- [ ] `/api/positions` returns `wallet_balance` and `available_balance` (numeric)
- [ ] Dashboard "Avail" field updates (not stuck at $0.00)
- [ ] No console errors in browser
- [ ] No column shifting in tables
- [ ] Run at least one bot in each mode
- [ ] Observe logs for recenter behavior
- [ ] Restart app.py and runner.py after all changes

## Restart Commands

After any changes:
```bash
# Windows
start.bat

# Or manually:
python app.py    # Terminal 1
python runner.py # Terminal 2
```
