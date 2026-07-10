# Refresh Git Credential Manager sign-in for both Agent Skills repositories.
# This file stays ASCII for Windows PowerShell 5.1.

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

if (-not $env:LOCALAPPDATA) {
    throw 'LOCALAPPDATA is not set for this Windows user.'
}
$configPath = Join-Path $env:LOCALAPPDATA 'AgentSkills\config.json'
if (-not (Test-Path $configPath -PathType Leaf)) {
    throw "Agent Skills configuration was not found at $configPath. Re-run bootstrap.ps1."
}

$config = Get-Content $configPath -Raw | ConvertFrom-Json
if (-not $config.runtime_path -or -not $config.inbox_repo_url) {
    throw "Agent Skills configuration is incomplete: $configPath"
}

Write-Host 'Checking the read-only skills repository...'
& git -C $config.runtime_path fetch origin
if ($LASTEXITCODE -ne 0) {
    throw "Skills repository authentication failed (Git exit $LASTEXITCODE)."
}

Write-Host 'Checking the feedback inbox repository...'
& git ls-remote --heads $config.inbox_repo_url | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Inbox repository authentication failed (Git exit $LASTEXITCODE)."
}

Write-Host 'Both repositories are reachable.' -ForegroundColor Green
