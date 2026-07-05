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

Run the Step 1 interview from `skills/agent-create-skill/SKILL.md`
(read it first): the ten-word job, trigger phrases, the verified-struggle
test, the script-vs-prose split. Two extra checks for team proposals:

- **Search for an existing skill first**: read the descriptions in
  `~/.agents/skills/*/SKILL.md`. If one nearly fits, propose improving it
  (a `LEARNINGS.md` entry or a small PR against it) instead of a new skill.
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

Run the Step 5 trigger test and show the user the table.

## Step 3 — Push and open the PR

The `AGENT_SKILLS_PAT` env var holds an Azure DevOps PAT. Never write it to
disk or into git config; pass it per command:

```bash
B64=$(printf ':%s' "$AGENT_SKILLS_PAT" | base64)
git add skills/<skill-name> && git commit -m "skills/<skill-name>: propose new skill"
git -c "http.extraheader=AUTHORIZATION: Basic $B64" push origin skill/<skill-name>
```

Create the PR (derive org/project/repo from `git remote get-url origin`):

```bash
curl -sf -X POST -H "Authorization: Basic $B64" -H "Content-Type: application/json" \
  "https://dev.azure.com/<org>/<project>/_apis/git/repositories/<repo>/pullrequests?api-version=7.1" \
  -d '{"sourceRefName":"refs/heads/skill/<skill-name>","targetRefName":"refs/heads/main","title":"skills: propose <skill-name>","description":"<see below>"}'
```

PR description must include: the ten-word job, the verified struggle that
motivated it (concrete, from the interview), the trigger-test table, and
the proposer's name.

## Step 4 — Leave the clone clean

```bash
git checkout main && git reset --hard origin/main
```

Give the user the PR link and tell them a maintainer will review it.

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
