# Research: Increase Liquidation Distance Priority

## Unknowns & Investigations

### Investigation 1: Exact Margin Calculation Formula
**Question**: How to calculate the exact USDT amount needed to reach a specific liquidation distance?
**Findings**:
- **Isolated Margin (Long)**: `LiqPrice = EntryPrice - (InitialMargin + ExtraMargin)/Size + EntryPrice * MMR`
- **Target Liq Price**: `MarkPrice * (1 - TargetDistance)`
- **Formula for Extra Margin**: `ExtraMargin = Size * (EntryPrice * (1 + MMR) - MarkPrice * (1 - TargetDistance)) - InitialMargin`
- **Maintenance Margin Rate (MMR)**: Standard is 0.005 (0.5%).
- **Decision**: Implement a robust calculation using the above formula to avoid "guessing" with small increments.

### Investigation 2: Priority and Cooldown Bypass
**Question**: How to make this "very high priority"?
**Findings**:
- Currently, `_auto_margin_guard` has a 20s cooldown.
- For extremely low liq distances (< 5%), the cooldown should be bypassed.
- **Decision**: Add a `critical_bypass` logic that triggers if `pct_to_liq < 5.0` and the position is newly opened.

### Investigation 3: Margin Allocation Safety
**Question**: How to avoid "dumping all balance"?
**Findings**:
- Config already has `max_total_add_usdt` and `max_add_usdt`.
- **Decision**: Ensure these caps are strictly enforced even in the high-priority "jump to 15%" path. Default `MAX_MARGIN_ALLOCATION_PER_BOT` should be safe (e.g., 20% of bot investment).

## Consolidated Findings

- **Decision**: Use a math-based approach to calculate the exact margin needed for a 15% safety buffer.
- **Rationale**: Faster and more precise than incremental top-ups.
- **Alternatives considered**: Incremental adding (Current logic). Rejected because it's too slow for fast-moving markets.
