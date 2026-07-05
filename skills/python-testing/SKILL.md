---
name: python-testing
description: "Write, backfill, or review pytest suites: readable behavior-driven tests, minimal mocking, test data that can't silently drift. Use when writing unit tests for new code, adding tests to an untested repo, auditing a suite for over-mocked or tautological tests, or wiring pytest + coverage into pre-commit. Covers pydantic/polyfactory test data, pandera for DataFrames, and faking Oracle/MSSQL stored procedures with contract tests."
disable-model-invocation: true
---

# Python testing

Bring a repo's tests to the house standard: behavior-driven pytest suites a
non-expert can read, minimal mocking, and test data mechanically tethered to
the real schemas so it cannot silently rot. Assumes the repo is on the
`python-uv-setup` standard (one pyproject.toml, uv, pre-commit).

The reader of every test is someone who does NOT know testing jargon. A test
is done when they can read it top to bottom and say what behavior it protects.

## Hard rules

1. **Every test must be able to fail.** Before writing a test, name the
   plausible bug that would make it fail. If you cannot name one, do not
   write the test. This kills getter tests, "it returns a dict" tests, and
   mock-echo tests.
2. **Expected values come from the spec, docstring, or requirement — never
   from running the code and pasting its output.** If the expected behavior
   is unclear, stop and ask the user what the code is supposed to do; that
   answer becomes the docstring AND the test.
3. **Test names are behavior sentences**:
   `test_expired_token_is_rejected`, `test_negative_amounts_raise_value_error`.
   Never `test_process_2`, never just `test_<function_name>`.
4. **One behavior per test. Arrange-Act-Assert with a blank line between the
   three blocks. Plain `assert`.** Duplicate setup across tests is fine;
   clever shared abstractions that hide what a test does are not.
5. **Assert on results and state, not on calls.** `assert_called_once_with`
   as a test's only assertion is banned. Sole exception: when the call IS
   the behavior (an email was sent, a job was enqueued) — and then assert
   against a hand-written fake's recorded state, not a MagicMock.
6. **The mocking ladder — always take the highest rung available:**
   real thing (`tmp_path`, in-memory DuckDB for DuckDB code, real temp
   objects) → hand-written fake of a boundary module you own → `mocker` /
   `monkeypatch` as last resort.
7. **Never mock or patch what you don't own.** No patching `httpx`,
   `requests`, `oracledb`, `pyodbc`, `pandas` internals. Wrap the external
   thing in a thin gateway module you own, and fake the gateway.
8. **Pass dependencies as parameters instead of patching import paths.**
   If you're reaching for `mocker.patch("pkg.module.thing")`, first try
   refactoring `thing` into an argument with the real object as default.
9. **Every piece of fake external data is tethered to reality by exactly one
   sync mechanism** from `references/mock-data-sync.md`: built from the real
   model class, validated against a schema in a test, or contract-tested
   against the real system. Untethered hand-written JSON/dict fixtures are
   banned.
10. **The full unit suite runs on every commit**, so it stays fast:
    milliseconds per test. Anything touching a network, database, container,
    or the real filesystem beyond `tmp_path` goes behind the `integration`
    marker, which the pre-commit hook excludes.

## Toolset

The prescribed set — do not add other test libraries without the user's OK:

```bash
uv add --dev pytest pytest-cov pytest-randomly pytest-mock
```

Add per need: `polyfactory` (test data from pydantic models),
`pandera[pandas]` (DataFrame schemas), `respx` (faking httpx) or `responses`
(faking requests), `pytest-asyncio` (async code). `hypothesis` only for pure
algorithmic transforms. Snapshot tools and HTTP cassettes are opt-in —
propose them only when `references/mock-data-sync.md` says they fit.

## Workflow

Three modes. Pick by what the user asked for.

### Mode A — tests for new/changed code (default)

1. Read the code under test. Write the behavior list first — bullet points
   of what the code promises, from its spec/docstring, not its body. Show
   the list in your response before writing tests.
2. If logic and I/O are tangled (SQL/HTTP calls mid-function), refactor
   first: extract pure functions, push I/O to a thin gateway at the edge.
   Most tests should need no test doubles at all.
3. For each behavior: apply hard rule 1, then write the test (AAA, behavior
   name). Use `@pytest.mark.parametrize` with readable `ids=` for
   input/output tables instead of near-duplicate tests.
4. Build test data per `references/mock-data-sync.md`. READ it before
   faking anything external. READ `references/dataframes-and-databases.md`
   if the code touches DataFrames, Oracle/MSSQL, or DuckDB.
5. Run `uv run pytest --cov`. Uncovered branches in the code under test are
   either a missing behavior on your list or dead code — resolve which.

### Mode B — backfill an untested repo

1. Config first: READ `references/config-templates.md`; install the
   pytest/coverage config, dependency group, `integration` marker, and
   pre-commit hook before writing any test.
2. Map the code: pure logic, I/O boundaries (HTTP, DB, files), entry
   points. Test in that order — pure logic is the cheapest and highest
   value; gateway extraction next; marker-gated integration tests last.
3. Apply Mode A per module.
4. Set the coverage ratchet: `fail_under` = current measured coverage,
   rounded down. It only ever goes up.
5. RUN `scripts/audit_tests.py tests/` at the end as a self-check.

### Mode C — review an existing suite

1. RUN `scripts/audit_tests.py tests/` (from this skill's folder). It
   mechanically finds: tests that cannot fail, mock-echo tautologies,
   patches of third-party internals, and orphaned fixture files.
2. Verdict each finding: **delete** (protects nothing), **rewrite** (real
   behavior, bad form), or **keep** (false positive — say why).
3. Check by hand what the script can't see: expected values that look
   copy-pasted from implementation output, fixture chains deeper than two
   levels, `autouse=True` fixtures that only some tests need, and asserts
   so weak they'd pass on wrong output (`assert result is not None`).
4. Report before changing anything: table of file → finding → verdict, then
   act on the user's confirmation.

## DataFrames and databases (this stack's specifics)

Full patterns in `references/dataframes-and-databases.md`. The rules:

- Schema every pipeline-stage boundary with a pandera `DataFrameModel`
  (`import pandera.pandas as pa` — the old top-level import is deprecated)
  and `@pa.check_types` on transforms.
- Compare frames only with `pd.testing.assert_frame_equal` — never `==` or
  `.equals()`. Small inline DataFrames in the test body beat fixture CSVs.
- Every public transform gets a no-mutation test (deep-copy input, run,
  assert input unchanged).
- Never use DuckDB or SQLite as a stand-in for Oracle/MSSQL — the vendor
  SQL text is the thing under test. Fake the gateway in unit tests; hit the
  real DB in marker-gated integration tests.
- Every faked stored-proc result set is backed by a shape contract test
  that runs the real proc (integration-marked) and checks the fake's
  columns/types against `cursor.description`.

## Example

`report.py` mixes a stored-proc call with logic — untestable without a DB:

```python
def monthly_totals(conn, month: str) -> dict[str, float]:
    cur = conn.cursor()
    cur.execute("EXEC dbo.GetOrders @month=?", month)
    rows = cur.fetchall()
    totals: dict[str, float] = {}
    for region, amount in rows:
        if amount > 0:                      # credits excluded
            totals[region] = totals.get(region, 0.0) + amount
    return totals
```

Step 1 — split: `gateway.py` gets `fetch_orders(conn, month) -> list[Order]`
(the SQL, row→`Order` mapping, nothing else); `report.py` keeps
`monthly_totals(orders: list[Order]) -> dict[str, float]` — now pure.

Step 2 — behavior list for `monthly_totals`: sums amounts per region;
excludes credits (amount ≤ 0); empty input → empty dict.

Step 3 — tests (no mocks anywhere):

```python
def test_totals_are_summed_per_region():
    orders = [Order(region="west", amount=10.0),
              Order(region="west", amount=5.0),
              Order(region="east", amount=2.0)]

    totals = monthly_totals(orders)

    assert totals == {"west": 15.0, "east": 2.0}

def test_credits_are_excluded_from_totals():
    orders = [Order(region="west", amount=10.0),
              Order(region="west", amount=-4.0)]

    totals = monthly_totals(orders)

    assert totals == {"west": 10.0}
```

Step 4 — the gateway gets one integration-marked shape contract test
(pattern in `references/dataframes-and-databases.md`), so the fake `Order`
rows used elsewhere can't drift from what `dbo.GetOrders` really returns.

## Bundled resources

- `scripts/audit_tests.py` — RUN on a tests/ dir in Mode C, and as the final
  self-check in Mode B. Flags are documented in `--help`.
- `references/mock-data-sync.md` — READ before faking any external data
  source (API responses, DB rows, files). The drift-prevention playbook.
- `references/dataframes-and-databases.md` — READ when the code under test
  touches pandas, Oracle/MSSQL, DuckDB, or stored procedures.
- `references/config-templates.md` — READ in Mode B step 1, or when adding
  the pre-commit gate to an already-tested repo.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
