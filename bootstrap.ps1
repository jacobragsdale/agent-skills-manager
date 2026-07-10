# bootstrap.ps1 - install the team Agent Skills runtime for a Windows 11 user.
#
# Maintainers set $DefaultRepoUrl and $DefaultInboxRepoUrl before publishing
# this script. Members then run one command:
#
#   irm https://<internal-host>/bootstrap.ps1 | iex
#
# The skills clone at %USERPROFILE%\.agents is runtime-only. All mutable state
# (events, logs, config, locks, and the local inbox clone) lives under
# %LOCALAPPDATA%\AgentSkills. The nightly task publishes only to this machine's
# inbox branch and fast-forwards a clean runtime checkout; it never resets or
# pushes the skills repository.
#
# This file stays ASCII because Windows PowerShell 5.1 reads BOM-less scripts
# fetched over HTTP as ANSI.

#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$RepoUrl = '',
    [string]$InboxRepoUrl = '',
    [string]$TaskTime = '02:00',
    [switch]$Uninstall
)

# Set both before publishing the installer.
$DefaultRepoUrl = ''
$DefaultInboxRepoUrl = ''

$Dependencies = @(
    @{ Command = 'git'
       Name = 'Git for Windows (includes Git Credential Manager)'
       WingetId = 'Git.Git'
       Hint = 'Install Git for Windows manually, then re-run.' }
    @{ Command = 'uv'
       Name = 'uv (runs the sync tooling)'
       WingetId = 'astral-sh.uv'
       Fallback = { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
       Hint = 'Install uv manually from https://docs.astral.sh/uv/, then re-run.' }
)

$ErrorActionPreference = 'Stop'
$RuntimeDir = Join-Path $HOME '.agents'
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set for this Windows user.' }
$StateDir = Join-Path $env:LOCALAPPDATA 'AgentSkills'
$UninstallDir = Join-Path $StateDir 'uninstall'
$UninstallRegistryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentSkills'
$TaskName = 'AgentSkillsNightly'
$StartTime = Get-Date
$script:Step = 0
$TotalSteps = 7

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

function Install-Dependency([hashtable]$Dependency) {
    if (Get-Command $Dependency.Command -ErrorAction SilentlyContinue) {
        Write-Note "$($Dependency.Command): already installed."
        return
    }
    Write-Note "$($Dependency.Command): installing $($Dependency.Name)..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id $Dependency.WingetId -e --silent --source winget `
            --disable-interactivity --accept-source-agreements --accept-package-agreements
        Update-SessionPath
    }
    if (-not (Get-Command $Dependency.Command -ErrorAction SilentlyContinue) -and $Dependency.Fallback) {
        Write-Note "$($Dependency.Command): winget unavailable; using the fallback installer..."
        & $Dependency.Fallback
        Update-SessionPath
    }
    if (-not (Get-Command $Dependency.Command -ErrorAction SilentlyContinue)) {
        throw "$($Dependency.Name) did not install cleanly. $($Dependency.Hint)"
    }
}

function Install-Uninstaller {
    $source = Join-Path $RuntimeDir 'uninstall.ps1'
    if (-not (Test-Path $source -PathType Leaf)) {
        throw "The runtime does not contain uninstall.ps1: $source"
    }

    New-Item -ItemType Directory -Force -Path $UninstallDir | Out-Null
    $target = Join-Path $UninstallDir 'uninstall.ps1'
    Copy-Item -Force $source $target

    $manifest = [ordered]@{
        schema_version = 1
        runtime_path = $RuntimeDir
        runtime_repo_url = $RepoUrl
        state_path = $StateDir
    }
    $manifest | ConvertTo-Json | Set-Content -Encoding UTF8 `
        (Join-Path $UninstallDir 'install.json')

    $version = (git -C $RuntimeDir rev-parse --short=12 HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw 'Could not determine the installed runtime version.'
    }
    $uninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$target`" -Pause"
    New-Item -Path $UninstallRegistryKey -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name DisplayName `
        -Value 'Team Agent Skills' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name DisplayVersion `
        -Value $version -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name Publisher `
        -Value 'Team Agent Skills' -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name InstallLocation `
        -Value $RuntimeDir -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name UninstallString `
        -Value $uninstallString -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name NoModify `
        -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $UninstallRegistryKey -Name NoRepair `
        -Value 1 -PropertyType DWord -Force | Out-Null
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
        'Publishes Agent Skills events and safely fast-forwards the runtime.'
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

if ($Uninstall) {
    $candidates = @(
        (Join-Path $UninstallDir 'uninstall.ps1'),
        $(if ($PSScriptRoot) { Join-Path $PSScriptRoot 'uninstall.ps1' })
    ) | Where-Object { $_ -and (Test-Path $_ -PathType Leaf) }
    $uninstaller = $candidates | Select-Object -First 1
    if (-not $uninstaller) {
        throw 'uninstall.ps1 was not found. Download it from the same internal location as bootstrap.ps1.'
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstaller
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host 'Team Agent Skills setup' -ForegroundColor Green
Write-Host '  Installs a read-only Cursor skill runtime and a separate local event spool.'
Write-Host '  Expect one corporate sign-in window and possibly an installer consent prompt.'

Write-Step 'Installing dependencies'
foreach ($dependency in $Dependencies) { Install-Dependency $dependency }

Write-Step 'Resolving the two repositories'
if (-not $RepoUrl) { $RepoUrl = $env:AGENT_SKILLS_REPO_URL }
if (-not $RepoUrl) { $RepoUrl = $DefaultRepoUrl }
if (-not $RepoUrl -and $PSScriptRoot) {
    try { $RepoUrl = (git -C $PSScriptRoot remote get-url origin 2>$null) } catch { $RepoUrl = '' }
}
if (-not $InboxRepoUrl) { $InboxRepoUrl = $env:AGENT_SKILLS_INBOX_URL }
if (-not $InboxRepoUrl) { $InboxRepoUrl = $DefaultInboxRepoUrl }
if (-not $RepoUrl) {
    throw 'No skills repo URL. Pass -RepoUrl, set AGENT_SKILLS_REPO_URL, or configure $DefaultRepoUrl.'
}
if (-not $InboxRepoUrl) {
    throw 'No inbox repo URL. Pass -InboxRepoUrl, set AGENT_SKILLS_INBOX_URL, or configure $DefaultInboxRepoUrl.'
}
Write-Note "Skills (read-only): $RepoUrl"
Write-Note "Inbox (machine branches): $InboxRepoUrl"
Write-Note "Runtime: $RuntimeDir"
Write-Note "Local state: $StateDir"

Write-Step 'Installing the read-only runtime checkout'
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
git ls-remote --heads $InboxRepoUrl | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not authenticate to the inbox repository.' }

Write-Step 'Configuring isolated local state'
$uvPath = (Get-Command uv).Source
New-Item -ItemType Directory -Force -Path (Join-Path $StateDir 'logs') | Out-Null
Push-Location $RuntimeDir
try {
    & $uvPath run manage.py configure --runtime-path $RuntimeDir --repo-url $RepoUrl `
        --inbox-repo-url $InboxRepoUrl --branch main --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { throw 'Manager configuration failed.' }
} finally {
    Pop-Location
}

Write-Step 'Registering Windows uninstall support'
Install-Uninstaller
Write-Note 'Available in Windows Settings under Installed apps.'

Write-Step "Registering the nightly sync (daily at $TaskTime)"
$logPath = Join-Path $StateDir 'logs\task.log'
$runtimeEscaped = $RuntimeDir -replace "'", "''"
$stateEscaped = $StateDir -replace "'", "''"
$uvEscaped = $uvPath -replace "'", "''"
$logEscaped = $logPath -replace "'", "''"
$command = "Set-Location '$runtimeEscaped'; & '$uvEscaped' run manage.py nightly --state-dir '$stateEscaped' *>> '$logEscaped'"
Register-NightlyTask $command
Write-Note "Task '$TaskName' registered."

Write-Step 'Publishing the first heartbeat and verifying the install'
$healthy = $true
Push-Location $RuntimeDir
try {
    & $uvPath run manage.py nightly --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { $healthy = $false }
    & $uvPath run manage.py doctor --state-dir $StateDir
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
Write-Host "  Runtime: $RuntimeDir"
Write-Host "  Local state and logs: $StateDir"
Write-Host '  Uninstall: Windows Settings > Apps > Installed apps > Team Agent Skills.'
Write-Host '  Repair expired sign-in: double-click fix-signin.cmd in the runtime folder.'
Write-Host '  Try: open Cursor and ask "set up this Python repo to our standards".'
