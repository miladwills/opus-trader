# Readiness Semantics

## Stages
- `watch`: non-actionable observation state
- `armed`: setup is close, still not a fire-now state
- `trigger_ready`: setup timing is actionable
- `late`: setup existed but timing quality degraded

## Two Separate Truths
- Setup quality answers: "is the structure good?"
- Execution viability answers: "can this safely open now?"
- A setup can be good while execution remains blocked.

## Stale Preview Demotion
- Stopped-preview payloads must demote stale data to non-actionable watch semantics.
- Demotion must overwrite both `setup_ready_*` and `setup_timing_*` fields.
- `stale_snapshot` is preferred over optimistic stage carry-forward.

## Inactive Blocker Demotion
- Stopped/inactive bots should not present saved runtime blockers as fresh current truth unless recomputed.
- Persisted blockers should demote to stale/non-current semantics for inactive bots.

## `stop_cleanup_pending`
- Means trading is blocked and cleanup truth is not yet confirmed.
- It is safer than claiming `stopped` while exchange exposure may still exist.

## Ambiguous Execution Outcome
- Ambiguous outcomes are not confirmed success or confirmed failure.
- They should surface as follow-up truth checks, not retry invitations.
- `retry_safe=False` means do not blindly retry.

## Preference Rule
- Truthful non-actionable state is preferred over optimistic labeling.
- If certainty is low, expose uncertainty clearly.
