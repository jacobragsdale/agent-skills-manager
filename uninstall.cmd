@echo off
rem Double-click uninstaller for the team Agent Skills system (Windows 11).
rem Launch a separate console so this wrapper exits before uninstall removes it.
setlocal EnableExtensions
set "UNINSTALLER=%LOCALAPPDATA%\AgentSkills\uninstall\uninstall.ps1"
if not exist "%UNINSTALLER%" set "UNINSTALLER=%~dp0uninstall.ps1"
cd /d "%USERPROFILE%"
if "%~1"=="" (start "Team Agent Skills Uninstall" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%UNINSTALLER%" -Pause & exit /b 0)
start "Team Agent Skills Uninstall" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%UNINSTALLER%" %* & exit /b 0
