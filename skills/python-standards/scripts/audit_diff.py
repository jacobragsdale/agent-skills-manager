#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Scan a git diff for added Python lines that smell like behavior changes.

A pure typing pass adds annotations, imports, and rule-scoped ignore comments
— it does not add asserts, guards, raises, or control flow. This is a
heuristic reviewer, not a verdict: exit 1 lists every suspicious added line
for human/agent review; each is either reverted or explained in the final
report.

Usage: audit_diff.py [--ref HEAD~3] [--project DIR]
Compares working tree (incl. staged) against --ref (default HEAD).
"""

import argparse
import re
import subprocess
import sys

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*assert\b"), "new assert — raises where code proceeded; stripped under python -O"),
    (re.compile(r"\bisinstance\s*\("), "new isinstance — new control flow; breaks duck-typed callers"),
    (re.compile(r"^\s*raise\b"), "new raise — new exception path"),
    (re.compile(r"^\s*(el)?if\b.*\bNone\b"), "new None guard — new control flow"),
    (re.compile(r"^\s*return\b"), "new return — control flow (fine inside a brand-new function; review)"),
    (re.compile(r"#\s*type:\s*ignore(?!\[)"), "bare type: ignore — use pyright: ignore[rule]"),
    (re.compile(r"#\s*pyright:\s*ignore(?!\[)"), "bare pyright: ignore — add the rule name in brackets"),
]
CAST = re.compile(r"\bcast\s*\(")


def added_lines(ref: str, project: str) -> list[tuple[str, int, str]]:
    proc = subprocess.run(
        ["git", "-C", project, "diff", ref, "-U0", "--no-color", "--", "*.py"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        print(f"error: git diff failed (exit {proc.returncode})", file=sys.stderr)
        sys.exit(2)

    out: list[tuple[str, int, str]] = []
    current_file, lineno = "", 0
    for raw in proc.stdout.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            out.append((current_file, lineno, raw[1:]))
            lineno += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="HEAD", help="git ref to diff against (default: HEAD)")
    parser.add_argument("--project", default=".", help="repo root (default: cwd)")
    args = parser.parse_args()

    findings = 0
    for file, lineno, line in added_lines(args.ref, args.project):
        for pattern, why in PATTERNS:
            if pattern.search(line):
                findings += 1
                print(f"{file}:{lineno}: {why}\n    +{line.rstrip()}")
        if CAST.search(line) and "#" not in line:
            findings += 1
            print(f"{file}:{lineno}: cast without a same-line invariant comment\n    +{line.rstrip()}")

    if findings:
        print(f"\n{findings} suspicious added line(s) — revert each, or restate it in the final report.")
        return 1
    print("clean: no behavior-smelling added lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
