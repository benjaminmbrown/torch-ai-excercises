from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nexus.auth import require_clearance, CurrentUser
from nexus.search.hybrid import HybridSearchService, SearchResult
from nexus.deps import get_search_service

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchRequest(BaseModel):
    query:      str         = Field(..., min_length=3, max_length=1000)
    top_k:      int         = Field(20, ge=1, le=100)
    int_types:  list[str] | None = None
    min_date:   str | None = None   # ISO-8601 date string
    max_date:   str | None = None


class SearchResponse(BaseModel):
    results:    list[SearchResult]
    total:      int
    query_time_ms: float


@router.post("/semantic", response_model=SearchResponse)
async def semantic_search(
    req:     SearchRequest,
    svc:     HybridSearchService = Depends(get_search_service),
    user:    CurrentUser         = Depends(require_clearance),
):
    """
    Hybrid semantic search. Clearance enforcement is at the DB layer
    via Row-Level Security — this endpoint never filters in application code.

    Returns results ordered by Reciprocal Rank Fusion score descending.
    """
    import time
    t0 = time.monotonic()

    try:
        results = await svc.search(
            query     = req.query,
            top_k     = req.top_k,
            int_types = req.int_types,
            min_date  = req.min_date,
            max_date  = req.max_date,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return SearchResponse(
        results      = results,
        total        = len(results),
        query_time_ms= (time.monotonic() - t0) * 1000,
    )
