---
name: opus-bugfix-surgical
description: Apply small, surgical bug fixes in Opus Trader without changing trading logic or destabilizing recent live-contract fixes.
---

This skill is for narrow bug fixes only.

Rules:
- fix the bug structurally
- avoid broad refactors
- preserve recent live-contract behavior
- do not change gate, recenter, exit, or range semantics unless explicitly required
- add a targeted regression test when practical
- compile-check touched Python files
- explain the root cause clearly

Priorities:
1. real live blocker first
2. no hidden behavior changes
3. no fake success messages
4. preserve canonical range-state and safety contracts

Execution pattern:
1. Reproduce or localize the defect from code, tests, logs, or persisted state.
2. Patch the smallest safe surface that fixes the root cause.
3. Verify adjacent live contracts are unchanged, especially bot ownership, range-state, readiness, and reduce-only behavior.
4. Add or update a narrow regression test when it provides real protection.
5. Compile-check touched Python modules before closing the task.
