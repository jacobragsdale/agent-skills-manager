# Testing pandas pipelines and raw-SQL database code

This stack: pandas DataFrames mutated through pipelines; Oracle + MSSQL via
stored procedures and raw SQL (no ORM); DuckDB for local analytics.

## Pandas

### Schema the boundaries with pandera

Untyped frames are why pipeline tests are hard to write and trust. Give
every pipeline-stage boundary a schema; the schema becomes the type:

```python
import pandera.pandas as pa          # NOT `import pandera as pa` — deprecated since 0.24
from pandera.typing import DataFrame

class RawOrders(pa.DataFrameModel):
    order_id: int = pa.Field(ge=0)
    region: str
    amount: float = pa.Field(nullable=False)

class RegionTotals(pa.DataFrameModel):
    region: str
    total: float

@pa.check_types
def summarize(df: DataFrame[RawOrders]) -> DataFrame[RegionTotals]:
    ...
```

Install as `pandera[pandas]`. `@pa.check_types` validates input and output
on every call — in tests AND production. Once boundaries are schema'd, most
"mock data drift" for frames disappears: a frame that doesn't match the
schema fails loudly at the boundary.

Property-based option for pure transforms: `pandera[strategies]` gives
`RawOrders.strategy(size=5)` / `.example()` for hypothesis-generated valid
frames. Use for invariants (row count preserved, no nulls introduced), not
value oracles.

### Comparing frames

Only `pd.testing.assert_frame_equal` — never `df1 == df2` (elementwise,
NaN-broken) or `.equals()` (no diff on failure). Decisions to make
explicitly per call:

- `check_dtype=True` is the default and usually what you want — dtype drift
  (int64 → float64 after a merge introduced NaNs) is a real bug class.
- Index is always compared. When index identity isn't part of the contract:
  `assert_frame_equal(result.reset_index(drop=True), expected.reset_index(drop=True))`.
- `check_like=True` ignores column/row order when order isn't the contract.
- Floats compare with rtol=1e-5 by default; tighten with `check_exact=True`
  for money-as-float pipelines, or better, use explicit rounding in code.

### Test data: inline frames, not CSVs

Default: 3–10 row `pd.DataFrame({...})` built in the test body. It documents
the expected shape and keeps the reader in the test file. Fixture CSVs hide
dtypes (everything round-trips through text) and rot invisibly — if a file
is genuinely needed, use Parquet (preserves dtypes) and a fixture-validation
test (mock-data-sync.md §2, with the pandera schema as validator).

### No-mutation tests

Pipelines that mutate frames in place cause spooky action at a distance.
Every public transform gets:

```python
def test_summarize_does_not_mutate_its_input():
    df = make_raw_orders()
    original = df.copy(deep=True)

    summarize(df)

    pd.testing.assert_frame_equal(df, original)
```

Version notes:
- pandas 2.x: put `pd.set_option("mode.copy_on_write", True)` in the root
  conftest.py so tests run under pandas-3.x semantics before the upgrade.
- pandas ≥3.0: Copy-on-Write is mandatory. `SettingWithCopyWarning` is gone
  and chained assignment (`df[mask]["col"] = x`) silently does nothing —
  the write is lost. The fix is always `df.loc[mask, "col"] = x`. A
  no-mutation failure that disappears on 3.0 usually means the code relied
  on view mutation and is now silently broken instead.

## Oracle / MSSQL, raw SQL, stored procedures

### The gateway pattern

All SQL and proc calls live in thin gateway modules. A gateway function
contains: the SQL string, parameter binding, row → typed-object mapping
(pydantic model or dataclass per result set). Nothing else — **no `if` in
the gateway**; anything with logic moves above it. Consequences:

- Business logic tests never see a cursor — they take lists of typed rows.
- Gateways get only marker-gated integration tests, no unit tests (there is
  no logic to unit-test; mocking a cursor to test SQL string formatting
  proves nothing).

### DuckDB is not a stand-in for Oracle/MSSQL

The vendor SQL text (T-SQL, PL/SQL, `EXEC`, `NVL`, `TOP n`, `#temp` tables,
empty-string-is-NULL) is exactly what's under test, and DuckDB speaks a
Postgres-flavored dialect with no stored procedures at all. A DuckDB-passing
test of vendor SQL is false confidence. DuckDB is only "the real thing"
(mocking-ladder rung 1) for code whose production target IS DuckDB — then
use a real in-memory `duckdb.connect()` in tests freely.

### Faking result sets: FakeCursor, not MagicMock chains

One small typed fake, seeded per test — it rejects typo'd methods and reads
like DB-API:

```python
class FakeCursor:
    def __init__(self, results: list[list[tuple]], description=None):
        self._results = iter(results)
        self.description = description
        self.executed: list[tuple[str, tuple]] = []
        self._current: list[tuple] = []

    def execute(self, sql: str, *params):
        self.executed.append((sql, params))
        self._current = next(self._results, [])

    def fetchall(self):
        return self._current

    def fetchone(self):
        return self._current.pop(0) if self._current else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
```

Prefer faking one level higher when possible: fake the gateway function
(return typed rows / a schema-validated DataFrame) rather than the cursor.
Fake the cursor only to test the gateway's own row-mapping.

### Shape contract tests: how fakes stay in sync with procs

For every stored proc a gateway calls, one integration-marked test runs the
real proc and asserts the SHAPE (not values — values change, shape is the
contract). The fake rows used in unit tests are built from the same typed
model, so schema drift fails this test even while all unit tests stay green:

```python
@pytest.mark.integration
def test_get_orders_proc_shape_matches_order_model(mssql_conn):
    cur = mssql_conn.cursor()

    cur.execute("EXEC dbo.GetOrders @month=?", "2026-06")

    assert [d[0].lower() for d in cur.description] == list(Order.model_fields)
```

If a proc's result set is too gnarly to model by hand, record it once from
the integration environment (serialize `cursor.description` + rows to a
checked-in file via a small script), replay through FakeCursor, and
regenerate with the script when the proc changes. No library does this for
DB-API — the script is ~20 lines and lives in the repo's `scripts/`.

### Running the integration tests

- Register the marker (config-templates.md); pre-commit excludes it; run
  explicitly with `uv run pytest -m integration`.
- Real DBs via testcontainers: `uv add --dev "testcontainers[mssql]"` →
  `SqlServerContainer` (image `mcr.microsoft.com/mssql/server:2022-latest`,
  needs `ACCEPT_EULA`, ~15–30s startup); `"testcontainers[oracle-free]"` →
  `OracleDbContainer` on `gvenzl/oracle-free:slim-faststart` (4–5 GB image).
  Caveats: both images are amd64-only — on Apple Silicon they need Rosetta
  emulation (slow) or a Linux CI/remote Docker host; prefer pointing tests
  at an existing dev-server DB via `.env` when containers are impractical.
- One session-scoped container/connection fixture + per-test transaction
  rollback. Never a container per test.
- Build the test schema by running the SAME SQL migration files that deploy
  to production, in order, at session start. A hand-maintained
  `test_schema.sql` is banned — it is fixture drift with extra steps.
- In-database proc logic that deserves its own tests: plain pytest
  integration tests calling the proc and asserting on results are fine;
  tSQLt (MSSQL) / utPLSQL (Oracle) only if the team already uses them.
