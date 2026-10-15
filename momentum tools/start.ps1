$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw '먼저 Python으로 python -m venv .venv 및 .venv\Scripts\python.exe -m pip install -r requirements.txt를 실행하세요.'
}
& $projectPython -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false
