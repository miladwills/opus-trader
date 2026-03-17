# Tasks: Trading Bot Audit and Safety Improvements

**Input**: Design documents from `/specs/001-trading-bot-audit/`
**Prerequisites**: plan.md (complete), spec.md (10 user stories), research.md (decisions), data-model.md (entities), contracts/api-changes.md

**Tests**: Per AGENTS.md, no formal automated test suite. Manual verification per checklists.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `services/`, `config/`, `app.py` at repository root
- **Frontend**: `static/js/`, `templates/` at repository root
- **Storage**: `storage/` (JSON files)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Preparation and verification of current state before any changes

- [x] T001 Backup current working files to temp directory (storage/bots.json, config/strategy_config.py, static/js/app_lf.js)
- [x] T002 [P] Verify app.py and runner.py are stopped before making changes
- [x] T003 [P] Review current dashboard.html cache-buster version for post-change increment

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Configuration constants and data model fields needed by multiple user stories

**⚠️ CRITICAL**: These changes enable all user story implementations

- [x] T004 Add GLOBAL_KILL_SWITCH_ENABLED constant to config/strategy_config.py (default False)
- [x] T005 [P] Add VOLATILITY_FREEZE_ATR_PCT constant (0.03) to config/strategy_config.py
- [x] T006 [P] Add VOLATILITY_FREEZE_BBW_PCT constant (0.08) to config/strategy_config.py
- [x] T007 [P] Add SCALP_FEE_MULTIPLIER constant (2.5) to config/strategy_config.py
- [x] T008 [P] Add SCALP_SPREAD_THRESHOLD_PCT constant (0.005) to config/strategy_config.py
- [x] T009 [P] Add SCALP_POST_CLOSE_COOLDOWN_SEC constant (30) to config/strategy_config.py
- [x] T010 [P] Add RECENTER_POSITION_BLOCK_ALL_MODES constant (True) to config/strategy_config.py
- [x] T011 [P] Update MAX_RISK_PER_BOT_PCT default comment with safe profile value (0.10) in config/strategy_config.py
- [x] T012 [P] Update MAX_CAPITAL_PER_SYMBOL_PCT default comment with safe profile value (0.25) in config/strategy_config.py
- [x] T013 [P] Update MAX_BOTS_PER_SYMBOL default comment with safe profile value (2) in config/strategy_config.py

**Checkpoint**: Configuration foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - View Accurate Account Balances (Priority: P1) 🎯 MVP

**Goal**: Fix the $0.00 available balance bug in dashboard header

**Independent Test**: Load dashboard with funded account, verify "Avail" field shows correct non-zero balance

### Implementation for User Story 1

- [x] T014 [US1] Add available_balance handling after wallet_balance block (line ~895) in static/js/app_lf.js
- [x] T015 [US1] Add guard for missing #pos-available-balance element in static/js/app_lf.js
- [x] T016 [US1] Update colspan from "12" to "13" for empty positions row (line 899) in static/js/app_lf.js
- [x] T017 [US1] Bump cache-buster version query param in templates/dashboard.html
- [ ] T018 [US1] Restart app.py and verify /api/positions returns available_balance field

**Checkpoint**: User Story 1 complete - available balance displays correctly

---

## Phase 4: User Story 2 - Prevent Excessive Grid Recentering Churn (Priority: P1)

**Goal**: Add anti-churn protections to prevent recenter loops in volatile markets

**Independent Test**: Run grid bot during high volatility, verify recenter triggers only once per cooldown period

### Implementation for User Story 2

- [x] T019 [US2] Add last_recenter_ts field initialization in bot creation in services/grid_bot_service.py
- [x] T020 [US2] Add cooldown check before any recenter operation in services/grid_bot_service.py
- [x] T021 [US2] Update last_recenter_ts after successful recenter in services/grid_bot_service.py
- [x] T022 [P] [US2] Add position-open check before recenter for dynamic mode in services/grid_bot_service.py
- [x] T023 [P] [US2] Add position-open check before recenter for trailing mode in services/grid_bot_service.py
- [x] T024 [P] [US2] Add position-open check before recenter for scalp mode in services/grid_bot_service.py
- [x] T025 [US2] Add volatility freeze check (ATR%/BBW% threshold) before recenter in services/grid_bot_service.py
- [x] T026 [US2] Add mode gate to defer neutral_classic recentering to neutral_grid_service in services/grid_bot_service.py
- [x] T027 [US2] Verify neutral_grid_service.recenter_if_trailing() position check exists in services/neutral_grid_service.py
- [x] T028 [US2] Add logging for anti-churn protection activations in services/grid_bot_service.py

**Checkpoint**: User Story 2 complete - recenter churn is prevented

---

## Phase 5: User Story 3 - Safe Auto-Stop on Direction Change (Priority: P1)

**Goal**: Prevent stranded losing positions when auto-stop triggers

**Independent Test**: Trigger direction change with losing position, verify bot enters reduce-only mode

### Implementation for User Story 3

- [x] T029 [US3] Add reduce_only_mode field to bot state in services/grid_bot_service.py
- [x] T030 [US3] Modify auto-stop logic to set reduce_only_mode instead of full stop when position losing in static/js/app_lf.js
- [x] T031 [US3] Add trend_direction enum field to /api/bots/runtime response in app.py
- [x] T032 [US3] Extract trend_direction from scalp_analysis or indicators in app.py
- [x] T033 [US3] Replace regex parsing of trend_status with trend_direction field in static/js/app_lf.js
- [ ] T034 [US3] Add reduce-only mode processing logic in services/grid_bot_service.py (skip new entries, allow closes)
- [ ] T035 [US3] Add auto_stop_paused field to distinguish from normal stop in services/grid_bot_service.py
- [x] T036 [US3] Bump cache-buster version in templates/dashboard.html

**Checkpoint**: User Story 3 complete - auto-stop safely handles losing positions

---

## Phase 6: User Story 4 - Reliable Dashboard with Unified Frontend (Priority: P2)

**Goal**: Eliminate console errors and update incorrect comments

**Independent Test**: Load dashboard, verify no console errors, all sections update correctly

### Implementation for User Story 4

- [x] T037 [US4] Update comments referencing "app.js" to "app_v5.js" in static/js/app_lf.js
- [x] T038 [US4] Verify dashboard loads without console errors (manual browser check)
- [x] T039 [US4] Document helper functions that remain duplicated with rationale in code comments in static/js/app_lf.js

**Checkpoint**: User Story 4 complete - dashboard runs error-free

---

## Phase 7: User Story 5 - Configurable Global Risk Kill-Switch (Priority: P2)

**Goal**: Add optional global kill-switch to halt trading on excessive daily losses

**Independent Test**: Enable kill-switch, simulate losses exceeding threshold, verify all bots pause

### Implementation for User Story 5

- [x] T040 [US5] Add kill_switch_triggered field to storage/risk_state.json schema in services/risk_manager_service.py
- [x] T041 [US5] Add kill_switch_triggered_at field to risk state in services/risk_manager_service.py
- [x] T042 [US5] Add daily_loss_pct calculation to risk manager cycle in services/risk_manager_service.py
- [x] T043 [US5] Add kill-switch trigger logic when GLOBAL_KILL_SWITCH_ENABLED and loss exceeds MAX_DAILY_LOSS_PCT in services/risk_manager_service.py
- [ ] T044 [US5] Implement pause all bots action when kill-switch triggers in services/risk_manager_service.py
- [ ] T045 [US5] Implement cancel non-reducing orders action when kill-switch triggers in services/risk_manager_service.py
- [x] T046 [US5] Add daily_loss_pct and kill_switch fields to /api/summary response in app.py
- [ ] T047 [P] [US5] Add optional /api/risk/reset-kill-switch endpoint in app.py

**Checkpoint**: User Story 5 complete - global kill-switch operational

---

## Phase 8: User Story 6 - Fee-Aware Scalp Minimum Profit (Priority: P2)

**Goal**: Make scalp minimum profit adaptive to fees and spreads

**Independent Test**: Configure scalp bot, verify min profit includes fee and spread calculations

### Implementation for User Story 6

- [x] T048 [US6] Add calculate_adaptive_min_profit() function in services/scalp_pnl_service.py
- [x] T049 [US6] Implement formula: max(config_min, notional * fee_pct * multiplier, spread_cost * 2) in services/scalp_pnl_service.py
- [x] T050 [US6] Add spread threshold check for no-trade state in services/scalp_pnl_service.py
- [x] T051 [US6] Add liquidity check for no-trade state in services/scalp_pnl_service.py
- [x] T052 [US6] Add last_close_ts tracking to bot state in services/scalp_pnl_service.py
- [x] T053 [US6] Add post-close cooldown check before new entries in services/scalp_pnl_service.py
- [x] T054 [US6] Add logging for adaptive profit calculations and no-trade states in services/scalp_pnl_service.py

**Checkpoint**: User Story 6 complete - scalp profits are fee-aware

---

## Phase 9: User Story 7 - Safer Out-of-Range Behavior (Priority: P2)

**Goal**: Pause instead of recenter during extreme volatility out-of-range conditions

**Independent Test**: Trigger out-of-range during high volatility, verify bot pauses instead of recentering

### Implementation for User Story 7

- [ ] T055 [US7] Add volatility check to out-of-range decision logic in services/grid_bot_service.py
- [ ] T056 [US7] Modify OUT_OF_RANGE_ACTION handling to choose "pause" when volatility extreme in services/grid_bot_service.py
- [ ] T057 [US7] Add regime strength check ("too_strong") to activate defensive behavior in services/grid_bot_service.py
- [ ] T058 [US7] Add logging for out-of-range pause decisions in services/grid_bot_service.py

**Checkpoint**: User Story 7 complete - out-of-range handles volatility safely

---

## Phase 10: User Story 8 - Consistent UPnL Stop-Loss Across Modes (Priority: P3)

**Goal**: Ensure UPnL SL triggers correctly in all bot modes

**Independent Test**: Run bots in all 4 modes with UPnL SL configured, verify SL triggers correctly

### Implementation for User Story 8

- [ ] T059 [US8] Audit UPnL SL implementation for neutral_classic_bybit in services/grid_bot_service.py
- [ ] T060 [P] [US8] Audit UPnL SL implementation for scalp_pnl mode in services/grid_bot_service.py
- [ ] T061 [P] [US8] Audit UPnL SL implementation for dynamic mode in services/grid_bot_service.py
- [ ] T062 [P] [US8] Audit UPnL SL implementation for trailing mode in services/grid_bot_service.py
- [ ] T063 [US8] Fix any inconsistencies found in UPnL SL across modes in services/grid_bot_service.py
- [ ] T064 [US8] Verify upnlSlBadges() in app_lf.js correctly displays SL info for all modes in static/js/app_lf.js

**Checkpoint**: User Story 8 complete - UPnL SL consistent across modes

---

## Phase 11: User Story 9 - Enforced Neutral Classic Loss Prevention (Priority: P3)

**Goal**: Ensure NLP checks actually block order placement when triggered

**Independent Test**: Trigger loss prevention conditions, verify orders are actually blocked

### Implementation for User Story 9

- [ ] T065 [US9] Audit NLP check invocation in _run_neutral_classic_bybit() in services/grid_bot_service.py
- [ ] T066 [US9] Verify NLP block result prevents order placement in services/grid_bot_service.py
- [ ] T067 [US9] Add momentum filter inventory cap tightening when ADX exceeds threshold in services/neutral_loss_prevention_service.py
- [ ] T068 [US9] Verify correct candle timeframe for breakout confirmation in services/neutral_loss_prevention_service.py
- [ ] T069 [US9] Add logging for NLP enforcement actions in services/neutral_loss_prevention_service.py

**Checkpoint**: User Story 9 complete - NLP checks are enforced

---

## Phase 12: User Story 10 - Reasonable Default Position Limits (Priority: P3)

**Goal**: Provide safe default position limits for new traders

**Independent Test**: Create new bot without modifying limits, verify defaults are applied

### Implementation for User Story 10

- [ ] T070 [US10] Add "Safe Profile" comment block with recommended defaults in config/strategy_config.py
- [ ] T071 [US10] Audit validate_new_bot() checks limits at creation time in services/risk_manager_service.py
- [ ] T072 [US10] Add missing limit checks to validate_new_bot() if not present in services/risk_manager_service.py
- [ ] T073 [US10] Add validation failure logging and user feedback in services/risk_manager_service.py

**Checkpoint**: User Story 10 complete - safe defaults available

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: Final verification and documentation

- [ ] T074 [P] Restart app.py and runner.py with all changes applied
- [ ] T075 [P] Run manual verification checklist from quickstart.md
- [ ] T076 Verify /api/positions returns wallet_balance and available_balance (numeric)
- [ ] T077 Verify dashboard "Avail" field updates (not stuck at $0.00)
- [ ] T078 [P] Verify no console errors in browser developer tools
- [ ] T079 [P] Verify no column shifting in position/bot tables
- [ ] T080 Run at least one bot in neutral_classic_bybit mode and verify logs
- [ ] T081 [P] Run at least one bot in scalp_pnl mode and verify logs
- [ ] T082 [P] Run at least one bot in dynamic mode and verify logs
- [ ] T083 [P] Run at least one bot in trailing mode and verify logs
- [ ] T084 Observe logs for recenter behavior - confirm no recenter spam
- [ ] T085 Final code review for any missed items from auditprompt.txt

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-12)**: All depend on Foundational phase completion
- **Polish (Phase 13)**: Depends on all user stories being complete

### User Story Dependencies

| Story | Priority | Can Start After | Dependencies |
|-------|----------|-----------------|--------------|
| US1 - Available Balance | P1 | Foundational | None - can start first |
| US2 - Anti-Churn | P1 | Foundational | None - can start in parallel with US1 |
| US3 - Auto-Stop Safety | P1 | Foundational | None - can start in parallel with US1/US2 |
| US4 - Unified Frontend | P2 | US1 | Uses same file (app_lf.js) - wait for US1 |
| US5 - Kill-Switch | P2 | Foundational | Uses foundational constants |
| US6 - Fee-Aware Scalp | P2 | Foundational | Uses foundational constants |
| US7 - Out-of-Range | P2 | US2 | Builds on recenter logic from US2 |
| US8 - UPnL SL Consistency | P3 | Foundational | Audit task - can run anytime |
| US9 - NLP Enforcement | P3 | Foundational | Audit task - can run anytime |
| US10 - Position Limits | P3 | Foundational | Uses foundational comments |

### Within Each User Story

- Config changes before service changes
- Backend changes before frontend changes
- Core implementation before logging/polish

### Parallel Opportunities

**Phase 2 (Foundational)**: T005-T013 can all run in parallel (different config sections)

**Phase 4 (US2)**: T022, T023, T024 can run in parallel (different mode checks)

**Phase 10 (US8)**: T060, T061, T062 can run in parallel (different mode audits)

**Phase 13 (Polish)**: T078-T083 can run in parallel (different verification tasks)

---

## Parallel Example: Phase 2 - Foundational Constants

```bash
# All these can be created simultaneously in config/strategy_config.py:
Task: "Add VOLATILITY_FREEZE_ATR_PCT constant (0.03)"
Task: "Add VOLATILITY_FREEZE_BBW_PCT constant (0.08)"
Task: "Add SCALP_FEE_MULTIPLIER constant (2.5)"
Task: "Add SCALP_SPREAD_THRESHOLD_PCT constant (0.005)"
Task: "Add SCALP_POST_CLOSE_COOLDOWN_SEC constant (30)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (backup files)
2. Complete Phase 2: Foundational (add config constants)
3. Complete Phase 3: User Story 1 (available balance fix)
4. **STOP and VALIDATE**: Test available balance display
5. Restart services and verify fix

### Recommended Execution Order

Given the P1 priority user stories affect different files:

1. **Complete US1** (app_lf.js only) → Test → Commit
2. **Complete US2** (grid_bot_service.py, neutral_grid_service.py) → Test → Commit
3. **Complete US3** (app_lf.js + app.py + grid_bot_service.py) → Test → Commit
4. Then P2 stories: US4 → US5 → US6 → US7
5. Then P3 stories: US8 → US9 → US10
6. Final: Polish phase

### Single Developer Strategy

1. Setup + Foundational
2. All P1 stories in sequence (US1 → US2 → US3)
3. Restart and full test after P1 complete
4. P2 stories in sequence
5. P3 stories in sequence
6. Polish and final verification

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Restart app.py + runner.py after any Python/template changes
- Bump cache-buster in dashboard.html after any JS changes
