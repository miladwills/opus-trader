---
name: deploy-approved
description: Deploy gate-approved fixes after verifying promotion gate verdict and interactive human confirmation. Refuses deployment if eligibility conditions are not met.
---

# /deploy-approved

Launch the Deploy Agent to promote gate-approved fixes to production.

## Pre-flight checks

Before delegating, verify:
- `/var/www/issues_queue.jsonl` exists and has entries with `promotion_gate_status=APPROVE_FOR_STAGED_PRODUCTION_AFTER_HUMAN_APPROVAL`.

If no gate-approved issues exist, report this and exit.

## Delegation

Delegate to the `deploy-agent` subagent with these instructions:

> You are starting a deployment session. Read `.claude/rules/opus-trader-core.md` and `.claude/rules/safety-boundaries.md` for your operating rules.
>
> Check all 6 eligibility conditions for each candidate issue. Present a pre-deploy summary for each eligible issue. Ask the operator "Deploy this approved item now? (yes/no)" and only proceed on a clear "yes".
>
> You may NOT deploy without gate approval. You may NOT deploy without explicit in-session confirmation. You may NOT include unrelated changes. Revert immediately if post-merge validation fails.

## Recommended terminal name: DEPLOY
