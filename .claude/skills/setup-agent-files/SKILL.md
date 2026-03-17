---
name: setup-agent-files
description: Normalize shared queue/report files. Ensures correct fields and statuses without inventing new ones.
---

# /setup-agent-files

Validate and normalize the shared agent files to ensure they conform to the contracts defined in `.claude/rules/agent-file-contracts.md`.

## What this does

1. **Read** `.claude/rules/agent-file-contracts.md` for the authoritative schema.

2. **Validate `issues_queue.jsonl`:**
   - Parse each line as JSON.
   - Check all required fields are present.
   - Check status values match the allowed set.
   - Check severity values match the allowed set.
   - Report any lines with missing fields, unknown statuses, or parse errors.

3. **Validate `development_ideas.jsonl`:**
   - Parse each line as JSON.
   - Check all required fields are present.
   - Check status values match the allowed set.
   - Report any lines with missing fields, unknown statuses, or parse errors.

4. **Create missing files:**
   - If `monitor_report.md` doesn't exist, create it with the section template from the contract.
   - If `issues_queue.jsonl` doesn't exist, create an empty file.
   - If `development_ideas.md` doesn't exist, create it with the section template from the contract.
   - If `development_ideas.jsonl` doesn't exist, create an empty file.

5. **Report findings:**
   - List any schema violations found.
   - List any files that were created.
   - Do NOT auto-fix violations — just report them for human review.
   - Do NOT invent new fields.

## What this does NOT do

- Does not modify existing entries in .jsonl files.
- Does not add fields to existing entries.
- Does not change any source code.
- Does not restart services.
