<#
  GeoSense one-shot setup for Windows (PowerShell).
    powershell -ExecutionPolicy Bypass -File .\setup.ps1              # everything
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -PipelineOnly  # just re-run data + ML
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoDocker      # use your own Postgres
#>
param([switch]$PipelineOnly, [switch]$NoDocker)
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
  & $Py -m pip install -r (Join-Path $Server "requirements.txt") pytest

  Step "Database migrations"
  Push-Location $Server; & $Py -m alembic upgrade head; Pop-Location
  if ($LASTEXITCODE -ne 0) { throw "alembic failed - is Postgres running and are DB_* values in .env correct?" }

  Step "300 m analytical grid (spatial_cells)"
  $count = & $Py -c "import sys; sys.path.insert(0, r'$Server'); from app.database import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text('select count(*) from spatial_cells')).scalar())"
  if ([int]$count -eq 0) { Run-Py "scripts\generate_spatial_cells.py" } else { Write-Host "spatial_cells already has $count cells" }

  Step "Frontend packages"
  # write WITHOUT a BOM (a BOM breaks Vite's .env parsing)
  $clientEnv = "VITE_API_URL=$($cfg['VITE_API_URL'])`nVITE_MAPBOX_TOKEN=$($cfg['VITE_MAPBOX_TOKEN'])`n"
  [IO.File]::WriteAllText((Join-Path $Client ".env"), $clientEnv, (New-Object System.Text.UTF8Encoding $false))
  Push-Location $Client; npm install; Pop-Location
}

Step "Heatmaps (NDVI / Water Health / LST)"
Run-Py "scripts\render_heatmaps.py" | Out-Null  # output already shown

Step "CPCB AQI from OpenAQ stations"
if ($cfg['OPENAQ_AQI_KEY']) {
  $c = Run-Py "scripts\generate_aqi_station_surface.py" @("--cells") -AllowFail
  if ($c -ne 0) { Write-Host "AQI: not enough fresh stations right now - the map will say AQI is unavailable." -ForegroundColor Yellow }
} else { Write-Host "OPENAQ_AQI_KEY not set - skipping AQI (map will show 'unavailable')." -ForegroundColor Yellow }

Step "Composite surface"
Run-Py "scripts\generate_composite_surface.py" | Out-Null

Step "ML: cell features + Isolation Forest + XGBoost + Water Health"
Run-Py "scripts\run_ml_pipeline.py" | Out-Null

Step "RAG retrieval check (BM25 vs embeddings vs hybrid)"
Run-Py "scripts\eval_rag.py" -AllowFail | Out-Null

Step "Tests"
Push-Location $Server; & $Py -m pytest tests\test_intelligence_layer.py -q; Pop-Location

Write-Host "`nDone. Start it with:  .\run.ps1   (or VS Code: Terminal > Run Task > 'GeoSense: start all')" -ForegroundColor Green
