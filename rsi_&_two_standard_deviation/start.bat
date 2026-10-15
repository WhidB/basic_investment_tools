@echo off
setlocal
title RSI and Z-score
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Please see README.md for setup.
    pause
    exit /b 1
)
echo Starting RSI and Z-score...
echo Your browser will open automatically.
echo Keep this window open while using the app. Close it to stop the app.
".venv\Scripts\python.exe" -m streamlit run "app.py" --server.headless=false --server.address=localhost --browser.gatherUsageStats=false
if errorlevel 1 (
    echo.
    echo The app could not start. See the error above.
    pause
    exit /b 1
)
endlocal
