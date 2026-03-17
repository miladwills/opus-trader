# Quick Start: Environment Switching

## Current Setup

Your `.env` file should have **both** testnet and mainnet credentials:

```env
# TESTNET (Safe - Fake Money)
BYBIT_TESTNET_API_KEY=your_testnet_key
BYBIT_TESTNET_API_SECRET=your_testnet_secret
BYBIT_TESTNET_BASE_URL=https://api-testnet.bybit.com

# MAINNET (Real Money - ⚠️ WARNING!)
BYBIT_MAINNET_API_KEY=your_mainnet_key
BYBIT_MAINNET_API_SECRET=your_mainnet_secret
BYBIT_MAINNET_BASE_URL=https://api.bybit.com

# Which environment to use (testnet or mainnet)
BYBIT_ACTIVE_ENV=testnet

# Auth
BASIC_AUTH_USER=admin
BASIC_AUTH_PASS=112233
```

## How to Switch Environments

### Method 1: Edit .env (Recommended)

**To use TESTNET (Safe):**
```env
BYBIT_ACTIVE_ENV=testnet
```

**To use MAINNET (Real Money):**
```env
BYBIT_ACTIVE_ENV=mainnet
```

Then restart the app.

### Method 2: Auto-Detection (Fallback)

If `BYBIT_ACTIVE_ENV` is not set, the system will:
1. **Prefer testnet** if testnet credentials exist
2. Fall back to mainnet only if testnet not configured

## Step-by-Step: First Time Setup

### 1. Get Your API Keys

**Testnet:**
- Go to: https://testnet.bybit.com
- Create account (free, fake money)
- API Management → Create API Key
- Save the key and secret

**Mainnet (Optional):**
- Go to: https://www.bybit.com
- Your real account
- API Management → Create API Key
- ⚠️ **Only do this when ready for real trading!**

### 2. Update .env File

Edit `C:\Users\Coding4\Desktop\Scalping\opus_trader\.env`:

```env
# TESTNET credentials (Start here!)
BYBIT_TESTNET_API_KEY=paste_your_testnet_key_here
BYBIT_TESTNET_API_SECRET=paste_your_testnet_secret_here
BYBIT_TESTNET_BASE_URL=https://api-testnet.bybit.com

# MAINNET credentials (Optional - for later)
BYBIT_MAINNET_API_KEY=leave_empty_for_now
BYBIT_MAINNET_API_SECRET=leave_empty_for_now
BYBIT_MAINNET_BASE_URL=https://api.bybit.com

# Use testnet by default
BYBIT_ACTIVE_ENV=testnet
```

### 3. Start/Restart the Application

```bash
cd C:\Users\Coding4\Desktop\Scalping\opus_trader
python app.py
```

### 4. Verify Environment

Open dashboard:
- Check navbar selector shows "🔵 Testnet (Safe)"
- Check page title includes "🔵 TESTNET"
- Check balance shows testnet funds
- Console should log: `✓ Active environment: testnet`

## Switching Between Environments

### Switch to Testnet

1. Stop the app (Ctrl+C)
2. Edit `.env`: `BYBIT_ACTIVE_ENV=testnet`
3. Restart: `python app.py`
4. Verify: Navbar shows 🔵 Testnet

### Switch to Mainnet

1. Stop the app (Ctrl+C)
2. Edit `.env`: `BYBIT_ACTIVE_ENV=mainnet`
3. Restart: `python app.py`
4. Verify: Navbar shows 🔴 Mainnet
5. ⚠️ **Double-check balance is real account**

## What Shows in Each Environment

### Testnet Mode
- Balance: Testnet fake money
- Positions: Testnet positions
- Bots shown: Only bots with `trading_env: "testnet"`
- New bots: Created as testnet bots
- Page title: "Bybit: $X.XX - 🔵 TESTNET"

### Mainnet Mode
- Balance: **Real account balance**
- Positions: **Real positions**
- Bots shown: Only bots with `trading_env: "mainnet"`
- New bots: Created as mainnet bots
- Page title: "Bybit: $X.XX - 🔴 MAINNET"

## Troubleshooting

### Problem: Shows mainnet but I want testnet

**Solution:**
1. Check `.env` file: `BYBIT_ACTIVE_ENV=testnet`
2. Verify testnet credentials are set
3. Restart the app
4. Check browser console: Should log `✓ Active environment: testnet`

### Problem: No bots appearing

**Cause:** Bots are for different environment than currently active

**Solution:**
1. Check which environment is active (navbar)
2. Your bots might be for the other environment
3. Switch environment to see them, OR
4. Create new bots for current environment

### Problem: Balance shows $0

**Possible causes:**
1. Testnet account has no fake funds (get some from testnet faucet)
2. Wrong API key/secret
3. API key doesn't have required permissions

**Solution:**
1. Verify credentials in `.env`
2. Check Bybit API key permissions
3. For testnet: Get test funds from Bybit testnet

### Problem: Can't tell which environment is active

**Check multiple indicators:**
1. Navbar selector (🔵 = testnet, 🔴 = mainnet)
2. Page title (includes environment)
3. Browser console log on page load
4. Balance amount (testnet usually has round numbers like $100,000)

## Best Practices

### For Development/Testing
1. ✅ **Always start with testnet**
2. ✅ Keep `BYBIT_ACTIVE_ENV=testnet` in .env
3. ✅ Test all strategies on testnet first
4. ✅ Only switch to mainnet when strategy is proven

### For Production
1. ⚠️ **Only use mainnet when ready**
2. ⚠️ Start with small amounts
3. ⚠️ Double-check environment before starting bots
4. ⚠️ Monitor closely for first few trades

### Safety Checklist
Before switching to mainnet:
- [ ] Strategy tested on testnet for at least 1 week
- [ ] Understand all risk parameters
- [ ] Have stop-loss configured
- [ ] Start with minimum investment
- [ ] Monitor first trades closely
- [ ] Have mainnet API key permissions set correctly

## Quick Reference

| Action | Command/Setting |
|--------|----------------|
| Use testnet | `BYBIT_ACTIVE_ENV=testnet` |
| Use mainnet | `BYBIT_ACTIVE_ENV=mainnet` |
| Check environment | Look at navbar (🔵 or 🔴) |
| Restart app | `Ctrl+C` then `python app.py` |
| View logs | Check console output |

## Important Notes

- **Environment is set at startup** - requires app restart to change
- **Navbar selector shows current environment** - trying to switch shows instructions
- **Bots are filtered by environment** - only see bots for active environment
- **All bots use paper_trading=true** - for extra safety even on mainnet
- **Testnet is default** - if both credentials exist, testnet is preferred
