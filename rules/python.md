# Python rules

Always-on rules for Python work in these repos — mostly batch jobs, ETL
pipelines, and trading systems that must never fail silently. Style and
mechanical correctness are the linters' job: repos use ruff + basedpyright
via pre-commit. Fix their findings; use per-file ignores for true
exceptions; never weaken global lint/type config to silence one file.

## Structure: functional core, imperative shell

- Business logic lives in pure functions that take values and return
  values. I/O — DB, files, HTTP, `os.environ`, the clock — happens only in
  the entrypoint and dedicated gateway modules.
- Keep the shell thin and branch-free: fetch → transform → write. An `if`
  next to a `cursor.execute()` means the decision belongs in the core.
- Parse, don't validate: convert raw input (rows, JSON, env) into typed
  frozen dataclasses or pydantic models once, at the boundary. Core
  functions accept parsed types, not raw dicts or `Any`.
- Make invalid states unconstructable: `Enum` for closed sets, `Decimal`
  for money, non-optional fields — reject at parse time instead of
  re-checking downstream.
- No hidden inputs: the run date, seeds, and config are parameters passed
  down from `main()`. `datetime.now()` and `os.getenv()` inside a
  transform make it untestable and non-reproducible.
- When logic decides on side effects (writes, deletes, orders), return the
  intended actions as data and execute them in a separate step — this
  makes the decision unit-testable and gives dry-run for free.
- Hold state in explicit values passed between functions, not in `global`,
  module-level caches, or accumulating class attributes.

## Batch jobs and pipelines

- Jobs are idempotent: parameterize by an explicit date/partition, read
  that partition (not "latest available"), and fully overwrite the output
  for it. A re-run must produce the same end state — overwrite or
  scoped delete-then-insert, not blind append.
- Publish atomically: write to a temp path or staging table, validate,
  then `os.replace()` / swap. A half-written output must never be visible.
- Gate outputs before publishing: assert row counts and invariants; a
  zero-row result is a failure unless the caller passed an explicit
  allow-empty flag.

## Failures bubble up

- Catch only exceptions you can correct at that point (retry a transient
  connection, quarantine-and-count a bad record). Everything else
  propagates — Python's default traceback-and-exit-1 is correct behavior,
  not a crash to prevent.
- The exit code is the contract with the scheduler: nonzero on any
  failure. A job that logs an error and exits 0 has lied.
- Fail fast at startup: missing or invalid required config raises
  immediately; provide defaults only for genuinely optional settings.
- Expected domain outcomes (an order rejected by a risk rule) are values —
  one named predicate per rule, violations returned and logged with the
  rule's name. Exceptions are reserved for the unexpected.

The entrypoint shape that follows from all of the above:

```python
def main() -> int:
    config = Config.from_env()                 # parse once; raises if incomplete
    orders = fetch_orders(config, config.run_date)   # gateway: I/O only
    actions = decide(orders, config.limits)          # pure core; unit-tested
    apply_actions(actions, config)                   # gateway: I/O only
    return 0

if __name__ == "__main__":
    sys.exit(main())    # anything raised → traceback, exit 1, scheduler sees it
```

## Toolchain

- uv only: `uv add`, `uv run`, `uv sync`. Never `pip install`; never write
  a setup shell script — every dependency and build fix lands in
  `pyproject.toml`.
- Python 3.11. One `pyproject.toml` per repo holds dependencies and all
  tool config (ruff, basedpyright, pytest).
- Standalone scripts are single files with a PEP 723 `# /// script` header,
  runnable anywhere with `uv run script.py` and no environment setup.

## Testing

- Tests assert behavior on results, not on mock calls; name them as
  behavior sentences (`test_expired_token_is_rejected`). Prefer real
  objects and hand-written fakes of boundaries you own over
  `mock.patch` — if code needs patching to test, restructure it per the
  rules above instead. Full standard: the `python-testing` skill.
