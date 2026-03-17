---
description: "Task list for Increase Liquidation Distance Priority implementation"
---

# Tasks: Increase Liquidation Distance Priority

**Input**: Design documents from `/specs/005-increase-liq-distance/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Tests**: Tests are OPTIONAL. The tasks below focus on manual verification and log auditing on testnet.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Verify API credentials in `.env` have "Asset Transfer" and "Spot" permissions enabled
- [x] T002 Update default auto-margin trigger to 15.0 and critical threshold to 5.0 in `config/strategy_config.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Implement math-based margin calculation formula for isolated positions in `services/grid_bot_service.py`
- [x] T004 Add `critical_pct` support to `_auto_margin_guard` configuration parsing in `services/grid_bot_service.py`
- [x] T005 [US1] Implement `FIRST_RUN_IMMEDIATE` bypass logic in `_auto_margin_guard` in `services/grid_bot_service.py`
- [x] T006 [US1] Ensure the bypass logic triggers if `last_ts == 0` and `pct_to_liq < 15.0` in `services/grid_bot_service.py`
- [x] T007 [US1] Implement high-priority bypass for `critical_pct` (< 5%) in `_auto_margin_guard` to skip cooldowns in `services/grid_bot_service.py`
- [x] T008 [US1] Log specialized `FIRST_RUN_IMMEDIATE` and `CRITICAL_RECOVERY` events to `storage/runner.log`
- [x] T009 [US2] Update `_auto_margin_guard` in `services/grid_bot_service.py` to strictly enforce `max_total_add_usdt` for all additions
- [x] T010 [US2] Add warning log when a bot reaches its margin cap but liq distance is still unsafe (< 15%) in `services/grid_bot_service.py`
- [x] T011 [US2] Update `auto_margin_remaining_cap` calculation in `services/grid_bot_service.py` for dashboard display


**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T012 Run full E2E manual validation following `quickstart.md` steps on testnet
- [x] T013 Verify that auto-margin actions are correctly reflected in `storage/bots.json` state

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundation -> Safety Trigger (MVP)
- **User Story 2 (P2)**: Foundation -> Allocation Guard (Risk Control)

### Parallel Opportunities

- T003 and T004 (Core math vs logic structure)
- US2 tasks (T009-T011) can be developed in parallel with US1 tasks (T005-T008) once Phase 2 is complete.

---

## Parallel Example: User Story 1 & 2

```bash
# Launch high-priority trigger and cap enforcement logic together:
Task: "Implement FIRST_RUN_IMMEDIATE bypass logic in services/grid_bot_service.py"
Task: "Update _auto_margin_guard to strictly enforce max_total_add_usdt"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test high-priority margin additions on testnet
5. Deploy safety fix

### Incremental Delivery

1. Foundation Ready
2. Add US1 (Safety Trigger) -> MVP
3. Add US2 (Budget Guard) -> Controlled Risk
4. Final Polish
