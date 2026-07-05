#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Static smell scan for FastAPI services.

Walks Python files and flags patterns that make an API lie to its clients,
swallow failures, or resist testing. Findings are LEADS for a human/agent
audit, not verdicts — every finding needs a judgment call before it goes
in a refactoring plan.

Checks (id — what it flags):
  untyped-response      route with no return annotation and no
                        response_model= kwarg — the response contract is
                        whatever the function happens to return
  implicit-status       POST/DELETE route with no explicit status_code=
                        (POST-create defaulting to 200, DELETE to 200+body)
  http-exception-deep   raise HTTPException outside a route function or
                        exception handler — HTTP policy in the service layer
  swallowed-exception   broad except inside a route body that neither
                        re-raises nor raises HTTPException — errors become
                        fake responses
  blocking-in-async     known-blocking call (requests.*, time.sleep,
                        urllib, subprocess, boto3, smtplib) inside an
                        `async def` — stalls the event loop
  dict-body             route parameter annotated dict/Dict/Any — the
                        request boundary parses nothing
  undocumented-route    route with no summary=/description= kwarg and no
                        docstring — OpenAPI shows nothing to consumers
  module-level-client   engine/session/HTTP client constructed at module
                        top level — invisible to dependency_overrides
  env-in-logic          os.environ / os.getenv outside settings/entrypoint
                        code — config scattered instead of parsed once
  nondeterminism        datetime.now/today, time.time, uuid4, random.*
                        inside non-entrypoint functions — hidden inputs

Exit codes: 0 = clean, 1 = findings, 2 = a file could not be parsed.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
ENTRYPOINT_NAMES = {"main", "cli", "run", "entrypoint", "create_app",
                    "get_settings", "lifespan"}

NONDET_CALLS = {
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
    ("date", "today"), ("time", "time"), ("time", "monotonic"),
    ("uuid", "uuid4"), ("uuid", "uuid1"),
}
NONDET_MODULES = {"random"}

BLOCKING_CALLS = {"time.sleep", "urllib.request.urlopen", "subprocess.run",
                  "subprocess.call", "subprocess.check_output",
                  "subprocess.check_call", "socket.create_connection"}
BLOCKING_MODULES = {"requests", "boto3", "smtplib", "ftplib", "pyodbc",
                    "pymssql", "oracledb", "cx_Oracle", "psycopg2"}

CLIENT_CONSTRUCTORS = {
    "create_engine", "create_async_engine",
    "requests.Session", "httpx.Client", "httpx.AsyncClient",
    "boto3.client", "boto3.resource", "redis.Redis", "Redis",
    "MongoClient", "pymongo.MongoClient", "KafkaProducer", "KafkaConsumer",
    "pyodbc.connect", "pymssql.connect", "oracledb.connect",
    "cx_Oracle.connect", "psycopg2.connect",
}

DICT_ANNOTATIONS = {"dict", "Dict", "Any"}


@dataclass
class Finding:
    path: str
    line: int
    check: str
    message: str


def dotted(node: ast.AST) -> str:
    """Best-effort dotted name for a call target: 'requests.get', 'open'."""
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


def route_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Call | None:
    """The @x.<method>("/path") decorator call, if this function is a route."""
    for dec in func.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in HTTP_METHODS
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str)
        ):
            return dec
    return None


def is_exception_handler(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in func.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr == "exception_handler":
            return True
    return False


def kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def annotation_name(node: ast.expr | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):  # Dict[str, Any] -> Dict
        return annotation_name(node.value)
    if isinstance(node, ast.Attribute):  # typing.Any -> Any
        return node.attr
    return ""


def check_route(func: ast.FunctionDef | ast.AsyncFunctionDef, dec: ast.Call,
                path: str, findings: list[Finding]) -> None:
    method = dec.func.attr if isinstance(dec.func, ast.Attribute) else "?"
    label = f"{method.upper()} route {func.name}()"

    status_kw = kwarg(dec, "status_code")
    status_204 = (
        isinstance(status_kw, ast.Constant) and status_kw.value == 204
    ) or (isinstance(status_kw, ast.Attribute)
          and "204" in status_kw.attr)

    if (func.returns is None and kwarg(dec, "response_model") is None
            and kwarg(dec, "response_class") is None and not status_204):
        findings.append(Finding(
            path, func.lineno, "untyped-response",
            f"{label} declares no return annotation and no response_model — "
            "the response contract is undeclared and unfiltered",
        ))

    if method in ("post", "delete") and status_kw is None:
        findings.append(Finding(
            path, dec.lineno, "implicit-status",
            f"{label} has no explicit status_code= — defaults to 200 "
            f"({'201 for create' if method == 'post' else '204 for delete'} "
            "is usually right)",
        ))

    has_summary = kwarg(dec, "summary") is not None or kwarg(dec, "description") is not None
    if not has_summary and ast.get_docstring(func) is None:
        findings.append(Finding(
            path, func.lineno, "undocumented-route",
            f"{label} has no summary/description and no docstring — "
            "OpenAPI documents nothing for consumers",
        ))

    for arg in func.args.args + func.args.kwonlyargs:
        if annotation_name(arg.annotation) in DICT_ANNOTATIONS:
            findings.append(Finding(
                path, arg.lineno if hasattr(arg, "lineno") else func.lineno,
                "dict-body",
                f"parameter `{arg.arg}` of {label} is annotated "
                f"{annotation_name(arg.annotation)} — nothing is parsed or "
                "documented at the boundary",
            ))

    for node in ast.walk(func):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            broad = handler.type is None or (
                isinstance(handler.type, ast.Name)
                and handler.type.id in ("Exception", "BaseException")
            )
            if broad and not any(isinstance(n, ast.Raise)
                                 for n in ast.walk(handler)):
                findings.append(Finding(
                    path, handler.lineno, "swallowed-exception",
                    f"broad except in {label} that never re-raises — a crash "
                    "becomes a hand-built response instead of reaching the "
                    "500 handler",
                ))


def check_function(func: ast.FunctionDef | ast.AsyncFunctionDef, path: str,
                   findings: list[Finding], *, is_route: bool) -> None:
    entry = func.name in ENTRYPOINT_NAMES or func.name.startswith("_main")
    is_async = isinstance(func, ast.AsyncFunctionDef)

    for node in ast.walk(func):
        if isinstance(node, ast.Raise) and not is_route and not is_exception_handler(func):
            target = node.exc
            if isinstance(target, ast.Call):
                target = target.func
            name = dotted(target) if target is not None else ""
            if name.endswith("HTTPException"):
                findings.append(Finding(
                    path, node.lineno, "http-exception-deep",
                    f"HTTPException raised in {func.name}(), which is not a "
                    "route — HTTP policy belongs at the edge; raise a domain "
                    "exception and map it in one handler",
                ))
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            head, _, tail = name.rpartition(".")
            head_root = head.split(".")[0] if head else ""
            if is_async and (name in BLOCKING_CALLS
                             or head_root in BLOCKING_MODULES
                             or name.split(".")[0] in BLOCKING_MODULES):
                findings.append(Finding(
                    path, node.lineno, "blocking-in-async",
                    f"{name}() inside async {func.name}() — blocks the event "
                    "loop for every in-flight request",
                ))
            if not entry:
                pair = (head_root or head, tail)
                if pair in NONDET_CALLS or head_root in NONDET_MODULES:
                    findings.append(Finding(
                        path, node.lineno, "nondeterminism",
                        f"{name}() inside {func.name}() — a hidden input; "
                        "inject it (Depends or parameter) instead",
                    ))
                if name in ("os.getenv", "os.environ.get"):
                    findings.append(Finding(
                        path, node.lineno, "env-in-logic",
                        f"environment read inside {func.name}() — parse "
                        "settings once at startup and inject them",
                    ))
        if (isinstance(node, ast.Subscript)
                and dotted(node.value) == "os.environ" and not entry):
            findings.append(Finding(
                path, node.lineno, "env-in-logic",
                f"os.environ[...] inside {func.name}() — parse settings "
                "once at startup and inject them",
            ))


def check_module_level(tree: ast.Module, path: str,
                       findings: list[Finding]) -> None:
    for node in tree.body:
        values: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            values = [node.value]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            values = [node.value]
        for value in values:
            if isinstance(value, ast.Call):
                name = dotted(value.func)
                if name in CLIENT_CONSTRUCTORS or name.split(".")[-1] in (
                        "create_engine", "create_async_engine"):
                    findings.append(Finding(
                        path, value.lineno, "module-level-client",
                        f"{name}(...) at module top level — constructed at "
                        "import time, invisible to dependency_overrides; "
                        "build it in the app factory / a dependency",
                    ))


def scan_file(path: Path) -> tuple[list[Finding], bool]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [Finding(str(path), getattr(exc, "lineno", 1) or 1,
                        "parse-error", f"could not parse: {exc}")], True
    findings: list[Finding] = []
    rel = str(path)
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dec = route_decorator(func)
        if dec is not None:
            check_route(func, dec, rel, findings)
        check_function(func, rel, findings, is_route=dec is not None)
    check_module_level(tree, rel, findings)
    return findings, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan FastAPI service code for contract, exception-"
        "handling, and testability smells. Prints file:line: [check] "
        "message, one per finding. Findings are leads, not verdicts.",
    )
    parser.add_argument("paths", nargs="+", type=Path,
                        help="files or directories to scan (dirs walked "
                        "recursively for *.py; venvs, tests/, and hidden "
                        "dirs skipped)")
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
                           ("venv", ".venv", "node_modules", "__pycache__",
                            "build", "dist", "tests", "test")
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
