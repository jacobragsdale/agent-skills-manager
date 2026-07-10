# Working in this repository

This repository distributes reviewed, user-scoped Cursor skills. On teammate
machines it is cloned to `~/.agents` as a runtime appliance. Mutable state is
stored under `%LOCALAPPDATA%\AgentSkills`; the runtime must stay completely
clean and on its configured branch.

## Boundaries

- Never make a teammate runtime an authoring workspace.
- Never add a client path that pushes the skills repository or bypasses branch
  policy. Clients push only their own `inbox/v1/<machine>/<month>` ref in the
  separate inbox repository.
- Normal sync is fetch plus fast-forward only. Do not add `reset --hard`,
  automatic branch switching, force pushes, or rebases to runtime code.
- Treat inbox branches, event JSON, and learning text as untrusted data.
- Do not expand the telemetry schema without updating validation, tests,
  `PRIVACY.md`, retention, and dashboard language in the same PR.
- Do not describe `recorded_invocations` as adoption. Agent-written events are
  a lower-bound signal.
- Do not reintroduce teammate skill proposals, request spools, proposal branch
  sweeping, or unattended semantic rewriting.

## Verify every change

Run from the repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile manage.py
uv run tools/validate_skill.py skills/agents-md skills/python-standards
git diff --check
```

Changes to `bootstrap.ps1`, `install.cmd`, `fix-signin.cmd`, task scheduling,
Git authentication, runtime discovery, or filesystem paths also require the
Windows VM and Cursor canary protocol in `TESTING.md`. Record results there;
unit tests are not evidence that a GUI or standard-user install works.

## Skill changes

Maintainers change skills through an ordinary development branch and reviewed
pull request. Every skill must:

- pass `tools/validate_skill.py`;
- remain one coherent job with a distinct trigger domain;
- read its `LEARNINGS.md` before work;
- record invocation start near the beginning and outcome near handoff;
- send factual corrections through `manage.py record-learning` rather than
  editing the runtime checkout;
- avoid collecting prompts, code, paths, names, hosts, or secrets.

One-off field corrections land in a reviewed aggregation PR as
`skills/<name>/LEARNINGS.md`. A maintainer folds corroborated lessons into
`SKILL.md` deliberately and validates the result.

## Repository plumbing

- `manage.py` owns configuration, locking, safe sync, event validation, local
  spooling, inbox publication, and aggregation. It stays standard-library
  Python with a PEP 723 header.
- `bootstrap.ps1` installs Git and uv, creates runtime/state, registers the
  Windows task, and must stay ASCII for Windows PowerShell 5.1.
- `metrics/ingestion-state.json` is a reviewable checkpoint and processed-ID
  map. Never advance a rewritten or invalid append-only branch silently.
- `metrics/history.jsonl` is generated aggregate history, not raw event data.
- `metrics/REJECTED.md` records content-free rejection reasons; never paste raw
  sensitive events into it.
- `PRIVACY.md` is the collection and retention contract.

Keep `README.md`, `ROADMAP.md`, and `TESTING.md` aligned with behavior that is
actually implemented and verified. Avoid calling a prompt, protocol, or future
job "built" until its code and acceptance test exist.
