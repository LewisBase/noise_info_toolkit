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

# Allow both `-UvPath uv` and an accidentally empty/null -UvPath.
if ([string]::IsNullOrWhiteSpace($UvPath)) { $UvPath = "uv" }
$uvExe = $UvPath
$uvCommand = Get-Command $UvPath -ErrorAction SilentlyContinue
if ($uvCommand) {
  if (-not [string]::IsNullOrWhiteSpace($uvCommand.Source)) {
    $uvExe = $uvCommand.Source
  } elseif (-not [string]::IsNullOrWhiteSpace($uvCommand.Name)) {
    $uvExe = $uvCommand.Name
  }
} elseif (-not (Test-Path $UvPath)) {
  $candidates = @(
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
    (Join-Path $InstallDir "tools\uv.exe")
  )
  $uvExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($uvExe) -or
    (-not (Get-Command $uvExe -ErrorAction SilentlyContinue) -and
     -not (Test-Path $uvExe))) {
  throw "uv not found. Install uv or pass -UvPath C:\path\uv.exe."
}
Write-Host "Using uv: $uvExe"
if (-not (Test-Path "$InstallDir\pyproject.toml")) {
  throw "pyproject.toml missing in $InstallDir"
}
if (-not (Test-Path "$InstallDir\uv.lock")) {
  throw "uv.lock missing in $InstallDir"
}

# Managed Python 3.11, no system Python installation required.
& $uvExe python install 3.11
if ($LASTEXITCODE -ne 0) { throw "uv python install failed" }
& $uvExe sync --frozen --python 3.11
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

if (-not (Test-Path "$InstallDir\.env")) {
  Copy-Item "$InstallDir\.env.example" "$InstallDir\.env"
}
$py = "$InstallDir\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "uv did not create .venv" }
& $py -c "from app.config import Settings; s=Settings(); print('config ok', s.retention_mode); import numpy, scipy, soundfile, nptdms, watchdog, loguru, streamlit, pyarrow; print('imports ok')"
if ($LASTEXITCODE -ne 0) { throw "import smoke test failed" }
Write-Host "Installation complete. Retention defaults to debug (no deletion)."
