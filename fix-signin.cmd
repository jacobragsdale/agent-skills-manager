@echo off
rem Refresh Git Credential Manager sign-in for both Agent Skills repositories.
echo Re-authenticating the Agent Skills runtime and inbox...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix-signin.ps1"
set "result=%errorlevel%"
if %result%==0 (
  echo.
  echo Sign-in OK. The nightly sync will resume automatically.
) else (
  echo.
  echo Sign-in still fails. Contact the Agent Skills maintainer.
)
pause
exit /b %result%
