# Research: Full Script Audit and Optimization

## Unknowns & Investigations

### Investigation 1: Redundant and Conflicting Files
**Question**: Which files are actually used and which are redundant?
**Findings**:
- `app.py` and `runner.py` import services from `services/` using standard names (e.g., `GridBotService`, `BotManagerService`).
- Files with `_lf.py` suffix (Live Features) are NOT imported and appear to be experimental forks.
- Root-level files like `grid_bot_service_remote.py`, `temp_file.py`, and `latest_opus_...zip` are leftovers from manual deployments or backups.
- **Decision**: Consolidate logic from `_lf.py` if unique, then delete. Cleanup root level junk.

### Investigation 2: `bot_id` NameError in Emergency Paths
**Question**: Where does `name 'bot_id' is not defined` originate?
**Findings**:
- Grep confirms occurrences in `bots.json` error logs.
- Source identified in `_emergency_partial_close` and similar methods in `grid_bot_service.py`. If an exception occurs before `bot_id` is assigned, the `except` block's call to `_hard_fail_close` or logging might fail if it references the local variable.
- **Decision**: Define `bot_id = bot.get("id")` at the very start of every method, BEFORE any `try` block.

### Investigation 3: Available Balance $0.00 in Dashboard
**Question**: Why does the positions table show $0.00 available?
**Findings**:
- `api_positions` relies on `account_service.get_overview()`.
- `account_service.py` specifically looks for "USDT" in the coin list of a Unified Account. In UTA, the specific coin balance might be 0 while the total account margin is positive.
- **Decision**: Update `AccountService.get_overview` to fallback to `totalAvailableBalance` at the account level if the specific USDT coin balance is not found or is less than the total margin.

### Investigation 4: Optimization of Trailing and Scalp Modes
**Question**: How to make the bot "smart" and avoid churn?
**Findings**:
- Neutral recentering already has a position guard, but it needs to be "zero-tolerance" (strictly blocked if position > 0).
- Trailing modes currently use static thresholds.
- **Decision**: Implement ATR-based distance calculation for trailing and scalp modes to adjust to current volatility.

## Consolidated Findings

- **Decision**: Standardize on a single service set (Remove `_lf.py` files).
- **Decision**: Define identifiers early in method scopes to prevent `NameError`.
- **Decision**: Use `totalAvailableBalance` for UTA users to fix the $0.00 UI bug.
- **Decision**: Harden `NeutralGridService` with a strict `if position_size > 0: skip_recenter` rule.
