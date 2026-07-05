# Audit principles

The numbered checklist every etl-audit finding must cite. Each entry:
the principle, why it matters, the Python smell that violates it, the fix
direction, and the source. Groups: A failure visibility (1–5),
B determinism & idempotency (6–11), C boundaries & structure (12–18),
D verification (19–21).

The unifying failure taxonomy — every silent-failure incident is one of:
(1) job crashed, nobody noticed → 5; (2) job "succeeded" but did nothing
or less → 19; (3) job succeeded on wrong data → 13, 19; (4) job
half-finished → 10, 11; (5) errors eaten in-process → 1–4.

## A. Failure visibility

### 1. Never swallow an exception you cannot correct

Catch only specific, expected exception types, only where you can act on
them; everything else propagates. The documented incident shape: a broad
`except Exception` inside a record loop logs at debug and skips — the run
finishes green with 15% fewer records.
**Smell:** `except: pass`, `except Exception: logger.error(e)` with no
`raise`, one `try` blanketing all of `main()`. Bare `except:` is worse —
it eats `SystemExit` and `KeyboardInterrupt` too (PEP 760 proposed
banning it).
**Fix:** name the exception types; re-raise everything else; if bad
records are quarantined, count them and fail past a threshold.
**Source:** Chu Ngwoke, [Silent Failures in Data Pipelines](https://medium.com/@chu.ngwoke/silent-failures-in-data-pipelines-why-theyre-so-dangerous-7c3c2aff8238);
charlax, [Error handling antipatterns](https://github.com/charlax/professional-programming/blob/master/antipatterns/error-handling-antipatterns.md);
[PEP 760](https://peps.python.org/pep-0760/).

### 2. The exit code is the contract with the scheduler

cron, systemd, Airflow, CI — all decide success from the return code
alone. Python's default is already correct: an uncaught exception prints
a traceback and exits 1. Most silent failures are code actively
defeating that default. A custom `sys.excepthook` may add structured
logging or an alert ping but must never suppress the nonzero exit.
**Smell:** `main()` that logs an error and falls off the end (returns
0); `sys.exit()` after an error; `sys.exit(0)` in an except block; error
counters never checked before exit.
**Fix:** let exceptions terminate; aggregating jobs end with
`sys.exit(1 if errors else 0)`; wrappers use
`subprocess.run(..., check=True)`.
**Source:** Henry Leach, [Controlling Python Exit Codes](https://henryleach.com/2025/02/controlling-python-exit-codes-and-shell-scripts/).

### 3. Fail fast at startup, not mid-run

Validate config and required inputs eagerly, before any work; a visible
immediate failure is cheap, a deferred one corrupts state and surfaces
far from the cause.
**Smell:** `config.get("url", "http://localhost")` in prod code, `or 0`
fallbacks on parse failures, functions returning `None` on error with
unchecked callers.
**Fix:** raise on missing/invalid config at the entrypoint; no fallback
values for required inputs.
**Source:** Jim Shore, [Fail Fast](https://martinfowler.com/ieeeSoftware/failFast.pdf) (IEEE Software, 2004).

### 4. For unattended batch work, crashing is a feature

Crash-only design: one way to stop (crash), one way to start (recovery),
so the recovery path is the tested path. Handle only the errors you can
correct in context — taxonomy: *transient* (bounded retry with backoff),
*expected-domain* (quarantine, count, threshold), *unexpected*
(propagate, crash, let the scheduler retry). Precondition: idempotent
re-runs (principle 10).
**Smell:** `while True: try: ... except Exception: continue` worker
loops; elaborate in-process recovery state machines; retrying
`ValueError` the same way as `ConnectionError`.
**Source:** Candea & Fox, [Crash-Only Software](https://dslab.epfl.ch/pubs/crashonly.pdf);
Trevor Brown, [Let It Crash outside Erlang](http://stratus3d.com/blog/2020/01/20/applying-the-let-it-crash-philosophy-outside-erlang/).

### 5. Dead-man's switch on every scheduled job

Alert on the *absence of success*, not just the presence of errors —
in-process alerting dies with the process and cannot catch the job that
never ran (dead host, expired creds, deleted crontab).
**Smell:** alert paths only inside the Python code; no external record
of last success time.
**Fix:** `python job.py && curl -fsS https://hc-ping.com/<uuid>` — the
`&&` gates the heartbeat on exit 0, so principles 1–2 are what make it
truthful.
**Source:** [Healthchecks.io — Monitoring Cron Jobs](https://healthchecks.io/docs/monitoring_cron_jobs/).

## B. Determinism & idempotency

### 6. Transforms are pure: deterministic and idempotent

Same inputs → same outputs, every run and re-run, with no side effects.
Pure tasks "can be written, tested, reasoned-about and debugged in
isolation." This is the precondition for safe backfills and for retries
being a feature instead of a risk.
**Smell:** a "transform" that also INSERTs, sends Slack messages,
mutates a shared cache, or writes checkpoint files as a byproduct.
**Source:** Maxime Beauchemin, [Functional Data Engineering](https://maximebeauchemin.medium.com/functional-data-engineering-a-modern-paradigm-for-batch-data-processing-2327ec32c42a).

### 7. No hidden inputs: clock, random, environment

`datetime.now()` "should never be used inside a task" — a backfill for
2024-03-01 must behave identically whether run that day or today. The
logical date, seeds, and config are parameters, passed in by the shell.
**Smell:** `datetime.now()` / `date.today()` / `time.time()` inside
transforms; unseeded `random` / `uuid4()`; `os.getenv` shaping logic
deep in the call tree.
**Source:** [Airflow Best Practices](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html).

### 8. Read explicit partitions, never "latest available"

Re-runs must see the same input the original run saw; "process
whatever's new" makes output depend on when the job happened to run.
**Smell:** `glob("*")` then `max(..., key=mtime)`; `SELECT max(updated_at)`
watermark tables; no interval parameter anywhere.
**Source:** [Airflow Best Practices](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html);
Beauchemin (above).

### 9. Unit of work = one partition; one task → one output

Each run instance maps to one (output, partition) cell, so any partition
can be recomputed independently and lineage is auditable. Avoid
partitions that depend on prior partitions of the same table (running
totals via "read yesterday's output") — backfills go serial and one bad
partition poisons the rest.
**Smell:** one job writing three tables plus a CSV; whole-table rescans
each run; cumulative delta-on-previous-output logic.
**Source:** Beauchemin (above).

### 10. Writes are re-run-safe: overwrite the partition, never blind-append

"A pure task should always fully overwrite a partition as its output."
Retry-after-failure is the *normal* case in batch systems; append-only
writes turn every retry into duplicate rows.
**Smell:** `df.to_sql(..., if_exists="append")` keyed on nothing;
`INSERT INTO` without a scoped preceding delete; appending to files.
**Fix:** output location/scope is a pure function of the run parameters;
insert-overwrite, partition replace, or delete-then-insert in one
transaction.
**Source:** Beauchemin (above); Start Data Engineering,
[Idempotent data pipelines](https://www.startdataengineering.com/post/why-how-idempotent-data-pipeline/).

### 11. Publish atomically: temp → validate → rename/swap

A consumer that reads a half-written output sees "data present" and
proceeds — partial success looks identical to success. Atomic publish
also creates the natural seam where quality gates (19) run before
anything is visible.
**Smell:** writing incrementally to the final path; quality checks after
the data is already published; loading straight into the prod table then
"fixing up."
**Fix:** write to `*.tmp`, flush/fsync, validate, `os.replace()` (atomic
on the same filesystem); in warehouses: staging table → checks → swap.
**Source:** Start Data Engineering (above);
[apxml — Idempotency in Pipelines](https://apxml.com/courses/intro-data-lake-architectures/chapter-3-ingestion-pipelines/idempotency-in-pipelines).

## C. Boundaries & structure

### 12. Functional core, imperative shell

Every decision in a pure function; every dependency in the shell. The
core has many paths and no dependencies → exhaustive unit tests without
mocks; the shell has many dependencies and almost no paths → a handful
of integration tests. A shell with conditionals has leaked decisions
into the untestable zone. Pass plain values (frozen dataclasses, dicts)
across the boundary, never live sessions/handles/ORM objects.
**Smell:** `if row["status"] == "active":` in the same loop as
`cursor.execute(...)`; a transform receiving a SQLAlchemy session.
**Fix:** `rows = fetch(); results = transform(rows); write(results)` —
the shell is three lines with no branching.
**Source:** Gary Bernhardt, [Boundaries](https://www.destroyallsoftware.com/talks/boundaries) /
[Functional Core, Imperative Shell](https://www.destroyallsoftware.com/screencasts/catalog/functional-core-imperative-shell).

### 13. Parse, don't validate — once, at the boundary

Validation returns nothing and the proof is discarded; parsing returns a
richer type that *carries* the proof, so it happens exactly once. The
anti-pattern is shotgun parsing: checks scattered through processing, so
invalid data is discovered after side effects began — the classic
half-loaded batch. Parse/reject the entire batch (dead-letter the bad
rows) before any load begins.
**Smell:** `dict`/`Any` flowing through the core;
`if "email" in record and record["email"]:` guards mid-transform;
`KeyError` on row 5000 after 4999 rows are already written.
**Fix:** at ingestion, raw rows → pydantic model or typed frozen
dataclass (raise on failure); core signatures accept only parsed types.
**Source:** Alexis King, [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/).

### 14. Make illegal states unrepresentable

If invalid data cannot be constructed, whole classes of defensive code
and tests disappear.
**Smell:** `amount: float | None` plus `assert ... is not None` sprinkled
through transforms; `status: str` compared to magic strings; parallel
lists that must stay in sync.
**Fix:** `Enum` for closed sets, `Decimal` for money, non-optional fields
on the parsed type, `@classmethod from_raw` smart constructors.
**Source:** Alexis King (above).

### 15. Ports and adapters: the core runs without real infrastructure

The application must be runnable and testable without its database,
APIs, or filesystem. High-level modules (domain) never import low-level
ones (infrastructure); adapters implement small `Protocol`/ABC ports.
Test with hand-written fakes, not `mock.patch` — patch-stacks are "a
code smell," coupling tests to call signatures instead of behavior. If
a dependency is hard to fake, the abstraction is wrong.
**Smell:** `import boto3` in a module that also holds business rules;
logic that can't execute without VPN + credentials; tests with three
stacked `@mock.patch` decorators asserting `assert_called_once_with`.
**Source:** Alistair Cockburn, [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/);
Percival & Gregory, [Architecture Patterns with Python ch. 2–3](https://www.cosmicpython.com/book/chapter_03_abstractions.html).

### 16. Decide *what* to do and *do* it in separate steps

The core returns a plan — action values like `("COPY", src, dst)` or
order intents — and the shell executes it. Highest-leverage single move
for batch jobs: the diff/decision logic becomes exhaustively unit
testable, and `--dry-run` plus an audit log of intended actions come
free.
**Smell:** `os.rename()` / `DELETE FROM` / order submission interleaved
with the comparison logic that decides them; no way to preview a run.
**Source:** Percival & Gregory, [ch. 3](https://www.cosmicpython.com/book/chapter_03_abstractions.html).

### 17. Mutable state is the complexity multiplier

Every bit of state doubles the space you must reason about, and state
contaminates: one stateful helper makes every transitive caller
stateful. Separate accidental state (caches, counters, checkpoints —
derivable, belongs in the shell) from essential input data.
**Smell:** module-level accumulators (`_seen = set()`), `global
row_count`, results that depend on how many times a function ran, a
"pure-looking" helper that hits Redis through a memoizer.
**Source:** Moseley & Marks, [Out of the Tar Pit](https://curtclifton.net/papers/MoseleyMarks06a.pdf).

### 18. Deep modules; define errors out of existence

Complexity felt by callers is what matters — one entry point with
sensible defaults, retries/pagination/lifecycle handled inside the
adapter. And design APIs so the error case cannot occur: empty batch →
empty list processed as a no-op, not a special case; `ensure_absent`
instead of delete-that-throws; anomalies normalized at the parse
boundary so the core never sees them.
**Smell:** an `extract()` needing six args and a documented call order;
`try/except KeyError` blankets; ten call sites re-implementing
"delete if exists."
**Source:** John Ousterhout, *A Philosophy of Software Design*
([interview](https://newsletter.pragmaticengineer.com/p/the-philosophy-of-software-design)).

## D. Verification

### 19. Quality gates that fail the run, between staging and publish

"A pipeline can succeed while writing zero rows." Green-run-empty-output
is a failure mode: assert row counts (floor or trailing-average band),
input↔output reconciliation, uniqueness/nullability on keys — and a
failed hard check raises → nonzero exit → publish never happens. Schema
drift is the top silent corrupter: declare frame schemas (pandera
`DataFrameModel` + `@pa.check_types`) at stage boundaries so drift fails
loudly at the boundary, not three transforms later. Warn-vs-error is an
explicit per-check decision; default is error.
**Smell:** checks that only `logger.warning`; `errors="coerce"` with no
NaN follow-up; zero-row runs reporting success without an explicit
`--allow-empty`.
**Source:** Robert Sahlin, [Your Pipeline Succeeded. Your Data Didn't.](https://robertsahlin.substack.com/p/your-pipeline-succeeded-your-data);
[dbt severity model](https://www.getorchestra.io/guides/dbt-test-config-warn-if-setting-row-thresholds);
[Pandera decorators](https://pandera.readthedocs.io/en/stable/decorators.html).

### 20. Business rules are named, pure, individually testable predicates

For order-emitting/trading code this is regulated practice (SEC Rule
15c3-5): price collars, max quantity/notional, order rate, duplicate
checks — each a discrete predicate with configured limits and a reject
action. A rule violation is an *expected value* (Result type or a frozen
`Violation` dataclass), recorded with the rule's name and the offending
values — never an exception caught by the same handler as I/O errors,
never a bare `is_valid() -> bool` that hides which rule fired. Reserve
exceptions for the unexpected (principle 4's taxonomy).
**Smell:** validation interleaved with submission; limits hardcoded
inline; `raise OrderRejected` caught three frames up next to
`ConnectionError`; `None`/`False`/`-1` signaling distinct failures.
**Fix:** `check(order, limits) -> Violation | None` per rule;
table-driven limits; run all rules, log every violation; unit-test each
rule in isolation.
**Source:** [CFTC Electronic Trading Risk Principles](https://www.federalregister.gov/documents/2020/07/15/2020-14381/electronic-trading-risk-principles);
[dry-python returns — railway](https://returns.readthedocs.io/en/latest/pages/railway.html);
Wlaschin, [Against Railway-Oriented Programming](https://fsharpforfunandprofit.com/posts/against-railway-oriented-programming/) (on the boundary).

### 21. Match test type to layer

Pure core: exhaustive unit tests plus property-based tests (Hypothesis)
for invariants — row-count relations, totals preserved, idempotence
`f(f(x)) == f(x)`, parse/serialize round-trips. Adapters: a few real
integration tests against containerized infrastructure, narrow contract
only. Shell: one or two edge-to-edge tests with fakes. The inversion —
hundreds of mocked "unit" tests for adapter code, happy-path examples
only for transform logic — is the smell.
**Source:** [Hypothesis docs](https://hypothesis.readthedocs.io/en/latest/);
Bernhardt, Percival & Gregory (above).
