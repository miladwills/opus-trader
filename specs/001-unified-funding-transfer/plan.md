# Implementation Plan: Add Unified to Funding Transfer to Dashboard

**Branch**: `001-unified-funding-transfer` | **Date**: Wed Jan 14 2026 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-unified-funding-transfer/spec.md`

## Summary

The feature will enable users to move USDT between their Unified Trading Account and Funding Account directly from the dashboard. This will be implemented by extending the existing `AccountService` to fetch both account balances and using the `BybitClient.create_internal_transfer` method to execute the movement of funds via the Bybit V5 API.

## Technical Context

**Language/Version**: Python 3.11, JavaScript (ES6+)  
**Primary Dependencies**: Flask, Requests (Backend); Tailwind CSS (Frontend)  
**Storage**: N/A (State is managed on-exchange and retrieved via API)  
**Testing**: Manual verification via API and dashboard; potential for unit tests in `tests/unit/`  
**Target Platform**: Linux/Windows (Server), Web Browser (Client)
**Project Type**: Web application (Flask + Vanilla JS)  
**Performance Goals**: Dashboard balance updates within 2 seconds of transfer completion.  
**Constraints**: Requires valid Bybit API credentials with "Transfer" permissions.  
**Scale/Scope**: Single user interaction on dashboard.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I: Library-First**: The transfer logic is encapsulated in the `BybitClient` and `AccountService` libraries.
- **Principle II: CLI Interface**: N/A for this dashboard feature, but BybitClient could be used by CLI tools.
- **Principle III: Test-First**: Will verify via manual test cycles as automated suite is not yet established for UI.
- **Principle IV: Integration Testing**: Verified by actual API calls to Bybit (testnet if available).

## Project Structure

### Documentation (this feature)

```text
specs/001-unified-funding-transfer/
├── plan.md              # This file
├── research.md          # Research findings (Phase 0)
├── data-model.md        # Data entities (Phase 1)
├── quickstart.md        # Quick start guide (Phase 1)
├── contracts/           # API schemas (Phase 1)
└── checklists/
    └── requirements.md  # Spec validation
```

### Source Code (repository root)

```text
app.py                  # API endpoints (/api/transfer)
app.js                  # Frontend logic (transfer form and balance polling)
templates/
└── dashboard.html      # UI elements (Transfer button/modal/section)
services/
├── bybit_client.py     # API implementation (create_internal_transfer)
└── account_service.py  # Account balance logic (get_overview)
```

**Structure Decision**: The project uses a single-directory structure for the core logic with a `services/` folder for business logic. No changes to the overall structure are required, only additions to existing files.


## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
