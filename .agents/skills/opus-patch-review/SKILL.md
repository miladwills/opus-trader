---
name: opus-patch-review
description: Verify Opus Trader patches against the real code and runtime files, mark each claim PASS/PARTIAL/FAIL, and find hidden regressions.
---

Review the patch by matching claims against the actual code, not the written summary.

Always:
- inspect touched files directly
- verify control flow, not comments
- search for remaining old paths
- check compile safety
- check whether a fix is only partial
- look for regressions introduced by the patch

Workflow:
1. Identify the claimed changes, expected behavior, and affected runtime contracts.
2. Inspect the touched files and any nearby call sites or legacy paths that can still bypass the fix.
3. Compare the patch claim to actual control flow, persisted state handling, and UI/API wiring where relevant.
4. Run a focused syntax or test check when practical to verify the patch is not only textually present but operationally safe.
5. Flag hidden regressions, partial fixes, and contract violations explicitly.

Required output:
- Executive summary
- PASS / PARTIAL / FAIL for each claim
- File-by-file changelog
- Hidden regressions
- Remaining risks
