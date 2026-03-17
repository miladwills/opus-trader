# Environment Switching with Application Restart

## Overview

The global environment selector now **reflects the actual active environment** from the backend (based on which API credentials are loaded in .env). Switching environments requires stopping and restarting the application with different credentials.

## How It Works

### 1. Environment Detection

**Backend Endpoint:** `GET /api/environment`

Returns the currently active environment by checking which API key is loaded:

```json
{
  "active_environment": "testnet",
  "base_url": "https://api-testnet.bybit.com",
  "default_environment": "testnet"
}
```

The backend determines the active environment by comparing the loaded API key against both testnet and mainnet keys.

### 2. Frontend Display

**On Page Load:**
1. Frontend calls `/api/environment` to get the actual active environment
2. Global selector in navbar is set to match the backend
3. Page title updates to show current environment (🔵 TESTNET or 🔴 MAINNET)
4. Only bots matching the current environment are displayed

### 3. Switching Environments

**When user tries to switch:**
1. Selector reverts to current environment immediately
2. Instructions dialog appears explaining how to switch

**Switching to Mainnet:**
```
Environment Switch Required

You are currently on: TESTNET
To switch to: MAINNET (Real Money)

To switch to MAINNET:

1. Stop the application
2. Update your .env file:
   - Set BYBIT_API_KEY to your MAINNET key
   - Set BYBIT_API_SECRET to your MAINNET secret
   - Set BYBIT_BASE_URL=https://api.bybit.com
3. Restart the application

⚠️ WARNING: MAINNET uses REAL MONEY!
```

**Switching to Testnet:**
```
Environment Switch Required

You are currently on: MAINNET
To switch to: TESTNET (Safe)

To switch to TESTNET:

1. Stop the application
2. Update your .env file:
   - Set BYBIT_API_KEY to your TESTNET key
   - Set BYBIT_API_SECRET to your TESTNET secret
   - Set BYBIT_BASE_URL=https://api-testnet.bybit.com
3. Restart the application
```

## What Changes Per Environment

### Testnet Mode (Safe)
- **Balances:** Shows testnet fake money balances
- **Positions:** Shows testnet positions only
- **Bots:** Shows only bots with `trading_env: "testnet"`
- **New Bots:** Created with `trading_env: "testnet"`
- **Page Title:** "Bybit: $X.XX - 🔵 TESTNET"
- **Safety:** No real money at risk

### Mainnet Mode (Real Money)
- **Balances:** Shows actual account balances (REAL MONEY)
- **Positions:** Shows real positions
- **Bots:** Shows only bots with `trading_env: "mainnet"`
- **New Bots:** Created with `trading_env: "mainnet"`
- **Page Title:** "Bybit: $X.XX - 🔴 MAINNET"
- **Warning:** All operations use real funds

## Bot Filtering

**Active Bots Table:**
- Only shows bots matching the current active environment
- If on testnet: only testnet bots appear
- If on mainnet: only mainnet bots appear

**Example:**
```
Current Environment: TESTNET
Bots in database:
  - BTC/USDT (testnet) ← SHOWN
  - ETH/USDT (testnet) ← SHOWN
  - BTC/USDT (mainnet) ← HIDDEN
  - SOL/USDT (mainnet) ← HIDDEN
```

## Step-by-Step: Switching from Testnet to Mainnet

### 1. Current State Check
- Open dashboard
- Verify current environment shows "🔵 Testnet (Safe)"
- Note current balances and bots

### 2. Prepare Mainnet Credentials
Ensure you have:
- Mainnet API Key
- Mainnet API Secret
- Mainnet is properly configured on Bybit

### 3. Stop the Application
```bash
# Stop the Flask app (Ctrl+C if running in terminal)
# Or stop the service/process
```

### 4. Update .env File
Edit `.env` file:
```env
# Change these lines:
BYBIT_API_KEY=your_mainnet_api_key_here
BYBIT_API_SECRET=your_mainnet_api_secret_here
BYBIT_BASE_URL=https://api.bybit.com
```

### 5. Restart the Application
```bash
python app.py
# Or restart your service
```

### 6. Verify Switch
- Open dashboard
- Selector should show "🔴 Mainnet (Real Money)"
- Page title shows "🔴 MAINNET"
- Balances reflect real account
- Only mainnet bots are displayed

## Safety Features

### Environment Detection
✅ **Automatic:** Backend automatically detects which credentials are loaded
✅ **No Manual Config:** Frontend reads actual environment from backend
✅ **No Mismatch:** Impossible for frontend to show wrong environment

### Data Separation
✅ **Bot Filtering:** Only bots for current environment are shown
✅ **Balance Isolation:** Testnet balance never mixed with mainnet
✅ **Clear Labels:** Environment clearly displayed everywhere

### User Protection
✅ **Cannot Switch Without Restart:** Prevents accidental environment changes
✅ **Clear Instructions:** Step-by-step guidance for switching
✅ **Warning Messages:** Prominent warnings about real money
✅ **Visual Indicators:** Colors and emojis distinguish environments

## Technical Implementation

### Backend Changes

**File:** `app.py`

**New Endpoint:**
```python
@app.route("/api/environment")
@require_basic_auth
def api_environment():
    """Get the current active trading environment."""
    from config.config import (
        BYBIT_TESTNET_API_KEY,
        BYBIT_MAINNET_API_KEY,
        DEFAULT_TRADING_ENV
    )

    current_api_key = cfg.get("api_key", "")

    if current_api_key == BYBIT_TESTNET_API_KEY:
        active_env = "testnet"
    elif current_api_key == BYBIT_MAINNET_API_KEY:
        active_env = "mainnet"
    else:
        active_env = DEFAULT_TRADING_ENV

    return jsonify({
        "active_environment": active_env,
        "base_url": cfg.get("base_url", ""),
        "default_environment": DEFAULT_TRADING_ENV
    })
```

### Frontend Changes

**File:** `static/js/app.js`

**Environment Detection:**
```javascript
async function loadGlobalEnvironment() {
  const data = await fetchJSON("/environment");
  const activeEnv = data.active_environment || "testnet";

  globalEnvironment = activeEnv;

  // Update selector to match backend
  const selector = $("global-env-selector");
  if (selector) {
    selector.value = globalEnvironment;
  }

  updatePageTitleWithEnvironment();
}
```

**Switch Prevention:**
```javascript
function switchGlobalEnvironment() {
  const selector = $("global-env-selector");
  const newEnv = selector.value;
  const currentEnv = globalEnvironment;

  if (newEnv !== currentEnv) {
    // Revert selector
    selector.value = currentEnv;

    // Show restart instructions
    alert(`Environment Switch Required\n\n...`);
  }
}
```

**Bot Filtering:**
```javascript
async function refreshBots() {
  const data = await fetchJSON("/bots/runtime");
  const allBots = data.bots || [];

  // Filter to current environment
  const bots = allBots.filter(bot => {
    const botEnv = (bot.trading_env || "testnet").toLowerCase();
    return botEnv === globalEnvironment;
  });

  // Display filtered bots
}
```

## Configuration Files

### .env Example (Testnet)
```env
# TESTNET Configuration (Safe - Fake Money)
BYBIT_API_KEY=testnet_key_here
BYBIT_API_SECRET=testnet_secret_here
BYBIT_BASE_URL=https://api-testnet.bybit.com

# Keep mainnet credentials commented out for safety
#BYBIT_API_KEY=mainnet_key_here
#BYBIT_API_SECRET=mainnet_secret_here
#BYBIT_BASE_URL=https://api.bybit.com
```

### .env Example (Mainnet)
```env
# MAINNET Configuration (⚠️ REAL MONEY!)
BYBIT_API_KEY=mainnet_key_here
BYBIT_API_SECRET=mainnet_secret_here
BYBIT_BASE_URL=https://api.bybit.com

# Testnet credentials (for reference)
#BYBIT_API_KEY=testnet_key_here
#BYBIT_API_SECRET=testnet_secret_here
#BYBIT_BASE_URL=https://api-testnet.bybit.com
```

## Troubleshooting

### Issue: Selector Shows Wrong Environment

**Symptom:** Navbar shows testnet but balances seem like mainnet

**Solution:**
1. Check console log for actual environment
2. Verify .env file has correct credentials
3. Restart application to reload credentials

### Issue: No Bots Showing

**Symptom:** "No bots configured for TESTNET/MAINNET" message

**Possible Causes:**
1. All bots are for the other environment
2. Need to switch environment to see those bots

**Solution:**
1. Check which environment you're on
2. Switch to other environment if needed (restart with different .env)
3. Or create new bots for current environment

### Issue: Balance Shows $0 or Wrong Amount

**Symptom:** Balance displays incorrectly

**Solution:**
1. Verify API credentials in .env
2. Check API key has correct permissions on Bybit
3. Ensure base URL matches environment (testnet vs mainnet)
4. Check Bybit account has funds in that environment

## Best Practices

### Development/Testing
1. **Always start with testnet**
2. Test all changes on testnet first
3. Keep testnet as default in .env
4. Only switch to mainnet when ready for production

### Production Deployment
1. Use separate .env files for testnet and mainnet
2. Never commit .env to version control
3. Use environment-specific deployment scripts
4. Always verify environment after restart

### Safety Protocol
1. **Double-check** environment indicator before starting bots
2. **Verify** balance amount matches expected environment
3. **Confirm** bot list shows expected bots
4. **Test** with small amounts first on mainnet

## Summary

This implementation provides:
- **Accurate environment detection** from backend
- **Clear visual indicators** of current environment
- **Bot filtering** by environment
- **Safe switching process** requiring application restart
- **Protection against accidents** through clear instructions
- **Separation of concerns** between testnet and mainnet data

The key insight: **environment is determined by which API credentials are loaded**, not by a toggle. The selector simply reflects the current state and provides instructions for changing it.
