from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Sequence

from asyncpg import Pool
from sentence_transformers import SentenceTransformer

EMBED_MODEL  = SentenceTransformer("BAAI/bge-large-en-v1.5")
RRF_K        = 60   # RRF constant – standard value per TREC literature
MAX_RESULTS  = 50


@dataclass
class SearchResult:
    event_id:    str
    score:       float
    rrf_rank:    int
    source_id:   str
    int_type:    str
    event_time:  str
    classification: str
    excerpt:     str


class HybridSearchService:
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def search(
        self,
        query:      str,
        top_k:      int  = 20,
        int_types:  list[str] | None = None,
        min_date:   str | None = None,
        max_date:   str | None = None,
    ) -> list[SearchResult]:
        """
        Parallel vector + keyword search with RRF fusion.
        Clearance enforcement via DB-level RLS (no app-layer filter needed).
        """
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: EMBED_MODEL.encode(
                query, normalize_embeddings=True
            ).tolist()
        )

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH
                vector_ranked AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            ORDER BY embedding <=> $1::vector
                        )                         AS vec_rank,
                        1 - (embedding <=> $1::vector) AS similarity
                    FROM intel_events
                    WHERE
                        ($3::text[]  IS NULL OR int_type  = ANY($3))
                        AND ($4::date IS NULL OR event_time >= $4)
                        AND ($5::date IS NULL OR event_time <= $5)
                    ORDER BY embedding <=> $1::vector
                    LIMIT 100
                ),
                text_ranked AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            ORDER BY ts_rank_cd(
                                to_tsvector('english', normalized_text),
                                plainto_tsquery('english', $2)
                            ) DESC
                        ) AS txt_rank
                    FROM intel_events
                    WHERE
                        to_tsvector('english', normalized_text)
                            @@ plainto_tsquery('english', $2)
                        AND ($3::text[] IS NULL OR int_type = ANY($3))
                        AND ($4::date  IS NULL OR event_time >= $4)
                        AND ($5::date  IS NULL OR event_time <= $5)
                    LIMIT 100
                ),
                rrf AS (
                    SELECT
                        COALESCE(v.id, t.id) AS id,
                        (
                          COALESCE(1.0 / ($6 + v.vec_rank), 0) +
                          COALESCE(1.0 / ($6 + t.txt_rank), 0)
                        )                       AS rrf_score,
                        COALESCE(v.similarity, 0) AS similarity,
                        ROW_NUMBER() OVER (
                            ORDER BY (
                              COALESCE(1.0 / ($6 + v.vec_rank), 0) +
                              COALESCE(1.0 / ($6 + t.txt_rank), 0)
                            ) DESC
                        ) AS rrf_rank
                    FROM vector_ranked v
                    FULL OUTER JOIN text_ranked t USING (id)
                )
                SELECT
                    e.id, e.source_id, e.int_type, e.event_time,
                    e.classification,
                    LEFT(e.normalized_text, 300) AS excerpt,
                    r.rrf_score, r.rrf_rank
                FROM rrf r
                JOIN intel_events e ON e.id = r.id
                ORDER BY r.rrf_rank
                LIMIT $7
                """,
                str(embedding),   # $1
                query,             # $2
                int_types,         # $3
                min_date,          # $4
                max_date,          # $5
                float(RRF_K),     # $6
                top_k,             # $7
            )

        return [
            SearchResult(
                event_id       = r["id"],
                score          = float(r["rrf_score"]),
                rrf_rank       = r["rrf_rank"],
                source_id      = r["source_id"],
                int_type       = r["int_type"],
                event_time     = r["event_time"].isoformat(),
                classification = r["classification"],
                excerpt        = r["excerpt"],
            )
            for r in rows
        ]
