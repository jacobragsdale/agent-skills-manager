# Skillsync

Skillsync gives an engineering team a shared, reviewable library of
Cursor skills that stays current on every developer workstation. Developers get
consistent help for common engineering tasks; managers get a controlled rollout
through normal Git permissions and pull requests; maintainers get a small
feedback loop for improving instructions that fail in the field.

It is intentionally narrow: distribute trusted skills, update them safely, and
return explicit corrections for human review. It is not an agent platform,
usage dashboard, or employee-monitoring system.

## What your team gets

| Audience | Benefit |
|---|---|
| Developers | Reviewed skills appear in Cursor, update automatically, and require no administrator-assisted install. |
| Engineering managers | Team practices are versioned, protected by branch policy, and changed through review instead of copied between laptops. |
| Skill maintainers | Factual corrections can flow back to the right skill without collecting prompts, code, or usage telemetry. |

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
4. When a developer explicitly corrects a skill, the agent can queue one short
   factual learning in a separate feedback repository.
5. A maintainer aggregates those learnings on a review branch and decides what,
   if anything, should change in the skill.

The two-repository design separates skill distribution from feedback writes.
Developer machines can read the skills repository but cannot push it. The
client publishes to `feedback/v1/<machine-id>`, but that branch name is routing,
not an authorization boundary: unless the Git host is configured with narrower
ACLs, a developer who can contribute feedback branches may also be able to read
or update branches created by other installations. Treat every inbox branch as
untrusted input.

Runtime safety is strict: the configured path, origin, and branch must match,
and the checkout must contain no tracked or untracked changes. Updates use a
fast-forward-only merge. The manager never resets, rebases, switches branches,
or deletes files from a dirty runtime.

## Feedback and data boundary

Ordinary skill use records nothing. There are no invocation, outcome, adoption,
duration, productivity, prompt, response, code, or repository-detail events.

An explicit learning contains only:

- random installation and event IDs;
- a UTC timestamp;
- the skill name and skills-repository Git SHA;
- a correction category;
- one factual, single-line message of at most 2,000 characters.

Never put prompts, code, paths, names, host details, tickets, customer data,
credentials, or internal URLs in a learning. The schema rejects unknown fields,
and maintainers must review all learning text as untrusted input.

Pending learnings stay under
`%LOCALAPPDATA%\AgentSkills\feedback\pending` until published. Published data
lives on a pseudonymous feedback branch; the Git provider can still associate
its normal authentication and audit records with the push. Pushed feedback and
merged learnings follow the repositories' normal Git retention. Removing the
local installation does not delete data already pushed.

## Requirements

- Windows 11 x64 and Cursor;
- read access to the protected skills repository;
- permission to create and update feedback branches in a separate feedback
  repository; the default design does not guarantee branch isolation between
  installations;
- an internal HTTPS location from which to serve the reviewed bootstrap script.

Git, uv, Python, and administrator rights are not prerequisites. When needed,
the installer downloads pinned, SHA-256-verified Git and uv releases plus a
managed Python runtime under `%LOCALAPPDATA%\AgentSkills`.

## Deploy for a team

1. Protect `main` in this repository. Developers should have read access but no
   direct contribution or policy-bypass permission.
2. Create a separate feedback repository with an initialized `main`. Allow
   developers to create and update feedback branches, but protect `main`. Do
   not assume the machine-ID branch name enforces ownership. If your Git host
   supports narrower per-branch ACLs, configure and test them separately;
   otherwise assume contributors can read or update other feedback branches.
3. Set the repository defaults near the top of `bootstrap.ps1`:

```powershell
$DefaultRepoUrl = 'https://dev.azure.com/<org>/<project>/_git/agent-skills'
$DefaultInboxRepoUrl = 'https://dev.azure.com/<org>/<project>/_git/agent-skills-feedback'
```

4. Host the reviewed `bootstrap.ps1` at an internal HTTPS URL.
5. Pilot with a small group, verify repository permissions, and review the first
   feedback aggregation before expanding access.

Azure DevOps is shown here, but the workflow only requires Git hosting and an
authentication setup that works with Git for Windows.

## Install

With the repository defaults configured, a developer runs:

```powershell
irm https://<internal-host>/bootstrap.ps1 | iex
```

For local testing or explicit configuration:

```powershell
powershell -ExecutionPolicy Bypass -File bootstrap.ps1 `
  -RepoUrl '<skills-repo-url>' `
  -InboxRepoUrl '<feedback-repo-url>'
```

The installer is safe to rerun. It preserves the installation ID and queued
feedback, replaces the nightly task definition, safely syncs the runtime, and
runs `doctor`.

## Day-to-day operation

No routine developer action is required. `AgentSkillsNightly` updates the
runtime and publishes queued learnings. Failed pushes stay queued, failures are
written to `%LOCALAPPDATA%\AgentSkills\logs\task.log`, and the process exits
nonzero.

If Git authentication expires, double-click `fix-signin.cmd` in
`%USERPROFILE%\.agents`. It checks both repositories and reopens the normal Git
Credential Manager sign-in flow without replacing local state.

Useful maintenance commands use the installed interpreter:

```powershell
$manager = "$HOME\.agents\manage.py"
$state = "$env:LOCALAPPDATA\AgentSkills"

& $env:AGENT_SKILLS_PYTHON $manager doctor --state-dir $state
& $env:AGENT_SKILLS_PYTHON $manager sync --state-dir $state
& $env:AGENT_SKILLS_PYTHON $manager publish --state-dir $state
```

## Review learning feedback

Aggregate from a clean development clone on a review branch:

```powershell
git fetch origin
git switch -c feedback/fold-2026-07-10 origin/main

uv run manage.py aggregate `
  --repo-root . `
  --inbox-repo-url '<feedback-repo-url>' `
  --state-dir "$env:LOCALAPPDATA\AgentSkillsMaintainer"
```

Aggregation accepts only the versioned feedback schema on
`feedback/v1/<machine-id>` branches. It deduplicates accepted messages and can
change only:

- the intended skill's `LEARNINGS.md`;
- `feedback/ingestion-state.json`;
- `feedback/REJECTED.md`, using content-free rejection reasons.

Review the diff, commit the aggregation result, run it a second time to confirm
there is no additional diff, and open a normal pull request. Maintainers fold a
corroborated learning into `SKILL.md` only when it improves the reviewed
instruction.

## Remove an installation

Optionally publish queued feedback, then confirm the runtime has the expected
origin and no local changes:

```powershell
& $env:AGENT_SKILLS_PYTHON "$HOME\.agents\manage.py" publish `
  --state-dir "$env:LOCALAPPDATA\AgentSkills"

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
instead of deleting it. Removing LocalAppData also removes unpublished feedback
and any Git, uv, or Python copy installed by this project. Pre-existing tools
and shared Git credentials remain untouched. Open a new terminal afterward so
it receives the cleaned user environment.

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
manage.py     safe updater and learning-feedback transport
bootstrap.ps1 per-user Windows installer and task registration
fix-signin.*  interactive Git Credential Manager recovery
feedback/     processed learning IDs and content-free rejection reasons
tests/        real-Git integration tests for manager behavior
```
