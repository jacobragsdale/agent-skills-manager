---
name: agents-md
description: "Write or overhaul a repo's AGENTS.md (or CLAUDE.md) so coding agents work well there. Use when creating agent instructions for a repo, auditing a bloated or ignored AGENTS.md/CLAUDE.md, when agents repeat the same mistakes in a codebase, or when wiring instruction files across Claude Code / Cursor / Codex."
disable-model-invocation: true
---

# Writing a repo's AGENTS.md

Produce a repo-scoped AGENTS.md that makes any coding agent effective in that
repo: verified commands, non-inferable rules, hard boundaries. The rules below
are evidence-based (vendor docs, three empirical studies, analysis of praised
production files) — `references/research-notes.md` has the receipts; read it
when the user questions a rule.

## Non-negotiables

- **Never template-dump or generate from a skim.** Auto-generated context
  files measurably HURT agents (−3% task success, +20% cost); human-curated
  ones help (+4%). Every line must be earned by investigation (step 2) or
  interview (step 3).
- **60–150 lines.** Measured gains reverse past ~150. Hard cap 200 — past
  that, move detail into linked docs or nested AGENTS.md files.
- **Only non-inferable content.** No file trees, no architecture essays, no
  "write clean code". If an agent could discover it with two tool calls,
  cut it.
- **Every command is verified.** Run it before documenting it. A stale
  command is worse than no command — it actively misleads.
- **Rules are one sentence each**, ideally traceable to a real observed
  failure. Facts and commands get followed; vague behavioral coaching gets
  ignored.

## Workflow

### 1. Inventory existing instruction files

Look for: `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, `.cursor/rules/`,
`.cursorrules`, `.github/copilot-instructions.md`, `.windsurfrules`,
`GEMINI.md`. The new AGENTS.md becomes canonical: mark what's still true to
fold in, list the rest for deletion (confirm in step 3).

### 2. Investigate the repo — thorough, budget real time here

- **Commands** — from package.json scripts / pyproject / Makefile / justfile
  AND the CI workflows (`.github/workflows` is ground truth for how tests and
  lint actually run). Collect: setup, build, full test, **single-file test**
  (the highest-value command in the file), lint, format, typecheck, run/serve.
- **Toolchain rules** — package manager (the pnpm-never-npm class of rule),
  version pins, workspace/monorepo tooling.
- **Conventions that differ from defaults** — read 3–5 representative source
  files and a few recent PRs; note naming, error handling, test patterns,
  import style — only where an agent would guess wrong.
- **Footguns** — slow commands (time them), flaky suites, generated files
  that must not be hand-edited, required services/ports.
- **Directory map** — only 5–15 non-obvious path → purpose entries.

RUN every candidate command now. Record duration for anything over ~10s.
Anything you can't verify does not go in the file.

### 3. Interview the user — required, do not skip to drafting

The highest-value content is what no investigation can surface. Ask (via
AskUserQuestion where available, otherwise directly):

1. What do agents — or new devs — repeatedly get wrong in this repo?
2. Which parts look wrong or odd but are intentional, and why?
3. What must an agent never do here (deploys, migrations, editing generated
   code, secrets)? What should it always ask about first?
4. Which internal tools/CLIs should an agent know by name, and where do
   internal docs live?
5. What's slow, expensive, or rate-limited that an agent might trigger
   accidentally?

Each adopted answer lands as one sentence; "looks wrong but intentional"
entries include the why.

### 4. Draft

READ `references/template.md` and fill it. Style rules:

- Commands early, fenced, each annotated inline with its failure mode or
  cost (`# ~6 min — use the single-file form below`).
- Positive or conditional phrasing ("Always X", "If X then Y"). A handful of
  Nevers at most, each stating the alternative — negation stacks make agents
  timid and "do not X" primes X.
- One real 3–10-line code snippet from the repo beats paragraphs describing
  style.
- Formatting/style rules belong to linters and hooks, not this file (for
  Python repos, the `python-uv-setup` skill wires those). If a rule must
  never be violated, it needs CI or a hook; prose is advisory.
- Boundaries as three tiers: **Always / Ask first / Never**.
- Emphasis (IMPORTANT, YOU MUST) on the top 1–3 rules only.

### 5. Cross-tool wiring

- `AGENTS.md` at repo root is canonical — read natively by Codex, Cursor,
  Copilot, Jules, Amp, and 20+ others.
- Claude Code does NOT read AGENTS.md. Create a `CLAUDE.md` whose content is
  exactly `@AGENTS.md` — the import beats a symlink (works on Windows, and
  leaves room for Claude-specific additions below the import).
- Monorepo: root file stays global; each subproject that differs gets its own
  nested AGENTS.md (closest file wins in most tools; Codex concatenates with
  a 32 KiB combined cap).
- Delete the superseded files from step 1.

### 6. Verify

- RUN `scripts/lint_agents_md.py <repo>/AGENTS.md` and fix every error
  (placeholders, length, dead paths, vague phrases, negation stacks).
- Re-run every documented command exactly as written, from the repo root.
- Final pass, per line: "would removing this cause an agent to make a
  mistake?" If no, cut it.

### 7. Hand off the maintenance contract

Close out by telling the user (and leaving an HTML comment footer in the
file — comments are stripped before models see it):

- Add a rule only after an observed failure, one sentence, ideally validated
  by re-running the failed task against the new rule.
- Update commands in the same PR that changes them.
- Prune on a schedule: delete rules that newer models no longer need, and
  anything whose removal wouldn't cause mistakes.

## Example

The shape of a good result (excerpt):

```markdown
# acme-billing

Django 4 invoicing monolith. Python 3.11, uv-managed, pnpm for the frontend.

## Commands
uv run pytest tests/path/test_x.py -x   # single file — full suite ~6 min, avoid
uv run pytest -m "not integration"      # pre-push safety net, ~40 s
pnpm --filter dashboard test            # frontend — NEVER npm (breaks lockfile)

## Gotchas
- `models/legacy_ledger.py` looks dead but backs the nightly reconciliation
  job — intentional, do not delete.
- Migrations: generate with `uv run manage.py makemigrations`, but ALWAYS ask
  before applying to any shared database.

## Boundaries
- Always: run the single-file test for anything you touch.
- Ask first: schema migrations, new dependencies, editing `infra/`.
- Never: commit secrets; hand-edit `api/generated/`.
```

## Bundled resources

- `scripts/lint_agents_md.py` — RUN in step 6 on the drafted file.
- `references/template.md` — READ in step 4; skeleton with required sections.
- `references/research-notes.md` — READ when a house rule is questioned;
  every claim above, with sources.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
