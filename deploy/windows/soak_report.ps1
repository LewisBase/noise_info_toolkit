param([Parameter(Mandatory = $true)][string]$Csv)
$rows = Import-Csv $Csv
$total = $rows.Count
$fail = @($rows | Where-Object { $_.status -ne "ok" }).Count
$first = $rows | Select-Object -First 1
$last = $rows | Select-Object -Last 1
Write-Host ("samples={0} failures={1} first={2} last={3}" -f $total, $fail, $first.timestamp, $last.timestamp)
if ($fail -gt 0) { exit 1 }
