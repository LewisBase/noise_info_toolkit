param(
  [string]$InstallDir = "C:\NoiseToolkit",
  [string]$RepoRef = "feat/field-deployment-hardening",
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
Write-Host "uv: $($uv.Source)"

# 2. Download the repository archive (no manual code copy).
$tempRoot = Join-Path $env:TEMP ("nit-bootstrap-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $tempRoot | Out-Null
$zip = Join-Path $tempRoot "source.zip"
$url = "https://github.com/LewisBase/noise_info_toolkit/archive/refs/heads/$RepoRef.zip"
Write-Host "Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $tempRoot -Force
$source = Get-ChildItem $tempRoot -Directory | Select-Object -First 1
if (-not $source) { throw "downloaded repository is empty" }

New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item (Join-Path $source.FullName "*") $InstallDir -Recurse -Force
Write-Host "Code copied to $InstallDir"

# 3. uv-managed Python + dependency sync + .env.
& "$InstallDir\deploy\windows\install.ps1" -InstallDir $InstallDir -UvPath $uv.Source
Write-Host "Bootstrap complete. Start with run_backend.ps1 / run_frontend.ps1 or install_services.ps1."
