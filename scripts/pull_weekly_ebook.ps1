# 每周一拉取服务器 /opt/ai-radar/exports 的播客文字稿到本机公众号文章目录。
# 由 Windows 计划任务「AI Radar Weekly Ebook Pull」调用。
$ErrorActionPreference = 'Continue'

$dest = 'D:\huangxh\obsidian\输出\公众号\草稿\每周播客'
$remote = 'ai-radar-server:/opt/ai-radar/exports/*.md'
$log = 'D:\huangxh\AI_Projects_100\p22_AI_Radar\state\logs\weekly-ebook-pull.log'

if (-not (Test-Path $dest)) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
}

$out = scp $remote "$dest\" 2>&1
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"[{0}] exit={1} out={2}" -f $ts, $LASTEXITCODE, (($out | Out-String).Trim() -replace "`r?`n", ' | ') | Out-File -Append -Encoding utf8 $log
exit 0
