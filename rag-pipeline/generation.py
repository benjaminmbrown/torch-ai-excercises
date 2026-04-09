from __future__ import annotations
import os, logging, textwrap
from dataclasses import dataclass, field
from typing import Generator

import anthropic

from ingestion import DocumentIngester
from retrieval import HybridRetriever, RetrievedChunk

log = logging.getLogger("nexus.generate")

GENERATION_MODEL = os.getenv("GENERATION_MODEL", "claude-sonnet-4-6")
MAX_CONTEXT_CHARS = 12_000  # ~3 k tokens at 4 chars/token

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a precise intelligence analyst assistant. Answer the user's question
    using ONLY the provided document excerpts. If the excerpts do not contain
    enough information to answer, say so explicitly.

    Rules:
    - Cite sources inline as [source_N] referencing the list at the end.
    - Do not speculate beyond what the excerpts support.
    - Keep answers concise and structured (bullet points where appropriate).
""")


@dataclass
class RAGResponse:
    answer: str
    citations: list[str]
    chunks_used: int
    model: str = GENERATION_MODEL


@dataclass
class EvalResult:
    question: str
    expected_keywords: list[str]
    answer: str
    keyword_recall: float
    passed: bool
    chunks_used: int


# ---------------------------------------------------------------------------
# Evaluation set — lightweight keyword-recall harness
# ---------------------------------------------------------------------------
EVAL_SET: list[dict] = [
    {
        "question": "What embedding model is used for document ingestion?",
        "keywords": ["bge", "large", "1024"],
    },
    {
        "question": "How are duplicate chunks detected during ingestion?",
        "keywords": ["sha256", "hash", "content_hash"],
    },
    {
        "question": "What fusion strategy combines BM25 and vector search results?",
        "keywords": ["reciprocal", "rank", "rrf"],
    },
    {
        "question": "Which Claude model is used for answer generation?",
        "keywords": ["claude", "sonnet"],
    },
    {
        "question": "What chunk size and overlap are used in the text splitter?",
        "keywords": ["512", "64"],
    },
]


class RAGPipeline:
    """Full RAG pipeline: retrieve → build context → generate → cite."""

    def __init__(self) -> None:
        self.retriever = HybridRetriever()
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _build_context(self, chunks: list[RetrievedChunk]) -> tuple[str, list[str]]:
        """Concatenate chunks up to MAX_CONTEXT_CHARS; return (context_str, citations)."""
        parts: list[str] = []
        citations: list[str] = []
        total = 0
        for i, chunk in enumerate(chunks, start=1):
            label = f"[source_{i}]"
            snippet = f"{label}\n{chunk.chunk_text}\n"
            if total + len(snippet) > MAX_CONTEXT_CHARS:
                break
            parts.append(snippet)
            citations.append(f"{label} {chunk.source_path}")
            total += len(snippet)
        return "\n".join(parts), citations

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def answer(self, question: str, top_k: int = 8) -> RAGResponse:
        chunks = self.retriever.retrieve(question, top_k=top_k)
        context, citations = self._build_context(chunks)

        user_message = (
            f"Document excerpts:\n\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Sources:\n" + "\n".join(citations)
        )

        response = self.client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer_text = response.content[0].text
        return RAGResponse(
            answer=answer_text,
            citations=citations,
            chunks_used=len(chunks),
        )

    def answer_stream(self, question: str, top_k: int = 8) -> Generator[str, None, None]:
        """Streaming variant — yields text deltas."""
        chunks = self.retriever.retrieve(question, top_k=top_k)
        context, citations = self._build_context(chunks)

        user_message = (
            f"Document excerpts:\n\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Sources:\n" + "\n".join(citations)
        )

        with self.client.messages.stream(
            model=GENERATION_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    # ------------------------------------------------------------------
    # Eval harness
    # ------------------------------------------------------------------

    def run_eval(self, eval_set: list[dict] | None = None) -> list[EvalResult]:
        """Keyword-recall evaluation over EVAL_SET."""
        dataset = eval_set or EVAL_SET
        results = []
        for item in dataset:
            q = item["question"]
            keywords = [kw.lower() for kw in item["keywords"]]
            try:
                resp = self.answer(q, top_k=8)
                answer_lower = resp.answer.lower()
                hits = sum(1 for kw in keywords if kw in answer_lower)
                recall = hits / len(keywords) if keywords else 1.0
                results.append(
                    EvalResult(
                        question=q,
                        expected_keywords=item["keywords"],
                        answer=resp.answer,
                        keyword_recall=recall,
                        passed=recall >= 0.5,
                        chunks_used=resp.chunks_used,
                    )
                )
            except Exception as exc:
                log.error("Eval failed for '%s': %s", q, exc)
                results.append(
                    EvalResult(
                        question=q,
                        expected_keywords=item["keywords"],
                        answer=f"ERROR: {exc}",
                        keyword_recall=0.0,
                        passed=False,
                        chunks_used=0,
                    )
                )

        passed = sum(1 for r in results if r.passed)
        log.info("Eval: %d/%d passed (%.0f%%)", passed, len(results), 100 * passed / len(results))
        return results


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    pipeline = RAGPipeline()

    # Optionally ingest a file passed as first arg
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        ingester = DocumentIngester()
        n = ingester.ingest_file(path)
        pipeline.retriever.refresh_index()
        print(f"Ingested {n} new chunks from {path.name}\n")

    # Interactive Q&A loop
    print("NEXUS RAG Pipeline — type 'eval' to run evaluation, 'quit' to exit\n")
    while True:
        try:
            q = input("Question: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.lower() == "quit":
            break
        if q.lower() == "eval":
            results = pipeline.run_eval()
            for r in results:
                status = "PASS" if r.passed else "FAIL"
                print(f"[{status}] {r.question}")
                print(f"       recall={r.keyword_recall:.0%}  chunks={r.chunks_used}")
            passed = sum(1 for r in results if r.passed)
            print(f"\n{passed}/{len(results)} passed")
            continue

        resp = pipeline.answer(q)
        print(f"\nAnswer:\n{resp.answer}\n")
        print("Sources:")
        for c in resp.citations:
            print(f"  {c}")
        print()
