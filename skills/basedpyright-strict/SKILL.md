---
name: basedpyright-strict
description: Set up basedpyright type checking on a Python repo, defaulting to recommended mode and strict only on request, then fix failing diagnostics without changing runtime behavior. Use when the user mentions basedpyright or pyright, strict typing, recommended mode, fixing type errors, or a type baseline.
disable-model-invocation: true
---

# basedpyright type checking

Default to `typeCheckingMode = "recommended"`, not `strict`. In current
basedpyright, unconfigured/plain basedpyright already means `recommended`:
all diagnostic rules are enabled as errors or warnings, and
`failOnWarnings = true` makes warnings fail the CLI. `strict` is narrower
than `recommended` in some basedpyright-exclusive areas, even though it
reports some shared rules as errors that `recommended` reports as warnings.

Use `strict` only when the user explicitly asks for it. basedpyright runs
through `uvx` — nothing is installed into the project except `types-*` stub
dev-dependencies. This skill gates on **failing diagnostics**: errors plus
warnings when `failOnWarnings` applies.

**Before executing, read `LEARNINGS.md` in this skill's folder** — entries
there override the instructions below.

## Bundled resources

- `scripts/setup_config.py` — **run** once to write `[tool.basedpyright]`.
- `scripts/triage.py` — **run** for every check: tiered worklist, `--json`
  snapshots, `--diff` against a snapshot. Never run bare `uvx basedpyright`
  for triage; the script's grouping is the deterministic worklist.
- `scripts/audit_diff.py` — **run** before finishing: flags behavior-smelling
  added lines (asserts, guards, bare ignores, uncommented casts).
- `references/rules.md` — **read** when a rule isn't covered by the fix
  policy below, and for baseline mechanics before writing a baseline.

## Step 0 — Preflight

- Require a clean `git status`; work on a branch.
- Find the behavior oracle: the repo's test command. Run it once and record
  the result — the suite must end in the identical state. No test suite →
  tell the user verification will be type-only.
- Note the version triage prints; rules shift between basedpyright releases.

## Step 1 — Configure

Run `setup_config.py` in the repo root. Exit 2 means config already exists
(a `pyrightconfig.json` silently overrides pyproject — reconcile into one
place); keep `typeCheckingMode` explicit. The script writes
`typeCheckingMode = "recommended"` by default; pass `--mode strict` only
when the user explicitly requested strict mode.

## Step 2 — Triage and plan

```bash
uv run <skill>/scripts/triage.py --project <repo> --json /tmp/tri-0.json
```

Report to the user before fixing anything: total errors and warnings, the
rule/tier table, and the plan. `triage.py` includes warnings by default
because recommended mode fails on warnings; pass `--errors-only` only for an
explicitly error-only/strict adoption. Fix everything feasible; if volume or
Tier B judgment sites make zero infeasible, say which portion will be
baselined or explicitly rule-disabled at the end. The baseline is the
remainder, never the strategy — do not skip to it.

## Step 3 — Fix, in this order

Each numbered batch is one commit. After each batch:
`triage.py --diff <last-snapshot>` — zero NEW failing diagnostics allowed;
save a fresh snapshot. While iterating inside a batch, pass just the touched
files to `triage.py` for fast subset checks; full run at the commit.

1. **Stubs**: `uv add --dev types-<pkg>` for each `reportMissingTypeStubs`;
   `allowedUntypedLibraries` in config for libs with no stubs. Never
   hand-write stubs that guess at behavior.
2. **Cascade sources**: triage lists error-dense files. Annotate the
   most-imported unannotated signatures first — `reportUnknown*` errors
   cascade from single untyped boundaries; one signature fix can clear
   hundreds. Fix the source, never each usage site.
3. **Tier A rules** (mechanical annotations), highest count first, one rule
   per batch.
4. **Tier B** (Optional handling, argument/attribute mismatches),
   module-by-module — these need the module's invariants; apply the fix
   policy per site.
5. **Remainder**: `uvx basedpyright --writebaseline -p <repo>`, commit
   `.basedpyright/baseline.json`. Read the baseline notes in
   `references/rules.md` first. For broad recommended-mode hygiene rules
   that require behavior-changing edits, prefer an explicit config override
   with a comment over scattering ignores.

## Fix policy

**Safe — apply freely (pure type-domain edits):**

- Annotations on parameters, returns, variables, class attributes. Two
  traps: never add a default value that wasn't there, and never turn a
  bare annotation into an assignment (a class attribute that didn't exist
  must not start existing).
- `from __future__ import annotations`, and imports moved under
  `if TYPE_CHECKING:` (also relieves annotation-only circular imports).
- `Protocol`, `TypeVar`, `ParamSpec`, `@overload` — as long as the
  implementation body is untouched.
- `uv add --dev types-*` stub packages.
- Correcting a lying annotation to the truth (e.g. `-> str` on a function
  that returns `str | None`), then handling the errors that surface at
  callers — those errors were always there; the lie hid them.
- `# pyright: ignore[specificRule]` — always with the rule in brackets.

**Forbidden — these change what the program does. Skip, flag, report:**

- `assert x is not None` — new exception path, and stripped under `python -O`.
- `if x is None:` guards, early returns, `isinstance()` checks — new control
  flow; isinstance also breaks duck-typed callers.
- Deleting "unreachable" code or "always-true" comparisons — on a freshly
  typed repo the annotation is as likely the lie as the code.
- Changing signatures, defaults, parameter names; mutable-default rewrites.
- Adding ABC bases, `@abstractmethod`, metaclasses, `__slots__`, dataclass
  conversions.
- Bare `# type: ignore` or bare `# pyright: ignore` (basedpyright disables
  `type: ignore` by default; leave it disabled).
- `Any` or `cast` used to silence an error you cannot explain.
- Deleting imports, variables, calls, or branches only because a warning says
  they are unused — removal can drop import side effects or observable work.

**Escape-hatch ladder — take the first rung that truthfully applies:**

1. Fix the type at its source (annotation or stub).
2. `# pyright: ignore[rule]` at the site.
3. Baseline entry (bulk pre-existing debt only, never one-offs).
4. `cast(T, x)` — only for out-of-band truth the checker can't express;
   REQUIRED same-line comment stating the invariant.
5. `Any` in the smallest possible scope; never on a public API.

**When basedpyright reveals a real bug** (a reachable None-deref, a genuine
typo): do not fix the behavior in this pass — the typing change must stay
mechanically reviewable. Suppress, flag with the exact format below, and put
it in the final report:

```python
x.frob()  # pyright: ignore[ruleName]  # FIXME(behavior): <why safe fixes don't apply + the real fix>
```

## Example

```python
user = find_user(uid)   # find_user() -> User | None
send(user.email)        # error: reportOptionalMemberAccess
```

- `find_user` can never return `None` (annotation is the lie) → rung 1: fix
  its return annotation to `User`.
- `None` is impossible *here* but possible elsewhere (uid came from a live
  session) → rung 2:
  `send(user.email)  # pyright: ignore[reportOptionalMemberAccess]`
- `None` is genuinely reachable → latent bug, flag it:
  `send(user.email)  # pyright: ignore[reportOptionalMemberAccess]  # FIXME(behavior): stale uid returns None; needs a guard — decide handling`

## Step 4 — Verify and report

All four, in order:

- [ ] `triage.py` full run: 0 failing diagnostics, or only the baselined /
      explicitly rule-disabled remainder.
- [ ] Test suite: identical result to the Step 0 run.
- [ ] `audit_diff.py` clean — or every finding restated in the report.
- [ ] Commits are per-batch and mechanical (one rule/module per commit).

End with this report (all sections REQUIRED):

```markdown
## basedpyright-strict report
- Before: <N> failing diagnostics | After: <M> | Baselined/disabled: <K>
- Commits: <one line each>
- Flagged sites needing your decision:
  | file:line | rule | why risky | proposed real fix |
- Suggested next ratchets: stricter severity for chosen warnings / reportAny cleanup / remove temporary rule disables
```

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
