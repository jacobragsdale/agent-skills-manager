# Skill-writing best practices (distilled research, July 2026)

Condensed from Anthropic's engineering guidance, the agentskills.io spec,
Jesse Vincent's `writing-skills` (obra/superpowers), Simon Willison's skills
coverage, and HN/community threads. Sources at the bottom.

## Progressive disclosure — the core mechanic

Three loading tiers; write for each:

1. **Frontmatter** (`name` + `description`) — always in context, ~30 tokens
   per installed skill. This is the *only* thing the router sees.
2. **SKILL.md body** — loaded when the skill triggers. Target < 300 lines;
   hard stop 500 (community reports accuracy degrading past that).
3. **`scripts/` / `references/` / `assets/`** — loaded or executed only on
   demand. Unlimited size. Every reference needs an explicit pointer in the
   body: "Read `references/x.md` when Y."

## Descriptions trigger, they don't summarize

- Pattern: one clause on what it does, then "Use when …" listing the concrete
  phrases, symptoms, and error messages a user would actually type.
- Observed failure mode: when the description summarizes the workflow, agents
  follow the description and never load the body.
- Routers may truncate around 250 characters — front-load.
- Bad: "For async testing." Good: "Use when tests have race conditions,
  timing dependencies, or pass/fail inconsistently."
- Undertriggering is the common failure; be deliberately pushy about contexts.

## Only non-default information

A skill competes with the model's own competence. Every line should push the
agent away from a default it would otherwise follow. If a capable agent would
do it anyway, delete the line. Skills accrete — prune on every edit.

## Scripts over prose

Deterministic work (parsing, validation, scaffolding, format conversion, API
sequences) belongs in executable scripts, not instructions. "Be careful to X"
in prose is a smell that X wanted a script. Scripts let the agent spend turns
on composition instead of reconstruction — and they're testable.

House pattern: single-file Python with PEP 723 inline metadata, run via
`uv run` — no venv, no setup prose:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
```

Always state whether the agent should **run** or **read** each bundled file.

## One skill, one job

Describable in ten words. A handful of focused skills outperforms hundreds of
overlapping ones (each installed skill costs idle tokens and routing
ambiguity). Mixed concerns in one skill cause both over- and under-triggering.

## Guidance form must match failure type

| Observed failure | Right form | Wrong form |
|---|---|---|
| Agent skips a rule under pressure | Hard prohibition + the rationalizations it will try | "Prefer / consider" |
| Wrong output shape | Exact template with REQUIRED fields | List of prohibitions |
| Omissions | Checklist | Prose reminders |

No nuance clauses: "don't X unless it matters" reopens the negotiation the
rule was written to close. Enumerate real exceptions or state the rule flat.

## Skills encode verified success, not speculation

The sharpest 2026 critique: asking a fresh agent to write a skill for a task
nobody has struggled with produces restated defaults ("the PB&J problem" —
you don't know what's hard until you've struggled). Write skills from real
transcripts: what actually went wrong, what actually fixed it. Corollary for
self-improvement: a learnings entry is valuable only when tied to a verified
failure or an explicit user correction.

## The learnings loop

Endorsed pattern for skills that improve over time:

- Keep SKILL.md clean and stable; append dated post-run notes to a sidecar
  (`LEARNINGS.md`) the agent reads before executing.
- Corrections take effect immediately (next read) without churning the skill.
- Periodically *fold*: recurring/confirmed entries move into SKILL.md at the
  point of the mistake; folded and stale entries are deleted.
- Store run-history data outside the skill folder if the skill is installed
  by copy (upgrades wipe it); with symlink installs the folder is the repo,
  so sidecars are safe and versioned.

## Testing without a harness

Minimum viable rigor for a new skill:

1. Lint (spec compliance, house rules).
2. Trigger test: ~3 should-trigger paraphrases + ~3 near-miss should-nots,
   judged against name + first 250 chars of description only.
3. Ideally one real task run with the skill, reading the transcript for
   wasted effort — not just checking the output.

Anthropic's skill-creator goes further (with/without-skill A/B runs, grader
subagents, description-optimization loops); adopt that machinery only when a
skill is high-stakes enough to justify it.

## Skills vs MCP (context for scoping)

Community benchmark: an ~800-token markdown file of `gh` CLI tips
outperformed ~28,000 tokens of MCP tool schemas. Default to CLI + skill for
developer workflows; reserve MCP for auth-gated, non-filesystem, or
customer-facing integrations. Skills handle the "squishy bits" — targeted
instructions for tools the agent can already run.

## Sources

- https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- https://agentskills.io/specification (the open spec; Cursor implements it)
- https://cursor.com/docs/skills
- https://github.com/obra/superpowers — `writing-skills` skill
- https://simonwillison.net/tags/skills/ (Oct 2025 → 2026 coverage)
- https://notes.ansonbiggs.com/youre-probably-using-agent-skills-wrong/ (verified-struggle critique)
- https://www.mindstudio.ai/blog/self-improving-ai-skills-claude-code (learnings loop)
- https://blog.trashwbin.top/en/posts/cli-vs-mcp-vs-skills/ (token benchmarks)
- https://pydevtools.com/handbook/how-to/how-to-write-a-self-contained-script/ (PEP 723 + uv)
