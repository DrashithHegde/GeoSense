################################################################################
# update_backend_app.ps1 — Update azapiodcij72zfek46 with new ACR image,
# ADMIN_TOKEN secret, and AZURE_CLIENT_ID for User-Assigned Managed Identity.
################################################################################
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$SUBSCRIPTION   = "77559dd2-c2bc-4301-a1aa-9b3020ab7aed"
$RESOURCE_GROUP = "geosense-eastasia-rg"
$APP_NAME       = "azapiodcij72zfek46"
$NEW_IMAGE      = "azacrodcij72zfek46.azurecr.io/geosense-api:20261125-durable-pipeline"
$ACR_SERVER     = "azacrodcij72zfek46.azurecr.io"
$ACR_USER       = "azacrodcij72zfek46"
$MANAGED_ID_CID = "89d1ab76-31d9-4ea8-8fc9-e8928bc1fc08"
$ARM_API        = "2024-03-01"

$adminToken = (Get-Content "$env:TEMP\admin_token.txt" -Raw -ErrorAction Stop).Trim()
$acrPass    = (az acr credential show -n azacrodcij72zfek46 --query "passwords[0].value" -o tsv 2>&1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $acrPass) { throw "Failed to get ACR credential" }

$tok = (az account get-access-token --resource https://management.azure.com --query accessToken -o tsv 2>&1).Trim()
$headers = @{ Authorization = "Bearer $tok"; "Content-Type" = "application/json" }

function Invoke-Arm($method, $path, $body = $null) {
    $uri = "https://management.azure.com$path`?api-version=$ARM_API"
    $json = if ($body) { $body | ConvertTo-Json -Depth 20 -Compress } else { $null }
    for ($i = 1; $i -le 5; $i++) {
        try {
            if ($json) { return Invoke-RestMethod -Method $method -Uri $uri -Headers $headers -Body $json }
            return Invoke-RestMethod -Method $method -Uri $uri -Headers $headers
        } catch {
            if ($i -ge 5) { throw $_ }
            Write-Warning "ARM $method attempt $i failed: $($_.Exception.Message). Retrying..."
            Start-Sleep ($i * 3)
        }
    }
}

$basePath = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/containerApps/$APP_NAME"
$app = Invoke-Arm "Get" $basePath
$secretsResp = Invoke-Arm "Post" "$basePath/listSecrets"

# Rebuild secrets list preserving existing values
$secretsMap = @{}
foreach ($s in $secretsResp.value) {
    $secretsMap[$s.name] = $s.value
}
$secretsMap["admin-token"] = $adminToken
$secretsMap["acr-password"] = $acrPass
$newSecrets = @()
foreach ($k in $secretsMap.Keys) {
    $newSecrets += @{ name = $k; value = $secretsMap[$k] }
}

# Update env vars preserving existing ones
$envList = @()
$existingNames = @{}
foreach ($e in $app.properties.template.containers[0].env) {
    $existingNames[$e.name] = $true
    if ($e.name -eq "ADMIN_TOKEN") {
        $envList += @{ name = "ADMIN_TOKEN"; secretRef = "admin-token" }
    } elseif ($e.name -eq "AZURE_CLIENT_ID") {
        $envList += @{ name = "AZURE_CLIENT_ID"; value = $MANAGED_ID_CID }
    } else {
        $envList += $e
    }
}
if (-not $existingNames.ContainsKey("ADMIN_TOKEN")) {
    $envList += @{ name = "ADMIN_TOKEN"; secretRef = "admin-token" }
}
if (-not $existingNames.ContainsKey("AZURE_CLIENT_ID")) {
    $envList += @{ name = "AZURE_CLIENT_ID"; value = $MANAGED_ID_CID }
}

$app.properties.configuration.secrets = $newSecrets
$app.properties.configuration.registries = @(
    @{ server = $ACR_SERVER; username = $ACR_USER; passwordSecretRef = "acr-password" }
)
$app.properties.template.containers[0].image = $NEW_IMAGE
$app.properties.template.containers[0].env = $envList

Write-Host "Updating backend Container App $APP_NAME -> $NEW_IMAGE ..."
$updated = Invoke-Arm "Put" $basePath $app
Write-Host "ProvisioningState: $($updated.properties.provisioningState)"
Write-Host "LatestRevision: $($updated.properties.latestRevisionName)"
Write-Host "Image: $($updated.properties.template.containers[0].image)"
