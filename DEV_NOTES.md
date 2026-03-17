# Developer Notes

Technical implementation details for Opus Trader internals.

---

## orderLinkId Format

The `orderLinkId` field in Bybit orders is used to attribute trades back to the correct bot for PnL tracking.

### Version 2 Format (Current)

```
bv2:{bot_id_16}:{ts_8}{seq}{side}{intent}
```

| Component | Description | Example |
|-----------|-------------|---------|
| `bv2` | Version prefix | `bv2` |
| `bot_id_16` | First 16 chars of UUID (no dashes) | `a1b2c3d4e5f67890` |
| `ts_8` | Last 8 digits of ms timestamp | `12345678` |
| `seq` | 2-digit sequence (00-99) | `01` |
| `side` | Order side | `B` (Buy), `S` (Sell) |
| `intent` | Order intent | `O` (Open/entry), `C` (Close/reduceOnly) |

**Example:** `bv2:a1b2c3d4e5f67890:1234567801BO`

**Total length:** 33 characters (fits Bybit's 36 limit)

**Uniqueness:** 8 digits of ms timestamp = ~27 hours before wrap

### Neutral Classic Bybit Format (Slot-Based)

```
bv2:{bot_id_16}:{seq6}:{slot}:{E|X}
```

| Component | Description | Example |
|-----------|-------------|---------|
| `bot_id_16` | First 16 chars of UUID (no dashes) | `a1b2c3d4e5f67890` |
| `seq6` | 6-digit sequence | `000123` |
| `slot` | Grid slot (L/S + level index) | `L03`, `S12` |
| `E|X` | Entry or Exit | `E` (ENTRY), `X` (EXIT) |

**Example:** `bv2:a1b2c3d4e5f67890:000123:L03:E`

**Used by:** `NEUTRAL_CLASSIC_BYBIT` slot state machine.

### Version 1 Format (Legacy)

```
{prefix}:{short_id}:{ts}:{seq}
```

| Prefix | Usage |
|--------|-------|
| `bot` | Standard grid orders |
| `scalp` | Scalp profile orders |
| `init` | Initial entry orders |
| `qtp` | Quick take-profit orders |
| `scalp_mkt` | Scalp market orders |

**Example:** `bot:a1b2c3d4:789012:0`

**Problem:** 8-character `short_id` can collide between bots, causing incorrect PnL attribution.

---

## PnL Service Parsing

The PnL service (`services/pnl_service.py`) parses orderLinkId to attribute fills to bots.

### Parsing Logic

```python
if order_link_id.startswith("bv2:"):
    # v2: Extract bot_id_16 from parts[1]
    bot_id = parts[1]  # 16 chars, no dashes
else:
    # v1: Extract short_id from parts[1]
    bot_id = parts[1]  # 8 chars
```

### Bot Lookup Strategy

Both v1 and v2 use prefix matching:

| Format | Bot ID | Matching |
|--------|--------|----------|
| v1 (8-char) | `a1b2c3d4` | Match start of full UUID |
| v2 (16-char) | `a1b2c3d4e5f67890` | Match start of UUID without dashes |

**Prefix Matching:**
```python
for bot in all_bots:
    full_id = bot["id"]
    full_id_clean = full_id.replace("-", "")  # Remove dashes

    if len(bot_id) <= 8:
        # v1: Match start of full UUID
        if full_id.startswith(bot_id):
            matching_bots.append(bot)
    else:
        # v2: Match start of UUID without dashes
        if full_id_clean.startswith(bot_id):
            matching_bots.append(bot)
```

**Collision Handling:**
- If 1 match: Use it
- If multiple: Filter by symbol
- If still ambiguous: Log warning, use first

---

## Margin-Freeing Order Cancellation

When the bot needs to free margin (e.g., approaching liquidation), it cancels far orders.

### Key Rule: Skip reduceOnly Orders

**Canceling reduceOnly orders does NOT free margin** - they only close existing positions.

Only **opening orders** (non-reduceOnly) reserve margin and should be cancelled.

### Implementation

```python
def _emergency_cancel_far_orders(self, symbol, last_price, ...):
    # Filter to only opening orders (not reduceOnly)
    opening_orders = [
        o for o in orders
        if not self._is_reduce_only_order(o)
    ]

    # Cancel farthest opening orders first
    far_orders = sorted(opening_orders,
                        key=lambda x: abs(x["price"] - last_price),
                        reverse=True)
```

### reduceOnly Detection

1. **Primary:** Check Bybit API `reduceOnly` field
2. **Fallback:** Parse orderLinkId intent suffix (`C` = close = reduceOnly)

```python
def _is_reduce_only_order(self, order, order_link_id=None):
    # Check API field first
    if order.get("reduceOnly") is True:
        return True

    # Fallback: parse orderLinkId intent
    parsed = self._parse_order_link_id(order_link_id)
    if parsed.get("intent") == "close":
        return True

    return False
```

### Order Tracking

The `existing_orders_with_ids` list now includes reduceOnly status:
```python
# (price, order_id, side, is_reduce_only)
existing_orders_with_ids.append((price, order_id, side, is_reduce_only))
```

When filtering for cancellation:
```python
# Only consider non-reduceOnly orders for margin freeing
far_orders = [
    (price, oid, side)
    for price, oid, side, is_ro in existing_orders_with_ids
    if not is_ro
]
```

---

## Files Reference

| File | Relevant Functions |
|------|-------------------|
| `services/grid_bot_service.py` | `_build_order_link_id()`, `_parse_order_link_id()`, `_is_reduce_only_order()`, `_emergency_cancel_far_orders()` |
| `services/pnl_service.py` | `_process_trade_fill()` - parsing and bot lookup |

---

## Neutral Classic Bybit Mode (NEUTRAL_CLASSIC_BYBIT)

### Hedge Mode Requirement
- Must run in Bybit Hedge Mode.
- LONG leg uses `positionIdx=1`, SHORT leg uses `positionIdx=2`.
- If hedge mode is not enabled or `positionIdx` is unsupported, the bot refuses to start with `HEDGE_MODE_REQUIRED`.
- Enable hedge mode per symbol in the Bybit UI (Position Mode -> Hedge) or via the Bybit position mode switch API.

### Required Bot Config Fields
- `mode`: `"NEUTRAL_CLASSIC_BYBIT"`
- `grid_lower_price`, `grid_upper_price`

---

## Fast Execution Layer (1m)

Multi-timeframe execution keeps regime signals on 15m/5m while using 1m only for fast exits.

### Configuration

Global defaults live in `config/strategy_config.py`:
- `EXECUTION_TF`, `REGIME_TF_PRIMARY`, `REGIME_TF_SECONDARY`
- `PARTIAL_TP_*` (fractions, ATR trigger, min profit, cooldown)
- `PROFIT_LOCK_*` (arm, giveback, close fraction, cooldown)
- `FAST_EXEC_TAKER_FEE_RATE`, `FAST_EXEC_SLIPPAGE_BUFFER_PCT`
- `SMALL_CAPITAL_PARTIAL_TP_MAX_SKIPS`

Per-bot overrides (keys in bot JSON):
- Partial TP: `partial_tp_enabled`, `partial_tp_fractions`, `partial_tp_trigger_atr_mult`, `partial_tp_min_profit_pct`, `partial_tp_cooldown_sec`
- Profit lock: `profit_lock_enabled`, `profit_lock_arm_pct`, `profit_lock_giveback_pct`, `profit_lock_close_fraction`, `profit_lock_cooldown_sec`
- Fee guard: `taker_fee_rate` or `fee_rate`, plus `fast_exec_slippage_buffer_pct`

### Safety Notes
- All fast-execution closes are reduce-only and use existing qty normalization guards.
- Fee guard: `effective_min_profit_pct = max(user_min_profit_pct, 2*fee_rate + slippage_buffer)`.
- Small-cap behavior: if partial TP skips hit `SMALL_CAPITAL_PARTIAL_TP_MAX_SKIPS`, the bot auto-disables partial TP.
- `grid_levels_total` (N grids => N+1 price levels)
- `neutral_post_only` (bool)
- `neutral_recenter_enabled` (bool, default false)
- `neutral_recenter_threshold_pct` (default 2.0)

### State Machine Summary
- Grid levels are fixed between `[grid_lower_price, grid_upper_price]` with uniform step.
- Below current price: place LONG ENTRY limit buys.
- Above current price: place SHORT ENTRY limit sells.
- ENTRY fill flips to EXIT at adjacent level:
  - Long entry at level i -> place reduceOnly sell at level i+1.
  - Short entry at level j -> place reduceOnly buy at level j-1.
- EXIT fill flips back to the corresponding ENTRY at the original entry level.
- Slots are persisted under `bot["neutral_grid"]` (levels, mid_index, slots, seq).

### Recenter Behavior
- If enabled and price exits range by threshold, cancel ENTRY orders only and reseed the grid.
- EXIT orders (reduceOnly) are never cancelled automatically.

---

## Safety/Risk Hardening (January 2026 Update)

### Required Environment Variables

The following environment variables **MUST** be set before starting the application:

#### Security (Required)

```bash
# REQUIRED: Dashboard credentials (no defaults - app will not start without these)
BASIC_AUTH_USER=your_admin_user
BASIC_AUTH_PASS=your_strong_password_here

# REQUIRED: Mainnet API credentials (mainnet only)
BYBIT_MAINNET_API_KEY=your_mainnet_key
BYBIT_MAINNET_API_SECRET=your_mainnet_secret

# Legacy fallback (used only if BYBIT_MAINNET_* is not set)
BYBIT_API_KEY=your_mainnet_key
BYBIT_API_SECRET=your_mainnet_secret
```

#### Optional Security Settings

```bash
# IP Allowlist (comma-separated, empty = allow all)
# Localhost (127.0.0.1, ::1) always bypasses this check
DASH_ALLOW_IPS=192.168.1.100,10.0.0.5

# Server binding (defaults to 127.0.0.1 for security)
APP_HOST=127.0.0.1
APP_PORT=8000

# Runner API is disabled by default on mainnet (set true to enable /api/runner/start)
RUNNER_API_ENABLE=false

# Optional override for runner lock file location
RUNNER_LOCK_FILE=storage/runner.lock
```

---
### Runner Lock

- `runner.py` holds an OS-level `fcntl.flock` lock at `RUNNER_LOCK_FILE`.
- `/api/runner/start` checks the same lock and returns 409 if already held.

---
### Order Qty Normalization

- All order placement goes through `BybitClient.normalize_qty(symbol, qty)` using `minOrderQty` and `qtyStep`.
- If normalized qty is below `minQty` or rounds to 0, order is skipped with log:
  `skip_order qty_below_min symbol=... raw_qty=... normalized_qty=... minQty=... step=...`

---
### Emergency Close Hard-Fail

- Emergency close paths hard-fail if a close order cannot be placed.
- `_hard_fail_bot` sets `status="error"`, stores the reason, and raises.

---
### Reverse Proxy Note

- The app binds to `127.0.0.1` by default.
- If exposing via a reverse proxy, keep the app on localhost and terminate TLS/auth at the proxy.
- `DASH_ALLOW_IPS` always allows localhost (127.0.0.1, ::1).

---

### Dual-Tick Risk Loop

The runner now operates on two tick intervals:

- **Risk Tick** (1 second): Fast UPnL stop-loss checks for all running bots
- **Grid Tick** (10 seconds): Full bot cycle including order management, PnL sync, etc.

This allows catching fast market moves while keeping API usage reasonable.

Configuration (`config/strategy_config.py`):
```python
GRID_TICK_SECONDS = 10   # Full bot cycle interval
RISK_TICK_SECONDS = 1    # Fast risk check interval
```

---

### Unrealized PnL Stop-Loss (UPnL SL)

Per-bot stop-loss based on unrealized PnL percentage. Takes precedence over legacy `MAX_BOT_LOSS_PCT`.

#### Thresholds

| Level | Action | Default (Most Symbols) | ETHUSDT |
|-------|--------|------------------------|---------|
| Soft | Block opening orders, cancel pending opens | -12% | -20% |
| Hard | Close position, enter cooldown | -18% | -30% |

#### Bot Fields

```json
{
  "upnl_stoploss_enabled": true,
  "upnl_stoploss_soft_pct": null,
  "upnl_stoploss_hard_pct": null,
  "upnl_stoploss_basis": "used_margin",
  "upnl_stoploss_cooldown_seconds": null,
  "upnl_stoploss_close_mode": "reduce_only_market",
  "upnl_stoploss_close_on_soft": false,
  "upnl_stoploss_cooldown_until": null,
  "upnl_stoploss_last_trigger": null,
  "upnl_stoploss_trigger_count": 0
}
```

#### Symbol Defaults

Configure in `config/strategy_config.py`:

```python
UPNL_STOPLOSS_SYMBOL_DEFAULTS = {
    "ETHUSDT": {
        "max_position_pct": 70,
        "soft_pct": -20,
        "hard_pct": -30,
        "cooldown_seconds": 1800,  # 30 min
    },
    "__default__": {
        "max_position_pct": 50,
        "soft_pct": -12,
        "hard_pct": -18,
        "cooldown_seconds": 3600,  # 1 hour
    },
}
```

---

### Forced Isolated Margin Mode

Bots now automatically set ISOLATED margin mode on start. This prevents:
- Cross-margin liquidation cascades
- Unexpected margin sharing between positions

If the margin mode cannot be set, the bot will **fail to start** (fail-safe behavior).

---

### Stop-Loss Precedence

The system checks stop-losses in this order:

1. **UPnL HARD SL** - Immediate position close + cooldown
2. **UPnL SOFT SL** - Block opening orders, cancel pending opens
3. **Legacy MAX_BOT_LOSS_PCT** - Only checked if UPnL SL is disabled

---

### Security Hardening

- **No hardcoded credentials**: API keys/secrets must come from environment variables
- **Required password**: `BASIC_AUTH_PASS` must be set or app won't start
- **Localhost binding**: Server binds to `127.0.0.1` by default (use reverse proxy for external access)
- **Debug disabled**: Debug mode is off by default (enable with `APP_DEBUG=true`)
- **IP allowlist**: Optional IP filtering (localhost always allowed)

---

### Dashboard UPnL SL Indicators

The bot status column shows UPnL SL status:

| Badge | Meaning |
|-------|---------|
| `🛡️` | UPnL SL enabled (hover for thresholds) |
| `⚠️ SOFT SL` | Soft threshold hit, opening orders blocked |
| `🛑 HARD SL` | Hard threshold hit, position closed |
| `⏳ Xm Ys` | Cooldown active with countdown |
| `🛡️×N` | Number of times UPnL SL has triggered |

---

### New Log Messages

```
# Fast risk check (every 1s for enabled bots)
[SYMBOL] 🛑 FAST RISK: HARD UPnL SL triggered - UPnL -25.5% <= HARD -18%
[SYMBOL] ⚠️ FAST RISK: SOFT UPnL SL triggered - UPnL -15.2% <= SOFT -12%

# Margin mode set on bot start
[SYMBOL] margin_mode_set=ISOLATED leverage_set=6

# Tick intervals at startup
Tick intervals: RISK=1s, GRID=10s
```

---

### AI Advisor / Guardian (OpenRouter)

Optional AI layer that provides conservative, structured recommendations. The AI **never** places orders directly. It only returns JSON guidance that is applied if it passes hard guardrails.

#### Environment Variables

```bash
# Required if any bot sets ai_advisor_enabled=true
OPENROUTER_API_KEY=your_openrouter_key

# Optional (defaults shown)
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_TIMEOUT_SECONDS=12
OPENROUTER_MAX_TOKENS=350
OPENROUTER_TEMPERATURE=0.2

# Optional attribution headers
OPENROUTER_HTTP_REFERER=https://yourdomain.example
OPENROUTER_X_TITLE=OpusTrader
```

#### Per-Bot Fields (bots.json)

```json
{
  "ai_advisor_enabled": true,
  "ai_advisor_interval_seconds": 60,
  "ai_advisor_model": "",
  "ai_advisor_confidence_threshold": 0.65,
  "ai_advisor_apply": true,
  "ai_advisor_allow_modes": ["LONG_DYNAMIC", "TRAILING_LONG", "PAUSE"]
}
```

#### Guardrails (Hard Enforcement)

- Calls are rate-limited per bot (min 60s).
- AI cannot change leverage or disable stop-loss logic.
- `max_position_cap_pct` can only be **reduced** and must stay within:
  - ETHUSDT: 40..75
  - Other symbols: 30..60
- `trade_allowed=false` blocks **new opening orders** only; reduce-only closes still run.
- If AI output is invalid, out of bounds, or below confidence threshold → **NO_CHANGE** (ignore).

#### Dashboard Label

Bots with AI enabled show an inline badge:

- `AI GUARD: ALLOW`
- `AI GUARD: PAUSE`
- `AI GUARD: NO_CHANGE`

---

### Testing Checklist

- [ ] Start app without `BASIC_AUTH_PASS` - should fail with clear error
- [ ] Start app without API keys - should fail with clear error
- [ ] Verify server binds to `127.0.0.1` by default
- [ ] IP allowlist blocks unauthorized IPs (if configured)
- [ ] Fast risk loop runs every 1s (check logs)
- [ ] Grid cycle runs every 10s (check logs)
- [ ] UPnL SOFT: blocks opening orders, cancels pending opens
- [ ] UPnL HARD: closes position, sets cooldown
- [ ] Cooldown blocks new orders for configured duration
- [ ] Legacy `MAX_BOT_LOSS_PCT` only triggers when UPnL SL disabled
- [ ] `set_margin_mode("ISOLATED")` called on bot start
- [ ] reduceOnly orders never canceled by margin-freeing logic
- [ ] Dashboard shows UPnL SL status and cooldown badges

---

*Last updated: January 2026*

---

## Small-Capital Mode (Adaptive Risk Tuner)

### Feature Flags

```python
SMALL_CAPITAL_MODE_ENABLED = True
SMALL_CAPITAL_INVEST_USDT_THRESHOLD = 50
```

### Behavior Summary

- When enabled and `investment <= threshold`, bots use adaptive sizing:
  - Effective grid levels are reduced so per-order notional meets `minNotional * 1.2`.
  - Grid step uses ATR% (5m) with symbol profile clamps (ETH vs MEME).
  - Orders below `minQty` or `minNotional` are skipped (rate-limited logs).
- Above threshold, bots keep existing behavior (backward compatible).

### Status/Observability

Exposed in status JSON (per bot):
- `effective_levels`, `per_order_notional`, `effective_step_pct`, `effective_range_pct`
- `atr_5m_pct`, `atr_15m_pct`
- `effective_upnl_soft`, `effective_upnl_hard`, `effective_upnl_liq_pct`, `liq_distance_pct`
- `skipped_small_qty_count`, `last_skip_reason`
- `auto_margin_remaining_cap`

### Small-Capital Auto-Margin Policy

- MEME/ALT profiles: auto-margin disabled by default unless `small_capital_allow_auto_margin=true` on the bot.
- ETHUSDT: total add-margin capped at 2.0 USDT and limited to 1 add per hour.
- Auto-margin never runs when stoploss is active or AI action is `PAUSE`.

---

## Safe Rollout Runbook (No Live Orders)

1) Run self-checks:
   - `python3 scripts/self_check_small_capital.py`
   - `python3 scripts/self_check_safety.py`
2) Restart services after flag changes.
3) Start ONE bot only (recommend `ETHUSDT`) and monitor:
   - `effective_levels` / `per_order_notional`
   - skip counters and `last_skip_reason`
   - absence of `retCode=110017`
   - any `CLOSE_FAILED` events
4) After 30–60 minutes stable, enable a second bot.
