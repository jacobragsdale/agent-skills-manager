# bootstrap.ps1 — one-time setup of the team agent-skills repo on a Windows machine.
#
# Clone the skills repo ANYWHERE (this throwaway clone is only how you obtain
# the script), then run from any PowerShell 5.1+ prompt (no admin required):
#
#   git clone <repo-url> skills-setup && cd skills-setup
#   $env:AGENT_SKILLS_PAT = '<your Azure DevOps PAT, Code read & write>'
#   powershell -ExecutionPolicy Bypass -File bootstrap.ps1
#
# The repo URL is taken from this clone's own `origin` remote (override with
# -RepoUrl). Bootstrap then creates the managed clone at %USERPROFILE%\.agents;
# the folder you ran from can be deleted afterwards.
#
# What it does:
#   1. Fails early if required env vars are missing (AGENT_SKILLS_PAT).
#   2. Installs prerequisites: git and uv (winget, with fallbacks).
#   3. Persists the PAT as a user env var and exposes it to WSL via WSLENV.
#   4. Clones the skills repo as %USERPROFILE%\.agents (the repo IS .agents).
#   5. If WSL is installed: installs uv and clones ~/.agents inside WSL too.
#   6. Registers a daily Scheduled Task that runs `uv run manage.py nightly`
#      (pull updates, harvest learnings, drive the WSL leg — see manage.py).
#   7. Runs `manage.py doctor` to verify the install.
#
# Re-running is safe: every step is idempotent.

#Requires -Version 5.1
[CmdletBinding()]
param(
    # Defaults to the origin remote of the clone this script is running from.
    [string]$RepoUrl = '',
    # Pass on exactly ONE machine to run the nightly MECHANICAL fold + PR
    # (manage.py fold). Skip it everywhere if a weekly agent-driven fold job
    # (prompts/weekly-learnings-fold.md) owns folding instead.
    [switch]$FoldMachine,
    [string]$TaskTime = '02:00'
)

$ErrorActionPreference = 'Stop'
$RequiredEnv = @('AGENT_SKILLS_PAT')   # extend as more required config appears
$Dest = Join-Path $HOME '.agents'
$TaskName = 'AgentSkillsNightly'

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Get-AuthHeader {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes(":$($env:AGENT_SKILLS_PAT)"))
    return "AUTHORIZATION: Basic $b64"
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

# --- 1. Fail early on missing env vars --------------------------------------
Write-Step 'Checking required environment variables'
$missing = $RequiredEnv | Where-Object { -not [Environment]::GetEnvironmentVariable($_) }
if ($missing) {
    throw "Missing required env var(s): $($missing -join ', '). " +
          "Set them in this session first, e.g.  `$env:AGENT_SKILLS_PAT = '<pat>'  " +
          '(Azure DevOps PAT with Code read & write scope).'
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

# --- 3. Persist env vars (scheduled task + WSL need them) --------------------
Write-Step 'Persisting environment variables for the scheduled task and WSL'
foreach ($name in $RequiredEnv) {
    [Environment]::SetEnvironmentVariable($name, [Environment]::GetEnvironmentVariable($name), 'User')
}
$wslenv = [Environment]::GetEnvironmentVariable('WSLENV', 'User')
$wslFlags = ($RequiredEnv | ForEach-Object { "$_/u" })
foreach ($flag in $wslFlags) {
    if (-not ($wslenv -split ':' -contains $flag)) { $wslenv = (@($wslenv, $flag) -ne '') -join ':' }
}
[Environment]::SetEnvironmentVariable('WSLENV', $wslenv, 'User')
$env:WSLENV = $wslenv
if ($FoldMachine) {
    [Environment]::SetEnvironmentVariable('AGENT_SKILLS_FOLD', '1', 'User')
    $env:AGENT_SKILLS_FOLD = '1'
    Write-Host '    This machine is designated as the learnings fold machine.'
}

# --- 4. Clone the repo as ~/.agents ------------------------------------------
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
    git -c "http.extraheader=$(Get-AuthHeader)" clone $RepoUrl $Dest
}

# --- 5. WSL: same setup inside, driven from Windows --------------------------
Write-Step 'Checking for WSL'
$wslDistros = @()
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    # wsl.exe emits UTF-16; strip nulls before testing.
    $wslDistros = (& wsl.exe -l -q 2>$null) -replace "`0", '' | Where-Object { $_.Trim() }
}
if ($wslDistros) {
    Write-Step "WSL detected ($($wslDistros[0].Trim())); installing uv and cloning ~/.agents inside it"
    $bash = @'
set -e
for tool in git curl; do
  command -v "$tool" >/dev/null || { echo "ERROR: $tool missing in WSL. Run: sudo apt-get install -y git curl, then re-run bootstrap."; exit 1; }
done
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
B64=$(printf ':%s' "$AGENT_SKILLS_PAT" | base64 | tr -d '\n')
if [ -d "$HOME/.agents/.git" ]; then
  echo "~/.agents already cloned in WSL"
else
  git -c "http.extraheader=AUTHORIZATION: Basic $B64" clone '__REPO_URL__' "$HOME/.agents"
fi
'@ -replace '__REPO_URL__', $RepoUrl
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

# --- 7. Verify ----------------------------------------------------------------
Write-Step 'Running doctor'
Push-Location $Dest
try {
    & $uvPath run manage.py doctor
    if ($LASTEXITCODE -ne 0) { Write-Warning 'doctor reported problems — see above.' }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Done. Skills live in ~/.agents (and ~/.agents inside WSL if present).' -ForegroundColor Green
Write-Host "Nightly sync runs at $TaskTime via Task Scheduler ('$TaskName'); log: $logPath"
