# bootstrap.ps1 - one-time setup of the team agent-skills repo on a Windows 11 machine.
#
# Three ways to run it, all equivalent -- use whichever your team distributes:
#
#   A. One line in PowerShell, if your team hosts this script at an internal URL:
#        irm https://<your-host>/bootstrap.ps1 | iex
#   B. No terminal at all: in Azure DevOps, open the repo in your browser,
#      "..." > Download as Zip, extract anywhere, double-click install.cmd.
#   C. From a clone (requires git already installed):
#        git clone <repo-url> skills-setup; cd skills-setup
#        powershell -ExecutionPolicy Bypass -File bootstrap.ps1
#
# No tokens, no configuration: when git first talks to Azure DevOps, a
# Microsoft sign-in window opens -- use your corporate account. Git Credential
# Manager (bundled with Git for Windows) caches and silently refreshes the
# credential afterwards, including for the nightly scheduled task.
#
# What it does:
#   1. Installs the dependencies listed in $Dependencies below (git + uv).
#   2. Clones the skills repo as %USERPROFILE%\.agents (the repo IS .agents)
#      and verifies the cached sign-in works.
#   3. Registers a daily Scheduled Task running `uv run manage.py nightly`
#      (pull updates, harvest learnings -- see manage.py).
#   4. Runs an initial sync (your machine shows up for the team immediately)
#      and a doctor check.
#
# Idempotent -- re-run any time. Undo everything with:
#   powershell -ExecutionPolicy Bypass -File bootstrap.ps1 -Uninstall
# If sign-in ever expires later, double-click fix-signin.cmd in %USERPROFILE%\.agents.
#
# This file must stay pure ASCII: it is fetched over HTTP and piped to iex,
# and Windows PowerShell 5.1 reads BOM-less files as ANSI.

#Requires -Version 5.1
[CmdletBinding()]
param(
    # Where the team skills repo lives. Resolved in order: this parameter,
    # $env:AGENT_SKILLS_REPO_URL, $DefaultRepoUrl below, and finally the
    # origin remote of the clone this script is running from (if any).
    [string]$RepoUrl = '',
    # MAINTAINER ONLY: enables the nightly mechanical fold + proposal-PR sweep.
    # Requires $env:AGENT_SKILLS_PAT (Azure DevOps PAT, Code read & write) to
    # be set in this session; it is persisted for the scheduled task.
    [switch]$FoldMachine,
    [string]$TaskTime = '02:00',
    # Remove the scheduled task and the managed clone (asks before deleting).
    [switch]$Uninstall
)

# Maintainers: set this to your team's repo URL before hosting or distributing
# the script, so members can run it with zero arguments.
$DefaultRepoUrl = ''

# Everything the fleet needs installed. To add a dependency, append a row:
#   Command  - executable name used to detect it (and skip if present)
#   Name     - human-readable label for messages
#   WingetId - winget package id (primary install route)
#   Fallback - optional scriptblock used when winget is missing or fails
#   Hint     - appended to the error message if nothing works
$Dependencies = @(
    @{ Command = 'git'
       Name    = 'Git for Windows (includes Git Credential Manager)'
       WingetId = 'Git.Git'
       Hint    = 'Install "App Installer" from the Microsoft Store (for winget) or Git for Windows manually, then re-run.' }
    @{ Command = 'uv'
       Name    = 'uv (runs the sync tooling)'
       WingetId = 'astral-sh.uv'
       Fallback = { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
       Hint    = 'Install uv manually (https://docs.astral.sh/uv/), then re-run.' }
)

$ErrorActionPreference = 'Stop'
$Dest = Join-Path $HOME '.agents'
$TaskName = 'AgentSkillsNightly'
$StartTime = Get-Date

$script:Step = 0
$TotalSteps = 4
function Write-Step([string]$msg) {
    $script:Step++
    Write-Host ''
    Write-Host "[$($script:Step)/$TotalSteps] $msg" -ForegroundColor Cyan
}
function Write-Note([string]$msg) { Write-Host "      $msg" }

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-Dependency([hashtable]$dep) {
    if (Get-Command $dep.Command -ErrorAction SilentlyContinue) {
        Write-Note "$($dep.Command): already installed."
        return
    }
    Write-Note "$($dep.Command): installing $($dep.Name)..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        # --disable-interactivity: no progress-bar spam in logs/SSH sessions;
        # --source winget: skip the msstore source and its agreement prompts.
        winget install --id $dep.WingetId -e --silent --source winget --disable-interactivity `
            --accept-source-agreements --accept-package-agreements
        Update-SessionPath
    }
    if (-not (Get-Command $dep.Command -ErrorAction SilentlyContinue) -and $dep.Fallback) {
        Write-Note "$($dep.Command): winget route unavailable; using the fallback installer..."
        & $dep.Fallback
        Update-SessionPath
    }
    if (-not (Get-Command $dep.Command -ErrorAction SilentlyContinue)) {
        throw "$($dep.Name) did not install cleanly. $($dep.Hint)"
    }
}

# --- Uninstall --------------------------------------------------------------
if ($Uninstall) {
    Write-Host 'Removing the agent skills system from this machine.' -ForegroundColor Cyan
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  Scheduled task '$TaskName' removed."
    foreach ($name in @('AGENT_SKILLS_FOLD', 'AGENT_SKILLS_PAT')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'User')
    }
    if (Test-Path $Dest) {
        $ans = Read-Host "  Also delete $Dest? Un-synced learnings in .manager will be lost [y/N]"
        if ($ans -match '^[Yy]') {
            Remove-Item -Recurse -Force $Dest
            Write-Host '  Managed clone removed.'
        } else {
            Write-Host "  Kept $Dest."
        }
    }
    Write-Host 'Uninstall complete. Installed dependencies (git, uv) were left in place.' -ForegroundColor Green
    return
}

# --- Banner + fail-early checks ----------------------------------------------
Write-Host ''
Write-Host 'Agent skills setup' -ForegroundColor Green
Write-Host '  Gives your coding agents the team skill library and keeps it fresh'
Write-Host '  with a nightly sync. Takes a few minutes; expect one Microsoft'
Write-Host '  sign-in window and possibly an installer consent prompt.'

if ($FoldMachine -and -not $env:AGENT_SKILLS_PAT) {
    throw '-FoldMachine requires $env:AGENT_SKILLS_PAT (Azure DevOps PAT, Code read & write) in this session.'
}

# --- 1. Dependencies -----------------------------------------------------------
Write-Step 'Installing dependencies'
foreach ($dep in $Dependencies) { Install-Dependency $dep }

# --- Maintainer configuration (fold machine only) ------------------------------
if ($FoldMachine) {
    Write-Host ''
    Write-Host '      Maintainer mode: enabling the nightly fold + proposal sweep.' -ForegroundColor Magenta
    [Environment]::SetEnvironmentVariable('AGENT_SKILLS_PAT', $env:AGENT_SKILLS_PAT, 'User')
    [Environment]::SetEnvironmentVariable('AGENT_SKILLS_FOLD', '1', 'User')
    $env:AGENT_SKILLS_FOLD = '1'
}

# --- 2. Clone the repo as ~/.agents --------------------------------------------
Write-Step 'Fetching the team skills repo'
if (-not $RepoUrl) { $RepoUrl = $env:AGENT_SKILLS_REPO_URL }
if (-not $RepoUrl) { $RepoUrl = $DefaultRepoUrl }
if (-not $RepoUrl -and $PSScriptRoot) {
    # try/catch: with EAP=Stop, PS 5.1 turns redirected native stderr into a
    # terminating error when this is not run from a clone.
    try { $RepoUrl = (git -C $PSScriptRoot remote get-url origin 2>$null) } catch { $RepoUrl = '' }
}
if (-not $RepoUrl) {
    throw 'No repo URL. Pass -RepoUrl <url>, set $env:AGENT_SKILLS_REPO_URL, ' +
          'or ask the maintainer to set $DefaultRepoUrl inside the hosted script.'
}
Write-Note "Repo: $RepoUrl"
Write-Note "Destination: $Dest"

if (Test-Path (Join-Path $Dest '.git')) {
    $existing = git -C $Dest remote get-url origin
    if ($existing -ne $RepoUrl) {
        throw "$Dest is already a git clone of '$existing', not '$RepoUrl'. Resolve manually, then re-run."
    }
    Write-Note 'Already cloned; the nightly job keeps it updated.'
} elseif (Test-Path $Dest) {
    throw "$Dest exists but is not a clone of the skills repo. Move it aside, then re-run."
} else {
    Write-Host ''
    Write-Host '      A Microsoft sign-in window may open now -- use your corporate' -ForegroundColor Yellow
    Write-Host '      account. It can open BEHIND other windows; check the taskbar' -ForegroundColor Yellow
    Write-Host '      if nothing seems to happen.' -ForegroundColor Yellow
    git clone $RepoUrl $Dest
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed (see message above). Fix the cause, then re-run this script."
    }
}

Write-Note 'Verifying the cached sign-in...'
git -C $Dest fetch origin
if ($LASTEXITCODE -ne 0) {
    throw "git could not authenticate to $RepoUrl. Run 'git -C $Dest fetch origin' " +
          'to retry the sign-in window, then re-run this script.'
}
Write-Note 'Sign-in cached -- the nightly task will reuse it silently.'

# --- 3. Nightly scheduled task --------------------------------------------------
Write-Step "Registering the nightly sync (daily at $TaskTime)"
$uvPath = (Get-Command uv).Source
New-Item -ItemType Directory -Force -Path (Join-Path $Dest '.manager') | Out-Null
$logPath = Join-Path $Dest '.manager\task.log'
$cmd = "Set-Location '$Dest'; & '$uvPath' run manage.py nightly *>> '$logPath'"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Note "Task '$TaskName' registered; it also catches up after a missed night."

# --- 4. First sync + verify ------------------------------------------------------
Write-Step 'Running the first sync (your machine will appear on the team dashboard)'
$syncOk = $true
Push-Location $Dest
try {
    & $uvPath run manage.py nightly
    if ($LASTEXITCODE -ne 0) { $syncOk = $false }
    & $uvPath run manage.py doctor
    if ($LASTEXITCODE -ne 0) { $syncOk = $false }
} finally {
    Pop-Location
}

# --- Done ------------------------------------------------------------------------
$elapsed = [int](New-TimeSpan -Start $StartTime -End (Get-Date)).TotalSeconds
Write-Host ''
if ($syncOk) {
    Write-Host "All set (took ${elapsed}s). Your coding agent now has the team skill library." -ForegroundColor Green
} else {
    Write-Host "Installed, but the first sync or health check reported a problem -- see above." -ForegroundColor Yellow
    Write-Host '  The nightly task will retry automatically; if this persists, send the' -ForegroundColor Yellow
    Write-Host "  output above (and $logPath) to the skills repo maintainer." -ForegroundColor Yellow
}
Write-Host "  Skills live in $Dest and update themselves nightly at $TaskTime."
Write-Host "  Sync log: $logPath"
Write-Host '  Try it now: open Cursor and ask "set up this Python repo to our standards".'
Write-Host '  If sync ever breaks: double-click fix-signin.cmd in the .agents folder.'
