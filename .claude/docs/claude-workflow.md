# Opus Trader Claude Code Workflow

## What Was Created

A reusable multi-agent workflow for Opus Trader, configured entirely through project-level Claude Code files. No long prompts need to be pasted — just use slash commands.

### Directory Structure

```
.claude/
  CLAUDE.md                          # Workflow overview
  settings.json                      # Hook configuration
  rules/
    opus-trader-core.md              # Durable project rules
    safety-boundaries.md             # Hard safety boundaries
    ui-summary-style.md              # Response style guide
    agent-file-contracts.md          # Shared file schemas
  agents/
    monitor-agent.md                 # Live monitoring agent
    fix-agent.md                     # Issue fixing agent
    promotion-gate.md                # Patch review agent
    scout-agent.md                   # Idea discovery agent
    evaluator-agent.md               # Idea evaluation agent
    deploy-agent.md                  # Deployment agent (manual only)
    regression-reviewer.md           # (pre-existing)
    ui-reviewer.md                   # (pre-existing)
  skills/
    monitor-live/SKILL.md            # /monitor-live command
    fix-queue/SKILL.md               # /fix-queue command
    gate-review/SKILL.md             # /gate-review command
    scout-ideas/SKILL.md             # /scout-ideas command
    evaluate-ideas/SKILL.md          # /evaluate-ideas command
    setup-agent-files/SKILL.md       # /setup-agent-files command
    deploy-approved/SKILL.md         # /deploy-approved command
    (5 pre-existing skills preserved)
  hooks/
    block-sensitive-files.sh         # (pre-existing)
    python-sanity.sh                 # (pre-existing)
    ui-sanity.sh                     # (pre-existing)
    monitor-safety.sh                # NEW: blocks destructive commands during monitoring
  docs/
    claude-workflow.md               # This file
```

### Shared Runtime Files (project root)

```
monitor_report.md                    # Monitor Agent health report
issues_queue.jsonl                   # Issue tracking queue
development_ideas.md                 # Ideas evaluation dashboard
development_ideas.jsonl              # Ideas record store
deployment_approval.md               # (deprecated — replaced by interactive in-session confirmation)
deployment_log.md                    # Deployment audit trail
```

## How to Launch Each Workflow

### Option 1: Slash commands (recommended)

Open a Claude Code terminal and type the slash command:

```
/monitor-live      # Start monitoring
/fix-queue         # Start fixing issues
/gate-review       # Start reviewing patches
/scout-ideas       # Start discovering ideas
/evaluate-ideas    # Start evaluating ideas
/setup-agent-files # Validate shared files
/deploy-approved   # Deploy gate-approved fixes
```

### Option 2: Direct agent invocation

You can also invoke agents directly when you need custom instructions:

```
Use the monitor-agent to check system health right now.
Use the fix-agent to investigate MON-014 specifically.
Use the promotion-gate to review the fix for MON-001.
```

## Recommended Terminal Layout

For full-workflow operation, use 5 terminals:

| Terminal | Name | Command | Duration |
|----------|------|---------|----------|
| 1 | MONITOR | `/monitor-live` | 4 hours |
| 2 | FIXER | `/fix-queue` | 4 hours |
| 3 | GATE | `/gate-review` | 4 hours |
| 4 | SCOUT | `/scout-ideas` | 2 hours |
| 5 | EVALUATOR | `/evaluate-ideas` | 2 hours |
| 6 | DEPLOY | `/deploy-approved` | On-demand |

### Recommended operational pattern

1. Start MONITOR first — it populates the issue queue.
2. Start FIXER after ~15 minutes — once the queue has entries.
3. Start GATE after FIXER produces fixes — once issues reach status=fixed.
4. Start SCOUT independently — it reads the codebase, not the queue.
5. Start EVALUATOR after SCOUT produces candidates — once ideas reach status=candidate.
6. Start DEPLOY only when Gate has approved an issue. The deploy session will ask for interactive confirmation.

## What Each Agent Does

### Monitor Agent
- Reads system state every 5 minutes (runtime snapshots, logs, service status).
- Detects issues: orphaned positions, stale data, error states, log patterns.
- Writes findings to `monitor_report.md` and `issues_queue.jsonl`.
- Never touches code, config, or running services.

### Fix Agent
- Reads the issue queue, picks highest-severity eligible issue.
- Investigates root cause by reading code and logs.
- Patches in an isolated git branch (`fix/MON-NNN-description`).
- Validates with syntax checks and test suite.
- Updates the issue record with fix details.
- Never deploys or merges to production.

### Promotion Gate
- Reviews issues with status=fixed or proposal_only.
- Classifies risk (Class A/B/C).
- Assigns a promotion verdict (REJECT through APPROVE_FOR_STAGED_PRODUCTION).
- Class C changes always require replay/shadow evidence + human approval.
- Never touches code or deploys.

### Scout Agent
- Analyzes one codebase area per cycle (every 10 minutes).
- Looks for: safety gaps, profit opportunities, truthfulness issues, operator friction.
- Writes ideas to `development_ideas.md` and `development_ideas.jsonl`.
- Verifies all claims before writing (learned from 16% error rate in prior sessions).
- Never implements anything.

### Evaluator Agent
- Reviews candidate ideas from Scout.
- Verifies scout claims by reading actual code.
- Scores each idea (value, complexity, risk, priority).
- Assigns verdict and records rationale.
- Updates the ideas dashboard.
- Never implements anything.

### Deploy Agent
- Runs on-demand only via `/deploy-approved`. Never part of automated loops.
- Reads `issues_queue.jsonl` for gate-approved issues.
- Verifies all 6 eligibility conditions before offering deployment.
- Presents a pre-deploy summary and asks for interactive confirmation (yes/no).
- Merges fix branch to main, runs validation, restarts services.
- Reverts immediately if post-merge validation fails.
- Records deployment in `deployment_log.md` and closes the issue.
- Never deploys without gate approval AND in-session human confirmation.

## Safety Model

### Hooks
- **block-sensitive-files.sh**: Prevents accidental edits to trading-core files (grid_bot_service, runner, bybit_client, etc.).
- **monitor-safety.sh**: When `/tmp/opus_monitor_active` exists, blocks destructive Bash commands. Lock file is created/removed by the monitor skill.
- **python-sanity.sh**: Syntax-checks every Python file after edit.
- **ui-sanity.sh**: Reminds to verify UI after frontend edits.

### Agent restrictions
- Monitor: read-only + report writing only.
- Fix: can edit code but only in branches, never deploys.
- Gate: review and verdict only, no code changes.
- Scout/Evaluator: read and report only.
- Deploy: gate approval + in-session confirmation required. On-demand only.

### Risk classes
- **Class A** (logging/UI): approve after review + tests.
- **Class B** (state/control flow): approve after review + tests + manual verification.
- **Class C** (execution/risk/sizing): requires replay/shadow evidence + human approval.

## Agent Model & Effort Policy

| Agent | Model | Effort | Notes |
|-------|-------|--------|-------|
| Monitor | Sonnet 4.6 | High | Default daily operation |
| Fixer | Sonnet 4.6 | High | Default; escalates for trading-path issues |
| Gate | Opus 4.6 | Max | Always max scrutiny |
| Deploy | Opus 4.6 | Max | Always max scrutiny |
| Scout | Sonnet 4.6 | High | Default daily operation |
| Evaluator | Sonnet 4.6 | High | Default daily operation |

### Fixer Escalation Rule
Fixer escalates from Sonnet 4.6 High to **Opus 4.6 Max** when the issue touches entry logic, thresholds, risk/margin/leverage, sizing, TP/SL, order router, execution, or any change that can materially alter live trading behavior or capital risk (Class C).

### Design Principle
- Model and effort level follow risk and task complexity, not habit.
- Gate and Deploy are intentionally heavier — they make production-readiness and deployment decisions.
- Use Opus Max only where extra scrutiny materially matters.

## Troubleshooting

### Monitor safety hook blocking commands unexpectedly
The monitor safety hook checks for `/tmp/opus_monitor_active`. If a previous monitor session crashed without cleanup:
```bash
rm -f /tmp/opus_monitor_active
```

### Skills not appearing in slash commands
Claude Code discovers skills on startup. If new skills don't appear, restart the Claude Code session.

### Shared files getting large
The .jsonl files grow over time (append-only). To archive old entries:
```bash
# Keep only last 100 entries
tail -100 issues_queue.jsonl > issues_queue.jsonl.tmp && mv issues_queue.jsonl.tmp issues_queue.jsonl
```
