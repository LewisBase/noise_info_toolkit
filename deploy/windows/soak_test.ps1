param(
  [string]$ApiBase = "http://127.0.0.1:8000",
  [int]$Days = 7,
  [int]$IntervalSeconds = 300,
  [string]$LogDir = "C:\NoiseToolkit\log"
)
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$csv = Join-Path $LogDir ("soak_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".csv")
"timestamp,status,http_code,queue_depth,monitoring,message" | Set-Content $csv
$end = (Get-Date).AddDays($Days)
$failures = 0
while ((Get-Date) -lt $end) {
  $stamp = (Get-Date).ToString("o")
  try {
    $response = Invoke-WebRequest -Uri "$ApiBase/health/ready" -UseBasicParsing -TimeoutSec 15
    $body = $response.Content | ConvertFrom-Json
    $line = "{0},{1},{2},{3},{4},{5}" -f $stamp, "ok", $response.StatusCode,
      $body.processing.queue_depth, $body.processing.monitoring, ""
    Add-Content $csv $line
  } catch {
    $failures++
    $line = "{0},{1},{2},{3},{4},{5}" -f $stamp, "fail", "", "", "",
      ($_.Exception.Message -replace ",", ";")
    Add-Content $csv $line
  }
  Start-Sleep -Seconds $IntervalSeconds
}
Write-Host ("soak finished; failures={0}; log={1}" -f $failures, $csv)
if ($failures -gt 0) { exit 1 }
