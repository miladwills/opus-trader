# Architecture

## Main Runtime / Control Path
- `app.py`: dashboard/API, lazy service setup, runner watchdog, export/watchdog endpoints
- `runner.py`: authoritative bot-cycle executor, fast risk tick + full grid tick, startup/error reconciliation, runtime snapshot bridge writes
- `storage/runtime_snapshot_bridge.json`: runner-published runtime truth consumed by the app when preferred over direct polling

## Readiness Path
- `services/entry_readiness_service.py`: setup quality, timing stage, execution viability
- `services/bot_status_service.py`: stopped-preview handling, stability layer, runtime payload shaping
- `templates/dashboard.html` + `static/js/app_lf.js`: live readiness display surface

## Execution Path
- `services/grid_bot_service.py`: cycle orchestration, stop/cleanup transitions, reconciliation follow-up
- `services/order_router_service.py`: symbol-scoped serialized execution, ambiguous timeout contract
- `services/bybit_client.py`: REST transport, cache invalidation, exchange-facing actions
- `services/order_ownership_service.py` + `services/pnl_service.py`: ownership breadcrumbs and close attribution

## Observability Path
- `services/audit_diagnostics_service.py`: compact machine-usable event log
- `services/watchdog_hub_service.py`: active issue aggregation and operator surfacing
- `services/trade_forensics_service.py`: append-only execution evidence
- `services/runtime_snapshot_bridge_service.py`: app-safe runtime publication

## Fragile Boundaries
- Same-symbol multi-bot ownership vs symbol-wide exchange truth
- Exchange reality vs persisted bot state after crashes / ambiguous outcomes
- Readiness preview truth vs stale/inactive runtime blockers
- Stop semantics vs actual flatten/cancel confirmation
