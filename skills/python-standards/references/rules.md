# basedpyright rule catalog and mechanics

Researched 2026-07-03 against basedpyright docs (`https://docs.basedpyright.com/latest/`).
Rules shift between releases — when a rule here doesn't match what triage
prints, trust the installed version's docs
(`https://docs.basedpyright.com/latest/configuration/config-files/` has the
per-mode rule matrix).

## Running (what triage.py does under the hood)

- `uvx basedpyright` — no install needed (PyPI package bundles node); it
  auto-detects `./.venv` as the interpreter. No `.venv` → pass
  `--pythonpath <interpreter>`.
- Files passed on the CLI override config include/exclude (subset checks);
  `-` reads a NUL/newline file list from stdin (changed-files-only runs).
- `--outputjson` fields per diagnostic: `file` (abs), `severity`
  (error|warning|information), `message`, optional `rule` (absent for
  syntax errors), `range.start/end.line/character` (zero-based).
- Exit: 0 clean, 1 errors, 2 internal fatal, 3 config unreadable, 4 bad CLI.
- `--level error` hides warnings; `--threads` parallelizes.
- Default mode when unconfigured is `recommended`, not Pyright-style
  `standard` or `basic`. `recommended` enables all diagnostic rules as
  errors or warnings, and `failOnWarnings = true` makes warnings fail the
  CLI. Always set the mode explicitly so reviewers know this was intentional.

## Config quick reference (`[tool.basedpyright]`)

- Modes: `off`, `basic`, `standard`, `strict`, `recommended`, `all`.
  `recommended` and `all` are basedpyright-only. Do not treat the list as a
  simple severity ladder: `recommended` is broader than `strict`, but it
  downgrades many typing-hygiene diagnostics from errors to warnings while
  keeping the CLI failing through `failOnWarnings`.
- Per-rule override: `reportX = "error" | "warning" | "information" | "none"`.
- `strict = ["src/core"]` — per-path strict; `executionEnvironments` give
  per-dir rule overrides but NOT per-env typeCheckingMode (open issue #1638).
- `allowedUntypedLibraries = ["pkg"]` — mutes reportMissingTypeStubs and
  reportUnknown* for those imports (for libs with no stubs on PyPI).
- File pragmas override config: `# pyright: strict`,
  `# pyright: basic, reportPrivateUsage=false`.
- A `pyrightconfig.json` silently takes precedence over pyproject.toml.

## Recommended vs strict defaults

Default `recommended` gives these settings that `strict` does not:

| Setting | recommended effect |
|---|---|
| `deprecateTypingAliases` | Flags deprecated `typing.List`, `typing.Dict`, etc. |
| `strictGenericNarrowing` | Narrows generic type parameters more strictly. |
| `enableTypeIgnoreComments = false` | Discourages `# type: ignore`; use `# pyright: ignore[rule]`. |
| `failOnWarnings = true` | Warnings make CLI/CI exit nonzero. |

Rules enabled by `recommended` that are not enabled by `strict` include:
`reportPropertyTypeMismatch`, `reportImportCycles`,
`reportEmptyAbstractUsage`, `reportMissingSuperCall`,
`reportUninitializedInstanceVariable`, `reportCallInDefaultInitializer`,
`reportImplicitStringConcatenation`, `reportUnusedCallResult`,
`reportUnnecessaryTypeIgnoreComment`, `reportImplicitOverride`,
`reportAny`, `reportExplicitAny`, `reportIgnoreCommentWithoutRule`,
`reportInvalidCast`, `reportImplicitRelativeImport`,
`reportPrivateLocalImportUsage`, `reportUnsafeMultipleInheritance`,
`reportImplicitAbstractClass`, `reportUnannotatedClassAttribute`,
`reportInvalidAbstractMethod`, and `reportSelfClsDefault`.

`recommended` also downgrades some `strict` errors to warnings, but
`failOnWarnings = true` still makes them fail the CLI. Common examples:
`reportUnusedImport`, `reportUnusedVariable`,
`reportUntypedFunctionDecorator`, `reportPrivateUsage`,
`reportUnknownVariableType`, `reportMissingParameterType`,
`reportUnnecessaryCast`, and `reportMatchNotExhaustive`.

## Baseline mechanics (read before --writebaseline)

- `uvx basedpyright --writebaseline` → `.basedpyright/baseline.json`; commit it.
- Matching key is **file path + rule + column range** (not line number), so
  edits elsewhere in a file don't resurface baselined errors — but renames
  and refactors that shift columns DO. Recovery: rerun `--writebaseline`.
- The baseline auto-shrinks as baselined errors get fixed (`--baselinemode
  auto` is the default ratchet; `lock`/`discard` exist).
- Regenerate only when errors incorrectly resurface or after enabling new
  rules. One-off suppressions use `# pyright: ignore[rule]`, never the
  baseline.
- Two same-rule errors at the same column in one file can alias each other.

## Tier A — mechanical, fix is always runtime-safe

| Rule | Meaning → safe fix |
|---|---|
| reportMissingParameterType / reportMissingTypeArgument | Unannotated param / bare generic → annotate (`list[str]`, not `list`); infer from call sites and docstrings. |
| reportUnknown{Variable,Member,Argument,Parameter,Lambda}Type | Type is partially Any — cascades from ONE untyped source. Annotate the source (function signature, lib boundary, stub); never patch usage sites one by one. |
| reportMissingTypeStubs | Untyped third-party import → `uv add --dev types-<pkg>`; no stubs on PyPI → `allowedUntypedLibraries`. Never hand-write stubs that guess behavior. |
| reportMissingModuleSource | Stub without source — informational; suppress or ignore. |
| reportUnannotatedClassAttribute | Annotate the attr. Never add a value that wasn't there. |
| reportImplicitOverride | Add `@override` (`typing` on 3.12+, else `typing_extensions` — note: new runtime dependency on <3.12). |
| reportPrivateLocalImportUsage | Re-export with redundant alias: `from x import y as y`. |
| reportImplicitRelativeImport | `import foo` in a package → `from . import foo`. Check the module isn't also run as a script first. |
| reportUnusedCallResult | Assign to `_ = f(...)`. Teams often disable this rule instead. |
| reportIgnoreCommentWithoutRule | Add the rule name into the brackets. |
| reportImplicitStringConcatenation | Make the concatenation explicit or add a separator if it was a real missing-comma bug. |
| reportDeprecated / reportTypeCommentUsage | Modernize deprecated typing aliases / type comments into current annotations. |

## Tier B — the checker may be right; judgment per site

| Rule | Meaning → approach |
|---|---|
| reportOptional{MemberAccess,Subscript,Call,Iterable,Operand} | `T \| None` used as `T`. Ladder: source annotation lie → fix it; impossible-here → `pyright: ignore[rule]`; genuinely reachable → latent bug, FLAG. The single most common strict-mode error class. |
| reportAttributeAccessIssue | Annotation too wide (fix: narrow / Protocol / overloads) or a real typo/dead path (FLAG as bug). |
| reportArgumentType / reportCallIssue / reportAssignmentType / reportReturnType / reportIndexIssue / reportOperatorIssue | Declared types disagree. Usually the annotation is the lie (e.g. `-> str` that returns `str \| None`) — correcting it is safe and surfaces the callers that were always broken. Code wrong → FLAG. |
| reportPropertyTypeMismatch / reportInvalidCast | Types claim incompatible truths. Correct lying annotations first; if runtime truth is out-of-band, prefer `pyright: ignore[rule]` with a comment over a cast. |
| reportPossiblyUnboundVariable | Assigned only in some branches. No pure-annotation fix exists: pre-initializing changes a NameError crash into a flowing value. Use `pyright: ignore[reportPossiblyUnboundVariable]` and FLAG if the unbound path looks reachable. |
| reportImportCycles | Usually needs dependency-direction design, not a drive-by edit. Use `TYPE_CHECKING` for annotation-only cycles; otherwise flag. |
| reportSelfClsDefault / reportInvalidAbstractMethod / reportEmptyAbstractUsage | Class model smells. Fix only if the intended abstraction is obvious and behavior stays unchanged; otherwise flag or disable. |
| reportUnnecessaryComparison / reportUnnecessaryIsInstance / reportUnnecessaryContains / reportUnreachable | "Dead" per the declared types — but on a freshly typed repo the types are often the lie. Never delete the code in this pass: fix the annotation or ignore-with-rule. |

## Tier C — Any-policing (basedpyright-exclusive)

`reportAny`, `reportExplicitAny`: fix at the source when cheap (annotate /
stub / `object` + narrowing); otherwise set both to `"none"` during adoption
and list re-enabling them as a next ratchet in the report.

## Tier D — commonly suppressed on legacy repos

`reportUnusedImport`, `reportUnusedVariable`, `reportUnusedCallResult`,
`reportCallInDefaultInitializer`, `reportMissingSuperCall`,
`reportUnnecessaryTypeIgnoreComment` (known false positives around
overloads, issue #496), `reportUninitializedInstanceVariable`,
`reportUnsafeMultipleInheritance`, `reportImplicitAbstractClass` (its "fix"
— adding an ABC base — is behavior-modifying: instantiation starts raising),
`reportMatchNotExhaustive`, and `reportPrivateUsage`. Downgrade to `"none"`
with a config comment rather than scattering ignores when fixing would change
runtime behavior or public API shape.

## Ignore-comment semantics (why the skill bans bare ignores)

- basedpyright disables `# type: ignore` by default
  (`enableTypeIgnoreComments = false`): per PEP 484 it suppresses ALL
  diagnostics on the line, and even `# type: ignore[rule]` ignores the
  bracket contents. Leave it disabled.
- `# pyright: ignore[rule]` is rule-scoped and validated;
  `reportUnnecessaryTypeIgnoreComment` can flag it when stale. A wrong
  `cast` is never flagged (except non-overlapping casts via
  `reportInvalidCast`) — which is why ignores outrank casts on the ladder.
- Repo also runs mypy → dual comments are unavoidable:
  `# type: ignore[x]  # pyright: ignore[y]`.

## Annotation runtime gotchas (the "safe" fixes that aren't, without care)

- Annotations are evaluated at runtime on <3.14 unless
  `from __future__ import annotations` is present — an annotation-only
  import or forward reference can raise NameError at import time. Adding
  the future import is itself safe and is the standard companion edit.
- `if TYPE_CHECKING:` imports are safe by construction; pair with the
  future import (or quoted annotations).
- `@overload` bodies never run; only the implementation does — keep it
  untouched.
- `cast(T, x)` returns `x` unchanged at runtime; `assert_type` is also a
  runtime call (no-op, but an import + call — avoid in hot paths, fine in
  tests).

## Sources

- CLI: https://docs.basedpyright.com/latest/configuration/command-line/
- Config + per-mode rule matrix: https://docs.basedpyright.com/latest/configuration/config-files/
- Pragmas: https://docs.basedpyright.com/latest/configuration/comments/
- Baseline: https://docs.basedpyright.com/latest/benefits-over-pyright/baseline/
- basedpyright-only rules: https://docs.basedpyright.com/latest/benefits-over-pyright/new-diagnostic-rules/
- Gradual adoption playbook: https://github.com/microsoft/pylance-release/blob/main/docs/howto/gradual-strict-adoption.md
- Ignore-comment issues: DetachHead/basedpyright #55, #330, #374, #496
