---
name: python-package-audit
description: "Audit a Python package or shared library and produce a detailed refactoring plan \u2014 no code changes. Use when asked to audit a package's public API/interface, dependency declarations and version bounds, layering (handlers, services, repositories), import-time behavior, exception design, or testability of a library other repos import."
disable-model-invocation: true
---

# Python package audit

Audit a Python package — usually an internal shared library other repos
import — and deliver a refactoring plan toward one target architecture:
**a deliberate public surface over a layered core**. Every importable
name is either promised (exported, `__all__`-declared, annotated,
documented) or underscored; dependency metadata tells consumers the
truth; importing is free of side effects; inside, thin handlers/services
orchestrate a domain core, persistence and I/O live in repositories/
adapters behind `Protocol` ports, and config enters at one composition
root. Failures reach consumers as the package's own exception types. The
companion `python-package-refactor` skill executes the plan this skill
produces.

## Hard rules

1. **Plan only. Do not edit, create, or delete any file in the audited
   repo.** The deliverable is a single plan document. If the user asks
   to implement it, that is `python-package-refactor`, after they
   approve the plan.
2. **Every finding cites `file:line` (or the pyproject.toml key) and
   names the principle it violates** (by number from
   `references/principles.md`). No free-floating advice.
3. **Scanner findings are leads, not verdicts.** Verdict each one:
   *real* (goes in the plan), *false positive* (say why), or *accepted*
   (real but not worth fixing — say why; an upper cap on a known
   incompatibility is the classic accepted case). Never paste raw
   scanner output into the plan.
4. **Rank by blast radius, not by count.** Radius here is measured in
   importers: a leaked private name three repos already depend on, or a
   dependency pin that breaks consumer resolution, outranks fifty
   missing annotations. Phase 1 of every plan is the public contract;
   internal layering comes after.
5. **Every contract must be deliberate.** For each importable name:
   promised or underscored — no third state. For each failure mode: a
   package exception type a consumer can catch. For each behavior
   switch: a parameter, never an env var. Anything consumers can
   observe that the package never promised gets flagged, even if the
   code looks correct.

## Workflow

### 1 — Map the package

Read `pyproject.toml` and the top-level `__init__.py`, then trace
inward. Build the inventory before judging anything:

- **Public surface**: every name importable without an underscore in
  its path — exported vs merely reachable, `__all__` coverage,
  annotation coverage, `py.typed` present or not.
- **Importers**: which repos/modules actually consume this package, and
  what they import (search consumer repos when reachable — the gap
  between *promised* and *actually used* decides severity under hard
  rule 4). Note anything importing underscored or undeclared names.
- **Dependency metadata**: runtime deps with their bounds, extras,
  dependency-groups, `requires-python` — and what a fresh consumer
  actually resolves.
- **Import graph and layers**: who imports whom; where domain logic,
  I/O, and orchestration currently live; cycles (including ones hidden
  by function-local imports); what runs at import time.
- **Failure surface**: every exception type that can escape the
  package, per public entry point — the package's own, stdlib's, or a
  third-party dependency's.

### 2 — Scan

RUN `scripts/scan_package_smells.py <src-dirs> <repo-root>` (from this
skill's folder; needs only `uv`). It mechanically flags dependency
pins/caps/missing bounds, dev deps in runtime metadata, missing
`requires-python` and `py.typed`, import-time side effects and clients,
logging configuration, env reads, accidental public surface
(`missing-all`, `untyped-public`, star imports), swallowed and generic
exceptions. `--help` covers flags; `--json` for machine-readable
output. Then apply hard rule 3.

### 3 — Judge against the principles

READ `references/principles.md` — the numbered, sourced audit
checklist. The scanner cannot see the highest-value problems; check
these by hand:

- Interface depth and ergonomics: shallow pass-through wrappers,
  positional booleans, parameter lists that mirror internals
  (principle 11); third-party types leaking through public signatures.
- Repository shape: session/ORM objects crossing into services,
  query-builder repos, fakes that would need query logic — apply the
  "fake is a set/dict wrapper" test (12); commits scattered instead of
  a unit of work (13).
- Anemic-vs-fat balance: business rules living in handlers instead of
  the domain, entrypoints doing more than transport (14).
- Ports and wiring: ABCs where Protocols belong, adapters imported by
  name in business code, module singletons instead of a composition
  root, env reads below the edge (15, 16).
- Compatibility machinery: is there any deprecation policy, changelog,
  or API diff gate at all (10, 20)? Lower bounds that were never
  tested (2)?
- Test reality: mock.patch stacks vs fakes, fakes nobody
  contract-tests, edge cases only reachable through real
  infrastructure (18, 19).

### 4 — Write the plan

Produce one document (`AUDIT.md` in the audited repo's root is the
default target — but only write it where the user says; hard rule 1
covers everything else). REQUIRED sections, in order:

```markdown
# Refactoring plan: <package name>

## Package snapshot
What it does, who imports it, blast radius of a breaking release.

## Public API inventory
One row per public name: name | kind | annotated? | in __all__? |
actually used by importers? | verdict (promise / underscore / deprecate).

## Dependency inventory
One row per dep: name | bounds | box (runtime/extra/group) | verdict.
Plus requires-python, py.typed, and lockfile status.

## Layering map
Current module → layer assignment (entrypoint / service / domain /
adapter / unclassifiable), the import edges that violate one-way flow,
and everything that executes at import time.

## Findings
One row per confirmed finding:
file:line | smell | principle # | severity (breaks-importers /
silent-failure / testability / hygiene) | one-line fix direction.
Scanner false positives and accepted findings listed separately, each
with its reason.

## Target architecture
Concrete layout for THIS package (public modules, _internal/ homes,
ports, repositories, composition root, exception hierarchy), what each
existing module becomes, what dies.

## Refactor phases
Ordered, independently shippable. Each phase: goal, exact moves, tests
unlocked, API changes (every public name whose location, signature, or
type visibly changes — enumerated, each with shim-or-remove), risk,
and a "done when" check. Phase 1 is always the public contract:
underscore internals, __all__, base exception, the griffe baseline —
it needs no restructuring and pays immediately.

## Test plan
Which domain logic gets exhaustive unit tests, which ports get
contract tests run against fake and real, where import-linter
contracts and the griffe CI gate land.

## Compatibility contract
The package's promised behavior: what is public, the deprecation
window, the versioning scheme, the supported Python/dependency window,
which exceptions each public entry point can raise.

## Out of scope
What was deliberately not addressed, so the plan's edges are explicit.
```

## Example

An internal `orderlib` consumed by four ETL repos and a FastAPI
service: `pyproject.toml` pins `pandas==2.1.0` and ships `pytest` as a
runtime dep; `import orderlib` configures logging and builds a
SQLAlchemy engine; services pass raw `Session` objects around; expected
"order missing" failures escape as `sqlalchemy.exc.NoResultFound`; two
consumer repos import `orderlib.utils.helpers._parse`.

The audit yields: a public API inventory showing 61 reachable names of
which 9 are promised and 2 privates are consumed downstream (flagged
breaks-importers, principle 6); a dependency inventory with the pin and
the dev dep (principles 1, 3); a layering map showing `client.py` as
entrypoint+service+adapter in one file with an import-time engine
(principles 8, 16); findings citing `client.py:14` (session in service
code, principle 12), `client.py:19` (swallowed exception, 9),
`pyproject.toml` deps (1, 2, 3). Target architecture: `orderlib/`
public façade + `_internal/{domain,services,adapters}`, `ports.py`
Protocols, `exceptions.py` hierarchy, `bootstrap.py` composition root.
Phase 1: underscore the internals behind re-exports, `__all__`, base
exception, griffe baseline — with a deprecation shim for the two
consumed private names. Phase 2: honest dependency metadata. Phase 3:
repository port + unit of work. Phase 4: contract tests, import-linter,
griffe gate in CI. No code was changed — the user got a plan to
approve.

## Bundled resources

- `scripts/scan_package_smells.py` — RUN in step 2 on the source dirs
  and repo root. Never paste its raw output into the plan (hard
  rule 3).
- `references/principles.md` — READ in step 3. The numbered principles
  findings must cite (hard rule 2), each with source and smell.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
