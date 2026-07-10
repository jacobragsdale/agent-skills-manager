# uninstall.ps1 - remove the team Agent Skills runtime for one Windows user.
#
# This file stays ASCII because Windows PowerShell 5.1 reads BOM-less scripts
# fetched over HTTP as ANSI. It does not require uv, network access, or a
# working runtime checkout. Git is used only to protect runtime files.

#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$KeepState,
    [switch]$RemoveModifiedRuntime,
    [switch]$Pause,
    [switch]$FromTemp
)

$ErrorActionPreference = 'Stop'

# Run from a temporary copy so the installed uninstaller can remove itself.
$scriptPath = $MyInvocation.MyCommand.Path
if (-not $FromTemp -and $scriptPath -and (Test-Path $scriptPath -PathType Leaf)) {
    $tempPath = Join-Path ([IO.Path]::GetTempPath()) `
        ("AgentSkills-uninstall-{0}.ps1" -f [guid]::NewGuid().ToString('N'))
    Copy-Item -Force $scriptPath $tempPath
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $tempPath, '-FromTemp')
    if ($Force) { $arguments += '-Force' }
    if ($KeepState) { $arguments += '-KeepState' }
    if ($RemoveModifiedRuntime) { $arguments += '-RemoveModifiedRuntime' }
    if ($Pause) { $arguments += '-Pause' }
    & powershell.exe @arguments
    $childExitCode = $LASTEXITCODE
    Remove-Item -Force $tempPath -ErrorAction SilentlyContinue
    exit $childExitCode
}

if (-not $env:LOCALAPPDATA) {
    throw 'LOCALAPPDATA is not set for this Windows user.'
}

$RuntimeDir = Join-Path $HOME '.agents'
$StateDir = Join-Path $env:LOCALAPPDATA 'AgentSkills'
$UninstallDir = Join-Path $StateDir 'uninstall'
$ManifestPath = Join-Path $UninstallDir 'install.json'
$ConfigPath = Join-Path $StateDir 'config.json'
$TaskName = 'AgentSkillsNightly'
$UninstallRegistryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentSkills'
$script:Removed = New-Object System.Collections.Generic.List[string]
$script:Retained = New-Object System.Collections.Generic.List[string]

function Finish([int]$Code) {
    Write-Host ''
    if ($script:Removed.Count -gt 0) {
        Write-Host 'Removed:' -ForegroundColor Green
        foreach ($item in $script:Removed) { Write-Host "  - $item" }
    }
    if ($script:Retained.Count -gt 0) {
        Write-Host 'Retained:' -ForegroundColor Yellow
        foreach ($item in $script:Retained) { Write-Host "  - $item" }
    }
    Write-Host 'Git, uv, shared Git credentials, and previously published data were not removed.'
    if ($Code -eq 0) {
        Write-Host 'Team Agent Skills was uninstalled for this Windows user.' -ForegroundColor Green
    } elseif ($Code -eq 2) {
        Write-Host 'Uninstall was only partially completed; see the retained items above.' -ForegroundColor Yellow
    } else {
        Write-Host 'Uninstall did not complete; it is safe to run again.' -ForegroundColor Red
    }
    if ($Pause) { Read-Host 'Press Enter to close' | Out-Null }
    exit $Code
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path $Path -PathType Leaf)) { return $null }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Normalize-RepoUrl([string]$Value) {
    if (-not $Value) { return '' }
    $normalized = $Value.Trim().Replace('\', '/').TrimEnd('/')
    if ($normalized.EndsWith('.git', [StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(0, $normalized.Length - 4)
    }
    return $normalized.ToLowerInvariant()
}

function Get-RuntimeStatus([object]$Manifest, [object]$Config) {
    if (-not (Test-Path $RuntimeDir)) {
        return [pscustomobject]@{ Kind = 'missing'; Detail = 'runtime is already absent' }
    }
    if (-not (Test-Path (Join-Path $RuntimeDir '.git'))) {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'runtime path is not a Git checkout' }
    }

    $expectedPath = ''
    $expectedUrl = ''
    if ($Manifest) {
        $expectedPath = [string]$Manifest.runtime_path
        $expectedUrl = [string]$Manifest.runtime_repo_url
    } elseif ($Config) {
        $expectedPath = [string]$Config.runtime_path
        $expectedUrl = [string]$Config.runtime_repo_url
    }
    if (-not $expectedPath -or -not $expectedUrl) {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'installation ownership metadata is missing' }
    }
    try {
        $resolvedExpected = [IO.Path]::GetFullPath($expectedPath).TrimEnd('\')
        $resolvedRuntime = [IO.Path]::GetFullPath($RuntimeDir).TrimEnd('\')
    } catch {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'installation ownership path is invalid' }
    }
    if (-not $resolvedExpected.Equals($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'installation metadata points at another runtime path' }
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'Git is unavailable, so runtime ownership cannot be verified' }
    }
    $origin = (& git -C $RuntimeDir remote get-url origin 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or
        (Normalize-RepoUrl $origin) -ne (Normalize-RepoUrl $expectedUrl)) {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'runtime origin does not match the installed repository' }
    }
    $changes = (& git -C $RuntimeDir status --porcelain --untracked-files=all 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        return [pscustomobject]@{ Kind = 'unrecognized'; Detail = 'runtime changes could not be inspected' }
    }
    if ($changes) {
        return [pscustomobject]@{ Kind = 'modified'; Detail = 'runtime contains local changes or untracked files' }
    }
    return [pscustomobject]@{ Kind = 'clean'; Detail = 'managed runtime is clean' }
}

function Stop-AndRemoveTask {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $task = Get-AgentTask $folder
    if (-not $task) {
        $script:Removed.Add("scheduled task $TaskName (already absent)")
        return
    }
    if ($task.State -eq 4) {  # TASK_STATE_RUNNING
        $task.Stop(0)
        $deadline = (Get-Date).AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 250
            $task = Get-AgentTask $folder
        } while ($task -and $task.State -eq 4 -and (Get-Date) -lt $deadline)
        if ($task -and $task.State -eq 4) {
            throw "scheduled task '$TaskName' did not stop within 15 seconds"
        }
    }
    $folder.DeleteTask($TaskName, 0)
    if (Get-AgentTask $folder) {
        throw "scheduled task '$TaskName' is still registered"
    }
    $script:Removed.Add("scheduled task $TaskName")
}

function Get-AgentTask([object]$Folder) {
    try {
        return $Folder.GetTask("\$TaskName")
    } catch {
        if ($_.Exception.HResult -eq -2147024894) { return $null }
        throw
    }
}

Set-Location $HOME
$manifest = Read-JsonFile $ManifestPath
$config = Read-JsonFile $ConfigPath
$pendingDir = Join-Path $StateDir 'events\pending'
$pendingCount = @(Get-ChildItem -LiteralPath $pendingDir -Filter '*.json' `
    -ErrorAction SilentlyContinue).Count
$machineId = if ($config) { [string]$config.machine_id } else { '' }
$runtimeStatus = Get-RuntimeStatus $manifest $config

Write-Host ''
Write-Host 'Team Agent Skills uninstall' -ForegroundColor Cyan
Write-Host "  Runtime: $RuntimeDir ($($runtimeStatus.Detail))"
Write-Host "  Local state: $StateDir ($pendingCount pending event(s))"
Write-Host "  Scheduled task: $TaskName"
if ($machineId) {
    Write-Host "  Installation ID: $machineId"
    Write-Host '  Save this ID before deleting state if you may request deletion of published data.'
}
Write-Host '  Local uninstall does not delete data already published to the inbox repository.'

$deleteRuntime = $runtimeStatus.Kind -eq 'clean'
$protectedRuntime = $runtimeStatus.Kind -eq 'unrecognized'
if ($runtimeStatus.Kind -eq 'modified') {
    if ($RemoveModifiedRuntime) {
        $deleteRuntime = $true
    } elseif ($Force) {
        Write-Host 'ERROR: The runtime is modified. Re-run with -RemoveModifiedRuntime to delete it explicitly.' -ForegroundColor Red
        Finish 1
    } else {
        $answer = Read-Host 'The runtime contains local changes. Type DELETE to remove it, or press Enter to cancel'
        if ($answer -cne 'DELETE') {
            Write-Host 'Uninstall canceled; no changes were made.' -ForegroundColor Yellow
            Finish 1
        }
        $deleteRuntime = $true
    }
}

if (-not $Force) {
    if ($pendingCount -gt 0 -and -not $KeepState) {
        $answer = Read-Host "Delete $pendingCount unsent event(s), [K]eep local state, or [C]ancel? [d/K/c]"
        if ($answer -match '^[Dd]$') {
            $KeepState = $false
        } elseif ($answer -match '^[Cc]$') {
            Write-Host 'Uninstall canceled; no changes were made.' -ForegroundColor Yellow
            Finish 1
        } else {
            $KeepState = $true
        }
    }
    $answer = Read-Host 'Continue with uninstall? [y/N]'
    if ($answer -notmatch '^[Yy]') {
        Write-Host 'Uninstall canceled; no changes were made.' -ForegroundColor Yellow
        Finish 1
    }
}

try {
    Stop-AndRemoveTask

    if ($deleteRuntime -and (Test-Path $RuntimeDir)) {
        Remove-Item -LiteralPath $RuntimeDir -Recurse -Force
        if (Test-Path $RuntimeDir) { throw "runtime still exists: $RuntimeDir" }
        $script:Removed.Add("runtime $RuntimeDir")
    } elseif ($runtimeStatus.Kind -eq 'missing') {
        $script:Removed.Add("runtime $RuntimeDir (already absent)")
    } elseif ($protectedRuntime) {
        $script:Retained.Add("unrecognized runtime $RuntimeDir ($($runtimeStatus.Detail))")
    }

    if ($protectedRuntime) {
        if (Test-Path $StateDir) {
            $script:Retained.Add("local state $StateDir, including retry metadata")
        }
    } elseif ($KeepState) {
        if (Test-Path $StateDir) { $script:Retained.Add("local state $StateDir") }
    } elseif (Test-Path $StateDir) {
        Remove-Item -LiteralPath $StateDir -Recurse -Force
        if (Test-Path $StateDir) { throw "local state still exists: $StateDir" }
        $script:Removed.Add("local state $StateDir")
    } else {
        $script:Removed.Add("local state $StateDir (already absent)")
    }

    if ($protectedRuntime) {
        $script:Retained.Add('Windows Installed apps entry, so cleanup can be retried')
        Finish 2
    }

    Remove-Item -Path $UninstallRegistryKey -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $UninstallRegistryKey) {
        throw 'Windows Installed apps entry could not be removed'
    }
    $script:Removed.Add('Windows Installed apps entry')

    if (Test-Path $UninstallDir) {
        Remove-Item -LiteralPath $UninstallDir -Recurse -Force
        if (Test-Path $UninstallDir) { throw "uninstaller files still exist: $UninstallDir" }
    }
    $script:Removed.Add('installed uninstaller files')
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Finish 1
}

Finish 0
