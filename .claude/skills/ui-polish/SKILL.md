---
name: ui-polish
description: Polish dashboard UI without changing behavior
---

# UI Polish

Improve the visual hierarchy, spacing, readability, and responsive behavior of the specified dashboard area.

## Rules

1. **Preserve behavior** - Do not change event handlers, data flow, polling, or API calls
2. **Frontend only** - Avoid backend changes unless absolutely necessary for the UI fix
3. **Reuse tokens** - Use existing CSS design tokens (--sp-*, --fs-*, --radius-*, --surface-*) and utility classes (.dashboard-panel, .metric-box, .toolbar-chip, etc.) before creating new ones
4. **Surgical diffs** - Change only what is needed for the improvement

## Process

1. Identify affected files (typically `templates/dashboard.html` and/or `static/js/app_lf.js`)
2. Read the current code for the target area
3. Summarize the plan before making changes
4. Implement changes surgically
5. Verify: no overlap, no clipping, no awkward gaps, no broken mobile layout
6. Run syntax checks: CSS brace balance, `node -c` for JS, `py_compile` for any Python touched

## Verification Checklist

- [ ] Desktop layout looks correct
- [ ] Narrow/mobile layout is usable
- [ ] No text overlap or clipping
- [ ] No unnecessary whitespace or gaps
- [ ] Live-updating elements still update without full rerender
- [ ] No behavior changes
