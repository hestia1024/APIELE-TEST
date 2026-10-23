$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment. Install Python 3.12+ first.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the pip output above.' }
& '.venv/Scripts/python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
