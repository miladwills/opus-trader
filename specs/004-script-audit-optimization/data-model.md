# Data Model: Script Audit and Optimization

## Entities

### BotState (Persistence: storage/bots.json)
Extending the existing bot state with better tracking for safety and audit logs.

- **id**: UUID. Unique bot identifier.
- **status**: String (`running`, `paused`, `error`, `stopped`).
- **_block_opening_orders**: Boolean. Safety flag to prevent new entries after errors.
- **_last_recenter_ts**: Float. Timestamp of last grid recenter.
- **_last_emergency_partial_close**: Float. Timestamp of last safety exit.
- **last_error**: String. Formatted error message with context.

### Position (Derived from Bybit + Enriched)
Mapping the "Avail: $0.00" fix.

- **symbol**: String.
- **side**: String (`Buy`, `Sell`).
- **size**: Float.
- **position_value**: Float.
- **available_balance**: Float. This represents the total available margin in the account (UTA-aware).
- **wallet_balance**: Float. Total equity (including unrealized PnL).

### StrategyParams (Strategy Config)
Dynamic markers for trailing modes.

- **use_dynamic_atr**: Boolean. If true, distances are calculated based on volatility.
- **atr_period**: Integer. Period for ATR calculation.
- **atr_multiplier**: Float. Sensitivity of trailing/scalp triggers.

## Validation Rules

- `available_balance` MUST NOT be negative.
- `_last_recenter_ts` MUST respect the cooldown period defined in `strategy_config.py`.
- `position_size` MUST be checked before any recenter trigger.
