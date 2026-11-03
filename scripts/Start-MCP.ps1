param([int]$Port = 8100, [int]$BackendPort = 8000)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$previousApiBase = $env:API_BASE_URL
$env:API_BASE_URL = "http://127.0.0.1:$BackendPort"
Push-Location $repoRoot
try {
    & (Join-Path $repoRoot '.venv\Scripts\python.exe') -m uvicorn mcp_sse_server:app --app-dir mcp-server --host 127.0.0.1 --port $Port --no-access-log
    if ($LASTEXITCODE -ne 0) { throw 'MCP stopped with an error. Check whether the port is already in use.' }
} finally {
    $env:API_BASE_URL = $previousApiBase
    Pop-Location
}
