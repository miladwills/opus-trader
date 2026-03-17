---
description: "Task list for Add Unified to Funding Transfer to Dashboard implementation"
---

# Tasks: Add Unified to Funding Transfer to Dashboard

**Input**: Design documents from `/specs/001-unified-funding-transfer/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are OPTIONAL. The tasks below include basic manual verification steps as no automated test framework was requested.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Verify Bybit API permissions in `.env` for "Asset Transfer" and "Spot" access
- [x] T002 [P] Create contracts directory if not already exists at `specs/001-unified-funding-transfer/contracts/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 [P] Update `AccountService.get_overview` in `services/account_service.py` to fetch both UNIFIED and FUND balances
- [x] T004 [P] Verify `BybitClient.create_internal_transfer` parameters in `services/bybit_client.py` against Bybit V5 API specs

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Access and Execute Account Transfers (Priority: P1) 🎯 MVP

**Goal**: Enable users to move funds from Unified Trading to Funding account from the dashboard.

**Independent Test**: Successfully initiate a 1 USDT transfer from Unified to Funding and see a success notification.

### Implementation for User Story 1

- [x] T005 [US1] Create `/api/transfer` endpoint in `app.py` using `client.create_internal_transfer`
- [x] T006 [US1] Add "Transfer Assets" button to `templates/dashboard.html` in the account section
- [x] T007 [US1] Implement transfer modal HTML in `templates/dashboard.html` with source/dest/amount fields
- [x] T008 [US1] Implement `openTransferModal` and `closeTransferModal` functions in `app.js`
- [x] T009 [US1] Implement `submitTransfer` function in `app.js` using `fetch` to call `/api/transfer`
- [x] T010 [US1] Add success/error toast notifications in `app.js` after transfer completion

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - View Account Balances (Priority: P2)

**Goal**: Display current balances for both account types before and after transfers.

**Independent Test**: Dashboard shows correct balances for both Unified and Funding accounts on page load and after a transfer.

### Implementation for User Story 2

- [x] T011 [P] [US2] Update `api_account_overview` in `app.py` to include `funding_balance` in the JSON response
- [x] T012 [P] [US2] Update `refreshSummary` function in `app.js` to parse and store `funding_balance` from API response
- [x] T013 [US2] Add display element for Funding balance in the "Total Assets" card in `templates/dashboard.html`
- [x] T014 [US2] Implement balance refresh logic in `app.js` to trigger automatically after a successful transfer

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T015 Add loading spinner state to the transfer modal confirm button in `app.js`
- [ ] T016 Run end-to-end validation following `quickstart.md` steps

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2)
- **User Story 2 (P2)**: Can start after Foundational (Phase 2). Although it complements US1, the API changes in Phase 2 make it independently implementable.

### Parallel Opportunities

- T003 and T004 (Backend foundational changes)
- T011 and T012 (Data flow for balance display)
- US1 UI work (T006, T007) and Backend work (T005) can start together once foundation is ready.

---

## Parallel Example: User Story 1

```bash
# Launch backend endpoint and frontend UI components together:
Task: "Create /api/transfer endpoint in app.py"
Task: "Implement transfer modal HTML in templates/dashboard.html"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test transfer functionality manually
5. Deploy/demo

### Incremental Delivery

1. Foundation Ready
2. Add US1 (Transfer Flow) -> MVP
3. Add US2 (Funding Balance Display) -> Enhanced Dashboard
4. Polish (UX improvements)
