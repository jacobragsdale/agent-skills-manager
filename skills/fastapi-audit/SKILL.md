---
name: fastapi-audit
description: "Audit a FastAPI service and produce a detailed refactoring plan \u2014 no code changes. Use when asked to audit an API for testability, typed request/response contracts, status-code correctness, exception handling, or undocumented endpoints; or to plan a refactor of routes that swallow errors, return raw dicts, or resist testing."
disable-model-invocation: true
---

# FastAPI audit

Audit a FastAPI service and deliver a refactoring plan toward one target
architecture: **typed contracts at the edge, functional core, one error
path**. Requests parse into constrained pydantic models before any logic
runs; responses leave through declared response models with explicit
status codes; business decisions live in pure functions below thin
routers; every dependency enters through an injectable seam; expected
rejections are typed domain exceptions mapped to a single uniform error
shape by one handler layer; unexpected exceptions reach one 500 handler.
The companion `fastapi-refactor` skill executes the plan this skill
produces.

## Hard rules

1. **Plan only. Do not edit, create, or delete any file in the audited
   repo.** The deliverable is a single plan document. If the user asks to
   implement it, that is `fastapi-refactor`, after they approve the plan.
2. **Every finding cites `file:line` and names the principle it violates**
   (by number from `references/principles.md`). No free-floating advice.
3. **Scanner findings are leads, not verdicts.** Verdict each one:
   *real* (goes in the plan), *false positive* (say why), or *accepted*
   (real but not worth fixing — say why). Never paste raw scanner output
   into the plan.
4. **Rank by blast radius, not by count.** A route that returns 200 on
   failure or blocks the event loop outranks fifty missing descriptions.
   Phase 1 of every plan is the error contract; documentation polish
   comes last.
5. **The contract must not lie.** For every route, the plan must answer:
   *can a client receive a status code or body shape this route does not
   declare?* Every undeclared 500, ad-hoc error dict, and unfiltered
   response model is a finding, even where the happy path looks correct.

## Workflow

### 1 — Map the service

Find the app construction (factory or module-level) and every
`APIRouter`. Build the inventory before judging anything:

- **Route inventory**: method, path, request model (or lack of one),
  response model, declared status codes, auth dependency — one row per
  route. Note routes whose *declared* contract differs from what the code
  can actually return.
- **Error surface**: every `raise HTTPException`, every exception
  handler, every try/except in a route. What does a client actually see
  for each failure mode — status, shape, message? Where can `str(exc)`
  leak internals?
- **Dependency graph**: what enters via `Depends` vs what is grabbed from
  module globals (engines, sessions, HTTP clients, settings). What could
  a test override today without `mock.patch`?
- **Startup**: where settings are read, what is validated at boot vs on
  first request, sync/async style per route vs the drivers actually used.

### 2 — Scan

RUN `scripts/scan_api_smells.py <src-dirs>` (from this skill's folder;
needs only `uv`). It mechanically flags untyped responses, implicit
status codes, HTTPException below the edge, swallowed exceptions in
routes, blocking calls in async routes, dict bodies, undocumented routes,
module-level clients, env reads in logic, and hidden inputs. `--help`
covers flags; `--json` for machine-readable output. Then apply hard
rule 3.

### 3 — Judge against the principles

READ `references/principles.md` — the numbered, sourced audit checklist.
The scanner cannot see the highest-value problems; check these by hand:

- Responses that are technically typed but wrong: one model shared by
  create/update/output, server-set fields optional everywhere,
  `float` money, `str` enums (principles 1, 4).
- Status-code semantics: 200-with-error-body, 500 for expected
  rejections, existence leaks (2); error shapes that vary by route (3).
- Rejections signaled by `None`/`False`/sentinel returns instead of
  typed exceptions or values (8).
- Business logic in route bodies and query composition inline (10);
  seams that exist but aren't injected (11).
- What actually happens at startup with a missing env var — trace it,
  don't assume (9, 13).
- Test reality: are there contract tests per declared status code, or
  happy-path-only tests through mocks (14)? Is the OpenAPI schema
  snapshotted anywhere (15)?

### 4 — Write the plan

Produce one document (`AUDIT.md` in the audited repo's root is the
default target — but only write it where the user says; hard rule 1
covers everything else). REQUIRED sections, in order:

```markdown
# Refactoring plan: <service name>

## Service snapshot
What it serves, who consumes it, blast radius if it lies to clients.

## Route inventory
One row per route: method | path | request model | response model |
declared statuses | actual possible statuses | auth | notes.

## Error surface
What a client sees in each failure mode today: trigger | status |
body shape | internals leaked? Include the undeclared ones.

## Findings
One row per confirmed finding:
file:line | smell | principle # | severity (contract-lie / silent-failure
/ testability / docs) | one-line fix direction.
Scanner false positives and accepted findings listed separately, each
with its reason.

## Target architecture
Concrete module layout for THIS repo (app factory, routers, services,
domain exceptions + handler module, settings), what each existing
function becomes, what dies.

## Refactor phases
Ordered, independently shippable. Each phase: goal, exact moves,
tests unlocked, contract changes (statuses/shapes that will visibly
change — enumerated per route), risk, and a "done when" check.
Phase 1 is always the error contract: domain exceptions, one handler
layer, one error shape, no swallowed exceptions.

## Test plan
Which logic gets pure unit tests, which routes get contract tests per
declared status via dependency_overrides fakes, where the OpenAPI
snapshot test lives.

## Error contract
The service's promised behavior: every status each route can emit, the
one error schema, which exceptions map to which statuses, what the 500
handler logs and returns.

## Out of scope
What was deliberately not addressed, so the plan's edges are explicit.
```

## Example

An internal `orders` service: routes return raw dicts from ORM rows,
`create_order` returns 200, every route body is wrapped in
`except Exception: return {"error": str(e)}`, services raise
`HTTPException(404)` directly, and `requests.get` runs inside
`async def` routes against a module-level session.

The audit yields: a route inventory showing 9 of 11 routes with no
response model and actual-vs-declared status mismatches on all of them;
an error surface showing three different error shapes plus stack traces
leaking through `str(e)`; findings citing `routes/orders.py:41`
(swallowed exception, principle 7), `services/orders.py:88`
(HTTPException below the edge, principle 6), `routes/orders.py:33`
(blocking call in async route, principle 12), `db.py:12` (module-level
engine, principles 11, 13). Target architecture: `app.py` factory,
`domain/exceptions.py`, `api/handlers.py` (one error shape),
`api/routes/*` thin, `services/*` pure-ish core, `settings.py`.
Phase 1: domain exceptions + one handler layer + delete the per-route
try/excepts. Phase 2: response/request models with explicit statuses.
Phase 3: injected dependencies, app factory, fix async/sync. Phase 4:
contract tests per status + OpenAPI snapshot. No code was changed — the
user got a plan to approve.

## Bundled resources

- `scripts/scan_api_smells.py` — RUN in step 2 on the audited source
  dirs. Never paste its raw output into the plan (hard rule 3).
- `references/principles.md` — READ in step 3. The numbered principles
  findings must cite (hard rule 2), each with source and FastAPI smell.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
