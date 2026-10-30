# Sync weekly Top 2 manuscripts from the durable production state.
# Called by the Windows scheduled task "AI Radar Weekly Ebook Pull".
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

function ConvertFrom-CodePoints {
    param([int[]]$CodePoints)
    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$obsidianRoot = 'D:\huangxh\obsidian'
$outputDir = ConvertFrom-CodePoints @(0x8F93, 0x51FA)
$wechatDir = ConvertFrom-CodePoints @(0x516C, 0x4F17, 0x53F7)
$draftDir = ConvertFrom-CodePoints @(0x8349, 0x7A3F)
$dailyPodcastDir = ConvertFrom-CodePoints @(0x6BCF, 0x65E5, 0x64AD, 0x5BA2)
$dest = Join-Path (Join-Path (Join-Path $obsidianRoot $outputDir) $wechatDir) $draftDir
$dest = Join-Path $dest $dailyPodcastDir
$remoteHost = 'drainage-demo'
$remoteRoot = '/srv/ai-radar-data/current/reports/ebook'
$log = 'D:\huangxh\AI_Projects_100\p22_AI_Radar\state\logs\weekly-ebook-pull.log'

function Write-PullLog {
    param(
        [int]$ExitCode,
        [string[]]$Copied,
        [string[]]$Skipped,
        [string[]]$Conflicts,
        [string]$Details
    )
    $logDir = Split-Path -Parent $log
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $detailsOneLine = $Details -replace "`r?`n", ' | '
    '[{0}] exit={1} copied={2} skipped={3} conflicts={4} files={5} details={6}' -f `
        $ts, $ExitCode, $Copied.Count, $Skipped.Count, $Conflicts.Count, ($Copied -join ','), $detailsOneLine |
        Out-File -Append -Encoding utf8 $log
}

$copied = @()
$skipped = @()
$conflicts = @()
$planned = @()

try {
    $listCommand = "cd '$remoteRoot' && find . -mindepth 2 -maxdepth 2 -type f -name 'top*.md' -exec sha256sum {} + | sort"
    $listing = @(& ssh -o BatchMode=yes -o ConnectTimeout=15 $remoteHost $listCommand 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "SSH listing failed: $($listing -join ' | ')"
    }
    if ($listing.Count -eq 0) {
        throw 'No weekly manuscripts found in the durable state.'
    }
    if (-not (Test-Path -LiteralPath $dest)) {
        if (-not $DryRun) {
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
        }
    }

    $namesSeen = @{}
    foreach ($line in $listing) {
        $match = [regex]::Match([string]$line, '^([0-9a-fA-F]{64})  \./(20[0-9]{2}-W(?:0[1-9]|[1-4][0-9]|5[0-3]))/(top[12]_[A-Za-z0-9._-]+\.md)$')
        if (-not $match.Success) {
            throw "Unexpected remote file listing: $line"
        }
        $expectedHash = $match.Groups[1].Value.ToLowerInvariant()
        $week = $match.Groups[2].Value
        $fileName = $match.Groups[3].Value
        if ($namesSeen.ContainsKey($fileName) -and $namesSeen[$fileName] -ne $expectedHash) {
            throw "Different weeks contain the same filename: $fileName"
        }
        $namesSeen[$fileName] = $expectedHash
        $localFile = Join-Path $dest $fileName

        if (Test-Path -LiteralPath $localFile) {
            $localHash = (Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($localHash -eq $expectedHash) {
                $skipped += $fileName
            } else {
                $conflicts += $fileName
            }
            continue
        }
        if ($DryRun) {
            $planned += "$week/$fileName"
            continue
        }

        $temporaryFile = Join-Path $dest ('.ai-radar-' + [guid]::NewGuid().ToString('N') + '.part')
        try {
            $remoteFile = "${remoteHost}:${remoteRoot}/${week}/${fileName}"
            $copyOutput = @(& scp -p $remoteFile $temporaryFile 2>&1)
            if ($LASTEXITCODE -ne 0) {
                throw "SCP failed for ${week}/${fileName}: $($copyOutput -join ' | ')"
            }
            $copiedHash = (Get-FileHash -LiteralPath $temporaryFile -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($copiedHash -ne $expectedHash) {
                throw "Checksum mismatch for ${week}/${fileName}"
            }
            Move-Item -LiteralPath $temporaryFile -Destination $localFile
            $copied += $fileName
        } finally {
            if (Test-Path -LiteralPath $temporaryFile) {
                Remove-Item -LiteralPath $temporaryFile
            }
        }
    }
    if ($conflicts.Count -gt 0) {
        throw "Local files differ from server; kept local versions: $($conflicts -join ',')"
    }
    $details = if ($DryRun) { "dry_run planned=$($planned.Count) files=$($planned -join ',')" } else { 'ok' }
    Write-PullLog -ExitCode 0 -Copied $copied -Skipped $skipped -Conflicts $conflicts -Details $details
    Write-Output "Weekly ebook sync: copied=$($copied.Count) skipped=$($skipped.Count) planned=$($planned.Count)"
    exit 0
} catch {
    $details = $_.Exception.Message
    Write-PullLog -ExitCode 1 -Copied $copied -Skipped $skipped -Conflicts $conflicts -Details $details
    [Console]::Error.WriteLine($details)
    exit 1
}
