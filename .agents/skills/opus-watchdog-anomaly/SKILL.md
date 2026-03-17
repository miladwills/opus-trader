---
name: opus-watchdog-anomaly
description: Build and extend Opus Trader monitoring, invariants, contradiction detection, and anomaly diagnostics with minimal API and server overhead.
---

Build monitoring in an event-driven, throttled, low-overhead way.

Must support:
- blocker stack changes
- `first_valid_at` / `actual_entry_at`
- recenter expected vs actual
- stale cache warnings
- config/runtime contradiction checks
- range-state invariant checks
- exit reason tracing
- severity levels: `INFO` / `WARN` / `ERROR` / `CRITICAL`

Avoid:
- heavy polling
- duplicate API calls
- writing giant logs every cycle
- changing trading behavior unless explicitly required

Implementation pattern:
1. Start from the smallest authoritative event or state transition that can emit the signal.
2. Reuse existing runtime snapshots, storage helpers, and throttled diagnostics where possible.
3. Prefer explicit invariant checks over vague warning logs.
4. Keep the output usable for live forensics: timestamps, bot ID, symbol, severity, and contradiction details.
