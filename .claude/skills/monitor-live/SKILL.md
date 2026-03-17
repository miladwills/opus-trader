---
name: monitor-live
description: Start a 4-hour live monitoring window. Reads system state, detects issues, updates monitor_report.md and issues_queue.jsonl. Read-only — never edits code.
---

# /monitor-live

Launch the Monitor Agent for a 4-hour observe-only monitoring session.

## Pre-flight checks

Before delegating, verify these files exist:
- `/var/www/monitor_report.md`
- `/var/www/issues_queue.jsonl`

If either is missing, create an empty one.

## Delegation

Delegate to the `monitor-agent` subagent with these instructions:

> You are starting a new monitoring window. Read `.claude/rules/opus-trader-core.md`, `.claude/rules/safety-boundaries.md`, and `.claude/rules/agent-file-contracts.md` for your operating rules and file contracts.
>
> Begin your 4-hour monitoring session now. Follow the full procedure defined in your agent instructions: startup, observation cycles every 5 minutes, heartbeats, and shutdown with handoff summary.
>
> Current time context: check `date -u` at startup for accurate timestamps.

## Recommended terminal name: MONITOR
