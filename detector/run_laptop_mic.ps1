$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv-detector\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Detector environment is missing: $python"
}

Push-Location $projectRoot
try {
    & $python -u '.\detector\live_detector.py'
    if ($LASTEXITCODE -ne 0) {
        throw "Detector exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
