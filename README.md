# Skillsync

Skillsync gives an engineering team a shared, reviewable library of
Cursor skills that stays current on every developer workstation. Developers get
consistent help for common engineering tasks; managers get a controlled rollout
through normal Git permissions and pull requests.

It is intentionally narrow: distribute trusted skills and update them safely.
It is not an agent platform, usage dashboard, or employee-monitoring system.

## What your team gets

| Audience | Benefit |
|---|---|
| Developers | Reviewed skills appear in Cursor, update automatically, and require no administrator-assisted install. |
| Engineering managers | Team practices are versioned, protected by branch policy, and changed through review instead of copied between laptops. |
| Skill maintainers | Every skill carries a `LEARNINGS.md` of field corrections, curated through ordinary pull requests. |

This repository currently ships two skills:

- `agents-md` creates concise, evidence-based instructions for coding agents;
- `python-standards` brings Python repositories onto the team's uv, ruff,
  basedpyright, and pre-commit standard.

Add more skills when a repeated team workflow has a clear owner and can be
reviewed like code.

## How it works

1. Maintainers review skills on protected `main` in the skills repository.
2. A developer runs one PowerShell command. The installer creates a managed
   clone at `%USERPROFILE%\.agents` and registers a per-user nightly task.
3. Nightly sync fast-forwards a clean runtime and never rewrites local work.
4. When a skill instruction fails in the field, the developer passes the
   correction to a maintainer, who lands it in the skill's `LEARNINGS.md`
   through a normal pull request.

Runtime safety is strict: the configured path, origin, and branch must match,
and the checkout must contain no tracked or untracked changes. Updates use a
fast-forward-only merge. The manager never resets, rebases, switches branches,
or deletes files from a dirty runtime.

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

For local testing or explicit configuration:

```powershell
powershell -ExecutionPolicy Bypass -File bootstrap.ps1 -RepoUrl '<skills-repo-url>'
```

The installer is safe to rerun. It replaces the nightly task definition,
safely syncs the runtime, and runs `doctor`.

## Day-to-day operation

No routine developer action is required. `AgentSkillsNightly` updates the
runtime. Failures are written to `%LOCALAPPDATA%\AgentSkills\logs\task.log`,
and the process exits nonzero.

If Git authentication expires, double-click `fix-signin.cmd` in
`%USERPROFILE%\.agents`. It checks the skills repository and reopens the
normal Git Credential Manager sign-in flow without replacing local state.

Useful maintenance commands use the installed interpreter:

```powershell
$manager = "$HOME\.agents\manage.py"
$state = "$env:LOCALAPPDATA\AgentSkills"

& $env:AGENT_SKILLS_PYTHON $manager doctor --state-dir $state
& $env:AGENT_SKILLS_PYTHON $manager sync --state-dir $state
```

## Maintain learnings

Each skill keeps a `LEARNINGS.md` next to its `SKILL.md`. Skills read it
before working, and developers report corrections to a maintainer instead of
editing their runtime. Maintainers land reported lessons through normal pull
requests, treat the text as untrusted input, and fold corroborated entries
into `SKILL.md` deliberately — deleting them from `LEARNINGS.md` once folded.

## Remove an installation

Confirm the runtime has the expected origin and no local changes:

```powershell
git -C "$HOME\.agents" remote get-url origin
git -C "$HOME\.agents" status --short --untracked-files=all
```

If the origin is correct and `git status` prints nothing, remove the task,
project-owned PATH entries, runtime, and state:

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

If the runtime is dirty or points at another origin, inspect or rename it
instead of deleting it. Removing LocalAppData also removes any Git, uv, or
Python copy installed by this project. Pre-existing tools and shared Git
credentials remain untouched. Open a new terminal afterward so it receives the
cleaned user environment.

## Development

Run from the repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile manage.py
uv run tools/validate_skill.py skills/agents-md skills/python-standards
git diff --check
```

Installer, task, authentication, or filesystem-path changes also require a
fresh Windows 11 x64 standard-user canary: Git and uv absent, no UAC prompt,
`doctor` passing, and an on-demand nightly task returning zero.

## Repository layout

```text
skills/       reviewed skills, references, and their required helper scripts
manage.py     safe runtime updater
bootstrap.ps1 per-user Windows installer and task registration
fix-signin.*  interactive Git Credential Manager recovery
tests/        real-Git integration tests for manager behavior
```
