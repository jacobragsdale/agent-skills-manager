@echo off
rem One-click repair for expired Azure DevOps sign-in.
rem A Microsoft sign-in window may open - use your corporate account.
echo Re-authenticating to Azure DevOps...
git -C "%USERPROFILE%\.agents" fetch origin
if %errorlevel%==0 (
  echo.
  echo Sign-in OK. The nightly skills sync will resume automatically.
) else (
  echo.
  echo Still failing. Contact the skills repo maintainer.
)
pause
