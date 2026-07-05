---
name: agent-create-skill
description: "Create, improve, or validate agent skills (SKILL.md folders). Use when the user wants to make a new skill, improve or refactor an existing one, fix a skill that isn't triggering or fires too often, tune a skill description, add scripts to a skill, or fold LEARNINGS.md notes into a skill — even if they just say 'teach the agent to do X' or 'make this workflow reusable'. Do NOT use for contributing a skill to the team repo via PR (use propose-skill) or for repo-level agent instructions (use agents-md)."
metadata:
  author: jacob
---

# Creating and improving agent skills

Build skills that conform to the agentskills.io open standard and work
unchanged in Cursor, Codex, and Copilot (all read `~/.agents/skills/`) and
Claude Code (via links into `~/.claude/skills/`). A skill is a folder whose
name matches the `name:` in its `SKILL.md`, optionally with `scripts/`,
`references/`, and `assets/` alongside. For how each agent discovers, routes,
and loads skills — and what that means for descriptions and body size — read
`references/invocation.md`.

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
   description and the trigger test in Step 5. Skills are model-invoked by
   default (see Step 3), so the description is the routing surface — getting
   these phrases right is the difference between a skill that fires and one
   that sits unused.
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

New skills are model-invocable by default: the agent triggers them from
conversation when the description matches. Pass `--explicit-only` (which sets
`disable-model-invocation: true`) only for consequential or destructive
workflows the user must consciously trigger with `/skill-name`.

## Step 3 — Draft the SKILL.md

House rules, and why:

- **The description is a trigger, not a summary** — it carries the entire
  routing burden; the body is invisible until the skill fires. Shape: third-
  person capability sentence, then a pushy "Use when …" listing the concrete
  phrases, symptoms, and file types from Step 1 (agents under-trigger by
  default — include "even if the user doesn't mention <domain> explicitly"
  cases), then a "Do NOT use when … (use <other-skill>)" boundary for every
  near-neighbor in the library. Front-load: truncation eats the tail. Do not
  describe the workflow — agents that see a workflow summary follow it and
  never read the body.
- **Keep the body under 150 lines** for model-invocable skills (~250 if
  explicit-only; hard limit 500). Once invoked, the body persists in context
  for the whole session, and trimming non-actionable content measurably
  improves execution. Reference material moves to `references/` with an
  explicit pointer: "Read `references/x.md` when Y" — never "see references/
  for details".
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
- **Model-invocable by default.** Skills trigger from conversation when the
  description matches — that is what makes a team library useful without
  anyone memorizing skill names. Reserve `disable-model-invocation: true`
  for consequential or destructive workflows (deploys, deletions, anything
  that publishes) the user must consciously trigger.

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

Write at least ten realistic user messages: five or more that should trigger
the skill and five or more near-misses that should not. Vary the positives
across phrasing (formal/casual/typos), explicitness (names the domain vs
only describes the need), and detail (terse vs file paths and backstory) —
the most valuable positives are ones where the skill helps but the
connection isn't obvious. Negatives must be near-misses that share
vocabulary but need something else; "what's the weather" tests nothing.
Judge each against **only the name and description** — that is all a router
ever sees — and show the user the table of message → expected → verdict.
Revise until all pass: broaden trigger coverage for false negatives, add a
"Do NOT use when" boundary for false positives, and never fix a miss by
making the description vaguer or by pasting a failed query verbatim —
generalize to its category. Freeze the final table as
`tests/triggers.md` in the skill folder for future regression runs.

## Step 6 — Wire the learnings loop

Every skill you create ships with a `LEARNINGS.md` (the scaffolder seeds it)
and ends with this exact block (substituting the skill's name). It rides the
skill body deliberately: it is in context exactly when the skill runs, which
no always-on rules file achieves across agents (see
`references/invocation.md`).

```markdown
## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use:

1. Append one line to `~/.agents/.manager/usage.jsonl` (create if missing):
   `{"ts": "<ISO-8601>", "skill": "<skill-name>", "outcome": "ok" | "corrected"}`
   — `corrected` when the user had to fix or redirect your use of this skill.
2. If the user corrected you or the outcome surprised you, also append one
   dated line to `LEARNINGS.md`:
   `- YYYY-MM-DD: <what happened> → <what to do instead>`. Facts only, never
   secrets. Do not edit SKILL.md directly — lessons are folded in
   deliberately through a weekly reviewed PR.
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
- `references/invocation.md` — **read** when tuning triggering, deciding
  body-vs-references placement, or targeting a specific agent (Cursor,
  Claude Code, Codex, Copilot discovery mechanics and budgets).

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use:

1. Append one line to `~/.agents/.manager/usage.jsonl` (create if missing):
   `{"ts": "<ISO-8601>", "skill": "agent-create-skill", "outcome": "ok" | "corrected"}`
   — `corrected` when the user had to fix or redirect your use of this skill.
2. If the user corrected you or the outcome surprised you, also append one
   dated line to `LEARNINGS.md`:
   `- YYYY-MM-DD: <what happened> → <what to do instead>`. Facts only, never
   secrets. Do not edit SKILL.md directly — lessons are folded in
   deliberately through a weekly reviewed PR.
