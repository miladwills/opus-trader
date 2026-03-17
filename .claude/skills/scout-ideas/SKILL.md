---
name: scout-ideas
description: Start a 2-hour idea discovery session. Analyzes codebase for improvement opportunities. No implementation — ideas only.
---

# /scout-ideas

Launch the Scout Agent for a 2-hour development idea discovery session.

## Pre-flight checks

Before delegating, verify these files exist:
- `/var/www/development_ideas.md`
- `/var/www/development_ideas.jsonl`

If either is missing, create an empty one.

## Delegation

Delegate to the `scout-agent` subagent with these instructions:

> You are starting a new scouting session. Read `.claude/rules/opus-trader-core.md`, `.claude/rules/safety-boundaries.md`, and `.claude/rules/agent-file-contracts.md` for your operating rules and file contracts.
>
> Begin your 2-hour discovery session now. Follow the full procedure: load existing ideas, pick a codebase area to analyze, verify claims before writing, propose ideas with evidence, update the ideas dashboard every 10 minutes.
>
> CRITICAL: Always verify claims with grep/read before asserting "X doesn't exist". Previous scout sessions had a 16% factual error rate on unverified claims.

## Recommended terminal name: SCOUT
