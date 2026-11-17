<#
  GeoSense one-shot setup for Windows (PowerShell).
    powershell -ExecutionPolicy Bypass -File .\setup.ps1                       # everything, Mumbai
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -City delhi           # install + build Delhi
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -PipelineOnly -City bengaluru
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoDocker             # use your own Postgres
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Upgrade              # DB upgrade + data + ML + history
    add -History to (re)build the seasonal history (Earth Engine + OpenAQ, ~30-60 min per city)
  A city whose satellite layers do not exist yet (Delhi, Bengaluru on a fresh copy) is built from
  scratch with Earth Engine + OpenAQ (scripts\setup_city.py); one that has them is refreshed.
#>
param([switch]$PipelineOnly, [switch]$NoDocker, [switch]$Upgrade, [switch]$History,
      [ValidateSet("mumbai", "delhi", "bengaluru")][string]$City = "mumbai")
if ($Upgrade) { $PipelineOnly = $true; $History = $true }
$ErrorActionPreference = "Stop"
$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Root "server"
$Client = Join-Path $Root "client"
$Py     = Join-Path $Server ".venv\Scripts\python.exe"

function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Need($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Write-Host "Missing: $cmd  -> $hint" -ForegroundColor Red; exit 1 }
}
function Run-Py($script, [string[]]$a = @(), [switch]$AllowFail) {
  Push-Location $Server
  $env:PYTHONUTF8 = "1"
  & $Py $script @a | Out-Host
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0 -and -not $AllowFail) { throw "$script failed (exit $code)" }
  return $code
}

# ---- .env ------------------------------------------------------------------
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $Root ".env.example") $EnvFile
  Write-Host "Created .env from .env.example. Fill in OPENAQ_AQI_KEY and VITE_MAPBOX_TOKEN, then re-run." -ForegroundColor Yellow
  notepad $EnvFile
  exit 0
}
$cfg = @{}
Get-Content $EnvFile | Where-Object { $_ -match '^\s*([A-Z_]+)\s*=\s*([^#]*)' } | ForEach-Object {
  $null = $_ -match '^\s*([A-Z_]+)\s*=\s*([^#]*)'; $cfg[$Matches[1]] = $Matches[2].Trim()
}

if (-not $PipelineOnly) {
  Step "Checking tools"
  Need python "Install Python 3.12 from python.org (tick 'Add to PATH')"
  Need node   "Install Node.js 20+ from nodejs.org"
  if (-not $NoDocker) { Need docker "Install Docker Desktop, or re-run with -NoDocker and your own PostGIS" }

  if (-not $NoDocker) {
    Step "Starting PostGIS (docker compose db)"
    Push-Location $Root
    docker compose up -d db
    Write-Host "Waiting for database to accept connections..."
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
      docker compose exec -T db pg_isready -U $cfg['DB_USER'] | Out-Null
      if ($LASTEXITCODE -eq 0) { $ready = $true; break }
      Start-Sleep -Seconds 2
    }
    Pop-Location
    if (-not $ready) { throw "PostGIS did not become ready - check 'docker compose logs db'" }
  }

  Step "Python virtual environment"
  if (-not (Test-Path $Py)) {
    # Prefer Python 3.12 (pinned numpy/scikit-learn wheels exist for it)
    $made = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
      py -3.12 -m venv (Join-Path $Server ".venv")
      if ($LASTEXITCODE -eq 0) { $made = $true }
    }
    if (-not $made) { python -m venv (Join-Path $Server ".venv") }
  }
  & $Py --version
  & $Py -m pip install --upgrade pip
  & $Py -m pip install -r (Join-Path $Server "requirements-pipeline.txt") pytest

  Step "Database migrations"
  Push-Location $Server; & $Py -m alembic upgrade head; Pop-Location
  if ($LASTEXITCODE -ne 0) { throw "alembic failed - is Postgres running and are DB_* values in .env correct?" }

  Step "300 m analytical grid (spatial_cells)"
  Run-Py "scripts\generate_spatial_cells.py" @("--city", $City) | Out-Null

  Step "Frontend packages"
  # write WITHOUT a BOM (a BOM breaks Vite's .env parsing)
  $clientEnv = "VITE_API_URLS=$($cfg['VITE_API_URL'])`nVITE_MAPBOX_TOKEN=$($cfg['VITE_MAPBOX_TOKEN'])`n"
  [IO.File]::WriteAllText((Join-Path $Client ".env"), $clientEnv, (New-Object System.Text.UTF8Encoding $false))
  Push-Location $Client; npm install; Pop-Location
}

if ($PipelineOnly -and -not (Test-Path $Py)) {
  Step "No Python environment here yet - creating it (fresh copy of the project)"
  Need python "Install Python 3.12 from python.org (tick 'Add to PATH')"
  $made = $false
  if (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv (Join-Path $Server ".venv"); if ($LASTEXITCODE -eq 0) { $made = $true } }
  if (-not $made) { python -m venv (Join-Path $Server ".venv") }
  & $Py -m pip install --upgrade pip
  & $Py -m pip install -r (Join-Path $Server "requirements-pipeline.txt") pytest
}
if ($PipelineOnly -and -not (Test-Path (Join-Path $Client "node_modules"))) {
  Step "Frontend packages (fresh copy)"
  Need node "Install Node.js 20+ from nodejs.org"
  Push-Location $Client; npm install; Pop-Location
}

if ($Upgrade) {
  if (-not $NoDocker) {
    Step "Database image with pgvector (same Postgres 16 - your data volume is kept)"
    Push-Location $Root
    docker compose up -d --build db
    if ($LASTEXITCODE -ne 0) {
      Write-Host "pgvector image could not be built - starting the existing database instead; RAG will use in-memory vectors." -ForegroundColor Yellow
      docker compose up -d db
    }
    Pop-Location
    Start-Sleep -Seconds 8
  }
  Step "Python packages"
  & $Py -m pip install -r (Join-Path $Server "requirements-pipeline.txt")
  Step "Database upgrade (seasonal history tables)"
  Push-Location $Server; & $Py -m alembic upgrade head; Pop-Location
  if ($LASTEXITCODE -ne 0) { throw "alembic failed - is Docker/Postgres running?" }
}

$CityData = if ($City -eq "mumbai") { Join-Path $Server "data" } else { Join-Path $Server "data\cities\$City" }
$HasLayers = Test-Path (Join-Path $CityData "surfaces\manifest.json")

if (-not $HasLayers) {
  Step "Building $City from scratch: boundaries, cells, NDVI, Water Health, LST, AQI, composite, ML (Earth Engine + OpenAQ)"
  $skip = if ($History) { @() } else { @("--skip", "history") }
  Run-Py "scripts\setup_city.py" (@("--city", $City) + $skip) | Out-Null
} else {
  Step "Heatmaps (NDVI / Water Health / LST) - $City"
  Run-Py "scripts\render_heatmaps.py" @("--city", $City, "--only", "ndvi", "--only", "water_health", "--only", "lst") | Out-Null

  Step "Supporting index NDMI (Sentinel-2, 20 m; NDBI = -NDMI derived)"
  $c = Run-Py "scripts\generate_index_surfaces.py" @("--city", $City) -AllowFail
  if ($c -ne 0) { Write-Host "NDMI: Earth Engine step failed - everything else still works without it." -ForegroundColor Yellow }

  Step "CPCB AQI from OpenAQ stations"
  if ($cfg['OPENAQ_AQI_KEY']) {
    $c = Run-Py "scripts\generate_aqi_station_surface.py" @("--city", $City) -AllowFail
    if ($c -ne 0) { Write-Host "AQI: not enough fresh stations right now - the map will say AQI is unavailable." -ForegroundColor Yellow }
  } else { Write-Host "OPENAQ_AQI_KEY not set - skipping AQI (map will show 'unavailable')." -ForegroundColor Yellow }

  Step "Composite surface"
  Run-Py "scripts\generate_composite_surface.py" @("--city", $City) | Out-Null

  Step "Ground-truth reference (ESA WorldCover 2021, once)"
  if (-not (Test-Path (Join-Path $CityData "validation\worldcover_cells_v200.csv"))) {
    $c = Run-Py "scripts\build_validation_reference.py" @("--city", $City) -AllowFail
    if ($c -ne 0) { Write-Host "WorldCover: Earth Engine step failed - validation card will say 'not run'." -ForegroundColor Yellow }
  } else { Write-Host "WorldCover reference already present" }

  Step "ML: cell features + Isolation Forest + XGBoost + Water Health"
  Run-Py "scripts\run_ml_pipeline.py" @("--city", $City) | Out-Null

  if ($History) {
    Step "Seasonal history 2023-now (Earth Engine + OpenAQ; resumable)"
    $c = Run-Py "scripts\build_history.py" @("--city", $City) -AllowFail
    if ($c -ne 0) { Write-Host "History: a step failed - re-run with -History to resume (finished seasons are kept)." -ForegroundColor Yellow }
  }
  Run-Py "scripts\prune_surfaces.py" @("--city", $City) -AllowFail | Out-Null
}

if ($Upgrade -or -not (Test-Path (Join-Path $Server "data\rag\corpus\passages.jsonl"))) {
  Step "RAG corpus: download documents -> passages -> embeddings -> pgvector"
  $c = Run-Py "scripts\ingest_corpus.py" -AllowFail
  if ($c -ne 0) { Write-Host "RAG corpus: ingestion incomplete - the app still works with the curated notes." -ForegroundColor Yellow }
}

Step "RAG retrieval check (BM25 vs embeddings vs hybrid)"
Run-Py "scripts\eval_rag.py" -AllowFail | Out-Null

Step "Tests"
Push-Location $Server; & $Py -m pytest tests -q; Pop-Location

Write-Host "`nDone. Start it with:  .\run.ps1   (or VS Code: Terminal > Run Task > 'GeoSense: start all')" -ForegroundColor Green
