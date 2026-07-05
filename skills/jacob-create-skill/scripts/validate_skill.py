#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Validate an agent skill folder against the agentskills.io spec and house rules.

Errors (exit 1) are spec violations; warnings encode house rules — address or
consciously accept each one.

Usage: validate_skill.py <skill-dir> [<skill-dir> ...]
"""

import argparse
import re
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# core spec + Cursor extensions + Claude Code extensions
KNOWN_FIELDS = {
    "name", "description", "license", "compatibility", "metadata", "allowed-tools",
    "paths", "disable-model-invocation",
    "model", "effort", "context", "agent", "hooks", "argument-hint", "user-invocable",
}
LOCAL_REF_RE = re.compile(r"\b((?:scripts|references|assets)/[A-Za-z0-9_.\-/]+)")
BODY_WARN_LINES = 300
BODY_MAX_LINES = 500
DESCRIPTION_MAX = 1024
ROUTER_VISIBLE_CHARS = 250


def parse_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """Return (frontmatter, body, error)."""
    if not text.startswith("---\n"):
        return None, text, "SKILL.md does not start with '---' frontmatter"
    end = text.find("\n---", 4)
    if end == -1:
        return None, text, "frontmatter is not closed with '---'"
    raw = text[4:end]
    body = text[end + 4:].lstrip("\n")
    try:
        fm = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return None, body, f"frontmatter is not valid YAML: {e}"
    if not isinstance(fm, dict):
        return None, body, "frontmatter is not a YAML mapping"
    return fm, body, None


def validate(skill_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"no SKILL.md in {skill_dir}"], []

    fm, body, fm_error = parse_frontmatter(skill_md.read_text())
    if fm_error:
        errors.append(fm_error)
    fm = fm or {}

    name = fm.get("name")
    if not name:
        errors.append("frontmatter missing required field: name")
    else:
        if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 64:
            errors.append(f"invalid name {name!r}: need lowercase alphanumerics/hyphens, max 64 chars")
        if name != skill_dir.resolve().name:
            errors.append(f"name {name!r} does not match folder name {skill_dir.resolve().name!r}")

    desc = fm.get("description")
    if not desc or not isinstance(desc, str) or not desc.strip():
        errors.append("frontmatter missing required field: description")
    else:
        if len(desc) > DESCRIPTION_MAX:
            errors.append(f"description is {len(desc)} chars (max {DESCRIPTION_MAX})")
        if len(desc) < 60:
            warnings.append("description under 60 chars — likely too thin to route on")
        lowered = desc.lower()
        use_when = lowered.find("use when")
        if use_when == -1:
            warnings.append("description has no 'Use when ...' clause — write it as a trigger, not a summary")
        elif use_when > ROUTER_VISIBLE_CHARS:
            warnings.append(f"'Use when' starts at char {use_when} — routers may only show the first {ROUTER_VISIBLE_CHARS}")

    for field in fm:
        if field not in KNOWN_FIELDS:
            warnings.append(f"unknown frontmatter field {field!r} — agents will ignore it silently")

    if fm.get("disable-model-invocation") is not True:
        warnings.append(
            "disable-model-invocation is not true — house default is explicit-invoke only; "
            "confirm the user actually asked for auto-triggering"
        )

    body_lines = body.count("\n") + 1 if body else 0
    if body_lines > BODY_MAX_LINES:
        errors.append(f"body is {body_lines} lines (hard limit {BODY_MAX_LINES}; accuracy degrades)")
    elif body_lines > BODY_WARN_LINES:
        warnings.append(f"body is {body_lines} lines (house target < {BODY_WARN_LINES}) — move detail to references/")

    for ref in sorted(set(LOCAL_REF_RE.findall(body))):
        if "<" in ref or ">" in ref:
            continue
        if not (skill_dir / ref).exists():
            warnings.append(f"body references {ref} but the file does not exist (ok if it's a generic example)")

    for py in sorted(skill_dir.rglob("*.py")):
        head = py.read_text().splitlines()[:15]
        if not any("/// script" in line for line in head):
            errors.append(f"{py.relative_to(skill_dir)} lacks a PEP 723 '# /// script' header — skill scripts must be self-contained")

    if not (skill_dir / "LEARNINGS.md").is_file():
        warnings.append("no LEARNINGS.md — the skill has no learnings loop")
    if "learnings.md" not in body.lower():
        warnings.append("body never mentions LEARNINGS.md — agents won't read or update it")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skill_dirs", nargs="+", type=Path, help="skill folder(s) to validate")
    args = parser.parse_args()

    exit_code = 0
    for skill_dir in args.skill_dirs:
        errors, warnings = validate(skill_dir)
        print(f"\n{skill_dir}")
        for e in errors:
            print(f"  ERROR: {e}")
        for w in warnings:
            print(f"  WARN:  {w}")
        if not errors and not warnings:
            print("  OK")
        elif not errors:
            print(f"  OK with {len(warnings)} warning(s)")
        else:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
