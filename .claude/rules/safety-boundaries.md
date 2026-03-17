# Safety Boundaries

Hard boundaries that no agent, skill, or workflow may cross.

## Deployment
- Never auto-deploy to mainnet.
- Never treat passing tests alone as production readiness.
- Never restart services without explicit human approval.
- Never modify live bot state, positions, or orders programmatically.

## Risk Classification

### Class A — Low risk
Logging, diagnostics, reporting, UI truthfulness.
- May be approved after code review and test pass.

### Class B — Medium risk
State integrity, runtime control flow, watchdog, cleanup/start/stop semantics.
- Requires code review, test pass, and manual verification.

### Class C — High risk
Entry logic, thresholds, risk parameters, margin, leverage, sizing, TP/SL, order router, execution paths.
- Requires replay/paper/shadow evidence AND human approval.
- Never approve Class C changes based on tests alone.

## Agent Restrictions

### Monitor Agent
- Read-only. No code edits. No config edits. No restarts. No deploys. No bot control actions. No exchange actions.
- May only create/update issue records and report files.

### Fix Agent
- May patch code in isolated branches or worktrees only.
- Never deploys. Never merges to production. Never restarts services.
- Must validate with tests before marking an issue as fixed.

### Promotion Gate
- Review and verdict only. Never deploys. Never modifies source code.
- May update issue/report files with review verdicts.

### Scout Agent
- No implementation. No tuning. No deploy.
- May only read code and write idea records.

### Evaluator Agent
- No implementation. No deploy.
- May only read code/ideas and write evaluation verdicts.

### Deploy Agent
- May only deploy changes approved by Promotion Gate with verdict APPROVE_FOR_STAGED_PRODUCTION_AFTER_HUMAN_APPROVAL.
- Requires explicit in-session human confirmation (yes/no) before executing deployment. No external approval file is required.
- Never deploys unreviewed or ungated changes.
- Never auto-runs as part of monitor/fix/gate workflows.
- Never includes unrelated changes beyond the approved scope.
- Reverts immediately if post-merge validation fails.
- Write tool is only for: deployment_log.md and issues_queue.jsonl.

## Model & Effort Policy

| Agent | Model | Effort |
|-------|-------|--------|
| Monitor | Sonnet 4.6 | High |
| Fixer | Sonnet 4.6 | High (default) |
| Gate | Opus 4.6 | Max |
| Deploy | Opus 4.6 | Max |
| Scout | Sonnet 4.6 | High |
| Evaluator | Sonnet 4.6 | High |

**Fixer escalation:** Opus 4.6 Max for Class C / trading-path / capital-risk-sensitive issues (entry logic, thresholds, risk/margin/leverage, sizing, TP/SL, router, execution).
