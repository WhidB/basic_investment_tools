@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title US Stock Win Rate Calculator
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" launcher.py
    goto finished
)

py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    py -3 launcher.py
    goto finished
)
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    python launcher.py
    goto finished
)
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PYTHON%" (
    "%BUNDLED_PYTHON%" launcher.py
    goto finished
)
echo Python 3.10 or later is required.
echo Install Python from https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH", then double-click run.bat again.

:finished
echo.
pause
endlocal
