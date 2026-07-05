#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Audit a pytest suite for tests that don't earn their keep.

Mechanical checks (AST-based, no imports of the code under test):

  CANNOT_FAIL   test function contains no assert, no pytest.raises, and no
                assert_* call — it passes no matter what the code does.
  MOCK_ECHO     every assertion in the test only checks mock wiring
                (assert_called*, call_count/call_args, or comparisons
                against a mock's return_value) — the test asserts that the
                mock returns what the mock was told to return.
  FOREIGN_PATCH mock.patch / mocker.patch / monkeypatch.setattr targets a
                module you don't own (not first-party) — brittle and
                forbidden by the house rules; wrap it in a gateway instead.
  ORPHAN_FIXTURE a file under a fixtures/ directory that no test source
                references — unvalidated fixtures rot silently.

Exit codes: 0 = clean, 1 = findings, 2 = usage error.

Typical use:
  uv run audit_tests.py tests/
  uv run audit_tests.py tests/ --first-party mypkg --first-party shared_lib
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MOCK_FACTORIES = {"Mock", "MagicMock", "AsyncMock", "PropertyMock", "create_autospec"}
MOCK_INTERACTION_ATTRS = {"call_count", "call_args", "call_args_list", "called",
                          "await_count", "await_args", "await_args_list",
                          "return_value", "side_effect", "mock_calls"}
# stdlib/typing roots that are fine to monkeypatch in a pinch and shouldn't
# be reported as "foreign" even though they aren't first-party
PATCH_ALLOWLIST_ROOTS = {"os", "sys", "time", "builtins"}


@dataclass
class Finding:
    check: str
    path: Path
    line: int
    message: str


@dataclass
class TestFunctionInfo:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    mock_names: set[str] = field(default_factory=set)
    asserts: list[ast.Assert] = field(default_factory=list)
    has_raises: bool = False
    assert_calls: list[ast.Call] = field(default_factory=list)  # foo.assert_*(...)


def is_test_file(path: Path) -> bool:
    return path.suffix == ".py" and (
        path.name.startswith("test_") or path.name.endswith("_test.py")
    )


def dotted_root(node: ast.expr) -> str | None:
    """Root name of an attribute chain: a.b.c -> 'a'."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def collect_mock_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names bound (directly or via attribute access) to mock objects."""
    mocks: set[str] = set()
    # two passes so `b = a.return_value` after `a = Mock()` is caught
    for _ in range(2):
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            is_mock = False
            if isinstance(value, ast.Call):
                func = value.func
                name = func.attr if isinstance(func, ast.Attribute) else (
                    func.id if isinstance(func, ast.Name) else None)
                if name in MOCK_FACTORIES or name == "patch":
                    is_mock = True
                # mocker.Mock() / mocker.patch.object(...)
                if isinstance(func, ast.Attribute) and dotted_root(func) == "mocker":
                    is_mock = True
            root = dotted_root(value) if isinstance(value, (ast.Attribute, ast.Name)) else None
            if root in mocks:
                is_mock = True
            if is_mock:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        mocks.add(target.id)
                    elif isinstance(target, ast.Tuple):
                        mocks.update(e.id for e in target.elts if isinstance(e, ast.Name))
    return mocks


def analyze_test(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> TestFunctionInfo:
    info = TestFunctionInfo(node=fn, mock_names=collect_mock_names(fn))
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            info.asserts.append(node)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr == "raises":  # pytest.raises(...)
                    info.has_raises = True
                elif func.attr.startswith("assert"):  # m.assert_called_once_with / pd assert helpers
                    info.assert_calls.append(node)
            elif isinstance(func, ast.Name) and func.id.startswith("assert"):
                info.assert_calls.append(node)
        elif isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute) \
                        and ctx.func.attr == "raises":
                    info.has_raises = True
    return info


def assertion_is_mock_interaction(node: ast.Assert | ast.Call, mocks: set[str]) -> bool:
    """True if this assertion only checks mock wiring."""
    if isinstance(node, ast.Call):  # foo.assert_called_once_with(...)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr.startswith("assert_"):
            return dotted_root(func) in mocks
        return False
    # plain `assert <expr>`: interaction-only if it touches call_count /
    # return_value / etc. of a mock, or compares nothing but mock-derived names
    touches_mock_meta = False
    non_mock_name_used = False
    for sub in ast.walk(node.test):
        if isinstance(sub, ast.Attribute) and sub.attr in MOCK_INTERACTION_ATTRS \
                and dotted_root(sub) in mocks:
            touches_mock_meta = True
        if isinstance(sub, ast.Name) and sub.id not in mocks:
            non_mock_name_used = True
    return touches_mock_meta or not non_mock_name_used


def detect_first_party(tests_dir: Path) -> set[str]:
    """Infer first-party package names from pyproject + src layout."""
    names: set[str] = set()
    for parent in [tests_dir, *tests_dir.parents]:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text())
                project_name = data.get("project", {}).get("name")
                if project_name:
                    names.add(project_name.replace("-", "_"))
            except tomllib.TOMLDecodeError:
                pass
            src = parent / "src"
            roots = [src] if src.is_dir() else [parent]
            for root in roots:
                for child in root.iterdir():
                    if child.is_dir() and (child / "__init__.py").is_file():
                        names.add(child.name)
            break
    return names


def audit_file(path: Path, first_party: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as exc:
        return [Finding("PARSE_ERROR", path, exc.lineno or 0, f"could not parse: {exc.msg}")]

    for node in ast.walk(tree):
        # FOREIGN_PATCH applies anywhere in the file, fixtures included
        if isinstance(node, ast.Call) and node.args:
            is_patch_call = (
                (isinstance(node.func, ast.Attribute) and node.func.attr in {"patch", "setattr"})
                or (isinstance(node.func, ast.Name) and node.func.id == "patch"))
            target = node.args[0]
            if is_patch_call and isinstance(target, ast.Constant) \
                    and isinstance(target.value, str) and "." in target.value:
                root = target.value.split(".")[0]
                if root not in first_party and root not in PATCH_ALLOWLIST_ROOTS:
                    findings.append(Finding(
                        "FOREIGN_PATCH", path, node.lineno,
                        f'patches "{target.value}" — not first-party; '
                        f"wrap it in a gateway module and fake that instead"))

        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue

        info = analyze_test(node)
        if not info.asserts and not info.assert_calls and not info.has_raises:
            findings.append(Finding(
                "CANNOT_FAIL", path, node.lineno,
                f"{node.name} has no assert / pytest.raises — it can never fail"))
            continue

        assertions: list[ast.Assert | ast.Call] = [*info.asserts, *info.assert_calls]
        if assertions and info.mock_names and all(
                assertion_is_mock_interaction(a, info.mock_names) for a in assertions):
            findings.append(Finding(
                "MOCK_ECHO", path, node.lineno,
                f"{node.name}: every assertion checks mock wiring — the test "
                f"verifies the mock, not the code; assert on results/state"))
    return findings


def audit_fixture_orphans(tests_dir: Path) -> list[Finding]:
    fixture_files = [p for p in tests_dir.rglob("*")
                     if p.is_file() and "fixtures" in p.parts and p.suffix != ".py"]
    if not fixture_files:
        return []
    literals: set[str] = set()
    for source in tests_dir.rglob("*.py"):
        try:
            tree = ast.parse(source.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
    findings = []
    for fixture in fixture_files:
        name = fixture.name
        referenced = any(
            name in lit or (("*" in lit or "?" in lit) and fnmatch.fnmatch(name, lit))
            for lit in literals)
        if not referenced:
            findings.append(Finding(
                "ORPHAN_FIXTURE", fixture, 0,
                "no test references this fixture file — delete it or add a "
                "schema-validation test that loads it"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tests_dir", type=Path, help="directory containing the test suite")
    parser.add_argument("--first-party", action="append", default=[],
                        help="package name to treat as first-party (repeatable); "
                             "auto-detected from pyproject.toml/src layout if omitted")
    args = parser.parse_args()

    tests_dir = args.tests_dir.resolve()
    if not tests_dir.is_dir():
        parser.error(f"{tests_dir} is not a directory")

    first_party = set(args.first_party) or detect_first_party(tests_dir)
    if not first_party:
        print("warning: could not detect first-party packages; every patch() "
              "target will be reported — pass --first-party to fix", file=sys.stderr)

    findings: list[Finding] = []
    for path in sorted(tests_dir.rglob("*.py")):
        if is_test_file(path) or path.name == "conftest.py":
            findings.extend(audit_file(path, first_party))
    findings.extend(audit_fixture_orphans(tests_dir))

    if not findings:
        print(f"clean: no findings in {tests_dir}")
        return 0

    findings.sort(key=lambda f: (f.check, str(f.path), f.line))
    current = None
    for f in findings:
        if f.check != current:
            current = f.check
            print(f"\n== {f.check} ==")
        loc = f"{f.path}:{f.line}" if f.line else str(f.path)
        print(f"  {loc}\n    {f.message}")
    print(f"\n{len(findings)} finding(s). Each needs a verdict: delete, rewrite, or keep (with reason).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
