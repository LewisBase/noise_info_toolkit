param(
  [string]$InstallDir = "C:\NoiseToolkit",
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$UiUrl = "http://127.0.0.1:8501"
)
$ErrorActionPreference = "Stop"
$py = "$InstallDir\.venv\Scripts\python.exe"
Write-Host "== files =="
foreach ($p in @("$InstallDir\.venv", "$InstallDir\requirements-field.txt", "$InstallDir\.env")) {
  if (-not (Test-Path $p)) { throw "missing: $p" }
}
Write-Host "== imports =="
& $py -c "import numpy, scipy, soundfile, nptdms, watchdog, loguru, streamlit; print('imports OK')"
Write-Host "== pip check =="
& $py -m pip check
Write-Host "== API =="
$ready = Invoke-RestMethod -Uri "$ApiBase/health/ready" -TimeoutSec 10
if ($ready.status -ne "ready") { throw "API not ready: $($ready.status)" }
Write-Host ("retention={0} calibrated={1} channels={2}" -f `
  $ready.retention_mode, $ready.calibrated, ($ready.channels -join ","))
Write-Host "== UI =="
$ui = Invoke-WebRequest -Uri $UiUrl -UseBasicParsing -TimeoutSec 10
if ($ui.StatusCode -ne 200) { throw "UI status $($ui.StatusCode)" }
Write-Host "smoke test OK"
