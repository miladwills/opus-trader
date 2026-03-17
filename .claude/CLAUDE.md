# Opus Trader — Claude Code Workflow

This project uses reusable Claude Code subagents instead of pasting long prompts.

## Agents

| Agent | Purpose | Window | Cadence | Restrictions |
|-------|---------|--------|---------|-------------|
| monitor-agent | Observe system health, detect issues | 4h | 5 min | Read-only, no code edits |
| fix-agent | Investigate and patch issues | 4h | 5 min | Isolated branches only, no deploy |
| promotion-gate | Review patches, assign verdicts | 4h | 5 min | No code changes, no deploy |
| scout-agent | Discover improvement ideas | 2h | 10 min | No implementation |
| evaluator-agent | Evaluate and prioritize ideas | 2h | 10 min | No implementation |
| deploy-agent | Deploy gate-approved fixes | On-demand | Manual | Gate approval + in-session confirmation, no auto-run |

## Skills (slash commands)

| Command | What it does |
|---------|-------------|
| `/monitor-live` | Start 4h monitoring window |
| `/fix-queue` | Start 4h fix session from issue queue |
| `/gate-review` | Start 4h promotion gate review |
| `/scout-ideas` | Start 2h idea discovery session |
| `/evaluate-ideas` | Start 2h idea evaluation session |
| `/setup-agent-files` | Validate and normalize shared files |
| `/deploy-approved` | Deploy gate-approved fixes (interactive confirmation) |

## Shared Files

| File | Owner | Purpose |
|------|-------|---------|
| `monitor_report.md` | Monitor Agent | Current system health and issue summary |
| `issues_queue.jsonl` | Monitor + Fix + Gate | Issue tracking (one JSON per line) |
| `development_ideas.md` | Scout + Evaluator | Idea evaluation dashboard |
| `development_ideas.jsonl` | Scout + Evaluator | Idea records (one JSON per line) |
| `deployment_approval.md` | (deprecated) | Replaced by interactive in-session confirmation |
| `deployment_log.md` | Deploy Agent | Deployment audit trail |

## Rules

All agents follow the rules in `.claude/rules/`:
- `opus-trader-core.md` — Safety, truthfulness, change philosophy
- `safety-boundaries.md` — Hard boundaries, risk classes, agent restrictions
- `ui-summary-style.md` — Response and report style
- `agent-file-contracts.md` — File schemas, statuses, update rules

## File Contracts

- `.jsonl` files: append-only, latest line for a given ID wins
- `.md` reports: fully rewritten each update cycle
- Schemas defined in `.claude/rules/agent-file-contracts.md`

## Safety Hooks

- `block-sensitive-files.sh` — Blocks edits to trading-core files without explicit request
- `python-sanity.sh` — Syntax-checks edited Python files
- `ui-sanity.sh` — Reminds to verify UI after frontend edits
- `monitor-safety.sh` — Blocks destructive commands when monitor-agent is active

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
