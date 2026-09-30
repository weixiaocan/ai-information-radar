# Pull only the current week's podcast exports.
# Called by the Windows scheduled task "AI Radar Weekly Ebook Pull".
$ErrorActionPreference = 'Stop'

function ConvertFrom-CodePoints {
    param([int[]]$CodePoints)
    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$obsidianRoot = 'D:\huangxh\obsidian'
$outputDir = ConvertFrom-CodePoints @(0x8F93, 0x51FA)
$wechatDir = ConvertFrom-CodePoints @(0x516C, 0x4F17, 0x53F7)
$publishedDir = ConvertFrom-CodePoints @(0x5DF2, 0x53D1, 0x5E03)
$dest = Join-Path (Join-Path (Join-Path $obsidianRoot $outputDir) $wechatDir) $publishedDir
$dest = Join-Path $dest 'AI_RADAR'
$remoteHost = 'ai-radar-server'
$remoteRoot = '/opt/ai-radar/exports'
$log = 'D:\huangxh\AI_Projects_100\p22_AI_Radar\state\logs\weekly-ebook-pull.log'

function Write-PullLog {
    param(
        [int]$ExitCode,
        [string]$WeekLabel,
        [string[]]$Files,
        [string[]]$Output
    )

    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $fileText = if ($Files.Count -gt 0) { $Files -join ',' } else { '-' }
    $outputText = (($Output | Out-String).Trim() -replace "`r?`n", ' | ')
    "[{0}] exit={1} week={2} count={3} files={4} out={5}" -f `
        $ts, $ExitCode, $WeekLabel, $Files.Count, $fileText, $outputText |
        Out-File -Append -Encoding utf8 $log
}

$today = (Get-Date).Date
$daysSinceMonday = (([int]$today.DayOfWeek + 6) % 7)
$weekStart = $today.AddDays(-$daysSinceMonday)
$nextWeekStart = $weekStart.AddDays(7)
$weekLabel = '{0}..{1}' -f $weekStart.ToString('yyyy-MM-dd'), $nextWeekStart.AddDays(-1).ToString('yyyy-MM-dd')
$findCommand = "find '$remoteRoot' -maxdepth 1 -type f -name '*.md' -newermt '$($weekStart.ToString('yyyy-MM-dd'))' ! -newermt '$($nextWeekStart.ToString('yyyy-MM-dd'))' -printf '%f\n' | sort"

$queryOutput = @(& ssh $remoteHost $findCommand 2>&1)
$queryExitCode = $LASTEXITCODE
if ($queryExitCode -ne 0) {
    Write-PullLog -ExitCode $queryExitCode -WeekLabel $weekLabel -Files @() -Output $queryOutput
    exit $queryExitCode
}

$remoteFiles = @(
    $queryOutput |
        ForEach-Object { "$_".Trim() } |
        Where-Object { $_ -match '^[A-Za-z0-9._-]+\.md$' }
)

if (-not (Test-Path -LiteralPath $dest)) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
}

$copiedFiles = @()
$copyOutput = @()
foreach ($fileName in $remoteFiles) {
    $remoteFile = "${remoteHost}:${remoteRoot}/${fileName}"
    $fileOutput = @(& scp -p $remoteFile "$dest\" 2>&1)
    $fileExitCode = $LASTEXITCODE
    $copyOutput += $fileOutput
    if ($fileExitCode -ne 0) {
        Write-PullLog -ExitCode $fileExitCode -WeekLabel $weekLabel -Files $copiedFiles -Output $copyOutput
        exit $fileExitCode
    }
    $copiedFiles += $fileName
}

Write-PullLog -ExitCode 0 -WeekLabel $weekLabel -Files $copiedFiles -Output $copyOutput
exit 0
