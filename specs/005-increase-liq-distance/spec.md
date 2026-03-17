# Feature Specification: Increase Liquidation Distance Priority

**Feature Branch**: `005-increase-liq-distance`  
**Created**: Wed Jan 14 2026  
**Status**: Draft  
**Input**: User description: "make to liq a very high priority when position open cause it open at only 2% distance which is too close to liquidation if the market moved fast!!! just make it increase to 15% don't dump all available balance into!"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Initial Liquidation Safety (Priority: P1)

As a trader using the bot, I want newly opened positions to immediately have a safe liquidation distance of at least 15% so that I don't get liquidated during fast market moves.

**Why this priority**: Protecting capital is the highest priority. A 2% distance is too risky for volatile crypto markets.

**Independent Test**: Can be tested by opening a new position through the bot and verifying that the auto-margin logic triggers immediately to increase the distance to liquidation to at least 15%.

**Acceptance Scenarios**:

1. **Given** a bot is running, **When** a new position is opened with a 2% liq distance, **Then** the system MUST automatically add margin to reach a 15% liq distance.
2. **Given** a position is open, **When** the liq distance is increased, **Then** the system MUST NOT use more than the configured maximum margin per bot.

---

### User Story 2 - Controlled Margin Allocation (Priority: P2)

As a risk manager, I want the bot to increase liquidation distance in a controlled manner without exhausting the entire account balance on a single position.

**Why this priority**: Prevents a single failing bot from draining the entire account, which allows other bots to continue operating.

**Independent Test**: Can be tested by simulating a fast-moving market against a bot with limited available capital and verifying it stops adding margin once its specific limit is reached.

**Acceptance Scenarios**:

1. **Given** a bot has reached its maximum margin allocation, **When** liq distance is still below 15%, **Then** the system MUST NOT add more margin and should log a warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST monitor liquidation distance of all open positions in real-time.
- **FR-002**: System MUST consider a liquidation distance below 15% as a "High Priority" risk event for newly opened positions.
- **FR-003**: System MUST automatically add margin to positions with liq distance < 15% to attempt reaching the 15% target.
- **FR-004**: System MUST respect a `MAX_MARGIN_ALLOCATION_PER_BOT` limit (configurable) to prevent account exhaustion.
- **FR-005**: System MUST log all auto-margin actions, including the amount added and the resulting liq distance.

### Key Entities *(include if feature involves data)*

- **BotConfig**: Includes `TARGET_LIQ_DISTANCE_PCT` (default 15%) and `MAX_MARGIN_ALLOCATION_PER_BOT`.
- **PositionState**: Tracks current liq distance and total margin added by the bot.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Newly opened positions reach >= 15% liq distance within 30 seconds of opening (assuming available margin).
- **SC-002**: Account-level "dumping" is prevented: no single bot adds margin exceeding its individual cap.
- **SC-003**: 100% of auto-margin actions are accurately recorded in the bot's trade logs.
