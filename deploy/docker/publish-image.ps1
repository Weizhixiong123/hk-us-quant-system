param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$Repository,

    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Tag = (Get-Date -Format 'yyyyMMdd-HHmmss'),

    [ValidateSet('0', '1')]
    [string]$InstallBrokerDeps = '1',

    [switch]$SkipLatest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$versionImage = "${Repository}:$Tag"
$latestImage = "${Repository}:latest"

docker build `
    --build-arg "INSTALL_BROKER_DEPS=$InstallBrokerDeps" `
    --tag $versionImage `
    .
if ($LASTEXITCODE -ne 0) {
    throw "Docker build failed with exit code $LASTEXITCODE"
}

docker push $versionImage
if ($LASTEXITCODE -ne 0) {
    throw "Docker push failed for $versionImage"
}

if (-not $SkipLatest) {
    docker tag $versionImage $latestImage
    if ($LASTEXITCODE -ne 0) {
        throw "Docker tag failed for $latestImage"
    }
    docker push $latestImage
    if ($LASTEXITCODE -ne 0) {
        throw "Docker push failed for $latestImage"
    }
}

Write-Output "Published immutable image: $versionImage"
if (-not $SkipLatest) {
    Write-Output "Updated deployment image: $latestImage"
}
