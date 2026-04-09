import pytest, numpy as np
from httpx import AsyncClient, ASGITransport
from main import app
from pipeline import WindowedDataset, ForecastPipeline

# ─── Unit: WindowedDataset ─────────────────────────────────────────────────
def test_windowed_shape():
    ds = WindowedDataset(window=5)
    series = np.arange(20, dtype=float)
    X, y = ds.transform(series)
    assert X.shape[0] == 15          # 20 - 5 = 15 samples
    assert X.shape[1] == 14          # 6 lags + 8 stat feats

def test_windowed_too_short():
    ds = WindowedDataset(window=10)
    with pytest.raises(ValueError):
        ds.transform(np.arange(5, dtype=float))

# ─── Unit: ForecastPipeline ───────────────────────────────────────────────
def test_pipeline_fit_predict():
    rng = np.random.default_rng(42)
    series = np.sin(np.linspace(0, 6*np.pi, 100)) + rng.normal(0, 0.05, 100)
    pipe = ForecastPipeline(window=12)
    pipe.fit(series)
    preds, lower, upper = pipe.predict(series, horizon=6)
    assert len(preds) == 6
    assert all(lower[i] <= preds[i] <= upper[i] for i in range(6))

def test_pipeline_auto_fit():
    """predict() without prior fit() should still work."""
    series = np.linspace(0, 10, 50)
    pipe = ForecastPipeline()
    preds, _, _ = pipe.predict(series, horizon=3)
    assert len(preds) == 3

# ─── Integration: API ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_ingest_and_forecast():
    values = (np.sin(np.linspace(0, 4*np.pi, 60)) + 2.0).tolist()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/ingest", json={"series_id": "test-01", "values": values})
        assert r.status_code == 202
        r2 = await c.post("/forecast", json={"series_id": "test-01", "horizon": 12})
        assert r2.status_code == 200
        data = r2.json()
        assert len(data["predictions"]) == 12
        assert data["latency_ms"] < 500

@pytest.mark.asyncio
async def test_forecast_unknown_series():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/forecast", json={"series_id": "nonexistent", "horizon": 6})
        assert r.status_code == 404

@pytest.mark.asyncio
async def test_ingest_too_short():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/ingest", json={"series_id": "short", "values": [1.0, 2.0]})
        assert r.status_code == 422
