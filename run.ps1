# Starts PostGIS (docker), the FastAPI backend and the Vite frontend in separate windows.
#   .\run.ps1          development mode (live reload while you edit code)
#   .\run.ps1 -Demo    demo mode: builds the frontend once and serves the optimised build -
#                      opens much faster; use this for the evaluation
param([switch]$NoDocker, [switch]$Demo)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $NoDocker) { Push-Location $Root; docker compose up -d db; Pop-Location }
if ($Demo) {
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\server'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
  Write-Host "Building the frontend (about 20 s)..."
  Push-Location (Join-Path $Root "client"); npm run build; Pop-Location
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\client'; npx vite preview --port 5173 --strictPort"
} else {
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\server'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8000"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\client'; npm run dev"
}
# Wait for the backend to answer before opening the browser (first start can take 10-30 s)
Write-Host "Waiting for the backend to start..." -NoNewline
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
  try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:8000/api/health" | Out-Null; $ready = $true; break }
  catch { Start-Sleep -Seconds 1; Write-Host "." -NoNewline }
}
Write-Host ""
if (-not $ready) { Write-Host "Backend did not answer yet - check the backend window for errors." -ForegroundColor Yellow }
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"
Write-Host "Backend: http://localhost:8000/docs   Frontend: http://localhost:5173"
