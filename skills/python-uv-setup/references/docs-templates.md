# README.md and AGENTS.md skeletons

Fill every `<...>` placeholder; delete sections that genuinely don't apply
(e.g. Configuration when there are no env vars). The Running table and the
Configuration table are REQUIRED — they are the contract that every entry
point is one `uv run` command and every env var is documented.

## README.md skeleton

```markdown
# <project-name>

<One paragraph: what this does and who uses it.>

## Requirements

- [uv](https://docs.astral.sh/uv/) — that's it. uv installs Python 3.11 itself.

## Setup

    uv sync
    uv run pre-commit install
    cp .env.example .env.dev   # fill in real values
    ln -sf .env.dev .env       # .env always points at the active environment

## Configuration

Environments live in `.env.dev` / `.env.staging` / `.env.prod` (gitignored);
`.env` is a symlink to the active one — switch with `ln -sf .env.staging .env`.
All variables:

| Variable | Purpose | Example |
|----------|---------|---------|
| `<VAR>`  | <what it controls> | `<placeholder>` |

## Running

| Command | What it does |
|---------|--------------|
| `uv run --env-file .env <entry>` | <description> |

## Development

    uv run pytest                                  # tests
    uv run ruff check --fix && uv run ruff format  # lint + format
    uv run basedpyright                                 # type check

Pre-commit runs all of the above on commit.

## Troubleshooting

<Only repo-specific gotchas discovered during setup — proxy exports needed
before `uv sync`, double-sync for no-build-isolation packages, etc.>
```

## AGENTS.md skeleton

Keep it short and command-first — an agent should be productive from this
file alone without reading the README. (This is the quick Python-specific
version; for a thorough, interview-driven AGENTS.md, use the `agents-md`
skill.)

```markdown
# AGENTS.md

## Setup

- `uv sync` — the only setup step. Python 3.11, managed by uv.
- NEVER `pip install`. NEVER create requirements.txt. All dependencies go in
  `pyproject.toml` via `uv add` (dev deps: `uv add --dev`).

## Commands

- Run: `uv run --env-file .env <entry>`
- Test: `uv run pytest`
- Lint/format: `uv run ruff check --fix && uv run ruff format`
- Type check: `uv run basedpyright`

## Conventions

- All dependency and tool config lives in `pyproject.toml` — no other config
  files for packaging, ruff, or basedpyright.
- Env vars: code reads `os.environ` only. Any new variable must be added to
  `.env.example` with a comment.
- New entry points get a `[project.scripts]` entry (or documented
  `python -m` command) AND a row in the README Running table.
- Commits must pass pre-commit (ruff, basedpyright, uv-lock).

## Gotchas

<repo-specific — e.g. "export proxy vars before uv sync: set -a; source .env; set +a">
```
