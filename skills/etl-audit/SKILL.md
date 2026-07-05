---
name: etl-audit
description: "Audit a Python ETL job, scheduled task, or trading/batch program and produce a detailed refactoring plan \u2014 no code changes. Use when asked to audit a pipeline for maintainability, testability, silent failures, or hidden state; to plan a refactor toward pure functions with typed I/O boundaries; or to review why a scheduled job fails quietly or exits 0 on errors."
disable-model-invocation: true
---

# ETL audit

Audit a Python batch program — a cron ETL job, an interdependent pipeline
task, a trading algorithm that emits orders — and deliver a refactoring
plan toward one target architecture: **functional core, imperative shell**.
Inputs enter through explicitly declared, typed boundaries; outputs leave
the same way; everything between is pure functions; failures raise, bubble
to the entrypoint, and become nonzero exit codes the scheduler can see.

## Hard rules

1. **Plan only. Do not edit, create, or delete any file in the audited
   repo.** The deliverable is a single plan document. If the user asks to
   implement it, that is a separate task after they approve the plan.
2. **Every finding cites `file:line` and names the principle it violates**
   (by number from `references/principles.md`). No free-floating advice.
3. **Scanner findings are leads, not verdicts.** Verdict each one:
   *real* (goes in the plan), *false positive* (say why), or *accepted*
   (real but not worth fixing — say why). Never paste raw scanner output
   into the plan.
4. **Rank by blast radius, not by count.** One swallowed exception in a
   money-touching job outranks twenty style smells. Phase 1 of every plan
   is failure visibility; purity refactors come after.
5. **Silence is the enemy.** For every input, output, and business rule,
   the plan must answer: *how would we know if this were wrong?* A rule
   with no test and no runtime assertion gets flagged even if the code
   looks correct.

## Workflow

### 1 — Map the job

Read the entrypoint(s) and trace outward. Build the boundary inventory
before judging anything:

- **Inputs**: every file glob, DB query, API call, env var, CLI arg — and
  the *hidden* ones: wall clock, `random`, "latest file in folder",
  watermark tables, module-level state.
- **Outputs**: every table write, file write, API POST, order/message
  emitted. Note write mode (append vs overwrite) and whether a partial
  write can survive a crash.
- **Exit paths**: what reaches the scheduler on success, on crash, on
  "ran but produced garbage"? Find every `except`, `sys.exit`, and bare
  `return` on the failure path.
- **Business rules**: for order-emitting/trading code, list every rule the
  output must satisfy and where (if anywhere) each is checked.

### 2 — Scan

RUN `scripts/scan_smells.py <src-dirs>` (from this skill's folder; needs
only `uv`). It mechanically flags swallowed exceptions, exit-code masking,
nondeterministic calls, env reads in logic, I/O tangled with branching,
module-level side effects, globals, and mutable defaults. `--help` covers
flags; `--json` for machine-readable output. Then apply hard rule 3.

### 3 — Judge against the principles

READ `references/principles.md` — the distilled, sourced audit checklist.
The scanner cannot see the highest-value problems; check these by hand:

- Append-mode writes and non-atomic publishes where idempotent
  overwrite-partition and temp-then-swap belong (principles 10–11).
- "Process whatever's new" instead of an explicit unit of work passed
  as a parameter (principles 8–9).
- Validation missing at ingestion — raw dicts/DataFrames flowing untyped
  through the core instead of being parsed once at the boundary (13–14).
- Business rules as scattered `if`s instead of named, individually
  testable predicates with a visible verdict (20).
- Outputs never sanity-checked — no row-count/invariant gate before
  publishing (19), no heartbeat after success (5).

### 4 — Write the plan

Produce one document (`AUDIT.md` in the audited repo's root is the
default target — but only write it where the user says; hard rule 1
covers everything else). REQUIRED sections, in order:

```markdown
# Refactoring plan: <job name>

## Job snapshot
What it does, schedule/trigger, blast radius if it silently fails.

## Boundary inventory
Inputs table: name | location | format | contract | validated where?
Outputs table: name | destination | write mode | idempotent? | checked?
Hidden inputs: clock/env/random/"latest" reads, each with file:line.

## Findings
One row per confirmed finding:
file:line | smell | principle # | severity (silent-failure / correctness
/ testability) | one-line fix direction.
Scanner false positives and accepted findings listed separately, each
with its reason.

## Target architecture
Concrete module layout for THIS repo (gateway modules, core modules,
entrypoint), what each existing function becomes, what dies.

## Refactor phases
Ordered, independently shippable. Each phase: goal, exact moves
(function → destination), tests unlocked, risk, and a "done when"
check. Phase 1 is always failure visibility (exits, exception policy,
heartbeat) — it needs no restructuring and pays immediately.

## Test plan
Which behaviors get pure unit tests, which boundaries get contract/
integration tests, which invariants become runtime gates.

## Failure-handling contract
The job's promised behavior: which errors raise, what the entrypoint
catches (nothing, except to log-and-re-raise), exit-code meanings,
what the scheduler/monitor sees in each failure mode.

## Out of scope
What was deliberately not addressed, so the plan's edges are explicit.
```

## Example

A nightly `sync_positions.py` reads "the newest CSV" from a drop folder,
enriches rows with `datetime.now()`, appends to `positions`, and wraps
`main()` in `except Exception: log.error(e)` — cron shows green for
three weeks while a schema change upstream produces zero rows a night.

The audit yields: boundary inventory exposing the two hidden inputs
(clock, "newest file"); findings citing `sync.py:12` (swallowed
exception, principle 1), `sync.py:48` (append write, principle 10),
`sync.py:31` (clock in transform, principle 7); a target layout of
`gateways/drop_folder.py`, `gateways/positions_db.py`, `core/enrich.py`
(pure, takes `as_of: datetime`), `main.py` (parses config, wires, lets
exceptions fly). Phase 1: delete the try/except, add `sys.excepthook`
logging, exit nonzero, add a zero-row gate. Phase 2: parse rows into a
typed model at ingestion. Phase 3: pure core + tests. Phase 4: overwrite
per-date partition instead of append. No code was changed — the user got
a plan to approve.

## Bundled resources

- `scripts/scan_smells.py` — RUN in step 2 on the audited source dirs.
  Never paste its raw output into the plan (hard rule 3).
- `references/principles.md` — READ in step 3. The numbered principles
  findings must cite (hard rule 2), each with source and Python smell.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
