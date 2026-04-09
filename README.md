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

## Related Exercise Pages
Full write-ups for each role are at [oakenai.tech/portfolio/torch](https://oakenai.tech/portfolio/torch).
