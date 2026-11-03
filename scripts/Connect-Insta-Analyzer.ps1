param([int]$BackendPort = 18002, [string]$TunnelId = '')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $repoRoot '.insta-analyzer\credentials.dpapi')) {
    & (Join-Path $repoRoot '.venv\Scripts\python.exe') (Join-Path $repoRoot 'windows\launcher.py') start
    exit $LASTEXITCODE
}
if (-not $TunnelId) {
    $manualProfile = Join-Path $repoRoot '.tools\tunnel-profiles\insta-analyzer.yaml'
    if (Test-Path -LiteralPath $manualProfile) {
        $profileText = Get-Content -LiteralPath $manualProfile -Raw
        if ($profileText -match 'tunnel_id:\s*"?(tunnel_[A-Za-z0-9]+)') { $TunnelId = $Matches[1] }
    }
}
if (-not $TunnelId) { $TunnelId = Read-Host 'Enter your OpenAI tunnel ID' }
& (Join-Path $PSScriptRoot 'Start-Tunnel.ps1') -TunnelId $TunnelId -BackendPort $BackendPort
