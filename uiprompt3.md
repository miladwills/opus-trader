You are working on Opus Trader.

Execute a final narrow finishing pass on the dashboard UI/layout based on the CURRENT post-refactor state.

This is NOT a broad redesign.
This is NOT a feature pass.
This is NOT a trading-logic change.

This is a screenshot-driven, precision cleanup pass meant to take the dashboard from “already much better” to “tightly finished, more premium, more balanced, and more professional.”

The recent layout pass already improved:
- KPI card cleanliness
- relocation of Running Now / Recent Closed PnL into a dedicated activity strip
- Active Bots width priority
- Bot Configuration vs companion panel balance
- Watchdog spacing
- empty-state compaction

Do NOT undo those gains.
Build on them.

==================================================
PRIMARY GOAL
==================================================

Perform a small but high-value finishing pass that resolves the remaining visible layout/UX issues:

1. remaining summary/detail mixing
2. oversized empty states
3. excess unused vertical space
4. right-rail panels still feeling too tall/heavy
5. uneven vertical balance between main content and companion areas
6. final Watchdog list/detail spacing inefficiencies
7. floating shortcut controls feeling slightly too visually heavy

The final result should feel:
- tighter
- more intentional
- more premium
- better balanced vertically
- calmer
- easier to scan
- less wasteful with space

==================================================
IMPORTANT CONTEXT
==================================================

Recent improvements already in place and must be preserved:

- KPI content relocation to an activity strip
- workspace grid rebalance
- workbench grid rebalance
- tighter empty states
- Watchdog tightening
- no JS needed for the last relocation pass
- all current behavior works

Current task:
polish the last 10–15% only

==================================================
STRICT CONSTRAINTS
==================================================

Do NOT:
- redesign the dashboard architecture from scratch
- move major sections into brand new locations unless explicitly required below
- change trading behavior
- change backend logic
- expand scope into unrelated UI areas
- add verbose explanatory copy
- add new heavy components
- create a new design language

Do:
- make targeted layout refinements
- preserve the current architecture
- reduce visual waste
- improve finishing quality
- keep the diff relatively small and disciplined

==================================================
SCREENSHOT-DRIVEN ISSUES TO FIX
==================================================

--------------------------------------------------
1) REMOVE THE LAST BIG SUMMARY/DETAIL MIX
--------------------------------------------------

Problem:
The Emergency KPI card still contains the “Ready to Trade” list beneath the emergency stop action.

Why this is still a problem:
- it breaks the new summary-vs-detail rule already applied elsewhere
- it makes the emergency summary card structurally inconsistent with the other KPI cards
- it keeps operational detail trapped inside a top-level summary card

Required change:
Move “Ready to Trade” out of the Emergency summary card into a more appropriate dedicated detail location.

Preferred destination:
- the existing Activity Strip area, alongside Running Now / Recent Closed PnL
OR
- a dedicated compact operational strip directly below the KPI row

Rules:
- Emergency card should become action/status focused only
- keep Ready to Trade visible and useful
- do not make the new location visually noisy
- keep the final result coherent with the current top-of-dashboard structure

==================================================
2) COMPACT EMPTY RECENT CLOSED PNL FURTHER
==================================================

Problem:
When Recent Closed PnL is empty, it still consumes more vertical space than justified.

Required change:
Make the empty state for Recent Closed PnL meaningfully more compact.

Possible approaches:
- reduce empty min-height
- shrink table shell when there are zero rows
- replace empty table body with a shorter compact placeholder state
- expand only when actual rows exist

Goal:
When empty, it should read as “quiet recent history strip,” not as a full panel reserving unnecessary space.

==================================================
3) MAKE ACTIVE BOTS MORE CONTENT-DRIVEN VERTICALLY
==================================================

Problem:
When very few bots are shown, Active Bots still leaves a large dead area below the visible content.

Required change:
Make Active Bots height more adaptive to the actual amount of content.

Requirements:
- reduce unnecessary empty vertical area when bot count is low
- preserve stability when many bots exist
- do not cause awkward jumpiness or collapse too aggressively
- keep the section visually important without wasting space

Goal:
A single visible bot should not leave a giant unused empty floor underneath.

==================================================
4) TIGHTEN THE RIGHT RAIL FURTHER
==================================================

Problem:
The right rail is improved, but some panels still feel too tall and visually heavy for the amount of information they contain.

Focus especially on:
- Positions (when empty)
- Scalp Safety (when mostly empty)
- Predictions / signal desk vertical rhythm
- other secondary side-intelligence boxes

Required change:
Introduce one more level of compactness for low-information states in the right rail.

Rules:
- preserve readability
- preserve important signals
- avoid over-compressing when data is present
- empty or near-empty states should visually shrink
- right rail should support the main workspace, not compete with it

==================================================
5) IMPROVE BOT CONFIGURATION VERTICAL BALANCE
==================================================

Problem:
In the Bot Configuration area, the main form continues much further downward than the companion panel, creating visible imbalance and a large inactive right-side vertical region.

Required change:
Improve the vertical balance between:
- main bot form
- companion scanner panel

Potential acceptable solutions:
- make the companion panel sticky and intentionally shorter
- let the companion panel compact more aggressively when idle
- stack/reflow earlier at a wider breakpoint
- allow the lower form area to visually reclaim more of the full width at the right moment
- use a better end-of-panel treatment so the mismatch feels intentional, not accidental

Goal:
The page should not feel like the right side “ends early” while the main form continues alone in a visually awkward way.

Important:
Do not remove the companion panel.
Just make the relationship feel deliberate.

==================================================
6) WATCHDOG CENTER FINAL SPATIAL CLEANUP
==================================================

Problem:
Watchdog is improved, but the top list/detail region still has some dead space and slightly uneven balance.

Observed issues to address:
- the upper-left side can still feel too empty in some states
- detail pane may feel more dominant than necessary
- list/detail/timeline spacing could be a bit tighter and more intentional

Required change:
Do a final small cleanup to make the Watchdog top region more efficient.

Possible acceptable directions:
- reduce upper region height when list content is sparse
- tighten filters/list/detail spacing
- make the left region feel less empty
- bring Recent Timeline visually closer where appropriate
- reduce excessive dead space without making the area cramped

Do NOT redesign Watchdog completely.
This is a finishing adjustment only.

==================================================
7) FLOATING SHORTCUTS / DOCK QUIET-DOWN
==================================================

Problem:
The floating shortcut controls at the lower-right are useful, but still feel a bit large / visually assertive relative to the rest of the cleaned UI.

Targets:
- Bots
- Scanner
- Top

Required change:
Make them slightly calmer and more compact.

Acceptable changes:
- reduce size
- reduce padding
- tighten internal spacing
- make the dock feel more subtle
- improve idle visual weight

Do not make them hard to tap/click.
Do not remove them.

==================================================
8) KEEP THE WHOLE RESULT COHERENT
==================================================

After the above refinements, ensure the dashboard still feels like one unified product.

Preserve consistency in:
- panel header rhythm
- spacing
- empty-state style
- compact metadata treatment
- card heights
- border/padding behavior
- summary vs detail separation
- right-rail secondary status

The goal is for the current layout architecture to feel “finished,” not merely “edited again.”

==================================================
IMPLEMENTATION PREFERENCE
==================================================

Approach this as a final precision pass.

Prefer:
- small, surgical HTML/CSS/Tailwind refinements
- minimal JS changes only if clearly required
- reusable empty-state and compactness rules
- content-driven height behavior where safe
- small responsive breakpoint improvements if needed
- preserving the current architecture

Avoid:
- broad movement of sections
- random style churn
- unnecessary abstractions
- over-compression that harms usability

==================================================
FILES TO REVIEW FIRST
==================================================

Inspect first:
- templates/dashboard.html
- any relevant style blocks/classes in the dashboard template
- static/js/app_lf.js only if absolutely needed for content-state-dependent compactness
- rendering structure for:
  - Emergency card
  - Activity strip
  - Active Bots
  - right rail panels
  - Bot Configuration workbench + companion panel
  - Watchdog top section
  - floating shortcut dock

==================================================
VERIFICATION EXPECTATIONS
==================================================

After implementing:

1. Verify the dashboard still renders correctly
2. Verify Emergency Stop remains visually strong and functional
3. Verify Ready to Trade remains visible after relocation
4. Verify Recent Closed PnL empty state is smaller
5. Verify Active Bots no longer leaves excessive vertical waste when few bots are visible
6. Verify right rail is more compact in empty/low-info states
7. Verify Bot Configuration still works and feels more balanced vertically
8. Verify Watchdog still works and reads more efficiently
9. Verify floating shortcuts still work and are easier on the eye
10. Run relevant UI tests if available
11. Add/update focused UI assertions only if existing tests already cover these areas

==================================================
OUTPUT FORMAT
==================================================

When done, provide:

1. Executive summary
A concise summary of the finishing pass

2. File-by-file changelog
For each changed file, explain exactly what changed and why

3. Finishing-pass summary
Explain how the remaining layout issues were resolved

4. Summary/detail cleanup summary
Explain where Ready to Trade moved and how KPI purity improved

5. Empty-state and vertical-balance summary
Explain:
- what became more compact
- what became more content-driven
- how vertical waste was reduced

6. Right-rail summary
Explain how the side panels became calmer and less heavy

7. Watchdog finishing summary
Explain what changed in the top list/detail/timeline region

8. Tests / verification
List what was checked and what passed

9. Risk check
Mention any minor styling/layout tradeoffs or deferred items

10. UI location report
MANDATORY:
For every UI change, state the exact location on the page:
- which page
- which panel/section
- above/below what
- whether it affects:
  - dashboard summary only
  - activity strip only
  - active bots only
  - right rail only
  - bot configuration only
  - watchdog only
  - floating controls only
  - or multiple surfaces

This UI location report is mandatory.

11. Deliverable packaging
At the end, create a ZIP of the full project in the project directory, excluding:
- venv
- zip files
- caches
- useless heavy/generated files

Name it with the latest remarkable changes plus today’s date/time.

==================================================
QUALITY BAR
==================================================

This pass should feel like the final tightening step after a successful architectural cleanup.

The result should:
- waste less space
- read faster
- feel more premium
- feel more finished
- reduce the last obvious layout annoyances
- preserve all recent gains
- make the dashboard look intentionally designed rather than iteratively accumulated