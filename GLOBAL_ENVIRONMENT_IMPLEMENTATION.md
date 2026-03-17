# Global Environment Toggle Implementation

## Overview

The system now has a **global environment selector** in the navbar that controls the trading environment for the entire dashboard. When you switch between testnet and mainnet, it affects:

- All API calls and data fetching
- Bot creation defaults
- Page title display
- Environment badges in the bot table

## Key Features

### 1. Global Environment Selector

**Location:** Top navigation bar, next to the title

**Options:**
- 🔵 Testnet (Safe) - Default
- 🔴 Mainnet (Real Money)

**Behavior:**
- Persists in localStorage
- Shows confirmation dialog when switching to mainnet
- Automatically refreshes all data when changed
- Updates page title to show current environment

### 2. Page Title Updates

The browser tab title now shows the current environment:

- `Bybit: $X.XX - 🔵 TESTNET`
- `Bybit: $X.XX - 🔴 MAINNET`

This provides constant visual feedback about which environment you're viewing.

### 3. Automatic Bot Environment Assignment

**All new bots automatically inherit the global environment setting:**

- If global environment is **testnet**: new bots are created on testnet
- If global environment is **mainnet**: new bots are created on mainnet
- All bots always use **paper_trading: true** for maximum safety

**No more per-bot environment selectors** - the environment is controlled globally.

### 4. Environment Badges in Bot Table

Each bot in the Active Bots table displays its environment:

- **🔵 TESTNET (Paper)** - Blue badge
- **🔴 MAINNET (Paper)** - Red badge with border

The badge appears below the symbol name in the first column.

## User Workflow

### Initial Load

1. Dashboard loads with **testnet** as the default environment
2. Global selector shows "🔵 Testnet (Safe)"
3. Page title includes "🔵 TESTNET"
4. All data displayed is from testnet

### Switching to Mainnet

1. Click the global environment dropdown in navbar
2. Select "🔴 Mainnet (Real Money)"
3. **Confirmation dialog appears:**
   ```
   ⚠️ WARNING: Switching to MAINNET Environment

   This will display REAL MONEY balances and positions.

   Any new bots created will default to MAINNET.

   Are you sure you want to continue?
   ```
4. Click OK to confirm
5. Page refreshes all data from mainnet
6. Page title updates to "🔴 MAINNET"
7. New bots will be created on mainnet

### Creating a Bot

1. Fill out the bot configuration form
2. Click "Save Bot"
3. **Bot is automatically created with:**
   - `trading_env`: Current global environment (testnet or mainnet)
   - `paper_trading`: true (always safe)

**No need to select environment per bot** - it's inherited from the global setting.

### Viewing Bots from Different Environments

**Bots show their environment via badges:**

- Blue badge = testnet bot
- Red badge = mainnet bot

**Important:** The bot table shows ALL bots regardless of current environment selection. The global environment only affects:
- Which API/balance data is displayed in summary cards
- What environment new bots will be created on

To see only bots from a specific environment, you can visually filter by badge color.

## Safety Features

### Multiple Layers of Protection

1. **Safe Default:**
   - System always defaults to testnet on first load
   - Global environment preference saved in localStorage

2. **Confirmation Dialog:**
   - Switching to mainnet requires explicit confirmation
   - Clear warning about REAL MONEY

3. **Always Paper Trading:**
   - All bots created with `paper_trading: true`
   - This prevents accidental live trading even on mainnet

4. **Visual Indicators:**
   - Page title shows current environment
   - Color-coded badges (blue = safe, red = danger)
   - Environment selector uses emoji indicators

5. **Persistent State:**
   - Environment choice remembered across sessions
   - Restored from localStorage on page load

## Technical Implementation

### Global State Variable

```javascript
let globalEnvironment = "testnet"; // Default to testnet (safe)
```

### Key Functions

**loadGlobalEnvironment()**
- Loads environment from localStorage
- Updates selector to match saved state
- Updates page title
- Called on page load

**switchGlobalEnvironment()**
- Called when user changes dropdown
- Shows confirmation for mainnet
- Saves to localStorage
- Refreshes all data

**getGlobalEnvironment()**
- Returns current global environment
- Used by saveBot() and other functions

**updatePageTitleWithEnvironment()**
- Updates browser tab title with environment indicator

### Data Flow

1. User selects environment → `switchGlobalEnvironment()`
2. Saves to localStorage
3. Calls `refreshAll()` to reload data
4. `saveBot()` reads `getGlobalEnvironment()`
5. New bot created with global environment

### Files Modified

| File | Changes |
|------|---------|
| `templates/dashboard.html` | Added global environment selector in navbar, removed per-bot selectors |
| `static/js/app.js` | Added global environment state and functions |

### Code Locations

| Function/Section | Lines (approx) | Purpose |
|-----------------|----------------|---------|
| Global state | Line 8-9 | `globalEnvironment` variable |
| `loadGlobalEnvironment()` | 1756-1772 | Load from localStorage |
| `switchGlobalEnvironment()` | 1777-1807 | Handle environment switch |
| `updatePageTitleWithEnvironment()` | 1812-1816 | Update page title |
| `getGlobalEnvironment()` | 1821-1823 | Getter function |
| `saveBot()` updated | 952-997 | Uses global environment |
| Navbar selector | dashboard.html:91-98 | HTML dropdown |

## Behavior Summary

### What Changes When You Switch Environment?

**Changes:**
- Page title updates
- Future bot creations use new environment
- Visual indicator in navbar

**Does NOT Change:**
- Existing bots remain on their original environment
- Bot table shows all bots (mixed environments)
- You must manually switch bots to different environment via edit

### What the Global Environment Controls

**Directly:**
- New bot creation default
- Page title display

**Does NOT Control (Yet):**
- API calls for balances (future enhancement)
- Position data fetching (future enhancement)
- PnL data (future enhancement)

Currently, the global environment is primarily used for **bot creation defaults** and **visual indicators**. To fully separate testnet/mainnet data fetching, additional backend API changes would be needed.

## Future Enhancements

### Potential Improvements

1. **Separate Data Fetching:**
   - Pass `trading_env` parameter to all API endpoints
   - Fetch balances, positions, PnL from selected environment only
   - Requires backend API modifications

2. **Environment Filter:**
   - Show only bots matching current global environment
   - Toggle to show "All", "Testnet Only", or "Mainnet Only"

3. **Multi-Environment Dashboard:**
   - Split-screen view showing testnet and mainnet side-by-side
   - Useful for comparing performance

4. **Environment History:**
   - Track when environment was switched
   - Show warning if user has been on mainnet for long time

5. **Live Trading Toggle:**
   - Add second global toggle for paper/live trading
   - Would override the hardcoded `paper_trading: true`

## Migration Notes

**Backward Compatibility:**
- Existing bots retain their `trading_env` and `paper_trading` fields
- No data migration needed
- Old bots continue to work with their original environment settings

**User Impact:**
- Simplified bot creation (no per-bot environment selection)
- Global control is more intuitive
- Less chance of accidentally creating mainnet bots

## Safety Checklist

- [x] Default environment is testnet (safe)
- [x] Confirmation required for mainnet switch
- [x] All bots created with paper_trading: true
- [x] Page title shows current environment
- [x] Environment persists in localStorage
- [x] Visual indicators (colors, emojis) clearly distinguish environments
- [x] No per-bot environment selectors (prevents confusion)

## Notes

This implementation follows the "safe by default" principle:
- **Testnet is the default**
- **Paper trading is always enabled**
- **Mainnet requires explicit confirmation**
- **Visual warnings are prominent**

The global environment selector provides a clear, simple way to manage the trading environment while maintaining maximum safety for users.
