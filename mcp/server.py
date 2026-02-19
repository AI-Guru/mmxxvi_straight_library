import json
import os
import sqlite3
from typing import Optional

from fastmcp import FastMCP

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/app/data/library.db")

VALID_SECTIONS = ("shortsummary", "summary", "fulltext")

mcp = FastMCP(
    "Straight Library MCP Server",
    instructions="""This server provides access to a digital library of ~400 books.
Each book has three content sections at different detail levels:
  - shortsummary: A brief overview (typically 1 page, ~650 tokens)
  - summary: A detailed summary (typically 5-10 pages, ~1000 tokens each)
  - fulltext: The complete text (tens to hundreds of pages, ~1000 tokens each)

Recommended workflow for reading a book:
  1. Use list_entries to find the book you want (search by title, author, genre, etc.)
  2. Use get_entry to see its metadata and table of contents (chapter headings with page numbers)
  3. Start with the shortsummary to get an overview
  4. Use the summary for more detail, or jump to specific fulltext chapters using the page numbers from get_entry
  5. Use get_pages to read multiple consecutive pages efficiently
  6. Use search_content to find specific topics or passages within a book""",
)

_connection = None


def get_db() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(
            f"file:{DATABASE_PATH}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        _connection.row_factory = sqlite3.Row
    return _connection


@mcp.tool()
def list_entries(
    skip: int = 0,
    limit: int = 20,
    title: Optional[str] = None,
    author: Optional[str] = None,
    genre: Optional[str] = None,
    tag: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> dict:
    """Browse and search the library catalog.

    Returns a paginated list of books with metadata and page counts for each
    section. Use this to discover what's available, then call get_entry for
    details on a specific book.

    Args:
        skip: Number of entries to skip for pagination (default 0).
        limit: Maximum entries to return (default 20, max 100).
        title: Filter by title (case-insensitive substring match).
        author: Filter by author (case-insensitive substring match).
        genre: Filter by genre (case-insensitive substring match).
        tag: Filter by custom tag (case-insensitive substring match).
        year_min: Minimum publication year (inclusive).
        year_max: Maximum publication year (inclusive).

    Returns:
        Dictionary with 'entries' list (each has id, title, author,
        publication_year, genre, custom_tags, and page counts per section),
        'total' matching count, 'skip', and 'limit'.
    """
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
    limit = min(limit, 100)

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
def get_entry(entry_id: str) -> dict:
    """Get detailed information about a specific book, including its table of contents.

    Returns the book's metadata and chapter headings with page numbers for each
    section. Use the chapter list to navigate directly to specific parts of the
    book with get_page or get_pages.

    Args:
        entry_id: The entry ID (16-char hex string from list_entries).

    Returns:
        Dictionary with 'metadata' (id, title, author, etc.) and 'chapters'
        list (each has section, page, heading, level). Chapters are ordered
        by section then page number.
    """
    db = get_db()

    meta_row = db.execute(
        """SELECT id, title, author, publication_year, genre, custom_tags,
                  shortsummary_pages, summary_pages, fulltext_pages
           FROM metadata WHERE id = ?""",
        (entry_id,),
    ).fetchone()
    if meta_row is None:
        return {"error": f"Entry {entry_id} not found"}

    chapters = []
    ch_rows = db.execute(
        "SELECT section, page, heading, level FROM chapters WHERE id = ? ORDER BY section, page",
        (entry_id,),
    ).fetchall()
    for ch in ch_rows:
        chapters.append(
            {
                "section": ch["section"],
                "page": ch["page"],
                "heading": ch["heading"],
                "level": ch["level"],
            }
        )

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
def get_page(
    entry_id: str,
    section: str,
    page: int = 1,
) -> dict:
    """Read a single page of a book section.

    Each page contains ~1000 tokens (~4000 characters) of text. Use get_pages
    to read multiple consecutive pages in one call.

    Args:
        entry_id: The entry ID (16-char hex string).
        section: Content section — one of: shortsummary, summary, fulltext.
        page: Page number (1-based, default 1).

    Returns:
        Dictionary with entry_id, section, page_number, total_pages, and content.
    """
    if section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    db = get_db()

    meta_row = db.execute(
        f"SELECT {section}_pages FROM metadata WHERE id = ?", (entry_id,)
    ).fetchone()
    if meta_row is None:
        return {"error": f"Entry {entry_id} not found"}

    total_pages = meta_row[f"{section}_pages"]

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

    row = db.execute(
        f"SELECT content FROM {section} WHERE id = ? AND page = ?",
        (entry_id, page),
    ).fetchone()

    return {
        "entry_id": entry_id,
        "section": section,
        "page_number": page,
        "total_pages": total_pages,
        "content": row["content"] if row else "",
    }


@mcp.tool()
def get_pages(
    entry_id: str,
    section: str,
    from_page: int = 1,
    to_page: int = 5,
) -> dict:
    """Read multiple consecutive pages of a book section in one call.

    Fetches up to 10 pages at once, reducing round-trips when reading longer
    passages. Each page is ~1000 tokens, so 10 pages ≈ 10,000 tokens.

    Args:
        entry_id: The entry ID (16-char hex string).
        section: Content section — one of: shortsummary, summary, fulltext.
        from_page: First page to read (1-based, default 1).
        to_page: Last page to read (inclusive, default 5, max range: 10 pages).

    Returns:
        Dictionary with entry_id, section, from_page, to_page, total_pages,
        and 'pages' list (each has page_number and content).
    """
    if section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    db = get_db()

    meta_row = db.execute(
        f"SELECT {section}_pages FROM metadata WHERE id = ?", (entry_id,)
    ).fetchone()
    if meta_row is None:
        return {"error": f"Entry {entry_id} not found"}

    total_pages = meta_row[f"{section}_pages"]

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

    rows = db.execute(
        f"""SELECT page, content FROM {section}
            WHERE id = ? AND page >= ? AND page <= ?
            ORDER BY page""",
        (entry_id, from_page, to_page),
    ).fetchall()

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
def search_content(
    query: str,
    entry_id: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Search for text across the entire library using full-text search.

    Powered by SQLite FTS5. Results are ranked by relevance with highlighted
    snippets (matches wrapped in >>> and <<<).

    Supports FTS5 query syntax:
      - Simple keywords: "consciousness"
      - Phrases: '"stream of consciousness"'
      - Boolean: "consciousness AND philosophy"
      - Prefix: "conscious*"
      - Negation: "consciousness NOT freud"

    Args:
        query: Search query (FTS5 syntax supported).
        entry_id: Optional — limit search to a specific book.
        section: Optional — limit to shortsummary, summary, or fulltext.
        limit: Max results to return (default 20, max 50).

    Returns:
        Dictionary with 'results' list (each has entry_id, title, section,
        page, and snippet with highlights) and 'total_results' count.
    """
    if section and section not in VALID_SECTIONS:
        return {"error": f"Section must be one of: {', '.join(VALID_SECTIONS)}"}

    db = get_db()
    limit = min(limit, 50)

    where_parts = ["content_fts MATCH ?"]
    params = [query]

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


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8000, host="0.0.0.0")
