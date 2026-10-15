@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto dependencies
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 goto failed
:dependencies
.venv\Scripts\python.exe -c "import FinanceDataReader, pandas, openpyxl" >nul 2>nul
if not errorlevel 1 goto run
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
:run
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Install Python 3.11 or newer with Tcl/Tk and PATH enabled, then retry.
echo If dependencies failed, run: .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
