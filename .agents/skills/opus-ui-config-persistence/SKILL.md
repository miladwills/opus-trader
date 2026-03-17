---
name: opus-ui-config-persistence
description: Diagnose and fix Opus Trader config save bugs across frontend, API, storage, normalization, and reload flow, especially boolean checkbox persistence.
---

Trace the full round-trip:
`UI -> payload -> backend -> validation -> merge -> storage -> reload -> UI`

Always inspect:
- unchecked checkbox handling
- false values dropped by missing-field logic
- popup config vs normal config path differences
- backend field allowlists
- storage normalization overwriting booleans
- stale refresh after save

Success criteria:
- on stays on after reload
- off stays off after reload
- UI only says saved after real persistence succeeds

Workflow:
1. Inspect the live frontend path in `templates/dashboard.html` and `static/js/app_lf.js` first.
2. Trace the exact payload and normalization path through API handlers and storage services.
3. Verify persisted state, reload behavior, and edit-form hydration instead of trusting toasts or optimistic UI messages.
4. Fix false-dropping behavior structurally, not with frontend-only patches unless the defect is strictly client-side.
