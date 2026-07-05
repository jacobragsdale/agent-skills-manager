# SKILL.md frontmatter reference

Portability rule of thumb: `name` + `description` work everywhere; everything
else degrades gracefully (unknown fields are ignored) but only *does*
something in the agents noted below. Our validator warns on fields outside
these tables.

## Core spec (agentskills.io) — safe everywhere

| Field | Required | Notes |
|---|---|---|
| `name` | yes | 1–64 chars, `^[a-z0-9]+(-[a-z0-9]+)*$`, **must match the folder name**. Claude Code silently ignores skills with non-compliant names. |
| `description` | yes | 1–1024 chars. The trigger surface — front-load "Use when …" into the first ~250 chars. |
| `license` | no | License name or pointer to a bundled license file. |
| `compatibility` | no | Free text (max 500 chars) describing environment requirements. |
| `metadata` | no | Arbitrary key-value mapping (author, version, …). Ignored by routing. |
| `allowed-tools` | no | Experimental. Space-separated pre-approved tools, e.g. `Bash(git:*) Read`. Support varies by agent. |

## Cursor extensions

| Field | Notes |
|---|---|
| `paths` | Glob patterns (comma-separated string or list). Skill is only surfaced when the agent reads/edits matching files. Skills in nested project dirs are auto-scoped to that dir without `paths`. |
| `disable-model-invocation` | `true` → never auto-triggered; only explicit `/skill-name`. House default is model-invocable (flag omitted); `init_skill.py --explicit-only` adds it for consequential/destructive workflows. |

Cursor discovers skills in `.agents/skills/`, `.cursor/skills/`, `~/.agents/skills/`,
`~/.cursor/skills/`, and (compat) `.claude/skills/` + `~/.claude/skills/`.

## Claude Code extensions

| Field | Notes |
|---|---|
| `disable-model-invocation` | Same semantics as Cursor — description leaves context entirely. |
| `user-invocable` | `false` hides the skill from the `/` menu only; does NOT block the Skill tool. |
| `when_to_use` | Extra trigger text appended to the description in the listing (shares its 1,536-char cap). |
| `paths` | Glob scoping, same idea as Cursor's. |
| `context` | `fork` runs the skill in an isolated subagent and returns a summary — keeps verbose output out of the main context. Task-shaped skills only. |
| `agent` | Which agent type executes a forked skill. |
| `model` / `effort` | Model/effort override while the skill runs. |
| `allowed-tools` / `disallowed-tools` | Tools pre-approved / removed while the skill runs. |
| `argument-hint` / `arguments` | `/skill-name` argument UI and named `$var` substitution. |
| `hooks` | Attach lifecycle hooks scoped to the skill. |

Claude Code discovers skills in `.claude/skills/` and `~/.claude/skills/`
only — it does NOT read `.agents/` (manage.py bridges with per-skill links
when `AGENT_SKILLS_CLAUDE=1`). Descriptions share a listing budget of ~1% of
the context window; least-invoked skills lose their descriptions first.

## Codex and Copilot

Both implement the agentskills.io core spec and read `~/.agents/skills/`
natively — `name` + `description` is all they need. Codex extras live in an
optional `agents/openai.yaml` (e.g. `allow_implicit_invocation`), not in
SKILL.md frontmatter. Copilot (VS Code) additionally honors
`argument-hint`, `user-invocable`, `disable-model-invocation`, and
experimental `context: fork`; GitHub-side Copilot honors `license` and
`allowed-tools`. Neither supports `paths` scoping.

## Portability guidance

- Need Cursor-only scoping? `paths` is safe: Claude Code ignores it (warns in
  its validator but still loads the skill).
- Slash-command-only skills: `disable-model-invocation: true` works in both.
- Don't rely on `allowed-tools` for safety — treat it as convenience
  pre-approval where supported, nothing more.
