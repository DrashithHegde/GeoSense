"""AI / ML / RAG endpoints for GeoSense.

GET  /api/analysis/point/explain?lon=&lat=   evidence + signals + RAG (+ validated LLM)
POST /api/assistant/ask                       grounded Q&A, optionally about a point
GET  /api/ml/summary                          model cards (IF, XGBoost CV metrics, WH baseline)
GET  /api/ml/hotspots?model=&limit=           GeoJSON points of flagged cells for the map
                                               (model: isolation_forest | heat_residual | water_health |
                                                if_ndvi | if_lst | if_water_health | if_aqi)
GET  /api/ml/stations                         station-level Isolation Forest (pollutant mix) as GeoJSON
GET  /api/knowledge                           the cited knowledge base (for transparency)
POST /api/ml/run                              re-run the cell ML pipeline (background)

Every endpoint works on the city of the request (?city=, or the city containing ?lon=&lat=).
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.cities import get_city, use_city
from app.database import engine, get_db
from app.services.rag import retriever
from app.services.rag.explainer import answer_question, explain_point, ml_summary
from app.services.rag.guardrails import AI_SUMMARY_LIMIT, ASK_LIMIT, log_event
from app.services.rag.llm import active_provider

router = APIRouter()

MODELS = {
    "isolation_forest": "isolation_forest_cell_v2",
    "heat_residual": "xgboost_lst_residual_v1",
    "water_health": "water_health_robust_z_v1",
    "if_ndvi": "isolation_forest_ndvi_v1",
    "if_lst": "isolation_forest_lst_v1",
    "if_water_health": "isolation_forest_water_health_v1",
    "if_aqi": "isolation_forest_aqi_v1",
}
FOCUS_PATTERN = "^(composite|ndvi|lst|water_health|aqi)$"
# anywhere in India (each city's own study region is checked by the analysis itself)
LON = dict(ge=68.0, le=98.0)
LAT = dict(ge=6.0, le=38.0)


async def _analysis(lon: float, lat: float) -> dict:
    from app.api.routes import get_point_analysis
    return await get_point_analysis(lon, lat, db_cm=get_db())


def _has_any_data(analysis: dict) -> bool:
    px = analysis.get("pixel") or {}
    for k in ("ndvi", "water_health", "aqi", "composite"):
        if (px.get(k) or {}).get("value") is not None:
            return True
    if (px.get("lst") or {}).get("value_c") is not None:
        return True
    cell = analysis.get("cell") or {}
    m = cell.get("metrics") or {}
    return bool(cell.get("features")) or any(m.get(k) is not None for k in ("ndvi", "lst", "aqi", "water_health_score",
                                                                           "composite"))


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/analysis/point/explain")
async def explain(request: Request, lon: float = Query(..., **LON), lat: float = Query(..., **LAT),
                  llm: bool = True, focus: Optional[str] = Query(None, pattern=FOCUS_PATTERN)):
    analysis = await _analysis(lon, lat)
    if not analysis.get("cell") and not analysis.get("municipality"):
        raise HTTPException(status_code=404, detail=f"Location is outside the {get_city().name} study region")
    if not _has_any_data(analysis):
        # nothing measured here yet (e.g. a city whose layers are still being generated): say so,
        # instead of an "all fine" write-up built from missing values
        raise HTTPException(status_code=404, detail=f"No layer data for this place yet: {get_city().name}'s layers "
                                                    "have not been generated.")
    limited = False
    if llm:
        ok, _ = AI_SUMMARY_LIMIT.check(_client(request))
        if not ok:   # over the AI limit: still answer, from the evidence only
            llm, limited = False, True
            log_event("rate_limit", "explain_ai", client=_client(request))
    result = await explain_point(analysis, use_llm=llm, focus=focus)
    if limited:
        result["generation"]["warnings"].append("AI summary paused for a moment (too many requests) — evidence write-up shown.")
    result["point_analysis"] = analysis
    return result


class AskRequest(BaseModel):
    """Pydantic validates every Ask request before any code runs (types, lengths, ranges, allowed values)."""
    question: str = Field(..., min_length=3, max_length=500)
    lon: Optional[float] = Field(None, **LON)
    lat: Optional[float] = Field(None, **LAT)
    city: Optional[str] = Field(None, max_length=20, pattern=r"^[a-z_]+$")
    focus: Optional[str] = Field(None, pattern=FOCUS_PATTERN)
    intent: Optional[str] = Field(None, max_length=40, pattern=r"^[a-z0-9_]+$")


@router.post("/assistant/ask")
async def ask(req: AskRequest, request: Request):
    ok, wait = ASK_LIMIT.check(_client(request))
    if not ok:
        log_event("rate_limit", "ask", req.question, client=_client(request))
        raise HTTPException(status_code=429, detail=f"Too many questions — please wait {int(wait) + 1} s.",
                            headers={"Retry-After": str(int(wait) + 1)})
    from app.core.cities import city_for_point
    cid = (city_for_point(req.lon, req.lat) if req.lon is not None and req.lat is not None else None) \
        or get_city(req.city).id
    with use_city(cid):
        analysis = await _analysis(req.lon, req.lat) if req.lon is not None and req.lat is not None else None
        return await answer_question(req.question, analysis, req.focus, req.intent)


@router.get("/ml/summary")
async def get_ml_summary():
    s = ml_summary()
    if not s:
        raise HTTPException(status_code=404, detail=f"No ML run yet for {get_city().name} — run "
                                                    f"scripts/run_ml_pipeline.py --city {get_city().id}")
    s = {k: v for k, v in s.items() if k != "city_percentiles"}
    s["llm_provider"] = (active_provider() or (None, None))[0]
    from app.services.rag.explainer import _composite_card
    s["composite"] = _composite_card()
    return s


@router.get("/ml/hotspots")
async def hotspots(model: str = Query("isolation_forest",
                                     pattern="^(isolation_forest|heat_residual|water_health|if_ndvi|if_lst|if_water_health|if_aqi)$"),
                   limit: int = Query(1500, ge=1, le=5000)):
    sql = text("""
        SELECT DISTINCT ON (ar.cell_id) ar.cell_id, sc.cell_code, sc.municipality_name,
               ST_X(sc.centroid) AS lon, ST_Y(sc.centroid) AS lat,
               ar.anomaly_score, ar.anomaly_type, ar.root_cause, ar.observed_at
        FROM anomaly_results ar JOIN spatial_cells sc ON sc.id = ar.cell_id
        WHERE sc.city = :city AND ar.model_name = :m AND ar.is_anomaly
          AND (:m <> 'xgboost_lst_residual_v1' OR ar.anomaly_type = 'unexplained_heat')
        ORDER BY ar.cell_id, ar.observed_at DESC
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"m": MODELS[model], "city": get_city().id}).mappings().all()
    rows = sorted(rows, key=lambda r: abs(r["anomaly_score"]), reverse=True)[:limit]
    scores = [abs(r["anomaly_score"]) for r in rows] or [1.0]
    lo, hi = min(scores), max(scores)
    return {
        "type": "FeatureCollection",
        "model": MODELS[model],
        "city": get_city().id,
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "cell_id": r["cell_id"], "cell_code": r["cell_code"], "municipality": r["municipality_name"],
                "score": r["anomaly_score"], "type": r["anomaly_type"], "summary": r["root_cause"],
                "intensity": 0.35 + 0.65 * ((abs(r["anomaly_score"]) - lo) / (hi - lo) if hi > lo else 1.0),
                "observed_at": r["observed_at"].isoformat(),
            },
        } for r in rows],
    }


@router.get("/ml/stations")
async def station_outliers():
    st = (ml_summary().get("station_isolation_forest") or {})
    return {
        "type": "FeatureCollection", "status": st.get("status"), "reason": st.get("reason"),
        "pollutants": st.get("pollutants"),
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [x["lon"], x["lat"]]},
                      "properties": {k: x.get(k) for k in ("station_name", "aqi", "is_anomaly", "score_percentile",
                                                           "dominant_deviations")}}
                     for x in st.get("stations") or [] if x.get("lon") is not None],
    }


@router.get("/rag/status")
async def rag_status():
    """Retrieval mode (hybrid / BM25) and the latest retrieval evaluation."""
    from pathlib import Path
    out = {"mode": retriever.retrieval_mode(), **retriever.corpus_stats()}
    p = Path(__file__).resolve().parents[2] / "data" / "rag" / "retrieval_eval.json"
    if p.exists():
        out["evaluation"] = json.loads(p.read_text(encoding="utf-8"))
    return out


@router.get("/knowledge")
async def knowledge(q: Optional[str] = None, k: int = 8):
    if q:
        return retriever.retrieve(q, k=k, min_score=0.0)
    return list(retriever.load_kb())


@router.post("/ml/run")
async def run_ml(background: BackgroundTasks, request: Request):
    from app.api.admin_guard import PIPELINE_LOCK, require_admin, run_exclusive
    require_admin(request)
    if PIPELINE_LOCK.locked():
        raise HTTPException(status_code=409, detail="The ML pipeline is already running.")

    city = get_city().id

    def _job():
        from app.services.ml.pipeline import run_cell_ml_pipeline
        with use_city(city), get_db() as db:
            run_cell_ml_pipeline(db)
    background.add_task(run_exclusive, _job)
    return {"status": "started", "city": city}
