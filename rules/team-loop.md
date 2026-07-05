# Team improvement loop (always-on rule)

<!-- INSTALL NOTE (not part of the rule): no agent auto-loads this file from
~/.agents/rules/. Make it always-on per agent — Cursor: paste into Settings →
Rules (User Rules); Claude Code: import from ~/.claude/CLAUDE.md; Codex:
append to ~/.codex/AGENTS.md; Copilot: repo AGENTS.md. Per-skill duties
(learnings, usage logging) ride each skill's footer and need no rule. -->

The team maintains vetted skills in `~/.agents/skills/` — a managed git
clone that syncs nightly. Two duties apply in every session:

1. **Unmet needs are signal.** If the user struggles with a task (wrong
   attempts, corrections, long detours), you worked it out the hard way,
   and no skill covers it, append one line to
   `~/.agents/.manager/requests.md` (create if missing):
   `- YYYY-MM-DD: <task that needed a skill> — <what was hard without one>`.
   This feeds the team's ranked backlog of skills worth building.

2. **Never put secrets, credentials, customer data, or proprietary file
   contents** into anything under `~/.agents` — learnings, usage logs, and
   requests land in a shared repo. Write only to the sanctioned paths
   (`skills/*/LEARNINGS.md`, `.manager/usage.jsonl`, `.manager/requests.md`);
   everything else there is reset nightly and edits are silently lost.
