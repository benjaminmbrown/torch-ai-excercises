# NEXUS Platform — Exercise Deliverables

Runnable code deliverables from the Torch.AI NEXUS platform role exercises.

## Contents

### `sitrep-parser/` — Full Stack Engineer
FastAPI service that parses military SITREP (Situation Report) text into structured JSON, with a minimal browser UI for live testing.

**Run locally:**
```bash
cd sitrep-parser
pip install -r requirements.txt
uvicorn main:app --reload
# open http://localhost:8000
```

**Endpoints:**
- `POST /parse` — parse a single SITREP text → structured JSON
- `POST /parse/batch` — parse up to 100 reports in one call
- `GET /schema` — return the field schema
- `GET /` — browser UI

**Docker:**
```bash
docker build -t sitrep-parser .
docker run -p 8000:8000 sitrep-parser
```

---

### `countries-pipeline/` — Data Engineer + Testing/QA Engineer
ETL pipeline that fetches country data from the REST Countries API, normalises it, and loads it into SQLite. Includes a full pytest test suite with HTML report output.

**Run pipeline:**
```bash
cd countries-pipeline
pip install -r requirements.txt
python pipeline.py
```

**Run tests:**
```bash
pytest test_api.py -v --html=report.html --self-contained-html
open report.html   # view results
```

**Test coverage:** 35 tests across functional, contract, latency (P95 assertions), and resilience scenarios.

---

### `.github/workflows/ci.yml` — DevOps Engineer
GitHub Actions CI pipeline covering:
- Python lint (ruff) + type check (mypy)
- Unit + integration tests with coverage
- Docker build + push to GHCR
- Kubernetes manifest validation (kubeval)
- Staging deploy with smoke test gate

---

### `temporal-forecast/` — Software Engineer (Python)
Production ML service for NEXUS intelligence time-series forecasting. FastAPI app with SQLite persistence, background model training, REST inference endpoints, structured JSON logging, and a full pytest suite.

**Run locally:**
```bash
cd temporal-forecast
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# API docs at http://localhost:8000/docs
```

**Endpoints:**
- `GET /health` — liveness check
- `POST /ingest` — submit a time series (triggers background model fit, returns 202)
- `POST /forecast` — generate N-step forecast with 95% confidence intervals
- `GET /series/{id}/history` — retrieve past forecasts for a series

**Run tests:**
```bash
cd temporal-forecast
pytest tests/ -v
```

**Architecture highlights:**
- Ridge regression over neural nets — lower latency, interpretable, no GPU required
- Sliding-window feature extraction: 6 lag features + 8 statistical features per window
- 95% confidence intervals from in-sample residual std × 1.96
- Background task model fitting so `/ingest` returns immediately
- SQLAlchemy ORM with SQLite — swap to PostgreSQL via `DATABASE_URL` env var
- Structured JSON logging compatible with Loki / CloudWatch

---

### `nexus-intel-platform/` — Enterprise Software Developer
Production-quality Python/FastAPI services for multi-INT fusion: ingestion pipeline, hybrid semantic search (pgvector + BM25 + RRF), RAG Q&A engine, JWT/Keycloak auth middleware, audit logging, and four TimescaleDB/PostgreSQL analytics queries.

**File structure:**
```
nexus/ingestion/pipeline.py    # IngestionPipeline: validate → dedup (Bloom) → embed → NER → persist
nexus/ingestion/consumer.py    # AIOKafkaConsumer batch consumer with SSL + manual commit
nexus/adapters/sigint.py       # SIGINT adapter: DTG parsing, FLASH stripping, geo extraction
nexus/search/hybrid.py         # HybridSearchService: pgvector HNSW + tsvector RRF (K=60)
nexus/api/routes/search.py     # FastAPI /api/v1/search/semantic endpoint
nexus/rag/engine.py            # RAGEngine: token-budget context window + citation tracking
nexus/auth/middleware.py       # Keycloak JWT RS256 + ClearanceMiddleware (SET LOCAL RLS)
nexus/auth/audit.py            # @audit_log decorator → immutable audit_log table
queries/threat_density_anomaly.sql  # TimescaleDB Z-score anomaly detection
queries/entity_network.sql          # Co-occurrence Jaccard similarity
queries/analyst_dashboard.sql       # PERCENTILE_CONT + RANK workload metrics
queries/source_reliability.sql      # A-D reliability grading
```

**Dependencies (conceptual — requires TimescaleDB, pgvector, Keycloak, Kafka):**
```bash
pip install fastapi asyncpg sentence-transformers aiokafka pybloom-live python-jose httpx
```

---

## Related Exercise Pages
Full write-ups for each role are at [oakenai.tech/portfolio/torch](https://oakenai.tech/portfolio/torch).
