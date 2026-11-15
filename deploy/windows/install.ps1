param(
  [string]$InstallDir = "C:\NoiseToolkit",
  [string]$Python = "py"
)
$ErrorActionPreference = "Stop"
Write-Host "Installing Noise Toolkit into $InstallDir"
New-Item -ItemType Directory -Force $InstallDir | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\audio_files" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\audio_events" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\Database" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\log" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\temp" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\trash" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\tools" | Out-Null

Set-Location $InstallDir
if (-not (Test-Path "$InstallDir\.venv")) {
  & $Python -3.11 -m venv "$InstallDir\.venv"
}
$py = "$InstallDir\.venv\Scripts\python.exe"
& $py -m pip install -U pip wheel
& $py -m pip install -r "$InstallDir\requirements-field.txt"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $py -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed" }

if (-not (Test-Path "$InstallDir\.env")) {
  Copy-Item "$InstallDir\.env.example" "$InstallDir\.env"
}
& $py -c "from app.config import Settings; s=Settings(); print('config ok', s.retention_mode); import numpy, scipy, soundfile, nptdms, watchdog, loguru, streamlit; print('imports ok')"
Write-Host "Installation complete. Retention defaults to debug (no deletion)."
