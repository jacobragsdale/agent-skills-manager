# How agents discover and invoke skills

Verified against official docs 2026-07. Read this when tuning triggering or
deciding what belongs in the description vs body vs references/.

## The universal model (agentskills.io progressive disclosure)

All four target agents implement the same three levels:

1. **Always in context:** every discovered skill's `name` + `description`
   (~100 tokens/skill). This is the ONLY routing signal — the body is
   invisible until the skill fires.
2. **On activation:** the full SKILL.md body is injected — and in Claude
   Code it persists in context for the rest of the session. Every body line
   is a recurring cost after first use.
3. **On demand:** `references/*.md` are read only when the body points to
   them; `scripts/` are executed, never loaded (only output costs tokens).

## Per-agent mechanics

| | Cursor | Claude Code | Codex | Copilot |
|---|---|---|---|---|
| Reads `~/.agents/skills` | yes | **no** | yes | yes |
| Other user paths | `~/.cursor/skills`, compat: `~/.claude`, `~/.codex` | `~/.claude/skills` only | `/etc/codex/skills` | `~/.copilot/skills`, `~/.claude/skills` |
| Description budget | none — injects everything it finds | 1% of context window; 1,536 chars/entry; least-invoked dropped first (`/doctor` shows) | 2% of context or 8,000 chars | undocumented |
| Duplicate handling | **none — same skill in two paths injects twice** | deduped | — | — |
| Explicit invoke | `/name`, `@` mention | `/name`, Skill tool | `/skills`, `$name` | `/name` (VS Code) |
| `disable-model-invocation` | honored; description withheld from context | honored; description removed from context | via `openai.yaml` `allow_implicit_invocation` | honored (VS Code) |
| `paths` scoping | yes — description withheld until matching files in play | yes (v2.1+) | no | no |
| `context: fork` (subagent) | no | yes | no | experimental (VS Code) |

Implications for this repo:

- The team clone at `~/.agents` natively serves Cursor, Codex, and Copilot.
  **Claude Code needs per-skill links** into `~/.claude/skills` (manage.py
  maintains them when `AGENT_SKILLS_CLAUDE=1`). Caution: Cursor also scans
  `~/.claude/skills` as a compat path and does NOT dedupe — on a machine
  running both, disable Cursor's "Include third-party Plugins, Skills, and
  other configs" setting to avoid double injection.
- `disable-model-invocation: true` is also a context-economy tool: the
  description leaves context entirely. Right for explicit-only workflows;
  fatal for anything that should trigger from conversation.
- `paths` withholds the description until the agent touches matching files.
  Use only when the skill is genuinely file-bound — a "set up X on this
  repo" request may route before any matching file has been read, and the
  skill will silently not exist.

## What the evidence says about triggering

- **Agents under-trigger by default.** They skip skills for tasks that look
  easy and treat skill listings as advisory (one production study measured
  a needed, installed skill skipped in 56% of cases). Descriptions must be
  pushy: "Use whenever the user mentions X, Y, Z — even if they don't say
  <domain> explicitly."
- **Over-triggering comes from breadth and overlap.** Documented failures:
  one broad "backend guidance" skill firing on unrelated queries (fixed by
  splitting into three narrow skills); two skills sharing the phrase "HIPAA
  compliance" both firing on every match. Keep trigger domains exclusive
  across the library, and give near-neighbor skills explicit "Do NOT use
  when … (use <other-skill>)" boundaries — Anthropic's own shipped skills
  do this.
- **Front-load the description.** Truncation (1,536 chars in Claude Code,
  ~250 visible in some pickers) eats the tail; the key use case and hottest
  trigger words go in the first sentence.
- **Third person.** "Processes X, generates Y. Use when …" — first/second
  person measurably hurts discovery in system-prompt injection.
- **Leaner bodies perform better.** A 55k-skill study found >60% of typical
  body content non-actionable, and compressing bodies ~39% *improved* task
  performance. Production sweet spot: **under ~150 lines for
  model-invocable skills** (~250 for explicit-only); hard spec ceiling 500
  lines / ~5k tokens. Everything else goes to references/ with an explicit
  "read X when Y" pointer — never "see references/ for details".

## Rules (always-on) vs skills (routed): where rules actually load

There is no user-global always-on rules path that works everywhere:

| Agent | User-global always-on | Project always-on |
|---|---|---|
| Cursor | Settings → Rules (User Rules) — manual paste only; `~/.agents/rules` is NOT read | `.cursor/rules/`, root `AGENTS.md` |
| Claude Code | `~/.claude/CLAUDE.md` (can `@import` files) | `CLAUDE.md`, `.claude/rules/` |
| Codex | `~/.codex/AGENTS.md` (32 KiB combined cap) | `AGENTS.md` chain root→cwd |
| Copilot | none (VS Code reads `~/.claude/CLAUDE.md`) | root `AGENTS.md`, `.github/copilot-instructions.md` |

Consequence: instructions that must accompany every skill use belong in the
skill's own body/footer (in context exactly when needed, zero cost
otherwise) — not in a rules file that most agents never load.
