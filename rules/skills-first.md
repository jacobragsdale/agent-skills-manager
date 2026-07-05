# Skills first (always-on rule)

<!-- INSTALL NOTE (not part of the rule): no agent auto-loads this file from
~/.agents/rules/. Make it always-on per agent — Cursor: paste into Settings →
Rules (User Rules); Claude Code: import from ~/.claude/CLAUDE.md; Codex:
append to ~/.codex/AGENTS.md; Copilot: repo AGENTS.md. -->

The team maintains vetted skills in `~/.agents/skills/` — each encodes
lessons from real failures, kept current by a weekly review cycle.

- **Before starting a nontrivial task, check whether an available skill
  covers it — and use it if so.** A matching skill overrides your default
  approach: it exists because the default failed for someone. Do not skip a
  skill because the task looks easy or you believe you already know how.
- Read the skill's `LEARNINGS.md` before executing it — entries there are
  newer than the skill body and take precedence.
- Prefer a skill's bundled scripts over improvising equivalents (`uv run
  <script>`; they are self-contained PEP 723 files).
- If a skill is wrong or stale, still complete the user's task, then record
  what happened per the skill's "Improving this skill" footer — never
  silently work around a broken skill and leave it broken for the next
  person.
- To create or change a skill, use `/propose-skill` (or follow
  `skills/agent-create-skill`) — never hand-edit `~/.agents/skills/`
  outside of `LEARNINGS.md`.
