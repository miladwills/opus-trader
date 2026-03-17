# Feature Specification: Full Script Audit and Optimization

**Feature Branch**: `004-script-audit-optimization`  
**Created**: Wed Jan 14 2026  
**Status**: Draft  
**Input**: User description: "do full auditing for the whole script to look for any illogical codes or features, bugs, useless codes and features, features need fixing etc give me your best analysis and opinion to get the bot to be smart to avoid big losses in trading especially with crypto and make good profit especially in neutral classic trailling, long trailling, scalp pnl/d dynamic modes and check grids recentering safety to avoid churning, reduntant files that causing conflict, fix Avail: $0.00 alway $0.00 in open positions table etc"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - System Audit and Bug Hunt (Priority: P1)

As a trader, I want the system to be free of illogical code and runtime errors so that I can trust the bot to manage my capital safely.

**Why this priority**: Stability is the foundation of any trading bot. Illogical code can lead to catastrophic losses.

**Independent Test**: Can be tested by running the bot in dry-run/testnet mode and verifying no unexpected crashes or "NameError" logs appear during complex state transitions.

**Acceptance Scenarios**:

1. **Given** the bot is running, **When** an emergency close is triggered, **Then** the bot should execute the close without referencing undefined variables (e.g., `bot_id`).
2. **Given** multiple files exist for the same service, **When** auditing, **Then** the system should identify which files are actually used and which are redundant leftovers.

---

### User Story 2 - Strategy Optimization and Safety (Priority: P2)

As a trader, I want my trailing and scalp modes to be smart enough to maximize profit while the grid recenter logic prevents "churn-loss" (repeatedly opening and closing at a loss).

**Why this priority**: Direct impact on profitability and fee management.

**Independent Test**: Monitor the bot for 1 hour in a volatile market; verify it does not recenter more than once every X minutes if positions are open.

**Acceptance Scenarios**:

1. **Given** a neutral classic trailing bot is active, **When** price moves outside the range, **Then** it should recenter only if no positions are open or if specific safety thresholds are met.
2. **Given** scalp pnl/d dynamic mode is selected, **When** profit targets are reached, **Then** it should execute dynamic exits based on market momentum rather than fixed points.

---

### User Story 3 - Fix Dashboard Data Inconsistencies (Priority: P3)

As a trader, I want to see my actual available balance in the open positions table so that I can accurately assess my remaining margin.

**Why this priority**: Essential for manual monitoring and risk assessment.

**Independent Test**: Compare the "Avail" balance in the dashboard table with the Bybit mobile app or web interface.

**Acceptance Scenarios**:

1. **Given** I have open positions, **When** I view the positions table, **Then** the "Avail" column should show a non-zero value representing actual available margin.

---

### Edge Cases

- **API Disconnection during audit**: System must handle partial data from API without miscalculating "illogical" behavior.
- **Simultaneous Recenter triggers**: Prevent race conditions where two threads try to recenter the same grid.
- **Empty Wallet**: Ensure the "Avail $0.00" fix differentiates between a bug and an actual zero balance.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST perform a deep audit of all service modules to identify and fix `NameError`, `TypeError`, and illogical control flows.
- **FR-002**: System MUST implement a "Recenter Safety Guard" that prevents grid rebuilding if positions are currently open, unless specifically overridden.
- **FR-003**: System MUST optimize "Neutral Classic Trailing" and "Long Trailing" to use dynamic distance markers instead of static ones.
- **FR-004**: System MUST consolidate redundant files (e.g., comparing `grid_bot_service.py` vs `grid_bot_service_remote.py`) and establish a single source of truth.
- **FR-005**: System MUST fix the data mapping in the `/api/positions` endpoint to ensure the available balance is correctly passed to the frontend.

### Key Entities *(include if feature involves data)*

- **BotState**: The internal representation of a bot's current health and activity.
- **StrategyParams**: Configuration for trailing and scalp modes.
- **RiskGuard**: A set of rules that override trading actions to prevent loss.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% reduction in "NameError" occurrences in server logs over a 48h period.
- **SC-002**: Total "churn" events (recenter while positions open) reduced to 0 for standard bots (Zero-Tolerance: any recenter while position > 0 is blocked).
- **SC-003**: Available balance display matches exchange data with +/- 0.01% accuracy.
- **SC-004**: Removal of at least 3 redundant service files without regression in features.
