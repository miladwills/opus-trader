# API Contract Changes: Trading Bot Audit

## Overview

This document specifies changes to existing API endpoints. No new endpoints are added.

---

## Modified Endpoints

### GET /api/positions

**Current Response** (unchanged fields):
```json
{
  "positions": [...],
  "wallet_balance": 1234.56,
  "available_balance": 1000.00
}
```

**Verification Required**:
- `available_balance` field already exists in response
- Frontend (app_lf.js) must consume this field

**No Backend Changes Required** - field is already returned by app.py.

---

### GET /api/bots/runtime

**Current Response Fields** (partial):
```json
{
  "bots": [
    {
      "id": "bot-123",
      "symbol": "BTCUSDT",
      "status": "running",
      "mode": "neutral_classic_bybit",
      "trend_status": "Price: $100, trend: bullish, momentum: strong"
    }
  ]
}
```

**New/Modified Fields**:
```json
{
  "bots": [
    {
      "id": "bot-123",
      "symbol": "BTCUSDT",
      "status": "running",
      "mode": "neutral_classic_bybit",
      "trend_status": "Price: $100, trend: bullish, momentum: strong",
      "trend_direction": "bullish",
      "reduce_only_mode": false,
      "last_recenter_ts": 1705000000.0
    }
  ]
}
```

| Field | Type | Values | Source |
|-------|------|--------|--------|
| `trend_direction` | string enum | "bullish", "bearish", "neutral", "unknown" | Extracted from scalp_analysis or indicators |
| `reduce_only_mode` | boolean | true/false | Bot state in storage |
| `last_recenter_ts` | float | Unix timestamp | Bot state in storage |

**Backend Change Required**: app.py must populate these fields from bot storage and indicator analysis.

---

### POST /api/bots/{bot_id}/stop

**Current Behavior**:
- Stops bot entirely
- May or may not close positions

**Modified Behavior** (when auto-stop triggers):
- If position is profitable: Stop normally
- If position is losing: Set `reduce_only_mode = true` instead of full stop

**Request**: No changes  
**Response**: No changes

**Behavior Change Only** - triggered by frontend auto-stop logic.

---

### GET /api/summary

**Current Response** (partial):
```json
{
  "total_pnl": 100.00,
  "daily_pnl": 10.00
}
```

**New Fields** (for kill-switch monitoring):
```json
{
  "total_pnl": 100.00,
  "daily_pnl": 10.00,
  "daily_loss_pct": 0.02,
  "kill_switch_triggered": false,
  "kill_switch_triggered_at": null
}
```

| Field | Type | Purpose |
|-------|------|---------|
| `daily_loss_pct` | float | Current day's loss as percentage of equity |
| `kill_switch_triggered` | boolean | Global kill-switch has fired |
| `kill_switch_triggered_at` | float/null | Timestamp when triggered |

**Backend Change Required**: app.py must read from risk_state.json.

---

### POST /api/risk/reset-kill-switch

**New Endpoint** (optional, for kill-switch reset):

**Request**:
```json
{
  "confirm": true
}
```

**Response**:
```json
{
  "success": true,
  "message": "Kill-switch reset. Trading may resume."
}
```

**Purpose**: Allow user to manually reset kill-switch after reviewing situation.

---

## Frontend Contract (JavaScript)

### app_lf.js: refreshPositions()

**Must Consume**:
```javascript
const availableBalance = data.available_balance || 0;
const availableBalanceEl = document.getElementById('pos-available-balance');
if (availableBalanceEl) {
  availableBalanceEl.textContent = `$${availableBalance.toFixed(2)}`;
}
```

### app_lf.js: updateRunningBotsStatus()

**Must Use Structured Field**:
```javascript
// Old (regex parsing):
const match = bot.trend_status.match(/trend:\s*(\w+)/i);

// New (structured field):
const direction = bot.trend_direction || 'unknown';
```

### Empty Table Row

**Current**: `colspan="12"`  
**Required**: `colspan="13"` (matches 13-column table)

---

## OpenAPI Schema (Reference)

```yaml
openapi: 3.0.0
info:
  title: Trading Bot Dashboard API
  version: 1.1.0
  description: Changes for trading bot audit

paths:
  /api/bots/runtime:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  bots:
                    type: array
                    items:
                      type: object
                      properties:
                        id:
                          type: string
                        trend_direction:
                          type: string
                          enum: [bullish, bearish, neutral, unknown]
                        reduce_only_mode:
                          type: boolean
                        last_recenter_ts:
                          type: number
                          format: float

  /api/summary:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  daily_loss_pct:
                    type: number
                    format: float
                  kill_switch_triggered:
                    type: boolean
                  kill_switch_triggered_at:
                    type: number
                    format: float
                    nullable: true
```
