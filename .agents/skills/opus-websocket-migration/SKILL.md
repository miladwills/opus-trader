---
name: opus-websocket-migration
description: Plan and implement WebSocket-first, REST-second migration phases for Opus Trader while preserving gate, range, and safety contracts.
---

Preserve these contracts:
- honest directional gate behavior
- no directional SR double punishment
- canonical range-state by mode
- fail-safe stale/private-cache behavior
- readiness semantics: Preview Off / Preview / Gate Off / Stale

Always separate:
- public market data
- private account state
- startup seed
- reconnect reseed
- reconciliation
- bridge/snapshot consumers

Do not change trading logic unless explicitly requested.
Prefer phased migration.

Migration workflow:
1. Map the current REST and websocket responsibilities before changing anything.
2. Define migration phases that keep runtime behavior observable and reversible.
3. Preserve snapshot seeding, reconnect reseeding, and reconciliation boundaries so stale state does not masquerade as live state.
4. Keep consumer contracts stable unless the task explicitly includes downstream updates.
5. Validate each phase against gate, range, readiness, and safety semantics before moving on.
