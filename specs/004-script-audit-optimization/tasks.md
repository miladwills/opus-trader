---
description: "Task list for Full Script Audit and Optimization implementation"
---

# Tasks: Full Script Audit and Optimization

**Input**: Design documents from `/specs/004-script-audit-optimization/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are OPTIONAL. The tasks below focus on manual verification and log-based auditing as requested.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Identify all redundant files for removal (e.g., `services/*_lf.py`, root level `.zip`, `temp_file.py`)
- [x] T002 Configure a safe testnet environment in `.env` for audit verification

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 [P] Consolidate unique logic from `services/grid_bot_service_lf.py` into `services/grid_bot_service.py`
- [x] T004 [P] Establish `services/grid_bot_service.py` as single source of truth and remove `grid_bot_service_remote.py`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - System Audit and Bug Hunt (Priority: P1) 🎯 MVP

**Goal**: Eliminate runtime errors (e.g., `bot_id` NameError) and cleanup redundant code.

**Independent Test**: Trigger an emergency close in testnet; verify logs show no NameError and bot stops correctly.

### Implementation for User Story 1

- [x] T005 [US1] Define `bot_id = bot.get("id")` before `try` blocks in `services/grid_bot_service.py` and `services/bot_manager_service.py`
- [x] T006 [US1] Audit all emergency close paths in `services/grid_bot_service.py` to ensure all variables (e.g., `symbol`, `position_size`) are bound before use in `except` blocks
- [x] T007 [US1] Remove confirmed redundant files: `services/*_lf.py`, `grid_bot_service_remote.py`, and root level `.zip/tar.gz` artifacts
- [x] T008 [US1] Verify server starts and runner loop functions in `runner.py` after cleanup

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Strategy Optimization and Safety (Priority: P2)

**Goal**: Harden recenter safety and implement dynamic trailing markers.

**Independent Test**: Monitor logs for `Skipping recenter: Positions open` when a position exists and price deviates.

### Implementation for User Story 2

- [x] T009 [US2] Implement zero-tolerance position guard in `recenter_if_needed` in `services/neutral_grid_service.py`
- [x] T010 [US2] Implement zero-tolerance position guard in `recenter_if_trailing` in `services/neutral_grid_service.py`
- [x] T011 [US2] Add ATR (Average True Range) calculation method in `services/indicator_service.py`
- [x] T012 [US2] Integrate ATR-based dynamic distance logic for "Trailing" and "Scalp" modes in `services/grid_bot_service.py`

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Fix Dashboard Data Inconsistencies (Priority: P3)

**Goal**: Fix the $0.00 Available Balance display bug for UTA users.

**Independent Test**: Open positions table in dashboard; verify "Avail" column shows actual account margin.

### Implementation for User Story 3

- [x] T013 [US3] Update `AccountService.get_overview` in `services/account_service.py` to use `totalAvailableBalance` fallback for UTA accounts
- [x] T014 [US3] Update `/api/positions` endpoint mapping in `app.py` to ensure `available_balance` is correctly passed in the response
- [x] T015 [US3] Verify "Avail" column display formatting in `static/js/app.js` and `templates/dashboard.html`

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T016 Perform full system validation following `quickstart.md` steps
- [x] T017 Remove any remaining root-level backup files and debug logs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundation -> Audit/Bug Hunt (Critical for stability)
- **User Story 2 (P2)**: Foundation -> Strategy Harden (Depends on stable service layer)
- **User Story 3 (P3)**: Foundation -> UI Fix (Independent of strategy logic but depends on AccountService)

### Parallel Opportunities

- T003 and T004 (Merging and cleaning core services)
- T011 (Indicator utility) can be developed in parallel with US1 tasks

---

## Parallel Example: User Story 1

```bash
# Launch core bug fixes and indicator utilities together:
Task: "Define bot_id before try blocks in services/grid_bot_service.py"
Task: "Add ATR calculation method in services/indicator_service.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Verify emergency close stability and file cleanup
5. Deploy stable core

### Incremental Delivery

1. Foundation + US1 (Stable Core)
2. Add US2 (Optimized Strategy Safety)
3. Add US3 (Accurate Dashboard Display)
4. Final Polish
