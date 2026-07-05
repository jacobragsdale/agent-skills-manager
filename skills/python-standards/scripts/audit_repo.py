#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Audit a Python repo for migration to the uv house standard.

Reports, as a migration worklist:
  - legacy packaging files (requirements*.txt, setup.py, Pipfile, ...)
  - custom setup scripts (shell scripts / Makefile targets that pip install)
  - pyproject.toml state (deps, requires-python, [project.scripts], [tool.uv])
  - entry-point candidates (__main__ blocks, Procfile, Dockerfile CMD)
  - env vars read in code vs. what .env.example declares
  - .env files present and whether .gitignore covers them

Read-only; never modifies the repo. Exits 1 if the path is not a directory.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".ruff_cache", "dist", "build", ".eggs"}

LEGACY_GLOBS = [
    "requirements*.txt", "requirements/*.txt", "setup.py", "setup.cfg",
    "Pipfile", "Pipfile.lock", "environment.yml", "environment.yaml",
    "poetry.lock", "conda-lock.yml", "tox.ini",
]

ENV_READ_RE = re.compile(
    r"""os\.environ(?:\.get)?\s*[\[\(]\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|os\.getenv\s*\(\s*["']([A-Z][A-Z0-9_]*)["']"""
)
ENV_FILE_VAR_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)
PIP_RE = re.compile(r"\b(pip3?\s+install|easy_install|conda\s+(install|env)|virtualenv)\b")


def walk_files(root: Path, suffixes: set[str] | None = None):
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and (suffixes is None or path.suffix in suffixes):
            yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def section(title: str, lines: list[str], empty_msg: str) -> None:
    print(f"\n== {title} ==")
    if lines:
        for line in lines:
            print(f"  {line}")
    else:
        print(f"  {empty_msg}")


def audit_pyproject(root: Path) -> None:
    pp = root / "pyproject.toml"
    if not pp.is_file():
        section("pyproject.toml", ["MISSING — create with `uv init --bare`"], "")
        return
    try:
        data = tomllib.loads(pp.read_text())
    except tomllib.TOMLDecodeError as e:
        section("pyproject.toml", [f"PARSE ERROR: {e}"], "")
        return
    proj = data.get("project", {})
    lines = [
        f"requires-python: {proj.get('requires-python', 'NOT SET')}",
        f"dependencies: {len(proj.get('dependencies', []))} declared",
        f"[project.scripts]: {', '.join(proj.get('scripts', {})) or 'none'}",
        f"[dependency-groups]: {', '.join(data.get('dependency-groups', {})) or 'none'}",
        f"[tool.uv] present: {'yes' if 'uv' in data.get('tool', {}) else 'no'}",
    ]
    if "poetry" in data.get("tool", {}):
        lines.append("WARNING: [tool.poetry] present — migrate to [project] and remove")
    for tool in ("ruff", "basedpyright", "pyright"):
        lines.append(f"[tool.{tool}] configured: {'yes' if tool in data.get('tool', {}) else 'no'}")
    section("pyproject.toml", lines, "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", nargs="?", default=".", help="repo root to audit (default: cwd)")
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1
    print(f"Auditing {root}")

    # Legacy packaging files
    legacy = sorted({p for g in LEGACY_GLOBS for p in root.glob(g)})
    section("Legacy packaging files (fold into pyproject.toml, then delete)",
            [str(p.relative_to(root)) for p in legacy], "none found")

    # Setup-ish scripts
    setup_scripts = []
    for p in walk_files(root, {".sh", ".bash", ""}):
        if p.suffix in {".sh", ".bash"} or p.name in {"Makefile", "makefile", "Justfile", "justfile"}:
            text = read_text(p)
            hits = sorted({m.group(1) or m.group(0) for m in PIP_RE.finditer(text)})
            if hits:
                setup_scripts.append(f"{p.relative_to(root)}  ({', '.join(hits)})")
    section("Custom setup scripts (re-express in pyproject, then delete)",
            setup_scripts, "none found")

    audit_pyproject(root)

    # Python pin
    pv = root / ".python-version"
    section(".python-version",
            [pv.read_text().strip() if pv.is_file() else "MISSING — run `uv python pin 3.11`"], "")

    # Entry-point candidates
    entries = []
    for p in walk_files(root, {".py"}):
        if 'if __name__ == "__main__"' in read_text(p) or "if __name__ == '__main__'" in read_text(p):
            entries.append(f"{p.relative_to(root)}  (__main__ block)")
    for name in ("Procfile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        f = root / name
        if f.is_file():
            for line in read_text(f).splitlines():
                if re.match(r"\s*(CMD|ENTRYPOINT|\w+:\s*\S)", line) and "python" in line:
                    entries.append(f"{name}: {line.strip()}")
    section("Entry-point candidates (each becomes one `uv run` command)",
            entries, "none found")

    # Env vars: code vs .env.example
    code_vars: set[str] = set()
    for p in walk_files(root, {".py"}):
        for m in ENV_READ_RE.finditer(read_text(p)):
            code_vars.add(m.group(1) or m.group(2))
    example = root / ".env.example"
    example_vars = set(ENV_FILE_VAR_RE.findall(read_text(example))) if example.is_file() else set()
    lines = [f"read in code: {', '.join(sorted(code_vars)) or 'none'}"]
    if example.is_file():
        missing = sorted(code_vars - example_vars)
        extra = sorted(example_vars - code_vars)
        if missing:
            lines.append(f"MISSING from .env.example: {', '.join(missing)}")
        if extra:
            lines.append(f"in .env.example but never read: {', '.join(extra)}")
        if not missing and not extra:
            lines.append(".env.example matches code")
    else:
        lines.append(".env.example MISSING — create it")
    section("Environment variables", lines, "")

    # .env files and gitignore coverage
    env_files = [p.name for p in sorted(root.glob(".env*")) if p.name != ".env.example"]
    gi = read_text(root / ".gitignore")
    covered = ".env" in gi
    lines = [f"local env files: {', '.join(env_files) or 'none'}",
             f".gitignore covers .env*: {'yes' if covered else 'NO — add .env / .env.* / !.env.example'}"]
    section(".env hygiene", lines, "")

    print("\nDone. Work the sections top to bottom (see SKILL.md workflow).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
