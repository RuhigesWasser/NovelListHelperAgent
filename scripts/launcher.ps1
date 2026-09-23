param([ValidateSet('start','setup','stop','clean')][string]$Mode = 'start', [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimePath = Join-Path $appRoot '.runtime'
$localPath = Join-Path $appRoot '.local'
$statePath = Join-Path $localPath 'server.json'

function Get-AppHash([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Get-AppState {
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $port = [int]$state.port
            if ($port -lt 1 -or $port -gt 65535) { return $null }
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
            if ($health.app -eq 'novel-list-helper') { return $state }
        } catch { }
    }
    return $null
}

function Stop-App {
    $state = Get-AppState
    if ($null -ne $state) {
        Invoke-RestMethod -Uri "http://127.0.0.1:$($state.port)/api/shutdown" -Method Post -Headers @{'X-Session-Token'=$state.token} -TimeoutSec 5 | Out-Null
        for ($i=0; $i -lt 60; $i++) {
            Start-Sleep -Milliseconds 250
            if ($null -eq (Get-AppState)) { return }
        }
        throw 'Server did not stop. Data was not removed.'
    }
}

function Remove-AppDirectory([string]$path) {
    $fullPath = [IO.Path]::GetFullPath($path)
    $allowed = @($runtimePath, $localPath, (Join-Path $appRoot '.agents\.venv-ocr'), (Join-Path $runtimePath 'venv'))
    if ($allowed -notcontains $fullPath -or -not $fullPath.StartsWith($appRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw 'Refusing unexpected deletion target.'
    }
    if (Test-Path -LiteralPath $fullPath) {
        # uv creates a version-alias junction. Unlink reparse entries without traversing them.
        Remove-AppLinks $fullPath
        if (-not (Test-Path -LiteralPath $fullPath)) { return }
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

function Remove-AppLinks([string]$path) {
    $entry = Get-Item -LiteralPath $path -Force
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if ($entry.PSIsContainer) { [IO.Directory]::Delete($entry.FullName) }
        else { [IO.File]::Delete($entry.FullName) }
        return
    }
    if ($entry.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $path -Force) {
            if ($child.PSIsContainer -or ($child.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                Remove-AppLinks $child.FullName
            }
        }
    }
}

try {
    if ($Mode -eq 'stop') { Stop-App; Write-Host 'Application stopped.'; exit 0 }
    if ($Mode -eq 'clean') {
        Write-Host "This removes runtime, caches, settings, ALL tasks and the local book library under: $appRoot"
        Write-Host 'Source files and Git history will be kept. External exports and browser/OS records are not removed.'
        if ((Read-Host 'Type CLEAN to continue') -cne 'CLEAN') { Write-Host 'Cancelled.'; exit 0 }
        Stop-App
        # A held file lock means the process is still shutting down; never delete live data.
        $lockPath = Join-Path $localPath 'server.lock'
        if (Test-Path -LiteralPath $lockPath) {
            $probe = [IO.File]::Open($lockPath, 'Open', 'ReadWrite', 'None')
            $probe.Dispose()
        }
        Remove-AppDirectory $runtimePath
        Remove-AppDirectory $localPath
        Remove-AppDirectory (Join-Path $appRoot '.agents\.venv-ocr')
        Write-Host 'Local app data removed. Delete this application folder to remove the source as well.'
        exit 0
    }
    $running = Get-AppState
    if ($null -ne $running -and $Mode -eq 'start') {
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$($running.port)" }
        Write-Host 'Opened the existing instance.'
        exit 0
    }
    $lockFile = Join-Path $appRoot 'uv.lock'
    if (-not (Test-Path -LiteralPath $lockFile)) { throw 'uv.lock is missing. Download a complete release.' }
    $fingerprint = (Get-AppHash $lockFile) + (Get-AppHash (Join-Path $appRoot 'pyproject.toml'))
    $readyPath = Join-Path $runtimePath 'ready.json'
    $pythonPath = Join-Path $runtimePath 'venv\Scripts\python.exe'
    $ready = $null
    if (Test-Path -LiteralPath $readyPath) { try { $ready = Get-Content -LiteralPath $readyPath -Raw | ConvertFrom-Json } catch {} }
    $needsSetup = -not (Test-Path -LiteralPath $pythonPath) -or $null -eq $ready -or $ready.hash -ne $fingerprint -or $ready.root -ne $appRoot
    if ($needsSetup) {
        Write-Host 'This application needs a private Python 3.12 runtime and packages.'
        Write-Host "Install/update them ONLY inside: $runtimePath"
        Write-Host 'Downloads: Astral uv/Python (GitHub) and packages (PyPI). Several hundred MB of disk space may be needed.'
        Write-Host 'No administrator access, system Python, registry registration, PATH changes or startup entries.'
        if ((Read-Host 'Allow this local installation? [y/N]') -notmatch '^(y|yes)$') { Write-Host 'Cancelled. Nothing installed.'; exit 0 }
    }
    foreach ($dir in @($runtimePath, $localPath, (Join-Path $localPath 'tmp'), (Join-Path $localPath 'logs'))) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    # Environment variables affect this process and its children only.
    $env:UV_CACHE_DIR = Join-Path $runtimePath 'cache\uv'
    $env:UV_PYTHON_CACHE_DIR = Join-Path $runtimePath 'cache\python'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimePath 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $runtimePath 'bin'
    $env:UV_TOOL_DIR = Join-Path $runtimePath 'tools'
    $env:UV_TOOL_BIN_DIR = Join-Path $runtimePath 'bin'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $runtimePath 'venv'
    $env:UV_PYTHON_INSTALL_REGISTRY = 'false'
    $env:UV_PYTHON_NO_REGISTRY = 'true'
    $env:UV_PYTHON_INSTALL_BIN = 'false'
    $env:UV_NO_MODIFY_PATH = 'true'
    $env:UV_NO_CONFIG = 'true'
    $env:UV_NO_PROGRESS = 'true'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $env:TEMP = Join-Path $localPath 'tmp'
    $env:TMP = $env:TEMP
    $env:TMPDIR = $env:TEMP
    $env:PIP_CACHE_DIR = Join-Path $runtimePath 'cache\pip'
    $env:XDG_CACHE_HOME = Join-Path $runtimePath 'cache'
    $env:XDG_CONFIG_HOME = Join-Path $localPath 'config'
    $env:XDG_DATA_HOME = Join-Path $localPath 'data'
    $env:HF_HOME = Join-Path $runtimePath 'cache\huggingface'
    $env:MPLCONFIGDIR = Join-Path $runtimePath 'cache\matplotlib'
    if ($needsSetup) {
        if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This launcher currently supports Windows x64.' }
        $uvPath = Join-Path $runtimePath 'uv\uv.exe'
        if (-not (Test-Path -LiteralPath $uvPath)) {
            $zipPath = Join-Path $runtimePath 'uv.zip'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/uv/releases/download/0.12.17/uv-x86_64-pc-windows-msvc.zip' -OutFile $zipPath
            if ((Get-AppHash $zipPath).ToLowerInvariant() -ne 'a252121d5b59398fcb137c6ea448176459a44010f33f67e0072305a637119ca7') { throw 'uv archive checksum mismatch.' }
            Expand-Archive -LiteralPath $zipPath -DestinationPath (Join-Path $runtimePath 'uv') -Force
            Remove-Item -LiteralPath $zipPath
        }
        if ($null -ne $ready -and $ready.root -ne $appRoot) { Remove-AppDirectory (Join-Path $runtimePath 'venv') }
        Push-Location $appRoot
        try {
            & $uvPath sync --locked --no-dev --managed-python --python 3.12
            if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Retry Start.cmd after checking the connection.' }
        } finally { Pop-Location }
        @{root=$appRoot; hash=$fingerprint} | ConvertTo-Json | Set-Content -LiteralPath $readyPath -Encoding UTF8
    }
    if ($Mode -eq 'setup') { Write-Host 'Local environment ready.'; exit 0 }
    $arguments = '-B -m app.main'
    if ($NoBrowser) { $arguments += ' --no-browser' }
    $proc = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $localPath 'logs\server.out.log') -RedirectStandardError (Join-Path $localPath 'logs\server.err.log')
    for ($i=0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 250
        $state = Get-AppState
        if ($null -ne $state) { Write-Host "Ready: http://127.0.0.1:$($state.port)"; exit 0 }
        if ($proc.HasExited) { break }
    }
    throw "Startup failed. See $localPath\logs\server.err.log"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
