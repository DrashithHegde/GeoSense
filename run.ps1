# Starts PostGIS (docker), the FastAPI backend and the Vite frontend in separate windows.
param([switch]$NoDocker)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $NoDocker) { Push-Location $Root; docker compose up -d db; Pop-Location }
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\server'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Root\client'; npm run dev"
Start-Sleep -Seconds 6
Start-Process "http://localhost:5173"
Write-Host "Backend: http://localhost:8000/docs   Frontend: http://localhost:5173"
