import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_pool
from models.schemas import EntryMetadata, EntryListResponse, PageResponse, DeleteResponse

router = APIRouter(prefix="/api/entries", tags=["library"])

VALID_SECTIONS = ("shortsummary", "summary", "fulltext")


@router.get("", response_model=EntryListResponse)
async def list_entries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    title: Optional[str] = Query(default=None),
    author: Optional[str] = Query(default=None),
    genre: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    year_min: Optional[int] = Query(default=None),
    year_max: Optional[int] = Query(default=None),
):
    """List library entries with optional filtering and pagination."""
    pool = await get_pool()

    where_clauses = []
    params: dict = {}

    if title:
        where_clauses.append("title ILIKE %(title)s")
        params["title"] = f"%{title}%"
    if author:
        where_clauses.append("author ILIKE %(author)s")
        params["author"] = f"%{author}%"
    if genre:
        where_clauses.append("genre ILIKE %(genre)s")
        params["genre"] = f"%{genre}%"
    if tag:
        where_clauses.append("custom_tags ILIKE %(tag)s")
        params["tag"] = f"%{tag}%"
    if year_min is not None:
        where_clauses.append("publication_year >= %(year_min)s")
        params["year_min"] = year_min
    if year_max is not None:
        where_clauses.append("publication_year <= %(year_max)s")
        params["year_max"] = year_max

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT COUNT(*) as cnt FROM metadata WHERE {where_sql}", params
        )
        count_row = await cur.fetchone()
        total = count_row["cnt"]

        params["limit"] = limit
        params["skip"] = skip
        cur = await conn.execute(
            f"""SELECT id, title, author, publication_year, genre, custom_tags,
                       shortsummary_pages, summary_pages, fulltext_pages
                FROM metadata
                WHERE {where_sql}
                ORDER BY title
                LIMIT %(limit)s OFFSET %(skip)s""",
            params,
        )
        rows = await cur.fetchall()

    entries = [
        EntryMetadata(
            id=row["id"],
            title=row["title"],
            author=row["author"],
            publication_year=row["publication_year"],
            genre=row["genre"],
            custom_tags=json.loads(row["custom_tags"]) if row["custom_tags"] else [],
            shortsummary_pages=row["shortsummary_pages"],
            summary_pages=row["summary_pages"],
            fulltext_pages=row["fulltext_pages"],
        )
        for row in rows
    ]

    return EntryListResponse(entries=entries, total=total, skip=skip, limit=limit)


@router.get("/{entry_id}/page", response_model=PageResponse)
async def get_entry_page(
    entry_id: str,
    section: str = Query(..., description="shortsummary, summary, or fulltext"),
    page: int = Query(default=1, ge=1),
):
    """Get a specific page of a specific section for a library entry."""
    if section not in VALID_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Section must be one of: {', '.join(VALID_SECTIONS)}",
        )

    pool = await get_pool()
    col = f"{section}_pages"

    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT {col} FROM metadata WHERE id = %(id)s", {"id": entry_id}
        )
        meta_row = await cur.fetchone()
        if meta_row is None:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

        total_pages = meta_row[col]

        if total_pages == 0:
            return PageResponse(
                entry_id=entry_id,
                section=section,
                page_number=0,
                total_pages=0,
                content="",
            )

        if page > total_pages:
            raise HTTPException(
                status_code=400, detail=f"Page {page} out of range (1-{total_pages})"
            )

        cur = await conn.execute(
            f"SELECT content FROM {section} WHERE id = %(id)s AND page = %(page)s",
            {"id": entry_id, "page": page},
        )
        row = await cur.fetchone()

    return PageResponse(
        entry_id=entry_id,
        section=section,
        page_number=page,
        total_pages=total_pages,
        content=row["content"] if row else "",
    )


@router.delete("/{entry_id}", response_model=DeleteResponse)
async def delete_entry(entry_id: str):
    """Delete a library entry and all its pages."""
    pool = await get_pool()

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT title FROM metadata WHERE id = %(id)s", {"id": entry_id}
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

        title = row["title"]
        # CASCADE deletes all related rows in content tables, chapters, and content_fts.
        await conn.execute(
            "DELETE FROM metadata WHERE id = %(id)s", {"id": entry_id}
        )

    # Clean up pgvector embeddings.
    try:
        from store import get_store, CHUNKS_NAMESPACE

        store = await get_store()
        chunk_namespace = (*CHUNKS_NAMESPACE, entry_id)
        old_items = await store.asearch(chunk_namespace, query=None, limit=10000)
        for old_item in old_items:
            await store.adelete(chunk_namespace, old_item.key)
    except Exception as e:
        print(f"Warning: pgvector cleanup failed for {entry_id}: {e}")

    return DeleteResponse(
        status="ok",
        entry_id=entry_id,
        message=f"Deleted '{title}'",
    )
