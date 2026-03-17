# Development Ideas — Evaluation Dashboard

**Evaluator Agent:** Active since 2026-03-16
**Last evaluation pass:** 2026-03-16T14:55Z
**Total ideas reviewed:** 25 / 25
**Scout batches received:** 3 (18 initial + 4 stream/guardian + 3 config/backtest)

---

## Current Queue Status

| Metric | Count |
|--------|-------|
| Total ideas received | 27 |
| **APPROVED HIGH** | **5** |
| APPROVED MEDIUM | 9 |
| APPROVED LOW | 3 |
| DEFERRED | 4 |
| REJECTED | 2 |
| REDUNDANT | 1 |
| FUTURE ROADMAP | 1 |
| NEEDS MORE EVIDENCE | 2 |

---

## Approved Ideas by Priority

### HIGH PRIORITY — Pursue Now (5 ideas)

| Rank | ID | Title | Value | Cmplx | Risk | Shape | Files Touched |
|------|----|-------|-------|-------|------|-------|---------------|
| 1 | SCOUT-020 | Stream freshness clock fix | 8 | 1 | 1 | small_patch | bybit_stream_service |
| 2 | SCOUT-023 | TP% profitability validation gate | 8 | 2 | 1 | small_patch | bot_manager_service, strategy_config |
| 3 | SCOUT-019 | Emergency exit partial fill retry | 8 | 4 | 2 | medium_feature | neutral_loss_prevention, guardian |
| 4 | SCOUT-001 | Batch order refill (neutral_classic only) | 7 | 3 | 2 | medium_feature | grid_bot_service, neutral_grid_service |
| 5 | SCOUT-003 | Funding fees in daily loss calc | 7 | 3 | 3 | small_patch | risk_manager, pnl_service |

**Post-verification corrections:**
- **SCOUT-009 DOWNGRADED to MEDIUM.** Fee guard IS active (FEE_AWARE_MIN_STEP_ENABLED=True). Step is expanded to 0.26% — fills ARE profitable. Issue is optimization (reduce levels vs expand step), not systematic loss.
- **SCOUT-001 NARROWED.** Serial refill only affects neutral_classic_bybit mode. Other modes already use `_submit_batch_orders()`.

**Recommended implementation order:**

1. **SCOUT-020** (stream freshness) — Near-zero risk correctness bug. Move `_note_topic_message()` after handler. Single file touch.

2. **SCOUT-023** (TP% gate) — Block bot creation/preset save if `tp_pct < min_profitable_tp_pct`. Must verify whether tp_pct is price-based or investment-based (leverage matters).

3. **SCOUT-019** (partial fill retry) — Safety-critical. Use async next-cycle retry (not 500ms sync loop). Verify position via exchange, not cache. Fix guardian flag-clearing.

4. **SCOUT-001** (batch refill for neutral_classic_bybit) — Design batch-aware router path first. Only affects neutral_classic mode.

5. **SCOUT-003** (funding in loss) — Verified: known_funding_total tracked but never used in risk formula. Must verify whether Bybit equity includes settled funding.

### MEDIUM PRIORITY — Pursue Soon (8 ideas)

| Rank | ID | Title | Value | Cmplx | Risk | Shape |
|------|----|-------|-------|-------|------|-------|
| 6 | SCOUT-009 | Fee-aware grid: reduce levels vs expand step | 6 | 3 | 2 | small_patch |
| 7 | SCOUT-008 | Entry gate: spread width check | 7 | 4 | 2 | small_patch |
| 8 | SCOUT-021 | Neutral inventory imbalance detection | 7 | 4 | 3 | small_patch |
| 9 | SCOUT-011 | Quality score to position sizing | 6 | 3 | 2 | small_patch |
| 10 | SCOUT-013 | Stuck bot detection watchdog | 6 | 3 | 1 | small_patch |
| 11 | SCOUT-017 | Unattributed PnL orphan bucket | 6 | 3 | 2 | small_patch |
| 12 | SCOUT-012 | 5m confirmation for neutral scanner | 6 | 3 | 3 | small_patch |
| 13 | SCOUT-026 | Flow override minimum quality floor | 6 | 2 | 2 | small_patch |
| 14 | SCOUT-004 | Intermediate drawdown stages | 7 | 7 | 4 | medium_feature |

**Scoping notes:**
- SCOUT-009: **DOWNGRADED.** Fee guard IS active. Fills are profitable. Issue is optimization only — reduce levels instead of expanding step for tighter grids.
- SCOUT-008: Spread check only (drop depth/liquidation). Block when `spread > 2x effective_grid_step`.
- SCOUT-021: Detection + logging only Phase 1. No auto-reduce. Threshold 0.7.
- SCOUT-011: Lock sizing at entry time. Don't recalculate per cycle. Toggle enabled.
- SCOUT-013: Check price-in-range to prevent false positives from quiet markets.
- SCOUT-017: Orphan bucket only. No heuristic attribution Phase 1. Respects same-symbol boundary.
- SCOUT-012: Use price velocity (`|price_now - price_5m_ago| / price > 1.5%`), not 5m ADX.
- SCOUT-026: Add `setup_quality_score >= 35` check to flow override. One condition. Scout verified code directly.
- SCOUT-004: DEFERRED until design doc addresses hysteresis, small-account calibration.

### LOW PRIORITY — When Convenient (3 ideas)

| Rank | ID | Title | Value | Cmplx | Risk | Shape |
|------|----|-------|-------|-------|------|-------|
| 14 | SCOUT-010 | Daily trend filter (directional only) | 5 | 3 | 2 | small_patch |
| 15 | SCOUT-014 | Status change audit trail | 5 | 3 | 1 | small_patch |
| 16 | SCOUT-025 | Config validation at creation time | 5 | 4 | 2 | medium_feature |

---

## Rejected / Redundant Ideas

| ID | Title | Verdict | Reason |
|----|-------|---------|--------|
| SCOUT-016 | 180-day ownership retention | REJECTED | Grid positions cycle within hours/days. 30-day retention covers 99%+ of cases. No evidence of 45+ day holds. |
| SCOUT-018 | Predictive grid re-centering | REJECTED | Three features in one = architecture project. Thrashing near edge boundary. Momentum grid shifting (2026-03-16) already provides trend-awareness. SIMPLER: reduce recenter cooldown. |
| SCOUT-024 | Same-symbol multi-bot prevention | REDUNDANT | **ALREADY IMPLEMENTED.** Phase 2 audit fix M6 at `bot_manager_service.py:1636-1654` blocks same-symbol creation with ValueError. Scout claim was factually incorrect. |
| SCOUT-027 | Prediction accuracy ledger | FUTURE_ROADMAP | Valid concept but CLAUDE.md states "AI layers are observe-only, not the main delivery focus." Prediction tuning is a future concern. When pursued, this is the right first step. |

---

## Deferred Ideas (need prerequisites)

| ID | Title | Prerequisite | When Ready |
|----|-------|-------------|------------|
| SCOUT-004 | Intermediate drawdown stages | Design doc: hysteresis, small-account calibration, mid-session propagation | After design review |
| SCOUT-006 | Comprehensive alert system | Scope to Phase A: kill-switch + error alerts only (2 types, not 8+) | After scope reduction |
| SCOUT-015 | Bounded auto-recovery | Error taxonomy: classify all exception types as transient vs structural | After error audit |
| SCOUT-022 | Profit protection auto-execute | Measure exit_now false positive rate. Fix rearm guard bug independently | After FP measurement |

---

## Needs More Evidence

| ID | Title | What's Missing |
|----|-------|---------------|
| SCOUT-002 | Exchange-side TP (NOT SL) | Scout claimed ZERO protection — **WRONG.** SL IS set via stop_loss_service → set_trading_stop. Only TP gap remains. Need: auto_stop_loss_enabled default, SL failure rate, trailing TP sync design. |
| SCOUT-007 | Phased entry ramp | Over-engineered (3-phase state machine). Simpler 2-candle cooldown better. Need log evidence of buy-the-top frequency. |

---

## Scout Factual Errors Found

| ID | Error | Correct Finding |
|----|-------|----------------|
| SCOUT-002 | Claimed "ZERO exchange-side exit protection" | SL IS set exchange-side via stop_loss_service.py:327 → set_trading_stop(). Only TP is missing. |
| SCOUT-009 | Claimed "systematic negative-EV per fill" with fee floor 0.16% | Fee floor is actually 0.26% (missed 0.10% slippage buffer). FEE_AWARE_MIN_STEP_ENABLED=True. Guard fires and expands step. Fills ARE profitable. |
| SCOUT-001 | Claimed all modes use serial refill | Only neutral_classic_bybit uses serial refill. Other modes already use _submit_batch_orders() in fast refill. |
| SCOUT-024 | Claimed "no duplicate symbol validation at creation" | M6 fix at bot_manager_service.py:1636-1654 already blocks same-symbol creation with ValueError. |

**Pattern:** Scout claims things don't exist or don't work without fully verifying. 4 of 25 ideas (16%) had materially incorrect claims. Evaluator must always verify critical claims, especially "no X exists" assertions.

---

## Answers to Scout's Open Questions

1. **SCOUT-002 (Exchange TP/SL interaction)**: SL already works. Only add exchange-side TP. Must cancel exchange TP before reduce-only exits. Update exchange TP on every trailing TP recalculation.

2. **SCOUT-004 (Per-account vs per-bot)**: Per-account for daily drawdown. Per-bot for individual loss limits. Both need hysteresis to prevent flapping.

3. **SCOUT-005 (Static vs real-time correlation)**: Static sector grouping is sufficient. No correlation computation needed. Use simple sector map.

4. **SCOUT-007 (Time vs confirmation)**: Time-based (2-candle cooldown) is the simpler and better approach.

5. **SCOUT-009 (Fetch fee tier)**: Configurable override is sufficient initially. Fetch from API is a nice Phase 2 enhancement.

6. **SCOUT-015 (Error classification)**: TimeoutError, ConnectionError, BybitRateLimitError = transient. InsufficientMarginError, PositionModeError, InvalidParameterError = structural.

7. **SCOUT-019 (Sync vs async retry)**: Async (verify on next cycle). Don't block runner tick. Residual sits for 1-2 seconds longer but doesn't block other bots.

8. **SCOUT-021 (Imbalance threshold)**: Start at 0.7 (70% directional). Detection + logging only. No auto-reduce Phase 1. Tune based on operator observation.

---

## Implementation Risk: grid_bot_service.py Concentration

Ideas touching `grid_bot_service.py` (27,131 lines): SCOUT-001, SCOUT-009, SCOUT-011, SCOUT-019, SCOUT-021

Phase 4 audit (pending) plans to decompose this into ~20 focused functions.

**RECOMMENDATION:** Prioritize ideas that DON'T touch grid_bot_service.py first:
- SCOUT-020 (bybit_stream_service) -- standalone
- SCOUT-023 (bot_manager_service) -- standalone
- SCOUT-003 (risk_manager + pnl_service) -- standalone
- SCOUT-008 (entry_gate_service) -- standalone
- SCOUT-013 (watchdog_hub_service) -- standalone
- SCOUT-017 (pnl_service + symbol_pnl_service) -- standalone

Then implement grid_bot_service ideas as part of or before Phase 4.

---

## Merge Opportunities

| Ideas | Merged Concept | Why |
|-------|---------------|-----|
| SCOUT-009 + SCOUT-023 | "Profitability gate" | Both validate fee viability — one for grid step, one for TP%. Share fee calculation logic. |
| SCOUT-008 + SCOUT-009 | "Pre-entry profitability validation" | Both prevent negative-EV entries (spread + fees). Can share a gate abstraction. |
| SCOUT-013 + SCOUT-006 Phase A | "Critical event detection" | Stuck bot detection feeds into alert system. Design together but implement independently. |

---

## Heartbeat Log

### Evaluation Pass #1 — 2026-03-16T14:35Z
- Reviewed 22 ideas (batches 1-2)
- Found 1 scout factual error (SCOUT-002: SL already implemented)
- Approved 14, deferred 4, rejected 2, needs evidence 2

### Evaluation Pass #2 — 2026-03-16T14:55Z
- Reviewed 3 new ideas (batch 3)
- Found 1 more scout factual error (SCOUT-024: same-symbol prevention already implemented)
- SCOUT-023 approved HIGH (TP% validation gap is real)
- SCOUT-024 marked REDUNDANT (already fixed in Phase 2 M6)
- SCOUT-025 approved LOW (UX improvement, not safety)

### Verification Pass — 2026-03-16T15:00Z
- Deep verification agents completed for SCOUT-001, SCOUT-002, SCOUT-003, SCOUT-004, SCOUT-009
- **SCOUT-009 DOWNGRADED:** Fee guard IS active. Fills profitable. Optimization only, not safety fix.
- **SCOUT-001 NARROWED:** Serial refill only in neutral_classic_bybit mode. Other modes already batch.
- **SCOUT-003/004 CONFIRMED:** All claims verified. Funding excluded from kill-switch. Binary response only.
- **SCOUT-002 CONFIRMED:** TP not set exchange-side. SL IS set. Only TP gap remains.
- **Scout error rate:** 4/25 ideas (16%) had materially incorrect claims.

### Scout Check #4 — 2026-03-16T15:10Z (whale/flow/OI/micro-bias/prediction integration)
- **Analyzed:** whale_detection_service.py (11K), order_flow_service.py (12K), open_interest_service.py (9.6K), micro_bias_service.py (12K), price_prediction_service.py (94K), market_sentiment_service.py (7K), mean_reversion_service.py (18K)
- **Lesson applied:** Verified ALL call sites via grep before claiming "not used". All 4 market analysis services ARE actively integrated into trading decisions (not display-only).
- **Ideas submitted:** 2 new candidates (SCOUT-026, SCOUT-027)
- **Key finding:** Order flow can OVERRIDE entry gate quality blocks (grid_bot_service.py:5250-5276) with NO minimum quality floor. flow_score >= 30 + confidence >= 0.4 forces entry regardless of setup quality. VERIFIED by reading lines 5249-5276.
- **Second finding:** Price predictions contribute ±60 points (30-60% of direction score) but zero accuracy tracking exists. Confidence is calibrated by internal agreement, never validated against actual outcomes.
- **Rejected ideas:** Whale spoofing detection (legitimate concern but persistence checks would add API overhead for a modest +/-20 point signal). OI lookback reduction (1-hour lookback is intentionally noise-filtering). Micro-bias exit integration (entry-only by design, extending to exits would require careful testing).

### Evaluation Pass #3 — 2026-03-16T15:15Z
- Reviewed 2 new ideas (SCOUT-026, SCOUT-027)
- SCOUT-026 (flow override quality floor): APPROVED MEDIUM. Simple one-condition fix. Scout verified code directly — good improvement from earlier error pattern.
- SCOUT-027 (prediction accuracy ledger): FUTURE_ROADMAP. Valid concept but AI layers are observe-only per CLAUDE.md. Not the delivery focus.
- Running totals: 27 ideas, 5 high, 9 medium, 3 low, 4 deferred, 2 rejected, 1 redundant, 1 future, 2 needs-evidence

### Next check: 10 minutes — monitoring for new scout ideas
