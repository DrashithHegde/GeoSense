# verify_api_endpoints.ps1
# After DB population, verify all key API endpoints return real data.

$base = "https://azapiodcij72zfek46.wonderfulrock-df4f34b7.eastasia.azurecontainerapps.io"

function Check-Endpoint {
    param([string]$Path, [string]$Expect = "")
    $url = "$base$Path"
    try {
        $resp = Invoke-RestMethod -Uri $url -UseBasicParsing -ErrorAction Stop
        $json = $resp | ConvertTo-Json -Depth 3 -Compress
        $truncated = if ($json.Length -gt 300) { $json.Substring(0, 300) + "..." } else { $json }
        Write-Host "[OK] $Path => $truncated"
        return $resp
    } catch {
        Write-Host "[FAIL] $Path => $($_.ToString())"
        return $null
    }
}

Write-Host "===== System Status ====="
Check-Endpoint "/api/system/status"

Write-Host ""
Write-Host "===== Surfaces ====="
foreach ($layer in @("ndvi","lst","water-health","aqi","composite")) {
    Check-Endpoint "/api/surfaces/$layer/latest"
}

Write-Host ""
Write-Host "===== Surface Point Values (Mumbai CBD: 72.8777, 19.0760) ====="
foreach ($layer in @("ndvi","lst","water-health","aqi","composite")) {
    Check-Endpoint "/api/surfaces/$layer/value?lon=72.8777&lat=19.0760"
}

Write-Host ""
Write-Host "===== Analysis Endpoints ====="
Check-Endpoint "/api/analysis/point?lon=72.8777&lat=19.0760"
Check-Endpoint "/api/ml/hotspots"
Check-Endpoint "/api/municipalities/latest"

Write-Host ""
Write-Host "===== History ====="
Check-Endpoint "/api/history/point?lon=72.8777&lat=19.0760"

Write-Host ""
Write-Host "Done"
