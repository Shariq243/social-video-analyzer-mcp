param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Version.Major -lt 10 -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'Insta Analyzer requires Windows 10 or Windows 11, 64-bit.'
}
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    throw 'This installer downloads x64 tools. Native ARM64 installation is not supported.'
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repoRoot = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $repoRoot '.tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null

function Install-VerifiedAsset([string]$Repository, [string]$AssetPattern, [string]$Target) {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/latest" -Headers @{'User-Agent'='Insta-Analyzer-Setup'}
    $asset = @($release.assets | Where-Object { $_.name -like $AssetPattern })
    if ($asset.Count -ne 1) { throw "Could not identify the official Windows download for $Repository." }
    $asset = $asset[0]
    $expected = ''
    if ($asset.digest -match '^sha256:([a-fA-F0-9]{64})$') { $expected = $Matches[1] }
    if (-not $expected) {
        $sumAsset = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' } | Select-Object -First 1
        if ($sumAsset) {
            $text = (Invoke-WebRequest -UseBasicParsing -Uri $sumAsset.browser_download_url).Content
            foreach ($line in ($text -split "`n")) {
                if ($line -match ('^([a-fA-F0-9]{64})\s+\*?' + [regex]::Escape($asset.name) + '\s*$')) { $expected = $Matches[1]; break }
            }
        } else {
            $sumAsset = $release.assets | Where-Object { $_.name -eq ($asset.name + '.sha256') } | Select-Object -First 1
            if ($sumAsset) {
                $text = (Invoke-WebRequest -UseBasicParsing -Uri $sumAsset.browser_download_url).Content
                if ($text -match '([a-fA-F0-9]{64})') { $expected = $Matches[1] }
            }
        }
    }
    if (-not $expected) { throw "No SHA256 checksum was available for $($asset.name); installation stopped." }
    $archive = Join-Path $tools $asset.name
    Write-Host "Downloading $Repository ($($release.tag_name))..."
    Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $archive
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $expected) { throw 'Download checksum mismatch; installation stopped.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destination = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            $entryPath = [IO.Path]::GetFullPath((Join-Path $Target $entry.FullName))
            if (-not $entryPath.StartsWith($destination, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive path; installation stopped.' }
        }
    } finally { $zip.Dispose() }
    Expand-Archive -LiteralPath $archive -DestinationPath $Target -Force
}

Push-Location $repoRoot
try {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCommand) { $uv = $uvCommand.Source }
    else {
        $uv = Join-Path $tools 'uv\uv.exe'
        if (-not (Test-Path -LiteralPath $uv)) {
            Install-VerifiedAsset 'astral-sh/uv' 'uv-x86_64-pc-windows-msvc.zip' (Join-Path $tools 'uv')
            $foundUv = Get-ChildItem -LiteralPath (Join-Path $tools 'uv') -Recurse -Filter uv.exe | Select-Object -First 1
            if (-not $foundUv) { throw 'The uv executable was not found after extraction.' }
            $uv = $foundUv.FullName
        }
    }
    # All managed runtimes/caches remain inside this installation folder.
    $env:UV_CACHE_DIR = Join-Path $repoRoot '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $tools 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $tools 'bin'
    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        & $uv python install 3.13 --no-bin --no-registry
        $installExit = $LASTEXITCODE
        $managedPython = Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'cpython-3.13.*' } | Sort-Object FullName -Descending |
            ForEach-Object { Get-Item -LiteralPath (Join-Path $_.FullName 'python.exe') -ErrorAction SilentlyContinue } | Select-Object -First 1
        if (-not $managedPython) { throw 'Python installation failed; a complete private runtime was not found.' }
        & $managedPython.FullName -c "import sys, tkinter, ssl; assert sys.version_info[:2] == (3, 13)"
        if ($LASTEXITCODE -ne 0) { throw 'The downloaded Python runtime failed validation.' }
        if ($installExit -ne 0) { Write-Host 'Using the validated private runtime directly; optional Windows runtime links were unavailable.' }
        & $uv venv --python $managedPython.FullName .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    Write-Host 'Installing the project dependencies...'
    & $uv pip install --python $python -r requirements-windows.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $python -c "import tkinter, mcp, google.genai; print('Runtime checks passed.')"
    if ($LASTEXITCODE -ne 0) { throw 'Runtime checks failed.' }
    $tunnelClient = Join-Path $tools 'tunnel-client\tunnel-client.exe'
    if (-not (Test-Path -LiteralPath $tunnelClient)) {
        Install-VerifiedAsset 'openai/tunnel-client' 'tunnel-client-v*-windows-amd64.zip' (Join-Path $tools 'tunnel-client')
    }
    if (-not (Test-Path -LiteralPath $tunnelClient)) { throw 'The tunnel client was not found after extraction.' }
    Write-Host 'Installation complete. Credentials are entered in the local setup window.'
    if (-not $NoLaunch) {
        & $python (Join-Path $PSScriptRoot 'launcher.py') setup
        if ($LASTEXITCODE -ne 0) { throw 'Setup window could not start.' }
    }
} finally { Pop-Location }
