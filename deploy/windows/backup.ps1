param(
  [string]$InstallDir = "C:\NoiseToolkit",
  [string]$BackupDir = "D:\NoiseBackup"
)
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $BackupDir $stamp
New-Item -ItemType Directory -Force $dest | Out-Null
$py = "$InstallDir\.venv\Scripts\python.exe"
$db = "$InstallDir\Database\noise_info.db"
if (Test-Path $db) {
  # Use sqlite backup API, not a raw copy of a live WAL database.
  & $py -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $db (Join-Path $dest "noise_info.db")
}
foreach ($name in @("audio_events")) {
  $src = Join-Path $InstallDir $name
  if (Test-Path $src) { Copy-Item $src (Join-Path $dest $name) -Recurse -Force }
}
Write-Host "Backup written to $dest"
