---
name: python-uv-setup
description: "Standardize or set up a Python repo on uv: single pyproject.toml, pre-commit (ruff + basedpyright), .env management, uv run entry points, README/AGENTS.md. Use when onboarding brownfield code to uv, fixing uv sync failures (undeclared build deps, SSL, proxy, private PyPI auth), or migrating off requirements.txt / setup.py / custom setup scripts."
disable-model-invocation: true
---

# Python environment setup with uv

Bring a Python repo — usually brownfield internal code — up to the house
standard: uv-managed, one pyproject.toml, zero custom setup steps.

## Target state (definition of done)

- [ ] `.python-version` pins `3.11`; `requires-python = ">=3.11"` (everything is 3.11 for now)
- [ ] One `pyproject.toml` declares everything: runtime deps, dev deps in
      `[dependency-groups]`, build workarounds under `[tool.uv]`, and all tool
      config (ruff, basedpyright, pytest)
- [ ] No `requirements*.txt`, `setup.py`, `setup.cfg`, `Pipfile`,
      `environment.yml`, or custom setup scripts remain
- [ ] `uv.lock` committed; `uv sync` succeeds from a fresh clone with no manual steps
- [ ] Pre-commit installed: ruff format + lint, basedpyright, uv-lock, hygiene hooks
- [ ] `.env.example` committed; real env files gitignored; switch convention documented
- [ ] Every entry point runs as a single `uv run` command and is listed in the README
- [ ] `README.md` and `AGENTS.md` written from the templates

## Hard rules

- Never `pip install` anything. Never write or keep a setup shell script.
  Every dependency or build fix lands in `pyproject.toml`.
- If a fix genuinely requires an environment variable (proxy, CA bundle),
  it goes in `.env.example` with a comment and in the README — never left
  as undocumented shell state.
- Python 3.11 only. Do not "helpfully" upgrade to a newer Python.
- Do not weaken lint/type rules globally to silence one file — use
  per-file-ignores and leave the global bar where it is.

## Workflow

### 0. Audit

RUN `scripts/audit_repo.py <repo-root>` (from this skill's folder). It reports
legacy packaging files, setup scripts, entry-point candidates, env-var reads,
and `.env`/gitignore state. Use its output as the migration worklist.

### 1. Establish pyproject.toml on 3.11

- `uv python pin 3.11`. If there is no `pyproject.toml`, run `uv init --bare`
  and fill in `[project]` (name, version, description, `requires-python`).
- Migrate dependencies **into** pyproject, then delete the source in the same
  commit:
  - `uv add -r requirements.txt`; dev files via `uv add --dev -r requirements-dev.txt`
  - `setup.py` / `setup.cfg`: move `install_requires` to `[project] dependencies`,
    console_scripts to `[project.scripts]`, then delete both files
  - Anything a custom setup script did (pip installs, env exports, apt notes)
    must be re-expressed as pyproject config or `.env.example` entries before
    the script is deleted — read the script line by line, don't just remove it.

### 2. The sync loop

Run this tight loop until clean — fix ONE error at a time:

1. `uv sync`
2. On failure, READ `references/troubleshooting.md` and match the error
   signature (undeclared build deps, git/SSL, proxy, private index auth are
   all covered).
3. Apply the fix — in `pyproject.toml` (or `.env.example` for env-var fixes).
4. Repeat.

If you solve an error that is NOT in the playbook, append an entry to
`references/troubleshooting.md` in the skills repo before moving on (format
is at the top of that file). This is how the skill learns.

Sync-time env vars (proxy, CA bundles) are not loaded from `.env` by
`uv sync` — export them first: `set -a; source .env; set +a`.

Verify from zero before calling it done:
`rm -rf .venv && uv sync && uv run python -c "import <top_level_package>"`,
plus `uv run pytest` if tests exist.

### 3. Lint, types, pre-commit

READ `references/precommit-and-lint.md` and copy its three templates:
`[tool.ruff]`, `[tool.basedpyright]` (basic mode for brownfield — NOT the
default "recommended", which buries untyped code), and
`.pre-commit-config.yaml` (basedpyright runs as a local hook via `uv run`
so it sees the project venv). Then:

```bash
uv add --dev ruff basedpyright pre-commit
uv run pre-commit install
uv run pre-commit run --all-files
```

Brownfield cleanup order: `uv run ruff check --fix`, review
`--unsafe-fixes`, hand-fix the remainder, per-file-ignores only for genuine
hotspots.

### 4. .env management

The convention (document it in the README):

- `.env.example` — committed. Every variable the code reads, placeholder
  values, one comment per var.
- One real file per environment: `.env.dev`, `.env.staging`, `.env.prod` —
  all gitignored.
- `.env` is a **symlink** to the active environment:
  `ln -sf .env.dev .env`. Switching environments = repointing the symlink.
- Commands load it explicitly: documented run commands use
  `uv run --env-file .env ...`. One-off override:
  `uv run --env-file .env.staging <cmd>`.
- Code reads `os.environ` only — no `load_dotenv()` calls, no dotenv dependency.

Gitignore block:

```gitignore
.env
.env.*
!.env.example
```

Cross-check: every var the audit script found in code must appear in
`.env.example`, and vice versa.

For sharing the VALUES across the team (encrypted `secrets/*.env` committed
to the repo, decrypted locally), READ `references/secrets.md` — it also has
the Windows-specific commands and the no-symlink variant of this scheme.

### 5. Entry points

Every way of running the project becomes exactly one `uv run` command:

- Packaged code: `[project.scripts]` console entries → `uv run <name>`
- Unpackaged modules: `uv run --env-file .env python -m pkg.main`
- Anything currently launched via bash wrapper, Makefile env-fiddling, or
  `python setup.py <cmd>` gets converted and the wrapper deleted.

List them all in a README "Running" table: `| command | what it does |`.

### 6. Docs

READ `references/docs-templates.md`; write `README.md` and `AGENTS.md` from
the skeletons, filling the Running table and env-var table from what you
built in steps 4–5.

## Example

Brownfield repo with `requirements.txt`, `setup.py`, and `run_server.sh`
(which exported three env vars and pip-installed a private wheel) ends as:

```toml
[project]
name = "billing-sync"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.115", "internal-billing-client>=2"]

[project.scripts]
serve = "billing_sync.server:main"

[dependency-groups]
dev = ["ruff", "basedpyright", "pre-commit", "pytest"]

[tool.uv.extra-build-dependencies]
old-c-lib = ["setuptools", "cython"]   # undeclared build dep, found via sync loop
```

plus `.env.example` holding the three vars, `run_server.sh` deleted, and a
README Running table whose only entry is
`uv run --env-file .env serve`.

## Bundled resources

- `scripts/audit_repo.py` — RUN first on any brownfield repo; prints the migration worklist.
- `references/troubleshooting.md` — READ at the first `uv sync` failure; APPEND newly solved errors. Contains the private-PyPI TODO block.
- `references/precommit-and-lint.md` — READ in step 3; copy templates from it.
- `references/secrets.md` — READ when the team needs to share env values (SOPS + age, Windows-first).
- `references/docs-templates.md` — READ in step 6; README + AGENTS.md skeletons.

## Improving this skill

Solved `uv sync` errors are domain knowledge, not process corrections — they
go in `references/troubleshooting.md` (see step 2), not LEARNINGS.md.

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
