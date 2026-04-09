from __future__ import annotations
import os, logging
from dataclasses import dataclass
from typing import Any
import numpy as np
import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

log = logging.getLogger("nexus.retrieve")
TOP_K   = int(os.getenv("TOP_K", 8))
RRF_K   = int(os.getenv("RRF_K", 60))


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_path: str
    chunk_text: str
    rrf_score: float
    vector_rank: int | None
    bm25_rank: int | None


class HybridRetriever:
    """BM25 + pgvector ANN with Reciprocal Rank Fusion."""

    def __init__(self) -> None:
        self.model = SentenceTransformer(os.getenv("EMBED_MODEL", "BAAI/bge-large-en-v1.5"))
        self.conn = psycopg2.connect(os.environ["DATABASE_URL"])
        register_vector(self.conn)
        self._bm25: BM25Okapi | None = None
        self._corpus: list[dict[str, Any]] = []
        self._build_bm25_index()

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _build_bm25_index(self) -> None:
        """Load all chunk texts from Postgres and build in-memory BM25 index."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_path, chunk_text FROM documents ORDER BY chunk_index"
            )
            rows = cur.fetchall()

        if not rows:
            log.warning("No documents found — BM25 index is empty")
            return

        self._corpus = [
            {"id": r[0], "source_path": r[1], "chunk_text": r[2]} for r in rows
        ]
        tokenized = [doc["chunk_text"].lower().split() for doc in self._corpus]
        self._bm25 = BM25Okapi(tokenized)
        log.info("BM25 index built over %d chunks", len(self._corpus))

    def refresh_index(self) -> None:
        """Call after ingesting new documents to rebuild BM25 index."""
        self._build_bm25_index()

    # ------------------------------------------------------------------
    # Individual retrievers
    # ------------------------------------------------------------------

    def _vector_search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Return (chunk_id, cosine_distance) sorted ascending (closer = better)."""
        vec = self.model.encode(query, normalize_embeddings=True).tolist()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, embedding <=> %s::vector AS dist
                FROM documents
                ORDER BY dist
                LIMIT %s
                """,
                (vec, k),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    def _bm25_search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Return (chunk_id, bm25_score) sorted descending (higher = better)."""
        if self._bm25 is None or not self._corpus:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:k]
        return [
            (self._corpus[i]["id"], float(scores[i]))
            for i in top_indices
            if scores[i] > 0
        ]

    # ------------------------------------------------------------------
    # RRF fusion
    # ------------------------------------------------------------------

    def _rrf_fuse(
        self,
        vector_hits: list[tuple[str, float]],
        bm25_hits: list[tuple[str, float]],
        k: int,
    ) -> list[RetrievedChunk]:
        """Reciprocal Rank Fusion over two ranked lists."""
        vector_ranks: dict[str, int] = {
            chunk_id: rank + 1 for rank, (chunk_id, _) in enumerate(vector_hits)
        }
        bm25_ranks: dict[str, int] = {
            chunk_id: rank + 1 for rank, (chunk_id, _) in enumerate(bm25_hits)
        }

        all_ids = set(vector_ranks) | set(bm25_ranks)
        rrf_scores: dict[str, float] = {}
        for cid in all_ids:
            score = 0.0
            if cid in vector_ranks:
                score += 1.0 / (RRF_K + vector_ranks[cid])
            if cid in bm25_ranks:
                score += 1.0 / (RRF_K + bm25_ranks[cid])
            rrf_scores[cid] = score

        top_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:k]

        # Fetch texts for top ids
        if not top_ids:
            return []

        placeholders = ",".join(["%s"] * len(top_ids))
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT id, source_path, chunk_text FROM documents WHERE id IN ({placeholders})",
                top_ids,
            )
            rows = {r[0]: r for r in cur.fetchall()}

        results = []
        for cid in top_ids:
            if cid not in rows:
                continue
            _, source_path, chunk_text = rows[cid]
            results.append(
                RetrievedChunk(
                    chunk_id=cid,
                    source_path=source_path,
                    chunk_text=chunk_text,
                    rrf_score=rrf_scores[cid],
                    vector_rank=vector_ranks.get(cid),
                    bm25_rank=bm25_ranks.get(cid),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = TOP_K) -> list[RetrievedChunk]:
        """Hybrid retrieval: BM25 + pgvector ANN fused with RRF."""
        candidate_k = top_k * 3  # over-fetch before fusion
        vector_hits = self._vector_search(query, candidate_k)
        bm25_hits = self._bm25_search(query, candidate_k)
        chunks = self._rrf_fuse(vector_hits, bm25_hits, top_k)
        log.info(
            "Retrieved %d chunks (vector=%d, bm25=%d) for query: %.60s",
            len(chunks),
            len(vector_hits),
            len(bm25_hits),
            query,
        )
        return chunks
