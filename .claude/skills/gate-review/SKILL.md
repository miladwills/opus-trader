---
name: gate-review
description: Start a 4-hour promotion gate session. Reviews fixed/proposed issues, assigns promotion verdicts. Never deploys or modifies code.
---

# /gate-review

Launch the Promotion Gate Agent for a 4-hour review session.

## Pre-flight checks

Before delegating, verify:
- `/var/www/issues_queue.jsonl` exists and has entries with status=fixed or proposal_only.

If no eligible issues exist, report this and exit.

## Delegation

Delegate to the `promotion-gate` subagent with these instructions:

> You are starting a new gate review session. Read `.claude/rules/opus-trader-core.md`, `.claude/rules/safety-boundaries.md`, and `.claude/rules/agent-file-contracts.md` for your operating rules and file contracts.
>
> Begin your 4-hour review session now. Follow the full procedure: load queue, review each fixed/proposed issue, classify risk, assign verdict, record rationale. Check for new eligible issues every 5 minutes.
>
> You may NOT modify source code. You may NOT deploy. Your highest approval requires human involvement.

## Recommended terminal name: GATE
