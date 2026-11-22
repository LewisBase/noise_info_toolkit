param([string]$InstallDir = "C:\NoiseToolkit")
$ErrorActionPreference = "Stop"
Set-Location $InstallDir
& "$InstallDir\.venv\Scripts\python.exe" -m streamlit run app/web/streamlit_app.py --global.developmentMode=false --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
