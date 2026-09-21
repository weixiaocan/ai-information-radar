# 每周一只拉取服务器 /opt/ai-radar/exports 本周生成的播客文字稿。
# 由 Windows 计划任务「AI Radar Weekly Ebook Pull」调用。
$ErrorActionPreference = 'Stop'

$dest = 'D:\huangxh\obsidian\输出\公众号\草稿\每周播客'
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
