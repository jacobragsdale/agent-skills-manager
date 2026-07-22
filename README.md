# Skillsync

Skillsync gives an engineering team a shared, reviewable library of
Cursor skills that stays current on every developer workstation. Skills are
organized into **inheriting skill sets** — universal practices at the root,
language and team specifics in child sets — and every machine subscribes to
exactly one set, receiving its skills plus everything inherited up the chain.

It is intentionally narrow: distribute trusted skills and update them safely.
It is not an agent platform, usage dashboard, or employee-monitoring system.

## What your team gets

| Audience | Benefit |
|---|---|
| Developers | The skills for *their* team appear in Cursor, update automatically, and require no administrator-assisted install. |
| Engineering managers | Team practices are versioned, protected by branch policy, and changed through review instead of copied between laptops. |
| Skill maintainers | One manifest describes who gets what; CI proves it is conflict-free before it can merge. |

## Skill sets and inheritance

`sets.toml` at the repository root is the whole data model:

```toml
[global]
skills = ["agents-md"]

[python]
inherits = "global"
skills = ["python-standards"]
```

Sets form a tree. A machine subscribed to a set receives the union of skills
along its inheritance chain:

```text
global ──────────── agents-md
   └── python ────── python-standards
          ├── payments ──── stripe-conventions      (example)
          └── data-eng ──── dbt-conventions         (example)
```

A machine on `payments` would get `agents-md` + `python-standards` +
`stripe-conventions`; a machine on `global` gets only `agents-md`. This
repository currently ships the `global` and `python` sets shown above.

The rules, all enforced by `manage.py validate-sets` in CI:

- exactly one root set has no `inherits`; every other set names one parent;
- inheritance is a tree — one parent, no cycles;
- every directory under `skills/` is listed in **exactly one** set.

Conflicts are handled structurally where possible: the flat `skills/`
directory makes duplicate skill names impossible, and the manifest rules make
a skill's owner unambiguous. Semantic conflicts — a child skill contradicting
inherited guidance — are the pull-request reviewer's job, made tractable
because a new skill only needs comparing against its own short inheritance
chain.

### Adding a skill or a team

1. Add `skills/<name>/` with a `SKILL.md` and `LEARNINGS.md`
   (`tools/validate_skill.py` checks the shape).
2. List it in the right set in `sets.toml` — or add a new
   `[your-team]` table with `inherits` and open the same pull request.
3. CI runs `validate-sets`; once merged, subscribed machines pick the change
   up on their next nightly sync. New teams install with
   `bootstrap.ps1 -SkillSet your-team`.

## How it works on a machine

```text
%LOCALAPPDATA%\AgentSkills\           internal state
  repo\                               full clone, fast-forward only, never edited
  config.json                         repo URL, branch, skill set, view path
  locks\  logs\

%USERPROFILE%\.agents\                generated view - Cursor reads this
  skills\<subscribed skills only>
  installed.json                      set, chain, skills, source Git SHA
  .agent-skills-managed               marker: safe for the manager to replace
  fix-signin.cmd                      double-click to repair Git sign-in
```

Nightly, the manager: validates the clone (right path, origin, branch, no
local changes) → fetches → fast-forward merges → resolves the subscribed set
from `sets.toml` → rebuilds the view in a temp directory and swaps it in
whole. The view is disposable and self-healing; the clone is never touched by
anything except a fast-forward. If a bad manifest ever reaches `main`, sync
fails loudly and the machine keeps yesterday's working view.

The manager never resets, rebases, switches branches, or deletes a directory
it cannot prove it generated (the marker file).

## Data boundary

The client records and transmits nothing. There are no invocation, outcome,
adoption, duration, productivity, prompt, response, code, or repository-detail
events. The only network traffic is the Git fetch of the skills repository,
which the Git provider can associate with its normal authentication and audit
records.

## Requirements

- Windows 11 x64 and Cursor;
- read access to the protected skills repository;
- an internal HTTPS location from which to serve the reviewed bootstrap script.

Git, uv, Python, and administrator rights are not prerequisites. When needed,
the installer downloads pinned, SHA-256-verified Git and uv releases plus a
managed Python runtime under `%LOCALAPPDATA%\AgentSkills`.

## Deploy for a team

1. Protect `main` in this repository. Developers should have read access but no
   direct contribution or policy-bypass permission.
2. Set the repository default near the top of `bootstrap.ps1`:

```powershell
$DefaultRepoUrl = 'https://dev.azure.com/<org>/<project>/_git/agent-skills'
```

3. Host the reviewed `bootstrap.ps1` at an internal HTTPS URL.
4. Pilot with a small group and verify repository permissions before expanding
   access.

Azure DevOps is shown here, but the workflow only requires Git hosting and an
authentication setup that works with Git for Windows.

## Install

With the repository default configured, a developer runs:

```powershell
irm https://<internal-host>/bootstrap.ps1 | iex
```

That subscribes the machine to the `global` set. To subscribe to a specific
team set, or for local testing:

```powershell
powershell -ExecutionPolicy Bypass -File bootstrap.ps1 `
  -RepoUrl '<skills-repo-url>' -SkillSet python
```

The installer is safe to rerun (also to change the subscribed set). It
replaces the nightly task definition, safely syncs, rebuilds the view, and
runs `doctor`.

## Day-to-day operation

No routine developer action is required. `AgentSkillsNightly` updates the
clone and rebuilds the view. Failures are written to
`%LOCALAPPDATA%\AgentSkills\logs\task.log`, and the process exits nonzero.

If Git authentication expires, double-click `fix-signin.cmd` in
`%USERPROFILE%\.agents`. It reopens the normal Git Credential Manager sign-in
flow without replacing local state.

Useful maintenance commands use the installed interpreter:

```powershell
$manager = "$env:LOCALAPPDATA\AgentSkills\repo\manage.py"
$state = "$env:LOCALAPPDATA\AgentSkills"

& $env:AGENT_SKILLS_PYTHON $manager doctor --state-dir $state
& $env:AGENT_SKILLS_PYTHON $manager sync --state-dir $state
```

`doctor` verifies the tools, the clone's safety invariants, that the
subscribed set still resolves, and that the view matches the clone's current
commit. `installed.json` in the view answers "what is on this machine and
where did it come from" at a glance.

## Maintain learnings

Each skill keeps a `LEARNINGS.md` next to its `SKILL.md`. Skills read it
before working, and developers report corrections to a maintainer instead of
editing their runtime. Maintainers land reported lessons through normal pull
requests, treat the text as untrusted input, and fold corroborated entries
into `SKILL.md` deliberately — deleting them from `LEARNINGS.md` once folded.

## Remove an installation

`%USERPROFILE%\.agents` is generated; confirm it carries the manager's marker
before deleting:

```powershell
Test-Path "$HOME\.agents\.agent-skills-managed"
```

If that prints `True`, remove the task, project-owned PATH entries, view, and
state:

```powershell
schtasks.exe /End /TN AgentSkillsNightly 2>$null
schtasks.exe /Delete /TN AgentSkillsNightly /F
Remove-Item -LiteralPath "$HOME\.agents" -Recurse -Force

$ownedPaths = @(
  "$env:LOCALAPPDATA\AgentSkills\tools\git\cmd",
  "$env:LOCALAPPDATA\AgentSkills\tools\uv"
)
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';' |
  Where-Object { $_ -and $_.TrimEnd('\') -notin $ownedPaths.TrimEnd('\') }
[Environment]::SetEnvironmentVariable('Path', ($userPath -join ';'), 'User')
[Environment]::SetEnvironmentVariable('AGENT_SKILLS_PYTHON', $null, 'User')
Remove-Item -LiteralPath "$env:LOCALAPPDATA\AgentSkills" -Recurse -Force
```

If `.agents` lacks the marker, it is not this project's directory — inspect it
instead of deleting it. Removing LocalAppData also removes the internal clone
and any Git, uv, or Python copy installed by this project. Pre-existing tools
and shared Git credentials remain untouched. Open a new terminal afterward so
it receives the cleaned user environment.

## Development

Run from the repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile manage.py
uv run tools/validate_skill.py skills/*
uv run manage.py validate-sets
git diff --check
```

CI (`.github/workflows/ci.yml`) runs the same commands on every push and pull
request. Installer, task, authentication, or filesystem-path changes also
require a fresh Windows 11 x64 standard-user canary: Git and uv absent, no UAC
prompt, `doctor` passing, and an on-demand nightly task returning zero.

## Repository layout

```text
sets.toml     skill sets and their inheritance tree
skills/       reviewed skills, references, and their required helper scripts
manage.py     safe runtime updater, set resolver, and view materializer
bootstrap.ps1 per-user Windows installer and task registration
fix-signin.*  interactive Git Credential Manager recovery
tests/        real-Git integration tests for manager behavior
```
