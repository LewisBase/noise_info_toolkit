param([string]$InstallDir = "C:\NoiseToolkit")
$ErrorActionPreference = "Stop"
Set-Location $InstallDir
& "$InstallDir\.venv\Scripts\python.exe" -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000 --workers 1
