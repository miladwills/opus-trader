# Live Changelog

Update this file for meaningful patches. Keep entries short.

## 2026-03-17
- Storage contention reuse follow-up: runner startup and maintenance reconciliation now forward the already-materialized full bot snapshot into `reconcile_bots_exchange_truth()`, eliminating the redundant same-tick `list_bots()` re-read for those paths and emitting throttled `BOT_STORAGE_REUSE` diagnostics so skipped reconciliation re-lists can be proven in live runner logs
- Storage contention read-path audit: runner/grid storage hot paths now emit throttled `BOT_STORAGE_READ` diagnostics with caller labels (`runner_risk_tick`, `runner_grid_tick`, `run_bot_cycle`, reconciliation, fast refill, runtime-save lookup) so remaining `cache_lock` pressure can be tied to cache hits vs refills and full-list reads without log flood, and `save_runtime_bot()` now reuses one cached bot-list snapshot instead of re-entering `_read_all_cached()` twice for the same runtime update
- Storage contention follow-up: repeated `error_maintenance` / `ambiguous_follow_up` exchange reconciliation passes now keep timestamp-only refreshes cache-only instead of re-writing `bots.json`, and bot storage emits throttled `BOT_RUNTIME_PERSIST` diagnostics for that path so duplicate runtime persistence can be measured without flooding logs
- Dashboard bridge freshness fix: SSE/dashboard stream payload assembly no longer trusts the raw `read_dashboard_payload()` bundle, so stale-but-complete `summary` / `positions` / `bots_runtime` bridge sections now fall back through the existing freshness-aware section recovery path instead of being streamed as live truth
- Dashboard bootstrap recovery fix: `/api/dashboard/bootstrap` now runs direct bounded `summary` / `positions` / `bots_runtime` rebuilds instead of the generic 1.5s snapshot wrappers, and fresh recovered sections are cached so the next stream tick serves stale-real data rather than repainting zero fallbacks during bridge recovery

## 2026-03-16
- Dashboard hot-path fix: fresh runner `bots_runtime` bridge payloads no longer trigger app-side direct runtime probes solely because a start is pending, preventing repeated stopped-preview/indicator rebuilds and reducing slow/stuck dashboard loads under gunicorn workers
- Dashboard follow-up: when a runner `bots_runtime` bridge payload exists but is stale or partial, the app now serves that stale truth with integrity flags instead of synchronously rebuilding `bots_runtime` on the request path and freezing the page during runner/exchange trouble
- Dashboard SSE follow-up: live `summary` and `positions` refreshes no longer hammer app-side `?fresh=1` probes while a runner bridge section already exists, and the served `app_lf.min.js` bundle now matches that bridge-first behavior so old tabs and current SSE sessions keep serving bridge truth instead of wedging workers on direct Bybit/account rebuilds

## 2026-03-14
- Active Bots UI follow-up: newly transitioned `watch` and `blocked` coins now sink to the end instead of jumping to the top, reducing row reshuffle while operators track symbols in those tabs
- Active Bots UI: search now overrides the current tab filter so symbol matches stay visible in any tab, recent tab movers are promoted to the top, the search-adjacent toolbar button is now `Clear`, explicit starts switch focus back to `Working Now`, and both main/quick bot editors now expose `Save & Start` without adding a new backend save path
- Fixed restart-after-stop persistence drift: `BotStorageService.save_bot()` now strips impossible persisted stop-cleanup/pause markers when a bot is saved into a non-cleanup / non-paused status, preventing fresh starts from being forced back through stale cleanup by leftover `stop_cleanup_*` truth
- Added `scripts/cleanup_legacy_stop_cleanup_bots.py` for one-time persisted-bot maintenance to dry-run/apply stale legacy `stop_cleanup_*` marker cleanup with timestamped `bots.json` backup, forced `stopped` status, reduce-only/auto-stop reset, compact reporting, and persisted-exposure skip warnings
- Micro-fix: cleared stale `stop_cleanup_pending` restart markers and cleanup-mode flags on fresh `start_bot()` / `resume_bot()` so runner no longer re-routes a newly started bot back into cleanup solely from stale stop truth

## 2026-03-13
- Phase 7: added adaptive profit protection and exit advisory modes (`off`, `advisory_only`, `shadow`, `partial_live`, `full_live`) with compact advisory persistence, shadow outcomes, reduce-only live guards, watchdog visibility, and bot detail/operator badges
- Phase 6A: aligned directional gate truth across readiness/advisor/runtime payloads, persisted compact entry-story snapshots into audit/forensics/PnL, and split affordability-cap material vs non-material diagnostics without changing strategy thresholds
- Phase 6A follow-up: restored `GridBotService._is_tradeable_symbol()` so stop-cleanup confirmation and placeholder-symbol guards no longer throw live cycle `AttributeError`
- Phase 5: aligned symbol daily kill-switch with cleanup-confirmed stop truth so bots stay `stop_cleanup_pending` until flat/orders-clear are confirmed
- Phase 4B: surfaced reconciliation-truth blockers in Active Bots, bot detail, and watchdog UI with compact exchange-truth badges and mismatch/follow-up rows
- Phase 4A: blocked new opening orders when reconciliation truth says exchange assumptions are stale, diverged, or unresolved, while keeping reduce-only and cleanup paths alive
- Phase 3: added exchange-state reconciliation for startup, error-state maintenance, ambiguous follow-up checks, and divergence diagnostics
- Phase 2: hardened ambiguous router timeouts, close intent fencing, cache invalidation, and bounded shutdown truth
- Phase 1.1: aligned NLP max-loss stop cleanup truth and stale inactive blocker handling
- Phase 1: fixed stale stopped-preview truth, stop cleanup truthfulness, hard-loss flatten-before-final-stop, and stale stopped-bot blocker demotion
