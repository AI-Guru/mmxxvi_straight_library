import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db
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
    db = get_db()

    where_clauses = []
    params = []

    if title:
        where_clauses.append("title LIKE ?")
        params.append(f"%{title}%")
    if author:
        where_clauses.append("author LIKE ?")
        params.append(f"%{author}%")
    if genre:
        where_clauses.append("genre LIKE ?")
        params.append(f"%{genre}%")
    if tag:
        where_clauses.append("custom_tags LIKE ?")
        params.append(f"%{tag}%")
    if year_min is not None:
        where_clauses.append("publication_year >= ?")
        params.append(year_min)
    if year_max is not None:
        where_clauses.append("publication_year <= ?")
        params.append(year_max)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    count_row = db.execute(
        f"SELECT COUNT(*) as cnt FROM metadata WHERE {where_sql}", params
    ).fetchone()
    total = count_row["cnt"]

    rows = db.execute(
        f"""SELECT id, title, author, publication_year, genre, custom_tags,
                   shortsummary_pages, summary_pages, fulltext_pages
            FROM metadata
            WHERE {where_sql}
            ORDER BY title
            LIMIT ? OFFSET ?""",
        params + [limit, skip],
    ).fetchall()

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

    db = get_db()

    # Get total pages from metadata.
    meta_row = db.execute(
        f"SELECT {section}_pages FROM metadata WHERE id = ?", (entry_id,)
    ).fetchone()
    if meta_row is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    total_pages = meta_row[f"{section}_pages"]

    if page > total_pages:
        raise HTTPException(
            status_code=400, detail=f"Page {page} out of range (1-{total_pages})"
        )

    # Fetch the specific page.
    row = db.execute(
        f"SELECT content FROM {section} WHERE id = ? AND page = ?",
        (entry_id, page),
    ).fetchone()

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
    db = get_db()

    row = db.execute(
        "SELECT title FROM metadata WHERE id = ?", (entry_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    title = row["title"]
    for table in ("chapters", "shortsummary", "summary", "fulltext", "metadata"):
        db.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))
    db.commit()

    return DeleteResponse(
        status="ok",
        entry_id=entry_id,
        message=f"Deleted '{title}'",
    )
