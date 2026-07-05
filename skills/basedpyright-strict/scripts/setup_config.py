#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tomlkit"]
# ///
"""Write [tool.basedpyright] recommended config into a repo's pyproject.toml.

Refuses (exit 2) when type-checker config already exists — a pyrightconfig.json
(which silently takes precedence over pyproject.toml) or an existing
[tool.basedpyright]/[tool.pyright] table — so an agent reconciles by hand
instead of clobbering someone's settings.
"""

import argparse
from pathlib import Path

import tomlkit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".", help="repo root (default: cwd)")
    parser.add_argument("--mode", default="recommended", choices=["recommended", "strict", "all", "standard"],
                        help="typeCheckingMode to set (default: recommended)")
    args = parser.parse_args()

    root = Path(args.project)
    pyrightconfig = root / "pyrightconfig.json"
    if pyrightconfig.exists():
        print(f"exit 2: {pyrightconfig} exists and takes precedence over pyproject.toml.")
        print("Reconcile: move its settings into [tool.basedpyright] and delete it, or configure there instead.")
        return 2

    pyproject = root / "pyproject.toml"
    doc = tomlkit.parse(pyproject.read_text()) if pyproject.exists() else tomlkit.document()
    tool = doc.get("tool", {})
    for existing in ("basedpyright", "pyright"):
        if existing in tool:
            print(f"exit 2: [tool.{existing}] already exists in {pyproject}:")
            print(tomlkit.dumps({existing: tool[existing]}))
            print(f"Edit it by hand; keep typeCheckingMode = \"{args.mode}\".")
            return 2

    if "tool" not in doc:
        doc["tool"] = tomlkit.table(is_super_table=True)
    section = tomlkit.table()
    section["typeCheckingMode"] = args.mode
    doc["tool"]["basedpyright"] = section
    pyproject.write_text(tomlkit.dumps(doc))
    print(f"wrote [tool.basedpyright] typeCheckingMode = \"{args.mode}\" to {pyproject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
