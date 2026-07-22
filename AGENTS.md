# Working in this repository

This repository distributes one flat pack of reviewed, user-scoped Cursor
skills. On teammate machines the clone lives under
`%LOCALAPPDATA%\AgentSkills\repo` and is internal state; `~/.agents` is a
generated, marker-guarded view holding every skill, and Cursor reads it.

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
uv run manage.py validate-skills
git diff --check
```

`validate-skills` is the merge gate for the flat skills directory; run it
before every merge that touches a skill.

Changes to `bootstrap.ps1`, task scheduling, Git authentication, runtime
discovery, or filesystem paths also require the standard-user Windows canary
listed in the README: missing Git and uv, no UAC, passing `doctor`, and a
successful on-demand nightly task.

## Skill changes

Every skill must:

- remain one coherent job with a distinct trigger;
- live at `skills/<name>/SKILL.md` with any references or scripts beside it;
- pass `manage.py validate-skills`.

## Plumbing

- `manage.py` owns configuration, safe fast-forward sync, validation, and view
  materialization. It stays a zero-dependency uv script.
- `bootstrap.ps1` installs pinned, checksum-verified Git and uv releases plus a
  uv-managed Python under LocalAppData, creates runtime/state, and registers the
  per-user task. It must stay ASCII for Windows PowerShell 5.1 and never require
  UAC.
- The README is the user-facing install guide.

Keep the README and behavior aligned. Track future work in issues instead of
adding speculative plans to the runtime repository.
