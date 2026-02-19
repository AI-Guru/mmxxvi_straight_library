import json
import os
from typing import Optional

from fastmcp import FastMCP
from langgraph.store.postgres import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

# Configuration
POSTGRES_URL = os.environ.get(
    "POSTGRES_URL",
    "postgresql://libraryuser:librarypassword@postgres:5432/librarydb",
)
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b")
EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "1024"))

VALID_SECTIONS = ("shortsummary", "summary", "fulltext")
CHUNKS_NAMESPACE = ("library", "chunks")

mcp = FastMCP(
    "Straight Library MCP Server",
    instructions="""This server provides access to a digital library of hundreds of books.

Each book (called an "entry") has an ID (16-char hex string) and three content sections
at different detail levels. Not all sections are required — shortsummary and summary may
be empty (0 pages) for some entries, while fulltext may also be empty in rare cases.
Always check the page counts before attempting to read a section.

Content sections (from least to most detailed):
  - shortsummary: A brief overview (typically 0-1 pages, ~1000 tokens per page).
  - summary: A more detailed summary (typically 0-10 pages, ~1000 tokens per page).
  - fulltext: The complete text (typically tens to hundreds of pages, ~1000 tokens per page).

Recommended workflow for reading a book:
  1. Use list_entries to browse or filter the catalog (by title, author, genre, tags, year).
     Results are sorted alphabetically by title and include page counts per section.
  2. Use get_entry to see a book's full metadata and table of contents (chapter headings
     with their page numbers for each section). This lets you jump to specific chapters.
  3. Start with shortsummary (if available) for a quick overview.
  4. Read the summary for more detail, or jump to specific fulltext chapters using the
     page numbers from get_entry's chapter list.
  5. Use get_pages to read up to 10 consecutive pages in one call (reduces round-trips).
  6. Use search_content to find specific topics or passages across the entire library
     or within a specific book. Results include highlighted snippets.

Discovery paths:
  - Use search_content for keyword/phrase matching (PostgreSQL full-text search).
  - Use semantic_search for conceptual/thematic queries — finds related content even
    without exact keyword matches (e.g., "themes of isolation" finds passages about
    loneliness, solitude, etc.). Semantic search covers fulltext content only.
  - Both search tools return page references you can follow with get_page/get_pages.""",
)

# PostgreSQL connection pool for library data
_pool: Optional[AsyncConnectionPool] = None


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=POSTGRES_URL,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
        )
        await _pool.open()
    return _pool


# pgvector store for semantic search (initialized on first use)
_pg_store: Optional[AsyncPostgresStore] = None
_pg_store_cm = None


async def get_pg_store() -> AsyncPostgresStore:
    """Get or create the async pgvector store instance."""
    global _pg_store, _pg_store_cm
    if _pg_store is None:
        embed_model = OLLAMA_EMBED_MODEL
        if not embed_model.startswith("ollama:"):
            embed_model = f"ollama:{embed_model}"

        _pg_store_cm = AsyncPostgresStore.from_conn_string(
            POSTGRES_URL,
            index={
                "embed": embed_model,
                "dims": EMBEDDING_DIMENSION,
            },
        )
        _pg_store = await _pg_store_cm.__aenter__()
        await _pg_store.setup()
    return _pg_store


@mcp.tool()
async def list_entries(
    skip: int = 0,
    limit: int = 20,
    title: Optional[str] = None,
    author: Optional[str] = None,
    genre: Optional[str] = None,
    tag: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> dict:
    """Browse and filter the library catalog. Returns paginated book metadata.

    Use this as your starting point to discover books. Each entry includes page
    counts for all three sections (shortsummary_pages, summary_pages,
    fulltext_pages) — a count of 0 means that section is empty/unavailable.
    All filters use case-insensitive substring matching.
    Results are sorted alphabetically by title.

    After finding a book, call get_entry(entry_id) to see its table of contents
    and chapter headings before reading.

    Args:
        skip: Number of entries to skip for pagination (default 0).
        limit: Maximum entries to return (default 20, max 100).
        title: Filter by title substring (e.g., "war" matches "War and Peace").
        author: Filter by author substring (e.g., "tolkien").
        genre: Filter by genre substring (e.g., "fiction", "philosophy").
        tag: Filter by custom tag substring (e.g., "classic", "dystopia").
        year_min: Minimum publication year inclusive (e.g., 1900).
        year_max: Maximum publication year inclusive (e.g., 1999).

    Returns:
        Dictionary with:
        - 'entries': list of books (each has id, title, author, publication_year,
          genre, custom_tags list, shortsummary_pages, summary_pages, fulltext_pages)
        - 'total': total matching count (use with skip/limit for pagination)
        - 'skip': current offset
        - 'limit': current page size
    """
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
    limit = min(limit, 100)

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

    entries = []
    for row in rows:
        entries.append(
            {
                "id": row["id"],
                "title": row["title"],
                "author": row["author"],
                "publication_year": row["publication_year"],
                "genre": row["genre"],
                "custom_tags": (
                    json.loads(row["custom_tags"]) if row["custom_tags"] else []
                ),
                "shortsummary_pages": row["shortsummary_pages"],
                "summary_pages": row["summary_pages"],
                "fulltext_pages": row["fulltext_pages"],
            }
        )

    return {"entries": entries, "total": total, "skip": skip, "limit": limit}


@mcp.tool()
async def get_entry(entry_id: str) -> dict:
    """Get a book's full metadata and table of contents (chapter headings with page numbers).

    Call this before reading a book to understand its structure. The chapters list
    shows markdown headings found in each section with their page numbers, so you
    can jump directly to a specific chapter using get_page or get_pages instead
    of reading sequentially from page 1.

    A section with 0 pages in the metadata means it has no content (shortsummary
    and summary are optional). The chapters list may be empty if the book has no
    markdown headings.

    Args:
        entry_id: The entry ID (16-char hex string, obtained from list_entries).

    Returns:
        Dictionary with:
        - 'metadata': id, title, author, publication_year, genre, custom_tags,
          shortsummary_pages, summary_pages, fulltext_pages
        - 'chapters': list of {section, page, heading, level} ordered by section
          then page. Level 1 = top-level heading (#), level 2 = subheading (##), etc.
        Returns {'error': '...'} if entry_id is not found.
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT id, title, author, publication_year, genre, custom_tags,
                      shortsummary_pages, summary_pages, fulltext_pages
               FROM metadata WHERE id = %(id)s""",
            {"id": entry_id},
        )
        meta_row = await cur.fetchone()
        if meta_row is None:
            return {"error": f"Entry {entry_id} not found"}

        cur = await conn.execute(
            "SELECT section, page, heading, level FROM chapters WHERE id = %(id)s ORDER BY section, page",
            {"id": entry_id},
        )
        ch_rows = await cur.fetchall()

    chapters = [
        {
            "section": ch["section"],
            "page": ch["page"],
            "heading": ch["heading"],
            "level": ch["level"],
        }
        for ch in ch_rows
    ]

    return {
        "metadata": {
            "id": meta_row["id"],
            "title": meta_row["title"],
            "author": meta_row["author"],
            "publication_year": meta_row["publication_year"],
            "genre": meta_row["genre"],
            "custom_tags": (
                json.loads(meta_row["custom_tags"])
                if meta_row["custom_tags"]
                else []
            ),
            "shortsummary_pages": meta_row["shortsummary_pages"],
            "summary_pages": meta_row["summary_pages"],
            "fulltext_pages": meta_row["fulltext_pages"],
        },
        "chapters": chapters,
    }


@mcp.tool()
async def get_page(
    entry_id: str,
    section: str,
    page: int = 1,
) -> dict:
    """Read a single page of a book's content section.

    Each page contains ~1000 tokens (~4000 characters) of text. For reading
    multiple consecutive pages, prefer get_pages to reduce round-trips.

    If total_pages is 0, the section is empty (no content available).
    Check total_pages in the response to know when you've reached the end.

    Args:
        entry_id: The entry ID (16-char hex string).
        section: Content section — must be one of: shortsummary, summary, fulltext.
        page: Page number, 1-based (default 1). Must be between 1 and total_pages.

    Returns:
        Dictionary with entry_id, section, page_number, total_pages, and content.
        Returns {'error': '...'} if entry not found, invalid section, or page out of range.
    """
    if section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    pool = await get_pool()
    col = f"{section}_pages"

    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT {col} FROM metadata WHERE id = %(id)s", {"id": entry_id}
        )
        meta_row = await cur.fetchone()
        if meta_row is None:
            return {"error": f"Entry {entry_id} not found"}

        total_pages = meta_row[col]

        if total_pages == 0:
            return {
                "entry_id": entry_id,
                "section": section,
                "page_number": 0,
                "total_pages": 0,
                "content": "",
            }

        if page < 1 or page > total_pages:
            return {"error": f"Page {page} out of range (1-{total_pages})"}

        cur = await conn.execute(
            f"SELECT content FROM {section} WHERE id = %(id)s AND page = %(page)s",
            {"id": entry_id, "page": page},
        )
        row = await cur.fetchone()

    return {
        "entry_id": entry_id,
        "section": section,
        "page_number": page,
        "total_pages": total_pages,
        "content": row["content"] if row else "",
    }


@mcp.tool()
async def get_pages(
    entry_id: str,
    section: str,
    from_page: int = 1,
    to_page: int = 5,
) -> dict:
    """Read multiple consecutive pages of a book section in one call.

    Preferred over get_page when reading more than one page. Fetches up to
    10 pages at once (~10,000 tokens). If the requested range exceeds 10 pages,
    it is automatically capped. If to_page exceeds total_pages, it is clamped.

    If total_pages is 0, the section is empty (returns empty pages list).

    Args:
        entry_id: The entry ID (16-char hex string).
        section: Content section — must be one of: shortsummary, summary, fulltext.
        from_page: First page to read, 1-based (default 1).
        to_page: Last page to read, inclusive (default 5). Max range: 10 pages.

    Returns:
        Dictionary with entry_id, section, from_page, to_page, total_pages,
        and 'pages' list (each has page_number and content, in order).
        Returns {'error': '...'} if entry not found, invalid section, or from_page out of range.
    """
    if section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    pool = await get_pool()
    col = f"{section}_pages"

    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT {col} FROM metadata WHERE id = %(id)s", {"id": entry_id}
        )
        meta_row = await cur.fetchone()
        if meta_row is None:
            return {"error": f"Entry {entry_id} not found"}

        total_pages = meta_row[col]

        if total_pages == 0:
            return {
                "entry_id": entry_id,
                "section": section,
                "from_page": 0,
                "to_page": 0,
                "total_pages": 0,
                "pages": [],
            }

        if from_page < 1:
            from_page = 1
        if to_page > total_pages:
            to_page = total_pages
        if from_page > total_pages:
            return {"error": f"from_page {from_page} out of range (1-{total_pages})"}

        # Cap at 10 pages per request.
        if to_page - from_page + 1 > 10:
            to_page = from_page + 9

        cur = await conn.execute(
            f"""SELECT page, content FROM {section}
                WHERE id = %(id)s AND page >= %(from)s AND page <= %(to)s
                ORDER BY page""",
            {"id": entry_id, "from": from_page, "to": to_page},
        )
        rows = await cur.fetchall()

    pages = [{"page_number": row["page"], "content": row["content"]} for row in rows]

    return {
        "entry_id": entry_id,
        "section": section,
        "from_page": from_page,
        "to_page": to_page,
        "total_pages": total_pages,
        "pages": pages,
    }


@mcp.tool()
async def search_content(
    query: str,
    entry_id: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Search for text across the entire library using full-text search.

    Powered by PostgreSQL full-text search. Results are ranked by relevance and
    include snippets with matching terms highlighted between >>> and <<< markers.
    Example snippet: "...the >>>consciousness<<< of the individual..."

    Use this to discover books by topic or to find specific passages within a book.

    Supports natural search syntax:
      - Simple keywords: "consciousness"
      - Exact phrases: '"stream of consciousness"' (wrap in double quotes)
      - Boolean OR: "consciousness OR awareness"
      - Negation: "-freud" excludes results containing that word

    Args:
        query: Search query string.
        entry_id: Optional — limit search to a specific book by its ID.
        section: Optional — limit to a specific section: shortsummary, summary, or fulltext.
        limit: Max results to return (default 20, max 50).

    Returns:
        Dictionary with:
        - 'results': list of {entry_id, title, section, page, snippet}
          Each result points to a specific page you can read with get_page.
        - 'total_results': number of results returned (capped at limit).
    """
    if section and section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    pool = await get_pool()
    limit = min(limit, 50)

    where_parts = ["cf.tsv @@ websearch_to_tsquery('english', %(q)s)"]
    params: dict = {"q": query, "limit": limit}

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
        {
            "entry_id": row["id"],
            "title": row["title"],
            "section": row["section"],
            "page": row["page"],
            "snippet": row["snippet"],
        }
        for row in rows
    ]

    return {"results": results, "total_results": len(results)}


@mcp.tool
async def semantic_search(
    query: str,
    entry_id: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search for conceptually related content using semantic vector search.

    Unlike search_content (which matches exact words/phrases via full-text search),
    this tool finds passages that are semantically similar to your query — even if
    they don't contain the exact search terms. Powered by pgvector embeddings of
    fulltext content.

    Examples of when to use semantic_search instead of search_content:
      - "books about the meaning of life" (conceptual, no exact keywords)
      - "themes of isolation and loneliness" (thematic search)
      - "philosophical arguments about free will" (finds related ideas)

    Each result points to a specific fulltext page you can read with get_page or get_pages.

    Args:
        query: Natural language search query describing what you're looking for.
        entry_id: Optional — limit search to a specific book by its ID.
        section: Optional — currently only fulltext is indexed for semantic search.
        limit: Max results to return (default 10, max 50).

    Returns:
        Dictionary with:
        - 'results': list of {entry_id, title, author, section, page_number,
          chunk_index, snippet} — each result points to a readable page.
        - 'total_results': number of results returned.
    """
    if section and section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    limit = min(limit, 50)
    store = await get_pg_store()

    if entry_id:
        namespace = (*CHUNKS_NAMESPACE, entry_id)
    else:
        namespace = CHUNKS_NAMESPACE

    filter_dict = {}
    if section:
        filter_dict["section"] = section

    try:
        results = await store.asearch(
            namespace,
            query=query,
            limit=limit,
            filter=filter_dict if filter_dict else None,
        )
    except Exception as e:
        return {"error": f"Semantic search failed: {str(e)}"}

    search_results = []
    for item in results:
        data = item.value
        search_results.append({
            "entry_id": data.get("entry_id", ""),
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "section": data.get("section", ""),
            "page_number": data.get("page_number", 0),
            "chunk_index": data.get("chunk_index", 0),
            "snippet": data.get("text", "")[:300],
        })

    return {
        "results": search_results,
        "total_results": len(search_results),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8000, host="0.0.0.0")
