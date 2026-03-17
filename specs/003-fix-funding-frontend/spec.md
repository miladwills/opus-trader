# Feature Specification: Fix Funding Balance Frontend Display

**Feature Branch**: `003-fix-funding-frontend`  
**Created**: Wed Jan 14 2026  
**Status**: Draft  
**Input**: User description: "funding still $0.00"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Funding Balance (Priority: P1)

As a trader, I want to see my actual Funding Account balance on the dashboard, even when "Live Features" are enabled, so that I have an accurate view of my total assets.

**Why this priority**: The user has successfully transferred funds to the Funding account, but the UI is not reflecting this, creating confusion and a lack of trust in the displayed data.

**Independent Test**:
1. Open the dashboard.
2. Verify that the "Funding" balance updates from $0.00 to the actual balance (e.g., $1.00) during the first refresh cycle.
3. Perform a transfer from Unified to Funding and verify the Funding balance updates accordingly.

**Acceptance Scenarios**:

1. **Given** a positive Funding balance exists on the exchange, **When** the dashboard performs its periodic refresh, **Then** the `summary-funding-balance` element should be updated with the correct value.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST ensure that the `refreshSummary` function in all active JavaScript files (specifically `app_lf.js`) includes logic to update the `summary-funding-balance` element.
- **FR-002**: System MUST update the global `window._currentFundingBalance` variable to ensure the transfer modal has the correct "Max" value.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Dashboard displays non-zero Funding balance within 10 seconds of page load (after first refresh).
- **SC-002**: No console errors related to missing elements or undefined variables during the refresh cycle.
