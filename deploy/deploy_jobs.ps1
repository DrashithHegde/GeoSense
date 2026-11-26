################################################################################
# deploy_jobs.ps1 — Deploy GeoSense Azure Container Apps Jobs via ARM REST API
# Usage: Set-Location <repo_root>; .\deploy\deploy_jobs.ps1
# Requires: az login completed; ADMIN_TOKEN in $env:TEMP\admin_token.txt
################################################################################
param(
    [switch]$SkipGeeJobs    # Pass -SkipGeeJobs if GEE_SERVICE_ACCOUNT_JSON is not yet configured
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── constants ──────────────────────────────────────────────────────────────────
$SUBSCRIPTION  = "77559dd2-c2bc-4301-a1aa-9b3020ab7aed"
$RESOURCE_GROUP = "geosense-eastasia-rg"
$JOBS_ENV       = "geosense-jobs-env"
$BACKEND_IMAGE  = "azacrodcij72zfek46.azurecr.io/geosense-api:20261125-durable-pipeline"
$ACR_SERVER     = "azacrodcij72zfek46.azurecr.io"
$ACR_USER       = "azacrodcij72zfek46"
$MANAGED_ID_RID = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/azidodcij72zfek46"
$MANAGED_ID_CID = "89d1ab76-31d9-4ea8-8fc9-e8928bc1fc08"
$BACKEND_URL    = "https://azapiodcij72zfek46.wonderfulrock-df4f34b7.eastasia.azurecontainerapps.io"
$RELOAD_URL     = "$BACKEND_URL/api/admin/bundle/reload"
$ARM_API        = "2024-03-01"

# ── read secrets from temp files (never print them) ───────────────────────────
$adminToken = (Get-Content "$env:TEMP\admin_token.txt" -Raw -ErrorAction Stop).Trim()
$dbUrl      = (Get-Content "$env:TEMP\db_url.txt"    -Raw -ErrorAction Stop).Trim()
$acrPass    = (az acr credential show -n azacrodcij72zfek46 --query "passwords[0].value" -o tsv 2>&1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $acrPass) { throw "Failed to get ACR credential" }

# ── get ARM token via az cli ───────────────────────────────────────────────────
Write-Host "Getting ARM token..."
$armToken = (az account get-access-token --resource https://management.azure.com --query accessToken -o tsv 2>&1)
if ($LASTEXITCODE -ne 0) { throw "az account get-access-token failed: $armToken" }

$headers = @{
    Authorization  = "Bearer $armToken"
    "Content-Type" = "application/json"
}

function Invoke-ArmPut($resourceId, $body) {
    $uri = "https://management.azure.com$resourceId`?api-version=$ARM_API"
    $json = $body | ConvertTo-Json -Depth 20 -Compress
    for ($i = 1; $i -le 5; $i++) {
        try {
            $resp = Invoke-RestMethod -Method Put -Uri $uri -Headers $headers -Body $json
            return $resp
        } catch {
            if ($i -ge 5) { throw $_ }
            Write-Warning "ARM PUT attempt $i failed: $($_.Exception.Message). Retrying in $($i*4)s..."
            Start-Sleep ($i * 4)
        }
    }
}

function Invoke-ArmGet($resourceId) {
    $uri = "https://management.azure.com$resourceId`?api-version=$ARM_API"
    for ($i = 1; $i -le 5; $i++) {
        try { return Invoke-RestMethod -Method Get -Uri $uri -Headers $headers }
        catch {
            if ($i -ge 5) { throw $_ }
            Start-Sleep ($i * 4)
        }
    }
}

# ── common environment variables (non-secret) ─────────────────────────────────
$commonEnv = @(
    @{ name = "AZURE_STORAGE_ACCOUNT_URL"; value = "https://azstodcij72zfek46.blob.core.windows.net" }
    @{ name = "AZURE_STORAGE_CONTAINER";   value = "geosense" }
    @{ name = "AZURE_CLIENT_ID";           value = $MANAGED_ID_CID }
    @{ name = "CITY";                      value = "mumbai" }
    @{ name = "BACKEND_RELOAD_URL";        value = $RELOAD_URL }
    @{ name = "GEE_PROJECT";               value = "flowing-tooling-480716-p6" }
)

# ── common secrets ────────────────────────────────────────────────────────────
# (secrets are defined per-job; values set via secretRef in env)
function Get-CommonSecrets {
    @(
        @{ name = "database-url";  value = $dbUrl      }
        @{ name = "admin-token";   value = $adminToken }
        @{ name = "acr-password";  value = $acrPass    }
    )
}

function Get-CommonSecretEnv {
    @(
        @{ name = "DATABASE_URL"; secretRef = "database-url"  }
        @{ name = "DB_SSLMODE";   value     = "require"        }
        @{ name = "ADMIN_TOKEN";  secretRef = "admin-token"   }
    )
}

# ── job template helper ───────────────────────────────────────────────────────
function Make-JobBody($jobName, $cronExpr, $command, $extraEnv, $extraSecrets) {
    $allSecrets = (Get-CommonSecrets) + $extraSecrets
    $allEnv     = $commonEnv + (Get-CommonSecretEnv) + $extraEnv
    @{
        location = "eastasia"
        identity = @{
            type = "UserAssigned"
            userAssignedIdentities = @{
                $MANAGED_ID_RID = @{}
            }
        }
        properties = @{
            environmentId = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/managedEnvironments/$JOBS_ENV"
            configuration = @{
                triggerType = "Schedule"
                replicaTimeout = 3600
                replicaRetryLimit = 1
                scheduleTriggerConfig = @{
                    cronExpression           = $cronExpr
                    parallelism              = 1
                    replicaCompletionCount   = 1
                }
                secrets = $allSecrets
                registries = @(
                    @{ server = $ACR_SERVER; username = $ACR_USER; passwordSecretRef = "acr-password" }
                )
            }
            template = @{
                containers = @(
                    @{
                        name    = $jobName
                        image   = $BACKEND_IMAGE
                        command = @("/bin/sh", "-c", $command)
                        env     = $allEnv
                        resources = @{
                            cpu    = 1.0
                            memory = "2Gi"
                        }
                    }
                )
            }
        }
    }
}

# ── Job 1: AQI + composite (every 3 hours) ─────────────────────────────────────
Write-Host "`n=== Deploying geosense-job-aqi ==="
$aqiCmd = "cd /app && python scripts/run_azure_job.py --job-name geosense-job-aqi --city mumbai --only aqi --only composite --publish"
$aqiId  = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/jobs/geosense-job-aqi"
$aqiBody = Make-JobBody "geosense-job-aqi" "0 */3 * * *" $aqiCmd @(
    @{ name = "OPENAQ_AQI_KEY"; secretRef = "openaq-aqi-key" }
) @(
    @{ name = "openaq-aqi-key"; value = $env:OPENAQ_AQI_KEY }
)
$r = Invoke-ArmPut $aqiId $aqiBody
Write-Host "AQI job: $($r.properties.provisioningState)"

# ── Job 4: ML pipeline (Tuesdays 04:00 UTC, after satellite Monday) ─────────────
Write-Host "`n=== Deploying geosense-job-ml ==="
$mlCmd  = "cd /app && python scripts/run_azure_job.py --job-name geosense-job-ml --city mumbai --only ml --publish"
$mlId   = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/jobs/geosense-job-ml"
$mlBody = Make-JobBody "geosense-job-ml" "0 4 * * 2" $mlCmd @() @()
$r = Invoke-ArmPut $mlId $mlBody
Write-Host "ML job: $($r.properties.provisioningState)"

if (-not $SkipGeeJobs) {
    # ── Job 2: Satellite NDVI + Water Health (Mondays 02:00 UTC, weekly) ─────────
    Write-Host "`n=== Deploying geosense-job-satellite ==="
    $satCmd  = "cd /app && python scripts/run_azure_job.py --job-name geosense-job-satellite --city mumbai --only ndvi --only water --only indices --only render --publish"
    $satId   = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/jobs/geosense-job-satellite"
    $satBody = Make-JobBody "geosense-job-satellite" "0 2 * * 1" $satCmd @(
        @{ name = "GEE_SERVICE_ACCOUNT_JSON"; secretRef = "gee-sa-json" }
    ) @(
        @{ name = "gee-sa-json"; value = $env:GEE_SERVICE_ACCOUNT_JSON }
    )
    $r = Invoke-ArmPut $satId $satBody
    Write-Host "Satellite job: $($r.properties.provisioningState)"

    # ── Job 3: LST (every 4 days at 03:00 UTC) ───────────────────────────────────
    Write-Host "`n=== Deploying geosense-job-lst ==="
    $lstCmd  = "cd /app && python scripts/run_azure_job.py --job-name geosense-job-lst --city mumbai --only lst --only render --publish"
    $lstId   = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/jobs/geosense-job-lst"
    $lstBody = Make-JobBody "geosense-job-lst" "0 3 */4 * *" $lstCmd @(
        @{ name = "GEE_SERVICE_ACCOUNT_JSON"; secretRef = "gee-sa-json" }
    ) @(
        @{ name = "gee-sa-json"; value = $env:GEE_SERVICE_ACCOUNT_JSON }
    )
    $r = Invoke-ArmPut $lstId $lstBody
    Write-Host "LST job: $($r.properties.provisioningState)"
} else {
    Write-Host "`n[SKIPPED] GEE jobs (geosense-job-satellite, geosense-job-lst) — pass GEE_SERVICE_ACCOUNT_JSON to enable"
}

Write-Host "`n=== All jobs deployed. Verifying... ==="
$jobNames = @("geosense-job-aqi","geosense-job-ml")
if (-not $SkipGeeJobs) { $jobNames += @("geosense-job-satellite","geosense-job-lst") }
foreach ($jn in $jobNames) {
    $jid = "/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/jobs/$jn"
    $j = Invoke-ArmGet $jid
    Write-Host "  $jn => provisioningState=$($j.properties.provisioningState)"
}
Write-Host "`nDone."
