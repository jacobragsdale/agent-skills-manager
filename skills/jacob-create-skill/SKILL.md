---
name: jacob-create-skill
description: Create, improve, or validate agent skills (SKILL.md folders). Use when the user wants to make a new skill, fix a skill that isn't triggering, review or refactor an existing skill, add scripts to a skill, or fold LEARNINGS.md notes into a skill.
metadata:
  author: jacob
disable-model-invocation: true
---

# Creating and improving agent skills

Build skills that conform to the agentskills.io open standard and work unchanged
in Cursor (`.agents/skills/`) and Claude Code (`.claude/skills/`). A skill is a
folder whose name matches the `name:` in its `SKILL.md`, optionally with
`scripts/`, `references/`, and `assets/` alongside.

**Before doing anything else, read `LEARNINGS.md` in this skill's folder.**
Entries there are corrections from real use and override anything below.

## Step 1 — Clarify before writing anything

Skills fail more often from fuzzy intent than bad prose. Interview the user
before scaffolding. Skip a question only if the request already answers it.

1. **The ten-word job.** Ask the user to state what the skill does in one short
   sentence. If it takes two sentences joined by "and", it is two skills —
   propose the split.
2. **Trigger phrases.** What would the user actually type when they want this?
   And what nearby requests should *not* trigger it? These become the
   description and the trigger test in Step 5 — they still matter even
   though skills default to explicit invocation (see Step 3): they're what
   the agent sees in the `/` menu, and what Step 5 judges if the user later
   asks to turn auto-triggering on.
3. **The verified-struggle test.** What has an agent actually gotten wrong
   doing this task without the skill? Skills encode lessons from verified
   success, not speculation — a skill written before anyone has struggled is
   usually restating the model's defaults. If the answer is "nothing yet,
   I just think it would help", recommend doing the task once without a skill
   and capturing what was hard, then writing the skill from that.
4. **Script vs. prose split.** Which parts are deterministic (same input, same
   output — parsing, validation, scaffolding, API calls)? Those become
   self-contained scripts. Which parts need judgment? Those stay as prose
   instructions. "Be careful to X" in prose is a smell that X wanted a script.

Also confirm where the skill lives: this repo's `skills/` directory (installed
globally via symlinks) or a specific project's `.agents/skills/`.

## Step 2 — Scaffold

Run the scaffolder rather than hand-creating files, so the folder name, the
frontmatter, and the learnings loop start correct:

```bash
uv run <this-skill-dir>/scripts/init_skill.py <skill-name> --dir <skills-root>
```

This defaults every new skill to `disable-model-invocation: true` (Cursor and
Claude Code both honor it): explicit `/skill-name` only, never auto-triggered
from conversation. Pass `--auto-trigger` only when the user has explicitly
asked for automatic triggering in Step 1 — it is an opt-in, not a default.

## Step 3 — Draft the SKILL.md

House rules, and why:

- **The description is a trigger, not a summary.** Routers may only show the
  first ~250 characters, so front-load "Use when …" with the concrete phrases,
  symptoms, and error messages from Step 1. Do not describe the workflow in
  the description — agents that see a workflow summary follow it and never
  read the body.
- **Keep the body under 300 lines** (hard limit 500 — reported accuracy drops
  beyond that). Reference material over ~100 lines moves to `references/`
  with an explicit pointer: "Read `references/x.md` when Y."
- **Only write what moves the agent off its defaults.** A capable agent
  already knows how to write Python and read docs. Every line should encode
  something it would otherwise get wrong. Delete the rest.
- **Imperative voice, one excellent worked example.** "Run X, then check Y"
  beats "the agent should…". One complete input→output example beats five
  fragments.
- **No nuance clauses.** "Don't X unless it matters" reopens the negotiation
  you wrote the rule to close. If a rule has real exceptions, enumerate them;
  otherwise state it flat.
- **Match the guidance form to the failure type.** Agent skips a rule → hard
  prohibition, not "prefer". Agent produces the wrong shape → exact template
  with REQUIRED fields, not a prohibition list. Agent forgets things → a
  checklist, not prose reminders.
- **Default `disable-model-invocation: true`.** House default for every skill
  in this repo, set by the scaffolder in Step 2. Only leave it off (auto-
  trigger from conversation) when the user explicitly asked for that in
  Step 1 — never assume it because a skill seems "obviously" auto-triggerable.

### Scripts: uv + PEP 723, always

Every bundled Python script is a self-contained single file with inline
dependency metadata, runnable anywhere `uv` exists — no venv, no
`pip install` prose in the skill body:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
```

Rules for skill scripts:

- Run with `uv run scripts/name.py`. Manage deps with
  `uv add --script scripts/name.py <pkg>`, never by editing prose.
- `argparse` with `--help` text good enough that SKILL.md doesn't need to
  restate the flags — the body says *when* to run it, `--help` says *how*.
- Fail loudly: nonzero exit codes and error messages that say what to fix.
- In SKILL.md, state for each script whether the agent should **run** it or
  **read** it as reference — agents guess wrong otherwise.

For frontmatter beyond `name` and `description` (Cursor's `paths` and
`disable-model-invocation`, `allowed-tools`, Claude Code extensions), read
`references/frontmatter.md` before using a field — support varies by agent.

## Step 4 — Validate

```bash
uv run <this-skill-dir>/scripts/validate_skill.py <path-to-skill-folder>
```

Fix every error. Address or consciously accept each warning — the warnings
encode the house rules above.

## Step 5 — Trigger test

Write six realistic user messages: three that should trigger the skill
(varied phrasing, not just keyword swaps) and three near-misses that should
not (share vocabulary but need something else). Judge each against **only the
name and the first 250 characters of the description** — that is all a router
sees. Show the user the table of message → expected → verdict. Revise the
description until all six are correct. Do not fix a trigger miss by making
the description vaguer; add the missing concrete phrase.

## Step 6 — Wire the learnings loop

Every skill you create ships with a `LEARNINGS.md` (the scaffolder seeds it)
and ends with this exact block:

```markdown
## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
```

## Improving an existing skill

When asked to improve a skill (or to "fold learnings"):

1. Read its `SKILL.md` and `LEARNINGS.md`.
2. Fold entries that recur or were explicitly user-confirmed into the body,
   in the section where the mistake happened. Delete each folded entry.
3. Delete stale or speculative entries — a lesson that never recurred and
   can't be tied to a real failure is noise.
4. While in there, cut body lines that aren't pulling weight; skills accrete.
5. Re-run Step 4 and Step 5 before finishing.

## Bundled resources

- `scripts/init_skill.py` — **run** to scaffold a new skill folder.
- `scripts/validate_skill.py` — **run** to lint a skill against the spec and
  these house rules.
- `references/best-practices.md` — **read** when unsure about a design choice
  (token budgets, description writing, script-vs-prose, sources).
- `references/frontmatter.md` — **read** before using any frontmatter field
  beyond `name`/`description`.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
