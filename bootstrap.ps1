# bootstrap.ps1 - install the team Agent Skills runtime for a Windows 11 user.
#
# Maintainers set $DefaultRepoUrl before publishing this script. Members then
# run one command:
#
#   irm https://<internal-host>/bootstrap.ps1 | iex
#
# The skills repository is cloned under %LOCALAPPDATA%\AgentSkills\repo and
# treated as internal state. %USERPROFILE%\.agents is a generated view holding
# every skill in the repository. The nightly task pulls updates and rebuilds
# that view. Sync restores the internal clone to origin and never pushes it.
#
# This file stays ASCII because Windows PowerShell 5.1 reads BOM-less scripts
# fetched over HTTP as ANSI.

#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$RepoUrl = '',
    [string]$TaskTime = '02:00'
)

# Set before publishing the installer.
$DefaultRepoUrl = ''

$ErrorActionPreference = 'Stop'
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set for this Windows user.' }
$StateDir = Join-Path $env:LOCALAPPDATA 'AgentSkills'
$RuntimeDir = Join-Path $StateDir 'repo'
$ViewDir = Join-Path $HOME '.agents'
$ViewMarker = Join-Path $ViewDir '.agent-skills-managed'
$ToolsDir = Join-Path $StateDir 'tools'
$PythonDir = Join-Path $StateDir 'python'
$UvCacheDir = Join-Path $StateDir 'uv-cache'
$TaskName = 'AgentSkillsNightly'
$StartTime = Get-Date
$script:Step = 0
$TotalSteps = 6

# Pinned official release artifacts make missing-dependency installation
# deterministic and keep it entirely inside this user's LocalAppData. Update
# each URL and checksum together after validating a newer release.
$PortableGitUrl = 'https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.2/PortableGit-2.55.0.2-64-bit.7z.exe'
$PortableGitSha256 = 'b20d42da3afa228e9fa6174480de820282667e799440d655e308f700dfa0d0df'
$UvUrl = 'https://github.com/astral-sh/uv/releases/download/0.11.28/uv-x86_64-pc-windows-msvc.zip'
$UvSha256 = '0a23463216d09c6a72ff80ef5dc5a795f07dc1575cb84d24596c2f124a441b7b'
$ManagedPython = '3.14.6'

function Write-Step([string]$Message) {
    $script:Step++
    Write-Host ''
    Write-Host "[$($script:Step)/$TotalSteps] $Message" -ForegroundColor Cyan
}

function Write-Note([string]$Message) { Write-Host "      $Message" }

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Add-UserPath([string]$Directory) {
    $directoryKey = $Directory.TrimEnd('\')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ })
    $present = $entries | Where-Object { $_.TrimEnd('\') -ieq $directoryKey }
    if (-not $present) {
        $entries += $Directory
        [Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
    }
    Update-SessionPath
}

function Save-VerifiedDownload(
    [string]$Url,
    [string]$ExpectedSha256,
    [string]$Destination
) {
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
        if ($actual -ne $ExpectedSha256) {
            throw "Checksum mismatch for $Url (expected $ExpectedSha256, got $actual)."
        }
    } catch {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Install-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Note 'git: already installed.'
        return
    }

    Write-Note 'git: installing the pinned portable Git for Windows release per-user...'
    $installDir = Join-Path $ToolsDir 'git'
    $archive = Join-Path $env:TEMP 'AgentSkills-PortableGit.exe'
    Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
    Save-VerifiedDownload $PortableGitUrl $PortableGitSha256 $archive
    try {
        & $archive "-o$installDir" -y | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Portable Git extraction failed with exit code $LASTEXITCODE." }
    } finally {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
    $commandDir = Join-Path $installDir 'cmd'
    if (-not (Test-Path (Join-Path $commandDir 'git.exe'))) {
        throw 'Portable Git extraction did not produce cmd\git.exe.'
    }
    Add-UserPath $commandDir
}

function Install-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Note 'uv: already installed.'
        return
    }

    Write-Note 'uv: installing the pinned official release per-user...'
    $installDir = Join-Path $ToolsDir 'uv'
    $archive = Join-Path $env:TEMP 'AgentSkills-uv.zip'
    Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
    Save-VerifiedDownload $UvUrl $UvSha256 $archive
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $installDir -Force
    } finally {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path (Join-Path $installDir 'uv.exe'))) {
        throw 'uv extraction did not produce uv.exe.'
    }
    Add-UserPath $installDir
}

function Install-Python([string]$UvPath) {
    $configured = [Environment]::GetEnvironmentVariable('AGENT_SKILLS_PYTHON', 'User')
    if ($configured -and (Test-Path $configured -PathType Leaf)) {
        Write-Note 'python: already installed for Agent Skills.'
        $env:AGENT_SKILLS_PYTHON = $configured
        $script:AgentSkillsPython = $configured
        return
    }

    Write-Note "python: installing managed Python $ManagedPython per-user..."
    Remove-Item -LiteralPath $PythonDir -Recurse -Force -ErrorAction SilentlyContinue
    $previousErrorPreference = $ErrorActionPreference
    try {
        # Windows PowerShell promotes redirected native stderr to an error
        # record. uv writes progress there, so keep it non-terminating here.
        $ErrorActionPreference = 'Continue'
        & $UvPath python install $ManagedPython --install-dir $PythonDir --no-bin `
            --no-registry --cache-dir $UvCacheDir 2>$null
        $installExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }

    # Some hardened Windows sessions refuse to traverse uv's convenience
    # junction even though the versioned Python installation is valid. The
    # runtime always uses the real versioned interpreter, so remove junctions.
    $junctions = Get-ChildItem -LiteralPath $PythonDir -Directory -Force `
        -ErrorAction SilentlyContinue | Where-Object {
            $_.Attributes -band [IO.FileAttributes]::ReparsePoint
        }
    foreach ($junction in $junctions) {
        Remove-Item -LiteralPath $junction.FullName -Force
    }

    $pythonPath = Get-ChildItem -LiteralPath $PythonDir -Directory `
        -ErrorAction SilentlyContinue | Where-Object {
            -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        } | Sort-Object Name -Descending | ForEach-Object {
            Join-Path $_.FullName 'python.exe'
        } | Where-Object {
            Test-Path $_ -PathType Leaf
        } | Select-Object -First 1

    if (-not $pythonPath) {
        throw "Managed Python installation failed with exit code $installExit."
    }
    & $pythonPath -c 'import json, pathlib, subprocess, tempfile, uuid'
    if ($LASTEXITCODE -ne 0) { throw 'The managed Python interpreter failed its import check.' }
    if ($installExit -ne 0) {
        Write-Note 'python: ignored an unusable convenience junction; the real interpreter is healthy.'
    }
    [Environment]::SetEnvironmentVariable('AGENT_SKILLS_PYTHON', $pythonPath, 'User')
    $env:AGENT_SKILLS_PYTHON = $pythonPath
    $script:AgentSkillsPython = $pythonPath
}

function Register-NightlyTask([string]$Command) {
    try {
        $clock = [datetime]::ParseExact(
            $TaskTime,
            'HH:mm',
            [Globalization.CultureInfo]::InvariantCulture
        )
    } catch {
        throw "TaskTime must use 24-hour HH:mm format: $TaskTime"
    }

    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = `
        'Pulls Agent Skills updates and rebuilds the Cursor view.'
    $definition.Principal.LogonType = 3  # TASK_LOGON_INTERACTIVE_TOKEN
    $definition.Principal.RunLevel = 0  # TASK_RUNLEVEL_LUA
    $definition.Settings.Enabled = $true
    $definition.Settings.StartWhenAvailable = $true
    $definition.Settings.ExecutionTimeLimit = 'PT1H'
    $definition.Settings.MultipleInstances = 2  # TASK_INSTANCES_IGNORE_NEW

    $action = $definition.Actions.Create(0)  # TASK_ACTION_EXEC
    $action.Path = 'powershell.exe'
    $action.Arguments = `
        "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$Command`""

    $trigger = $definition.Triggers.Create(2)  # TASK_TRIGGER_DAILY
    $trigger.StartBoundary = (Get-Date).Date.AddHours($clock.Hour).AddMinutes($clock.Minute).ToString('s')
    $trigger.DaysInterval = 1
    $trigger.Enabled = $true

    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $registered = $folder.RegisterTaskDefinition(
        $TaskName,
        $definition,
        6,  # TASK_CREATE_OR_UPDATE
        $currentUser,
        $null,
        3,  # TASK_LOGON_INTERACTIVE_TOKEN
        $null
    )
    if (-not $registered) { throw "Task '$TaskName' was not registered." }
}

Write-Host ''
Write-Host 'Team Agent Skills setup' -ForegroundColor Green
Write-Host '  Installs a read-only Cursor skill runtime.'
Write-Host '  Runs entirely as the current user; no administrator prompt is required.'
Write-Host '  Expect one corporate sign-in window when private repositories need authentication.'

Write-Step 'Installing dependencies'
[Net.ServicePointManager]::SecurityProtocol = `
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
Install-Git
Install-Uv
$uvPath = (Get-Command uv).Source
Install-Python $uvPath
$pythonPath = $script:AgentSkillsPython

Write-Step 'Resolving the skills repository'
if (-not $RepoUrl) { $RepoUrl = $env:AGENT_SKILLS_REPO_URL }
if (-not $RepoUrl) { $RepoUrl = $DefaultRepoUrl }
if (-not $RepoUrl -and $PSScriptRoot) {
    try { $RepoUrl = (git -C $PSScriptRoot remote get-url origin 2>$null) } catch { $RepoUrl = '' }
}
if (-not $RepoUrl) {
    throw 'No skills repo URL. Pass -RepoUrl, set AGENT_SKILLS_REPO_URL, or configure $DefaultRepoUrl.'
}
Write-Note "Skills (read-only): $RepoUrl"
Write-Note "Runtime clone: $RuntimeDir"
Write-Note "Skills view (Cursor reads this): $ViewDir"

Write-Step 'Installing the read-only runtime checkout'
if (Test-Path (Join-Path $ViewDir '.git')) {
    throw "$ViewDir is a Git clone from an older layout. Remove it per the README, then re-run."
}
if ((Test-Path $ViewDir) -and -not (Test-Path $ViewMarker)) {
    throw "$ViewDir exists but is not a managed skills view. Move it aside, then re-run."
}
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
if (Test-Path (Join-Path $RuntimeDir '.git')) {
    $existing = git -C $RuntimeDir remote get-url origin
    if ($existing -ne $RepoUrl) {
        throw "$RuntimeDir points at '$existing', not '$RepoUrl'. Resolve it manually, then re-run."
    }
    Write-Note 'Runtime already cloned.'
} elseif (Test-Path $RuntimeDir) {
    throw "$RuntimeDir exists but is not a Git clone. Move it aside, then re-run."
} else {
    Write-Host '      A Microsoft sign-in window may open behind this console.' -ForegroundColor Yellow
    git clone $RepoUrl $RuntimeDir
    if ($LASTEXITCODE -ne 0) { throw 'Skills repository clone failed.' }
}
git -C $RuntimeDir fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Could not fetch the skills repository.' }

Write-Step 'Configuring isolated local state'
New-Item -ItemType Directory -Force -Path (Join-Path $StateDir 'logs') | Out-Null
Push-Location $RuntimeDir
try {
    & $pythonPath manage.py configure --runtime-path $RuntimeDir --repo-url $RepoUrl `
        --view-path $ViewDir --branch main --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { throw 'Manager configuration failed.' }
} finally {
    Pop-Location
}

Write-Step "Registering the nightly sync (daily at $TaskTime)"
$logPath = Join-Path $StateDir 'logs\task.log'
$runtimeEscaped = $RuntimeDir -replace "'", "''"
$stateEscaped = $StateDir -replace "'", "''"
$pythonEscaped = $pythonPath -replace "'", "''"
$logEscaped = $logPath -replace "'", "''"
$command = "Set-Location '$runtimeEscaped'; & '$pythonEscaped' manage.py sync --state-dir '$stateEscaped' *>> '$logEscaped'"
Register-NightlyTask $command
Write-Note "Task '$TaskName' registered."

Write-Step 'Verifying the install'
$healthy = $true
Push-Location $RuntimeDir
try {
    & $pythonPath manage.py sync --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { $healthy = $false }
    & $pythonPath manage.py doctor --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { $healthy = $false }
} finally {
    Pop-Location
}

$elapsed = [int](New-TimeSpan -Start $StartTime -End (Get-Date)).TotalSeconds
Write-Host ''
if (-not $healthy) {
    Write-Host 'Installation finished, but verification failed. See the output above and:' -ForegroundColor Red
    Write-Host "  $logPath" -ForegroundColor Red
    exit 1
}
Write-Host "All set (took ${elapsed}s). Cursor can now discover the team skills." -ForegroundColor Green
Write-Host "  Skills view: $ViewDir"
Write-Host "  Runtime clone, state, and logs: $StateDir"
Write-Host "  Repair expired sign-in: git -C '$RuntimeDir' fetch"
Write-Host '  Try: open Cursor and ask "set up this Python repo to our standards".'
