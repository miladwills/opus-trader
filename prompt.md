You are performing a major but staged architectural refactor of Opus Trader.

This is a real-money trading system. The goal is to stop the current pattern where dashboard loading, runtime state, scanner work, stopped-preview readiness, analytics, and exchange-derived enrichment all collide in the same hot path and keep breaking each other.

This is NOT a rewrite from scratch.
This is a controlled decomposition of the existing system into isolated lanes with a safe migration path.

Core mission
Transform the current tightly coupled architecture into a layered system with these principles:

- market data lane is separate
- execution lane is separate
- runtime snapshot/state lane is separate
- background analytics lane is separate
- UI/API reads prebuilt snapshots only
- heavy analysis never blocks critical dashboard truth
- bots_runtime_light is distinct from bots_runtime_full
- the system remains operational during migration

Non-negotiable constraints
1. Do not rewrite the whole project from scratch.
2. Preserve current trading logic, execution logic, and risk behavior unless moving code boundaries requires a safe adapter.
3. Prefer staged extraction over big-bang replacement.
4. Dashboard-critical data must stop depending on heavy enrichment.
5. UI/API lane must never require scanner, predictions, stopped-preview computation, watchdog, advisor, or heavy analysis to paint the operator dashboard.
6. Keep the current system runnable during the migration.
7. Avoid cosmetic churn unless required to support the new architecture.
8. After completion, create a full ZIP in /var/www/ excluding venv, storage, zip files, apk files, caches, and heavy junk.

What is broken today
The current architecture mixes too much into the hot path:
- dashboard payload generation
- runtime bridge publishing
- scanner work
- stopped-preview readiness
- live open-order enrichment
- predictions / heatmap / watchdog / triage / config advisor
- UI bootstrap shaping
- bridge truth / recovery logic

This causes:
- slow dashboard first paint
- stale or false-zero critical panels
- runner/bridge publish cycles becoming too slow
- constant regressions where one performance fix breaks truthfulness and vice versa

Target architecture
Design and implement the system into these lanes/services inside the current repo first, with clear boundaries and adapters:

1) Market Data Lane
Responsibilities:
- consume Bybit websocket / account / order / market feeds
- normalize and cache latest market/account/exchange state
- expose lightweight, reusable state for other lanes
Must NOT do:
- scanner
- predictions
- readiness analysis
- dashboard shaping
- heavy UI payload building

2) Execution Lane
Responsibilities:
- place / amend / cancel / close orders
- reconcile exchange order/position truth
- enforce risk at execution time
Must NOT do:
- dashboard shaping
- heavy analytics
- scanner / heatmap / advisor work

3) Runtime Snapshot / State Lane
Responsibilities:
- publish dashboard-critical snapshots only
- summary
- positions
- runtime health
- bots_runtime_light
- pnl_today / recent closed pnl
- connection/integrity state
Properties:
- fast
- deterministic
- bounded
- no heavy enrichment
Must NOT depend on:
- scanner
- predictions
- stopped-preview heavy evaluation
- advisor/watchdog heavy builders

4) Background Analytics Lane
Responsibilities:
- scanner
- predictions
- watchdog
- bot triage
- config advisor
- stopped-preview readiness
- heatmap
- rich diagnostics
- extended attribution / experimental analytics
Properties:
- async only
- slower cadence acceptable
- results written to cache/store
- must never block critical dashboard lane

5) UI/API Lane
Responsibilities:
- read already-built snapshots only
- show stale/degraded truthfully
- send commands only
Must NOT do:
- exchange calls for critical dashboard paint
- heavy aggregation
- runtime bot heavy enrichment

Critical design rule
Create a strict split between:

A) bots_runtime_light
Dashboard-critical only:
- bot id
- symbol
- mode
- status
- live side
- current price
- quick pnl / exposure
- compact readiness stage
- compact blocker reason
- updated_at
- runtime health markers

B) bots_runtime_full
Analytics/advisory only:
- scanner context
- stopped-preview deep fields
- advisor/watchdog/triage detail
- heavy attribution
- extended diagnostics
- any expensive enrichment

The dashboard critical path must use bots_runtime_light only.

Implementation strategy
Do this in stages, not all-or-nothing.

PHASE 1 — Architecture map and contracts
Before moving code, inspect the current codebase and identify:
- current market/exchange ingestion paths
- current execution/order paths
- current runtime bridge publishing path
- dashboard bootstrap/SSE/fallback paths
- scanner/predictions/watchdog/triage/advisor builders
- where get_runtime_bots() is overloaded with mixed responsibilities
- where the UI/API path still reaches into heavy logic

Then define explicit contracts for:
1. DashboardCriticalSnapshot
2. PositionsSnapshot
3. SummarySnapshot
4. RuntimeHealthSnapshot
5. BotsRuntimeLightSnapshot
6. BotsRuntimeFullSnapshot
7. AnalyticsSnapshot bundle or separate caches

Create these contracts as clear typed schemas / dataclasses / TypedDicts / helper models in a new shared module.
Do not leave the new architecture as implicit ad hoc dicts.

Deliverable of phase 1:
- explicit architecture map in docs
- snapshot contracts in code
- no behavior breakage yet

PHASE 2 — Extract a runtime snapshot publisher boundary
Create a dedicated internal module/service layer for runtime snapshot publishing.

Goal:
- one canonical producer of dashboard-critical state
- no UI endpoint should assemble dashboard-critical truth by recomputing heavy logic

Implement something like:
- services/runtime_state_publisher.py
or equivalent structure

It should publish/store only:
- summary snapshot
- positions snapshot
- bots_runtime_light snapshot
- runtime health snapshot
- pnl critical snapshot

It must be able to run on a fast cadence with bounded work.
It must not call heavy analytics builders.

Refactor current bridge usage so the dashboard reads from this publisher/store boundary, not from mixed logic paths.

PHASE 3 — Split bots runtime generation
Refactor the current runtime bot generation so that:
- bots_runtime_light can be produced cheaply and frequently
- bots_runtime_full is produced separately and asynchronously

Important:
- do not let stopped-preview, scanner lookup, heavy open-order enrichment, or advisor fields leak back into the light path
- do not keep one giant get_runtime_bots() that conditionally does everything
- separate the concerns explicitly, even if you temporarily keep compatibility wrappers

Acceptable pattern:
- get_runtime_bots_light(...)
- get_runtime_bots_full(...)
or equivalent provider classes

PHASE 4 — Move heavy analytics off the critical path
Create or refactor dedicated background workers/providers for:
- scanner
- predictions
- watchdog
- triage
- config advisor
- stopped-preview readiness
- heatmap

Each should:
- run on its own cadence
- publish cached results
- be independently failure-tolerant
- never block critical dashboard publishing

If needed, create:
- analytics cache registry
- analytics publish timestamps
- stale metadata per analytic panel

PHASE 5 — Make UI/API read snapshots only
Refactor dashboard bootstrap, SSE/live updates, and fallback reads so that:
- critical dashboard data comes only from the runtime snapshot/state lane
- secondary analytics panels come only from background analytics caches/results
- no critical endpoint recomputes heavy analytics
- no UI first-paint path depends on scanner/advisor/watchdog/predictions

The dashboard must clearly distinguish:
- true empty
- stale but last-known-good
- unavailable / retrying

But do not drown the interface in extra text.

PHASE 6 — Introduce adapters and compatibility shims
Because this is a staged migration, keep backward-compatible adapters where needed.
Examples:
- old endpoints can read new snapshot sources
- old builders can be wrapped while new publishers take over
- existing UI payload shapes can be preserved temporarily while the backend source becomes cleaner

Goal:
- minimize blast radius
- preserve trading behavior
- keep deployment safe

PHASE 7 — Tight verification and rollout safety
Add targeted tests and diagnostics for:
- snapshot contract shape validity
- bots_runtime_light generation does not call heavy analytics
- dashboard bootstrap does not depend on heavy analytics
- analytics worker failure does not break critical dashboard snapshot
- runtime snapshot publisher continues to publish even if analytics lane is slow/failing
- stale/degraded flags are truthful
- old dead/slow bridge failure mode is no longer able to poison critical dashboard truth

Also add concise diagnostics that help operators/devs verify:
- snapshot ages
- publisher freshness
- critical lane latency
- analytics lane freshness separately
- whether critical dashboard is using light/runtime snapshot source as intended

Files and structure to create/refactor
You decide the exact file layout after reading the current codebase, but the result should likely include clear modules such as:
- shared snapshot contracts / models
- runtime state publisher
- market state provider
- analytics cache/publisher
- split runtime bot providers
- compatibility adapter layer if needed
- docs describing lanes and data flow

Important implementation principles
- preserve existing bot logic and order logic
- preserve current exchange integration behavior unless boundary extraction requires wrapping it
- do not bury the design in huge monolithic functions
- reduce hidden side effects
- prefer explicit data flow over implicit global recomputation
- critical path must be observable and measurable
- heavy path must be isolated and allowed to be stale without breaking operations

What I want you to deliver
A) Working implementation
Implement the staged architectural split in the codebase, not just a design document.

B) Service/lane boundary map
Create a concise architecture document showing:
- current-to-new mapping
- lane responsibilities
- which current functions/modules moved to which lane
- what remains temporary compatibility code

C) Snapshot contracts
Create explicit typed contracts for the critical snapshots and analytics snapshots.

D) Migration notes
Document:
- what was moved now
- what remains coupled but is isolated behind adapters
- the next recommended extraction step after this pass

E) Tests
Run focused tests and add missing targeted tests if required.

F) ZIP packaging
Create a ZIP in /var/www/ excluding:
- venv
- storage
- *.zip
- *.apk
- __pycache__
- .pytest_cache
- .mypy_cache
- .ruff_cache
- .cache
- other obvious heavy/generated junk

What not to do
- do not answer only with theory
- do not stop after docs only
- do not rewrite the whole app
- do not change strategy thresholds casually
- do not mix heavy analytics back into the critical snapshot lane
- do not leave the dashboard dependent on get_runtime_bots_full-style heavy enrichment

Success criteria
The result should make these statements true:
1. The dashboard critical first paint no longer depends on heavy analytics.
2. bots_runtime_light can be published quickly and repeatedly.
3. Scanner/predictions/watchdog/triage/advisor can be stale or slow without breaking dashboard truth.
4. Critical dashboard endpoints read prebuilt snapshot state instead of rebuilding mixed heavy logic.
5. The codebase is structurally clearer, with isolated lanes and less chance that future fixes collide.
6. The system remains operational during and after the migration.

Final output format
At the end, report briefly and practically:
- exact files created/changed
- which responsibilities were moved into which lane
- what the new critical dashboard path is
- what moved to background analytics
- what compatibility shims remain
- exact UI location affected:
  - main dashboard first load
  - live refresh path
  - critical panels vs secondary panels
- obvious practical effect for the operator
- what still remains for a future phase