# Quickstart: Increase Liquidation Distance Priority

## Overview
This feature ensures that new positions are immediately protected by increasing their liquidation distance to at least 15%.

## Setup
1. Ensure `AUTO_MARGIN_PRESET` in `.env` is set to `aggressive` or `conservative` (both default to 15% trigger).
2. The bot will automatically handle the rest when a new position is opened.

## Verification Steps
1. **Open a Position**: Trigger the bot to open a new position.
2. **Monitor Logs**: Look for `FIRST_RUN_IMMEDIATE` in the runner logs.
3. **Verify Dashboard**: Confirm that the "Liq. Dist." column for the new position quickly moves to >= 15%.
4. **Safety Check**: Verify that `total_added_usdt` for the bot does not exceed its configured `max_total_add_usdt`.

## Configuration
In `storage/bots.json`, you can customize the behavior for a specific bot:
```json
"auto_margin": {
    "enabled": true,
    "min_trigger_pct": 15.0,
    "target_liq_pct": 20.0,
    "max_total_add_usdt": 10.0
}
```
