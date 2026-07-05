#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Scaffold a new agent skill folder.

Creates <dir>/<name>/ with a SKILL.md template (valid frontmatter, house-rule
section placeholders, learnings-loop block) and a seeded LEARNINGS.md.
"""

import argparse
import json
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
{invocation_line}---

# {title}

<!-- One paragraph: what this skill does and the standard it follows. -->

## When to use

<!-- Concrete trigger contexts. Mirror the description's "Use when" phrases. -->

## Workflow

<!-- Imperative steps. Deterministic work goes in scripts/ (uv + PEP 723);
     judgment stays here as prose. State for each script whether the agent
     should RUN it or READ it. -->

## Example

<!-- One complete, realistic input -> output example. -->

## Bundled resources

<!-- - `scripts/<x>.py` — run to ...
     - `references/<x>.md` — read when ... -->

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use, if the user corrected you or the
outcome surprised you, append one dated line to `LEARNINGS.md`:
`- YYYY-MM-DD: <what happened> → <what to do instead>`. Do not edit SKILL.md
directly; lessons are folded in deliberately, not on the fly.
"""

LEARNINGS_TEMPLATE = """\
# Learnings

Dated corrections from real use of this skill. Read before executing;
fold recurring/confirmed entries into SKILL.md and delete them here.

Format: `- YYYY-MM-DD: <what happened> → <what to do instead>`

(no entries yet)
"""

DEFAULT_DESCRIPTION = (
    "TODO — write as a trigger, not a summary: what it does, then "
    "'Use when ...' with the concrete phrases a user would type. "
    "Front-load everything important into the first 250 characters."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="skill name: lowercase letters, digits, hyphens; max 64 chars")
    parser.add_argument("--dir", default="skills", help="skills root to create the folder in (default: ./skills)")
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION, help="frontmatter description (trigger-style)")
    parser.add_argument(
        "--auto-trigger", action="store_true",
        help="omit disable-model-invocation (house default is explicit-invoke only); "
        "pass this only when the user asked for automatic triggering",
    )
    args = parser.parse_args()

    if not NAME_RE.match(args.name) or len(args.name) > 64:
        print(f"error: invalid name {args.name!r} — need ^[a-z0-9]+(-[a-z0-9]+)*$, max 64 chars", file=sys.stderr)
        return 1

    skill_dir = Path(args.dir) / args.name
    if skill_dir.exists():
        print(f"error: {skill_dir} already exists", file=sys.stderr)
        return 1

    skill_dir.mkdir(parents=True)
    title = args.name.replace("-", " ").capitalize()
    invocation_line = "" if args.auto_trigger else "disable-model-invocation: true\n"
    (skill_dir / "SKILL.md").write_text(
        # json.dumps produces a YAML-safe double-quoted scalar
        SKILL_TEMPLATE.format(
            name=args.name, description=json.dumps(args.description), title=title, invocation_line=invocation_line
        )
    )
    (skill_dir / "LEARNINGS.md").write_text(LEARNINGS_TEMPLATE)

    print(f"created {skill_dir}/")
    print(f"  SKILL.md      — fill in the TODO sections, keep the body under 300 lines")
    print(f"  LEARNINGS.md  — seeded empty")
    print(
        "  invocation    — explicit only (disable-model-invocation: true)" if not args.auto_trigger
        else "  invocation    — auto-trigger enabled (--auto-trigger passed)"
    )
    print("next: draft, then validate with scripts/validate_skill.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
