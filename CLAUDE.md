# CLAUDE.md

## Mission
- Opus Trader is being developed as a professional trading operating system.
- Current priority is trading correctness, entry-readiness truthfulness, execution truth, and exchange-state safety.
- AI layers are observe-only for now. They are not the main delivery focus.

## Strategic Priority
1. Exchange truth over optimistic local assumptions
2. Correct stop / cleanup semantics
3. Truthful readiness and blocker semantics
4. Durable order / position attribution
5. Low-noise operator UX

## Current Workflow
1. Codex implements the patch.
2. Claude Code Opus 4.6 Max Thinking reviews the patch.
3. Review findings are considered before the next patch.
4. Future review prompts should include the Codex implementation summary inline.

## Runtime Ownership
- `app.py`: Flask dashboard/API, lazy service wiring, runner watchdog, diagnostics/export endpoints
- `runner.py`: authoritative execution runtime, fast risk tick + full grid tick, startup/error reconciliation, runtime snapshot publishing
- `services/grid_bot_service.py`: bot-cycle orchestration, stop semantics, execution follow-up, exchange-state reconciliation
- `services/order_router_service.py`: serialized symbol-scoped execution routing, ambiguous timeout truth
- `services/bybit_client.py`: REST execution, cache invalidation, exchange transport
- `services/bot_status_service.py`: runtime payload, readiness display, reconciliation metadata surfacing
- `services/entry_readiness_service.py`: readiness/setup/execution-viability semantics
- `storage/runtime_snapshot_bridge.json`: runner-to-app runtime truth bridge

## Truth Model
- Exchange truth is authoritative when local runtime or persisted state disagrees.
- Persisted bot state can be stale after crashes, ambiguous execution outcomes, or partial cleanup.
- Truthful non-actionable states are preferred over optimistic labels.
- `stop_cleanup_pending` means no new trading, cleanup still unresolved.
- Ambiguous router outcomes are not safe to retry blindly.
- Same-symbol multi-bot ownership is a hard safety boundary.

## Key Statuses
- Lifecycle: `running`, `paused`, `recovering`, `stop_cleanup_pending`, `stopped`, `risk_stopped`, `error`
- Readiness: `watch`, `armed`, `trigger_ready`, `late`
- Reconciliation metadata: exchange/persist divergence, orphaned order/position, ambiguous follow-up pending/resolved

## Readiness Notes
- Setup quality and execution viability are separate truths.
- Stale stopped previews must demote to non-actionable watch-style semantics.
- Inactive/stopped bots should not surface stale runtime blockers as fresh current blockers.
- Prefer `stale_snapshot`, `preview_disabled`, `preview_limited`, or inactive demotion over hopeful readiness.

## Completed Phases
- Phase 1: stale stopped-preview truth, cleanup-pending stop semantics, hard-loss flatten-before-final-stop, stale blocker demotion
- Phase 1.1: NLP max-loss consistency, small-capital stale demotion, dead-code cleanup
- Phase 2: ambiguous router timeout semantics, retry fencing, cache invalidation after ambiguous order actions, bounded shutdown truth
- Phase 3: startup/error-state reconciliation, ambiguous follow-up truth checks, divergence diagnostics, bounded local truth correction

## Highest-Priority Remaining Risk
- Reconciliation is now snapshot-based but not a full durable execution ledger.
- Long outages, partial fills, and same-symbol ownership ambiguity can still require operator judgment.

## UI Preference
- Keep the UI concise, low-noise, and minimally descriptive.
- Favor truthful state badges/fields over explanatory prose.

## Delivery Rules
- After any meaningful patch: restart `app.py` and `runner.py`, verify final PIDs, and push changes to GitHub (`git add -A && git commit && git push origin main`).
- Never push `.env`, `venv`, logs, or other sensitive/heavy artifacts (covered by `.gitignore`).

## Do Not Break
- Reduce-only exits and cleanup truth
- Ownership tagging and PnL attribution
- `control_version` / storage merge guards
- Mainnet-only assumptions
- Auto-Pilot placeholder symbol safety
- Thin route / service-owned business logic structure

## MCP Tools
- Use Context7 for up-to-date library/framework documentation when relevant.
- Use Memory for prior project decisions, conventions, and long-running context when relevant.
- Use Sequential Thinking for complex debugging, architecture, or multi-step reasoning when the task genuinely benefits from it.
- Do not force these tools if the task is simple.
