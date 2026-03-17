---
name: bot-status-polish
description: Improve Bot Status modal and live log UX
---

# Bot Status Polish

Refactor the Bot Status modal for structured live logs, readable hierarchy, filters/toggles, stable live updates, and mobile-safe layout.

## Rules

1. **Preserve functionality** - All existing data, actions, and trading behavior must remain intact
2. **Frontend-first** - Prefer template/CSS/JS changes over backend changes
3. **Stable live updates** - Logs and status should update incrementally without scroll jumps or full rerenders
4. **Mobile-safe** - Modal must be usable on narrow screens

## Focus Areas

- Log readability: structured entries, clear timestamps, severity indicators
- Hierarchy: bot identity and status prominent, logs secondary
- Filters/toggles: allow filtering log severity or categories
- Scroll behavior: auto-scroll to newest unless user has scrolled up
- Mobile layout: full-width modal, readable text, touch-friendly controls

## Process

1. Read the current Bot Status modal code in `static/js/app_lf.js` and `templates/dashboard.html`
2. Identify hierarchy, readability, and responsiveness issues
3. Propose a plan before implementing
4. Implement surgically
5. Verify on desktop and narrow/mobile widths
