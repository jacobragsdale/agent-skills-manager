# AGENTS.md skeleton

Fill every `<...>`; delete sections with nothing non-inferable to say.
Target 60–150 lines total. Sections marked REQUIRED must survive.

```markdown
# <repo-name>

<One or two sentences: what this is, the stack, the one fact that frames
everything else (e.g. "uv-managed", "pnpm workspace", "deployed via GHCR").>

## Commands   <!-- REQUIRED — verified, annotated, single-file test first -->

<fenced commands, one per line, each with an inline comment stating cost or
failure mode. Include: setup, single-file test, full test, lint+format,
typecheck, run. Nothing unverified.>

## Structure   <!-- only if non-obvious; 5–15 entries max -->

- `<path>` — <purpose an agent would not guess>

## Conventions   <!-- only rules that differ from language/framework defaults -->

- <one sentence per rule; include a real 3–10-line code snippet if style
  matters more than any single rule>

## Gotchas   <!-- the interview gold: looks-wrong-but-intentional, footguns -->

- <thing> — <why it is intentional / what to do instead>

## Git & PRs   <!-- only house rules: message format, when to open PRs, CI expectations -->

## Boundaries   <!-- REQUIRED — three tiers -->

- **Always:** <e.g. run the single-file test for anything touched>
- **Ask first:** <e.g. migrations, new dependencies, anything in infra/>
- **Never:** <e.g. commit secrets; hand-edit generated code — say where the
  source of truth is>

<!-- Maintenance: add a rule only after an observed failure (one sentence).
Update commands in the same PR that changes them. Prune regularly: if
removing a line wouldn't cause agent mistakes, remove it. -->
```

## Companion CLAUDE.md (always create alongside)

Claude Code does not read AGENTS.md. `CLAUDE.md` at repo root:

```markdown
@AGENTS.md
```

Add Claude-specific lines below the import only if they exist. Do not
duplicate content between the two files.

## Monorepo variant

Root AGENTS.md holds only repo-wide truth (toolchain, git rules, global
boundaries). Each subproject whose commands or conventions differ gets its
own short AGENTS.md next to its code. Keep the combined chain small — Codex
stops reading at 32 KiB total.
