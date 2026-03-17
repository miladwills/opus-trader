# Quickstart: Full Script Audit and Optimization

## Overview
This guide describes how to verify the safety audit and optimization fixes.

## 1. Safety Audit Verification
### `bot_id` Definition
- Open `services/grid_bot_service.py`.
- Search for `_emergency_partial_close`.
- Verify `bot_id = bot.get("id")` is defined BEFORE the `try` block.

### Redundant File Removal
- Verify the following files are removed:
    - `services/bot_manager_service_lf.py`
    - `services/grid_bot_service_lf.py`
    - `services/neutral_grid_service_lf.py`
- Verify `app.py` and `runner.py` still start without import errors.

## 2. Optimization Verification
### Recenter Safety Guard
- Start a bot with `neutral_recenter_enabled: true`.
- Open a manual position for the same symbol.
- Verify the logs show `Skipping recenter: Positions open`.

### Available Balance Fix
- Open the dashboard positions table.
- Verify the "Avail" column shows a non-zero value if your account has margin.

## 3. Dynamic Mode Verification
- Configure a bot with `trailing` or `scalp` mode.
- Check the runner logs for `ATR-based distance calculation` messages.
