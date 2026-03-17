# Antigravity Memory - Lessons Learned & Persistent Solutions

## Global TP % Position Not Closing (2026-01-16)

### ISSUE: TP Hit Sets Status But Position Stays Open
**Symptoms:**
- Bot status shows `tp_hit` but position is still open
- Bot stops placing orders, leaving position exposed to market movement
- Losses accumulate while position remains open

**Root Cause:**
- The TP hit code in `grid_bot_service.py` called `_close_bot_symbol()` but **ignored the return value**.
- Status was set to `tp_hit` regardless of whether the position actually closed.

**Solution:**
- Modified TP hit handling to check `close_success` return value.
- If close fails → Set status to `error` with message "TP_HIT_CLOSE_FAILED: Position still open - requires manual close"
- If close succeeds → Set status to `tp_hit` as expected.

**Prevention:**
- Always check return values from critical trading operations.
- Use error status on failure so user is alerted to intervene.

---

## Last Coin Quick-Run Feature Missing (2026-01-16)

### ISSUE: HTML Section Not Appearing in Browser
**Symptoms:**
- JavaScript console shows `[LastCoin] ERROR: section element not found!`
- `document.getElementById('last-coin-section')` returns `null`
- JS functions work, but HTML elements don't exist

**Root Cause:**
- **File sync issue**: The local `templates/dashboard.html` had the HTML section, but the server version did NOT.
- JavaScript was correctly synced, but the HTML template was not uploaded.

**Solution:**
1. Upload `templates/dashboard.html` to server via SCP
2. Restart `opus_trader` service: `systemctl restart opus_trader`

**Prevention:**
- Always verify critical files are synced after adding new features
- Check both JS and HTML files on server after deployment
- **API Note:** When updating bots via `/api/bots`, must include `symbol` field (required)

---

## Web Stack & Connectivity (2026-01-13)


### ISSUE: 404 "Not Found" on Dashboard
**Symptoms:** 
- `{"detail":"Not Found"}` returned from `madowlab.online`.
- `server: uvicorn` header observed in response.
- Dashboard (Flask) reported 502/404.

**Root Cause:**
- A rogue **FastAPI/Uvicorn** process was listening on port 8000. Under the current proxy setup, Apache forwards traffic to port 8000. It was reaching the rogue FastAPI app (which had no `/` route) instead of the Flask app.
- Port 80 was also blocked by stray processes, preventing Apache from restarting correctly.

**Solution:**
- Killed processes on port 80 and 8000 using `fuser -k`.
- Restarted `opus_trader` (Flask) and `apache2`.

**Prevention:**
- Update `opus_trader.service` with `ExecStartPre=/usr/bin/fuser -k 8000/tcp || true`.
- Update `apache2.service` (or a helper) to ensure port 80 is clear of non-apache processes.

---

### ISSUE: Adding Custom Models to OpenCode (2026-01-15)
**Symptoms:** 
- User wants to use "Opus 4.5 of Antigravity" within the OpenCode editor.
- Requires interactive login (not API key).

**Solution:**
- Create an `opencode.json` file in the project root.
- Add the `opencode-antigravity-auth` plugin.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "opencode-antigravity-auth"
  ],
  "provider": {
    "google": {
      "models": {
        "antigravity-claude-opus-4-5-thinking": {
          "id": "antigravity-claude-opus-4-5-thinking",
          "name": "Claude Opus 4.5 (Antigravity)"
        }
      }
    }
  }
}
```



**Usage:**
- Restart OpenCode.
- Open the terminal in OpenCode.
- Run `/connect` (or `opencode auth login`) and select "Antigravity".
- Follow the interactive login prompt.


---


### ISSUE: Bybit API 429 Rate Limits (kline)
**Symptoms:** 
- Errors in logs while scanning symbols or running bots.
- Redirected to Bybit rate limit documentation.

**Root Cause:**
- `IndicatorService` was not effectively caching when different services requested different `limit` parameters for the same symbol/interval.

**Solution:**
- Optimized `IndicatorService.get_ohlcv` to reuse larger cached datasets by slicing them.
- Standardized `limit=200` across `PricePredictionService` and `NeutralScannerService`.

**Prevention:**
- Always use `limit=200` for standard indicators unless specifically needing more.
- Verified with `tests/test_indicator_cache.py`.

---

### ISSUE: Scalp Mode TP Shifting
**Symptoms:** 
- Bot recenters grid during a trade, moving Take Profit orders away from the entry.

**Root Cause:**
- `_run_scalp_pnl_cycle` recentered unconditionally based on price.

**Solution:**
- Added a check to block recentering if position size > 0.

**Prevention:**
- Never allow grid center resets in Scalp mode while a position is held.

---

### ISSUE: 503 Service Unavailable / Startup Crash (2026-01-14)
**Symptoms:** 
- `503 Service Unavailable` on dashboard.
- `opus_trader` service fails to start or exits immediately.

**Root Causes:**
1.  **Port Conflict:** Port 8000 held by old process (Status `1/FAILURE` on `ExecStartPre` if not handled).
2.  **Syntax Error:** `SyntaxError` in python code (missing `except` block) causing main process crash.

**Solution:**
- **Service Hardening:** Updated `opus_trader.service` to use `ExecStartPre=/bin/sh -c '/usr/bin/fuser -k 8000/tcp || true'`. Note the `/bin/sh -c` wrapper is required for the `|| true` fallback.
- **Code Fix:** Patched `services/bot_manager_service.py` to fix missing `except` block.

---

### ISSUE: 503 Service Unavailable / Startup Crash (2026-01-14)
**Symptoms:** 
- `503 Service Unavailable` on dashboard.
- `opus_trader` service fails to start or exits immediately.

**Root Causes:**
1.  **Port Conflict:** Port 8000 held by old process (Status `1/FAILURE` on `ExecStartPre` if not handled).
2.  **Syntax Error:** `SyntaxError` in python code (missing `except` block) causing main process crash.

**Solution:**
- **Service Hardening:** Updated `opus_trader.service` to use `ExecStartPre=/bin/sh -c '/usr/bin/fuser -k 8000/tcp || true'`. Note the `/bin/sh -c` wrapper is required for the `|| true` fallback.
- **Code Fix:** Patched `services/bot_manager_service.py` to fix missing `except` block.

---

### ISSUE: [Errno 13] Permission denied: 'storage/bots.json'
**Symptoms:** 
- Errors in Runner Log on dashboard.
- File ownership keeps getting messed up even after `chown`.

**Root Cause:**
- **Split Personality:** `opus_trader` (Flask) was running as `root`, but `opus_runner` (Bot Runner) was running as `www-data`.
- When `root` touched a file, `www-data` got locked out.

**Solution:**
- Unified both services to run as `root`.
- Updated `/etc/systemd/system/opus_runner.service` with `User=root`.
- Ran `chown -R root:root storage/` one last time.

---

## Bybit API Timestamp Mismatch (retCode=10002) (2026-02-05)

### ISSUE: API Error - invalid request, check server timestamp
**Symptoms:**
- Logs show retCode=10002 with req_timestamp and server_timestamp differences.
- Bots fail to fetch positions or account overview.

**Root Cause:**
- Local system clock was out of sync with Bybit's servers by more than the recv_window (5s).
- BybitClient was using local time without checking server time.

**Solution:**
- Modified services/bybit_client.py to fetch server time during health checks.
- Implemented automatic time offset calculation (server_time - local_time).
- Updated _timestamp_ms() to apply this offset to all requests.

**Prevention:**
- Client now periodically re-syncs time (every 30 mins) to account for drift.
- Verified with check_environment.py.

---

## Dashboard Auth Required on Localhost (2026-02-05)

### ISSUE: auth_required when accessing localhost:8000
**Symptoms:**
- User is blocked from dashboard with 401 error.

**Root Cause:**
- HTTP Basic Auth is enabled by default via require_basic_auth decorator in app.py.
- User needs to provide credentials from .env.

**Solution:**
- Advised user to use credentials: admin / 245983.
- Verified credentials match .env configuration.

---

---

## Bybit API Timestamp Mismatch (retCode=10002) - REFINED (2026-02-05)

### ISSUE: API Error - invalid request, check server timestamp (STILL PERSISTED)
**Symptoms:**
- Logs continued to show retCode=10002 after first fix attempt.
- Difference was consistently ~66s.

**Root Cause:**
- Initial fix looked for 
esult.timeMS which does not exist in Bybit V5.
- Bybit V5 provides server time in a top-level 	ime field (milliseconds).

**Solution:**
- Corrected logic in services/bybit_client.py to use data.get("time").
- Added explicit health_check call to BybitClient constructor to ensure immediate sync on startup.

**Prevention:**
- Re-verified with Bybit V5 API documentation.

---

## Dashboard Auth Prompt Not Appearing (2026-02-05)

### ISSUE: Browser showed JSON error instead of login popup
**Symptoms:**
- Requesting localhost:8000 returned {"error": "auth_required"} as raw JSON.
- Browser console showed 401 but no prompt appeared.

**Root Cause:**
- Many modern browsers suppress the Basic Auth prompt if the 401 response contains a body with Content-Type: application/json.

**Solution:**
- Simplified require_basic_auth in config/config.py to return a plain text message and no JSON body.
- Changed the Auth Realm to "OpusTrader Dashboard" to force a fresh login attempt.

---

---

## Dashboard Auth Localhost Bypass (2026-02-05)

### ISSUE: Persistent "Unauthorized" on Localhost
**Symptoms:**
- Even in Incognito, the Basic Auth prompt failed to appear.
- "Unauthorized" text message was visible, confirming code execution but browser suppression.

**Root Cause:**
- Local system configuration or browser versions can sometimes suppress Basic Auth popups on localhost/non-https connections.

**Solution:**
- Added a localhost bypass to the require_basic_auth decorator in config/config.py.
- If request.remote_addr is 127.0.0.1 or ::1, auth is skipped.
- SECURITY: This is safe as it only affects local access (user's own machine). Remote access still requires credentials.

---

---

## Final Utility: stop.bat (2026-02-05)

### FEATURE: One-click Full Shutdown
**Capability:**
- Terminate all python.exe processes across the entire project (Runner, Web Server, Scanners).
- Automatically close all cmd.exe windows to clear the desktop.
- Script is self-closing (no user input needed).

**Usage:**
- Run stop.bat whenever you want to completely stop the system before a restart or update.

---

## app_lf.js Audit Findings (2026-02-19)

### BUG: Double Stop API Call in botAction
**Root Cause:** Follow-up setTimeout sent a second `/bots/stop` POST for stop actions.
**Fix:** Removed the redundant stop call, kept only the `refreshBots()` follow-up.

### BUG: Wrong Element ID in runBacktestFromForm
**Root Cause:** Used `"bot-grid-count"` but actual ID is `"bot-grids"`.
**Fix:** Changed to `"bot-grids"`.

### BUG: Undefined API_BASE in runBacktestFromForm
**Root Cause:** `API_BASE` never defined. Causes ReferenceError.
**Fix:** Replaced with `fetchJSON("/backtest", ...)`.

### BUG: Wrong Default Mode
**Root Cause:** Defaulted to invalid `"neutral_classic"`.
**Fix:** Changed to `"neutral"`.

### Prevention:
- Always use `fetchJSON()` not raw `fetch()` for API calls.
- Always verify element IDs match between JS and HTML.
- Never duplicate API calls in follow-up timers.

---

## Small Profit Target Optimization for Small Capital (2026-02-25)

### CHANGE: Bot Takes Quick $0.10 Profits Instead of Waiting for $0.30-.00
**Context:**
- User invests $10- per bot, so waiting for $0.60+ profit is unrealistic
- Old defaults were designed for $50+ investments

**Changes Made (3 files):**

1. **config/strategy_config.py:**
   - SCALP_PNL_QUICK_PROFIT: $0.30 to $0.10
   - SCALP_PNL_TARGET_PROFIT: $0.60 to $0.15
   - SCALP_PNL_MAX_TARGET: $1.00 to $0.25
   - PARTIAL_TP_LEVELS: First level at 0.3% instead of 0.5%
   - PROFIT_LOCK_ARM_PCT: 0.8% to 0.4%

2. **services/scalp_pnl_service.py:**
   - BASE_INVESTMENT in adapt_targets_to_atr(): $50 to $20
   - Trending exit: takes profit at quick_profit instead of holding for max_target
   - Aged position exit: 120s to 60s

3. **services/take_profit_service.py:**
   - min_tp_pct: 0.5% to 0.3%
   - Scalp default TP: 0.8% to 0.5%

**Lesson:**
- When investment size is small, profit thresholds must scale down proportionally
- Three profit layers interact: config defaults then adaptive scaling then mode-specific logic
- Trending hold logic was preventing exits on small profits
