param(
  [string]$InstallDir = "C:\NoiseToolkit",
  [string]$UvPath = "uv"
)
$ErrorActionPreference = "Stop"
Write-Host "Installing Noise Toolkit into $InstallDir using uv"
New-Item -ItemType Directory -Force $InstallDir | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\audio_files" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\audio_events" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\Database" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\log" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\temp" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\trash" | Out-Null
New-Item -ItemType Directory -Force "$InstallDir\tools" | Out-Null

Set-Location $InstallDir
if (-not (Get-Command $UvPath -ErrorAction SilentlyContinue) -and -not (Test-Path $UvPath)) {
  throw "uv not found: $UvPath. Run bootstrap.ps1 or install uv first."
}
if (-not (Test-Path "$InstallDir\pyproject.toml")) {
  throw "pyproject.toml missing in $InstallDir"
}
if (-not (Test-Path "$InstallDir\uv.lock")) {
  throw "uv.lock missing in $InstallDir"
}

# Managed Python 3.11, no system Python installation required.
& $UvPath python install 3.11
if ($LASTEXITCODE -ne 0) { throw "uv python install failed" }
& $UvPath sync --frozen --python 3.11
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

if (-not (Test-Path "$InstallDir\.env")) {
  Copy-Item "$InstallDir\.env.example" "$InstallDir\.env"
}
$py = "$InstallDir\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "uv did not create .venv" }
& $py -c "from app.config import Settings; s=Settings(); print('config ok', s.retention_mode); import numpy, scipy, soundfile, nptdms, watchdog, loguru, streamlit, pyarrow; print('imports ok')"
if ($LASTEXITCODE -ne 0) { throw "import smoke test failed" }
Write-Host "Installation complete. Retention defaults to debug (no deletion)."
