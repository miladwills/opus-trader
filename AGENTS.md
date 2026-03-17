# Repository Guidelines

## Current Repo Reality
- The live Opus Trader checkout on this host is `/var/www`, not `/var/www/opus_trader`.
- `/var/www/opus_trader` does not currently exist. Some old helper files and unit files still reference it. Treat those paths as stale until they are fixed.
- This workspace is not currently a git checkout. Do not rely on `git status`, history, or branches being available.
- Trading is effectively mainnet-only in the current runtime. Do not carry forward old testnet assumptions.
- Runtime data under `storage/` is live operational state. Read it carefully; do not hand-edit it unless the task is explicitly a state repair.

## Current Operating Priorities
- Narrow fix first. Do not broaden a patch unless the smaller fix is unsafe.
- Trading correctness, readiness truth, execution truth, and exchange-state safety come before feature breadth.
- AI/advisor layers are currently observe-only and not the main delivery priority.
- Prefer detect + surface + classify over optimistic labeling or silent auto-repair.

## Structured Project Memory
- `CLAUDE.md`: durable Claude-facing project understanding and non-break rules
- `docs/ARCHITECTURE.md`: concise runtime/control map
- `docs/READINESS_SEMANTICS.md`: readiness, blocker, and ambiguity semantics
- `docs/OPEN_RISKS.md`: current real risks only
- `docs/PHASE_STATUS.md`: current phase state and next gate
- `docs/CHANGELOG_LIVE.md`: short recent patch history
- `docs/REVIEW_LOG.md`: Claude review outcomes and follow-up state

## Required Workflow
1. Inspect the real code and existing docs first.
2. Make the smallest safe patch.
3. Add or update focused tests for changed behavior.
4. Restart both `app.py` and `runner.py`, then verify final PIDs.
5. Create the required project zip in `/var/www/`.
6. Update only the relevant docs.

## Review Workflow
- After each meaningful implementation:
  1. Codex implements.
  2. Claude Code Opus 4.6 Max Thinking reviews.
  3. Review findings are considered before the next patch.
- Future review prompts should include the Codex implementation summary directly in the prompt.

## Required Implementation Summary Format
- Executive summary
- Exact files changed
- Why each change was needed
- Tests added/updated
- Test results
- Any intentionally unchanged behavior
- Remaining risks or follow-up items
- Explicit UI location note, or `No visible UI change in this patch.`

## Documentation Update Rule
- Update only the docs touched by the patch.
- Do not rewrite all docs every time.
- `docs/CHANGELOG_LIVE.md`, `docs/PHASE_STATUS.md`, and `docs/REVIEW_LOG.md` should change most often.
- `CLAUDE.md` and `AGENTS.md` should change only when project understanding or workflow rules materially change.

## Preferred Risk Classification
- `Critical`: could create unsafe live exposure, false stop/flat state, wrong-side execution, or loss of ownership truth
- `High`: could materially mislead readiness/execution truth or break recovery/reconciliation
- `Medium`: operationally harmful, noisy, or regression-prone but not immediately dangerous to live exposure
- `Low`: docs, ergonomics, or minor observability gaps with low safety impact

## Explicit Avoid Rules
- Avoid broad refactors during live-safety work.
- Avoid silent threshold changes.
- Avoid hidden retry loops.
- Avoid symbol-wide exchange actions that cross same-symbol bot ownership boundaries.
- Avoid stale optimistic labels when truth is uncertain.
- Avoid duplicating the same guidance across multiple docs.

## Project Structure
- `app.py`: main Flask dashboard/API process. It lazily builds runtime services, exposes the dashboard, runner controls, watchdog/diagnostics/export APIs, backtest APIs, PnL APIs, and SSE stream fallback endpoints.
- `runner.py`: trading runner. Owns the main bot cycle, fast risk tick vs grid tick cadence, runner lock/stop flag handling, runtime snapshot publishing, and uncaught-cycle exception persistence.
- `config/config.py`: environment/auth/proxy configuration. Mainnet-only trading credentials are loaded here. Basic Auth is required unless explicitly bypassed by config.
- `config/strategy_config.py`: live strategy, risk, watchdog, Auto-Pilot, AI advisor, breakout, readiness, and scanner tuning. This is a high-risk file.
- `services/`: active business logic. Important clusters:
  - Execution and exchange: `bybit_client.py`, `order_router_service.py`, `position_service.py`, `account_service.py`, `bybit_stream_service.py`
  - Bot lifecycle/state: `bot_manager_service.py`, `bot_storage_service.py`, `bot_status_service.py`, `runtime_settings_service.py`
  - Trading engine: `grid_bot_service.py`, `grid_engine_service.py`, `range_engine_service.py`, `neutral_grid_service.py`, `scalp_pnl_service.py`
  - Entry and signal stack: `entry_gate_service.py`, `entry_readiness_service.py`, `price_action_signal_service.py`, `indicator_service.py`, `micro_bias_service.py`, `breakout_runtime_guard_service.py`
  - Risk and protections: `risk_manager_service.py`, `margin_monitor_service.py`, `flash_crash_service.py`, `neutral_loss_prevention_service.py`, `stop_loss_service.py`, `take_profit_service.py`, `trend_protection_service.py`, `danger_zone_service.py`
  - Attribution and analytics: `pnl_service.py`, `symbol_pnl_service.py`, `order_ownership_service.py`, `decision_snapshot_service.py`, `trade_forensics_service.py`, `ai_advisor_service.py`, `ai_advisor_analytics_service.py`, `advisor_replay_analysis_service.py`
  - Diagnostics and observability: `audit_diagnostics_service.py`, `watchdog_diagnostics_service.py`, `watchdog_hub_service.py`, `config_integrity_watchdog_service.py`, `diagnostics_export_service.py`, `runtime_snapshot_bridge_service.py`
  - Auto-Pilot and discovery: `neutral_scanner_service.py`, `auto_pilot_candidate_cache_service.py`, `open_interest_service.py`, `funding_rate_service.py`
- `templates/dashboard.html`: live dashboard template.
- `static/js/app_lf.js`: primary dashboard client.
- `static/js/app_v5.js`: shared globals/helpers loaded before `app_lf.js`.
- `static/js/app.js`, `static/js/app_bundled.js`, root-level `app.js`: legacy or non-primary assets. Verify the template includes before editing.
- `neutralscanner/`: standalone PHP neutral scanner and presets.
- `tests/`: active pytest suite covering runtime, dashboard APIs/UI contracts, watchdogs, Auto-Pilot, PnL attribution, breakout logic, snapshot bridge behavior, and config integrity.
- `storage/`: live JSON state, logs, diagnostics, exports, and lock files.

## Live Architecture
- `app.py` and `runner.py` are separate long-running processes. The app also runs a runner watchdog thread and can respawn the runner.
- The runner is the authoritative execution runtime. It dispatches full maintenance cycles for `running`, `paused`, and `recovering` bots, not just `running`.
- The default websocket owner is the runner. `BYBIT_STREAM_OWNER` controls whether the stream lives in `runner`, `app`, `both`, or `none`.
- The runner publishes read-only snapshots to `storage/runtime_snapshot_bridge.json`. The app prefers that bridge when stream ownership or freshness makes it safer than direct polling.
- The dashboard uses `/api/stream/events` SSE when available and falls back to periodic refreshes.
- The active dashboard now includes:
  - runner status and controls
  - active bot runtime cards/table
  - Neutral Scanner integration
  - watchdog hub
  - diagnostics export controls
  - AI advisor/replay analytics views

## Active High-Impact Subsystems
- Auto-Pilot is live and broad:
  - strong symbol filters
  - universe modes (`default_safe`, `aggressive_full`)
  - candidate cache
  - adaptive rotation timing
  - remaining-loss-budget opening guard
  - placeholder-symbol startup/reset rules
- Entry logic is layered:
  - indicator/readiness analysis
  - directional entry gate
  - price-action confluence
  - breakout confirmation / no-chase / invalidation logic
  - scanner guidance and runtime blockers
- Diagnostics are first-class:
  - audit diagnostics JSONL + summary + review snapshot
  - active watchdog registry/hub
  - trade forensics lifecycle log
  - decision snapshots
  - AI advisor review and replay analysis
  - export archives under `storage/exports/`
- PnL attribution is durable:
  - `orderLinkId` tagging still matters
  - `storage/order_ownership.json` is a critical fallback source
  - unattributed and ambiguous same-symbol closes are intentionally preserved when ownership is not provable

## Critical Guardrails

### Execution And Order Safety
- Do not change order creation, close, cancel, or reduce-only behavior casually. Review `bybit_client.py`, `order_router_service.py`, `grid_bot_service.py`, and `bot_manager_service.py` together.
- Same-symbol multi-bot ownership is a hard boundary. Do not introduce symbol-wide cancel/close behavior that can touch another bot’s orders or position.
- The literal symbol `Auto-Pilot` is placeholder control state, not a tradable symbol. Never let it reach exchange-facing calls.
- Preserve reduce-only exits when pausing or safety-blocking a bot. Opening-order cancellation and closing-position logic are intentionally separate.
- If you touch close flows, preserve ownership snapshot handoff into `create_order(...)` so later PnL attribution still works.

### Persistence And State Integrity
- Do not write `storage/*.json` directly from new code. Use the existing storage/services and lock helpers.
- `bot_storage_service.py` has control-version and settings-version merge guards. Do not bypass them with raw saves.
- `/api/bots` now enforces settings-version concurrency. Preserve `settings_version` on edits and expect `409` on stale saves.
- Config-save integrity is actively audited. Keep `/api/bots` and `/api/config-integrity/report` compatible with `config_integrity_watchdog_service.py` round-trip checks.
- Preserve authoritative aggregate PnL fields. Generic lifecycle/runtime saves must not roll back `realized_pnl` or `total_pnl`.
- Canonical range persistence is mode-specific:
  - `neutral_classic_bybit` may persist `grid_lower_price` / `grid_upper_price`
  - non-classic modes should persist `lower_price` / `upper_price` and strip legacy aliases
- `symbol_pnl.json` contains both symbol rows and `bot:<id>` rows. Symbol-wide readers must filter the bot keys.

### Risk Logic
- `config/strategy_config.py` changes are high-risk even when small. Treat timing, leverage, loss limits, breakout settings, and Auto-Pilot filters as production-sensitive.
- Account-level and symbol-level kill-switch behavior lives across config, `risk_manager_service.py`, `grid_bot_service.py`, and `bot_manager_service.py`.
- Fast risk polling and full-cycle behavior are intentionally separate in `runner.py`. Do not collapse them without reviewing side effects on stop-loss, refill, and reconcile paths.
- `scalp_pnl` keeps separate profit-taking behavior from shared directional quick-profit logic.

### Watchdogs, Diagnostics, And Forensics
- Watchdogs are passive diagnostics, not execution controllers by themselves. Keep them observational unless the existing subsystem already uses their state.
- `config_integrity_watchdog_service.py` protects config round-trip truth, especially bot boolean toggles across main vs quick edit paths.
- `audit_diagnostics_service.py` maintains rolling summaries used by the watchdog hub and review snapshots.
- `watchdog_hub_service.py` persists active issues in `storage/watchdog_active_state.json`; preserve its TTL- and runtime-based resolution behavior.
- `trade_forensics_service.py` is append-only lifecycle evidence. Keep payloads compact and deduped.
- `decision_snapshot_service.py` is derived from forensics, not a primary ledger.
- Diagnostics exports under `storage/exports/` are expected runtime outputs, not throwaway temp files.

### Dashboard And Readiness Semantics
- Preserve the distinction between `preview_disabled`, `preview_limited`, and `stale_snapshot`.
- `templates/dashboard.html` + `static/js/app_lf.js` are the live UI pair. Check both when changing dashboard behavior.
- `app_v5.js` still provides globals/helpers consumed by `app_lf.js`; do not break that load order.

### Neutral Scanner
- `neutralscanner/` is live PHP code, not an archive.
- `neutralscanner/cache/` and `neutralscanner/neutral_symbols.json` must remain writable by the PHP runtime user.
- The scanner now uses cached payload serving plus lease-based refresh locking. Preserve the fast `action=data` path and the locked `action=refresh` path split.

## Important Runtime Files
- `storage/bots.json`: live bot registry and runtime-enriched control state
- `storage/trade_logs.json`: realized trade log source for PnL rebuilds
- `storage/order_ownership.json`: durable ownership breadcrumbs
- `storage/risk_state.json`: kill-switch and risk state
- `storage/runtime_settings.json`: lightweight dashboard/runtime toggles
- `storage/runtime_snapshot_bridge.json`: runner-to-app snapshot bridge
- `storage/audit_diagnostics.jsonl`
- `storage/audit_diagnostics_summary.json`
- `storage/audit_diagnostics_review_snapshot.json`
- `storage/watchdog_active_state.json`
- `storage/trade_forensics.jsonl`
- `storage/decision_snapshots.json`
- `storage/ai_advisor_review.json`
- `storage/advisor_replay_analysis.json`
- `storage/exports/ai_layer/`
- `storage/exports/watchdog/`
- `storage/exports/all_diagnostics/`
- `storage/app.log`
- `storage/runner.log`

## Obsolete Or Misleading Artifacts
- `opus_trader.service`, `opus_runner.service`, and `restart_services.php` still reference `/var/www/opus_trader`. Verify or fix before relying on them.
- Root-level and alternate JS artifacts are not necessarily the live dashboard client.
- Existing `.zip`, `.bak`, `temp_*`, and cache files are not source of truth unless the task is explicitly forensic or restore-related.

## Development Workflow
- Use the repo root `/var/www` as the working directory in this environment.
- Keep route handlers thin. Push trading/risk/state logic into `services/`.
- Prefer extending existing services over adding parallel replacement modules.
- Use `logging`, not `print`.
- Prefer `rg` for searches.
- Avoid editing generated/runtime files unless the task explicitly targets them.
- There is no npm or frontend build pipeline here. Frontend verification is driven by Flask/pytest tests plus a small Node-backed test helper path.

## Verification
- Fast syntax check:
  - `./venv/bin/python -m py_compile app.py runner.py services/*.py config/*.py tests/*.py`
- Full regression suite:
  - `./venv/bin/pytest -q tests`
- Useful regression anchors for this codebase:
  - `tests/test_app_config_integrity_watchdog.py`
  - `tests/test_audit_diagnostics_service.py`
  - `tests/test_bot_checkbox_persistence.py`
  - `tests/test_bot_status_signal_drift_watchdog.py`
  - `tests/test_diagnostics_export_api.py`
  - `tests/test_runtime_snapshot_bridge_service.py`
  - `tests/test_trade_forensics_service.py`
  - `tests/test_watchdog_hub_service.py`
  - `tests/test_watchdog_hub_ui.py`
- For dashboard/API changes, also smoke:
  - `/`
  - `/api/summary`
  - `/api/positions`
  - `/api/bots/runtime`
  - `/api/watchdog-center`
  - `/api/export/watchdog`
  - `/api/neutral-scan`
  - `/api/pnl/log`
  - `/api/pnl/stats`
- For runner/state/order-flow changes, inspect fresh `storage/runner.log` and `storage/app.log` after restart.
- For config save bugs, verify persisted bot JSON, returned API payload, and rendered dashboard state all agree.

## Restart Workflow
- After any repository change, restart both `app.py` and `runner.py`.
- Do not consider any change complete until both processes are restarted and their final PIDs are verified.
- Current live process style on this host is direct Python execution from `/var/www/venv/bin/python`, not reliable systemd service management.
- Because `app.py` runs a runner watchdog, restarting the app can also affect runner lifecycle. Always re-check both PIDs after restart.

## Permanent Release / Handoff ZIP Rule
- After every completed implementation, bugfix, refactor, or finished modification batch, always create a fresh full-project ZIP archive automatically.
- This rule is always active by default.
- It applies every time changes are completed, even multiple times within the same chat/session.

### ZIP Policy
- Archive the full project.
- Canonical target path is `/var/www/opus_trader`.
- On this host, that path is currently missing and the live project root is `/var/www`; until `/var/www/opus_trader` exists again, archive `/var/www`.
- Save the archive in `/var/www/`.
- Include important source code, configs, docs, templates, assets, tests, and required scripts.
- Exclude:
  - `venv/`
  - `.venv/`
  - `env/`
  - all existing `.zip` files
  - `__pycache__/`
  - `.pytest_cache/`
  - `.mypy_cache/`
  - `.cache/`
  - temp files
  - logs
  - other bulky non-runtime artifacts not needed for execution, review, or handoff
- Use this naming format:
  - `opus_trader - [latest remarkable changes] - [YYYY-MM-DD] [HH-MM AM/PM].zip`

## Commands
- `python3 -m venv venv && source venv/bin/activate`
- `pip install -r requirements.txt`
- `./venv/bin/python app.py`
- `./venv/bin/python runner.py`
- `./venv/bin/python -m py_compile app.py runner.py services/*.py config/*.py tests/*.py`
- `./venv/bin/pytest -q tests`
