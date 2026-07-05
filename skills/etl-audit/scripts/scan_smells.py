#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Static smell scan for ETL-style Python jobs.

Walks Python files and flags patterns that make batch jobs silently fail,
nondeterministic, or hard to test. Findings are LEADS for a human/agent
audit, not verdicts — every finding needs a judgment call before it goes
in a refactoring plan.

Checks (id — what it flags):
  swallowed-exception  except body is only pass/continue/... , or catches
                       broadly and neither re-raises nor exits nonzero
  exit-masking         sys.exit(0)/sys.exit() or os._exit inside an except
                       handler — errors converted into success exit codes
  nondeterminism       datetime.now/utcnow/today, time.time, random.*,
                       uuid.uuid4 called inside a function that isn't an
                       obvious entrypoint (main/cli/run) — hidden inputs
  env-in-logic         os.environ / os.getenv read inside non-entrypoint
                       functions — config scattered instead of parsed once
  io-in-logic          a function that both performs I/O (open, requests,
                       read_sql/to_csv, cursor.execute, boto3, ...) and
                       branches/loops — transform logic welded to I/O
  module-side-effect   executable statements at module top level outside
                       an `if __name__ == "__main__"` guard
  missing-main-guard   script has top-level execution but no main guard
  global-state         `global` statement — mutable module state
  mutable-default      mutable default argument (list/dict/set literal)

Exit codes: 0 = clean, 1 = findings, 2 = a file could not be parsed.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ENTRYPOINT_NAMES = {"main", "cli", "run", "entrypoint"}

NONDET_CALLS = {
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
    ("date", "today"), ("time", "time"), ("time", "monotonic"),
    ("uuid", "uuid4"), ("uuid", "uuid1"),
}
NONDET_MODULES = {"random"}

IO_ATTR_HINTS = {
    "read_csv", "read_sql", "read_sql_query", "read_sql_table", "read_excel",
    "read_parquet", "read_json", "to_csv", "to_sql", "to_parquet", "to_excel",
    "execute", "executemany", "commit", "fetchall", "fetchone", "fetchmany",
    "urlopen", "download_file", "upload_file", "put_object", "get_object",
}
# Generic verbs shared with dicts/lists — only I/O when the receiver's name
# looks like a client (`session.get`, `s3_client.put`), never `totals.get`.
IO_GENERIC_VERBS = {"get", "post", "put", "delete", "request", "send",
                    "publish"}
IO_RECEIVER_HINTS = ("client", "session", "conn", "cursor", "sock", "http",
                     "s3", "bucket", "api", "queue", "producer", "channel")
IO_NAME_HINTS = {"open", "input"}
IO_MODULE_HINTS = {"requests", "httpx", "urllib", "boto3", "smtplib", "ftplib",
                   "paramiko", "shutil"}


@dataclass
class Finding:
    path: str
    line: int
    check: str
    message: str


def dotted(node: ast.AST) -> str:
    """Best-effort dotted name for a call target: 'datetime.now', 'open'."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        inner = dotted(node.func)
        if inner:
            parts.append(inner)
    return ".".join(reversed(parts))


def is_entrypoint(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return func.name in ENTRYPOINT_NAMES or func.name.startswith("_main")


def handler_reraises_or_fails(handler: ast.ExceptHandler) -> bool:
    """True if the handler re-raises, raises anything, or exits nonzero."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name in ("sys.exit", "exit"):
                if node.args and not (
                    isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in (0, None)
                ):
                    return True
    return False


def check_except_handlers(tree: ast.AST, path: str, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            body_is_noop = all(
                isinstance(s, (ast.Pass, ast.Continue))
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                for s in handler.body
            )
            broad = handler.type is None or (
                isinstance(handler.type, ast.Name)
                and handler.type.id in ("Exception", "BaseException")
            )
            for inner in ast.walk(handler):
                if isinstance(inner, ast.Call):
                    name = dotted(inner.func)
                    exits_zero = name in ("sys.exit", "exit", "os._exit") and (
                        not inner.args
                        or (isinstance(inner.args[0], ast.Constant)
                            and inner.args[0].value in (0, None))
                    )
                    if exits_zero:
                        findings.append(Finding(
                            path, inner.lineno, "exit-masking",
                            f"{name}({'0' if inner.args else ''}) inside except "
                            "handler — a failed run reports success to the scheduler",
                        ))
            if body_is_noop:
                findings.append(Finding(
                    path, handler.lineno, "swallowed-exception",
                    "except body is only pass/continue — the error vanishes",
                ))
            elif broad and not handler_reraises_or_fails(handler):
                findings.append(Finding(
                    path, handler.lineno, "swallowed-exception",
                    "broad except that neither re-raises nor exits nonzero — "
                    "likely logs-and-continues past a real failure",
                ))


def check_functions(tree: ast.AST, path: str, findings: list[Finding]) -> None:
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in func.args.defaults + func.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                findings.append(Finding(
                    path, default.lineno, "mutable-default",
                    f"mutable default argument in {func.name}()",
                ))
        entry = is_entrypoint(func)
        has_io = False
        branchiness = 0
        for node in ast.walk(func):
            if isinstance(node, ast.Global):
                findings.append(Finding(
                    path, node.lineno, "global-state",
                    f"`global {', '.join(node.names)}` in {func.name}() — "
                    "mutable module state defeats isolated testing",
                ))
            if isinstance(node, (ast.If, ast.For, ast.While)):
                branchiness += 1
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                head, _, tail = name.rpartition(".")
                head_root = head.split(".")[0] if head else ""
                if (
                    name in IO_NAME_HINTS
                    or tail in IO_ATTR_HINTS
                    or head_root in IO_MODULE_HINTS
                    or (tail in IO_GENERIC_VERBS
                        and any(h in head.lower() for h in IO_RECEIVER_HINTS))
                ):
                    has_io = True
                if not entry:
                    pair = (head_root or head, tail)
                    if pair in NONDET_CALLS or head_root in NONDET_MODULES:
                        findings.append(Finding(
                            path, node.lineno, "nondeterminism",
                            f"{name}() inside {func.name}() — a hidden input; "
                            "pass the value in as a parameter",
                        ))
                    if name in ("os.getenv", "os.environ.get") or (
                        head == "os" and tail == "environ"
                    ):
                        findings.append(Finding(
                            path, node.lineno, "env-in-logic",
                            f"environment read inside {func.name}() — parse "
                            "config once at the entrypoint and pass it down",
                        ))
            if isinstance(node, ast.Subscript) and dotted(node.value) == "os.environ":
                if not entry:
                    findings.append(Finding(
                        path, node.lineno, "env-in-logic",
                        f"os.environ[...] inside {func.name}() — parse config "
                        "once at the entrypoint and pass it down",
                    ))
        if has_io and branchiness >= 2 and not entry:
            findings.append(Finding(
                path, func.lineno, "io-in-logic",
                f"{func.name}() mixes I/O with branching logic — candidate to "
                "split into a gateway (I/O only) and a pure transform",
            ))


def check_module_level(tree: ast.Module, path: str, findings: list[Finding]) -> None:
    has_exec = False
    has_guard = False
    for node in tree.body:
        if isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
            ):
                has_guard = True
                continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef, ast.Assign,
                             ast.AnnAssign, ast.AugAssign)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        has_exec = True
        findings.append(Finding(
            path, node.lineno, "module-side-effect",
            f"{type(node).__name__} at module top level — runs at import "
            "time, outside any error handling or test control",
        ))
    if has_exec and not has_guard:
        findings.append(Finding(
            path, 1, "missing-main-guard",
            "top-level execution with no `if __name__ == '__main__'` guard — "
            "file cannot be imported for testing without running the job",
        ))


def scan_file(path: Path) -> tuple[list[Finding], bool]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [Finding(str(path), getattr(exc, "lineno", 1) or 1, "parse-error",
                        f"could not parse: {exc}")], True
    findings: list[Finding] = []
    rel = str(path)
    check_except_handlers(tree, rel, findings)
    check_functions(tree, rel, findings)
    check_module_level(tree, rel, findings)
    return findings, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan Python ETL/batch-job code for testability and "
        "silent-failure smells. Prints file:line: [check] message, one per "
        "finding. Findings are leads, not verdicts.",
    )
    parser.add_argument("paths", nargs="+", type=Path,
                        help="files or directories to scan (dirs walked "
                        "recursively for *.py; venvs and hidden dirs skipped)")
    parser.add_argument("--json", action="store_true",
                        help="emit findings as a JSON array instead of text")
    parser.add_argument("--checks",
                        help="comma-separated check ids to include "
                        "(default: all)")
    args = parser.parse_args()

    files: list[Path] = []
    for p in args.paths:
        if p.is_dir():
            files.extend(
                f for f in sorted(p.rglob("*.py"))
                if not any(part.startswith(".") or part in
                           ("venv", "node_modules", "__pycache__", "build",
                            "dist", ".venv")
                           for part in f.parts)
            )
        elif p.is_file():
            files.append(p)
        else:
            print(f"error: {p} does not exist", file=sys.stderr)
            return 2

    if not files:
        print("error: no Python files found under the given paths",
              file=sys.stderr)
        return 2

    only = set(args.checks.split(",")) if args.checks else None
    all_findings: list[Finding] = []
    parse_failed = False
    for f in files:
        findings, failed = scan_file(f)
        parse_failed = parse_failed or failed
        all_findings.extend(
            fi for fi in findings if only is None or fi.check in only
        )

    all_findings.sort(key=lambda fi: (fi.path, fi.line))
    if args.json:
        print(json.dumps([asdict(fi) for fi in all_findings], indent=2))
    else:
        for fi in all_findings:
            print(f"{fi.path}:{fi.line}: [{fi.check}] {fi.message}")
        print(f"\n{len(all_findings)} finding(s) across {len(files)} file(s)",
              file=sys.stderr)

    if parse_failed:
        return 2
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
