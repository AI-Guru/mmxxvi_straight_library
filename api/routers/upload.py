import asyncio
import hashlib
import json
import re

import yaml
from fastapi import APIRouter, HTTPException, UploadFile, File
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from database import get_pool
from pagination import paginate_content
from store import get_store, CHUNKS_NAMESPACE
from models.schemas import UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])

VALID_SECTIONS = ("shortsummary", "summary", "fulltext")


def parse_library_entry(content: str) -> dict:
    """Parse a _libraryentry.md file into its 4 sections."""
    lines = content.split("\n")
    separator_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]

    if len(separator_indices) != 4:
        raise ValueError(
            f"Expected 4 '---' separators, found {len(separator_indices)}"
        )

    yaml_block = "\n".join(lines[separator_indices[0] + 1 : separator_indices[1]])
    shortsummary = "\n".join(
        lines[separator_indices[1] + 1 : separator_indices[2]]
    ).strip()
    summary = "\n".join(
        lines[separator_indices[2] + 1 : separator_indices[3]]
    ).strip()
    fulltext = "\n".join(lines[separator_indices[3] + 1 :]).strip()

    metadata = yaml.safe_load(yaml_block)

    return {
        "metadata": metadata,
        "shortsummary": shortsummary,
        "summary": summary,
        "fulltext": fulltext,
    }


def extract_chapters(pages: list[str], section: str) -> list[dict]:
    """Extract chapter/section headings from paginated content.

    Detects markdown headings (# Heading) and returns their page number,
    heading text, and heading level.
    """
    chapters = []
    for page_num, page_content in enumerate(pages, 1):
        for line in page_content.split("\n"):
            line_stripped = line.strip()
            match = re.match(r"^(#{1,4})\s+(.+)", line_stripped)
            if match:
                level = len(match.group(1))
                heading = match.group(2).strip()
                # Skip very short or link-only headings
                if len(heading) < 2:
                    continue
                # Strip markdown bold/italic
                heading = re.sub(r"\*+", "", heading).strip()
                if heading:
                    chapters.append({
                        "section": section,
                        "page": page_num,
                        "heading": heading,
                        "level": level,
                    })
    return chapters


@router.post("/upload", response_model=UploadResponse)
async def upload_entry(file: UploadFile = File(...)):
    """Upload a _libraryentry.md file to the library."""
    content_bytes = await file.read()
    content = content_bytes.decode("utf-8").replace("\x00", "")

    try:
        parsed = parse_library_entry(content)
    except (ValueError, yaml.YAMLError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid library entry: {e}")

    entry_id = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    meta = parsed["metadata"]

    ss_pages = paginate_content(parsed["shortsummary"], settings.page_max_chars)
    s_pages = paginate_content(parsed["summary"], settings.page_max_chars)
    ft_pages = paginate_content(parsed["fulltext"], settings.page_max_chars)

    # Extract chapter markers from all sections.
    all_chapters = []
    all_chapters.extend(extract_chapters(ss_pages, "shortsummary"))
    all_chapters.extend(extract_chapters(s_pages, "summary"))
    all_chapters.extend(extract_chapters(ft_pages, "fulltext"))

    pool = await get_pool()

    async with pool.connection() as conn:
        async with conn.transaction():
            # Delete old data (CASCADE handles content tables, chapters, fts).
            await conn.execute(
                "DELETE FROM metadata WHERE id = %(id)s", {"id": entry_id}
            )

            await conn.execute(
                """INSERT INTO metadata
                   (id, title, author, publication_year, genre, custom_tags,
                    shortsummary_pages, summary_pages, fulltext_pages)
                   VALUES (%(id)s, %(title)s, %(author)s, %(year)s, %(genre)s,
                           %(tags)s, %(ss)s, %(s)s, %(ft)s)""",
                {
                    "id": entry_id,
                    "title": meta["title"],
                    "author": meta["author"],
                    "year": meta.get("publication_year"),
                    "genre": meta.get("genre"),
                    "tags": json.dumps(meta.get("custom_tags", [])),
                    "ss": len(ss_pages),
                    "s": len(s_pages),
                    "ft": len(ft_pages),
                },
            )

            for page_num, page_content in enumerate(ss_pages, 1):
                await conn.execute(
                    "INSERT INTO shortsummary (id, page, content) VALUES (%(id)s, %(page)s, %(content)s)",
                    {"id": entry_id, "page": page_num, "content": page_content},
                )
            for page_num, page_content in enumerate(s_pages, 1):
                await conn.execute(
                    "INSERT INTO summary (id, page, content) VALUES (%(id)s, %(page)s, %(content)s)",
                    {"id": entry_id, "page": page_num, "content": page_content},
                )
            for page_num, page_content in enumerate(ft_pages, 1):
                await conn.execute(
                    "INSERT INTO fulltext (id, page, content) VALUES (%(id)s, %(page)s, %(content)s)",
                    {"id": entry_id, "page": page_num, "content": page_content},
                )

            for ch in all_chapters:
                await conn.execute(
                    "INSERT INTO chapters (id, section, page, heading, level) VALUES (%(id)s, %(section)s, %(page)s, %(heading)s, %(level)s)",
                    {"id": entry_id, "section": ch["section"], "page": ch["page"], "heading": ch["heading"], "level": ch["level"]},
                )

            # Index all pages for full-text search.
            for section_name, pages in [("shortsummary", ss_pages), ("summary", s_pages), ("fulltext", ft_pages)]:
                for page_num, page_content in enumerate(pages, 1):
                    await conn.execute(
                        "INSERT INTO content_fts (id, section, page, content) VALUES (%(id)s, %(section)s, %(page)s, %(content)s)",
                        {"id": entry_id, "section": section_name, "page": page_num, "content": page_content},
                    )

    # Chunk and embed fulltext pages in pgvector for semantic search.
    try:
        store = await get_store()
        chunk_namespace = (*CHUNKS_NAMESPACE, entry_id)

        # Delete old embeddings (idempotent re-upload).
        old_items = await store.asearch(chunk_namespace, query=None, limit=10000)
        for old_item in old_items:
            await store.adelete(chunk_namespace, old_item.key)

        # Chunk fulltext pages into ~1000-char pieces with overlap.
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        async def store_chunk(
            page_num: int, chunk_idx: int, chunk_text: str
        ) -> None:
            chunk_key = f"p{page_num}_c{chunk_idx}"
            await store.aput(
                chunk_namespace,
                chunk_key,
                {
                    "text": chunk_text,
                    "entry_id": entry_id,
                    "title": meta["title"],
                    "author": meta["author"],
                    "section": "fulltext",
                    "page_number": page_num,
                    "chunk_index": chunk_idx,
                },
            )

        tasks = []
        global_chunk_idx = 0
        for page_num, page_content in enumerate(ft_pages, 1):
            chunks = text_splitter.split_text(page_content)
            for chunk_text in chunks:
                tasks.append(store_chunk(page_num, global_chunk_idx, chunk_text))
                global_chunk_idx += 1

        if tasks:
            await asyncio.gather(*tasks)
    except Exception as e:
        # PostgreSQL data is already committed — log but don't fail.
        print(f"Warning: pgvector embedding failed for {entry_id}: {e}")

    return UploadResponse(
        status="ok",
        entry_id=entry_id,
        title=meta["title"],
        message=f"Uploaded '{meta['title']}' by {meta['author']}",
    )
