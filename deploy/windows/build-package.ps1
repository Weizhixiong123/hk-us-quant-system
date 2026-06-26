[CmdletBinding()]
param(
    [string]$PackageName = "hk-us-quant-client",
    [string]$OutputDir = "",
    [switch]$SkipFrontendBuild,
    [switch]$NoRuntime,
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "release"
}

$releaseRoot = (New-Item -ItemType Directory -Force -Path $OutputDir).FullName
$packageRoot = Join-Path $releaseRoot $PackageName
$zipPath = Join-Path $releaseRoot "$PackageName.zip"

function Remove-InRelease {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $resolved.StartsWith($releaseRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refuse to remove path outside release root: $resolved"
    }

    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Copy-RequiredItem {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required path not found: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function New-ZipPackage {
    param(
        [string]$SourceDirectory,
        [string]$DestinationZip
    )

    # 只用 Windows 自带的 tar(全路径),避免 git bash 的 MSYS tar 把 "E:" 当远程主机
    $windowsTar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path -LiteralPath $windowsTar) {
        & $windowsTar -a -cf $DestinationZip -C $SourceDirectory .
        if ($LASTEXITCODE -ne 0) {
            throw "tar failed with exit code $LASTEXITCODE"
        }
        return
    }

    Compress-Archive -Path (Join-Path $SourceDirectory "*") -DestinationPath $DestinationZip -Force
}

if (-not $SkipFrontendBuild) {
    Push-Location (Join-Path $repoRoot "frontend")
    try {
        if (-not (Test-Path -LiteralPath "node_modules")) {
            npm ci
        }
        npm run build
    }
    finally {
        Pop-Location
    }
}

$frontendDist = Join-Path $repoRoot "frontend\dist"
if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html"))) {
    throw "frontend/dist/index.html not found. Run frontend build first."
}

Remove-InRelease $packageRoot
Remove-InRelease $zipPath

New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "backend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "frontend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "logs") | Out-Null

Copy-RequiredItem (Join-Path $repoRoot "backend\app") (Join-Path $packageRoot "backend")
Copy-RequiredItem (Join-Path $repoRoot "backend\quant") (Join-Path $packageRoot "backend")
Copy-RequiredItem (Join-Path $repoRoot "backend\requirements.txt") (Join-Path $packageRoot "backend")
Copy-RequiredItem $frontendDist (Join-Path $packageRoot "frontend")

Copy-RequiredItem (Join-Path $scriptDir "start.bat") $packageRoot
Copy-RequiredItem (Join-Path $scriptDir "stop.bat") $packageRoot
Copy-RequiredItem (Join-Path $scriptDir "repair-runtime.bat") $packageRoot
Copy-RequiredItem (Join-Path $scriptDir "README-local-deploy.md") $packageRoot

if (-not $NoRuntime) {
    $venv = Join-Path $repoRoot "backend\.venv"
    if (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe")) {
        Copy-RequiredItem $venv (Join-Path $packageRoot "runtime")
    }
    else {
        Write-Warning "backend\.venv was not found. Package will require repair-runtime.bat on client machine."
    }
}

if (-not $NoZip) {
    New-ZipPackage -SourceDirectory $packageRoot -DestinationZip $zipPath
}

Write-Host "Package directory: $packageRoot"
if (-not $NoZip) {
    Write-Host "Package zip:       $zipPath"
}
