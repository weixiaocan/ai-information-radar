param(
    [Parameter(Mandatory = $true)]
    [string]$Task,

    [string]$PythonExe = "",

    [switch]$Deliver,

    [int]$Days = 0,

    [switch]$IgnoreSeen
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedPythonExe = $PythonExe

if ([string]::IsNullOrWhiteSpace($resolvedPythonExe)) {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $resolvedPythonExe = $venvPython
    }
}

if ([string]::IsNullOrWhiteSpace($resolvedPythonExe) -or -not (Test-Path $resolvedPythonExe)) {
    throw "Python executable not found. Pass -PythonExe or create .venv first."
}

$logsDir = Join-Path $projectRoot "state\logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logsDir "$Task-$timestamp.log"
$stdoutPath = Join-Path $logsDir "$Task-$timestamp.stdout.log"
$stderrPath = Join-Path $logsDir "$Task-$timestamp.stderr.log"

$arguments = @(
    (Join-Path $projectRoot "main.py")
    "--task"
    $Task
)

if ($Deliver) {
    $arguments += "--deliver"
}

if ($Days -gt 0) {
    $arguments += @("--days", $Days.ToString())
}

if ($IgnoreSeen) {
    $arguments += "--ignore-seen"
}

Push-Location $projectRoot
try {
    $process = Start-Process `
        -FilePath $resolvedPythonExe `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -Wait `
        -PassThru `
        -NoNewWindow

    $stdout = if (Test-Path $stdoutPath) { Get-Content $stdoutPath -Raw } else { "" }
    $stderr = if (Test-Path $stderrPath) { Get-Content $stderrPath -Raw } else { "" }
    $combined = @($stdout, $stderr) -join ""
    Set-Content -Path $logPath -Value $combined -Encoding UTF8

    if ($stdout) {
        Write-Output $stdout.TrimEnd()
    }

    if ($stderr) {
        Write-Output $stderr.TrimEnd()
    }

    if ($process.ExitCode -ne 0) {
        throw "Pipeline exited with code $($process.ExitCode)"
    }
}
finally {
    Pop-Location
}
