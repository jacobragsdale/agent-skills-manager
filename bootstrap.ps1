# bootstrap.ps1 — one-time setup of the team agent-skills repo on a Windows machine.
#
# Clone the skills repo ANYWHERE (this throwaway clone is only how you obtain
# the script), then run from any PowerShell 5.1+ prompt (no admin required):
#
#   git clone <repo-url> skills-setup && cd skills-setup
#   powershell -ExecutionPolicy Bypass -File bootstrap.ps1
#
# No tokens, no configuration: when git first talks to Azure DevOps, a
# Microsoft sign-in window opens — use your corporate account. Git Credential
# Manager (bundled with Git for Windows) caches and silently refreshes the
# credential afterwards, including for the nightly scheduled task.
#
# What it does:
#   1. Installs prerequisites: git (with Git Credential Manager) and uv.
#   2. Clones the skills repo as %USERPROFILE%\.agents (the repo IS .agents)
#      and verifies the cached sign-in works.
#   3. If WSL is installed: installs uv, points WSL git at the Windows
#      credential manager, and clones ~/.agents inside WSL too.
#   4. Registers a daily Scheduled Task running `uv run manage.py nightly`
#      (pull updates, harvest learnings, drive the WSL leg — see manage.py).
#   5. Runs an initial sync (your machine shows up for the team immediately)
#      and a doctor check.
#
# If sign-in ever expires later, double-click fix-signin.cmd in %USERPROFILE%\.agents.
# Re-running this script is safe: every step is idempotent.

#Requires -Version 5.1
[CmdletBinding()]
param(
    # Defaults to the origin remote of the clone this script is running from.
    [string]$RepoUrl = '',
    # MAINTAINER ONLY: enables the nightly mechanical fold + proposal-PR sweep.
    # Requires $env:AGENT_SKILLS_PAT (Azure DevOps PAT, Code read & write) to
    # be set in this session; it is persisted for the scheduled task.
    [switch]$FoldMachine,
    [string]$TaskTime = '02:00'
)

$ErrorActionPreference = 'Stop'
$RequiredEnv = @()   # member machines need no env vars; extend if that changes
$Dest = Join-Path $HOME '.agents'
$TaskName = 'AgentSkillsNightly'

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

# --- 0. Resolve the repo URL from this clone ---------------------------------
if (-not $RepoUrl) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $RepoUrl = (git -C $PSScriptRoot remote get-url origin 2>$null)
    }
    if (-not $RepoUrl) {
        throw 'Could not determine the repo URL. Run this script from inside a clone ' +
              'of the skills repo, or pass -RepoUrl <url>.'
    }
}
Write-Host "Repo: $RepoUrl"

# --- 1. Fail early on missing configuration ----------------------------------
$missing = $RequiredEnv | Where-Object { -not [Environment]::GetEnvironmentVariable($_) }
if ($missing) { throw "Missing required env var(s): $($missing -join ', ')." }
if ($FoldMachine -and -not $env:AGENT_SKILLS_PAT) {
    throw '-FoldMachine requires $env:AGENT_SKILLS_PAT (Azure DevOps PAT, Code read & write) in this session.'
}

# --- 2. Prerequisites: git + uv ----------------------------------------------
Write-Step 'Ensuring git is installed'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
        Update-SessionPath
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'git is not installed and winget is unavailable. Install Git for Windows, then re-run.'
    }
}

Write-Step 'Ensuring uv is installed'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id astral-sh.uv -e --silent --accept-source-agreements --accept-package-agreements
        Update-SessionPath
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        Update-SessionPath
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv installation failed. Install it manually (https://docs.astral.sh/uv/), then re-run.'
    }
}

# --- 3. Maintainer configuration (fold machine only) --------------------------
if ($FoldMachine) {
    Write-Step 'Configuring this machine as the maintainer (fold + proposal sweep)'
    [Environment]::SetEnvironmentVariable('AGENT_SKILLS_PAT', $env:AGENT_SKILLS_PAT, 'User')
    [Environment]::SetEnvironmentVariable('AGENT_SKILLS_FOLD', '1', 'User')
    $env:AGENT_SKILLS_FOLD = '1'
}

# --- 4. Clone the repo as ~/.agents -------------------------------------------
Write-Step "Cloning skills repo into $Dest"
if (Test-Path (Join-Path $Dest '.git')) {
    $existing = git -C $Dest remote get-url origin
    if ($existing -ne $RepoUrl) {
        throw "$Dest is already a git clone of '$existing', not '$RepoUrl'. Resolve manually, then re-run."
    }
    Write-Host '    Already cloned; will update via the nightly job.'
} elseif (Test-Path $Dest) {
    throw "$Dest exists but is not a clone of the skills repo. Move it aside, then re-run."
} else {
    Write-Host '    If a Microsoft sign-in window opens, use your corporate account.' -ForegroundColor Yellow
    git clone $RepoUrl $Dest
}

Write-Step 'Verifying the cached Azure DevOps sign-in'
git -C $Dest fetch origin
if ($LASTEXITCODE -ne 0) {
    throw "git could not authenticate to $RepoUrl. Run 'git -C $Dest fetch origin' " +
          'to retry the sign-in window, then re-run this script.'
}
Write-Host '    Sign-in cached — the nightly task will reuse it silently.'

# --- 5. WSL: same setup inside, driven from Windows --------------------------
Write-Step 'Checking for WSL'
$wslDistros = @()
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    # wsl.exe emits UTF-16; strip nulls before testing.
    $wslDistros = (& wsl.exe -l -q 2>$null) -replace "`0", '' | Where-Object { $_.Trim() }
}
if ($wslDistros) {
    Write-Step "WSL detected ($($wslDistros[0].Trim())); installing uv and cloning ~/.agents inside it"
    $gcm = Get-ChildItem 'C:\Program Files\Git' -Recurse -Filter 'git-credential-manager.exe' -ErrorAction SilentlyContinue |
           Select-Object -First 1 -ExpandProperty FullName
    if (-not $gcm) { $gcm = 'C:\Program Files\Git\mingw64\bin\git-credential-manager.exe' }
    $gcmWsl = '/mnt/' + $gcm.Substring(0,1).ToLower() + ($gcm.Substring(2) -replace '\\', '/') -replace ' ', '\ '
    $bash = @'
set -e
for tool in git curl; do
  command -v "$tool" >/dev/null || { echo "ERROR: $tool missing in WSL. Run: sudo apt-get install -y git curl, then re-run bootstrap."; exit 1; }
done
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
git config --global credential.helper '__GCM__'
if [ -d "$HOME/.agents/.git" ]; then
  echo "~/.agents already cloned in WSL"
else
  git clone '__REPO_URL__' "$HOME/.agents"
fi
'@ -replace '__REPO_URL__', $RepoUrl -replace '__GCM__', $gcmWsl
    & wsl.exe -e bash -lc $bash
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'WSL setup failed (see message above). Windows setup continues; fix WSL and re-run.'
    }
} else {
    Write-Host '    WSL not present; Windows-only install.'
}

# --- 6. Nightly scheduled task ------------------------------------------------
Write-Step "Registering scheduled task '$TaskName' (daily at $TaskTime)"
$uvPath = (Get-Command uv).Source
New-Item -ItemType Directory -Force -Path (Join-Path $Dest '.manager') | Out-Null
$logPath = Join-Path $Dest '.manager\task.log'
$cmd = "Set-Location '$Dest'; & '$uvPath' run manage.py nightly *>> '$logPath'"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

# --- 7. First sync + verify ----------------------------------------------------
Write-Step 'Running the first sync (your machine will appear on the team dashboard)'
Push-Location $Dest
try {
    & $uvPath run manage.py nightly
    & $uvPath run manage.py doctor
    if ($LASTEXITCODE -ne 0) { Write-Warning 'doctor reported problems — see above.' }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Done. Your coding agent now has the team skill library.' -ForegroundColor Green
Write-Host "Skills live in ~/.agents and update themselves nightly at $TaskTime (log: $logPath)."
Write-Host 'Try it: open Cursor and ask "set up this Python repo to our standards".'
Write-Host 'If sync ever breaks, double-click fix-signin.cmd in your .agents folder.'
