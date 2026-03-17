---
name: active-bots-polish
description: Improve Active Bots card hierarchy and readability
---

# Active Bots Polish

Improve the Active Bots card layout for better scannability and visual hierarchy.

## Design Goals

- **Symbol dominant** - Symbol name should be the most prominent element
- **Badges tiered** - Status, mode, and feature badges visually tiered by importance
- **KPIs clearer** - PnL, position size, range displayed with clear labels and formatting
- **Notes quieter** - Informational notes and secondary text should not compete with primary data
- **Actions visible** - Start/stop/pause/delete buttons accessible but not visually dominant
- **Responsive** - Cards should be easy to scan on all screen widths

## Rules

1. **Preserve behavior** - All actions, data bindings, and event handlers must remain functional
2. **Data correctness** - No changes to how data is fetched, computed, or displayed
3. **Reuse tokens** - Use existing CSS design tokens and utility classes
4. **Surgical changes** - Minimal diff, focused on hierarchy and spacing

## Process

1. Read bot card rendering code in `static/js/app_lf.js`
2. Read related styles in `templates/dashboard.html`
3. Propose hierarchy improvements before implementing
4. Implement and verify desktop + narrow/mobile layout
