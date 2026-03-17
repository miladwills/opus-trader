You are upgrading the existing AI Ops system inside Opus Trader from terminal-first operation into a dashboard-controlled AI Ops control plane.

Context:
- The existing AI Ops multi-agent setup already exists.
- Existing agents:
  - monitor-agent
  - fix-agent
  - promotion-gate
  - deploy-agent
  - scout-agent
  - evaluator-agent
  - planner-agent
  - implementer-agent
- Existing skills:
  - /monitor-live
  - /fix-queue
  - /gate-review
  - /deploy-approved
  - /scout-ideas
  - /evaluate-ideas
  - /plan-approved-ideas
  - /implement-approved-ideas
  - /setup-agent-files
- Existing workflows:
  - Incidents: Monitor -> Fixer -> Gate -> Deploy
  - Ideas: Scout -> Evaluator -> Planner -> Implementer -> Gate -> Deploy

Goal:
Build dashboard control for the AI Ops system so I can manage and run the workflow from the Opus Trader website without needing to open multiple terminals on my personal machine.

Critical architectural rules:
1. The source of truth must be a structured AI Ops state model, not markdown.
2. Markdown, summaries, and reports should remain secondary human-readable artifacts only.
3. Deploy must remain manual, explicit, gated, and auditable.
4. Agents must use controlled write paths and isolated execution contexts, not ad hoc shared file editing.
5. The dashboard must not execute arbitrary shell commands from free-form user input.
6. The dashboard must trigger typed backend actions and jobs only.
7. Keep AI Ops operationally separated from the live trading execution path. Do not create any path where AI workflow instability can directly affect trading safety.
8. Agents must not run endlessly. The system must provide explicit runtime controls, stop controls, bounded loop timing, and timeout protection.

What to build:

A) Backend AI Ops control layer
Implement a dedicated backend module/service for AI Ops orchestration with:
- structured state persistence
- typed workflow actions
- agent run tracking
- approvals
- deploy tracking
- audit logging
- live status broadcasting
- runtime controls for start/stop/pause/wait timing

Use the project’s existing architecture style where appropriate, but prefer a clean service-oriented design.

B) Structured state model
Create a canonical structured state model for:
- agents
- incidents
- ideas
- approvals
- deployments
- agent_runs
- agent_runtime_controls

Each entity should have stable ids, timestamps, statuses, owner references, and auditable transitions.

Minimum required fields:

1. agents
- id
- slug
- display_name
- enabled
- desired_state
- runtime_state
- status
- current_run_id
- current_job_kind
- current_title
- last_heartbeat_at
- blocked_reason
- updated_at

Notes:
- enabled: whether the agent is allowed to run
- desired_state: running, stopped, paused
- runtime_state: starting, running, idle, paused, stopping, stopped, blocked, failed

2. incidents
- id
- title
- summary
- source (auto_monitor or operator_manual)
- severity
- priority
- owner_agent
- status
- triage_status
- gate_status
- deploy_status
- operator_action_required
- blocked_reason
- related_run_ids
- created_at
- updated_at

3. ideas
- id
- title
- summary
- source
- priority
- status
- evaluator_status
- planner_status
- implementer_status
- gate_status
- deploy_status
- related_run_ids
- created_at
- updated_at

4. approvals
- id
- entity_type
- entity_id
- approval_kind
- requested_by
- status
- approved_by
- rejected_reason
- created_at
- updated_at

5. deployments
- id
- source_entity_type
- source_entity_id
- target_branch
- target_environment
- status
- started_at
- finished_at
- result_summary
- created_at
- updated_at

6. agent_runs
- id
- agent_slug
- workflow_type
- entity_type
- entity_id
- status
- started_at
- finished_at
- logs_path
- patch_path
- report_path
- worktree_path
- exit_code
- stop_requested
- stop_reason
- timeout_at
- created_at
- updated_at

7. agent_runtime_controls
- id
- agent_slug
- auto_run_enabled
- poll_interval_seconds
- idle_sleep_seconds
- retry_backoff_seconds
- max_run_seconds
- max_consecutive_runs
- max_failures_before_auto_pause
- default_timeout_seconds
- cooldown_seconds
- updated_by
- updated_at

C) Typed actions only
Implement backend endpoints/actions such as:
- create_incident
- submit_manual_incident
- triage_incident
- run_fix_agent
- request_gate_review
- approve_gate_item
- reject_gate_item
- enqueue_deploy
- run_deploy
- create_idea
- evaluate_idea
- plan_idea
- implement_idea

Also implement runtime control actions:
- start_agent
- stop_agent
- pause_agent
- resume_agent
- stop_all_agents
- pause_all_agents
- resume_all_agents
- update_agent_runtime_controls
- request_run_stop
- clear_agent_failure_state

Do not add arbitrary shell execution endpoints.

D) Worker orchestration
Build a worker/supervisor mechanism on the VPS that:
- launches the correct agent for the typed job
- attaches the correct skill/hook context
- stores run metadata
- updates structured state
- writes secondary markdown/report artifacts if needed
- uses isolated worktrees or equivalent isolated controlled write paths

Each run must have:
- a run record
- a clear status lifecycle
- bounded logs
- failure capture
- auditability
- cooperative stop checks
- timeout enforcement

Important runtime safety requirements:
- Do not use endless uncontrolled loops.
- Do not leave agents running forever without stop checks.
- Any polling loop must respect configured intervals from structured runtime controls.
- Any running agent must periodically check for stop_requested or desired_state changes.
- Support graceful stop first, then forced stop if the timeout is exceeded.
- Support automatic pause/stop after repeated failures.
- Support global Stop All / Pause All from the dashboard.
- Support per-agent wait/sleep timing from the dashboard so agents do not run continuously without control.
- Prefer bounded cycles or scheduled ticks over naive infinite bash loops.
- If bash wrappers exist, they must read structured control values and must not hardcode infinite unmanaged behavior.

E) Dashboard UI
Add a new main dashboard section/tab:
- AI Ops

Inside AI Ops, build:

1. Agent status strip
Show all agents with:
- running / idle / paused / stopped / blocked / failed / starting / stopping
- current task title
- last heartbeat
- enabled/disabled signal

2. Agent controls panel
For each agent provide:
- Start
- Stop
- Pause
- Resume
- Clear failure state
- runtime control values:
  - poll interval
  - idle sleep
  - retry backoff
  - cooldown
  - max run time
  - max consecutive runs
  - max failures before auto-pause

Also provide global controls:
- Start All allowed agents
- Pause All
- Stop All

These controls must be explicit and clearly reflect current state.

3. Incidents panel
Show incident list with:
- title
- severity
- priority
- owner
- status
- blocked / deployable / operator-action-required
- latest transition time

Include filters and compact operator-friendly layout.

4. Manual incident input
Add a small operator form to create incidents manually:
- title
- summary
- severity
- priority
- submit

Manual flow should be:
Operator -> Monitor triage -> Fixer -> Gate -> Deploy

5. Approval queue
Show all approval-required items with:
- linked incident/idea
- patch/report/test status
- approve / reject / request changes actions

6. Deploy queue / deploy progress
Show:
- ready to deploy
- deploying
- deployed
- failed
- manual deploy action
- deployment audit history

7. Ideas pipeline
Show idea flow:
- New
- Evaluating
- Planned
- Implementing
- Waiting Gate
- Deployable
- Shipped

F) UX rules
- Keep the interface compact, clean, and low-noise.
- Avoid verbose descriptive text.
- Prefer tight labels, status chips, compact cards/tables, and drawers/modals for detail.
- Make the key signal understandable in a few seconds.
- Do not clutter the page with long explanations.

G) Safety rules
- No auto deploy
- No direct production edits from the UI
- No arbitrary shell command execution from the dashboard
- No shared uncontrolled writes across agents
- Keep approval and deploy actions explicit and auditable
- Keep AI Ops isolated from live trading safety-critical runtime paths
- Respect stop/pause requests quickly and reliably
- Prevent infinite uncontrolled execution
- Runtime control changes must be persisted and auditable

H) Implementation expectations
Please implement this in real code, integrated into the current Opus Trader codebase.
Do not stop at a design-only answer.

Deliver:
1. the implementation
2. a concise architecture summary
3. exact file list changed
4. exact UI location of every UI addition
5. a short non-technical change summary
6. tests for the core orchestration/state transitions and runtime controls
7. a packaged zip of the updated project excluding venv and existing zip files

Before changing code:
- inspect the existing project structure
- find the current dashboard layout, backend app entrypoints, service patterns, persistence patterns, and any existing AI Ops related files
- reuse what is already good
- avoid unnecessary rewrites

Important:
- do not replace the current human-readable reports; keep them as secondary outputs
- the structured state model must become the primary source of truth
- favor incremental integration over a giant risky rewrite
- if needed, implement this in phases internally, but complete the end-to-end first usable version in one pass