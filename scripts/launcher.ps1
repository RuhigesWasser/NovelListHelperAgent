param([ValidateSet('start','setup','stop','clean')][string]$Mode = 'start', [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimePath = Join-Path $appRoot '.runtime'
$localPath = Join-Path $appRoot '.local'
$statePath = Join-Path $localPath 'server.json'

$downloadSources = @{ PACKAGE_INDEX='https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple'; PACKAGE_FALLBACK='https://pypi.org/simple'; PYTHON_MIRROR='' }
$configPath = Join-Path $appRoot 'download-sources.conf'
if (Test-Path -LiteralPath $configPath) {
    foreach ($line in Get-Content -LiteralPath $configPath) {
        if ($line -match '^\s*(PACKAGE_INDEX|PACKAGE_FALLBACK|PYTHON_MIRROR)\s*=(.*)$') { $downloadSources[$matches[1]]=$matches[2].Trim() }
    }
}

function Invoke-DirectUv([string]$Executable,[string[]]$Arguments,[string]$Index) {
    $proxyNames=@('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY')
    $savedProxy=@{}
    foreach($name in $proxyNames){$savedProxy[$name]=[Environment]::GetEnvironmentVariable($name,'Process');[Environment]::SetEnvironmentVariable($name,$null,'Process')}
    $env:NO_PROXY='*'
    try { & $Executable @Arguments; $result=$LASTEXITCODE }
    finally {foreach($name in $proxyNames){[Environment]::SetEnvironmentVariable($name,$savedProxy[$name],'Process')}}
    if($result -ne 0){
        $hasProxy=$savedProxy['HTTP_PROXY'] -or $savedProxy['HTTPS_PROXY'] -or $savedProxy['ALL_PROXY']
        if(!$hasProxy){
            $systemProxy=[Net.WebRequest]::GetSystemWebProxy()
            if(!$systemProxy.IsBypassed([Uri]$Index)){
                $proxyUrl=$systemProxy.GetProxy([Uri]$Index).AbsoluteUri
                $env:HTTP_PROXY=$proxyUrl;$env:HTTPS_PROXY=$proxyUrl;$hasProxy=$true
            }
        }
        try{if($hasProxy){ & $Executable @Arguments; $result=$LASTEXITCODE }}
        finally{foreach($name in $proxyNames){[Environment]::SetEnvironmentVariable($name,$savedProxy[$name],'Process')}}
    }
    if($result -ne 0){throw 'Dependency download failed for this source.'}
}

function Save-AppDownload([string]$Url,[string]$Destination) {
    foreach($useProxy in @($false,$true)){
        $response=$null;$inputStream=$null;$outputStream=$null
        try{
            $request=[Net.HttpWebRequest]::Create($Url)
            if(!$useProxy){$request.Proxy=$null}
            $request.Timeout=120000;$request.ReadWriteTimeout=120000
            $response=$request.GetResponse();$inputStream=$response.GetResponseStream()
            $outputStream=[IO.File]::Create($Destination);$inputStream.CopyTo($outputStream)
            return
        }catch{if($useProxy){throw}}
        finally{if($outputStream){$outputStream.Dispose()};if($inputStream){$inputStream.Dispose()};if($response){$response.Dispose()}}
    }
}

function Get-AppHash([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Invoke-AppJson([string]$Url,[string]$Method='GET',[string]$Token='') {
    $request=[Net.HttpWebRequest]::Create($Url);$request.Proxy=$null
    $request.Timeout=2000;$request.ReadWriteTimeout=2000;$request.Method=$Method
    if($Token){$request.Headers.Add('X-Session-Token',$Token)}
    if($Method -eq 'POST'){$request.ContentLength=0}
    $response=$null;$reader=$null
    try{$response=$request.GetResponse();$reader=New-Object IO.StreamReader($response.GetResponseStream());return ($reader.ReadToEnd() | ConvertFrom-Json)}
    finally{if($reader){$reader.Dispose()};if($response){$response.Dispose()}}
}

function Get-AppState {
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $port = [int]$state.port
            if ($port -lt 1 -or $port -gt 65535) { return $null }
            $health = Invoke-AppJson "http://127.0.0.1:$port/health"
            if ($health.app -eq 'novel-list-helper') { return $state }
        } catch { }
    }
    return $null
}

function Stop-App {
    $state = Get-AppState
    if ($null -ne $state) {
        Invoke-AppJson "http://127.0.0.1:$($state.port)/api/shutdown" 'POST' $state.token | Out-Null
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
        Write-Host 'Bundled uv/Python are used when available. Missing packages use download-sources.conf.'
        Write-Host 'The complete application is already included; no Git or repository download is needed.'
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
    $env:UV_NO_ENV_FILE = 'true'
    if($downloadSources.PYTHON_MIRROR){$env:UV_PYTHON_INSTALL_MIRROR=$downloadSources.PYTHON_MIRROR}
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
        $bundledUv = Join-Path $appRoot 'vendor\uv\uv.exe'
        $bundledPython = Join-Path $appRoot 'vendor\python\python.exe'
        if(Test-Path -LiteralPath $bundledUv){$uvPath=$bundledUv}
        if (-not (Test-Path -LiteralPath $uvPath)) {
            $zipPath = Join-Path $runtimePath 'uv.zip'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $wheelPath='54/19/1d5009571cecd0b1c4260823e95dc0c11ccc9429ad0a7cadebab855886cc/uv-0.12.17-py3-none-win_amd64.whl'
            try{Save-AppDownload ('https://mirrors.tuna.tsinghua.edu.cn/pypi/web/packages/'+$wheelPath) $zipPath}
            catch{Save-AppDownload ('https://files.pythonhosted.org/packages/'+$wheelPath) $zipPath}
            if ((Get-AppHash $zipPath).ToLowerInvariant() -ne '7a14aafc5d5816cebfb8b61b8529fe6f9b99210363523fe2a9d441e757bd3cb7') { throw 'uv archive checksum mismatch.' }
            Expand-Archive -LiteralPath $zipPath -DestinationPath (Join-Path $runtimePath 'uv') -Force
            Move-Item -LiteralPath (Join-Path $runtimePath 'uv\uv-0.12.17.data\scripts\uv.exe') -Destination $uvPath
            Remove-Item -LiteralPath $zipPath
        }
        if ($null -ne $running) { throw 'Stop the running application before updating its environment.' }
        if (Test-Path -LiteralPath (Join-Path $runtimePath 'venv')) { Remove-AppDirectory (Join-Path $runtimePath 'venv') }
        Push-Location $appRoot
        try {
            $requirements = Join-Path $runtimePath 'requirements.lock.txt'
            if(Test-Path -LiteralPath $bundledPython){
                $env:UV_PYTHON=$bundledPython
                $env:UV_PYTHON_DOWNLOADS='never'
                & $uvPath venv --python $bundledPython (Join-Path $runtimePath 'venv')
                if($LASTEXITCODE -ne 0){throw 'Failed to prepare the private environment.'}
            }else{
                & $uvPath venv --managed-python --python 3.12 (Join-Path $runtimePath 'venv')
                if($LASTEXITCODE -ne 0){throw 'Python setup failed. Use a runtime-included distribution or configure PYTHON_MIRROR.'}
            }
            & $uvPath export --locked --no-dev --no-emit-project --format requirements-txt --output-file $requirements --quiet | Out-Null
            if($LASTEXITCODE -ne 0){throw 'Dependency lock export failed.'}
            $installed=$false
            foreach($index in @($downloadSources.PACKAGE_INDEX,$downloadSources.PACKAGE_FALLBACK) | Select-Object -Unique){
                if(!$index){continue}
                Write-Host "Installing locked packages from: $index"
                try{
                    Invoke-DirectUv $uvPath @('pip','sync','--python',$pythonPath,'--require-hashes','--only-binary',':all:','--index-url',$index,$requirements) $index
                    $installed=$true;break
                }catch{Write-Host 'This source failed; trying the next configured source.'}
            }
            if(!$installed){throw 'Dependency setup failed. Check download-sources.conf and retry.'}
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
