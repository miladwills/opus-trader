# Research: Funding Balance Display

## Unknowns & Investigations

### Investigation 1: Conflicting `refreshSummary` Definitions
**Question**: Why is the funding balance showing as $0.00 despite a working backend API?
**Findings**:
- `grep` revealed 7 different definitions of `refreshSummary` across various versions of `app.js` and `app_lf.js`.
- The version in `app_lf.js` (which is loaded *after* `app_v5.js` in `dashboard.html`) does not include the logic to update the `summary-funding-balance` element.
- This override effectively reverts the UI display to its default state ($0.00).

## Consolidated Findings

- **Decision**: Update the `refreshSummary` function in `app_lf.js` to include funding balance logic.
- **Rationale**: This is the file currently loaded in the dashboard and is causing the direct issue.
- **Decision**: Fix the `logging` import in `account_service.py`.
- **Rationale**: Resolves an LSP error and ensures proper logging availability.
