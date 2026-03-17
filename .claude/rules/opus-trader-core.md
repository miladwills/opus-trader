# Opus Trader Core Rules

These rules apply to all work in this repository.

## System Nature
- Opus Trader is a real-money live trading system on Bybit mainnet.
- Every edit has financial consequences. There is no staging environment.

## Change Philosophy
- Prefer small, reversible diffs over large refactors.
- Every change must be justified by a confirmed root cause or clear requirement.
- No speculative fixes. No "while we're here" improvements.
- Distinguish setup readiness (can we enter?) from execution viability (should we enter now?).

## Truthfulness
- Exchange state is authoritative over local state.
- Preserve operator truthfulness: never hide, soften, or delay bad news.
- Truthful non-actionable states are preferred over optimistic labels.
- Stale data must be labeled stale, not displayed as current.

## Safety Priorities (in order)
1. Exchange truth over optimistic local assumptions
2. Correct stop / cleanup semantics
3. Truthful readiness and blocker semantics
4. Durable order / position attribution
5. Low-noise operator UX

## UI Rules
- Keep UI text concise and low-noise.
- Favor truthful state badges over explanatory prose.
- After any UI change, state the exact UI location (card name, section, element).
- Avoid verbose descriptions in dashboard elements.

## Language
- English only for all prompts, workflow files, and agent output.
