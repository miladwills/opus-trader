# Research: Unified to Funding Transfer

## Unknowns & Investigations

### Investigation 1: Fetching Funding Account Balance
**Question**: How to fetch the Funding account balance specifically using Bybit V5 API?
**Findings**:
- Endpoint: `/v5/account/wallet-balance`
- Parameter: `accountType=FUND`
- Response: Standard wallet balance response format.
- Decision: Extend `AccountService` to accept an optional `account_type` parameter in `get_overview` or add a new method specifically for Funding balance.

### Investigation 2: Internal Transfer API Details
**Question**: Is the current `BybitClient.create_internal_transfer` implementation correct for V5 Asset Transfer?
**Findings**:
- Current implementation uses `/v5/asset/transfer/inter-transfer`.
- Required parameters: `transferId` (UUID), `coin`, `amount`, `fromAccountType`, `toAccountType`.
- Valid account types: `UNIFIED`, `FUND`.
- Decision: The existing implementation in `BybitClient` is correct. It needs to be called with the correct account types.

### Investigation 3: Frontend Modal and Balance Updates
**Question**: Best practice for adding a transfer modal in the existing Tailwind dashboard?
**Findings**:
- Existing dashboard uses Tailwind CSS and Vanilla JS.
- Decision: Create a simple hidden `div` modal in `dashboard.html`. Add an "Asset Transfer" button next to the wallet balance display. Use `fetch` in `app.js` to call `/api/transfer`.

## Consolidated Findings

- **Decision**: Extend `AccountService.get_overview` to also fetch and return the `FUND` account balance.
- **Rationale**: The dashboard already calls `api_account_overview`, which uses `AccountService.get_overview`. Adding it here ensures both balances are available to the frontend in a single call.
- **Alternatives considered**: Adding a separate API endpoint for Funding balance. Rejected because it would require an additional network request from the frontend during the polling cycle.

- **Decision**: Add a new API endpoint `/api/account/funding-balance` (Internal helper).
- **Rationale**: Useful for specific lookups if needed, but primary display will be through the overview.

- **Decision**: Update `api_transfer` in `app.py` to correctly map the `fromAccountType` and `toAccountType` as requested by the spec (Unified -> Funding).
- **Rationale**: Ensures the backend logic correctly implements the specific transfer flow requested.
