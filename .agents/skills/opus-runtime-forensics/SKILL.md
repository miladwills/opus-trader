---
name: opus-runtime-forensics
description: Investigate Opus Trader runtime behavior from logs, bot state, trade logs, and diagnostics to explain losses, missed entries, stale state, and unexpected decisions.
---

Perform runtime forensics, not generic code review.

Correlate:
- `runner.log`
- `app.log`
- `bots.json`
- `trade_logs.json`
- `audit_diagnostics.jsonl`
- `runtime_snapshot_bridge.json`

Focus on:
- first valid setup vs actual entry
- blocker stack
- recenter expected vs actual
- stale cache / stale readiness
- config/runtime contradiction
- attribution gaps
- false error/success state persistence

Method:
1. Build a timeline from logs, bot snapshots, and trade records before reading large code sections.
2. Match runtime events to the exact persistence and decision paths that could produce them.
3. Distinguish structural defects from stale state, transient runtime drift, and pure tuning choices.
4. Prefer hard evidence such as timestamps, persisted fields, and tagged order attribution over narrative guesses.

Output:
- What happened
- Why it happened
- Evidence
- Whether the issue is structural, state-related, or tuning-related
