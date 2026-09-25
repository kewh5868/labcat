@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0labcat.ps1" %*
set "labcat_exit=%errorlevel%"
if not "%labcat_exit%"=="0" (
    echo.
    echo If PowerShell reports a blocked script, follow your site's script-signing policy.
    echo You can also use the Docker Compose startup commands in the README.
    pause
)
exit /b %labcat_exit%
