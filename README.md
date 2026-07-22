# Skillsync

Skillsync puts one shared pack of Cursor skills on each developer workstation.
Every directory under `skills/` is installed. There are no per-team choices or
manifests.

A developer runs one bootstrap command. A per-user nightly job pulls updates
and rebuilds Cursor's `~/.agents` view.

## Repository shape

```text
skills/
  agents-md/
    SKILL.md
    references/
    scripts/
  python-standards/
    SKILL.md
    references/
    scripts/
bootstrap.ps1
manage.py
tests/
```

To add a skill, add `skills/<name>/SKILL.md` and any files it needs. Once the
change reaches `main`, every installed machine receives it on the next nightly
sync.

## Install

Requirements are Windows 11 x64, Cursor, read access to the skills repository,
and an internal HTTPS location serving `bootstrap.ps1`. Administrator rights,
Git, uv, and Python are not prerequisites. When missing, the bootstrap installs
pinned, checksum-verified copies under `%LOCALAPPDATA%\AgentSkills`.

Before publishing the bootstrap, configure its repository URL:

```powershell
$DefaultRepoUrl = 'https://dev.azure.com/<org>/<project>/_git/agent-skills'
```

Then a developer runs:

```powershell
irm https://<internal-host>/bootstrap.ps1 | iex
```

For local testing, pass the repository explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File bootstrap.ps1 `
  -RepoUrl '<skills-repo-url>'
```

The bootstrap is safe to rerun. It installs missing tools, creates or reuses
the read-only runtime clone, writes local configuration, replaces the nightly
task definition, syncs the skills, and runs `doctor`.

After deploying this version, rerun the bootstrap once on machines installed
with an earlier version so their simplified local configuration is rewritten.
Nightly updates require no action after that.

## What runs on a machine

```text
%LOCALAPPDATA%\AgentSkills\
  repo\                 read-only runtime clone
  config.json           repository, branch, and view paths
  locks\
  logs\task.log

%USERPROFILE%\.agents\
  skills\               the complete pack
  installed.json        skill names and source Git SHA
  .agent-skills-managed replacement safety marker
```

`AgentSkillsNightly` runs `manage.py sync` once a day. Sync verifies that the
clone has the expected origin and branch and has no local changes, fetches the
remote, fast-forwards `main`, validates every skill, and replaces the generated
view.

The manager never pushes, resets, rebases, switches branches, or discards clone
files. It only replaces a view carrying its marker. If an invalid skill reaches
`main`, the previous working view remains in place.

The client records and transmits nothing. Its only network traffic is the Git
fetch, subject to the Git provider's normal authentication and audit records.

## Maintenance

No routine developer action is required. Failures are written to:

```text
%LOCALAPPDATA%\AgentSkills\logs\task.log
```

If Git authentication expires, run one interactive fetch:

```powershell
git -C "$env:LOCALAPPDATA\AgentSkills\repo" fetch
```

Useful checks use the installed Python:

```powershell
$manager = "$env:LOCALAPPDATA\AgentSkills\repo\manage.py"
$state = "$env:LOCALAPPDATA\AgentSkills"

& $env:AGENT_SKILLS_PYTHON $manager doctor --state-dir $state
& $env:AGENT_SKILLS_PYTHON $manager sync --state-dir $state
```

`doctor` verifies the tools, clone safety, flat skill pack, nightly task, and
generated view.

## Remove an installation

Confirm that `.agents` is managed by this project before deleting it:

```powershell
Test-Path "$HOME\.agents\.agent-skills-managed"
```

If that prints `True`:

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

If the marker is absent, inspect `.agents` instead of deleting it. Removing
`AgentSkills` also removes tool copies installed by the bootstrap; pre-existing
tools and shared Git credentials are untouched.

## Development

Run from the repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile manage.py
uv run manage.py validate-skills
git diff --check
```

`validate-skills` checks that `skills/` is non-empty, contains only kebab-case
skill directories, and that every `SKILL.md` has matching frontmatter and a
description.

Changes to `bootstrap.ps1`, task scheduling, Git authentication, runtime
discovery, or filesystem paths also require a Windows 11 x64 standard-user
canary with Git and uv absent: no UAC prompt, `doctor` passing, and an on-demand
nightly task returning zero.
