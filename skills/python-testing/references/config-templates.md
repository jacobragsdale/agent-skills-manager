# Config templates: pytest, coverage, pre-commit

All config lives in the one `pyproject.toml`, per the `python-uv-setup`
standard. Copy these blocks, then adjust only the marked values.

## Dependencies

```bash
uv add --dev pytest pytest-cov pytest-randomly pytest-mock
```

(`pytest-randomly` shuffles test order every run so hidden inter-test
dependencies surface immediately instead of in six months.)

## pyproject.toml

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers", "--strict-config", "--import-mode=importlib"]
xfail_strict = true
filterwarnings = ["error"]
markers = [
    "integration: touches a real DB/network/container; excluded from pre-commit, run with `uv run pytest -m integration`",
]

[tool.coverage.run]
branch = true
source = ["src"]          # ADJUST if the repo doesn't use src/ layout

[tool.coverage.report]
fail_under = 0            # ADJUST: the ratchet — see below
skip_covered = true
show_missing = true
```

Why the strict flags: `--strict-markers`/`--strict-config` turn typo'd
markers and config into errors; `filterwarnings = ["error"]` makes
deprecation rot a test failure instead of scroll-by noise. If a third-party
warning is genuinely unfixable, add a targeted
`"ignore:<msg>:<category>:<module>"` entry — never delete the `"error"`.

Async repos add: `asyncio_mode = "auto"` under `[tool.pytest.ini_options]`
after `uv add --dev pytest-asyncio`.

## The coverage ratchet

`fail_under` starts at current measured branch coverage, rounded DOWN to an
integer (`uv run pytest --cov` prints it). It only ever increases — raise
it after work that adds coverage. Do not chase a number: coverage is a map
of what's untested, not a target. Never add tests whose only purpose is
moving the percentage (hard rule 1 still applies). ~85% branch coverage is
a healthy plateau for most repos; 100% is not a goal.

## Test layout

```
tests/
  conftest.py          # shared fixtures ONLY if genuinely shared; keep small
  fixtures/            # serialized fixture files — each needs a validation test
  test_<module>.py     # mirrors src/<pkg>/<module>.py
```

Mirror `src/` one-to-one so the test file for any module is findable
without grep. Fixtures live at the narrowest conftest that needs them —
a fixture used by one file belongs in that file, not conftest.py.

## Pre-commit hook (commit-gated)

Appended to the `.pre-commit-config.yaml` from `python-uv-setup` (after the
ruff/basedpyright hooks — cheap checks fail first):

```yaml
  - repo: local
    hooks:
      - id: pytest
        name: pytest (unit, with coverage ratchet)
        entry: uv run pytest -m "not integration" --cov -q
        language: system
        pass_filenames: false
        types: [python]
```

The full unit suite runs on every commit — this is the chosen house
trade-off, and it's why hard rule 10 (unit tests in milliseconds,
everything slow behind the `integration` marker) is non-negotiable. If the
hook creeps past ~30 seconds, the fix is finding the slow tests
(`uv run pytest --durations=10`) and moving/fixing them — not `--no-verify`
and not removing the hook.

Integration tests run on demand (`uv run pytest -m integration`) with real
credentials/containers available — document that command in the README
Running table.
