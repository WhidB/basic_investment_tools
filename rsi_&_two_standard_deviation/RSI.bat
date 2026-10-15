@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
 echo Python environment not found. Please check DESKTOP_README.md.
 pause
 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "native_app.py" --rsi

