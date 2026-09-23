param([switch]$FrameworkDependent,[string]$BuildDirectory,[string]$OutputDirectory)
$ErrorActionPreference='Stop'
$appRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot=if($BuildDirectory){[IO.Path]::GetFullPath($BuildDirectory)}else{Join-Path $appRoot '.runtime\build\desktop'}
$stage=Join-Path $buildRoot ([guid]::NewGuid().ToString('N'))
$output=if($OutputDirectory){[IO.Path]::GetFullPath($OutputDirectory)}else{Join-Path $appRoot 'dist'}
New-Item -ItemType Directory -Force -Path $buildRoot,$stage,$output | Out-Null
$env:DOTNET_CLI_HOME=Join-Path $buildRoot 'dotnet-home'
$env:NUGET_PACKAGES=Join-Path $buildRoot 'cache\nuget'
$env:NUGET_HTTP_CACHE_PATH=Join-Path $buildRoot 'cache\nuget-http'
$env:NUGET_PLUGINS_CACHE_PATH=Join-Path $buildRoot 'cache\nuget-plugins'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
$env:MSBUILDDISABLENODEREUSE='1'
$env:TEMP=Join-Path $buildRoot 'tmp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$project=Join-Path $appRoot 'desktop\windows\Shiye.Desktop.csproj'
$intermediate=(Join-Path $buildRoot 'obj')+'\'
$binaries=(Join-Path $buildRoot 'bin')+'\'
$selfContained=if($FrameworkDependent){'false'}else{'true'}
$properties=@("-p:BaseIntermediateOutputPath=$intermediate","-p:MSBuildProjectExtensionsPath=$intermediate","-p:BaseOutputPath=$binaries","-p:SelfContained=$selfContained",'-p:DebugType=None')
& dotnet restore $project -r win-x64 --source https://api.nuget.org/v3/index.json @properties
if($LASTEXITCODE -ne 0){throw 'Desktop restore failed.'}
& dotnet publish $project -c Release -r win-x64 --self-contained $selfContained --no-restore -o $stage @properties
if($LASTEXITCODE -ne 0){throw 'Desktop build failed.'}
Push-Location $appRoot
try{
  & .runtime/venv/Scripts/python.exe -B -m scripts.package_apps --edition windows --stage $stage --zip (Join-Path $output 'Shiye-Windows-x64.zip')
  if($LASTEXITCODE -ne 0){throw 'Desktop packaging failed.'}
}finally{Pop-Location}
@{stage=$stage;archive=(Join-Path $output 'Shiye-Windows-x64.zip');self_contained=(-not $FrameworkDependent)} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'windows-build.json') -Encoding UTF8
Write-Host "Desktop ready: $stage\Shiye.exe"
