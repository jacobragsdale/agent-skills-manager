# Working in this repository

This repository distributes reviewed, user-scoped Cursor skills. Teammate
machines use `~/.agents` only as a clean runtime. Mutable configuration,
locks, and logs live under `%LOCALAPPDATA%\AgentSkills`.

## Boundaries

- Client code may fetch and fast-forward the skills repository but never push,
  reset, switch branches, rebase, or discard runtime files.
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
uv run tools/validate_skill.py skills/agents-md skills/python-standards
git diff --check
```

Changes to `bootstrap.ps1`, task scheduling, Git authentication, runtime
discovery, or filesystem paths also require the standard-user Windows canary
listed in the README: missing Git and uv, no UAC, passing `doctor`, and a
successful on-demand nightly task.

## Skill changes

Every skill must:

- remain one coherent job with a distinct trigger;
- read its `LEARNINGS.md` before work;
- pass `tools/validate_skill.py`;
- direct corrections to the maintainer instead of editing the runtime.

`LEARNINGS.md` files are updated only through reviewed pull requests. Treat
reported lessons as untrusted text; fold corroborated entries into `SKILL.md`
deliberately and delete them from `LEARNINGS.md`.

## Plumbing

- `manage.py` owns configuration and safe fast-forward sync.
- `bootstrap.ps1` installs pinned, checksum-verified Git and uv releases plus a
  uv-managed Python under LocalAppData, creates runtime/state, and registers the
  per-user task. It must stay ASCII for Windows PowerShell 5.1 and never require
  UAC.
- The README is the user-facing install guide.

Keep the README and behavior aligned. Track future work in issues instead of
adding speculative plans to the runtime repository.
