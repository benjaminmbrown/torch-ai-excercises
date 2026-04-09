from __future__ import annotations
import textwrap
from dataclasses import dataclass, field
from typing import AsyncIterator

from nexus.search.hybrid import HybridSearchService, SearchResult
from nexus.llm.client import LLMClient          # wraps vLLM or Azure OpenAI

MAX_CONTEXT_TOKENS = 6000  # leave headroom for prompt + response
CHARS_PER_TOKEN    = 4     # rough approximation for budget check


@dataclass
class RAGResponse:
    answer:    str
    citations: list[dict]   # source_id, event_time, classification, excerpt
    confidence: float       # average retrieval score of top-k context
    total_events_retrieved: int


SYSTEM_PROMPT = textwrap.dedent("""
    You are an intelligence analysis assistant for NEXUS.
    Answer the question using ONLY the provided context events.
    Rules:
    1. Never assert facts not present in the context.
    2. Always cite the source_id for each claim.
    3. If the context does not contain sufficient information,
       say "Insufficient evidence in current retrieval window."
    4. Do not speculate beyond the classification level of the context.
""")


class RAGEngine:
    def __init__(
        self,
        search_svc: HybridSearchService,
        llm:        LLMClient,
        top_k:      int = 10,
    ) -> None:
        self.search_svc = search_svc
        self.llm        = llm
        self.top_k      = top_k

    async def query(self, question: str) -> RAGResponse:
        # 1. Retrieve relevant events
        hits: list[SearchResult] = await self.search_svc.search(
            query=question, top_k=self.top_k
        )
        if not hits:
            return RAGResponse(
                answer="No relevant events found in current retrieval window.",
                citations=[], confidence=0.0, total_events_retrieved=0,
            )

        # 2. Build context window (budget-aware)
        context_parts  = []
        citations      = []
        token_budget   = MAX_CONTEXT_TOKENS * CHARS_PER_TOKEN

        for hit in hits:
            chunk = (
                f"[SOURCE: {hit.source_id} | "
                f"{hit.int_type.upper()} | "
                f"{hit.event_time} | "
                f"CLASSIFICATION: {hit.classification}]\n"
                f"{hit.excerpt}\n"
            )
            if len("\n".join(context_parts + [chunk])) > token_budget:
                break
            context_parts.append(chunk)
            citations.append({
                "source_id":      hit.source_id,
                "event_time":     hit.event_time,
                "classification": hit.classification,
                "excerpt":        hit.excerpt,
                "retrieval_score": hit.score,
            })

        context_block = "\n---\n".join(context_parts)
        user_prompt   = (
            f"CONTEXT EVENTS:\n{context_block}\n\n"
            f"QUESTION: {question}\n\n"
            "Answer concisely, cite source_ids in brackets:"
        )

        # 3. LLM inference (streaming capable)
        answer = await self.llm.complete(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=800,
            temperature=0.1,  # low temp for factual precision
        )

        avg_score = sum(c["retrieval_score"] for c in citations) / len(citations)

        return RAGResponse(
            answer                 = answer,
            citations              = citations,
            confidence             = avg_score,
            total_events_retrieved = len(hits),
        )

    async def stream_query(
        self, question: str
    ) -> AsyncIterator[str]:
        """Streaming version for long-poll UI connections."""
        hits = await self.search_svc.search(query=question, top_k=self.top_k)
        context_block = self._build_context(hits)
        user_prompt   = (
            f"CONTEXT EVENTS:\n{context_block}\n\nQUESTION: {question}"
        )
        async for chunk in self.llm.stream_complete(
            system=SYSTEM_PROMPT, user=user_prompt, max_tokens=800
        ):
            yield chunk
