from __future__ import annotations
import logging, time, uuid
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, JSON
from sqlalchemy.orm import declarative_base, Session
import numpy as np
from datetime import datetime, timezone
from pipeline import ForecastPipeline, WindowedDataset

# ─── Structured logging ───────────────────────────────────────────────────────
logging.basicConfig(
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    level=logging.INFO
)
log = logging.getLogger("nexus.forecast")

# ─── Database ─────────────────────────────────────────────────────────────────
engine = create_engine("sqlite:///./forecast.db", connect_args={"check_same_thread": False})
Base = declarative_base()

class ForecastRecord(Base):
    __tablename__ = "forecasts"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    series_id  = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    horizon    = Column(Integer, nullable=False)
    predictions= Column(JSON, nullable=False)
    latency_ms = Column(Float, nullable=False)
    model_ver  = Column(String, default="v1.0")

Base.metadata.create_all(engine)

# ─── Pydantic schemas ─────────────────────────────────────────────────────────
class IngestRequest(BaseModel):
    series_id: str = Field(..., description="Unique identifier for the time series")
    values: List[float] = Field(..., min_length=10, description="Observed values (ordered)")
    timestamps: Optional[List[str]] = None

class ForecastRequest(BaseModel):
    series_id: str
    horizon: int = Field(12, ge=1, le=96, description="Steps ahead to forecast")

class ForecastResponse(BaseModel):
    forecast_id: str
    series_id: str
    predictions: List[float]
    confidence_lower: List[float]
    confidence_upper: List[float]
    latency_ms: float
    model_ver: str

# ─── In-memory series store ───────────────────────────────────────────────────
_series_store: dict[str, np.ndarray] = {}
_pipeline = ForecastPipeline()

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting NEXUS Forecast Service")
    yield
    log.info("Shutting down")

app = FastAPI(
    title="NEXUS Temporal Forecast Service",
    version="1.0.0",
    lifespan=lifespan
)

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "series_count": len(_series_store)}

@app.post("/ingest", status_code=202)
async def ingest_series(req: IngestRequest, bg: BackgroundTasks):
    if len(req.values) < 10:
        raise HTTPException(400, "At least 10 observations required")
    arr = np.array(req.values, dtype=np.float64)
    _series_store[req.series_id] = arr
    log.info("Ingested series=%s len=%d", req.series_id, len(arr))
    bg.add_task(_fit_pipeline, req.series_id, arr)
    return {"series_id": req.series_id, "accepted": True, "length": len(arr)}

@app.post("/forecast", response_model=ForecastResponse)
async def forecast(req: ForecastRequest):
    if req.series_id not in _series_store:
        raise HTTPException(404, f"series_id '{req.series_id}' not found")
    t0 = time.perf_counter()
    arr = _series_store[req.series_id]
    preds, lower, upper = _pipeline.predict(arr, req.horizon)
    latency = (time.perf_counter() - t0) * 1000
    fid = str(uuid.uuid4())
    with Session(engine) as db:
        db.add(ForecastRecord(
            id=fid, series_id=req.series_id, horizon=req.horizon,
            predictions=preds, latency_ms=latency
        ))
        db.commit()
    log.info("Forecast series=%s horizon=%d latency_ms=%.1f", req.series_id, req.horizon, latency)
    return ForecastResponse(
        forecast_id=fid, series_id=req.series_id,
        predictions=preds, confidence_lower=lower, confidence_upper=upper,
        latency_ms=round(latency, 1), model_ver="v1.0"
    )

@app.get("/series/{series_id}/history")
async def forecast_history(series_id: str, limit: int = 20):
    with Session(engine) as db:
        rows = (db.query(ForecastRecord)
                .filter(ForecastRecord.series_id == series_id)
                .order_by(ForecastRecord.created_at.desc())
                .limit(limit).all())
    if not rows:
        raise HTTPException(404, "No forecasts found for this series")
    return [{"id": r.id, "created_at": str(r.created_at),
              "horizon": r.horizon, "latency_ms": r.latency_ms} for r in rows]

def _fit_pipeline(series_id: str, data: np.ndarray):
    """Background task: fit/update model for this series."""
    _pipeline.fit(data)
    log.info("Pipeline fitted for series=%s", series_id)
