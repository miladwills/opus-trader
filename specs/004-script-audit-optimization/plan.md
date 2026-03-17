# Implementation Plan: Full Script Audit and Optimization

**Branch**: `004-script-audit-optimization` | **Date**: Wed Jan 14 2026 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-script-audit-optimization/spec.md`

## Summary

The project requires a full safety audit and optimization of the Bybit trading bot. Key objectives include eliminating runtime errors (e.g., `bot_id` undefined in close paths), consolidating redundant service files, hardening the neutral grid recenter logic with a zero-tolerance safety guard (no recenter if position > 0), and fixing the frontend "Available Balance" display in the positions table.

## Technical Context

**Language/Version**: Python 3.11, JavaScript (ES6+)  
**Primary Dependencies**: Flask, Requests, Bybit API V5  
**Storage**: JSON-based storage (`/storage/*.json`)  
**Testing**: Manual E2E on testnet; verification of log integrity; regression checks for redundant file removal.  
**Target Platform**: VPS (Linux/Windows server)
**Project Type**: Single project (Web Application)  
**Performance Goals**: Reduction of churn-based fee bleed; sub-second UI updates for balance data.  
**Constraints**: Zero-tolerance recentering (Must NOT recenter if any position > 0).  
**Scale/Scope**: System-wide audit and core service optimization.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I: Library-First**: Audit focuses on self-contained services in `services/`.
- **Principle II: CLI Interface**: Runner logic remains text-based and log-heavy for observability.
- **Principle III: Test-First**: Fixes will be verified by observing specific failure modes (e.g., triggering emergency closes).
- **Principle IV: Integration Testing**: Full loop verification between `runner.py` and `BybitClient`.

## Project Structure

### Documentation (this feature)

```text
specs/004-script-audit-optimization/
├── plan.md              # This file
├── research.md          # Audit findings and decisions
├── data-model.md        # Balance mapping and bot state entities
├── quickstart.md        # Guide for running the audit suite
├── contracts/           # API contract for positions balance
└── checklists/
    └── requirements.md  # Spec validation
```

### Source Code (repository root)

```text
app.py                  # API endpoints (/api/positions)
runner.py               # Bot execution cycle
services/               # Audit target: core logic
├── account_service.py  # Balance fetching
├── bybit_client.py     # API implementation
├── grid_bot_service.py # Core bot logic
└── neutral_grid_service.py # Recenter safety
static/js/app.js        # UI balance display
```

**Structure Decision**: Single project structure is preserved. The audit will prioritize merging redundant `*_lf.py` or `*_remote.py` files into standard versions.
