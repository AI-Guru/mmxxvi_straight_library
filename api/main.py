from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from routers import library_router, upload_router
from models.schemas import SearchResponse, SearchResult, StatusResponse
from database import get_db, init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Library API starting up...")
    init_db()
    print("SQLite database initialized")
    yield
    print("Library API shutting down...")
    close_db()


app = FastAPI(
    title="Straight Library API",
    description="Read-only library browser API for book summaries and full texts",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(library_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/search", response_model=SearchResponse, tags=["search"])
async def search_content(
    q: str = Query(..., min_length=1, description="Search query (FTS5 syntax)"),
    entry_id: Optional[str] = Query(default=None, description="Limit to specific entry"),
    section: Optional[str] = Query(default=None, description="Limit to section"),
    limit: int = Query(default=20, ge=1, le=50),
):
    """Full-text search across all library content using FTS5."""
    db = get_db()

    where_parts = ["content_fts MATCH ?"]
    params = [q]

    if entry_id:
        where_parts.append("content_fts.id = ?")
        params.append(entry_id)
    if section:
        where_parts.append("content_fts.section = ?")
        params.append(section)

    where_sql = " AND ".join(where_parts)

    rows = db.execute(
        f"""SELECT content_fts.id, content_fts.section, content_fts.page,
                   snippet(content_fts, 3, '>>>', '<<<', '...', 32) as snippet,
                   metadata.title
            FROM content_fts
            JOIN metadata ON metadata.id = content_fts.id
            WHERE {where_sql}
            ORDER BY rank
            LIMIT ?""",
        params + [limit],
    ).fetchall()

    results = [
        SearchResult(
            entry_id=row["id"],
            title=row["title"],
            section=row["section"],
            page=row["page"],
            snippet=row["snippet"],
        )
        for row in rows
    ]

    return SearchResponse(results=results, total_results=len(results), query=q)


@app.get("/api/status", response_model=StatusResponse, tags=["health"])
async def health_check():
    db = get_db()
    row = db.execute("SELECT COUNT(*) as cnt FROM metadata").fetchone()
    return StatusResponse(
        status="healthy",
        version="1.0.0",
        total_entries=row["cnt"],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
