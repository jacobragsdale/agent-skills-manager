# agent-skills-manager

**Your team's coding agents, learning from each other's mistakes — automatically.**

Every developer using Cursor, Claude Code, Codex, or Copilot is quietly
re-teaching their agent the same lessons: the flag that changed, the internal
proxy dance, the deploy step everyone forgets. That knowledge evaporates at
the end of each session, on each machine, for each person.

This repo turns [Agent Skills](https://agentskills.io) into a **team
memory with a feedback loop**: skills are distributed to every machine
nightly, agents record what went wrong in the field, and a weekly reviewed
pull request folds those corrections back into the skills everyone runs
tomorrow. No servers, no telemetry infrastructure, no new tools — the entire
system is **git plus one scheduled task**.

## How it works

```mermaid
flowchart LR
    subgraph fleet["Every machine, nightly"]
        A["Agent uses a skill,<br/>appends corrections to LEARNINGS.md,<br/>usage + requests to local spools"]
        H["manage.py nightly<br/>(Windows Task Scheduler)"]
        A --> H
    end

    subgraph repo["Team repo (cloned as ~/.agents)"]
        I["learnings/inbox/<br/>metrics/inbox/<br/>requests/inbox/<br/>machines/*.json"]
        M["main"]
    end

    subgraph weekly["One machine, weekly"]
        W["Headless agent runs<br/>prompts/weekly-learnings-fold.md"]
        PR["Fold PR:<br/>LEARNINGS folded + deduped<br/>SKILL.md improvements<br/>dashboard + backlog + fleet health"]
        W --> PR
    end

    H -- "harvest: push uniquely-named<br/>files (zero conflicts)" --> I
    H -- "hard reset = update pull" --> M
    M -- "skills + rules + tooling<br/>(self-updating)" --> H
    I --> W
    PR -- "human review, merge" --> M
```

Three loops ride the same pipe:

- **Learnings** — after using a skill, agents append one dated correction
  line to its `LEARNINGS.md`. Nightly harvest ships them upstream; the
  weekly agent semantically dedupes across the team, and lessons confirmed
  by **two or more people** get folded into the skill itself — as separate,
  droppable commits in a PR a human reviews.
- **Metrics** — agents log each skill use to a local spool; the dashboard
  (`metrics/DASHBOARD.md`) shows adoption, corrected-rates, struggling
  skills, and deprecation candidates. The fleet heartbeats in
  `machines/*.json` flag broken installs nobody noticed.
- **Requests** — when an agent watches a user struggle at a task no skill
  covers, it logs the need. The weekly triage ranks `requests/BACKLOG.md`
  by distinct requesters: a demand-ranked backlog of skills worth writing,
  authored by the agents that saw the pain.

Contributing is a conversation: a teammate tells their agent
*"this should be a team skill"*, and `/propose-skill` interviews them,
scaffolds, validates, and opens the PR.

## Why this design holds up

- **Machines are appliances.** The repo is cloned directly as `~/.agents`
  (no symlinks — they need admin on Windows). Every night each clone pushes
  its sanctioned local writes upstream as *uniquely-named files* — zero
  merge conflicts at any fleet size — then hard-resets to `origin/main`.
  Harvest **is** the update pull; drift is structurally impossible.
- **The tooling ships inside the repo.** `manage.py` (single-file,
  stdlib-only, PEP 723) updates itself with every nightly pull. New
  features and dependencies reach the whole fleet without reinstalling
  anything.
- **Windows 11 only, on purpose.** One OS, one scheduled task, one install
  path to polish and test. Dependencies live in a small table at the top of
  `bootstrap.ps1` — adding one for the whole fleet is a one-row change.
- **Improvement is gated, not automatic.** Agents may only append
  learnings; skills change through the weekly fold PR, with evidence in the
  description and one commit per fold so a reviewer can drop any single
  change.
- **Auth is your corporate sign-in, not tokens.** Members never touch a
  PAT: Git Credential Manager (bundled with Git for Windows) pops one
  Microsoft sign-in window at install and silently refreshes afterwards,
  including for the scheduled task. If it ever expires, a Windows toast
  points at `fix-signin.cmd` — one double-click repairs it. The only PAT in
  the fleet lives on the maintainer machine, for the pull-request API.

## Quick start (teammate, Windows 11)

If your team hosts the install script (maintainer setup below), the whole
install is one line in PowerShell — no git needed first, no tokens, no
settings:

```powershell
irm https://<your-host>/bootstrap.ps1 | iex
```

No script host? Then it's two clicks and no terminal at all: open the repo
in Azure DevOps in your browser, choose **⋯ → Download as Zip**, extract it
anywhere, and double-click **install.cmd**. (Or, if you already have git:
clone the repo anywhere and run
`powershell -ExecutionPolicy Bypass -File bootstrap.ps1`.)

Every entry point runs the same installer: it installs git + uv (winget
with fallbacks), creates the managed clone at `%USERPROFILE%\.agents`,
registers the nightly Scheduled Task, and runs a first sync — your machine
appears on the team dashboard immediately. When git first talks to Azure DevOps, the familiar Microsoft
sign-in window opens once; that is the only prompt. Idempotent — re-run any
time; `bootstrap.ps1 -Uninstall` removes the task and the clone.

## Which agents pick this up

The managed clone at `~/.agents` puts skills at `~/.agents/skills/` — an
official user-level discovery path for **Cursor, Codex, and Copilot**, so
those three see every skill natively with zero configuration. **Claude
Code** reads only `~/.claude/skills`; set `AGENT_SKILLS_CLAUDE=1` and the
nightly sync maintains per-skill links there. (On machines running both
Claude Code and Cursor, disable Cursor's *Include third-party Plugins,
Skills, and other configs* setting — Cursor also scans `~/.claude/skills`
and does not dedupe.)

All four agents load skills the same way: name + description always in
context (~100 tokens/skill), body only when a skill fires, references only
when read. The learnings/usage loop rides each skill's footer, so it is in
context exactly when a skill runs — no always-on configuration needed.

There is deliberately no always-on rules layer: no agent auto-loads rules
from `~/.agents`, so anything that mattered there rides skill footers and
descriptions instead — zero manual configuration per teammate.

## Setting up for your team (maintainer, one-time)

1. Push this repo to your Azure DevOps project.
2. Set `$DefaultRepoUrl` near the top of `bootstrap.ps1` to your repo URL
   and commit — members then never need to know or type it.
3. Host `bootstrap.ps1` at any HTTPS URL teammates can reach **without
   signing in** (intranet static server, Azure Storage static website,
   internal tools page) and distribute the one-liner. Re-publish the copy
   whenever `bootstrap.ps1` changes. Azure DevOps itself cannot serve raw
   files anonymously — that is why the Zip + `install.cmd` path exists as
   the zero-hosting fallback; if you skip this step, distribute those
   instructions instead.
4. On YOUR machine only, create an ADO PAT (Code read & write) and run
   `bootstrap.ps1 -FoldMachine` with `$env:AGENT_SKILLS_PAT` set — this is
   the one machine that talks to the PR API. Its nightly job then runs the
   mechanical fold and opens PRs for teammates' pushed `skill/*` proposal
   branches (`manage.py sweep-proposals`).
5. For the judgment-enhanced weekly fold, schedule your headless agent CLI
   against the committed prompt:

   ```powershell
   cd $HOME\.agents; agent -p (Get-Content prompts\weekly-learnings-fold.md -Raw)
   ```

6. Optional: set `TEAMS_WEBHOOK_URL` on the fold machine for a weekly
   digest that credits contributors whose lessons got promoted.
7. Recommended: branch policy requiring review on `learnings/fold` PRs.

Hosting elsewhere? Harvest works with any git remote; only the PR-creation
and auth-header helpers are Azure DevOps-specific (one small function each
to swap for GitHub/GitLab).

## Layout

```
skills/<name>/          one folder per skill: SKILL.md + LEARNINGS.md (+ scripts/, references/)
prompts/                versioned prompts for scheduled agent jobs
learnings/inbox/        harvested corrections awaiting the weekly fold
metrics/inbox/ + DASHBOARD.md    usage telemetry and the weekly dashboard
requests/inbox/ + BACKLOG.md     demand-ranked backlog of skills to build
machines/               per-machine heartbeats (fleet health)
manage.py               nightly sync/harvest/fold/sweep engine (self-updating)
bootstrap.ps1           one-time Windows machine setup (irm | iex, zip, or clone)
install.cmd             double-click installer for the zip-download path
fix-signin.cmd          one-click repair when the cached sign-in expires
TESTING.md              clean-VM install test protocol (Windows 11)
AGENTS.md               rules for agents working inside this repo
ROADMAP.md              where this goes: trigger CI, drift detection, multi-team scale
```

`manage.py doctor` verifies any machine; `.manager/` holds local logs,
backups, and spools (gitignored).

## The conventions that make it work

Every skill follows the house process in `skills/agent-create-skill`
(interview → scaffold → validate → trigger-test → learnings loop). Skills
are model-invocable by default — descriptions are written as pushy triggers
with explicit "Do NOT use" boundaries, tuned against the invocation
mechanics documented in
`skills/agent-create-skill/references/invocation.md`, and the library is
kept deliberately small (every description enters every session's context).
The improvement loop (read LEARNINGS first; log usage and corrections
after) rides each skill's footer. Nothing else about a machine is trusted
or preserved — which is exactly why the system stays healthy with zero
ongoing administration.
