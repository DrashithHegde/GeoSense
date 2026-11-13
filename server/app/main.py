from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import mimetypes

# heatmaps are WebP; some Windows installs have no .webp entry in their MIME registry
mimetypes.add_type("image/webp", ".webp")

from app.api.routes import router as api_router
from app.api.intelligence import router as intelligence_router
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


@app.middleware("http")
async def cache_surface_images(request, call_next):
    """Heatmap PNGs never change under the same name (new runs get new timestamped files and a
    ?v=<sha256> stamp), so the browser may keep them for a day instead of re-downloading ~15 MB."""
    response = await call_next(request)
    if request.url.path.startswith("/surface-assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response

app.include_router(intelligence_router, prefix="/api", tags=["Intelligence"])
app.include_router(api_router, prefix="/api", tags=["GeoSense"])


@app.on_event("startup")
def verify_database_connection() -> None:
    test_database_connection()


@app.on_event("startup")
def start_aqi_auto_refresh() -> None:
    """Rebuild the AQI layer when it is more than 6 h old, at start-up and every 3 h after."""
    try:
        from app.services.surfaces.aqi_refresh import start_background
        start_background()
    except Exception as exc:          # never block the server from starting
        import logging
        logging.getLogger(__name__).warning("AQI auto-refresh not started: %s", exc)


@app.on_event("startup")
def warm_up() -> None:
    """Do one full click in the background at start-up (embedding model, vector store, rasters,
    ML outputs, database pool), so the user's first real click is as fast as the rest."""
    import asyncio
    import threading

    def _warm():
        try:
            from app.services.rag import retriever
            retriever.retrieve("warm up", k=1)
        except Exception:
            pass
        try:
            from app.api.intelligence import _analysis
            from app.services.rag.explainer import explain_point

            async def _one():
                a = await _analysis(72.8777, 19.0760)   # central Mumbai
                if a.get("cell"):
                    await explain_point(a, use_llm=False, focus="composite")
            asyncio.run(_one())
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()