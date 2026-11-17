import logging
import mimetypes
from urllib.parse import parse_qs

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# heatmaps may be WebP; some Windows installs have no .webp entry in their MIME registry
mimetypes.add_type("image/webp", ".webp")

from app.api.intelligence import router as intelligence_router
from app.api.routes import router as api_router
from app.core.cities import CITIES, UnknownCity, city_for_point, get_city, reset_city, set_city
from app.core.config import get_settings
from app.database import test_database_connection

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="GeoSense API", version="3.0.0", docs_url="/docs", redoc_url="/redoc")


class CityContextMiddleware:
    """Every request works on one city: the city that contains ?lon=&lat= (a map click),
    else ?city=<id>, else the default city. Unknown ?city= -> 404."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        q = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        cid = None
        try:
            if "lon" in q and "lat" in q:
                cid = city_for_point(float(q["lon"][0]), float(q["lat"][0]))
        except (ValueError, TypeError):
            cid = None
        try:
            cid = cid or get_city(q.get("city", [None])[0]).id
        except UnknownCity as exc:
            resp = JSONResponse({"detail": f"Unknown city {exc.args[0]!r}. Cities: {', '.join(CITIES)}"},
                                status_code=404)
            return await resp(scope, receive, send)
        token = set_city(cid)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_city(token)


class ApiGZip:
    """Compress API JSON (large evidence/geometry responses); map images are already compressed."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=2048)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/"):
            return await self.gzip(scope, receive, send)
        return await self.app(scope, receive, send)


app.add_middleware(CityContextMiddleware)
app.add_middleware(ApiGZip)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parsed_cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static derived artifacts only (map images per city). This is intentionally not a tile server.
for _cid, _city in CITIES.items():
    _dir = _city.data_dir / "surfaces"
    _dir.mkdir(parents=True, exist_ok=True)
    app.mount(f"/surface-assets/{_cid}", StaticFiles(directory=_dir), name=f"surface-assets-{_cid}")


@app.middleware("http")
async def cache_surface_images(request, call_next):
    """Map images never change under the same name (new runs get new timestamped files and a
    ?v=<sha256> stamp), so the browser may keep them for a day instead of re-downloading them."""
    response = await call_next(request)
    if request.url.path.startswith("/surface-assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


app.include_router(intelligence_router, prefix="/api", tags=["Intelligence"])
app.include_router(api_router, prefix="/api", tags=["GeoSense"])


@app.get("/", include_in_schema=False)
def root():
    return {"service": "GeoSense API", "docs": "/docs", "health": "/api/health", "cities": "/api/cities"}


@app.on_event("startup")
def verify_database_connection() -> None:
    """Log (not crash) when the database is unreachable: /api/health reports it, and a hosted
    instance can come up while its database is still starting."""
    try:
        test_database_connection()
    except Exception as exc:
        logger.error("Database not reachable at start-up: %s", exc)


@app.on_event("startup")
def start_aqi_auto_refresh() -> None:
    """Rebuild each city's AQI layer when it is more than 6 h old, at start-up and every 3 h after."""
    try:
        from app.services.surfaces.aqi_refresh import start_background
        start_background()
    except Exception as exc:          # never block the server from starting
        logger.warning("AQI auto-refresh not started: %s", exc)


@app.on_event("startup")
def warm_up() -> None:
    """Do one full click per city in the background at start-up (embedding model, vector store,
    rasters, ML outputs, database pool), so the first real click is as fast as the rest.
    WARM_UP=0 turns it off (small hosted instances)."""
    import asyncio
    import os
    import threading

    if os.getenv("WARM_UP", "1").strip().lower() in ("0", "false", "no", "off"):
        return

    def _warm():
        try:
            from app.services.rag import retriever
            retriever.retrieve("warm up", k=1)
        except Exception:
            pass
        from app.api.intelligence import _analysis
        from app.core.cities import available_cities, use_city
        from app.services.rag.explainer import explain_point

        async def _one(lon, lat):
            a = await _analysis(lon, lat)
            if a.get("cell"):
                await explain_point(a, use_llm=False, focus="composite")

        for cid in available_cities():
            try:
                with use_city(cid) as city:
                    asyncio.run(_one(*city.center))
            except Exception:
                pass
    threading.Thread(target=_warm, daemon=True).start()
