---
name: quant-safety-review
description: Review trading-risk impact before implementation
---

# Quant Safety Review

Before implementing a task that may touch trading logic, perform a safety review to identify risks and propose the safest implementation boundary.

## Review Process

1. **Classify the task**: Does it touch trading logic, or only presentation/UI?
2. **Identify sensitive areas** that could be affected:
   - Entry/exit logic (entry gate, readiness, direction scoring)
   - Order sizing, placement, cancellation
   - Position management (margin, leverage, liquidation)
   - Risk management (daily limits, bot limits, emergency stop)
   - PnL accounting and attribution
   - Neutral grid management (recenter, breakout guard, inventory cap)
   - Range engine (dynamic, trailing, fixed)
   - Config save/load paths
3. **List regression risks**: What could break if the change is implemented incorrectly?
4. **Propose implementation boundary**: What is the safest scope for the change?
5. **Explicitly state** when a task should remain frontend-only

## Output Format

Provide a structured assessment:
- **Classification**: UI-only / Backend-safe / Trading-sensitive
- **Sensitive areas touched**: List or "None"
- **Regression risks**: Bulleted list
- **Recommended boundary**: Where to make changes and where to avoid
- **Testing requirements**: What to verify after implementation
