"""Semantic search router using pgvector via LangGraph store."""

from fastapi import APIRouter, HTTPException

from store import get_store, CHUNKS_NAMESPACE
from models.schemas import (
    SemanticSearchRequest,
    SemanticSearchResult,
    SemanticSearchResponse,
)

router = APIRouter(prefix="/api", tags=["semantic-search"])

VALID_SECTIONS = ("shortsummary", "summary", "fulltext")


@router.post("/semantic-search", response_model=SemanticSearchResponse)
async def semantic_search(request: SemanticSearchRequest):
    """Semantic vector search across library fulltext content.

    Uses pgvector embeddings to find conceptually related passages.
    Each result points to a specific (entry_id, section, page_number)
    that can be read via GET /api/entries/{id}/page.
    """
    if request.section and request.section not in VALID_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Section must be one of: {', '.join(VALID_SECTIONS)}",
        )

    store = await get_store()

    if request.entry_id:
        namespace = (*CHUNKS_NAMESPACE, request.entry_id)
    else:
        namespace = CHUNKS_NAMESPACE

    filter_dict = {}
    if request.section:
        filter_dict["section"] = request.section

    try:
        results = await store.asearch(
            namespace,
            query=request.query,
            limit=request.limit,
            filter=filter_dict if filter_dict else None,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Semantic search error: {str(e)}"
        )

    search_results = []
    for item in results:
        data = item.value
        search_results.append(
            SemanticSearchResult(
                entry_id=data.get("entry_id", ""),
                title=data.get("title", ""),
                author=data.get("author", ""),
                section=data.get("section", ""),
                page_number=data.get("page_number", 0),
                chunk_index=data.get("chunk_index", 0),
                snippet=data.get("text", "")[:300],
            )
        )

    return SemanticSearchResponse(
        query=request.query,
        results=search_results,
        total_results=len(search_results),
    )
