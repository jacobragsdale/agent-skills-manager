---
name: propose-skill
description: "Propose a new team skill (or an improvement to one) as a reviewed pull request to the team skills repo. Use when the user says 'propose a skill', 'add a team skill for X', 'share this workflow with the team', 'this should be a skill', or wants to contribute a skill without knowing the repo process. Do NOT use for building a personal or single-project skill (use agent-create-skill)."
metadata:
  author: jacob
---

# Propose a team skill

Turn a teammate's pain point into a reviewed PR against the team skills
repo — no git or process knowledge required from the user. All work happens
inside `~/.agents` (the managed clone of the team repo).

## Step 1 — Qualify and interview

Run Step 0 (library fit check) and the Step 1 interview from
`skills/agent-create-skill/SKILL.md` (read it first): the ten-word job,
trigger phrases, the verified-struggle test, the script-vs-prose split.
The library is deliberately small — every skill's description enters every
teammate's context in every session, so the default answer to "should this
be a new skill?" is **improve an existing one**. Extra checks for team
proposals:

- **Name the nearest neighbors**: identify the two or three existing skills
  closest to this job and state why each doesn't cover it. This analysis is
  REQUIRED in the PR description — a proposal without it gets bounced. If
  one nearly fits, propose improving it (a `LEARNINGS.md` entry or a small
  PR against it) instead of a new skill.
- **Team-relevance**: if the workflow is personal to this user (their
  machine, their side project), recommend a personal skill outside the team
  repo and stop.

If the verified-struggle test fails ("nothing has gone wrong yet"), do not
proceed to a PR. Instead append the need to `~/.agents/.manager/requests.md`
(`- YYYY-MM-DD: <task> — <why a skill might help>`) and tell the user it has
been logged as a skill request for the weekly review.

## Step 2 — Branch, scaffold, draft, validate

Work on a branch so the nightly sync is never disturbed:

```bash
cd ~/.agents
git fetch origin && git checkout -B skill/<skill-name> origin/main
uv run skills/agent-create-skill/scripts/init_skill.py <skill-name> --dir skills
```

Draft the SKILL.md following agent-create-skill Steps 3–6 (edit the
scaffold in place; keep its frontmatter). Then validate — fix every error:

```bash
uv run skills/agent-create-skill/scripts/validate_skill.py skills/<skill-name>
```

Run the Step 5 trigger test — including the collision test against every
existing skill's description — and show the user the table.

## Step 3 — Commit and push (the commit message IS the proposal)

No credentials or API calls are needed — a plain `git push` uses the
machine's cached corporate sign-in, and the maintainer's nightly job opens
a pull request from every pushed `skill/*` branch, using the branch tip's
commit message as the PR description. So write the full proposal into the
commit message:

```bash
git add skills/<skill-name>
git commit -m "skills: propose <skill-name>" -m "<proposal body>"
git push origin skill/<skill-name>
```

The proposal body (second `-m`) must include: the ten-word job, the
verified struggle that motivated it (concrete, from the interview), the
library fit analysis (the nearest existing skills and why each doesn't
cover this), the trigger-test table including the collision test, and the
proposer's name. A proposal without the fit analysis gets bounced.

## Step 4 — Leave the clone clean

```bash
git checkout main && git reset --hard origin/main
```

Tell the user their proposal is pushed and a pull request will be opened
automatically by the nightly maintainer job — they'll see it in the repo
within a day, and a maintainer will review it.

## Improving this skill

Before executing, read `LEARNINGS.md` in this skill's folder — entries there
override the instructions above. After use:

1. Append one line to `~/.agents/.manager/usage.jsonl` (create if missing):
   `{"ts": "<ISO-8601>", "skill": "propose-skill", "outcome": "ok" | "corrected"}`
   — `corrected` when the user had to fix or redirect your use of this skill.
2. If the user corrected you or the outcome surprised you, also append one
   dated line to `LEARNINGS.md`:
   `- YYYY-MM-DD: <what happened> → <what to do instead>`. Facts only, never
   secrets. Do not edit SKILL.md directly — lessons are folded in
   deliberately through a weekly reviewed PR.
