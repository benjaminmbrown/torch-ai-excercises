from __future__ import annotations
import os, uuid, hashlib, logging
from pathlib import Path
from typing import Iterator
import numpy as np
import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader
from docx import Document as DocxDocument

log = logging.getLogger("nexus.ingest")
CHUNK_SIZE, CHUNK_OVERLAP = 512, 64  # tokens

class DocumentIngester:
    def __init__(self):
        self.model = SentenceTransformer(os.getenv("EMBED_MODEL", "BAAI/bge-large-en-v1.5"))
        self.conn = psycopg2.connect(os.environ["DATABASE_URL"])
        register_vector(self.conn)
        self._init_schema()

    def _init_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    source_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    chunk_index  INT NOT NULL,
                    chunk_text   TEXT NOT NULL,
                    embedding    vector(1024),
                    metadata     JSONB DEFAULT '{}'
                )""")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS documents_embedding_idx
                ON documents USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)""")
            self.conn.commit()

    def ingest_file(self, path: Path) -> int:
        """Return count of chunks ingested (0 if already exists)."""
        chunks = list(self._extract_chunks(path))
        ingested = 0
        for i, text in enumerate(chunks):
            h = hashlib.sha256(text.encode()).hexdigest()
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM documents WHERE content_hash=%s", (h,))
                if cur.fetchone():
                    continue  # idempotent: skip already-ingested chunks
                vec = self.model.encode(text, normalize_embeddings=True).tolist()
                cur.execute("""
                    INSERT INTO documents (source_path, content_hash, chunk_index, chunk_text, embedding)
                    VALUES (%s, %s, %s, %s, %s)""",
                    (str(path), h, i, text, vec))
                ingested += 1
        self.conn.commit()
        log.info("Ingested %d new chunks from %s", ingested, path.name)
        return ingested

    def _extract_chunks(self, path: Path) -> Iterator[str]:
        text = self._read_file(path)
        words = text.split()
        for start in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP):
            chunk = " ".join(words[start : start + CHUNK_SIZE])
            if len(chunk.strip()) > 50:
                yield chunk

    def _read_file(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(path)
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        elif suffix == ".docx":
            doc = DocxDocument(path)
            return "\n".join(p.text for p in doc.paragraphs)
        elif suffix in (".txt", ".md"):
            return path.read_text(encoding="utf-8")
        raise ValueError(f"Unsupported file type: {suffix}")
