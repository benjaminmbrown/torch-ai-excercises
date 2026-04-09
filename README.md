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

### `rag-pipeline/` — AI/ML Engineer
Production RAG pipeline: document ingestion (PDF/DOCX/TXT) with BGE-large-en-v1.5 embeddings, hybrid retrieval (BM25 + pgvector ANN + RRF), and Claude-powered generation with citation tracking. Includes a keyword-recall eval harness.

**Setup:**
```bash
cd rag-pipeline
pip install -r requirements.txt
cp .env.example .env   # add ANTHROPIC_API_KEY + DATABASE_URL
docker compose up -d   # starts pgvector/pgvector:pg16

# Ingest a document and start Q&A
python generation.py path/to/document.pdf
```

**File structure:**
```
ingestion.py    # DocumentIngester: PDF/DOCX/TXT chunking, SHA-256 dedup, BGE embed, HNSW index
retrieval.py    # HybridRetriever: BM25Okapi + pgvector ANN, RRF fusion (RRF_K=60)
generation.py   # RAGPipeline: Claude generation, token-budget context, citation tracking + eval harness
```

**Architecture highlights:**
- BGE-large-en-v1.5 (1024-dim) embeddings via sentence-transformers
- Idempotent ingestion via SHA-256 content hash deduplication
- Hybrid retrieval: BM25 (rank-bm25) + pgvector HNSW cosine ANN, fused with Reciprocal Rank Fusion
- Token-budget context window (12k chars) with citation tracking
- Eval harness: 5-question keyword-recall suite, type `eval` in interactive loop

---

### `intelligence-connector/` — Software Engineer (Java)
Spring Boot 3 / Java 21 contract-first REST service. OpenAPI 3.1 spec drives server stub generation, Feign client with fallback for upstream NEXUS platform, and a full MockMvc + WireMock integration test suite.

**Run locally:**
```bash
cd intelligence-connector
mvn spring-boot:run
# API docs at http://localhost:8080/swagger-ui.html
```

**Run tests:**
```bash
mvn test
```

**File structure:**
```
src/main/resources/openapi.yaml                          # Contract-first API definition (OpenAPI 3.1)
src/main/java/ai/torch/nexus/connector/
  IntelEventController.java                              # REST controller: POST/GET /api/v1/intel/events
  IntelEventService.java                                 # Business logic: enrichment, threat tier, entity extraction
  NexusFeignClient.java                                  # Feign client with no-op fallback for upstream NEXUS
src/test/java/ai/torch/nexus/connector/
  IntelEventControllerTest.java                          # MockMvc + WireMock: happy path, 404, 400, circuit-breaker fallback
```

**Architecture highlights:**
- Contract-first: `openapi-generator-maven-plugin` generates server stubs from `openapi.yaml` at build time
- Java 21 with Spring Boot 3.2 (Jakarta EE, virtual threads compatible)
- Feign client circuit-breaker: upstream 503 activates fallback stub, ingest still returns 202
- WireMock stubs simulate upstream NEXUS platform in integration tests
- In-memory store (ConcurrentHashMap) — swap for JPA repository in production

---

### `nexus-db/` — Database Administrator
PostgreSQL 16 + TimescaleDB + pgvector schema design for the NEXUS intelligence platform. Includes 7 tables, 23 indexes, 6 analytical queries, RLS policies with audit trigger, and a TimescaleDB compression/retention strategy.

**File structure:**
```
schema.sql                            # 7 tables: sources, analysts, intel_events (hypertable), entities,
                                      #           event_entities, tags, event_tags, audit_log
indexes.sql                           # 23 indexes (covering, partial, HNSW) + continuous aggregate
rls_policies.sql                      # Clearance-gated RLS + PL/pgSQL audit trigger
vacuum_settings.sql                   # Autovacuum tuning, TimescaleDB compression/retention policies
queries/
  query_01_source_dashboard.sql       # Source performance: volume rank + criticality rank
  query_02_analyst_workload.sql       # PERCENTILE_CONT P50/P95 resolution time + clearance violations
  query_03_entity_correlation.sql     # Co-occurrence correlation confidence score
  query_04_threat_density_timeseries.sql  # Rolling 24h density + Z-score anomaly detection
  query_05_geo_clustering.sql         # 1° lat/lon grid clustering with centroid
  query_06_audit_trail.sql            # EXPORT/DELETE compliance trail with over-access flag
```

**Architecture highlights:**
- TimescaleDB hypertable (`intel_events`) partitioned monthly — automatic chunk pruning via retention policy
- pgvector HNSW index (m=16, ef_construction=64) for sub-millisecond semantic ANN search
- Row-Level Security enforces clearance levels; `app.analyst_id` session variable set by API middleware
- Continuous aggregate `hourly_threat_stats` refreshes every hour via TimescaleDB policy
- TimescaleDB columnar compression (segment by source/tier) reduces storage 10-20×

---

## Related Exercise Pages
Full write-ups for each role are at [oakenai.tech/portfolio/torch](https://oakenai.tech/portfolio/torch).
