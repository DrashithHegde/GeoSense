from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes import router as api_router
from app.database import test_database_connection
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="GeoSense API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parsed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static derived artifacts only.  This is intentionally not a tile server.
SURFACE_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "surfaces"
SURFACE_DIRECTORY.mkdir(parents=True, exist_ok=True)
app.mount("/surface-assets", StaticFiles(directory=SURFACE_DIRECTORY), name="surface-assets")

app.include_router(api_router, prefix="/api", tags=["GeoSense"])


@app.on_event("startup")
def verify_database_connection() -> None:
    test_database_connection()
