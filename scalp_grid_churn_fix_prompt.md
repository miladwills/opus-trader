# FIX: Scalp PnL Grid Order Churn (12→15→12 Oscillation)

## YOUR TASK

Fix a performance and stability issue where the scalp_pnl bot's order count oscillates (e.g. 12→15→12) after each fill cycle, creating temporary duplicate/excess orders that waste margin and API rate limits.

**RULES:**
- Python project, follow existing patterns
- Do NOT change the scalp profit-taking logic, market analysis, or position management
- The fix must preserve the existing tolerance-based order reuse at lines 9885-9907
- Must work with both REST polling and WebSocket execution events
- Orders that haven't been filled should stay in place as much as possible

---

## ROOT CAUSE ANALYSIS

### What Currently Happens (the churn loop):

```
CYCLE 1: Momentum = "trending_down" → 40/60 split → 10 buys, 15 sells
  Grid levels: Buy [14.95, 14.94, 14.93, ...], Sell [15.01, 15.02, 15.03, ...]
  Places 12 orders (capped by margin/slots)

  ← ORDER FILLS →

CYCLE 2: Momentum = "neutral" → 50/50 split → 12 buys, 12 sells  
  Grid levels: Buy [14.96, 14.95, 14.94, ...], Sell [15.01, 15.02, ...]
  NEW levels: 14.96 (new buy), etc — not within 0.1% of any existing order
  REUSED levels: 14.95, 14.94, ... — matched existing orders ✓
  Places 3 NEW orders at new levels → count goes 12→15
  
CYCLE 3: Stale cleanup runs
  Cancels 3 old orders that are >25x grid spacing from center
  Count goes 15→12

  ← Repeat every fill →
```

### Three Contributing Factors:

**Factor 1: Momentum-based buy/sell split changes every cycle** (`scalp_pnl_service.py:586-601`)
```python
if momentum_direction == "up":
    num_buys = int(total_levels * 0.6)    # 60% buys
elif momentum_direction == "down":
    num_sells = int(total_levels * 0.6)   # 60% sells
else:
    num_buys = total_levels // 2           # 50/50
```
When momentum flips between cycles, the entire level distribution shifts, generating new levels that don't match old ones.

**Factor 2: `recommended_grid_distance` can change between cycles**
The `market_analysis.recommended_grid_distance` comes from the market condition analyzer and varies with volatility. Different distances = different price levels = no match with old orders.

**Factor 3: Stale cleanup is delayed** (`grid_bot_service.py:10505-10535`)
Old orders from the previous grid configuration stick around for 1-2 cycles (stale threshold is generous at 25x spacing), so new orders coexist with old ones temporarily.

---

## PROJECT FILES

```
c:\laragon\www\opus trader 2026\
├── services/
│   ├── grid_bot_service.py          # Lines 9800-10550: Scalp cycle — MODIFY
│   └── scalp_pnl_service.py         # Lines 556-633: get_scalp_grid_levels — MODIFY
└── config/
    └── strategy_config.py           # Scalp config constants
```

---

## THE FIX (3 Parts)

### Part 1: Lock grid levels until a fill event changes them (MODIFY [grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py))

**Concept:** Cache the generated grid levels (buy + sell) and reuse them across cycles unless the scalp center changes or a fill occurs. This prevents minor momentum direction changes from shuffling the grid every second.

**Where:** In the scalp cycle method, around lines 9867-9877

**Current code:**
```python
flat_position = total_long <= 0.0 and total_short <= 0.0

# Get scalp-optimized grid levels based on FIXED center (not current price)
buy_levels, sell_levels = self.scalp_pnl_service.get_scalp_grid_levels(
    last_price=scalp_center,
    market_analysis=market_analysis,
    tick_size=tick_size,
    grid_count=MAX_SCALP_ORDERS,
    force_balanced=flat_position,
)
```

**Replace with:**
```python
flat_position = total_long <= 0.0 and total_short <= 0.0

# Lock grid levels across cycles to prevent churn from minor momentum changes.
# Only regenerate when: (1) center moved, (2) a fill occurred, (3) no cached levels.
scalp_state = bot.get("_scalp_grid_state") or {}
cached_center = scalp_state.get("locked_center")
cached_buy = scalp_state.get("buy_levels")
cached_sell = scalp_state.get("sell_levels")
last_fill_seq = scalp_state.get("last_fill_seq", 0)
current_fill_seq = int(bot.get("_scalp_fill_seq", 0) or 0)

# Determine if we need fresh levels
center_moved = cached_center is None or abs(cached_center - scalp_center) > tick_size
fill_occurred = current_fill_seq != last_fill_seq
no_cache = not cached_buy or not cached_sell

if center_moved or fill_occurred or no_cache:
    buy_levels, sell_levels = self.scalp_pnl_service.get_scalp_grid_levels(
        last_price=scalp_center,
        market_analysis=market_analysis,
        tick_size=tick_size,
        grid_count=MAX_SCALP_ORDERS,
        force_balanced=flat_position,
    )
    # Cache the levels
    bot["_scalp_grid_state"] = {
        "locked_center": scalp_center,
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "last_fill_seq": current_fill_seq,
        "locked_at": now_iso,
    }
    logger.debug(
        f"[{symbol}] Scalp grid regenerated: center={scalp_center:.6f}, "
        f"buys={len(buy_levels)}, sells={len(sell_levels)}, "
        f"reason={'center_moved' if center_moved else 'fill' if fill_occurred else 'no_cache'}"
    )
else:
    buy_levels = cached_buy
    sell_levels = cached_sell
    logger.debug(
        f"[{symbol}] Scalp grid reused from cache: buys={len(buy_levels)}, sells={len(sell_levels)}"
    )
```

**Also:** Increment `_scalp_fill_seq` wherever fills are detected. Search for where `positions_closed` is incremented in the scalp cycle and add:
```python
bot["_scalp_fill_seq"] = int(bot.get("_scalp_fill_seq", 0) or 0) + 1
```

---

### Part 2: Increase order-level matching tolerance (MODIFY [grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py))

**Where:** Line 9887

**Current:**
```python
SCALP_ORDER_TOLERANCE_PCT = 0.001  # 0.1% - much smaller than grid spacing
```

**Replace with:**
```python
# Tolerance must be generous enough to catch orders from the same grid
# that shifted slightly due to rounding or minor center drift.
# Half the grid_distance ensures we match orders at the same grid level
# without accidentally matching adjacent levels.
SCALP_ORDER_TOLERANCE_PCT = min(
    recommended_dist * 0.4,   # 40% of grid spacing — won't cross to next level
    0.005,                     # Cap at 0.5% for safety
)
```

This makes the tolerance **proportional to the actual grid spacing** instead of a fixed 0.1%. If the grid spacing is 0.3%, the tolerance becomes 0.12% — enough to catch slightly shifted orders without merging adjacent levels.

---

### Part 3: Cancel-before-place ordering (MODIFY [grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py))

**Where:** Lines 10505-10535 (stale order cleanup) — move this BEFORE the order placement loop

The current order of operations is:
1. Place new orders (lines 10105-10483)
2. Then cancel stale orders (lines 10505-10535)

This means for 1-2 seconds, BOTH old and new orders exist. Flip the order:
1. Cancel stale orders FIRST
2. Then place new orders

**Move the stale cleanup block** (lines 10505-10535) to just BEFORE the "Place BUY orders" comment at line 10075.

Add a brief sleep after cancellations to let Bybit process them:
```python
if orders_cancelled > 0:
    time.sleep(0.3)
    # Refresh the order snapshot so placement loop has accurate state
    orders_resp_refresh = self.client.get_open_orders(symbol)
    if orders_resp_refresh.get("success"):
        order_list = orders_resp_refresh.get("data", {}).get("list", []) or []
        order_snapshot = self._snapshot_open_orders(order_list, tick_size)
        existing_order_prices = order_snapshot["existing_order_prices"]
        existing_order_prices_list = order_snapshot["existing_order_prices_list"]
        existing_orders_with_ids = order_snapshot["existing_orders_with_ids"]
        current_order_count = len(order_list)
        available_slots = max(0, MAX_SCALP_ORDERS - current_order_count)
```

---

## IMPORTANT: What NOT to Change

1. ❌ Do NOT modify [get_scalp_grid_levels()](file:///c:/laragon/www/opus%20trader%202026/services/scalp_pnl_service.py#556-634) level generation math
2. ❌ Do NOT change scalp profit-taking ([should_take_profit](file:///c:/laragon/www/opus%20trader%202026/services/scalp_pnl_service.py#444-555))
3. ❌ Do NOT change position closing logic
4. ❌ Do NOT change the recenter logic (center is already stabilized)
5. ❌ Do NOT remove the stale order cleanup — just reorder it
6. ❌ Do NOT add `time.sleep()` to the main fast-refill loop

---

## VERIFICATION

### 1. Compile Check
```bash
python -m py_compile services/grid_bot_service.py services/scalp_pnl_service.py
```

### 2. Run Existing Tests
```bash
python -m pytest -q tests/
```
All tests must pass (currently 272).

### 3. New Unit Test: `tests/test_scalp_grid_stability.py`

```python
def test_grid_levels_cached_across_cycles():
    """Grid levels should not change between cycles if center hasn't moved."""
    # Setup: bot with _scalp_grid_state cached
    # Run scalp cycle with same center, different momentum
    # Assert: buy_levels and sell_levels are reused from cache

def test_grid_levels_refresh_on_fill():
    """Grid levels should regenerate when a fill occurs."""
    # Setup: bot with cached levels, increment _scalp_fill_seq
    # Run scalp cycle
    # Assert: get_scalp_grid_levels was called (not cached)

def test_grid_levels_refresh_on_center_change():
    """Grid levels should regenerate when scalp center moves."""
    # Setup: bot with cached levels, change scalp_center by > tick_size
    # Run scalp cycle
    # Assert: get_scalp_grid_levels was called (not cached)

def test_tolerance_scales_with_grid_distance():
    """Order reuse tolerance should be proportional to grid spacing."""
    # Test with recommended_dist=0.003 → tolerance=0.0012
    # Test with recommended_dist=0.001 → tolerance=0.0004
    # Test with recommended_dist=0.02 → tolerance=0.005 (capped)

def test_stale_cleanup_runs_before_placement():
    """Stale orders should be cancelled before new orders are placed."""
    # Mock order list with stale orders
    # Verify cancel_order called before place_order
```

### 4. Functional Verification (Manual on VPS)
```bash
# After deploying:
# 1. Start a scalp_pnl bot with 12 grids
# 2. Watch logs for 5 minutes:
grep -E 'Scalp grid|orders placed|Scalp cycle|reused from cache|regenerated' storage/runner.log | tail -50

# Expected:
# - "Scalp grid reused from cache" on most cycles (no churn)
# - "Scalp grid regenerated" only on fills or center moves
# - Order count stays STABLE: always 12/12, never 12→15→12
# - "Scalp cycle complete - closed=0, placed=0, cancelled=0" on quiet cycles
```

---

## DELIVERABLES

1. Modified [services/grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py) — Grid level caching, dynamic tolerance, cancel-before-place (~50 lines)
2. `tests/test_scalp_grid_stability.py` — New test file (~80 lines)

**Total: ~130 lines of changes. Zero trading logic changes.**
