param([string]$BaseUrl = "http://127.0.0.1:8000")
$ErrorActionPreference = "Stop"
$response = Invoke-RestMethod -Uri "$BaseUrl/health/ready" -TimeoutSec 10
if ($response.status -ne "ready") { throw "not ready: $($response.status)" }
Write-Host "ready; retention=$($response.retention_mode); calibrated=$($response.calibrated)"
