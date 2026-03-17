# Review Log

Update this file after major Claude reviews. Keep it factual and short.

## Phase 1
- Reviewer: Claude Code Opus 4.6 Max Thinking
- Verdict: Follow-up needed
- Key notes: NLP `max_loss_stop` success path still skipped cleanup-confirmation truth; `_small_capital_block_opening_orders` still needed inactive demotion
- Follow-up: Phase 1.1 closed the review findings

## Phase 1.1
- Reviewer: Claude Code Opus 4.6 Max Thinking
- Verdict: Accepted
- Key notes: cleanup-consistency and stale-blocker follow-up items were resolved
- Follow-up: No immediate follow-up from that review

## Phase 2
- Reviewer: Claude Code Opus 4.6 Max Thinking
- Verdict: Follow-up needed
- Key notes: remaining top risk was exchange-state reconciliation after crashes, ambiguous outcomes, and error-state drift
- Follow-up: Phase 3 implemented the narrow reconciliation layer

## Phase 3
- Reviewer: Pending
- Verdict: Pending
- Key notes: startup/error-state reconciliation and ambiguous follow-up truth are implemented and awaiting review
- Follow-up: Review outcome will determine the next narrow patch

## 2026-03-16 Dashboard Probe Hotfix
- Reviewer: Codex explorer via `opus-patch-review`
- Verdict: Accepted
- Key notes: fresh-bridge pending-start probe removal is structurally correct; added direct coverage for held startup state when the fresh bridge has not listed the bot yet
- Follow-up: No open review findings for this patch

## 2026-03-16 Dashboard SSE Fresh-Probe Hotfix
- Reviewer: Codex explorer via `opus-patch-review`
- Verdict: Accepted
- Key notes: the live `app_lf.min.js` bundle now matches the bridge-first `summary` / `positions` hot path, duplicate source copies were aligned, and the served-template wiring is covered by regression tests
- Follow-up: Remaining risk is limited to bridge-missing windows where `?fresh=1` is still intentionally allowed

## 2026-03-17 Dashboard Bridge Freshness And Bootstrap Recovery
- Reviewer: Codex explorer via `opus-patch-review`
- Verdict: Accepted
- Key notes: stream payload assembly now routes critical sections through the existing freshness-aware helpers, bootstrap recovery now uses direct builders with a shared outer timeout budget, and focused regressions cover both the raw-bridge bypass and the bounded bootstrap path
- Follow-up: Remaining live slowness is outside this patch and still depends on upstream exchange/network health plus the unchanged non-bootstrap 1.5s section timeout behavior
