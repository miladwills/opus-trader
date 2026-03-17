# Opus Trader Monitor Report

**Monitor started:** 2026-03-16 13:04 CET
**Last updated:** 2026-03-16 13:09 CET
**Update #:** 1 (Session restart observed at 13:07:47 CET — new runner PID 1057015)
**Next update:** ~13:14 CET

---

## Current Health Snapshot

| Component | Status | Detail |
|-----------|--------|--------|
| opus_trader (Flask) | RUNNING | PID 1057001 (restarted 13:07:47 CET) |
| opus_runner | RUNNING | PID 1057015 (restarted 13:07:47 CET) |
| Public WebSocket | **FRESH** | pub reconnect_epoch=1 (fresh since restart), ETHUSDT+BTCUSDT subscribed |
| Private WebSocket | **FRESH** | priv reconnect_epoch=1, position age=5.2s (borderline), order age=1.7s |
| Account Equity | **$32.89** | Available: $13.39 |
| Daily PnL | **-$3.00** | 30W / 29L (improved from -$3.94 at 11:13 CET) |
| Daily Loss % | **8.36%** | Kill switch: OFF |
| Open Positions | **1** | ETHUSDT 0.03 ETH Long @ 7.0x |
| Active Bots | **1** | ETHUSDT e10b5e1d — running, pos=0.03 ETH |
| Bots in ERROR | **0** | SUIUSDT + PUMPFUNUSDT reset to stopped by operator |
| Divergence Guard | **ACTIVE** | ETHUSDT opening orders blocked — diverged post-restart (expected) |
| BTC Corr Filter | **HEAVY** | corr=0.98 > 0.60, BTC ADX=27.2 — blocking 25+ symbols in app.log |
| Dashboard Timeouts | **ONGOING** | 4-5/min in app.log (bots_runtime, 1.5s threshold) |

---

## New Findings Since Last Update

**Prior session ended 11:13 CET. This session starts 13:04 CET (~2h gap).**

### Summary of What Changed in the Gap

- Services were restarted at **11:00:05 CET** (prior runner, PID 1019540, started there)
- TAOUSDT bot eb63cde0 continued to cycle until ~11:56 CET with AMBIGUOUS ws_timeout warnings (last log: 11:56:13 CET)
- SUIUSDT 8580f06d and PUMPFUNUSDT 6055cb3b remained in ERROR state through 11:55:49 CET
- **Operator intervened**: reset all three bots to stopped (no more error logs after 11:56)
- Services restarted again at **13:07:47 CET** (new PID 1057015)
- New ETHUSDT bot e10b5e1d was started at 13:01:59 CET (6 min before latest restart)
- Post-restart, ETHUSDT bot has position 0.03 ETH; divergence guard is active

### ETHUSDT Bot Post-Restart Divergence Guard (Active)

- Bot restarted with existing exchange state (0.03 ETH position + live orders)
- Startup reconciliation correctly detected divergence
- "Exchange recheck still diverged — keeping blocker active (flat=False orders_cleared=False)" at 13:08:41
- New opening orders blocked; position is protected by existing orders
- **Expected to self-resolve** as reconciliation completes; monitoring for persistence

### BTC Correlation Filter Log Flood (NEW)

- app.log flooded with ~2 BTC-blocked messages per second for 25+ symbols
- Pattern: `🚫 XXUSDT blocked by BTC correlation filter: corr=0.98 > 0.60, BTC ADX=27.2 >= 25.0`
- Active for all Auto-Pilot universe symbols — this is expected behavior during BTC trend
- However the LOG RATE is severe: ~25 symbols × every ~60s = drowning out real errors
- Similar noise pattern to the old entry gate spam (MON-006/FIX-005)

### TAOUSDT MON-014 Resolution (bot stopped)

- TAOUSDT bot eb63cde0 continued hitting ws_timeout AMBIGUOUS after prev session ended
- Last AMBIGUOUS at 11:56:13 CET — bot then apparently stopped by operator
- MON-014 (infinite paralysis from unresolved ambiguous follow-up) **incident ended**
- **Code bug still latent** — any bot hitting ws_timeout on close will hit same issue

### WS Reliability Pattern

- Runner PID 1019540 (11:00-13:07 CET) reached public_reconnect_epoch=42 in ~2h
- Current reconnect_epoch=1 after 13:07 restart (fresh)
- At prior rate (~20 reconnects/hour), expect ~80 by end of today's 4h window
- Each reconnect was handled cleanly by FIX-003 but WS connection quality is poor

---

## Repeated Patterns

| Pattern | Frequency | Since |
|---------|-----------|-------|
| BTC correlation filter blocked | ~2/sec (25+ symbols) | 13:01 CET |
| Dashboard snapshot timeout (bots_runtime, 1.5s) | 4-5/min | 13:01 CET |
| Bot storage cache_lock timeout | ~2/5min | 09:50 CET |
| ETHUSDT Strong trend warning (ADX_15m=36.4, ADX_1h=54.5) | Every cycle | 13:02 CET |
| ETHUSDT ADX momentum throttle | Every cycle | 13:07 CET |
| Public WS ping/pong timeout | ~20/hour | All session |

---

## Highest-Risk Open Issues

| # | Severity | Issue | Status | Trend |
|---|----------|-------|--------|-------|
| MON-014 | HIGH | Ambiguous follow-up never resolves → bot paralysis (code bug) | OPEN (latent) | Incident ended, code not fixed |
| MON-015 | HIGH | ACTIVE_POSITION_OWNER_STATUSES excludes error — unpatched in code | OPEN | Unchanged |
| MON-005 | MEDIUM | Dashboard snapshot timeouts (1.5s, 4-5/min) | OPEN | Ongoing |
| MON-017 | MEDIUM | Public WS drops ~20/hour (reconnect_epoch=42 in prior 2h) | NEW | Ongoing |
| MON-016 | LOW | BTC correlation filter log flood — 25+ symbols ~2/sec in app.log | NEW | Ongoing |
| MON-018 | LOW | ETHUSDT divergence guard active post-restart (expected to resolve) | NEW | Monitoring |
| MON-011 | LOW | Cache_lock timeouts (204 total in runner.log, ~2/5min now) | OPEN | Improved |
| MON-012 | LOW | PUMPFUNUSDT ambiguous still_unresolved (truth_check_expired, bot stopped) | OPEN | Stale |
| MON-008 | LOW | Phases 3-7 unreviewed in REVIEW_LOG.md | OPEN | Unchanged |

---

## Issues Resolved Since Last Session

| # | Severity | Resolution |
|---|----------|-----------|
| MON-001 | CRITICAL | Orphaned SUIUSDT position — FIX-002 deployed, operator closed, bot reset |
| MON-002 | CRITICAL | WS dead/degraded — FIX-003 deployed, WS fresh |
| MON-003 | HIGH | SUIUSDT bot stuck in error — operator reset to stopped |
| MON-004 | HIGH | Position leverage/margin risk — position closed by operator |
| MON-009 | LOW | Entry gate 42.0 boundary — no evidence in current logs, closed |
| MON-010 | HIGH | Systemic ws_timeout CLOSE_FAILED — FIX-001 deployed, 0 new CLOSE_FAILED in active session |

---

## Issues Handed to Fix Agent

Key remaining code-level issues requiring Fix Agent attention (in priority order):

1. **MON-014**: Ambiguous follow-up never auto-resolves → running bot can be permanently paralyzed. Bounded time-out + exchange verification on ESCALATION CRITICAL needed.
2. **MON-015**: ACTIVE_POSITION_OWNER_STATUSES in bot_status_service.py:41 excludes error/risk_stopped/stop_cleanup_pending — same pattern as FIX-002 but different file, not patched.
3. **MON-012**: PUMPFUNUSDT ambiguous follow-up with truth_check_expired=true — stale state in a stopped bot, operator visibility concern.

---

## Questions Still Unproven

1. Will ETHUSDT divergence guard self-resolve in next 1-2 cycles? (monitoring)
2. Is PUMPFUNUSDT ambiguous follow-up (truth_check_expired) visible to operator in dashboard?
3. What triggered the 13:07:47 service restart? (no log evidence yet)
4. Why does BTC ADX filter generate 2 messages per symbol (double-logged)?
5. Will ADX momentum throttle allow ETHUSDT to accumulate position as trend continues?

---

## Fix Agent Notes

**From previous session** (session report 09:32-10:15 UTC):
- FIX-001 through FIX-005 deployed, all gate-approved APPROVE_FOR_HUMAN_REVIEW
- 1054 tests passing, 0 failures
- Production validation: FIX-001 confirmed working (H1+FIX-001 APPROVE_FOR_STAGED_PRODUCTION)
- Remaining fix scope: MON-014 (ambiguous resolution), MON-015 (status filter gap in bot_status_service)

## Promotion Gate Notes

**Gate session:** 2026-03-16 11:20 CET (Opus 4.6 Max)
**Reviewed by:** Promotion Gate Agent
**Tests at review time:** 1056 passed, 0 failures

### Formal Verdicts — Deployed Fixes (FIX-001 through FIX-005)

| Fix | Issue | Risk | Verdict | Evidence |
|-----|-------|------|---------|----------|
| H1+FIX-001 | MON-010 | C | **APPROVE_FOR_STAGED_PRODUCTION_AFTER_HUMAN_APPROVAL** | 117+ AMBIGUOUS survived, 0 new CLOSE_FAILED in production |
| FIX-002 | MON-001 | B | APPROVE_FOR_HUMAN_REVIEW | LIVE_POSITION_OWNER_STATUSES verified in code, no new attribution gaps |
| FIX-003 | MON-002 | B | APPROVE_FOR_HUMAN_REVIEW | Public WS consistently fresh post-restart |
| FIX-004 | MON-009 | A | APPROVE_FOR_HUMAN_REVIEW | Display precision fix, tests pass |
| FIX-005 | MON-006 | A | APPROVE_FOR_HUMAN_REVIEW | Log spam eliminated, tests pass |
| FIX-001 (prevention) | MON-003 | C | NEEDS_MORE_VALIDATION | Prevents error entry but no recovery path; MON-014 shows _block_opening_orders gap |

### Blocked Promotions

| Item | Risk | Verdict | Reason |
|------|------|---------|--------|
| Pullback Re-Entry (Feature #35) | C | NEEDS_MORE_VALIDATION | Enabled LIVE with entry gate bypasses, zero shadow evidence |
| Phase 7 advisory rollout | C | NEEDS_MORE_VALIDATION | No formal review |

### Critical Code Gaps Found During Review

**1. MON-014 — _block_opening_orders has NO bounded clearance (CRITICAL)**

Root cause confirmed via code tracing:
- 6 ambiguous handlers set `bot["_block_opening_orders"] = True` (lines 20353, 20526, 21055, 21829, 23215, 24139)
- Ambiguous follow-up resolution (line 6976-6978) does NOT clear the flag
- `_clear_opening_block_flags` (line 9526) does NOT include `_block_opening_orders`
- Cycle-start clearance (line 12846) only clears if `_upnl_stoploss_reason` is also set
- No-position clearance (line 13182) only clears if position is gone
- **Result:** Bot stays "running" but places zero orders indefinitely when position exists and close was ambiguous

**Fix needed:** When `ambiguous_execution_follow_up` resolves (line 6976), also clear `_block_opening_orders`. Add bounded timeout (e.g., 300s + exchange verification).

**2. MON-015 — ACTIVE_POSITION_OWNER_STATUSES not patched (HIGH)**

- `bot_status_service.py:41` has separate set with 13 references
- FIX-002 patched LIVE_POSITION_OWNER_STATUSES but missed this one
- Affects open order queries, runtime source classification, readiness evaluation
- CAUTION: Not all 13 usages may need expansion — per-reference analysis required

**3. MON-013 — _cancel_orders_on_error doesn't zero internal counters (MEDIUM)**

- `runner.py:352-378` cancels exchange orders but doesn't zero `open_order_count`, `entry_orders_open`, `exit_orders_open`
- Class A fix (display truthfulness), low risk

### Unreviewd Post-Restart Code (WARNING)

**10 files modified after the 09:50 restart** — NOT currently running, NOT gate-reviewed:

| File | Modified | Size | Category |
|------|----------|------|----------|
| runtime_state_integrity_watchdog_service.py | 13:06 | 1048 lines (NEW) | Dashboard truth arbitration |
| test_runtime_state_integrity_watchdog_service.py | 13:06 | 305 lines (NEW) | Tests for new service |
| app.py | 09:58 | Wires in new service | App integration |
| config/strategy_config.py | 10:25 | Unknown changes | Configuration |
| services/watchdog_hub_service.py | 10:26 | Unknown changes | Watchdog |
| services/watchdog_diagnostics_service.py | 10:26 | Unknown changes | Watchdog |
| runner.py | 10:32 | Unknown changes | Runtime |
| services/guardian_service.py | 10:50 | Unknown changes | Watchdog |
| services/grid_bot_service.py | 10:50 | Unknown changes | Execution (Class C) |
| services/bybit_client.py | 10:59 | Unknown changes | Execution (Class C) |

**WARNING:** The new RuntimeStateIntegrityWatchdogService (1048 lines) is a substantial new service for dashboard runtime truth arbitration. It is wired into app.py. The grid_bot_service.py and bybit_client.py modifications are Class C files. **These changes need gate review before the next service restart deploys them.**

### Recommendations for Human Reviewer

1. **APPROVE H1+FIX-001** for staged production — production-proven with 117+ live events. This is the highest-priority safety fix.
2. **APPROVE FIX-002/003/004/005** — all bounded, correct, low regression risk.
3. **PRIORITIZE MON-014 fix** — the _block_opening_orders clearance gap will paralyze any bot that hits ws_timeout on a close with an existing position. This is latent and will recur.
4. **REVIEW the 10 post-restart file modifications** before any restart. Especially: new RuntimeStateIntegrityWatchdogService (1048 lines), grid_bot_service.py changes, bybit_client.py changes.
5. **DISABLE Pullback Re-Entry** (`PULLBACK_REENTRY_ENABLED = False`) until shadow evidence is gathered.
6. **Review bot max_loss settings** before H4 stop_loss fix takes effect — leverage-adjusted stops will trigger much closer to entry at high leverage.

---

## Session Heartbeat Log

### 13:09 CET — Update #1 (Session Start)

**Context:** Starting fresh 4h session. Previous session (09:31-11:13 CET) ended with MON-014 TAOUSDT paralysis active. Between sessions: operator reset error bots, services restarted twice (11:00, 13:07).

**Key findings:**
- 0 open positions at this session start (ETHUSDT 0.03 ETH just acquired in first 6min)
- All critical issues from prior session resolved (MON-001/002/003/004)
- System generally stable with known latent issues (MON-014 code, MON-015 code)
- Services just restarted 3 min ago; ETHUSDT divergence guard expected to resolve
- WS reliability ongoing concern (42 reconnects in prior 2h session)

**Active monitoring:** ETHUSDT 0.03 ETH long position, 7.0x leverage, strong ADX trend environment

**Counters:** AMBIGUOUS=0 (fresh restart), cache_lock=204 cumulative, WS drops=42 prior session

---

## Fix Agent Notes — Session 2 (2026-03-16 ~11:15–11:30 CET)

**Session:** Fix Agent Session 2, started after previous session (FIX-001–005) completed.

### Issues Investigated

| Issue | Severity | Class | Status |
|-------|----------|-------|--------|
| MON-014 | Critical | **C** | **FIXED** |
| MON-015 | Critical | B | **FIXED** |
| MON-013 | High | A/B | **FIXED** |

### Fixes Applied

#### FIX-006: MON-014 — Ambiguous close block never clears (bot paralysis)
**File:** `services/grid_bot_service.py` (3 changes)
1. `_classify_ambiguous_execution_follow_up`: reduce_only with position present now returns `no_pending_close_order/pending=False` instead of `still_unresolved/pending=True`. Market close orders execute immediately — if they're not in open orders after 10s, outcome is determined.
2. `reconcile_bots_exchange_truth`: clears `_block_opening_orders` when ambiguous marker resolves (if not held by UPnL SL).
3. `_get_exchange_truth_opening_blocker`: condition simplified to `if marker.get("pending")` only — non-pending markers (expired or resolved) no longer block indefinitely.
**⚠️ CLASS C — requires Gate review and replay/shadow evidence before production.**

#### FIX-007: MON-015 — ACTIVE_POSITION_OWNER_STATUSES missing error in bot_status_service.py
**File:** `services/bot_status_service.py` (2 changes)
- Added `LIVE_ORDER_OWNER_STATUSES` constant (extends ACTIVE set with error/risk_stopped/stop_cleanup_pending)
- `_build_live_open_orders_by_symbol` now uses LIVE_ORDER_OWNER_STATUSES for open order queries
- `ACTIVE_POSITION_OWNER_STATUSES` left unchanged (readiness/preview semantics unaffected)
**CLASS B — dashboard truthfulness.**

#### FIX-008: MON-013 — Stale order counters for error-state bots
**File:** `runner.py` (1 change)
- Added counter zeroing at end of `_cancel_orders_on_error`: zeros `open_order_count`, `entry_orders_open`, `exit_orders_open` unconditionally after cancel attempt. Reconciliation confirms actual exchange state on next pass.
**CLASS A/B — display truthfulness.**

### Test Results
- **1057 passed, 0 failures** (previous session: 1054 passed)
- Focused: exchange_reconciliation_phase3 (5), entry_gate_service (17), bot_status_opening_cap (5) — all pass

### Remaining Queue Items (auto_fix_allowed=true, open)
- MON-012 (medium): Ambiguous escalation not resolving for error bots — partially addressed by FIX-006
- MON-003 (high): CLOSE_FAILED has no auto-recovery path — FIX-001 prevents entry; recovery still manual
- MON-010 (high): WS reliability systemic issue — operational, not a code fix
- MON-011 (medium): cache_lock contention — low priority, ongoing

### Rollback Instructions
```
cp services/grid_bot_service.py.bak_MON014 services/grid_bot_service.py
cp services/bot_status_service.py.bak_MON015 services/bot_status_service.py
cp runner.py.bak_MON013 runner.py
```
