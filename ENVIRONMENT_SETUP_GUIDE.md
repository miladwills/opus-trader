# Bybit Environment Setup Guide

## Overview

The Bybit Control Center now supports **dual trading environments**:

- **TESTNET** (default): Safe testing environment with fake money
- **MAINNET**: Live trading with real money ⚠️

Each bot can independently choose which environment to use, and you can switch between them without editing configuration files.

---

## Safety Features

### Default Configuration (Ultra-Safe)
- **Default environment**: `testnet` (fake money)
- **Default paper trading**: `True` (no real API calls)
- **Environment switching**: Blocked while bot is running
- **Credential validation**: Prevents switching to environments without valid API keys
- **Logging**: Clear warnings when using mainnet

### Risk Mitigation
1. **Testnet First**: All bots start on testnet by default
2. **Paper Trading Default**: Even on testnet, paper trading is ON by default
3. **Manual Opt-In**: Mainnet requires explicit credential configuration
4. **Runtime Safety**: Cannot switch environments while bot is active
5. **Audit Trail**: All environment switches are logged with warnings

---

## Initial Setup

### Step 1: Create .env File

```bash
# Copy the example file
cp .env.example .env
```

### Step 2: Configure Testnet Credentials (REQUIRED)

1. Sign up at [Bybit Testnet](https://testnet.bybit.com)
2. Create API key with **Trade + Read** permissions
3. Add to `.env`:

```bash
# Testnet (safe, fake money)
BYBIT_TESTNET_API_KEY=your_testnet_api_key_here
BYBIT_TESTNET_API_SECRET=your_testnet_api_secret_here
BYBIT_TESTNET_BASE_URL=https://api-testnet.bybit.com
```

### Step 3: (Optional) Configure Mainnet Credentials

⚠️ **ONLY after thorough testing on testnet!**

1. Sign up/login at [Bybit](https://www.bybit.com)
2. Create API key with:
   - **Trade + Read** permissions ONLY
   - **IP whitelist** restrictions (recommended)
   - **NO withdrawal permissions**
3. Add to `.env`:

```bash
# Mainnet (REAL MONEY - use with extreme caution!)
BYBIT_MAINNET_API_KEY=your_mainnet_api_key_here
BYBIT_MAINNET_API_SECRET=your_mainnet_api_secret_here
BYBIT_MAINNET_BASE_URL=https://api.bybit.com
```

### Step 4: Restart Application

```bash
# Stop the app if running
# Then restart to load new environment variables
python app.py
```

---

## Using Different Environments

### Default Behavior

When you create a new bot:
- `trading_env`: `"testnet"` (safe)
- `paper_trading`: `True` (no real orders)

### Creating a Bot on Testnet (Default)

```bash
POST /api/bots
{
  "symbol": "BTCUSDT",
  "lower_price": 40000,
  "upper_price": 45000,
  "mode": "neutral",
  "trading_env": "testnet",      # Optional (this is the default)
  "paper_trading": true           # Optional (this is the default)
}
```

### Creating a Bot on Mainnet

⚠️ **Use with extreme caution! This uses REAL MONEY!**

```bash
POST /api/bots
{
  "symbol": "BTCUSDT",
  "lower_price": 40000,
  "upper_price": 45000,
  "mode": "neutral",
  "trading_env": "mainnet",       # Explicit opt-in to real money
  "paper_trading": false          # Disable paper trading (live orders)
}
```

### Switching a Bot's Environment

You MUST stop the bot first:

```bash
# 1. Stop the bot
POST /api/bots/stop
{
  "id": "bot_id_here"
}

# 2. Switch environment
PATCH /api/bots/{bot_id}/environment
{
  "trading_env": "mainnet",       # or "testnet"
  "paper_trading": false          # optional
}

# 3. Start the bot (if desired)
POST /api/bots/start
{
  "id": "bot_id_here"
}
```

### Error Handling

The API will return clear errors:

```json
// Trying to switch while running
{
  "error": "Cannot switch environment while bot is running. Please stop the bot first."
}

// Missing credentials
{
  "error": "Mainnet credentials not configured. Set BYBIT_MAINNET_API_KEY and BYBIT_MAINNET_API_SECRET in environment variables. ⚠️ WARNING: Mainnet uses REAL MONEY!"
}

// Invalid environment
{
  "error": "trading_env must be 'testnet' or 'mainnet'"
}
```

---

## Frontend Integration (For UI Developers)

### Display Environment Badge

Show the bot's current environment prominently:

```html
<!-- Testnet badge (blue/green) -->
<span class="badge badge-info">ENV: TESTNET</span>

<!-- Mainnet badge (red/warning) -->
<span class="badge badge-danger">ENV: MAINNET ⚠️</span>
```

### Environment Selector

Add a toggle/dropdown in bot settings:

```javascript
// Example: Update environment
async function updateBotEnvironment(botId, newEnv) {
  try {
    const response = await fetch(`/api/bots/${botId}/environment`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Basic ' + btoa('admin:password')
      },
      body: JSON.stringify({
        trading_env: newEnv,  // "testnet" or "mainnet"
        paper_trading: newEnv === 'testnet'  // auto-enable paper trading on testnet
      })
    });

    if (!response.ok) {
      const error = await response.json();
      alert(error.error);
      return;
    }

    const data = await response.json();
    console.log('Environment updated:', data.bot);
  } catch (err) {
    console.error('Failed to update environment:', err);
  }
}
```

### Safety UX Recommendations

1. **Disable environment toggle while bot is RUNNING**
   - Show message: "Stop bot to change environment"

2. **Show confirmation dialog for mainnet**
   ```
   ⚠️ WARNING: Switching to MAINNET

   This bot will use REAL MONEY!

   Are you sure you want to continue?
   [Cancel] [Yes, I understand the risks]
   ```

3. **Visual indicators**
   - Testnet: Blue/Green color scheme
   - Mainnet: Red/Orange color scheme
   - Add warning icons ⚠️ for mainnet bots

---

## Logging and Monitoring

### Log Messages

The system logs all environment-related events:

```
# Bot creation
INFO: Bot saved: abc123 for BTCUSDT (profile=normal, auto_direction=False, range_mode=fixed, tp_pct=0.0150, trading_env=testnet, paper_trading=True)

# Mainnet warning on creation
WARNING: ⚠️ Bot abc123 configured for MAINNET environment - REAL MONEY at risk!

# Bot startup
INFO: Bot abc123 using BYBIT TESTNET environment (safe)

# Or for mainnet:
WARNING: 🚨 Bot abc123 starting on BYBIT MAINNET environment - REAL MONEY at risk! (paper_trading=False)

# Environment switch
WARNING: ⚠️ Bot abc123 environment switched to MAINNET (REAL MONEY!) - paper_trading=False
```

### What to Monitor

When using mainnet:

1. **Check logs for mainnet warnings** on startup
2. **Verify paper_trading status** (False = live orders)
3. **Monitor first 24-48 hours closely**
4. **Set up alerts** for unexpected behavior
5. **Start with minimal capital** (test with small amounts)

---

## Troubleshooting

### Bot won't start on mainnet

**Error**: `Mainnet credentials not configured`

**Solution**: Add mainnet API credentials to `.env`:
```bash
BYBIT_MAINNET_API_KEY=your_key
BYBIT_MAINNET_API_SECRET=your_secret
```

### Cannot switch environment

**Error**: `Cannot switch environment while bot is running`

**Solution**: Stop the bot first:
```bash
POST /api/bots/stop
{
  "id": "your_bot_id"
}
```

### Orders not executing on mainnet

**Check**:
1. Is `paper_trading` set to `False`?
2. Do you have sufficient funds in your Bybit account?
3. Check mainnet API key permissions (Trade + Read required)
4. Verify API key IP whitelist (if enabled)

### Testnet API errors

**Solution**: Testnet can be unstable. Common fixes:
1. Regenerate testnet API keys
2. Check [Bybit Testnet Status](https://status.bybit.com)
3. Temporarily use mainnet in paper trading mode

---

## Migration from Old Configuration

### If you had hardcoded credentials

Old `config/config.py`:
```python
BYBIT_API_KEY = "your_key"
BYBIT_API_SECRET = "your_secret"
BYBIT_BASE_URL = "https://api.bybit.com"
```

**Migration steps**:

1. Determine which environment your old credentials are for
   - `https://api.bybit.com` = mainnet
   - `https://api-testnet.bybit.com` = testnet

2. Move to `.env`:
   ```bash
   # If they were mainnet credentials:
   BYBIT_MAINNET_API_KEY=your_old_key
   BYBIT_MAINNET_API_SECRET=your_old_secret

   # If they were testnet credentials:
   BYBIT_TESTNET_API_KEY=your_old_key
   BYBIT_TESTNET_API_SECRET=your_old_secret
   ```

3. Remove hardcoded values from `config/config.py`
   - They will be read from `.env` automatically

4. Existing bots will default to testnet
   - Manually switch to mainnet if needed

---

## Security Best Practices

### Bybit API Key Setup

1. **Minimum permissions**: Trade + Read ONLY
2. **NO withdrawal permissions** (critical!)
3. **IP whitelist**: Restrict to your server IP
4. **Separate keys**: Use different keys for testnet/mainnet
5. **Regular rotation**: Change keys periodically

### Environment Variables

1. **Never commit `.env`**: Already in `.gitignore`
2. **Use `.env.example`**: Template without real credentials
3. **Secure file permissions**: `chmod 600 .env`
4. **Backup safely**: Encrypted backups only

### Mainnet Usage

1. **Test on testnet FIRST** (run for days/weeks)
2. **Start with tiny capital** (minimum viable amount)
3. **Use SAFE profile** initially
4. **Monitor closely** (first 24-48 hours)
5. **Set alerts** for unusual activity
6. **Have kill switch ready** (emergency stop button)

---

## Summary

### Files Changed
- `config/config.py`: Added environment support
- `.env.example`: New environment variable template
- `services/client_factory.py`: New file for creating environment-specific clients
- `services/bot_manager_service.py`: Added trading_env field handling
- `services/grid_bot_service.py`: Added per-bot environment client selection
- `app.py`: Added `/api/bots/{id}/environment` endpoint

### New Environment Variables
- `DEFAULT_TRADING_ENV`: Default environment (testnet)
- `BYBIT_TESTNET_API_KEY`: Testnet API key
- `BYBIT_TESTNET_API_SECRET`: Testnet API secret
- `BYBIT_TESTNET_BASE_URL`: Testnet API endpoint
- `BYBIT_MAINNET_API_KEY`: Mainnet API key
- `BYBIT_MAINNET_API_SECRET`: Mainnet API secret
- `BYBIT_MAINNET_BASE_URL`: Mainnet API endpoint

### New Bot Fields
- `trading_env`: "testnet" or "mainnet" (default: "testnet")
- `paper_trading`: True or False (default: True)

### Defaults Remain Safe
- ✅ Default environment: `testnet`
- ✅ Default paper trading: `True`
- ✅ No core trading logic modified
- ✅ Backwards compatible (existing bots default to testnet)

---

## Support

For issues or questions:
1. Check logs for error messages
2. Verify `.env` configuration
3. Test on testnet first
4. Review this guide
5. Contact support with log excerpts (redact API keys!)

**Remember**: When in doubt, use testnet! 🛡️
