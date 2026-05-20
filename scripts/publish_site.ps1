param(
    [string]$PythonExe = "",
    [string]$Task = "publish-site"
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

Push-Location $projectRoot
try {
    & $resolvedPythonExe (Join-Path $projectRoot "main.py") --task $Task
}
finally {
    Pop-Location
}
