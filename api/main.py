from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from routers import library_router, upload_router, semantic_router
from models.schemas import SearchResponse, SearchResult, StatusResponse
from database import get_pool, init_db, close_pool
from store import get_store, close_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Library API starting up...")
    await init_db()
    print("PostgreSQL database initialized")
    await get_store()
    print("pgvector store initialized")
    yield
    print("Library API shutting down...")
    await close_store()
    await close_pool()


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
app.include_router(semantic_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/search", response_model=SearchResponse, tags=["search"])
async def search_content(
    q: str = Query(..., min_length=1, description="Search query"),
    entry_id: Optional[str] = Query(default=None, description="Limit to specific entry"),
    section: Optional[str] = Query(default=None, description="Limit to section"),
    limit: int = Query(default=20, ge=1, le=50),
):
    """Full-text search across all library content using PostgreSQL FTS."""
    pool = await get_pool()

    where_parts = ["cf.tsv @@ websearch_to_tsquery('english', %(q)s)"]
    params = {"q": q, "limit": limit}

    if entry_id:
        where_parts.append("cf.id = %(entry_id)s")
        params["entry_id"] = entry_id
    if section:
        where_parts.append("cf.section = %(section)s")
        params["section"] = section

    where_sql = " AND ".join(where_parts)

    async with pool.connection() as conn:
        cur = await conn.execute(
            f"""SELECT cf.id, cf.section, cf.page,
                       ts_headline('english', cf.content,
                           websearch_to_tsquery('english', %(q)s),
                           'StartSel=>>>,StopSel=<<<,MaxFragments=1,MaxWords=32'
                       ) as snippet,
                       m.title
                FROM content_fts cf
                JOIN metadata m ON m.id = cf.id
                WHERE {where_sql}
                ORDER BY ts_rank(cf.tsv, websearch_to_tsquery('english', %(q)s)) DESC
                LIMIT %(limit)s""",
            params,
        )
        rows = await cur.fetchall()

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
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) as cnt FROM metadata")
        row = await cur.fetchone()
    return StatusResponse(
        status="healthy",
        version="1.0.0",
        total_entries=row["cnt"],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
