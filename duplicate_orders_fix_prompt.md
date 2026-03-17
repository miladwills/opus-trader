# FIX: Neutral Grid Duplicate/Excess Orders Bug

## YOUR TASK

Fix a bug where neutral grid bots accumulate **more open orders than expected** (e.g. 28-32 orders when max should be 25), causing margin waste, duplicate slot orders, and eventual emergency stops.

**IMPORTANT RULES:**
- Python project, follow existing patterns (type hints, logging, `logger = logging.getLogger(__name__)`)
- Do NOT change any trading logic, order sizing, grid level calculation, or slot state machine
- The fix must be **conservative** — better to leave an extra order alive for one tick than to cancel a valid order
- All changes must work with both REST polling and WebSocket execution events
- Test that the fix doesn't break normal fast-refill behavior (missing orders must still be replaced promptly)

---

## PROJECT CONTEXT

### Directory Structure
```
c:\laragon\www\opus trader 2026\
├── services/
│   ├── grid_bot_service.py         # Fast-refill coordinator (14,058 lines) — MODIFY
│   ├── neutral_grid_service.py     # Grid reconciliation & order placement (2,138 lines) — MODIFY
│   └── bybit_client.py            # REST/WS API client
└── config/
    └── strategy_config.py          # Strategy constants
```

### What Happened (Real Incident — RIVERUSDT, bot 29c36d6e)

**Timeline from logs:**
```
03:18:36 ⚡ Fast refill reconcile: 28/25 orders open
03:18:36 Cancelled duplicate slot order bv2:29c36d6ed0664450:000196:L11:E
03:18:38 ⚡ Fast refill reconcile: 28/25 orders open     ← Still 28! Cancel hasn't propagated
03:18:41 ⚡ Fast refill reconcile: 28/25 orders open
03:18:46 ⚡ Fast refill reconcile: 29/25 orders open     ← Getting worse
03:18:51 ⚡ Fast refill reconcile: 29/25 orders open
03:19:08 ⚡ Fast refill reconcile: 30/25 orders open     ← Accelerating
03:19:10 Cancelled duplicate slot order bv2:...000261:L11:X
03:19:12 ⚡ Fast refill reconcile: 32/25 orders open     ← Peak excess
03:19:13 Cancelled duplicate slot order bv2:...000261:L11:X   ← Same order cancelled AGAIN
03:19:16 Cancelled duplicate slot order bv2:...000261:L11:X   ← And again...
03:19:18 Cancelled duplicate slot order bv2:...000261:L11:X
03:19:21 Cancelled duplicate slot order bv2:...000261:L11:X
03:19:35 ✓ Cycle completed
03:20:05 🚨 EMERGENCY STOP TRIGGERED FOR RIVERUSDT 🚨
```

**Slot L11 had duplicates cancelled 6 times in 45 seconds but kept recreating.**

---

## ROOT CAUSE ANALYSIS

### The Race Condition (3-step cycle repeating every ~1 second):

```
 TICK 1 (T+0ms)
 ├─ count_bot_open_orders() → 28 (> expected 25)
 ├─ open_count != expected → trigger reconcile_on_start()
 ├─ reconcile_on_start() finds slots with duplicate orders
 ├─ Sends cancel_order() to Bybit for duplicates
 ├─ Clears slot.order_id / slot.order_link_id for empty slots
 ├─ Places NEW orders for those now-empty slots           ← CREATES NEW ORDERS
 └─ Returns bot with 25 slots all having order_link_id set

 TICK 2 (T+1000ms)                                        ← 1 second later
 ├─ count_bot_open_orders() → 28                          ← STILL 28!
 │   Because: Bybit cancel is async (~200ms), BUT the new
 │   replacement orders from Tick 1 are ALSO now visible,
 │   so: 25 original + 3 new replacements - 3 cancelled = 25...
 │   EXCEPT the cancels haven't all propagated yet!
 │   Real count: 25 original + 3 replacements = 28 (cancels pending)
 ├─ open_count != expected → trigger reconcile_on_start() AGAIN
 ├─ Finds MORE duplicates (the old ones + the new ones)
 ├─ Cancels them, places MORE replacements
 └─ Cycle continues... order count GROWS

 TICK 3 (T+2000ms)
 └─ Even more duplicates, count reaches 30-32
```

### Why It Gets Worse Over Time

Each reconcile cycle:
1. **Cancels** N duplicate orders (async, takes ~200ms on Bybit)
2. **Places** N new replacement orders (succeeds immediately)
3. Net effect: for ~200ms, there are `expected + N` orders on exchange
4. Next tick sees the inflated count, triggers another reconcile
5. This creates MORE duplicates, not fewer

### The Core Problem

**[reconcile_on_start()](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py#58-349) is designed for startup (run once), not for being called every 1 second in a tight loop.** When called every 1s:
- It doesn't know it JUST cancelled duplicates 1 second ago
- It sees stale exchange state (cancels not yet propagated)
- It re-creates the same orders it's trying to clean up

---

## THE FIX (3 Parts)

### Part 1: Add reconcile cooldown to fast-refill (MODIFY [grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py))

**File:** [services/grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py)
**Method:** [run_neutral_classic_fast_refill](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py#2433-2522) (line 2433)

**Current code** (lines 2491-2506):
```python
            else:
                open_count = self.neutral_grid_service.count_bot_open_orders(
                    bot, symbol, self.client, skip_cache=True
                )
                if open_count != expected:
                    logger.info(
                        "[%s] ⚡ Fast refill reconcile: %s/%s orders open",
                        symbol,
                        open_count,
                        expected,
                    )
                    bot = self.neutral_grid_service.reconcile_on_start(
                        bot, symbol, self.client
                    )
                    if bot.get("status") == "error":
                        return bot
```

**Replace with:**
```python
            else:
                open_count = self.neutral_grid_service.count_bot_open_orders(
                    bot, symbol, self.client, skip_cache=True
                )
                if open_count != expected:
                    # Tolerance: if over-count is small (≤3 excess), it's likely
                    # pending cancellations from a previous reconcile. Skip this
                    # tick to let Bybit process the cancels. Only force reconcile
                    # if significantly over (>3 excess) or under-count (missing orders).
                    is_over_count = open_count > expected
                    excess = open_count - expected if is_over_count else 0

                    # Check cooldown: don't re-reconcile if we just did it
                    last_reconcile_ts = float(
                        (bot.get("neutral_grid") or {}).get("_last_reconcile_ts", 0) or 0
                    )
                    now_ts = time.time()
                    reconcile_cooldown_sec = 5.0  # Wait 5s between reconciles

                    if is_over_count and excess <= 3 and (now_ts - last_reconcile_ts) < reconcile_cooldown_sec:
                        logger.debug(
                            "[%s] ⚡ Skipping reconcile (cooldown): %s/%s orders, excess=%s, %.1fs since last reconcile",
                            symbol,
                            open_count,
                            expected,
                            excess,
                            now_ts - last_reconcile_ts,
                        )
                    else:
                        logger.info(
                            "[%s] ⚡ Fast refill reconcile: %s/%s orders open",
                            symbol,
                            open_count,
                            expected,
                        )
                        neutral_state = bot.get("neutral_grid") or {}
                        neutral_state["_last_reconcile_ts"] = now_ts
                        bot["neutral_grid"] = neutral_state
                        bot = self.neutral_grid_service.reconcile_on_start(
                            bot, symbol, self.client
                        )
                        if bot.get("status") == "error":
                            return bot
```

**Why this works:**
- Under-count (missing orders): Always reconciles immediately (critical for grid integrity)
- Over-count ≤3 excess: Waits 5 seconds before re-reconciling (lets cancels propagate)
- Over-count >3 excess: Always reconciles immediately (something is seriously wrong)
- The cooldown only applies to the fast-refill path, not the full bot cycle

---

### Part 2: Add delay after duplicate cancellation (MODIFY [neutral_grid_service.py](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py))

**File:** [services/neutral_grid_service.py](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py)
**Method:** [reconcile_on_start](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py#58-349) (line 58)

**Current code** (lines 249-267):
```python
        for duplicate_order in duplicate_slot_orders:
            try:
                client.cancel_order(
                    symbol=symbol,
                    order_id=duplicate_order.get("orderId"),
                    order_link_id=duplicate_order.get("orderLinkId"),
                )
                logger.warning(
                    "[%s] Cancelled duplicate slot order %s",
                    symbol,
                    duplicate_order.get("orderLinkId") or duplicate_order.get("orderId"),
                )
            except Exception:
                logger.warning(
                    "[%s] Failed to cancel duplicate slot order %s",
                    symbol,
                    duplicate_order.get("orderLinkId") or duplicate_order.get("orderId"),
                    exc_info=True,
                )
```

**Replace with:**
```python
        cancelled_duplicate_count = 0
        for duplicate_order in duplicate_slot_orders:
            try:
                client.cancel_order(
                    symbol=symbol,
                    order_id=duplicate_order.get("orderId"),
                    order_link_id=duplicate_order.get("orderLinkId"),
                )
                cancelled_duplicate_count += 1
                logger.warning(
                    "[%s] Cancelled duplicate slot order %s",
                    symbol,
                    duplicate_order.get("orderLinkId") or duplicate_order.get("orderId"),
                )
            except Exception:
                logger.warning(
                    "[%s] Failed to cancel duplicate slot order %s",
                    symbol,
                    duplicate_order.get("orderLinkId") or duplicate_order.get("orderId"),
                    exc_info=True,
                )

        # If we cancelled duplicates, give Bybit time to process before
        # placing replacement orders. This prevents the cancel-replace race.
        if cancelled_duplicate_count > 0:
            time.sleep(0.5)
            logger.info(
                "[%s] Waited 500ms for %d duplicate cancel(s) to propagate",
                symbol,
                cancelled_duplicate_count,
            )
```

**Why this works:** A 500ms sleep after cancelling duplicates lets Bybit process the cancellations before the code continues to check which slots need orders. Without this, the slot appears empty (order_id cleared in local state) so a new order is placed, but the old order is still alive on exchange — creating another duplicate.

---

### Part 3: Don't place new orders for slots that just had duplicates cancelled (MODIFY [neutral_grid_service.py](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py))

**File:** [services/neutral_grid_service.py](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py)
**Method:** [reconcile_on_start](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py#58-349) (line 58)

After the duplicate cancellation loop (Part 2 above) and before the slot order placement loop (line 303), add tracking of which slots had duplicates:

**Add this immediately after the duplicate cancellation block (after the sleep):**
```python
        # Track slots that had duplicates cancelled — don't re-place orders
        # for these slots in this reconcile pass. Let the next tick handle them
        # after the cancel has fully propagated on exchange.
        duplicate_cancelled_slots: set = set()
        for dup_order in duplicate_slot_orders:
            dup_link_id = dup_order.get("orderLinkId")
            dup_parsed = self._parse_order_link_id(dup_link_id)
            if dup_parsed:
                dup_slot_id = dup_parsed.get("slot")
                if dup_slot_id:
                    duplicate_cancelled_slots.add(dup_slot_id)
```

**Then modify the placement loop** (lines 303-337) to skip those slots:

**Current code:**
```python
        for slot_id, slot in slots.items():
            if slot.get("order_link_id"):
                continue
            place_result = self._place_slot_order(
```

**Replace with:**
```python
        for slot_id, slot in slots.items():
            if slot.get("order_link_id"):
                continue
            # Skip slots that just had duplicates cancelled — the existing
            # "winner" order in slot_open_map is already live on exchange.
            # Placing another order now would just create a new duplicate.
            if slot_id in duplicate_cancelled_slots:
                logger.debug(
                    "[%s] Skipping order placement for slot %s (duplicate just cancelled)",
                    symbol,
                    slot_id,
                )
                continue
            place_result = self._place_slot_order(
```

**Why this works:** When a slot has duplicates, one order is kept (`slot_open_map[slot_id] = order`) and the others are cancelled. The kept order is already live. But after the duplicate cancellation, the slot state is synced from the kept order (lines 272-280), so `slot.order_link_id` is already set and this skip won't trigger. HOWEVER, there's a subtle case: if the "kept" order is the one that gets cancelled (wrong one kept due to preferred_link_id logic), the slot ends up with no order, and a new one would be placed — creating another duplicate. This guard prevents that.

---

## IMPORTANT: What NOT to Change

1. ❌ Do NOT add `time.sleep()` anywhere in the fast-refill loop in [grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py) — it runs every 1s for ALL bots and a sleep would delay other bots
2. ❌ Do NOT change [count_bot_open_orders()](file:///C:/Users/Coding4/AppData/Local/Temp/neutral_grid_service_vps.py#1115-1132) — it correctly counts orders
3. ❌ Do NOT change the slot state machine (ENTRY/EXIT transitions) in [on_order_filled()](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py#439-569)
4. ❌ Do NOT change [_place_slot_order()](file:///C:/Users/Coding4/AppData/Local/Temp/neutral_grid_service_vps.py#1176-1450) logic
5. ❌ Do NOT change [process_execution_events()](file:///C:/Users/Coding4/AppData/Local/Temp/neutral_grid_service_vps.py#400-438) — execution processing is correct
6. ❌ Do NOT modify any grid level calculations or slot building

---

## VERIFICATION PLAN

### 1. Unit Tests
Create or update `tests/test_neutral_grid_duplicate_fix.py`:

```python
def test_fast_refill_cooldown_skips_recent_over_count():
    """When open_count > expected by ≤3 and reconcile was recent, skip reconcile."""
    # Set _last_reconcile_ts to 2 seconds ago
    # Call run_neutral_classic_fast_refill with open_count = expected + 2
    # Assert reconcile_on_start was NOT called

def test_fast_refill_reconciles_on_under_count_always():
    """When open_count < expected, always reconcile regardless of cooldown."""
    # Set _last_reconcile_ts to 1 second ago
    # Call run_neutral_classic_fast_refill with open_count = expected - 3
    # Assert reconcile_on_start WAS called

def test_fast_refill_reconciles_on_large_over_count():
    """When open_count > expected by >3, always reconcile."""
    # Set _last_reconcile_ts to 1 second ago
    # Call run_neutral_classic_fast_refill with open_count = expected + 5
    # Assert reconcile_on_start WAS called

def test_duplicate_cancelled_slots_skipped_in_placement():
    """Slots with recently cancelled duplicates should not get new orders."""
    # Create a slot with a duplicate order
    # Run reconcile_on_start
    # Assert _place_slot_order was NOT called for that slot

def test_duplicate_cancel_delay():
    """Verify sleep(0.5) occurs after duplicate cancellation."""
    # Mock time.sleep
    # Create duplicate_slot_orders list
    # Run reconcile_on_start
    # Assert time.sleep(0.5) was called
```

### 2. Integration Test (Manual on VPS)
```bash
# 1. Deploy the fix
# 2. Start a neutral bot with 25 grids on a low-volume symbol
# 3. Watch logs for 5 minutes:
grep -i 'duplicate\|reconcile\|excess\|cooldown' storage/runner.log

# Expected: No "duplicate slot order" warnings
# Expected: No "Fast refill reconcile: 28/25" or similar over-counts
# Expected: Order count stays at exactly 25
```

### 3. Stress Test
```bash
# Manually create a duplicate by:
# 1. Place a limit order with a bot's orderLinkId format on the same symbol
# 2. Watch the bot handle it within 1-2 ticks (cancel the extra, NOT spiral)
# Expected: Single "Cancelled duplicate" log, then stable 25/25
```

---

## DELIVERABLES

1. Modified [services/grid_bot_service.py](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py) — Add reconcile cooldown (~25 lines changed in [run_neutral_classic_fast_refill](file:///c:/laragon/www/opus%20trader%202026/services/grid_bot_service.py#2433-2522))
2. Modified [services/neutral_grid_service.py](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py) — Add delay after duplicate cancel + skip placement for affected slots (~20 lines in [reconcile_on_start](file:///c:/laragon/www/opus%20trader%202026/services/neutral_grid_service.py#58-349))
3. `tests/test_neutral_grid_duplicate_fix.py` — Unit tests for the fix

**Total: ~50 lines of changes across 2 files. Zero trading logic changes.**
