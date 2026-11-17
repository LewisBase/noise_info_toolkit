param(
  [string]$InstallDir = "C:\NoiseToolkit",
  [string]$Nssm = "$InstallDir\tools\nssm.exe"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Nssm)) { throw "nssm.exe not found: $Nssm" }
$py = "$InstallDir\.venv\Scripts\python.exe"

& $Nssm install NoiseBackend $py
& $Nssm set NoiseBackend AppParameters "-m uvicorn app.api.app:app --host 127.0.0.1 --port 8000 --workers 1"
& $Nssm set NoiseBackend AppDirectory $InstallDir
& $Nssm set NoiseBackend AppStdout "$InstallDir\log\backend-stdout.log"
& $Nssm set NoiseBackend AppStderr "$InstallDir\log\backend-stderr.log"
& $Nssm set NoiseBackend AppExit Default Restart
& $Nssm set NoiseBackend AppRestartDelay 5000
& $Nssm start NoiseBackend

& $Nssm install NoiseFrontend $py
& $Nssm set NoiseFrontend AppParameters "-m streamlit run app/web/streamlit_app.py --global.developmentMode=false --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false"
& $Nssm set NoiseFrontend AppDirectory $InstallDir
& $Nssm set NoiseFrontend AppStdout "$InstallDir\log\frontend-stdout.log"
& $Nssm set NoiseFrontend AppStderr "$InstallDir\log\frontend-stderr.log"
& $Nssm set NoiseFrontend AppExit Default Restart
& $Nssm set NoiseFrontend AppRestartDelay 5000
& $Nssm start NoiseFrontend
Write-Host "Services installed. Check http://127.0.0.1:8000/health/ready"
