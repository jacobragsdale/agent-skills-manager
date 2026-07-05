---
name: fastapi-refactor
description: "Execute an approved fastapi-audit refactoring plan on a FastAPI service: phase-by-phase, contract-preserving, with characterization tests and an OpenAPI snapshot before every move. Use when asked to implement an API audit plan, execute or continue an AUDIT.md on a FastAPI repo, or refactor routes/services per the audit."
disable-model-invocation: true
---

# FastAPI refactor

Execute a refactoring plan produced by the `fastapi-audit` skill (usually
`AUDIT.md` in the repo root): move a FastAPI service to typed contracts
at the edge, functional core, one error path — one plan phase at a time,
each phase shippable on its own. The defining constraint over an ETL
refactor: **this service has clients.** Every externally visible change —
a status code, a response shape, a header — is a contract change, and
contract changes are enumerated and approved, never incidental. Plan
documents cite principles by number — those live in
`../fastapi-audit/references/principles.md` (installed alongside this
skill); read the cited entries when a finding needs interpretation.

## Hard rules

1. **No plan, no refactor.** If there is no audit plan the user has seen,
   stop and offer to run `fastapi-audit` first. Do not improvise a
   refactor from a verbal description — the plan is the approval artifact.
2. **Pin the contract before touching anything.** Before the first move
   of the first phase: snapshot `app.openapi()` to a committed file, and
   write characterization tests through `TestClient`/`httpx.AsyncClient`
   asserting the *current* status codes and body shapes of every route
   the phase touches — including its current error responses, however
   ugly. Green against the code as-is before any move.
3. **One phase per commit (or PR), phases in plan order.** A phase is
   done only when its "done when" check passes, the full suite is green,
   and `fastapi-audit`'s scanner no longer reports the findings that
   phase claimed. Never start phase N+1 in the same commit.
4. **Every contract change is enumerated, matched to the plan, and
   surfaced.** After each phase, diff the OpenAPI snapshot. Every delta
   must appear on the plan's approved contract-changes list for that
   phase; an unlisted delta is a defect in the phase — revert or get it
   approved before merging. The phase report lists each change as
   `route: old → new`.
5. **Refactor and bug fix never share a commit.** Restructuring commits
   keep characterization tests green. When a phase exposes a real bug
   (a route that always 500s, a rejection returning 200), record it in
   `BUGS-FOUND.md` with file:line and evidence, tell the user, and keep
   going. Fixing it is its own commit, after the user confirms.
6. **Fakes over patches.** Test doubles enter through
   `app.dependency_overrides` on a factory-built app — hand-written
   fakes implementing the port. `mock.patch` on import paths is a smell
   that the seam from the plan's target architecture is missing; build
   the seam first.

## Workflow

### 1 — Reconcile the plan with reality

Read the plan, then re-verify every file:line it cites for the phase you
are about to execute — code drifts between audit and implementation.
Note stale findings; if more than roughly a third of the phase's
findings are stale, tell the user the plan needs a re-audit instead of
silently improvising. Establish where execution stands (plan checkmarks,
git history, whether target modules exist) and resume at the first
incomplete phase.

### 2 — Build the safety net

- If the app has no factory, carve out a minimal `create_app()` first —
  it is the enabler for everything else (isolated test apps, overrides).
  This is a sanctioned early move even if the plan schedules the full
  factory later.
- Snapshot `app.openapi()` (sorted keys, stable dump) into the repo and
  add the test that compares against it.
- Write the rule-2 characterization tests for the routes this phase
  touches: one test per route per status code it *actually* produces
  today. Freeze hidden inputs (clock, uuid) via `dependency_overrides`
  or fixtures.
- Full suite green before the first move.

### 3 — Execute the phase, smallest reversible moves

Extract-and-delegate, never rewrite-in-place. Typical move order:

1. Build the new piece next to the old (domain exception + handler,
   response model, service function, injected dependency).
2. Point one route at it; run the suite; the OpenAPI diff shows exactly
   this route's approved delta and nothing else.
3. Sweep the remaining routes one by one, then delete the old path
   (dead per-route try/excepts, ad-hoc error dicts, module globals).
4. Update the characterization tests to the new contract *in the same
   commit* as the approved change they witness — never loosen a test to
   "temporarily" pass.

Phase-specific notes:
- **Error-contract phase**: add the domain exception and its handler
  before deleting a route's try/except, so no request ever sees a raw
  500 mid-refactor. The per-route sweep is: raise domain exception in
  service → delete route's catch → contract test asserts new
  status/shape.
- **Response-model phase**: introduce the model with `response_model=`
  first and confirm the snapshot diff only *documents* (no shape
  change), then tighten fields — each tightening is a listed contract
  change.
- **Dependency phase**: introduce the `Depends` seam returning the
  existing global, migrate call sites, then move construction into the
  factory/lifespan and delete the global.

### 4 — Verify and report the phase

- Full suite green; characterization tests changed only where rule 4's
  approved list says so.
- RUN `../fastapi-audit/scripts/scan_api_smells.py <src-dirs>`: findings
  this phase claimed must be gone; no new findings introduced.
- Diff the OpenAPI snapshot; reconcile against the approved list
  (rule 4).
- Report: what moved where, the contract-change list as `route: old →
  new`, bugs recorded under rule 5, and what the next phase is. Then
  stop — the default is one phase per session; continue only if the
  user asked for the whole plan.

## Example

Plan for the `orders` service, phase 1: "error contract — domain
exceptions, one handler, one shape." Reconcile: 11 routes, one
try/except already deleted upstream — noted stale, rest holds. Safety
net: minimal `create_app()`; OpenAPI snapshot committed;
characterization tests pinning today's behavior, including the ugly
truth that `GET /orders/{id}` returns **200** `{"error": "..."}` on a
missing order. Execute: `domain/exceptions.py` (`OrderNotFound`,
`DuplicateSku`), `api/handlers.py` emitting one problem-shape, wired in
the factory; then route-by-route: service raises `OrderNotFound`, the
route's `except Exception: return {"error": str(e)}` dies, contract
test now asserts **404** with the problem shape. Verify: suite green;
scanner's `swallowed-exception` and `http-exception-deep` findings gone;
OpenAPI diff shows exactly the eleven approved deltas. Report lists
`GET /orders/{id}: 200+error-dict → 404 problem+json` (approved, phase
1) and one rule-5 bug: `POST /orders` wrote the order *before*
validating the SKU — recorded in `BUGS-FOUND.md`, not fixed. Commit:
`refactor(orders): phase 1 — error contract`.

## Bundled resources

None bundled. This skill runs against its siblings:

- `../fastapi-audit/references/principles.md` — READ the entries a
  finding cites when the fix direction is unclear.
- `../fastapi-audit/scripts/scan_api_smells.py` — RUN in step 4 to
  verify a phase's findings are gone.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
