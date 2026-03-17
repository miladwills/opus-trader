---
name: opus-skill-bootstrap
description: Create, update, organize, and validate repo-local Codex skills for Opus Trader under .agents/skills.
---

Use this skill when the task is about skills themselves.

Responsibilities:
- create new repo-local skills under `.agents/skills/`
- update existing `SKILL.md` files safely
- keep names and descriptions specific and triggerable
- avoid vague or overlapping skills
- maintain `.agents/skills/README.md`
- preserve existing unrelated skills
- validate folder structure and required metadata
- keep skills concise, reusable, and project-specific

When editing skills:
- prefer instruction-first skills
- only add scripts/references when clearly justified
- avoid duplicate responsibilities across skills
- keep trigger conditions explicit
- make each skill easy for Codex to select correctly

Validation checklist:
1. every skill lives in its own folder under `.agents/skills/`
2. every skill has a `SKILL.md`
3. every `SKILL.md` begins with YAML front matter containing `name` and `description`
4. `.agents/skills/README.md` is present and current
5. unrelated existing skills remain untouched unless the task explicitly changes them
