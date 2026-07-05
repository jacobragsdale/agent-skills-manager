#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Lint an AGENTS.md against the evidence-based house rules.

Errors (exit 1): unfilled placeholders, no/multiple H1, length over hard cap,
referenced repo paths that don't exist.
Warnings: over soft length target, vague filler phrases, negation stacks,
no commands present.

Usage: lint_agents_md.py path/to/AGENTS.md [--repo-root DIR]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SOFT_LINES, HARD_LINES = 150, 300

VAGUE = [
    "write clean code", "best practices", "high quality", "high-quality",
    "be careful", "as appropriate", "helpful assistant", "properly",
    "robust and maintainable", "follow good", "make sure to test",
]
PLACEHOLDER_RE = re.compile(r"<[a-z][^<>\n]{2,60}>|\bTODO\b|\bFIXME\b|\bTBD\b")
NEGATION_RE = re.compile(r"^\s*[-*]?\s*\**(never|don'?t|do not)\b", re.IGNORECASE)
# backticked tokens that look like repo paths: contain / , no spaces, not a URL or flag
PATH_RE = re.compile(r"`([^`\s]+/[^`\s]*)`")
# a backticked span shaped like an invocation: executable word, space, args
CMD_HINT_RE = re.compile(r"`[a-z][a-zA-Z0-9._-]* [^`\n]+`")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", help="AGENTS.md to lint")
    p.add_argument("--repo-root", default=None, help="repo root for path checks (default: the file's directory)")
    args = p.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 1
    root = Path(args.repo_root) if args.repo_root else path.resolve().parent
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    in_fence = False
    body: list[tuple[int, str]] = []  # (lineno, line) outside fences
    fenced: list[str] = []
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        (fenced.append(line) if in_fence else body.append((i, line)))

    errors: list[str] = []
    warnings: list[str] = []

    if not text.strip():
        print("error: file is empty", file=sys.stderr)
        return 1

    n = len(lines)
    if n > HARD_LINES:
        errors.append(f"{n} lines — over the {HARD_LINES}-line hard cap; split into nested/linked docs")
    elif n > SOFT_LINES:
        warnings.append(f"{n} lines — over the {SOFT_LINES}-line target where measured gains reverse")

    h1s = [i for i, l in body if re.match(r"^# \S", l)]
    if len(h1s) == 0:
        errors.append("no H1 title")
    elif len(h1s) > 1:
        errors.append(f"multiple H1s at lines {h1s} — exactly one")

    for i, l in body:
        # backticked spans are pattern documentation (`skills/<name>/`), not placeholders
        stripped = re.sub(r"`[^`]*`", "", l)
        for m in PLACEHOLDER_RE.finditer(stripped):
            errors.append(f"line {i}: unfilled placeholder/TODO: {m.group(0)!r}")

    low = "\n".join(l.lower() for _, l in body)
    for phrase in VAGUE:
        if phrase in low:
            warnings.append(f"vague filler phrase present: {phrase!r} — replace with a concrete rule or delete")

    negations = [i for i, l in body if NEGATION_RE.match(l)]
    if len(negations) > 7:
        warnings.append(f"{len(negations)} negation-led rules (lines {negations[:10]}...) — prohibition stacks make agents timid; state alternatives or convert to hooks")

    if not fenced and not CMD_HINT_RE.search(text):
        warnings.append("no commands found (no fenced blocks, no backticked invocations) — commands are the highest-ROI section")

    missing = []
    for _, l in body:
        for m in PATH_RE.finditer(l):
            token = m.group(1)
            if token.startswith(("http", "@", "-", "<", "~", "/")) or "*" in token or "<" in token or "$" in token or token.endswith("/..."):
                continue
            if not (root / token.rstrip("/")).exists():
                missing.append(token)
    for token in sorted(set(missing)):
        errors.append(f"referenced path does not exist in repo: `{token}` (stale paths actively mislead)")

    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"WARN:  {w}")
    if not errors and not warnings:
        print(f"OK — {n} lines, clean")
    elif not errors:
        print(f"OK with {len(warnings)} warning(s) — {n} lines")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
