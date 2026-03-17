# Frontend Environment UI Implementation

## Overview

This document describes the frontend UI toggles added to support the Bybit environment toggle system (testnet vs mainnet) with paper trading controls.

## Changes Made

### 1. Bot Configuration Form (dashboard.html)

Added two new dropdowns to the bot configuration form:

**Trading Environment Selector:**
- Options: "Testnet (Safe)" or "Mainnet (Real Money ⚠️)"
- ID: `bot-trading-env`
- Default: testnet

**Trading Mode Selector:**
- Options: "Paper Trading (Sim)" or "Live Trading"
- ID: `bot-paper-trading`
- Default: Paper Trading (true)

**Location:** Lines 424-441 in `templates/dashboard.html`

### 2. JavaScript Functions Updated (static/js/app.js)

#### fillBotForm()
- **Purpose:** Populate form fields when editing an existing bot
- **Changes:** Added logic to populate `bot-trading-env` and `bot-paper-trading` selects
- **Default fallbacks:** testnet and true (paper trading)

#### resetBotForm()
- **Purpose:** Reset form to safe defaults
- **Changes:** Reset environment to "testnet" and paper trading to "true"

#### saveBot()
- **Purpose:** Create or update a bot
- **Changes:**
  - Read values from environment and paper trading selects
  - Include `trading_env` and `paper_trading` in bot data
  - Show confirmation dialog when saving a mainnet + live trading bot
  - Warning: "⚠️ WARNING: You are about to save a bot for MAINNET with LIVE TRADING. This will use REAL MONEY!"

#### environmentBadge()
- **Purpose:** Generate environment badge HTML for bot table
- **Changes:** New function added
- **Badge styles:**
  - **Testnet (Paper):** Blue badge - "TESTNET (Paper)"
  - **Testnet (Live):** Blue badge - "TESTNET (Live)"
  - **Mainnet (Paper):** Yellow/red badge with border - "🟡 MAINNET (Paper)"
  - **Mainnet (LIVE):** Red badge with border - "🔴 MAINNET (LIVE)"

#### switchBotEnvironment()
- **Purpose:** Switch a bot's environment via API
- **Changes:** New function added
- **Safety checks:**
  - Cannot switch while bot is running (403 error prevention)
  - Confirmation dialog for mainnet + live trading switches
  - Success/error alerts
- **API call:** `PATCH /api/bots/{id}/environment`

### 3. Bot Table Display (refreshBots)

**Environment Badge Display:**
- Badge shown below the symbol name in the bot table
- Small badge (10px font) with environment and trading mode
- Color-coded for quick visual identification:
  - Blue = testnet (safe)
  - Red = mainnet (danger)

**Location:** Lines 564-577 in `static/js/app.js`

## User Workflow

### Creating a New Bot

1. Fill in symbol, price range, investment, etc.
2. **Select Trading Environment:**
   - Default: Testnet (Safe)
   - Option: Mainnet (Real Money ⚠️)
3. **Select Trading Mode:**
   - Default: Paper Trading (Sim)
   - Option: Live Trading
4. Click "Save Bot"
5. If mainnet + live trading: Confirmation dialog appears
6. Bot is created with environment settings

### Editing an Existing Bot

1. Click the "✏️ Edit" button on a bot
2. Form populates with current bot settings, including environment
3. Modify environment/paper trading settings as needed
4. Click "Save Bot"
5. Confirmation shown if switching to mainnet + live

### Switching Environment for Existing Bot

**Via Edit Form:**
1. Edit the bot
2. Change environment/paper trading dropdowns
3. Save (triggers confirmation if needed)

**Via API (future enhancement):**
- Call `switchBotEnvironment(botId, newEnv, newPaperTrading)` function
- This can be wired to a button in the bot table or detail modal

## Safety Features

### Multi-Layer Protection

1. **Default to Safe:**
   - New bots: testnet + paper trading
   - Reset form: testnet + paper trading

2. **Visual Warnings:**
   - Red badges for mainnet
   - Warning emoji (⚠️) in dropdown
   - Border around dangerous badges

3. **Confirmation Dialogs:**
   - Saving mainnet + live bot
   - Switching to mainnet + live
   - Clear warnings about REAL MONEY

4. **Runtime Protection:**
   - Cannot switch environment while bot is running
   - Server-side validation in `PATCH /api/bots/{id}/environment`

5. **Credential Validation:**
   - Server checks that credentials exist for target environment
   - Returns 400 error if credentials missing

## API Integration

### Saving Bot (POST /api/bots)

**Request body includes:**
```json
{
  "symbol": "BTCUSDT",
  "lower_price": 50000,
  "upper_price": 52000,
  "investment": 50,
  "leverage": 3,
  "mode": "neutral",
  "profile": "normal",
  "trading_env": "testnet",      // NEW
  "paper_trading": true,         // NEW
  ...
}
```

### Switching Environment (PATCH /api/bots/{id}/environment)

**Request:**
```json
{
  "trading_env": "mainnet",
  "paper_trading": false
}
```

**Responses:**
- **200 OK:** Environment switched successfully
- **400 Bad Request:** Invalid environment or missing credentials
- **403 Forbidden:** Bot is running, cannot switch
- **404 Not Found:** Bot doesn't exist

## Testing Checklist

- [x] Create new bot with testnet + paper (default)
- [x] Create new bot with testnet + live
- [x] Create new bot with mainnet + paper (shows warning)
- [x] Create new bot with mainnet + live (shows strong warning)
- [x] Edit existing bot to change environment
- [x] Reset form returns to safe defaults
- [x] Environment badges display correctly in table
- [x] switchBotEnvironment() function works
- [x] Cannot switch while running (blocked by client)
- [x] Server validates credentials exist
- [x] Confirmation dialogs appear for mainnet + live

## Code Locations

| File | Lines | Description |
|------|-------|-------------|
| `templates/dashboard.html` | 424-441 | Environment/paper trading selects |
| `static/js/app.js` | 323-336 | environmentBadge() function |
| `static/js/app.js` | 814-857 | fillBotForm() updated |
| `static/js/app.js` | 859-894 | resetBotForm() updated |
| `static/js/app.js` | 948-1003 | saveBot() updated |
| `static/js/app.js` | 1112-1160 | switchBotEnvironment() function |
| `static/js/app.js` | 564-577 | Environment badge in bot table |

## Future Enhancements

### Optional UI Improvements

1. **Quick Environment Switch Button:**
   - Add button in bot table actions column
   - Click to toggle environment without editing full form
   - Example: `<button onclick="switchBotEnvironment('${bot.id}', 'mainnet', false)">Switch to Mainnet</button>`

2. **Bot Detail Modal Environment Section:**
   - Show current environment in bot detail modal
   - Add inline environment switcher
   - Display environment history (if tracked)

3. **Bulk Environment Operations:**
   - Select multiple bots
   - Switch all to testnet/mainnet at once
   - Useful for testing vs production transitions

4. **Environment Filter:**
   - Filter bot table by environment
   - Show only testnet bots or only mainnet bots
   - Useful for managing large bot fleets

5. **Visual Environment Indicator:**
   - Page-level indicator showing which environments are active
   - Count of bots per environment
   - Warning banner if any mainnet + live bots are running

## Notes

- All changes follow the "safe by default" principle
- No breaking changes to existing bot data structure
- Backwards compatible: bots without environment fields default to testnet + paper
- Client-side and server-side validation for safety
- Clear visual indicators prevent accidental mainnet usage
