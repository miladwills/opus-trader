---
description: "Task list for Fix Funding Balance Display implementation"
---

# Tasks: Fix Funding Balance Display

**Input**: Design documents from `/specs/002-fix-funding-balance-display/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Tests are OPTIONAL. The tasks below include manual verification steps as no automated test framework is established for this service layer fix.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Verify access to `services/account_service.py` and ability to restart server

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 [P] Create backup of `services/account_service.py` before modification

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Accurate Funding Balance Display (Priority: P1) 🎯 MVP

**Goal**: Ensure the Funding Account balance (USDT) is correctly fetched, parsed, and displayed on the dashboard.

**Independent Test**:
1. Check logs for "Funding Balance Response".
2. Verify dashboard shows non-zero funding balance (if funds exist).
3. Verify "Max" button in transfer modal uses correct balance.

### Implementation for User Story 1

- [x] T003 [US1] Add debug logging to `get_overview` in `services/account_service.py` to capture raw `fund_response`
- [x] T004 [US1] Improve parsing logic in `services/account_service.py` to robustly find "USDT" coin (case-insensitive or alternative keys) and log warning if missing
- [x] T005 [US1] Restart server and verify logs show the raw response structure
- [x] T006 [US1] Verify dashboard funding balance matches the log data

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T007 Remove temporary debug logging if response is confirmed and fix is stable (optional cleanup)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup
- **User Stories (Phase 3+)**: Depends on Foundational

### User Story Dependencies

- **User Story 1 (P1)**: Only story in this feature.

### Parallel Opportunities

- N/A for this small fix.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 (Fix parsing + Logging)
4. **STOP and VALIDATE**: Verify logs and dashboard
5. Deploy
