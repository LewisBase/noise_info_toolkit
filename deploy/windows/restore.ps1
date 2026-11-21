param(
  [Parameter(Mandatory = $true)][string]$BackupDir,
  [string]$InstallDir = "C:\NoiseToolkit",
  [switch]$Force
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $BackupDir)) { throw "backup not found: $BackupDir" }
$db = Join-Path $BackupDir "noise_info.db"
if (-not (Test-Path $db)) { throw "backup DB not found: $db" }
if (-not $Force) {
  $answer = Read-Host "Restore will stop services and overwrite $InstallDir. Type YES"
  if ($answer -ne "YES") { throw "restore cancelled" }
}
$nssm = Join-Path $InstallDir "tools\nssm.exe"
if (Test-Path $nssm) {
  & $nssm stop NoiseBackend 2>$null | Out-Null
  & $nssm stop NoiseFrontend 2>$null | Out-Null
}
Copy-Item $db (Join-Path $InstallDir "Database\noise_info.db") -Force
$events = Join-Path $BackupDir "audio_events"
if (Test-Path $events) {
  $target = Join-Path $InstallDir "audio_events"
  if (Test-Path $target) { Remove-Item $target -Recurse -Force }
  Copy-Item $events $target -Recurse -Force
}
if (Test-Path $nssm) {
  & $nssm start NoiseBackend | Out-Null
  & $nssm start NoiseFrontend | Out-Null
}
Write-Host "Restore complete. Run smoke_test.ps1 and verify calibration/retention."
