param(
    [Parameter(Mandatory = $true)][ValidatePattern('^tunnel_[A-Za-z0-9]+$')][string]$TunnelId,
    [int]$BackendPort = 8000,
    [string]$TunnelClient = ''
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$mcpScript = Join-Path $repoRoot 'mcp-server\mcp_sse_server.py'
$profileDir = Join-Path $repoRoot '.tools\tunnel-profiles'
$profileFile = Join-Path $profileDir 'insta-analyzer.yaml'
if (-not $TunnelClient) {
    $bundledClient = Join-Path $repoRoot '.tools\tunnel-client\tunnel-client.exe'
    if (Test-Path -LiteralPath $bundledClient) { $TunnelClient = $bundledClient }
    else { $TunnelClient = 'tunnel-client' }
}
if (-not (Get-Command $TunnelClient -ErrorAction SilentlyContinue)) {
    throw 'Install the official Windows tunnel-client from https://github.com/openai/tunnel-client/releases/latest and pass -TunnelClient with its full executable path.'
}
$previousApiBase = $env:API_BASE_URL
$previousControlKey = $env:CONTROL_PLANE_API_KEY
$env:API_BASE_URL = "http://127.0.0.1:$BackendPort"
try {
    if (-not $env:CONTROL_PLANE_API_KEY) {
        $secureKey = Read-Host 'Enter the tunnel runtime API key locally (hidden)' -AsSecureString
        $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        try { $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer) }
    }
    $mcpCommand = '"{0}" "{1}" --stdio' -f $pythonExe.Replace('\', '/'), $mcpScript.Replace('\', '/')
    if (-not (Test-Path -LiteralPath $profileFile)) {
        & $TunnelClient init --sample sample_mcp_stdio_local --profile insta-analyzer --profile-dir $profileDir --tunnel-id $TunnelId --mcp-command $mcpCommand --health-listen-addr 127.0.0.1:18080
        if ($LASTEXITCODE -ne 0) { throw 'Tunnel profile initialization failed. Check tunnel-client help quickstart.' }
    } elseif (-not ((Get-Content -LiteralPath $profileFile -Raw).Contains($TunnelId))) {
        throw 'Existing profile uses a different tunnel ID. It was not overwritten.'
    }
    & $TunnelClient doctor --profile insta-analyzer --profile-dir $profileDir --explain
    if ($LASTEXITCODE -ne 0) { throw 'Tunnel checks failed. Check account permissions and tunnel association.' }
    & $TunnelClient run --profile insta-analyzer --profile-dir $profileDir
} finally {
    $env:API_BASE_URL = $previousApiBase
    $env:CONTROL_PLANE_API_KEY = $previousControlKey
    if ($secureKey) { $secureKey.Dispose() }
}
