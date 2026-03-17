# Open Risks

## Highest Priority
- Snapshot reconciliation is helpful but not a full durable execution ledger. Long outages or partial fills can still leave ambiguity.
- Same-symbol ownership ambiguity can prevent confident orphaned-order/position attribution.
- Reconciliation annotates truth but does not auto-repair exposure; operator action may still be required.

## Medium Priority
- Ambiguous execution follow-up still depends on later exchange snapshots, not an append-only intent history.
- Runtime truth is better surfaced in APIs than in dedicated dashboard/watchdog presentation.
- Old helper/service files still reference stale `/var/www/opus_trader` paths.

## Lower Priority
- Archive/output hygiene still needs discipline because the project root accumulates zips and runtime byproducts quickly.
