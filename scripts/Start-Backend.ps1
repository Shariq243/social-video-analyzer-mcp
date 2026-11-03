param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    & (Join-Path $repoRoot '.venv\Scripts\python.exe') -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port --no-access-log
    if ($LASTEXITCODE -ne 0) { throw 'Backend stopped with an error. Check whether the port is already in use.' }
} finally { Pop-Location }
