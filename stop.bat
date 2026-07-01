@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launcher.py stop
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python launcher.py stop
  ) else (
    echo Python 3 was not found.
    echo Install Python 3 and run this file again.
    pause
    exit /b 1
  )
)

echo.
echo You can close this window.
pause
