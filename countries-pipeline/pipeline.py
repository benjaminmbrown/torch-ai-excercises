"""
Torch.AI — Data Engineer Exercise
REST Countries API Ingestion Pipeline

Ingests country data from restcountries.com, normalizes it,
and stores it in a SQLite database with a clean relational schema.

Usage:
    python pipeline.py                    # Full run
    python pipeline.py --dry-run          # Fetch and validate, no DB write
    python pipeline.py --country US       # Single country by alpha2 code
"""

import argparse
import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ─── CONFIG ──────────────────────────────────────────────────────────────────

API_BASE = "https://restcountries.com/v3.1"
# API enforces a max of 10 fields per request
FIELDS = "name,cca2,cca3,region,subregion,capital,population,languages,currencies,borders"
DB_PATH = Path(__file__).parent / "countries.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── DATABASE ────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS countries (
    cca2            TEXT PRIMARY KEY,
    cca3            TEXT UNIQUE NOT NULL,
    common_name     TEXT NOT NULL,
    official_name   TEXT,
    region          TEXT,
    subregion       TEXT,
    capital         TEXT,
    population      INTEGER,
    area_km2        REAL,
    latitude        REAL,
    longitude       REAL,
    flag_png        TEXT,
    flag_svg        TEXT,
    ingested_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS languages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cca2        TEXT NOT NULL REFERENCES countries(cca2),
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    UNIQUE(cca2, code)
);

CREATE TABLE IF NOT EXISTS currencies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cca2        TEXT NOT NULL REFERENCES countries(cca2),
    code        TEXT NOT NULL,
    name        TEXT,
    symbol      TEXT,
    UNIQUE(cca2, code)
);

CREATE TABLE IF NOT EXISTS borders (
    cca2        TEXT NOT NULL REFERENCES countries(cca2),
    border_cca3 TEXT NOT NULL,
    PRIMARY KEY (cca2, border_cca3)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    records_fetched  INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated  INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running'
);
"""


@contextmanager
def get_db(path: Path = None):
    # Read DB_PATH at call time so tests can override the module variable
    import pipeline as _self
    resolved = path or _self.DB_PATH
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: Path = None):
    import pipeline as _self
    resolved = path or _self.DB_PATH
    with sqlite3.connect(resolved) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    log.info("Database initialized: %s", resolved)


# ─── FETCH ───────────────────────────────────────────────────────────────────

def fetch_all_countries() -> list[dict]:
    """Fetch all countries with selected fields."""
    url = f"{API_BASE}/all?fields={FIELDS}"
    log.info("Fetching: %s", url)
    t0 = time.time()
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    elapsed = time.time() - t0
    log.info("Fetched %d countries in %.2fs", len(data), elapsed)
    return data


def fetch_country(alpha: str) -> list[dict]:
    """Fetch a single country by alpha2 or alpha3 code."""
    url = f"{API_BASE}/alpha/{alpha}?fields={FIELDS}"
    log.info("Fetching single country: %s", alpha.upper())
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # API returns list or dict depending on query type
    return data if isinstance(data, list) else [data]


# ─── TRANSFORM ───────────────────────────────────────────────────────────────

def transform(raw: dict) -> Optional[dict]:
    """
    Normalize a raw API country record into a flat dict
    plus nested lists for languages, currencies, and borders.
    Returns None if the record is missing required fields.
    """
    cca2 = raw.get("cca2", "").strip()
    cca3 = raw.get("cca3", "").strip()
    if not cca2 or not cca3:
        log.warning("Skipping record with missing alpha codes: %s", raw.get("name"))
        return None

    name = raw.get("name", {})

    # Capital is a list in v3.1; take first element
    capitals = raw.get("capital", [])
    capital = capitals[0] if capitals else None

    # Languages: {code: name}
    languages = [
        {"cca2": cca2, "code": code, "name": name_val}
        for code, name_val in raw.get("languages", {}).items()
    ]

    # Currencies: {code: {name, symbol}}
    currencies = [
        {
            "cca2": cca2,
            "code": code,
            "name": cur.get("name"),
            "symbol": cur.get("symbol"),
        }
        for code, cur in raw.get("currencies", {}).items()
    ]

    # Borders: list of cca3 codes
    borders = [
        {"cca2": cca2, "border_cca3": b}
        for b in raw.get("borders", [])
    ]

    return {
        "country": {
            "cca2": cca2,
            "cca3": cca3,
            "common_name": name.get("common", ""),
            "official_name": name.get("official"),
            "region": raw.get("region"),
            "subregion": raw.get("subregion"),
            "capital": capital,
            "population": raw.get("population"),
            "area_km2": None,   # not fetched (API 10-field limit)
            "latitude": None,   # not fetched (API 10-field limit)
            "longitude": None,  # not fetched (API 10-field limit)
            "flag_png": None,   # not fetched (API 10-field limit)
            "flag_svg": None,   # not fetched (API 10-field limit)
        },
        "languages": languages,
        "currencies": currencies,
        "borders": borders,
    }


# ─── LOAD ─────────────────────────────────────────────────────────────────────

def upsert_country(conn: sqlite3.Connection, record: dict) -> str:
    """Insert or update a country record. Returns 'inserted' or 'updated'."""
    existing = conn.execute(
        "SELECT cca2 FROM countries WHERE cca2 = ?", (record["cca2"],)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE countries SET
               cca3=:cca3, common_name=:common_name, official_name=:official_name,
               region=:region, subregion=:subregion, capital=:capital,
               population=:population, area_km2=:area_km2,
               latitude=:latitude, longitude=:longitude,
               flag_png=:flag_png, flag_svg=:flag_svg
               WHERE cca2=:cca2""",
            record,
        )
        return "updated"
    else:
        conn.execute(
            """INSERT INTO countries
               (cca2,cca3,common_name,official_name,region,subregion,capital,
                population,area_km2,latitude,longitude,flag_png,flag_svg)
               VALUES
               (:cca2,:cca3,:common_name,:official_name,:region,:subregion,:capital,
                :population,:area_km2,:latitude,:longitude,:flag_png,:flag_svg)""",
            record,
        )
        return "inserted"


def load(conn: sqlite3.Connection, transformed: dict) -> str:
    """Load all normalized data for one country into the database."""
    action = upsert_country(conn, transformed["country"])
    cca2 = transformed["country"]["cca2"]

    # Replace child records (delete + insert is simpler than full upsert)
    conn.execute("DELETE FROM languages WHERE cca2 = ?", (cca2,))
    conn.execute("DELETE FROM currencies WHERE cca2 = ?", (cca2,))
    conn.execute("DELETE FROM borders WHERE cca2 = ?", (cca2,))

    if transformed["languages"]:
        conn.executemany(
            "INSERT OR IGNORE INTO languages (cca2, code, name) VALUES (:cca2, :code, :name)",
            transformed["languages"],
        )
    if transformed["currencies"]:
        conn.executemany(
            "INSERT OR IGNORE INTO currencies (cca2, code, name, symbol) VALUES (:cca2, :code, :name, :symbol)",
            transformed["currencies"],
        )
    if transformed["borders"]:
        conn.executemany(
            "INSERT OR IGNORE INTO borders (cca2, border_cca3) VALUES (:cca2, :border_cca3)",
            transformed["borders"],
        )

    return action


# ─── PIPELINE ────────────────────────────────────────────────────────────────

def run_pipeline(country_code: Optional[str] = None, dry_run: bool = False):
    """
    Full ETL pipeline:
    1. Extract — fetch from REST Countries API
    2. Transform — normalize into relational records
    3. Load — upsert into SQLite
    """
    started_at = datetime.utcnow().isoformat() + "Z"
    stats = {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0}

    # Extract
    raw_records = fetch_country(country_code) if country_code else fetch_all_countries()
    stats["fetched"] = len(raw_records)

    if dry_run:
        log.info("[DRY RUN] Would process %d records — no DB writes", stats["fetched"])
        # Still transform to validate
        errors = 0
        for raw in raw_records:
            result = transform(raw)
            if result is None:
                errors += 1
        log.info("Transform validation: %d errors out of %d", errors, stats["fetched"])
        return stats

    # Init DB
    init_db()

    with get_db() as conn:
        # Start pipeline run log
        cursor = conn.execute(
            "INSERT INTO pipeline_runs (started_at, records_fetched) VALUES (?, ?)",
            (started_at, stats["fetched"]),
        )
        run_id = cursor.lastrowid
        conn.commit()

        # Transform + Load
        for raw in raw_records:
            transformed = transform(raw)
            if transformed is None:
                stats["skipped"] += 1
                continue

            action = load(conn, transformed)
            stats[action] += 1

        conn.commit()

        # Finalize run log
        finished_at = datetime.utcnow().isoformat() + "Z"
        conn.execute(
            """UPDATE pipeline_runs
               SET finished_at=?, records_inserted=?, records_updated=?, status='completed'
               WHERE id=?""",
            (finished_at, stats["inserted"], stats["updated"], run_id),
        )
        conn.commit()

    log.info(
        "Pipeline complete — fetched: %d | inserted: %d | updated: %d | skipped: %d",
        stats["fetched"], stats["inserted"], stats["updated"], stats["skipped"],
    )
    return stats


# ─── QUERY HELPERS ───────────────────────────────────────────────────────────

def query_summary():
    """Print a summary of what's in the database."""
    with get_db() as conn:
        counts = {
            "countries": conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0],
            "languages": conn.execute("SELECT COUNT(DISTINCT code) FROM languages").fetchone()[0],
            "currencies": conn.execute("SELECT COUNT(DISTINCT code) FROM currencies").fetchone()[0],
        }
        regions = conn.execute(
            "SELECT region, COUNT(*) as n FROM countries GROUP BY region ORDER BY n DESC"
        ).fetchall()

    print("\n=== Countries Database Summary ===")
    print(f"  Countries : {counts['countries']}")
    print(f"  Languages : {counts['languages']} unique")
    print(f"  Currencies: {counts['currencies']} unique")
    print("\n  By Region:")
    for row in regions:
        print(f"    {row['region'] or 'Unknown':20s} {row['n']:4d}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="REST Countries ETL Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + validate, no DB write")
    parser.add_argument("--country", metavar="ALPHA", help="Single country code (e.g. US, GBR)")
    parser.add_argument("--summary", action="store_true", help="Print DB summary after run")
    args = parser.parse_args()

    stats = run_pipeline(country_code=args.country, dry_run=args.dry_run)

    if args.summary and not args.dry_run:
        query_summary()
