# Agent Skills Manager

Distribute a small, reviewed set of Cursor skills to Windows teammates and
fast-forward those skills safely. When a user corrects a skill, the agent can
queue one factual learning for maintainer review.

The system deliberately does not collect invocation counts, outcomes,
heartbeats, adoption metrics, prompts, code, or repository details.

## How it works

Each teammate has:

- a clean runtime clone at `%USERPROFILE%\.agents`;
- local configuration, queued feedback, and logs under
  `%LOCALAPPDATA%\AgentSkills`;
- one daily `AgentSkillsNightly` task that safely updates the runtime and
  publishes queued feedback.

The skills and feedback inbox are separate repositories. Teammates need read
access to the skills repository and permission to push only their own
`feedback/v1/<machine-id>` branch in the inbox repository. They never push the
skills repository.

Runtime updates require the configured path, origin, and branch to match. The
checkout must be completely clean, including untracked files. Updates use
`git merge --ff-only` and never reset, switch branches, rebase, or delete local
files.

## Repository setup

Create two Azure DevOps repositories:

1. Protect `main` in this skills repository. Give teammates read access but no
   direct contribution or policy-bypass permission.
2. Initialize a feedback inbox repository with a README on `main`. Allow
   teammates to create and update their own feedback branches. Treat every
   branch and JSON file as untrusted.

Set both defaults near the top of `bootstrap.ps1` before publishing it:

```powershell
$DefaultRepoUrl = 'https://dev.azure.com/<org>/<project>/_git/agent-skills'
$DefaultInboxRepoUrl = 'https://dev.azure.com/<org>/<project>/_git/agent-skills-feedback'
```

Host the reviewed script at an internal HTTPS URL.

## Install

With both defaults configured:

```powershell
irm https://<internal-host>/bootstrap.ps1 | iex
```

For local testing or explicit configuration:

```powershell
powershell -ExecutionPolicy Bypass -File bootstrap.ps1 `
  -RepoUrl '<skills-repo-url>' `
  -InboxRepoUrl '<feedback-inbox-url>'
```

The installer needs no administrator rights. When Git or uv is missing, it
downloads a pinned official release, verifies its SHA-256 checksum, and installs
it under `%LOCALAPPDATA%\AgentSkills\tools`. uv installs the runtime's managed
Python under the same state directory. The installer then clones the runtime,
writes local configuration, registers the per-user daily task, runs a first
safe update, and executes `doctor`. Re-running it preserves the installation
UUID and replaces the task definition without touching queued feedback.

## Normal operation

The scheduled command is equivalent to:

```powershell
cd $HOME\.agents
& $env:AGENT_SKILLS_PYTHON manage.py nightly `
  --state-dir "$env:LOCALAPPDATA\AgentSkills"
```

Nightly first attempts a safe runtime update, then publishes queued learnings
even if the update failed. A failed push leaves the learning queued. Failures
exit nonzero, appear in `logs\task.log`, and attempt a Windows notification.

Useful commands:

| Command | Purpose |
|---|---|
| `manage.py doctor` | Verify tools, configuration, runtime safety, inbox access, and the task |
| `manage.py sync` | Fast-forward a verified clean runtime |
| `manage.py publish` | Retry queued feedback publication |
| `manage.py record-learning` | Queue one factual correction |
| `manage.py aggregate` | Fold new feedback into `LEARNINGS.md` on a review branch |

Run `fix-signin.cmd` from the runtime if Git Credential Manager sign-in expires.

## Learning feedback

Skills read their local `LEARNINGS.md` before work. They record nothing during
ordinary successful use. If a user corrects a skill's trigger or instructions,
the agent can queue one short factual lesson:

```powershell
& $env:AGENT_SKILLS_PYTHON "$HOME\.agents\manage.py" record-learning `
  --skill python-standards `
  --category instruction `
  --message "Use the project-specific command before the generic fallback."
```

A learning contains only a random event ID, random installation ID, timestamp,
skill name and Git SHA, category, and one single-line message. Feedback failure
must never block the user's task. See [Privacy and feedback](PRIVACY.md).

## Maintainer aggregation

Aggregate from a clean development clone on a review branch:

```powershell
git fetch origin
git switch -c feedback/fold-2026-07-09 origin/main

uv run manage.py aggregate `
  --repo-root . `
  --inbox-repo-url '<feedback-inbox-url>' `
  --state-dir "$env:LOCALAPPDATA\AgentSkillsMaintainer"
```

The aggregator:

- accepts only `feedback/v1/<machine-id>` branches and exact versioned JSON;
- rejects malformed feedback, unsafe paths, and mismatched machine IDs;
- appends new, deduplicated text to the intended skill's `LEARNINGS.md`;
- writes only `feedback/ingestion-state.json`,
  `feedback/REJECTED.md`, and skill `LEARNINGS.md` files.

Review the diff as untrusted feedback, run verification, and open a normal pull
request. A maintainer decides whether a corroborated learning should be folded
into `SKILL.md`.

## Manual uninstall

There is no installed uninstaller. Before removal, optionally publish queued
feedback and inspect the runtime:

```powershell
& $env:AGENT_SKILLS_PYTHON "$HOME\.agents\manage.py" publish `
  --state-dir "$env:LOCALAPPDATA\AgentSkills"

git -C "$HOME\.agents" remote get-url origin
git -C "$HOME\.agents" status --short --untracked-files=all
```

If the origin is the expected skills repository and `git status` prints
nothing, remove the task and the two owned directories:

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
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentSkills' `
  -Recurse -Force -ErrorAction SilentlyContinue
```

If the runtime is dirty or points at another origin, do not delete it. Rename it
or inspect it manually. Removing LocalAppData deletes any unpublished feedback
and the managed Python plus any Git or uv copy installed under its `tools`
directory. A pre-existing Git or uv installation and shared Git credentials
remain untouched. Open a new terminal after removal so it receives the cleaned
user environment. The registry command removes a stale Installed Apps entry
created by versions that shipped an automated uninstaller; it is harmless for
new installations.

## Development

Run from the repository root:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m py_compile manage.py
uv run tools/validate_skill.py skills/agents-md skills/python-standards
git diff --check
```

Changes to installation, scheduled tasks, authentication, runtime discovery, or
filesystem paths also require the Windows 11 and Cursor checks in `TESTING.md`.

## Layout

```text
skills/                 reviewed Cursor skills
manage.py               safe updater and learning-feedback transport
bootstrap.ps1           Windows installer and task registration
install.cmd             optional double-click wrapper
fix-signin.cmd/.ps1     interactive Git sign-in repair
feedback/               processed learning IDs and content-free rejections
tests/                  local real-Git integration tests
PRIVACY.md              exact feedback boundary
TESTING.md              Windows and Cursor canary
ROADMAP.md              remaining pilot gates
```
