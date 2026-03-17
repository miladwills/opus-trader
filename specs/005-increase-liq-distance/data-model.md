# Data Model: Increase Liquidation Distance Priority

## Entities

### AutoMarginRequest
Represents a calculated request to add margin to a position to achieve a target liquidation distance.

- **symbol**: String. Trading pair symbol.
- **position_idx**: Integer. 0, 1, or 2 (One-way, Buy Hedge, Sell Hedge).
- **current_liq_distance**: Float. Percentage distance from mark price to liquidation price.
- **target_liq_distance**: Float. Target percentage distance (e.g., 15.0).
- **amount_needed**: Float. Calculated USDT amount required to reach the target.
- **max_allowed**: Float. Maximum amount the bot is permitted to add in this request.

### BotConfig (Updated)
Configuration parameters that control the auto-margin behavior.

- **enabled**: Boolean.
- **min_trigger_pct**: Float. Threshold to start adding margin (e.g., 15.0).
- **target_liq_pct**: Float. Desired liq distance after addition (e.g., 20.0).
- **critical_pct**: Float. Threshold for bypassing cooldowns and using exact math (e.g., 5.0).
- **max_total_add_usdt**: Float. Total budget for margin additions per bot.

## Validation Rules

- `amount_needed` MUST NOT exceed `available_balance` of the account.
- `amount_needed` MUST respect `max_add_usdt` per request.
- `total_added_usdt` MUST NOT exceed `max_total_add_usdt`.
