# Architecture

## Overview

The watchdog runs as a standalone FastAPI service, completely isolated from Opus Trader. It monitors the trading platform through:

1. **HTTP probes** - calls safe read-only API endpoints
2. **File probes** - reads bridge JSON, runner lock, log file metadata
3. **Process probes** - checks systemd unit states
4. **Log probes** - tails log files and matches known error patterns

## Components

```
main.py (lifespan)
  |
  +-- ProbeScheduler
  |     +-- 11 probes (independent asyncio tasks)
  |           +-- HTTP: bootstrap, bridge_diag, services
  |           +-- File: bridge_json, runner_lock, log_freshness
  |           +-- Process: proc_trader, proc_runner, sys_resources
  |           +-- Log: log_runner, log_app -> IncidentClassifier
  |
  +-- HealthScorer (30s loop)
  |     +-- reads latest probe results
  |     +-- computes 5-component weighted score
  |     +-- stores snapshot
  |
  +-- IncidentClassifier
  |     +-- pattern matching against 12 known log patterns
  |     +-- cooldown dedup, auto-resolve
  |
  +-- Repository (SQLite)
        +-- probe_results, incidents, health_snapshots, latency_samples
```

## Data Flow

1. Probes execute on independent cadences (10-30s)
2. Results stored in SQLite via Repository
3. Log probes feed lines into IncidentClassifier
4. Classifier creates/bumps incidents with dedup
5. HealthScorer reads latest probes + incidents every 30s
6. UI pages query Repository for display
7. JS auto-refresh updates dashboard every 10s

## Storage

SQLite with WAL mode for concurrent reads. Retention purge runs hourly.

| Table | Retention |
|-------|-----------|
| probe_results | 7 days |
| incidents | 30 days |
| health_snapshots | 7 days |
| latency_samples | 3 days |

## Isolation

- No Python imports from `/var/www/` (Opus Trader)
- HTTP probes use httpx with configurable auth
- File probes use read-only access
- Process probes use `systemctl is-active` (no control)
- No shared mutable state with trading runtime
