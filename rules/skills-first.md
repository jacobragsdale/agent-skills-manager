# Skills first

The team maintains vetted skills in `~/.agents/skills/` — each encodes
lessons from real failures, kept current by a weekly review cycle.

- **Before starting a nontrivial task, check whether a skill covers it**
  (skill descriptions state their triggers). A matching skill's
  instructions override your defaults: it exists because the default
  approach failed for someone.
- Read the skill's `LEARNINGS.md` before executing it — entries there are
  corrections newer than the skill body and take precedence.
- Prefer a skill's bundled scripts over improvising equivalents; run them
  with `uv run <script>` (they are self-contained PEP 723 files).
- If a skill is wrong or stale, still complete the user's task, then record
  what happened per the team improvement loop rule — do not silently
  work around a broken skill and leave it broken for the next person.
- To create or change a skill, use `/propose-skill` (or follow
  `skills/agent-create-skill`) so it goes through validation and review —
  never hand-edit `~/.agents/skills/` outside of `LEARNINGS.md`.
