from __future__ import annotations
import asyncio, hashlib, logging, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from asyncpg import Connection, Pool
from pybloom_live import ScalableBloomFilter
from sentence_transformers import SentenceTransformer

from nexus.adapters import AdapterRegistry
from nexus.models import IntelEvent, ClassificationLevel, ThreatTier
from nexus.ner import extract_entities
from nexus.metrics import INGEST_COUNTER, INGEST_LATENCY

logger = logging.getLogger(__name__)

# BGE model – MTEB score 64.23, 1024-dim output, runs CPU-only
EMBED_MODEL = SentenceTransformer("BAAI/bge-large-en-v1.5")


class IntSource(str, Enum):
    SIGINT = "sigint"
    HUMINT = "humint"
    IMINT  = "imint"
    OSINT  = "osint"
    STRUCT = "structured_db"


@dataclass
class RawEvent:
    source_type: IntSource
    source_id:   str
    raw_text:    str
    metadata:    dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class IngestionPipeline:
    """
    Orchestrates: validate -> deduplicate -> normalize -> embed -> NER -> persist.
    Thread-safe: each coroutine uses its own asyncpg connection from pool.
    """

    def __init__(self, pool: Pool, bloom_capacity: int = 1_000_000) -> None:
        self.pool    = pool
        self._bloom  = ScalableBloomFilter(
            initial_capacity=bloom_capacity, error_rate=0.001
        )
        self._lock   = asyncio.Lock()

    async def ingest(self, raw: RawEvent) -> str | None:
        """
        Ingest one event. Returns new event UUID or None if duplicate.
        Raises ValueError on schema validation failure.
        """
        with INGEST_LATENCY.time():
            # 1. Schema validation
            _validate(raw)

            # 2. Content fingerprint for dedup
            fp = hashlib.sha256(
                (raw.source_id + raw.raw_text).encode()
            ).hexdigest()

            async with self._lock:
                if fp in self._bloom:
                    logger.debug("Duplicate fingerprint %s – skipping", fp[:8])
                    return None
                self._bloom.add(fp)

            # 3. Normalize via INT-specific adapter
            adapter  = AdapterRegistry.get(raw.source_type)
            event    = await adapter.normalize(raw)

            # 4. Generate embedding (CPU-bound -> run in thread pool)
            loop      = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(
                None,
                lambda: EMBED_MODEL.encode(
                    event.normalized_text, normalize_embeddings=True
                ).tolist()
            )

            # 5. NER – extract entities for graph fusion
            entities = await extract_entities(event.normalized_text)

            # 6. Persist (TimescaleDB hypertable + pgvector) in one transaction
            event_id = await self._persist(event, embedding, entities)

        INGEST_COUNTER.labels(source=raw.source_type.value).inc()
        return event_id

    async def _persist(
        self,
        event:     IntelEvent,
        embedding: list[float],
        entities:  list[dict],
    ) -> str:
        event_id = str(uuid.uuid4())
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Insert into TimescaleDB hypertable
                await conn.execute(
                    """
                    INSERT INTO intel_events (
                        id, source_id, event_time, int_type,
                        classification, threat_tier, raw_text,
                        normalized_text, geo_lat, geo_lon,
                        embedding, metadata, fingerprint
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11::vector, $12::jsonb, $13
                    )
                    """,
                    event_id,
                    event.source_id,
                    event.event_time,
                    event.int_type.value,
                    event.classification.value,
                    event.threat_tier.value,
                    event.raw_text,
                    event.normalized_text,
                    event.geo_lat,
                    event.geo_lon,
                    str(embedding),   # asyncpg passes as text, cast to vector
                    event.metadata,
                    event.fingerprint,
                )

                # Insert extracted entities and link to event
                for ent in entities:
                    ent_id = await conn.fetchval(
                        """
                        INSERT INTO entities (name, entity_type, aliases)
                        VALUES ($1, $2, $3::jsonb)
                        ON CONFLICT (name, entity_type) DO UPDATE
                          SET aliases = entities.aliases || EXCLUDED.aliases
                        RETURNING id
                        """,
                        ent["name"], ent["type"], ent.get("aliases", []),
                    )
                    await conn.execute(
                        """
                        INSERT INTO event_entities (event_id, entity_id, role, confidence)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT DO NOTHING
                        """,
                        event_id, ent_id, ent["role"], ent["confidence"],
                    )
        return event_id


def _validate(raw: RawEvent) -> None:
    if not raw.raw_text or len(raw.raw_text.strip()) < 10:
        raise ValueError("raw_text too short or empty")
    if not raw.source_id:
        raise ValueError("source_id is required")
    if raw.received_at.tzinfo is None:
        raise ValueError("received_at must be timezone-aware")
