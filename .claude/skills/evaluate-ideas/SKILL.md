---
name: evaluate-ideas
description: Start a 2-hour idea evaluation session. Reviews candidate ideas from scout, assigns priority verdicts. No implementation.
---

# /evaluate-ideas

Launch the Evaluator Agent for a 2-hour idea evaluation session.

## Pre-flight checks

Before delegating, verify:
- `/var/www/development_ideas.jsonl` exists and has entries with status=candidate.

If no candidates exist, report this and exit.

## Delegation

Delegate to the `evaluator-agent` subagent with these instructions:

> You are starting a new evaluation session. Read `.claude/rules/opus-trader-core.md`, `.claude/rules/safety-boundaries.md`, and `.claude/rules/agent-file-contracts.md` for your operating rules and file contracts.
>
> Begin your 2-hour evaluation session now. Follow the full procedure: load candidate ideas, verify scout claims by reading actual code, score each idea, assign verdicts, update the ideas dashboard every 10 minutes.
>
> CRITICAL: Always verify critical claims by reading the actual code before accepting "X doesn't exist" or "Y is broken". Scout claims have a known error rate.

## Recommended terminal name: EVALUATOR
