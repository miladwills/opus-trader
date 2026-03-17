---
name: opus-live-audit
description: Audit Opus Trader for trading-risk bugs, feature collisions, stale state, entry lateness, grid issues, and runtime contradictions using code, logs, bot state, and trade logs.
---

You are auditing Opus Trader as a live trading system, not just a codebase.

Always prioritize:
1. live trading loss risks
2. stale or contradictory state
3. entry lateness
4. grid placement / recenter correctness
5. feature collisions
6. false success / fail-open safety paths

Primary files to inspect first:
- `services/grid_bot_service.py`
- `services/entry_gate_service.py`
- `services/entry_readiness_service.py`
- `services/neutral_loss_prevention_service.py`
- `services/neutral_grid_service.py`
- `services/scalp_pnl_service.py`
- `services/bot_manager_service.py`
- `services/bot_storage_service.py`
- `services/bybit_client.py`
- `services/bybit_stream_service.py`
- `config/strategy_config.py`
- `storage/bots.json`
- `storage/trade_logs.json`
- `storage/runner.log`
- `storage/app.log`
- `storage/runtime_snapshot_bridge.json`
- `storage/audit_diagnostics.jsonl`

Workflow:
1. Read the live-contract notes in `AGENTS.md` before drawing conclusions.
2. Correlate code paths with current runtime state and recent logs.
3. Confirm issues with direct evidence; do not speculate beyond what the code or runtime files support.
4. Separate structural defects from stale state, operator tuning, and one-off exchange/runtime noise.
5. Treat same-symbol ownership, attribution, and fail-open behavior as first-class audit targets.

Audit output must include:
- Executive summary
- Confirmed issues only where evidence exists
- Severity and confidence
- Entry lateness report
- Grid/recenter report
- Exit safety report
- Feature collision map
- Safe patch plan
