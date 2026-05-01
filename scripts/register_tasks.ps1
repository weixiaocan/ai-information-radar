param(
    [string]$TaskPrefix = "AI Radar",
    [string]$PythonExe = "",
    [string]$RunAsUser = "SYSTEM",
    [string]$DailyTime = "08:00",
    [string]$IngestTime = "07:00",
    [string]$Tier1Time = "07:30",
    [string]$DailyCurateTime = "07:50",
    [string]$Tier2Time = "11:00",
    [string]$WeeklyTime = "12:00"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $PSScriptRoot "run_pipeline.ps1"
$resolvedPythonExe = $PythonExe

if ([string]::IsNullOrWhiteSpace($resolvedPythonExe)) {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $resolvedPythonExe = $venvPython
    }
}

if (-not (Test-Path $runScript)) {
    throw "Missing runner script: $runScript"
}

if ([string]::IsNullOrWhiteSpace($resolvedPythonExe) -or -not (Test-Path $resolvedPythonExe)) {
    throw "Python executable not found. Pass -PythonExe or create .venv first."
}

function Register-AIRadarTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$TaskName,
        [Parameter(Mandatory = $true)]
        [string]$TriggerTime,
        [switch]$Deliver,
        [switch]$Weekly,
        [string]$DaysOfWeek = "Sunday"
    )

    $taskFullName = "$TaskPrefix $Name"
    $scriptArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $runScript),
        "-PythonExe", ('"{0}"' -f $resolvedPythonExe),
        "-Task", $TaskName
    )

    if ($Deliver) {
        $scriptArguments += "-Deliver"
    }

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($scriptArguments -join " ")
    $principal = if ($RunAsUser -eq "SYSTEM") {
        New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    }
    else {
        New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType Interactive -RunLevel Limited
    }

    if ($Weekly) {
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $TriggerTime
    }
    else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $TriggerTime
    }

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -WakeToRun

    Register-ScheduledTask `
        -TaskName $taskFullName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "AI Radar automation task for $TaskName" `
        -Force | Out-Null
}

Register-AIRadarTask -Name "Ingest" -TaskName "ingest" -TriggerTime $IngestTime
Register-AIRadarTask -Name "Tier1" -TaskName "tier1" -TriggerTime $Tier1Time
Register-AIRadarTask -Name "Daily Curate" -TaskName "daily-curate" -TriggerTime $DailyCurateTime
Register-AIRadarTask -Name "Daily Digest" -TaskName "daily" -TriggerTime $DailyTime -Deliver
Register-AIRadarTask -Name "Tier2" -TaskName "tier2" -TriggerTime $Tier2Time -Weekly
Register-AIRadarTask -Name "Weekly Digest" -TaskName "weekly" -TriggerTime $WeeklyTime -Weekly -Deliver
