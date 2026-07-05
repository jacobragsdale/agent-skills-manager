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
| `disable-model-invocation` | `true` → never auto-triggered; only explicit `/skill-name`. **House default for every skill in this repo** (set by `init_skill.py` unless `--auto-trigger` is passed) — not just for consequential workflows. |

Cursor discovers skills in `.agents/skills/`, `.cursor/skills/`, `~/.agents/skills/`,
`~/.cursor/skills/`, and (compat) `.claude/skills/` + `~/.claude/skills/`.

## Claude Code extensions

| Field | Notes |
|---|---|
| `disable-model-invocation` | Same semantics as Cursor. |
| `user-invocable` | `false` hides the skill from the `/` menu (model-only). |
| `context` | `fork` runs the skill in a subagent and returns a summary — keeps verbose output out of the main context. |
| `agent` | Which agent type executes a forked skill. |
| `model` / `effort` | Model/effort override while the skill runs. |
| `allowed-tools` | Tools pre-approved while the skill runs. |
| `argument-hint` | Hint shown after `/skill-name` for expected arguments. |
| `hooks` | Attach lifecycle hooks scoped to the skill. |

Claude Code discovers skills in `.claude/skills/` and `~/.claude/skills/` only
(no `.agents/` support — hence this repo's symlink installer).

## Portability guidance

- Need Cursor-only scoping? `paths` is safe: Claude Code ignores it (warns in
  its validator but still loads the skill).
- Slash-command-only skills: `disable-model-invocation: true` works in both.
- Don't rely on `allowed-tools` for safety — treat it as convenience
  pre-approval where supported, nothing more.
