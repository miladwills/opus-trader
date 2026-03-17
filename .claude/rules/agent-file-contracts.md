# Agent File Contracts

Shared file schemas, statuses, and update rules for all agents.

## issues_queue.jsonl

One JSON object per line. Each line is one issue.

### Core fields (set by Monitor Agent)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| issue_id | string | yes | Format: MON-NNN |
| created_at | ISO 8601 | yes | When first observed |
| updated_at | ISO 8601 | yes | Last modification |
| status | string | yes | See status values below |
| severity | string | yes | critical, high, medium, low |
| category | string | yes | state, execution, risk, latency, config, logic, diagnostics, process, runtime_pattern, integrity, watchdog, code_review |
| affected_bot_ids | string[] | yes | Bot UUIDs or empty array |
| symbols | string[] | yes | Trading symbols or empty array |
| summary | string | yes | One-line description |
| symptom | string | yes | What was observed |
| evidence | string[] | yes | File:line refs, log excerpts, data points |
| suspected_root_cause | string | yes | Best current hypothesis |
| root_cause_confidence | string | yes | high, medium, low |
| profit_impact | string | yes | high, medium, low, none, unknown |
| safety_impact | string | yes | critical, high, medium, low, none, unknown |
| operator_truthfulness_impact | string | yes | high, medium, low, none |
| auto_fix_allowed | boolean | yes | Whether automated fix is permitted |
| fix_scope_hint | string | yes | state, execution, risk, logic, diagnostics, review, process |
| notes_for_fixer | string | yes | Guidance for Fix Agent |

### Fix/Gate fields (added by Fix Agent or Promotion Gate)

| Field | Type | Description |
|-------|------|-------------|
| confirmed_root_cause | string | Verified root cause |
| changed_files | string[] | Files modified by fix |
| branch_name | string | Fix branch name |
| validation_run | string | Test command and result summary |
| focused_test_results | string | Targeted test output |
| replay_or_shadow_results | string | Paper/shadow/replay evidence |
| regression_risk | string | What could break |
| rollback_plan | string | How to undo |
| exact_ui_location_if_any | string | UI element affected |
| fixer_summary | string | Fix Agent notes |
| promotion_gate_status | string | Gate verdict |
| promotion_gate_reason | string | Gate rationale |
| approved_scope | string | What scope is approved |
| additional_validation_required | string | What else is needed |
| reviewer_summary | string | Gate reviewer notes |

### Issue statuses

| Status | Meaning |
|--------|---------|
| open | Detected, not yet investigated |
| investigating | Fix Agent is analyzing |
| root_cause_confirmed | Root cause found, fix not started |
| fix_in_progress | Fix Agent is patching |
| fixed | Patch applied, awaiting gate review |
| proposal_only | Idea/observation, no fix needed |
| reviewed | Gate has reviewed |
| approved | Gate approved for promotion |
| rejected | Gate rejected |
| closed | Resolved or no longer applicable |

---

## development_ideas.jsonl

One JSON object per line. Each line is one idea.

### Core fields (set by Scout Agent)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| idea_id | string | yes | Format: SCOUT-NNN |
| created_at | ISO 8601 | yes | When proposed |
| updated_at | ISO 8601 | yes | Last modification |
| status | string | yes | See status values below |
| title | string | yes | Short descriptive title |
| theme | string | yes | execution, risk, grid, readiness, sizing, diagnostics, analytics, state, ui, operator_control |
| problem_detected | string | yes | What problem this addresses |
| evidence | string[] | yes | File:line refs, log data, measurements |
| proposed_improvement | string | yes | What to do |
| expected_value | string | yes | profit, safety, truthfulness, operator_clarity, multi-benefit |
| expected_impact | string | yes | high, medium, low |
| implementation_cost | string | yes | high, medium, low |
| risk_level | string | yes | high, medium, low |
| affected_areas | string[] | yes | Files or services affected |
| why_now | string | yes | Why this matters now |
| notes_for_evaluator | string | yes | Guidance for Evaluator Agent |

### Evaluator fields (added by Evaluator Agent)

| Field | Type | Description |
|-------|------|-------------|
| evaluator_status | string | Evaluator verdict |
| evaluator_summary | string | Evaluation rationale |
| evaluator_confidence | string | high, medium, low |
| priority_score | integer | 1-10 |
| value_score | integer | 1-10 |
| complexity_score | integer | 1-10 |
| risk_score | integer | 1-10 |
| recommendation | string | pursue_now, pursue_later, needs_more_evidence, reject |
| implementation_shape | string | small_patch, medium_feature, large_feature, architecture_project |
| overlap_notes | string | Related ideas or existing features |
| challenge_notes | string | Implementation risks |
| next_step | string | What to do next |

### Idea statuses

| Status | Meaning |
|--------|---------|
| candidate | Proposed by Scout, not yet evaluated |
| APPROVED_HIGH_PRIORITY | Evaluator approved, pursue now |
| APPROVED_MEDIUM_PRIORITY | Evaluator approved, pursue soon |
| APPROVED_LOW_PRIORITY | Evaluator approved, when convenient |
| DEFERRED | Good idea, needs prerequisites |
| REJECTED | Not worth pursuing |
| REDUNDANT | Already implemented or duplicate |
| NEEDS_MORE_EVIDENCE | Insufficient evidence to decide |
| FUTURE_ROADMAP | Long-term consideration |

---

## monitor_report.md

Human-readable report maintained by Monitor Agent.

### Required sections
1. Header: monitor start time, last updated, update count, next update
2. Current Health Snapshot: table of component statuses
3. New Findings Since Last Update
4. Repeated Patterns: table of recurring events
5. Highest-Risk Open Issues: table with severity and trend
6. Issues Handed to Fix Agent
7. Questions Still Unproven
8. Fix Agent Notes (if applicable)
9. Promotion Gate Notes (if applicable)
10. Final Handoff Summary (at end of window)

---

## development_ideas.md

Human-readable report maintained by Scout and Evaluator Agents.

### Required sections
1. Header: evaluator status, last evaluation pass, totals
2. Current Queue Status: table of counts by verdict
3. New Candidate Ideas
4. Newly Reviewed Ideas
5. Approved Ideas by Priority (HIGH / MEDIUM / LOW tables)
6. Deferred / Rejected Ideas
7. Repeated Opportunity Themes
8. Open Questions
9. Final Handoff Summary (at end of window)

---

## Update Rules

1. Only append new lines to .jsonl files. Never rewrite the entire file.
2. To update an existing entry, append a new line with the same ID and updated fields.
3. The latest line for a given ID is authoritative.
4. Always update the `updated_at` field when modifying an entry.
5. Reports (.md files) may be fully rewritten on each update cycle.
6. All timestamps must be ISO 8601 with timezone.
7. Do not invent new fields beyond what is defined here.
