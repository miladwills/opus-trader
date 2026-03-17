# Opus Trader Repo-Local Skills

These repo-local skills live under `.agents/skills/` and are intended to route recurring Opus Trader work into reusable, project-specific workflows instead of repeating long prompts.

## Quick Routing

- Use `opus-live-audit` for full repo audits, trading-risk reviews, feature collision reviews, and loss analysis.
- Use `opus-patch-review` for checking whether a claimed patch really exists in code and whether it introduced regressions.
- Use `opus-bugfix-surgical` for narrow hotfixes, crash fixes, and small structural bug repairs.
- Use `opus-runtime-forensics` for “why did this happen live?” investigations using logs/state.
- Use `opus-websocket-migration` for REST-to-WS migration planning and phased implementation.
- Use `opus-watchdog-anomaly` for monitoring, diagnostics, invariants, and anomaly detection work.
- Use `opus-ui-config-persistence` for save/reload/config checkbox/boolean persistence issues.
- Use `opus-skill-bootstrap` for creating or editing skills themselves.

## Skill Index

### `opus-live-audit`
- What it is for: Full live-system audits focused on trading risk, stale state, grid/recenter behavior, entry lateness, feature collisions, and fail-open paths.
- When to use it: When reviewing the repo as an actively running trading system rather than a static codebase.
- Example prompt starters:
  - `Use opus-live-audit to review recent live trading risks and stale-state contradictions.`
  - `Run opus-live-audit on the current repo and logs, then give me a safe patch plan.`

### `opus-patch-review`
- What it is for: Claim-by-claim verification that a patch is really present in code and did not introduce regressions.
- When to use it: After a bugfix, refactor, or claimed production patch that needs independent verification.
- Example prompt starters:
  - `Use opus-patch-review to verify this patch summary against the actual code.`
  - `Run opus-patch-review on the latest changes and mark each claim PASS, PARTIAL, or FAIL.`

### `opus-bugfix-surgical`
- What it is for: Small structural fixes that need to preserve live trading contracts and avoid broad behavior changes.
- When to use it: For hotfixes, narrow runtime bugs, or small code repairs where broad refactoring would be risky.
- Example prompt starters:
  - `Use opus-bugfix-surgical to fix this crash without changing trading semantics.`
  - `Apply opus-bugfix-surgical to this stale control-state bug and add a focused test if practical.`

### `opus-runtime-forensics`
- What it is for: Runtime timeline reconstruction using logs, state files, diagnostics, and trade records.
- When to use it: When the main question is why a live decision, missed entry, loss, or stale state happened.
- Example prompt starters:
  - `Use opus-runtime-forensics to explain why this bot entered late.`
  - `Run opus-runtime-forensics on the latest logs and tell me what happened and why.`

### `opus-websocket-migration`
- What it is for: Phased WebSocket-first migration planning and implementation without breaking existing safety contracts.
- When to use it: When moving public or private data flows away from REST-heavy behavior while keeping reconciliation and readiness semantics intact.
- Example prompt starters:
  - `Use opus-websocket-migration to plan the next WS migration phase.`
  - `Apply opus-websocket-migration to move this snapshot consumer off REST safely.`

### `opus-watchdog-anomaly`
- What it is for: Low-overhead monitoring, invariant checks, contradiction detection, and anomaly diagnostics.
- When to use it: When adding or extending runtime diagnostics, alerting signals, severity-tagged anomalies, or contradiction logging.
- Example prompt starters:
  - `Use opus-watchdog-anomaly to add recenter expected-vs-actual diagnostics.`
  - `Apply opus-watchdog-anomaly to track blocker stack changes with throttled severity logs.`

### `opus-ui-config-persistence`
- What it is for: End-to-end config save and reload debugging across frontend, API, storage, normalization, and UI hydration.
- When to use it: For boolean checkbox issues, save-to-reload mismatches, false-value persistence bugs, or stale post-save UI behavior.
- Example prompt starters:
  - `Use opus-ui-config-persistence to fix this checkbox not staying off after reload.`
  - `Run opus-ui-config-persistence on the bot edit form save path.`

### `opus-skill-bootstrap`
- What it is for: Creating, updating, organizing, and validating repo-local Codex skills for this project.
- When to use it: When the task itself is about adding or editing skill folders, `SKILL.md` files, or the skills index.
- Example prompt starters:
  - `Use opus-skill-bootstrap to add a new skill for Bybit reconciliation work.`
  - `Apply opus-skill-bootstrap to clean up overlapping repo-local skills and refresh the README.`
