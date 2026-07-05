#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run basedpyright (via uvx) and print a deterministic, tiered triage report.

Groups failing diagnostics by rule (with a safety tier) and by file, so
fixes can proceed cheapest-safe-first. Save raw output with --json and
compare a later run against it with --diff to prove no new diagnostics were
introduced.

Tiers: A = mechanical, always runtime-safe fix; B = judgment per site (the
checker may have found a real bug); C = Any-policing; ? = unmapped rule
(see references/rules.md); D = commonly suppressed on legacy repos.

Exit codes: 0 = no failing diagnostics reported, 1 = diagnostics present,
2 = basedpyright itself failed (config/CLI/internal error).
"""

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

TIERS: dict[str, str] = {
    # Tier A — mechanical, runtime-safe
    "reportMissingParameterType": "A", "reportMissingTypeArgument": "A",
    "reportUnknownParameterType": "A", "reportUnknownVariableType": "A",
    "reportUnknownMemberType": "A", "reportUnknownArgumentType": "A",
    "reportUnknownLambdaType": "A", "reportMissingTypeStubs": "A",
    "reportMissingModuleSource": "A", "reportUnannotatedClassAttribute": "A",
    "reportImplicitOverride": "A", "reportPrivateLocalImportUsage": "A",
    "reportImplicitRelativeImport": "A", "reportImplicitStringConcatenation": "A",
    "reportUnusedCallResult": "A", "reportIgnoreCommentWithoutRule": "A",
    "reportDeprecated": "A", "reportTypeCommentUsage": "A",
    # Tier B — judgment per site
    "reportOptionalMemberAccess": "B", "reportOptionalSubscript": "B",
    "reportOptionalCall": "B", "reportOptionalIterable": "B",
    "reportOptionalOperand": "B", "reportAttributeAccessIssue": "B",
    "reportArgumentType": "B", "reportCallIssue": "B",
    "reportAssignmentType": "B", "reportReturnType": "B",
    "reportIndexIssue": "B", "reportOperatorIssue": "B",
    "reportPropertyTypeMismatch": "B", "reportInvalidCast": "B",
    "reportPossiblyUnboundVariable": "B", "reportUnboundVariable": "B",
    "reportImportCycles": "B", "reportSelfClsDefault": "B",
    "reportInvalidAbstractMethod": "B", "reportEmptyAbstractUsage": "B",
    "reportUnnecessaryComparison": "B",
    "reportUnnecessaryIsInstance": "B", "reportUnnecessaryContains": "B",
    "reportRedeclaration": "B", "reportConstantRedefinition": "B",
    "reportGeneralTypeIssues": "B", "reportUnreachable": "B",
    # Tier C — Any-policing
    "reportAny": "C", "reportExplicitAny": "C",
    # Tier D — commonly suppressed on legacy repos
    "reportMissingSuperCall": "D", "reportUnnecessaryTypeIgnoreComment": "D",
    "reportUninitializedInstanceVariable": "D", "reportUnusedImport": "D",
    "reportUnusedVariable": "D", "reportCallInDefaultInitializer": "D",
    "reportUnsafeMultipleInheritance": "D", "reportImplicitAbstractClass": "D",
    "reportMatchNotExhaustive": "D", "reportPrivateUsage": "D",
    "reportUntypedFunctionDecorator": "D", "reportUnnecessaryCast": "D",
}
TIER_SORT = {"A": 0, "B": 1, "?": 2, "C": 3, "D": 4}


def run_basedpyright(paths: list[str], project: str | None) -> dict:
    cmd = ["uvx", "basedpyright", "--outputjson", "--threads"]
    if project:
        cmd += ["--project", project]
    cmd += paths
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # exit 0/1 = ran fine (1 just means errors found); 2/3/4 = tool failure
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        sys.stderr.write(proc.stderr or proc.stdout)
        print(f"error: basedpyright failed (exit {proc.returncode})", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout[:2000])
        print("error: basedpyright produced non-JSON output", file=sys.stderr)
        sys.exit(2)


def rel(file: str) -> str:
    try:
        return str(Path(file).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return file


def key(d: dict) -> tuple[str, str, str]:
    # line numbers shift as fixes land; (file, rule, message) is the stable-ish identity
    return (rel(d["file"]), d.get("rule", "syntax"), d["message"].split("\n")[0][:120])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="limit the check to these files/dirs (overrides config include)")
    parser.add_argument("--project", "-p", help="repo root / config location")
    parser.add_argument("--json", type=Path, metavar="OUT", help="save raw basedpyright JSON snapshot here")
    parser.add_argument("--diff", type=Path, metavar="OLD", help="compare against a previous --json snapshot")
    parser.add_argument("--errors-only", action="store_true",
                        help="triage only errors; use only for explicit error-only adoption")
    parser.add_argument("--include-warnings", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    data = run_basedpyright(args.paths, args.project)
    if args.json:
        args.json.write_text(json.dumps(data, indent=1))

    wanted = {"error"} if args.errors_only else {"error", "warning"}
    diags = [d for d in data["generalDiagnostics"] if d["severity"] in wanted]
    s = data["summary"]
    print(f"basedpyright {data.get('version', '?')} | files {s['filesAnalyzed']} | "
          f"errors {s['errorCount']} | warnings {s['warningCount']}"
          + (" (triaging errors only)" if args.errors_only else " (triaging errors + warnings)"))

    by_rule: dict[str, list[dict]] = defaultdict(list)
    for d in diags:
        by_rule[d.get("rule", "syntax")].append(d)

    if by_rule:
        print(f"\n{'RULE':<40} {'TIER':<4} {'COUNT':<6} TOP FILES")
        for rule, ds in sorted(by_rule.items(), key=lambda kv: (TIER_SORT[TIERS.get(kv[0], '?')], -len(kv[1]))):
            tier = TIERS.get(rule, "?")
            files = Counter(rel(d["file"]) for d in ds)
            top = "  ".join(f"{f}({n})" for f, n in files.most_common(3))
            print(f"{rule:<40} {tier:<4} {len(ds):<6} {top}")

        dense = Counter(rel(d["file"]) for d in diags)
        print("\nDiagnostic-dense files (cascade candidates — fix boundary signatures here first):")
        for f, n in dense.most_common(5):
            print(f"  {n:>5}  {f}")

    if args.diff:
        old = json.loads(args.diff.read_text())
        old_keys = {key(d) for d in old["generalDiagnostics"] if d["severity"] in wanted}
        new_keys = {key(d): d for d in diags}
        fixed = old_keys - new_keys.keys()
        introduced = [d for k, d in new_keys.items() if k not in old_keys]
        print(f"\nvs {args.diff}: FIXED {len(fixed)} | NEW {len(introduced)}")
        for d in sorted(introduced, key=key):
            line = d["range"]["start"]["line"] + 1
            print(f"  NEW {rel(d['file'])}:{line} {d.get('rule', 'syntax')}: {d['message'].splitlines()[0]}")
        if introduced:
            print("  ^ new diagnostics — a fix above removed a lying annotation (good: now fix the truth)"
                  " or was wrong (bad: revert). Inspect before proceeding.")

    return 1 if diags else 0


if __name__ == "__main__":
    raise SystemExit(main())
