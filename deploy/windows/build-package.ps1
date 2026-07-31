[CmdletBinding()]
param(
    [string]$PackageName = "hk-us-quant-client",
    [string]$OutputDir = "",
    [switch]$SkipFrontendBuild,
    [switch]$NoRuntime,
    [switch]$ReuseRuntime
)

$ErrorActionPreference = "Stop"

if ($NoRuntime -and $ReuseRuntime) {
    throw "-NoRuntime and -ReuseRuntime cannot be used together."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "release"
}

$releaseRoot = (New-Item -ItemType Directory -Force -Path $OutputDir).FullName
$packageRoot = Join-Path $releaseRoot $PackageName

function Write-Step {
    param([string]$Message)

    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

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

if (-not $SkipFrontendBuild) {
    Write-Step "Building frontend..."
    Push-Location (Join-Path $repoRoot "frontend")
    try {
        if (-not (Test-Path -LiteralPath "node_modules")) {
            Write-Step "Installing frontend dependencies..."
            npm ci
        }
        npm run build
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Skipping frontend build."
}

$frontendDist = Join-Path $repoRoot "frontend\dist"
if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html"))) {
    throw "frontend/dist/index.html not found. Run frontend build first."
}

Write-Step "Refreshing package while preserving runtime data..."
if (Test-Path -LiteralPath $packageRoot) {
    $dataDir = Join-Path $packageRoot "data"
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

    $legacyDataDir = Join-Path $packageRoot "backend\data"
    if (Test-Path -LiteralPath $legacyDataDir) {
        Get-ChildItem -LiteralPath $legacyDataDir -Filter "*.sqlite3" -File | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $dataDir -Force
        }
    }

    $refreshItems = @(
        "backend",
        "frontend",
        "start.bat",
        "stop.bat",
        "repair-runtime.bat",
        "README-local-deploy.md"
    )
    if (-not $ReuseRuntime) {
        $refreshItems += "runtime"
    }
    $refreshItems | ForEach-Object {
        Remove-InRelease (Join-Path $packageRoot $_)
    }
}

Write-Step "Creating package directories..."
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "backend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "frontend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "logs") | Out-Null

Write-Step "Copying application files..."
Copy-RequiredItem (Join-Path $repoRoot "backend\app") (Join-Path $packageRoot "backend")
Copy-RequiredItem (Join-Path $repoRoot "backend\quant") (Join-Path $packageRoot "backend")
Copy-RequiredItem (Join-Path $repoRoot "backend\requirements.txt") (Join-Path $packageRoot "backend")
Copy-RequiredItem $frontendDist (Join-Path $packageRoot "frontend")

Copy-RequiredItem (Join-Path $scriptDir "start.bat") $packageRoot
Copy-RequiredItem (Join-Path $scriptDir "stop.bat") $packageRoot
Copy-RequiredItem (Join-Path $scriptDir "repair-runtime.bat") $packageRoot
Copy-RequiredItem (Join-Path $scriptDir "README-local-deploy.md") $packageRoot

if ($ReuseRuntime) {
    if (-not (Test-Path -LiteralPath (Join-Path $packageRoot "runtime\Scripts\python.exe"))) {
        throw "Existing package runtime was not found; rebuild without -ReuseRuntime."
    }
    Write-Step "Reusing existing Python runtime."
}
elseif (-not $NoRuntime) {
    $venv = Join-Path $repoRoot "backend\.venv"
    if (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe")) {
        Write-Step "Copying Python runtime (this may take several minutes)..."
        Copy-RequiredItem $venv (Join-Path $packageRoot "runtime")
        Write-Step "Python runtime copied."
    }
    else {
        Write-Warning "backend\.venv was not found. Package will require repair-runtime.bat on client machine."
    }
}
else {
    Write-Step "Skipping Python runtime."
}

Write-Step "Package build completed."
Write-Host "Package directory: $packageRoot"
