"""
Torch.AI — Full-Stack Engineer Exercise
Naval SITREP Event Parser

Ingests structured operational event data (USS Spruance / DDG-170 shadowing incident),
exposes a REST API, and renders a minimal event timeline dashboard.

Exercise: https://torch-ai.atlassian.net/wiki/spaces/TCITAGIP/pages/1576960001/Full-Stack+Engineer
"""

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "events.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(
    title="SITREP Event Parser",
    description="Operational event timeline parser — Torch.AI Full-Stack Exercise",
    version="1.0.0",
)


# ─── DATABASE ────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                sequence    INTEGER,
                timestamp   TEXT,
                vessel      TEXT,
                bearing     TEXT,
                distance_nm REAL,
                speed_kts   REAL,
                description TEXT,
                raw         TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ─── SITREP PARSER ───────────────────────────────────────────────────────────

# Seed data — actual exercise input
SEED_SITREP = """
1. 28/0814Z: USS SPRUANCE observed a Chinese LUYANG II DDG-170 commence shadowing operations on the port quarter at 10NM.
2. 28/0825Z: DDG-170 was observed paralleling course remaining on the port quarter at 9NM.
3. 28/0836Z: DDG-170 remained on port quarter at 9NM.
4. 28/0841Z: DDG-170 CPA'd port quarter at 8NM paralleling course at 25 knots. No communications were established.
5. 28/0900Z: No change noted in DDG-170 posture.
""".strip()


def parse_sitrep_line(line: str) -> Optional[dict]:
    """Parse a single SITREP event line into structured fields."""
    match = re.match(r"(\d+)\.\s+(\d+/\d+Z):\s+(.+)", line.strip())
    if not match:
        return None

    seq, ts, desc = match.group(1), match.group(2), match.group(3)

    # Extract distance (e.g. "10NM", "8NM")
    dist_match = re.search(r"(\d+(?:\.\d+)?)\s*NM", desc, re.IGNORECASE)
    distance = float(dist_match.group(1)) if dist_match else None

    # Extract speed (e.g. "25 knots")
    speed_match = re.search(r"(\d+(?:\.\d+)?)\s*knots?", desc, re.IGNORECASE)
    speed = float(speed_match.group(1)) if speed_match else None

    # Identify vessel mentioned
    vessel = "DDG-170"
    if "USS SPRUANCE" in desc.upper():
        vessel = "USS SPRUANCE"

    # Parse DTG to ISO (day/HHMMz → assume current month/year for demo)
    day, time_part = ts.split("/")
    hour, minute = time_part[:2], time_part[2:4]
    iso_ts = f"2024-01-{int(day):02d}T{hour}:{minute}:00Z"

    return {
        "id": str(uuid.uuid4()),
        "sequence": int(seq),
        "timestamp": iso_ts,
        "vessel": vessel,
        "bearing": "port quarter" if "port quarter" in desc.lower() else None,
        "distance_nm": distance,
        "speed_kts": speed,
        "description": desc.strip(),
        "raw": line.strip(),
    }


def seed_events():
    """Load seed SITREP data on startup if table is empty."""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count > 0:
            return
        for line in SEED_SITREP.split("\n"):
            event = parse_sitrep_line(line)
            if event:
                conn.execute(
                    """INSERT INTO events
                       (id, sequence, timestamp, vessel, bearing, distance_nm, speed_kts, description, raw)
                       VALUES (:id,:sequence,:timestamp,:vessel,:bearing,:distance_nm,:speed_kts,:description,:raw)""",
                    event,
                )
        conn.commit()


@app.on_event("startup")
def startup():
    init_db()
    seed_events()


# ─── MODELS ──────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    timestamp: str
    vessel: str
    bearing: Optional[str] = None
    distance_nm: Optional[float] = None
    speed_kts: Optional[float] = None
    description: str
    raw: Optional[str] = None


class Event(EventCreate):
    id: str
    sequence: int
    created_at: str


# ─── API ROUTES ──────────────────────────────────────────────────────────────

@app.get("/events", response_model=list[dict], summary="List all events")
def list_events(
    vessel: Optional[str] = Query(None, description="Filter by vessel name"),
    keyword: Optional[str] = Query(None, description="Search description text"),
):
    with get_db() as conn:
        sql = "SELECT * FROM events WHERE 1=1"
        params = []
        if vessel:
            sql += " AND vessel LIKE ?"
            params.append(f"%{vessel}%")
        if keyword:
            sql += " AND description LIKE ?"
            params.append(f"%{keyword}%")
        sql += " ORDER BY sequence"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@app.get("/events/{event_id}", response_model=dict, summary="Get a specific event")
def get_event(event_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        return dict(row)


@app.post("/events", response_model=dict, status_code=201, summary="Create a new event")
def create_event(body: EventCreate):
    with get_db() as conn:
        max_seq = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()[0]
        event = {
            "id": str(uuid.uuid4()),
            "sequence": max_seq + 1,
            **body.model_dump(),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        conn.execute(
            """INSERT INTO events
               (id,sequence,timestamp,vessel,bearing,distance_nm,speed_kts,description,raw,created_at)
               VALUES (:id,:sequence,:timestamp,:vessel,:bearing,:distance_nm,:speed_kts,:description,:raw,:created_at)""",
            event,
        )
        conn.commit()
        return event


@app.get("/events/search/", response_model=list[dict], summary="Search events by keyword")
def search_events(q: str = Query(..., description="Search term")):
    return list_events(keyword=q)


@app.get("/health")
def health():
    return {"status": "ok"}


# ─── DASHBOARD UI ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return (TEMPLATES_DIR / "index.html").read_text()
