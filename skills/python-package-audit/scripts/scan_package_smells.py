#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Static smell scan for Python packages/libraries.

Checks pyproject.toml dependency declarations and walks package source for
patterns that make a library brittle for its consumers: undeclared or
over-constrained dependencies, import-time side effects, an accidental
public API, self-configuration. Findings are LEADS for a human/agent
audit, not verdicts — every finding needs a judgment call before it goes
in a refactoring plan.

Checks (id — what it flags):
  pinned-dep            == pin in [project].dependencies — a library
                        dictating exact versions to every consumer
  upper-cap             <, <=, ~= upper bound in runtime deps — blanket
                        caps that create unresolvable conflicts downstream
  unbounded-dep         runtime dep with no lower bound — untested claim
                        of compatibility with every version ever released
  dev-dep-in-runtime    pytest/ruff/mypy-style tooling in runtime deps
  missing-requires-python  no requires-python in [project]
  missing-py-typed      package ships annotations but no py.typed marker
  module-side-effect    executable statement at module top level — runs
                        on import (try/except ImportError exempted)
  module-level-client   engine/session/HTTP client constructed at import
  logging-config        logging.basicConfig or addHandler (non-Null) in
                        library code — configuring the consumer's logging
  env-read              os.environ / os.getenv inside the library —
                        self-configuration instead of parameters
  print-in-library      print() outside __main__/cli modules
  star-import           from x import *
  missing-all           public __init__.py re-exports names but defines
                        no __all__
  untyped-public        public function in a public module missing
                        parameter or return annotations
  swallowed-exception   broad except that neither re-raises nor returns
                        a typed failure — errors vanish inside the library
  generic-exception     raise Exception(...) — consumers cannot catch it
                        without catching everything
  global-state          `global` statement — mutable module state

Exit codes: 0 = clean, 1 = findings, 2 = a file/pyproject could not be parsed.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

DEV_TOOLS = {"pytest", "ruff", "mypy", "basedpyright", "pyright", "black",
             "flake8", "isort", "pylint", "pre-commit", "coverage",
             "pytest-cov", "tox", "nox", "pip-tools", "build", "twine"}

CLIENT_CONSTRUCTORS = {
    "create_engine", "create_async_engine",
    "requests.Session", "httpx.Client", "httpx.AsyncClient",
    "boto3.client", "boto3.resource", "redis.Redis",
    "MongoClient", "pymongo.MongoClient", "KafkaProducer", "KafkaConsumer",
    "pyodbc.connect", "pymssql.connect", "oracledb.connect",
    "cx_Oracle.connect", "psycopg2.connect",
}

CLI_MODULE_NAMES = {"cli", "__main__", "main", "console"}


@dataclass
class Finding:
    path: str
    line: int
    check: str
    message: str


def dotted(node: ast.AST) -> str:
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


# ---------- pyproject checks ----------

REQ_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(\[[^\]]*\])?\s*(.*)$")


def check_pyproject(pyproject: Path, findings: list[Finding]) -> None:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        findings.append(Finding(str(pyproject), 1, "parse-error",
                                f"could not parse pyproject.toml: {exc}"))
        return
    project = data.get("project", {})
    rel = str(pyproject)

    if "requires-python" not in project:
        findings.append(Finding(
            rel, 1, "missing-requires-python",
            "no requires-python in [project] — installers cannot refuse "
            "unsupported interpreters",
        ))

    for dep in project.get("dependencies", []):
        m = REQ_RE.match(dep)
        if not m:
            continue
        name, _, spec = m.groups()
        spec = spec.split(";")[0].strip()  # drop environment markers
        if name.lower().replace("_", "-") in DEV_TOOLS:
            findings.append(Finding(
                rel, 1, "dev-dep-in-runtime",
                f"`{name}` in [project].dependencies — development tooling "
                "installed into every consumer's environment",
            ))
        clauses = [c.strip() for c in spec.split(",") if c.strip()]
        if any(c.startswith("==") and not c.startswith("===") or
               c.startswith("~=") for c in clauses):
            findings.append(Finding(
                rel, 1, "pinned-dep",
                f"`{dep}` — exact/compatible-release pin in a library; "
                "consumers cannot resolve alongside other pins",
            ))
        elif any(c.startswith("<") for c in clauses):
            findings.append(Finding(
                rel, 1, "upper-cap",
                f"`{dep}` — blanket upper bound; only cap on a known, "
                "documented incompatibility",
            ))
        if spec.startswith("(") or not any(
                c.startswith((">=", ">", "==", "~=")) for c in clauses):
            findings.append(Finding(
                rel, 1, "unbounded-dep",
                f"`{dep}` — no lower bound; the oldest version that "
                "actually works is undeclared and untested",
            ))


def check_py_typed(pkg_dirs: list[Path], findings: list[Finding]) -> None:
    for pkg in pkg_dirs:
        if not (pkg / "py.typed").exists():
            findings.append(Finding(
                str(pkg), 1, "missing-py-typed",
                f"package `{pkg.name}` has no py.typed marker — consumers' "
                "type checkers treat every annotation as missing (PEP 561)",
            ))


# ---------- AST checks ----------

def is_public_module(path: Path) -> bool:
    return not any(part.startswith("_") and part != "__init__.py"
                   for part in path.parts)


def is_cli_module(path: Path) -> bool:
    stem = path.stem.lower()
    return stem in CLI_MODULE_NAMES or stem.endswith("_cli")


def handler_catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        names: list[str] = []
        t = handler.type
        if isinstance(t, ast.Name):
            names = [t.id]
        elif isinstance(t, ast.Tuple):
            names = [e.id for e in t.elts if isinstance(e, ast.Name)]
        if any(n in ("ImportError", "ModuleNotFoundError") for n in names):
            return True
    return False


def check_module_level(tree: ast.Module, path: Path,
                       findings: list[Finding]) -> None:
    rel = str(path)
    is_init = path.name == "__init__.py"
    has_reexport = False
    has_all = False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            has_reexport = True
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets
                           if isinstance(t, ast.Name)]
            elif isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if "__all__" in targets:
                has_all = True
            value = getattr(node, "value", None)
            if isinstance(value, ast.Call):
                name = dotted(value.func)
                if name in CLIENT_CONSTRUCTORS or name.split(".")[-1] in (
                        "create_engine", "create_async_engine"):
                    findings.append(Finding(
                        rel, value.lineno, "module-level-client",
                        f"{name}(...) at module top level — I/O client "
                        "constructed the moment anyone imports the package",
                    ))
            continue
        if isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"):
                continue
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                continue
            if (isinstance(test, ast.Attribute)
                    and test.attr == "TYPE_CHECKING"):
                continue
        if isinstance(node, ast.Try) and handler_catches_import_error(node):
            continue  # optional-dependency import guard
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        findings.append(Finding(
            rel, node.lineno, "module-side-effect",
            f"{type(node).__name__} at module top level — executes on "
            "import; importing a library must be free",
        ))
    if is_init and is_public_module(path) and has_reexport and not has_all:
        findings.append(Finding(
            rel, 1, "missing-all",
            "__init__.py re-exports names but defines no __all__ — the "
            "public surface is whatever happens to be importable",
        ))


def check_functions(tree: ast.AST, path: Path,
                    findings: list[Finding]) -> None:
    rel = str(path)
    public_module = is_public_module(path)
    cli = is_cli_module(path)
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        public_func = not func.name.startswith("_")
        if public_module and public_func:
            args = func.args.args + func.args.kwonlyargs + func.args.posonlyargs
            missing = [a.arg for a in args
                       if a.annotation is None and a.arg not in ("self", "cls")]
            if missing or func.returns is None:
                what = (f"params {', '.join(missing)}" if missing else
                        "return type")
                findings.append(Finding(
                    rel, func.lineno, "untyped-public",
                    f"public {func.name}() missing annotations ({what}) — "
                    "the interface is undeclared for consumers and checkers",
                ))
        for node in ast.walk(func):
            if isinstance(node, ast.Global):
                findings.append(Finding(
                    rel, node.lineno, "global-state",
                    f"`global {', '.join(node.names)}` in {func.name}() — "
                    "mutable module state shared across consumers",
                ))
            if isinstance(node, ast.Raise):
                target = node.exc
                if isinstance(target, ast.Call):
                    target = target.func
                if isinstance(target, ast.Name) and target.id == "Exception":
                    findings.append(Finding(
                        rel, node.lineno, "generic-exception",
                        f"raise Exception(...) in {func.name}() — consumers "
                        "cannot catch this without catching everything; "
                        "raise a package exception type",
                    ))
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if name in ("os.getenv", "os.environ.get"):
                    findings.append(Finding(
                        rel, node.lineno, "env-read",
                        f"environment read inside {func.name}() — libraries "
                        "take config as parameters; the caller owns the env",
                    ))
                if name == "print" and not cli:
                    findings.append(Finding(
                        rel, node.lineno, "print-in-library",
                        f"print() in {func.name}() — use logging; stdout "
                        "belongs to the consumer",
                    ))


def check_everywhere(tree: ast.AST, path: Path,
                     findings: list[Finding]) -> None:
    rel = str(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
                a.name == "*" for a in node.names):
            findings.append(Finding(
                rel, node.lineno, "star-import",
                f"from {node.module} import * — the namespace (and public "
                "surface) depends on another module's contents",
            ))
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name == "logging.basicConfig":
                findings.append(Finding(
                    rel, node.lineno, "logging-config",
                    "logging.basicConfig() in library code — hijacks the "
                    "consumer's logging setup; libraries add NullHandler only",
                ))
            if name.endswith(".addHandler") and not any(
                    isinstance(a, ast.Call)
                    and dotted(a.func).endswith("NullHandler")
                    for a in node.args):
                findings.append(Finding(
                    rel, node.lineno, "logging-config",
                    "addHandler(...) in library code — libraries attach "
                    "NullHandler only; real handlers belong to the app",
                ))
        if isinstance(node, ast.Subscript) and dotted(node.value) == "os.environ":
            findings.append(Finding(
                rel, node.lineno, "env-read",
                "os.environ[...] in library code — libraries take config "
                "as parameters; the caller owns the env",
            ))
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
                    rel, handler.lineno, "swallowed-exception",
                    "broad except that never re-raises — the consumer can't "
                    "tell failure from success",
                ))


def scan_file(path: Path) -> tuple[list[Finding], bool]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [Finding(str(path), getattr(exc, "lineno", 1) or 1,
                        "parse-error", f"could not parse: {exc}")], True
    findings: list[Finding] = []
    check_module_level(tree, path, findings)
    check_functions(tree, path, findings)
    check_everywhere(tree, path, findings)
    return findings, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a Python package for dependency-declaration, "
        "public-API, and import-hygiene smells. Prints file:line: [check] "
        "message, one per finding. Findings are leads, not verdicts.",
    )
    parser.add_argument("paths", nargs="+", type=Path,
                        help="package source dirs or files (dirs walked "
                        "recursively for *.py; venvs, tests/, hidden dirs "
                        "skipped). If a dir contains pyproject.toml it is "
                        "checked too.")
    parser.add_argument("--json", action="store_true",
                        help="emit findings as a JSON array instead of text")
    parser.add_argument("--checks",
                        help="comma-separated check ids to include "
                        "(default: all)")
    args = parser.parse_args()

    files: list[Path] = []
    pyprojects: list[Path] = []
    pkg_dirs: set[Path] = set()
    for p in args.paths:
        if p.is_dir():
            if (p / "pyproject.toml").exists():
                pyprojects.append(p / "pyproject.toml")
            for f in sorted(p.rglob("*.py")):
                if any(part.startswith(".") or part in
                       ("venv", ".venv", "node_modules", "__pycache__",
                        "build", "dist", "tests", "test", "_vendor")
                       for part in f.parts):
                    continue
                files.append(f)
                if f.name == "__init__.py":
                    parent_init = f.parent.parent / "__init__.py"
                    if not parent_init.exists():
                        pkg_dirs.add(f.parent)  # top-level package dir
        elif p.is_file():
            if p.name == "pyproject.toml":
                pyprojects.append(p)
            else:
                files.append(p)
        else:
            print(f"error: {p} does not exist", file=sys.stderr)
            return 2

    seen: set[Path] = set()
    files = [f for f in files
             if (r := f.resolve()) not in seen and not seen.add(r)]
    pyprojects = list(dict.fromkeys(p.resolve() for p in pyprojects))

    if not files and not pyprojects:
        print("error: nothing to scan under the given paths",
              file=sys.stderr)
        return 2

    only = set(args.checks.split(",")) if args.checks else None
    all_findings: list[Finding] = []
    parse_failed = False
    for pj in pyprojects:
        found: list[Finding] = []
        check_pyproject(pj, found)
        parse_failed = parse_failed or any(
            f.check == "parse-error" for f in found)
        all_findings.extend(found)
    check_py_typed(sorted(pkg_dirs), all_findings)
    for f in files:
        findings, failed = scan_file(f)
        parse_failed = parse_failed or failed
        all_findings.extend(findings)
    if only is not None:
        all_findings = [fi for fi in all_findings if fi.check in only]

    all_findings.sort(key=lambda fi: (fi.path, fi.line))
    if args.json:
        print(json.dumps([asdict(fi) for fi in all_findings], indent=2))
    else:
        for fi in all_findings:
            print(f"{fi.path}:{fi.line}: [{fi.check}] {fi.message}")
        print(f"\n{len(all_findings)} finding(s)", file=sys.stderr)

    if parse_failed:
        return 2
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
