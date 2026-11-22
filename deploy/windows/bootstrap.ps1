param(
  [string]$InstallDir = "D:\NoiseToolkit",
  [string]$RepoRef = "main",
  [string]$SourceZip = "",
  [switch]$SkipDependencies
)
$ErrorActionPreference = "Stop"
Write-Host "Noise Toolkit one-click bootstrap"
Write-Host "InstallDir: $InstallDir"
Write-Host "RepoRef:    $RepoRef"

# 1. Install uv if needed (no system Python required).
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
  Write-Host "Installing uv..."
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $uvPath = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
  if (-not (Test-Path $uvPath)) {
    throw "uv installation did not produce $uvPath"
  }
  $uv = Get-Item $uvPath
}
$uvExe = $uv.Source
if ([string]::IsNullOrWhiteSpace($uvExe)) { $uvExe = $uv.Name }
if ([string]::IsNullOrWhiteSpace($uvExe)) { $uvExe = "uv" }
Write-Host "uv: $uvExe"

# 2. Use a local source zip when provided (offline transfer), otherwise
#    download the repository archive.  GitHub supports archive/<ref>.zip for
#    both branches and tags; the old refs/heads/<tag>.zip form returned 404.
$tempRoot = Join-Path $env:TEMP ("nit-bootstrap-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $tempRoot | Out-Null
if ($SourceZip) {
  if (-not (Test-Path $SourceZip)) {
    throw "SourceZip not found: $SourceZip"
  }
  Write-Host "Using local source archive: $SourceZip"
  Expand-Archive -Path $SourceZip -DestinationPath $tempRoot -Force
} else {
  $zip = Join-Path $tempRoot "source.zip"
  $url = "https://github.com/LewisBase/noise_info_toolkit/archive/$RepoRef.zip"
  Write-Host "Downloading $url"
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  Expand-Archive -Path $zip -DestinationPath $tempRoot -Force
}
$source = Get-ChildItem $tempRoot -Directory |
  Where-Object { Test-Path (Join-Path $_.FullName "pyproject.toml") } |
  Select-Object -First 1
if ($source) {
  $sourcePath = $source.FullName
} elseif (Test-Path (Join-Path $tempRoot "pyproject.toml")) {
  $sourcePath = $tempRoot
} else {
  throw "source archive has no pyproject.toml"
}

New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item (Join-Path $sourcePath "*") $InstallDir -Recurse -Force
Write-Host "Code copied to $InstallDir"

# 3. uv-managed Python + dependency sync + .env.
if (-not $SkipDependencies) {
  & "$InstallDir\deploy\windows\install.ps1" -InstallDir $InstallDir -UvPath $uvExe
  if ($LASTEXITCODE -ne 0) { throw "install.ps1 failed" }
}
Write-Host "Bootstrap complete. Start with run_backend.ps1 / run_frontend.ps1 or install_services.ps1."
