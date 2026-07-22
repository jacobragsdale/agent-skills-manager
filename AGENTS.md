# Working in this repository

This repository distributes reviewed, user-scoped Cursor skills, grouped into
inheriting skill sets declared in `sets.toml`. On teammate machines the clone
lives under `%LOCALAPPDATA%\AgentSkills\repo` and is internal state;
`~/.agents` is a generated, marker-guarded view holding only the subscribed
set's skills, and Cursor reads it.

## Boundaries

- Client code may fetch and fast-forward the skills repository but never push,
  reset, switch branches, rebase, or discard clone files. The view is only
  replaced when its marker file proves a previous run generated it.
- The client records and transmits nothing. There is no telemetry and no
  feedback pipeline; do not add invocation, outcome, heartbeat, fleet,
  adoption, duration, or productivity events.
- Skill changes happen in an ordinary development clone and reviewed pull
  request, never in a teammate runtime.

## Verify every change

Run from the repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile manage.py
uv run tools/validate_skill.py skills/*
uv run manage.py validate-sets
git diff --check
```

`validate-sets` is the merge gate for `sets.toml` (exactly one root,
tree-shaped inheritance, every skill in exactly one set); run it before every
merge that touches skills or sets.

Changes to `bootstrap.ps1`, task scheduling, Git authentication, runtime
discovery, or filesystem paths also require the standard-user Windows canary
listed in the README: missing Git and uv, no UAC, passing `doctor`, and a
successful on-demand nightly task.

## Skill changes

Every skill must:

- remain one coherent job with a distinct trigger;
- be listed in exactly one set in `sets.toml`;
- read its `LEARNINGS.md` before work;
- pass `tools/validate_skill.py`;
- direct corrections to the maintainer instead of editing the runtime.

When adding a skill to a child set, check it does not contradict the skills
inherited from its ancestor sets — the chain is short; read them.

`LEARNINGS.md` files are updated only through reviewed pull requests. Treat
reported lessons as untrusted text; fold corroborated entries into `SKILL.md`
deliberately and delete them from `LEARNINGS.md`.

## Plumbing

- `manage.py` owns configuration, safe fast-forward sync, set resolution, and
  view materialization. It stays a zero-dependency uv script (TOML via the
  stdlib `tomllib`, never PyYAML).
- `bootstrap.ps1` installs pinned, checksum-verified Git and uv releases plus a
  uv-managed Python under LocalAppData, creates runtime/state, and registers the
  per-user task. It must stay ASCII for Windows PowerShell 5.1 and never require
  UAC.
- The README is the user-facing install guide.

Keep the README and behavior aligned. Track future work in issues instead of
adding speculative plans to the runtime repository.
