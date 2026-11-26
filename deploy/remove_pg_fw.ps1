[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$subId = "77559dd2-c2bc-4301-a1aa-9b3020ab7aed"
$rg = "geosense-eastasia-rg"
$pgName = "azpgodcij72zfek46"
$apiVerPg = "2022-12-01"
$fwRuleName = "temp-deploy-client"

$token = (az account get-access-token --resource https://management.azure.com --query accessToken -o tsv 2>&1)
if ($LASTEXITCODE -ne 0 -or -not $token) { Write-Error "Failed to get token"; exit 1 }
$headers = @{ "Authorization" = "Bearer $token" }
$fwUrl = "https://management.azure.com/subscriptions/$subId/resourceGroups/$rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/$pgName/firewallRules/${fwRuleName}?api-version=$apiVerPg"

for ($i = 1; $i -le 5; $i++) {
    try {
        Invoke-RestMethod -Uri $fwUrl -Method DELETE -Headers $headers -UseBasicParsing -ErrorAction Stop | Out-Null
        Write-Host "Firewall rule '$fwRuleName' deleted."
        exit 0
    } catch {
        Write-Host "Attempt $i failed. Retrying..."
        Start-Sleep -Seconds 3
    }
}
Write-Error "Failed to delete firewall rule '$fwRuleName'"
exit 1
