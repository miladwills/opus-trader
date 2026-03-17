---
name: pnl-popup-refactor
description: Refactor Closed PnL History popup for responsive UX and stable live updates
---

# PnL Popup Refactor

Improve the Closed PnL History popup layout, stats hierarchy, filter controls, desktop table readability, and mobile layout.

## Design Goals

- Stats summary prominent at the top
- Filter controls compact and intuitive
- Desktop: clean table with aligned columns, readable numbers
- Mobile: card-based or stacked layout instead of horizontal table
- Live updates should be incremental (delta), not full rerender
- Preserve filters, pagination, and scroll context across updates

## Rules

1. **Preserve functionality** - Filters, pagination, sorting, and data must remain correct
2. **Backend minimal** - Keep backend changes to absolute minimum; prefer frontend restructuring
3. **Incremental updates** - Prefer delta/incremental DOM updates over full innerHTML replacement
4. **Scroll preservation** - User's scroll position and filter state must survive live updates

## Process

1. Read the PnL popup rendering code in `static/js/app_lf.js`
2. Read related styles and HTML structure in `templates/dashboard.html`
3. Identify rerender, responsiveness, and hierarchy issues
4. Propose a plan before implementing
5. Implement and verify: desktop table, mobile layout, live update stability
