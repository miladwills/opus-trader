# Implementation Plan: Trading Bot Audit and Safety Improvements

**Branch**: `001-trading-bot-audit` | **Date**: 2026-01-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-trading-bot-audit/spec.md`

## Summary

This audit addresses critical UI bugs, frontend code redundancy, and trading bot safety improvements. The primary requirement is to fix the $0.00 available balance display bug, consolidate overlapping JavaScript files, and implement anti-churn protections for grid recentering. Technical approach involves targeted fixes to existing Flask/JavaScript codebase with minimal architectural changes - keeping controllers thin and business logic in services per repo guidelines.

## Technical Context

**Language/Version**: Python 3.8+ (compatible with Flask>=2.3.0, tested up to 3.12)  
**Primary Dependencies**: Flask>=2.3.0, requests>=2.28.0, python-dotenv>=1.0.0, pandas (unlisted but used)  
**Storage**: JSON file-based (`storage/bots.json`, `storage/risk_state.json`, `storage/trade_logs.json`, etc.)  
**Testing**: pytest with fixtures (tests/ directory, 13 test files, mocked services)  
**Target Platform**: Windows primary (start.bat), cross-platform compatible (Unix file locking support)  
**Project Type**: Web application (Flask backend + Tailwind/JS frontend dashboard)  
**Performance Goals**: Bot cycle execution ~5-10s, dashboard polling without lag  
**Constraints**: Minimal architectural changes, keep controllers thin, restart services after changes  
**Scale/Scope**: Single-user trading dashboard, multiple concurrent bots per symbol

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution template contains placeholders only. No specific gates defined. Proceeding with industry best practices:

| Gate | Status | Notes |
|------|--------|-------|
| Library-First | N/A | Not applicable - modifying existing services, not creating new libraries |
| CLI Interface | N/A | Not applicable - changes to web dashboard and backend services |
| Test-First | ADVISORY | Repo guidelines state "no formal automated suite" but recommend pytest for future tests |
| Integration Testing | ADVISORY | Manual verification per AGENTS.md checklist |
| Simplicity | PASS | Changes are targeted fixes, not architectural rewrites |

## Project Structure

### Documentation (this feature)

```text
specs/001-trading-bot-audit/
├── spec.md              # Feature specification (complete)
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── api-changes.yaml # API contract changes
└── checklists/
    └── requirements.md  # Specification quality checklist (complete)
```

### Source Code (repository root)

```text
# Existing structure - files to modify
config/
├── config.py            # Credentials, auth (no changes needed)
└── strategy_config.py   # Add kill-switch toggle, update defaults

services/
├── grid_bot_service.py      # Recenter gating, out-of-range logic, scalp cooldowns
├── grid_bot_service_lf.py   # Low-frequency variant (align with main service)
├── neutral_grid_service.py  # Recenter logic authority for neutral_classic
├── neutral_loss_prevention_service.py  # Ensure enforcement, momentum filter
├── scalp_pnl_service.py     # Fee-aware thresholds, no-trade gating
├── risk_manager_service.py  # Re-enable kill-switch, position limits
├── stop_loss_service.py     # Verify consistent UPnL SL across modes
└── take_profit_service.py   # Verify consistency

static/js/
├── app_v5.js            # Base helpers (reference only)
├── app_lf.js            # Fix available balance, colspan, direction-change safety
└── [app.js, app_bundled.js removed from active use]

templates/
└── dashboard.html       # Cache-buster bump after JS changes

app.py                   # Add trend_direction structured field if needed
runner.py                # No changes expected

storage/
├── bots.json            # Add recenter_last_ts field to bot state
└── risk_state.json      # Add kill-switch triggered state
```

**Structure Decision**: Existing Flask web application structure maintained. All changes are modifications to existing files in `services/`, `static/js/`, and `config/`.

## Complexity Tracking

No constitution violations requiring justification. All changes follow existing patterns:
- Business logic in services/ (not controllers)
- Targeted diffs (not broad rewrites)
- JSON file storage (existing pattern)
