@echo off
rem Double-click installer for the team agent skills system (Windows 11).
rem Runs bootstrap.ps1 from this folder; safe to re-run any time.
rem Use this after downloading the repo as a Zip from Azure DevOps --
rem no terminal, no git, no configuration needed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
echo.
pause
