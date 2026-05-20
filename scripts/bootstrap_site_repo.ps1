param(
    [Parameter(Mandatory = $true)]
    [string]$SiteRepoPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$starterRoot = Join-Path $projectRoot "site_starter"
$resolvedSiteRepoPath = (Resolve-Path -LiteralPath $SiteRepoPath).Path

if (-not (Test-Path $starterRoot)) {
    throw "Missing site starter directory: $starterRoot"
}

if (-not (Test-Path (Join-Path $resolvedSiteRepoPath ".git"))) {
    throw "Target is not a git repository: $resolvedSiteRepoPath"
}

Copy-Item -Path (Join-Path $starterRoot "*") -Destination $resolvedSiteRepoPath -Recurse -Force
Write-Output "Copied site starter files into $resolvedSiteRepoPath"
