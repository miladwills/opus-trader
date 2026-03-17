# Data Model: Unified to Funding Transfer

## Entities

### AccountBalance
Represents the balance information for a specific account type.

- **account_type**: String (`UNIFIED`, `FUND`).
- **equity**: Float. Total equity in USDT.
- **available_balance**: Float. Balance available for trading/withdrawal.
- **realized_pnl**: Float. Cumulative realized profit and loss.
- **unrealized_pnl**: Float. Current floating profit and loss.

### TransferRequest
Represents a request to move funds between accounts.

- **amount**: Float (Positive). The amount of USDT to transfer.
- **coin**: String (Default: `USDT`).
- **from_account_type**: String (e.g., `UNIFIED`).
- **to_account_type**: String (e.g., `FUND`).
- **transfer_id**: UUID. Unique identifier generated for the transaction.

## Validation Rules

- `amount` MUST be greater than 0.
- `from_account_type` and `to_account_type` MUST be valid Bybit account types.
- `coin` MUST be a supported asset (USDT is primary focus).

## Relationships

- An `AccountBalance` is retrieved for each account type involved in a transfer before and after the operation.
- A `TransferRequest` generates a transaction on the exchange, resulting in updates to multiple `AccountBalance` entities.
