# Working in this repo

This is the team's Agent Skills repo (agentskills.io format). On teammate
machines it is cloned directly as `~/.agents` and managed by a nightly sync
(`manage.py`): the working tree hard-resets to `origin/main` every night, so
**local edits outside the sanctioned paths are lost by design**.

Sanctioned local writes (collected upstream automatically by the nightly
harvest — the instructions ride each skill's footer):

- `skills/<name>/LEARNINGS.md` — dated corrections after using a skill
- `.manager/usage.jsonl` — one JSON line per skill use
- `.manager/requests.md` — demand signal for skills that don't exist yet

Everything else changes through pull requests:

- **Creating or changing a skill?** Use `/propose-skill`, which follows
  `skills/agent-create-skill/SKILL.md` — the house process (clarify →
  scaffold → draft → validate → trigger test → learnings loop).
- Every skill must pass
  `uv run skills/agent-create-skill/scripts/validate_skill.py skills/<name>`
  before commit. Treat warnings as decisions, not noise.
- All bundled Python is a single file with a PEP 723 `# /// script` header,
  runnable via `uv run` with no environment setup.
- Never edit a skill's SKILL.md to record a one-off correction — append a
  dated line to that skill's `LEARNINGS.md` instead. Folding learnings into
  SKILL.md happens in the weekly reviewed fold PR, not on the fly.
- One skill, one job. If a change makes a skill's description need an
  "and", split it.

Repo plumbing (`manage.py`, `bootstrap.ps1`, `prompts/`, `learnings/`,
`metrics/`, `requests/`, `machines/`) is documented in `README.md`.
