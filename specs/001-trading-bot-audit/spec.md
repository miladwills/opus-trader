# Feature Specification: Trading Bot Audit and Safety Improvements

**Feature Branch**: `001-trading-bot-audit`  
**Created**: 2026-01-15  
**Status**: Draft  
**Input**: User description: "Full audit and implementation of UI fixes, frontend cleanup, and trading bot safety improvements covering: Available balance bug fix, frontend JS consolidation, grid recentering anti-churn, risk controls, scalp PnL profitability, neutral classic improvements, and specific UI/logic fixes"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Accurate Account Balances (Priority: P1)

As a trader viewing the dashboard, I need to see my actual available balance in the Open Positions header so I can make informed decisions about new trades and position sizing.

**Why this priority**: This is a critical UI bug that displays $0.00 for available balance regardless of actual account funds. Traders cannot accurately assess their trading capacity without this information, leading to poor decision-making and potential overexposure.

**Independent Test**: Navigate to the dashboard with a funded account and verify the "Avail" field displays the correct non-zero balance matching the account's actual available USDT.

**Acceptance Scenarios**:

1. **Given** a funded trading account with available USDT, **When** the dashboard loads and polls /api/positions, **Then** the "Avail" field displays the correct dollar amount (not $0.00)
2. **Given** the API returns available_balance in the response, **When** refreshPositions() executes, **Then** the #pos-available-balance element is updated with the formatted value
3. **Given** the available balance element does not exist in the DOM, **When** refreshPositions() attempts to update it, **Then** no errors are thrown (graceful fallback)

---

### User Story 2 - Prevent Excessive Grid Recentering Churn (Priority: P1)

As a trader running grid bots, I need the system to prevent excessive recentering during volatile markets so that my bots don't continuously cancel and recreate orders, wasting fees and missing profitable trades.

**Why this priority**: Recenter loops in volatile markets cause significant fee drain and missed opportunities. This directly impacts profitability and can turn profitable strategies into losing ones.

**Independent Test**: Run a grid bot during high volatility conditions and verify that recentering does not trigger more than once within the configured minimum interval, and that logs show anti-churn protections activating.

**Acceptance Scenarios**:

1. **Given** a grid bot with positions open, **When** price crosses the recenter threshold, **Then** recentering is blocked until positions are closed
2. **Given** a recent recenter occurred within the cooldown period, **When** price crosses the threshold again, **Then** the system waits until cooldown expires before recentering
3. **Given** extreme volatility (ATR% or BBW% above threshold), **When** recenter would normally trigger, **Then** the system pauses recentering and enters defensive mode
4. **Given** a neutral_classic bot, **When** grid_bot_service processes it, **Then** only neutral_grid_service handles recentering (no conflicting logic)

---

### User Story 3 - Safe Auto-Stop on Direction Change (Priority: P1)

As a trader using the auto-stop feature, I need the system to safely handle stopping bots when market direction changes so that losing positions are not left unmanaged and stranded.

**Why this priority**: The current implementation can stop a bot while leaving a losing position unmanaged, which is a significant risk exposure issue. Traders may not realize they have unmanaged losses.

**Independent Test**: Enable auto-stop, trigger a direction change while the bot has a losing position, and verify the system either keeps risk management active or handles the position appropriately.

**Acceptance Scenarios**:

1. **Given** a bot with a losing position and auto-stop enabled, **When** market direction changes, **Then** the bot enters "reduce-only" mode instead of fully stopping
2. **Given** a bot stopped due to direction change with an open position, **When** the position hits configured risk thresholds, **Then** the position is closed automatically
3. **Given** the need to determine market direction, **When** processing bot status, **Then** a structured backend field is used instead of parsing freeform trend_status text

---

### User Story 4 - Reliable Dashboard with Unified Frontend (Priority: P2)

As a trader, I need the dashboard to load and function without console errors so that all sections update correctly and I can trust the displayed information.

**Why this priority**: Multiple overlapping JS files create maintenance burden and potential for subtle bugs. While not immediately dangerous, it undermines user confidence and complicates future improvements.

**Independent Test**: Load the dashboard, open browser developer console, verify no JavaScript errors appear, and confirm all sections (Summary, Positions, Bots, Scanner, Predictions, PnL) update correctly.

**Acceptance Scenarios**:

1. **Given** the dashboard loads, **When** JavaScript executes, **Then** no console errors appear
2. **Given** base helpers defined in app_v5.js, **When** app_lf.js loads, **Then** it uses the existing globals instead of redefining them
3. **Given** the Open Positions table has 13 columns, **When** no positions exist, **Then** the empty row uses colspan="13"

---

### User Story 5 - Configurable Global Risk Kill-Switch (Priority: P2)

As a risk-conscious trader, I need a configurable global kill-switch so that if my daily losses exceed a threshold, all trading activity pauses automatically to prevent further losses.

**Why this priority**: Large unexpected losses can devastate an account. Having an optional but easy-to-enable global stop provides a safety net for risk-averse traders.

**Independent Test**: Enable the kill-switch in configuration, simulate losses exceeding the threshold, verify all bots pause and non-reducing orders are canceled.

**Acceptance Scenarios**:

1. **Given** the kill-switch is enabled and MAX_DAILY_LOSS_PCT is configured, **When** daily drawdown exceeds the threshold, **Then** all bots are paused
2. **Given** the kill-switch triggers, **When** non-reducing orders exist, **Then** those orders are canceled
3. **Given** the kill-switch is disabled (default), **When** losses exceed any threshold, **Then** no automatic intervention occurs

---

### User Story 6 - Fee-Aware Scalp Minimum Profit (Priority: P2)

As a trader running scalp_pnl mode, I need the minimum profit threshold to account for fees and spreads so that trades are only taken when genuinely profitable after costs.

**Why this priority**: A fixed $0.05 minimum profit may be eaten entirely by fees and slippage on many symbols, making apparently profitable trades actually losing. This directly impacts strategy profitability.

**Independent Test**: Configure a scalp bot, verify that minimum profit calculations include estimated fees and spread costs, and confirm trades are only opened when expected profit exceeds the adaptive threshold.

**Acceptance Scenarios**:

1. **Given** a scalp bot analyzing a trade opportunity, **When** calculating minimum required profit, **Then** the system uses max(config_min, fee_cost * multiplier, spread_cost * multiplier)
2. **Given** spread is too wide or market is illiquid, **When** evaluating trade opportunities, **Then** the bot enters "no trade" state
3. **Given** a position just closed, **When** the bot would place new opening orders, **Then** it waits for a cooldown period first

---

### User Story 7 - Safer Out-of-Range Behavior (Priority: P2)

As a trader running grid bots in volatile markets, I need out-of-range situations to be handled intelligently based on market conditions so that recentering doesn't occur during dangerous volatility spikes.

**Why this priority**: Recentering during extreme volatility can lock in losses and place new orders in unfavorable conditions. Smarter out-of-range handling protects capital.

**Independent Test**: Configure a grid bot, trigger an out-of-range condition during high volatility, verify the bot pauses instead of recentering.

**Acceptance Scenarios**:

1. **Given** price moves out of range AND volatility is extreme (high ATR% or spread), **When** determining out-of-range action, **Then** the system chooses "pause" instead of "recenter"
2. **Given** regime indicates "too_strong" trend, **When** out-of-range is detected, **Then** defensive behavior is activated

---

### User Story 8 - Consistent UPnL Stop-Loss Across Modes (Priority: P3)

As a trader running any bot mode, I need unrealized PnL stop-loss and trailing stop-loss to work consistently so that I can trust risk management regardless of which mode I'm using.

**Why this priority**: Inconsistent stop-loss behavior across modes creates confusion and potential for unexpected losses. Traders need predictable risk management.

**Independent Test**: Run bots in each mode (neutral_classic, scalp_pnl, dynamic, trailing), configure UPnL SL, verify the stop-loss triggers correctly in each mode.

**Acceptance Scenarios**:

1. **Given** any bot mode with UPnL SL configured, **When** unrealized loss exceeds threshold, **Then** the stop-loss executes
2. **Given** the dashboard displays UPnL SL badges, **When** viewing bot status, **Then** correct SL information is shown for all modes

---

### User Story 9 - Enforced Neutral Classic Loss Prevention (Priority: P3)

As a trader running neutral_classic bots, I need breakout guards and momentum filters to actually block order placement when triggered so that I'm protected from breakout losses and inventory accumulation.

**Why this priority**: If loss prevention checks don't enforce their decisions, they provide false security. Traders may be exposed to risks they believe are mitigated.

**Independent Test**: Configure a neutral_classic bot, trigger conditions that should activate loss prevention (strong momentum, breakout), verify new orders are actually blocked.

**Acceptance Scenarios**:

1. **Given** neutral_loss_prevention_service blocks opening orders, **When** grid_bot_service processes neutral_classic, **Then** order placement is actually prevented
2. **Given** ADX exceeds threshold with one-sided trend, **When** momentum filter activates, **Then** inventory cap is tightened and new entries may be paused
3. **Given** a breakout is detected, **When** breakout guard activates, **Then** appropriate candle timeframe is used for confirmation

---

### User Story 10 - Reasonable Default Position Limits (Priority: P3)

As a new trader setting up bots, I need sensible default position sizing and exposure limits so that I don't accidentally over-concentrate risk in any single symbol or bot.

**Why this priority**: Disabled or unlimited exposure settings can lead to catastrophic losses for inexperienced traders. Reasonable defaults provide a safety baseline.

**Independent Test**: Create a new bot without modifying exposure limits, verify default caps are applied at bot creation time.

**Acceptance Scenarios**:

1. **Given** default configuration, **When** creating a new bot, **Then** MAX_RISK_PER_BOT_PCT, MAX_CAPITAL_PER_SYMBOL_PCT, and MAX_BOTS_PER_SYMBOL have reasonable non-zero defaults
2. **Given** exposure limits are configured, **When** validate_new_bot() runs, **Then** the limits are enforced

---

### Edge Cases

- What happens when the available_balance element doesn't exist in the DOM?
  - System gracefully skips update without throwing errors
- How does the system handle multiple recenters triggered in rapid succession?
  - Cooldown timer prevents additional recenters until expiry
- What happens when a bot is stopped while having both a winning and losing position on the same symbol?
  - Risk management continues for all open positions
- How does the system behave when API returns null or undefined for available_balance?
  - System defaults to 0 and displays "$0.00" without errors
- What happens when volatility transitions from extreme to normal during out-of-range?
  - System re-evaluates and may proceed with normal recenter action

## Requirements *(mandatory)*

### Functional Requirements

#### UI Bug Fixes (Section A, G)

- **FR-001**: System MUST update the #pos-available-balance element when refreshPositions() receives available_balance from /api/positions
- **FR-002**: System MUST guard against missing DOM elements when updating available balance (no-op if element absent)
- **FR-003**: System MUST use colspan="13" for empty position rows to match the 13-column table structure

#### Frontend Consolidation (Section B)

- **FR-004**: app_lf.js MUST NOT redefine helpers that already exist in app_v5.js ($, fetchJSON, shared formatters, shared state objects)
- **FR-005**: app_lf.js MUST use globals from app_v5.js (API_BASE, previousValues, etc.)
- **FR-006**: Comments in app_lf.js MUST accurately reference app_v5.js as the base file (not app.js)

#### Grid Recentering Safety (Section C)

- **FR-007**: System MUST enforce a minimum time between range rebuilds at the bot level regardless of how many times the threshold is crossed
- **FR-008**: System MUST prevent recentering while positions are open for all modes (dynamic, trailing, scalp)
- **FR-009**: System MUST disable recentering when ATR% or BBW% exceed configured volatility thresholds
- **FR-010**: neutral_classic mode MUST use only neutral_grid_service for recentering, with grid_bot_service deferring to it

#### Risk Controls (Section D)

- **FR-011**: System MUST provide a configurable global kill-switch toggle in strategy_config.py
- **FR-012**: When kill-switch is enabled and MAX_DAILY_LOSS_PCT is exceeded, system MUST pause all bots and cancel non-reducing orders
- **FR-013**: System MUST enforce UPnL stop-loss consistently across neutral_classic_bybit, scalp_pnl, dynamic, and trailing modes
- **FR-014**: System MUST apply position sizing limits (MAX_RISK_PER_BOT_PCT, MAX_CAPITAL_PER_SYMBOL_PCT, MAX_BOTS_PER_SYMBOL) at bot creation via validate_new_bot()

#### Scalp PnL Improvements (Section E)

- **FR-015**: System MUST calculate adaptive minimum profit as max(config_min, estimated_fee_cost * multiplier, spread_cost * multiplier)
- **FR-016**: System MUST enter "no trade" state when spread is too wide, market is illiquid, or regime is too strong for scalp logic
- **FR-017**: System MUST enforce a cooldown period after closing a position before placing new opening orders

#### Neutral Classic Improvements (Section F)

- **FR-018**: System MUST enforce NLP (neutral loss prevention) decisions when processing neutral_classic_bybit bots - if NLP blocks opening orders, orders MUST NOT be placed
- **FR-019**: System MUST tighten inventory cap when ADX exceeds threshold with one-sided trend
- **FR-020**: System MUST use correct candle timeframe for breakout confirmation logic

#### Auto-Stop Safety (Section G2)

- **FR-021**: Auto-stop on direction change MUST be opt-in via dashboard checkbox
- **FR-022**: When auto-stop triggers with a losing position, system MUST either: keep bot running in reduce-only mode, OR close if risk thresholds hit, OR pause bot but maintain risk management
- **FR-023**: System MUST expose a structured trend_direction field from backend instead of parsing trend_status text

### Key Entities

- **Bot Configuration**: Trading bot instance with mode, symbol, range parameters, and risk settings
- **Position**: Open trading position with entry price, size, direction, and unrealized PnL
- **Risk State**: Current risk metrics including daily drawdown, exposure per symbol, and volatility indicators
- **Recenter State**: Tracking data for recentering including last recenter timestamp, cooldown status, and volatility freeze state

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Available balance displays correctly within 2 seconds of dashboard load for 100% of page loads when account has funds
- **SC-002**: Grid recentering occurs no more than once per configured cooldown period (minimum 60 seconds) during continuous threshold crossings
- **SC-003**: Zero unmanaged positions exist after auto-stop triggers on direction change
- **SC-004**: Dashboard loads with zero JavaScript console errors in all supported browsers
- **SC-005**: When daily losses exceed configured threshold with kill-switch enabled, all trading activity halts within 10 seconds
- **SC-006**: Scalp trades only execute when expected profit exceeds calculated costs (fees + spread) by configured multiplier
- **SC-007**: During extreme volatility (ATR% or spread above threshold), out-of-range situations result in pause action 100% of the time
- **SC-008**: UPnL stop-loss triggers correctly in all four bot modes (neutral_classic, scalp_pnl, dynamic, trailing)
- **SC-009**: When NLP blocks opening orders, no new orders are placed for that bot during that cycle
- **SC-010**: New bot creation fails validation when exposure limits would be exceeded

## Assumptions

1. The existing /api/positions endpoint reliably returns numeric available_balance
2. app_v5.js loads before app_lf.js in the script order
3. ATR% and BBW% volatility indicators are already calculated and available in the bot processing context
4. Fee rates are known or can be estimated based on exchange tier
5. The dashboard checkbox for auto-stop already exists and its state is accessible
6. Neutral loss prevention service checks are already invoked but may not be enforced
7. The runner.py process can be restarted to apply configuration changes

## Out of Scope

- Creating automated test suites (manual verification per repo guidelines)
- Changing the fundamental architecture of the trading bot system
- Adding new trading modes or strategies
- Modifying exchange API integrations
- Changes to authentication or security model
- Mobile responsive design improvements
- Historical data analysis or backtesting features
