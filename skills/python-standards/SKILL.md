---
name: python-standards
description: "Apply the team's complete Python project standard: uv with one pyproject.toml, ruff + basedpyright pre-commit hooks, and basedpyright recommended mode. Use when setting up a Python repo, onboarding a brownfield project, or explicitly standardizing its packaging and tooling. Do NOT use for an isolated dependency, lint, or type error; writing tests; or repo agent instructions."
metadata:
  author: jacob
---

# Team Python standards

Bring any Python repo — usually brownfield internal code — to the house
standard: uv-managed, one `pyproject.toml`, ruff + basedpyright enforced by
pre-commit, zero custom setup steps.

## Target state (definition of done)

- [ ] `.python-version` pins `3.11`; `requires-python = ">=3.11"`
- [ ] One `pyproject.toml` declares everything: runtime deps, dev deps in
      `[dependency-groups]`, build workarounds under `[tool.uv]`, and all
      tool config (ruff, basedpyright)
- [ ] No `requirements*.txt`, `setup.py`, `setup.cfg`, `Pipfile`, or custom
      setup scripts remain
- [ ] `uv.lock` committed; `uv sync` succeeds from a fresh clone
- [ ] Pre-commit installed: ruff format + lint, basedpyright, uv-lock
- [ ] basedpyright passes in `recommended` mode (baseline only as a last
      resort, never as the strategy)
- [ ] `.env.example` committed; real env files gitignored
- [ ] Every entry point runs as a single `uv run` command, listed in the README

## Hard rules

- Never `pip install` anything. Never write or keep a setup shell script.
  Every dependency or build fix lands in `pyproject.toml`.
- Python 3.11 only. Do not "helpfully" upgrade.
- Never weaken lint/type rules globally to silence one file — use
  per-file-ignores and leave the global bar where it is.
- Fixes to type errors must not change runtime behavior; the test suite (if
  one exists) must end in the identical state it started in.

## Workflow

### 1. Audit

RUN `scripts/audit_repo.py <repo-root>`. It reports legacy packaging files,
setup scripts, entry-point candidates, env-var reads, and gitignore state —
this is the migration worklist.

### 2. pyproject on 3.11

`uv python pin 3.11`; `uv init --bare` if there is no `pyproject.toml`.
Migrate dependencies IN, then delete the source in the same commit:
`uv add -r requirements.txt` (dev files via `--dev`); `setup.py`/`setup.cfg`
contents move to `[project]`; anything a custom setup script did must be
re-expressed as pyproject config or `.env.example` entries before deleting
it — read it line by line.

### 3. The sync loop

Run until clean, fixing ONE error at a time: `uv sync` → on failure READ
`references/troubleshooting.md` and match the error signature → apply the
fix in `pyproject.toml` (or `.env.example` for env-var fixes) → repeat.
Verify from zero: remove `.venv` with the platform-appropriate filesystem
command, then run `uv sync` and
`uv run python -c "import <top_level_package>"`.

### 4. Pre-commit: ruff + basedpyright

READ `references/precommit-and-lint.md` and copy its `[tool.ruff]` and
`.pre-commit-config.yaml` templates (basedpyright runs as a local hook via
`uv run` so it sees the project venv). Then:

```bash
uv add --dev ruff basedpyright pre-commit
uv run pre-commit install && uv run pre-commit run --all-files
```

Brownfield lint cleanup order: `uv run ruff check --fix`, review
`--unsafe-fixes`, hand-fix the rest, per-file-ignores only for genuine
hotspots.

### 5. Type checking

Use the `[tool.basedpyright]` configuration from step 4. A stray
`pyrightconfig.json` silently overrides pyproject; reconcile existing settings
into one place before running:

```bash
uv run <skill>/scripts/triage.py --project <repo> --json /tmp/tri-0.json
```

Never run bare basedpyright for triage — the script's tiered grouping is
the deterministic worklist. Report totals and the plan to the user before
fixing. Fix in this order, one commit per batch, re-running `triage.py
--diff <snapshot>` after each (zero NEW diagnostics allowed):

1. **Stubs**: `uv add --dev types-<pkg>` per `reportMissingTypeStubs`;
   `allowedUntypedLibraries` for libs with none. Never hand-write stubs
   that guess at behavior.
2. **Cascade sources**: annotate the most-imported unannotated signatures
   first — one boundary fix can clear hundreds of `reportUnknown*` errors.
   Fix the source, never each usage site.
3. **Everything else** by rule, highest count first. For rules or baseline
   mechanics not covered here, READ `references/rules.md`.

Before finishing, inspect the complete diff for runtime behavior changes and
re-run the repository's existing tests.

### 6. Env and entry points

`.env.example` committed (every var the code reads, one comment each); real
`.env*` files gitignored (`.env`, `.env.*`, `!.env.example`); commands load
explicitly via `uv run --env-file .env ...`; code reads `os.environ` only —
no dotenv dependency. Every way of running the project becomes exactly one
`uv run` command (console scripts in `[project.scripts]`, else
`uv run --env-file .env python -m pkg.main`); wrappers and Makefile
env-fiddling get deleted. List them in a README "Running" table.

## Bundled resources

- `scripts/audit_repo.py` — RUN first on any brownfield repo.
- `scripts/triage.py` — RUN for every type check; never bare basedpyright.
- `references/troubleshooting.md` — READ at the first `uv sync` failure.
- `references/precommit-and-lint.md` — READ in step 4; copy templates.
- `references/rules.md` — READ for uncovered diagnostic rules and baseline mechanics.
