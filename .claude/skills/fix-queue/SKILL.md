---
name: fix-queue
description: Start a 4-hour fix session. Consumes issues_queue.jsonl, investigates root causes, patches in isolated branches. Never deploys.
---

# /fix-queue

Launch the Fix Agent for a 4-hour issue-fixing session.

## Pre-flight checks

Before delegating, verify:
- `/var/www/issues_queue.jsonl` exists and has entries.
- There are issues with status=open or root_cause_confirmed and auto_fix_allowed=true.

If the queue is empty or has no eligible issues, report this and exit.

## Delegation

Delegate to the `fix-agent` subagent with these instructions:

> You are starting a new fix session. Read `.claude/rules/opus-trader-core.md`, `.claude/rules/safety-boundaries.md`, and `.claude/rules/agent-file-contracts.md` for your operating rules and file contracts.
>
> Begin your 4-hour fix session now. Follow the full procedure: load queue, pick highest-severity eligible issue, investigate, patch in isolated branch, validate, update records. Check for new issues every 5 minutes.
>
> Work in a git branch named `fix/MON-NNN-short-description`. Never merge to main. Never deploy.

## Recommended terminal name: FIXER
