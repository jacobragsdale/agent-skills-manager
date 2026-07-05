---
name: python-package-refactor
description: "Execute an approved python-package-audit refactoring plan on a Python library: phase-by-phase, API-preserving, with a griffe public-API baseline and characterization tests before every move. Use when asked to implement a package audit plan, execute or continue an AUDIT.md on a library repo, or restructure a package per the audit."
disable-model-invocation: true
---

# Python package refactor

Execute a refactoring plan produced by the `python-package-audit` skill
(usually `AUDIT.md` in the repo root): move a Python library to a
deliberate public API, honest dependency declarations, and a layered
core (handlers/services orchestrating, repositories/adapters behind
ports) — one plan phase at a time, each phase shippable on its own. The
defining constraint: **this package has importers.** The public API —
every importable name, signature, exception type, and dependency
constraint — is the contract, and contract changes are enumerated,
deprecated on a schedule, and approved, never incidental. Plan documents
cite principles by number — those live in
`../python-package-audit/references/principles.md` (installed alongside
this skill); read the cited entries when a finding needs interpretation.

## Hard rules

1. **No plan, no refactor.** If there is no audit plan the user has
   seen, stop and offer to run `python-package-audit` first. Do not
   improvise a restructure from a verbal description — the plan is the
   approval artifact.
2. **Pin the API before touching anything.** Before the first move of
   the first phase, establish the griffe baseline: commit (or tag) the
   current state, and from then on RUN
   `uvx griffe check <pkg> -s <src-dir> --against <baseline-ref>` after
   every change — exit 0 means the public surface is intact, exit 1
   lists every breakage. Also write characterization tests importing the
   *public* surface only, pinning the behavior the phase touches.
3. **One phase per commit (or PR), phases in plan order.** A phase is
   done only when its "done when" check passes, the full suite is green,
   and `python-package-audit`'s scanner no longer reports the findings
   that phase claimed. Never start phase N+1 in the same commit.
4. **Every public-API change goes through the deprecation path, matched
   to the plan.** After each phase, run the griffe check; every reported
   breakage must appear on the plan's approved API-changes list. For
   approved removals/renames/signature changes, the default is a
   deprecation shim — old name re-exported, emitting `DeprecationWarning`
   with the replacement and `stacklevel=2` — removed only when the
   plan's compatibility contract says so (internal-only packages with
   all importers migrated in the same change may skip the shim if the
   plan says so explicitly). An unlisted breakage is a defect in the
   phase — revert or get it approved before merging.
5. **Refactor and bug fix never share a commit.** Restructuring commits
   keep characterization tests green. When a phase exposes a real bug,
   record it in `BUGS-FOUND.md` with file:line and evidence, tell the
   user, and keep going. Fixing it is its own commit, after the user
   confirms.
6. **Dependency-constraint edits are contract changes too.** Raising a
   lower bound, adding a dependency, or moving one to an extra changes
   what resolves in every consumer's environment — each such edit is
   listed in the phase report with its reason, and new lower bounds get
   verified (install with `uv pip install --resolution lowest-direct`
   or a constraints file, then run the suite).

## Workflow

### 1 — Reconcile the plan with reality

Read the plan, then re-verify every file:line it cites for the phase you
are about to execute — code drifts between audit and implementation.
Note stale findings; if more than roughly a third of the phase's
findings are stale, tell the user the plan needs a re-audit instead of
silently improvising. Establish where execution stands (plan checkmarks,
git history, whether target modules exist) and resume at the first
incomplete phase. Identify the importers: internal repos consuming this
package (search their imports if reachable) — they decide how much
compatibility machinery each change needs.

### 2 — Build the safety net

- Establish the griffe baseline ref (rule 2) and confirm
  `uvx griffe check` runs clean against itself.
- Write the rule-2 characterization tests: import only public names,
  exercise the behaviors this phase touches, pin current results —
  including current exception types raised on failure paths.
- Full suite green before the first move.

### 3 — Execute the phase, smallest reversible moves

Extract-and-delegate, never rewrite-in-place. Typical move order:

1. Create the target module (`_internal/` home, port Protocol, domain
   exception, repository class) next to the old code.
2. Move one unit, leave a re-export or delegating shim at the old
   location; griffe check must stay clean (the shim preserves the
   surface).
3. Sweep call sites, then handle the old name per rule 4 — deprecation
   shim or approved removal.
4. Update characterization tests to the new contract in the same commit
   as the approved change they witness — never loosen a test to
   "temporarily" pass.

Phase-specific notes:
- **Public-API phase** (underscore internals, `__all__`, `py.typed`):
  move implementation modules under `_internal/` while re-exporting the
  approved public names from `__init__.py` — griffe confirms the
  surface is unchanged even though every file moved. Add `py.typed`
  only when public signatures are fully annotated, or consumers'
  checkers inherit half-typed noise.
- **Exception phase**: introduce the package base exception and
  subclasses, then convert raise sites; where consumers may catch the
  old type, make the new exception *also* subclass it for one
  deprecation window, and note it in the report.
- **Layering phase**: define the port (Protocol) from what the core
  actually needs (not what the adapter offers), build the fake +
  contract test first, then move the real I/O into the
  repository/adapter and inject it — constructor/parameter injection,
  never a module-level singleton. Wire an import-linter contract as the
  phase's "done when" so the layering can't silently regress.
- **Dependency phase**: apply rule 6; pair every constraint change with
  the resolution test that proves it.

### 4 — Verify and report the phase

- Full suite green; characterization tests changed only where rule 4's
  approved list says so.
- RUN `../python-package-audit/scripts/scan_package_smells.py <src>`:
  findings this phase claimed must be gone; no new findings introduced.
- RUN the griffe check against the baseline; reconcile every reported
  breakage against the approved list (rule 4).
- Report: what moved where, the API-change list as `name: old → new
  (shimmed until vX)`, dependency-constraint changes with reasons, bugs
  recorded under rule 5, and what the next phase is. Then stop — the
  default is one phase per session; continue only if the user asked for
  the whole plan.

## Example

Plan for `orderlib`, phase 3: "repository layer — persistence behind a
port." Reconcile: `client.py:8` module-level engine still there, one
cited helper already deleted — noted stale, rest holds. Safety net:
griffe baseline at `v0.9.2`; characterization tests pinning
`fetch_orders()` results against a seeded dev database. Execute:
`OrderRepository` Protocol defined in `orderlib/ports.py` with exactly
the two methods the core calls; `FakeOrderRepository` plus a contract
test module that runs the same suite against fake and real;
`_internal/db/sqlalchemy_repo.py` absorbs the engine and raw queries;
`process()` now takes `repo: OrderRepository` — the old zero-arg
signature kept as a shim that builds the default repo and warns.
Verify: suite green; scanner's `module-level-client` and `env-read`
findings gone; griffe reports only the one approved signature change
(shimmed). Report lists it as `process(): repo now injectable, default
shimmed until v1.0`, plus one rule-5 bug: the old code swallowed
`IntegrityError` on duplicate orders — recorded, not fixed. Commit:
`refactor(orderlib): phase 3 — repository port`.

## Bundled resources

None bundled. This skill runs against its siblings and two external
tools:

- `../python-package-audit/references/principles.md` — READ the entries
  a finding cites when the fix direction is unclear.
- `../python-package-audit/scripts/scan_package_smells.py` — RUN in
  step 4 to verify a phase's findings are gone.
- `uvx griffe check <pkg> -s <src> --against <ref>` — RUN after every
  move; exit 1 + a breakage list means the public surface changed.
- `uvx --from import-linter lint-imports` (contracts in the audited
  repo's pyproject.toml per the plan) — RUN as the layering phase's
  "done when".

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
