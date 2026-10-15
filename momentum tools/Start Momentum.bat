@echo off
setlocal
cd /d "%~dp0"
title Momentum lab

if not exist ".venv\Scripts\python.exe" (
    echo Python environment was not found.
    echo Please follow the setup instructions in README.md.
    pause
    exit /b 1
)

echo Starting Momentum lab...
echo The app will open in your default browser.
echo Keep this window open while using the app.
echo Press Ctrl+C to stop the app.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false

if errorlevel 1 (
    echo.
    echo The app could not start. Check the error above.
    echo If port 8501 is already in use, open http://localhost:8501
    pause
)
endlocal
