---
name: etl-refactor
description: "Execute an approved etl-audit refactoring plan on a Python ETL/batch job: phase-by-phase, behavior-preserving, characterization tests before every move. Use when asked to implement an AUDIT.md, execute or continue a refactoring plan, refactor a pipeline toward functional core / imperative shell, or make an audited job testable."
disable-model-invocation: true
---

# ETL refactor

Execute a refactoring plan produced by the `etl-audit` skill (usually
`AUDIT.md` in the repo root): move a Python batch job to functional core,
imperative shell — one plan phase at a time, each phase shippable on its
own, with tests pinning behavior before any code moves. This skill is the
"implement" half; `etl-audit` is the "plan" half. Plan documents cite
principles by number — those live in `../etl-audit/references/principles.md`
(installed alongside this skill); read the cited entries when a finding
needs interpretation.

## Hard rules

1. **No plan, no refactor.** If there is no audit plan the user has seen,
   stop and offer to run `etl-audit` first. Do not improvise a refactor
   from a verbal description — the plan is the approval artifact.
2. **Characterization tests before code moves.** Before restructuring
   anything a phase touches, pin its current observable behavior with
   tests that pass against the code as-is (golden outputs from real-ish
   input fixtures). If current behavior looks wrong, pin it anyway and
   flag it — see rule 4.
3. **One phase per commit (or PR), phases in plan order.** A phase is done
   only when its "done when" check from the plan passes, the full test
   suite is green, and `etl-audit`'s scanner no longer reports the
   findings that phase claimed. Never start phase N+1 in the same commit.
4. **Refactor and behavior change never share a commit.** Restructuring
   commits must be behavior-preserving — characterization tests unchanged
   and green. When the refactor exposes a real bug (it will — that's what
   the audit was for), record it in a `BUGS-FOUND.md` note with file:line
   and evidence, tell the user, and keep refactoring around it. Fixing it
   is its own commit, after the user confirms the current behavior is
   actually wrong.
5. **Phase 1 (failure visibility) is the sanctioned behavior change.**
   Deleting exception swallowing makes previously hidden errors crash the
   job — that is the point, but it is externally visible. Say so
   explicitly when reporting the phase, and expect the first scheduled
   runs after it to surface long-standing failures.

## Workflow

### 1 — Reconcile the plan with reality

Read the plan, then re-verify every file:line it cites for the phase you
are about to execute — code drifts between audit and implementation. Note
which findings are stale (already fixed, moved, or gone) and confirm the
phase still makes sense. If more than roughly a third of the phase's
findings are stale, tell the user the plan needs a re-audit instead of
silently improvising.

Also establish where execution stands: if some phases are already done
(check plan checkmarks, git history, whether the target modules exist),
resume at the first incomplete phase rather than starting over.

### 2 — Build the safety net

- Get the test infrastructure to the `python-testing` standard if the repo
  has it as a skill; otherwise minimal pytest + fixtures.
- Write characterization tests for everything this phase moves: feed the
  current entrypoint (or the functions being extracted) fixed inputs,
  assert on exact current outputs. Freeze hidden inputs the audit found
  (clock, env, "latest file") by fixing them in the test harness.
- Run the suite; it must be green before the first move.

### 3 — Execute the phase, smallest reversible moves

Extract-and-delegate, never rewrite-in-place: create the target module
(gateway or core function per the plan's target architecture), move the
code, make the old call site delegate to it, run tests, then collapse the
old site. Typical move order inside a phase:

1. Extract the pure part first (the decision), passing today's hidden
   inputs in as parameters with the current call site supplying them
   (`as_of=datetime.now()` moves to the shell, not deeper).
2. Type the seam: frozen dataclass or pydantic model parsed at the
   boundary, core signature takes only the parsed type.
3. Unit-test the extracted core directly — these are the tests the plan's
   "tests unlocked" column promised.
4. Only then delete the old path.

### 4 — Verify and report the phase

- Full suite green, including untouched characterization tests (rule 4).
- RUN `../etl-audit/scripts/scan_smells.py <src-dirs>`: findings this
  phase claimed must be gone; no new findings introduced.
- If the job has a cheap end-to-end invocation (dry-run flag, dev config),
  run it once and compare output to the pre-phase baseline.
- Report: what moved where, contract/behavior deltas (only phase 1 should
  have any), bugs recorded under rule 4, and what the next phase is. Then
  stop — the default is one phase per session; continue only if the user
  asked for the whole plan.

## Example

Plan for `sync_positions.py`, phase 2: "parse rows into a typed model at
ingestion." Reconcile: `sync.py:31` clock read already fixed in phase 1 —
noted stale, rest holds. Safety net: characterization test feeding the
current `load_rows()` a fixture CSV and asserting the exact dict rows it
returns today. Execute: add `core/models.py` with a frozen `Position`
model (`qty: int`, `symbol: str`, `price: Decimal` — no Optionals),
`from_raw()` raising on bad rows; `gateways/drop_folder.py` returns
`list[Position]`; the enrich loop's four `if "px" in row` guards die.
Tests: `from_raw` unit tests for good/bad/boundary rows. Verify: suite
green, scanner clean on the two claimed findings. Report notes one rule-4
bug: rows with negative qty were silently zeroed by an old guard —
recorded, not fixed. Commit: `refactor(sync): phase 2 — typed ingestion
boundary`.

## Bundled resources

None bundled. This skill runs against its siblings:

- `../etl-audit/references/principles.md` — READ the entries a finding
  cites when the fix direction is unclear.
- `../etl-audit/scripts/scan_smells.py` — RUN in step 4 to verify a
  phase's findings are gone.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
