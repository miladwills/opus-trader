# Phase Status

Update this file after meaningful phase changes. Do not rewrite old sections unless the phase understanding changed.

## Completed
- Phase 1: fixed stale stopped-preview truth, introduced cleanup-pending stop semantics, made hard-loss stops flatten first, demoted stale inactive execution blockers
- Phase 1.1: aligned NLP max-loss stop path, demoted `_small_capital_block_opening_orders`, removed reviewed dead code
- Phase 2: made router timeouts explicitly ambiguous, fenced close intents, invalidated caches after ambiguous exchange actions, hardened bounded shutdown truth
- Phase 3: added startup/error-state reconciliation, ambiguous follow-up rechecks, exchange/persist divergence diagnostics, and bounded local truth annotations
- Phase 4A: enforced reconciliation truth as an execution blocker for new opening orders while preserving reduce-only, cleanup, and monitoring behavior
- Phase 4B: surfaced reconciliation-truth status, mismatch chips, and follow-up state in the operator UI without changing backend enforcement
- Phase 5: made symbol daily kill-switch cleanup-confirmed and `stop_cleanup_pending` when symbol-level close/cancel/flat confirmation is still unresolved
- Phase 6A: aligned directional gate truth contracts, retained compact entry-story evidence through audit/forensics/PnL, and separated affordability-cap materiality from non-material checks
- Phase 7: added adaptive profit protection and exit advisory modes with shadow evaluation, reduce-only live guards, retained outcome context, watchdog visibility, and concise bot detail/operator surfaces

## Current Focus
- Validate Phase 7 advisory-only/shadow output on fresh profitable positions before considering broader live rollout.
- Compare shadow saved-giveback vs trend-cut evidence before enabling `partial_live` or `full_live` outside controlled subsets.

## Next Gate
- Claude review of Phase 7 adaptive profit protection and exit advisory rollout safety.

## Next Likely Step
- Audit the next live winners and mixed-regime giveback cases to compare advisory decisions, shadow outcomes, and any live reduce-only partial/full actions.
