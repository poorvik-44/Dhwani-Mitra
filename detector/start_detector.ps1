$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv-detector\Scripts\python.exe'
$entry = Join-Path $PSScriptRoot 'live_detector.py'
$workDir = Join-Path $projectRoot 'work'
$pidFile = Join-Path $workDir 'detector.pid'
$stderrFile = Join-Path $workDir 'detector-stderr.log'

if (-not (Test-Path $python)) {
    throw "Detector Python environment is missing: $python"
}

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like "*$entry*"
} | Select-Object -First 1

if ($existing) {
    Write-Output "YAMNet detector is already running (PID $($existing.ProcessId))."
    exit 0
}

New-Item -ItemType Directory -Path $workDir -Force | Out-Null
$env:DHVANI_DETECTOR_WS = 'ws://127.0.0.1:8000/ws/detector'

$process = Start-Process -FilePath $python `
    -ArgumentList "`"$entry`"" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput 'NUL' `
    -RedirectStandardError $stderrFile `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -NoNewline
Write-Output "Started YAMNet detector in the background (PID $($process.Id))."
if ($env:DHVANI_MIC_DEVICE) {
    Write-Output "Listening on the configured microphone: $env:DHVANI_MIC_DEVICE"
} else {
    Write-Output 'Listening on the Windows default input microphone.'
}
Write-Output 'Classifications are sent to the local FastAPI bridge.'
