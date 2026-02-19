import hashlib
import json
import re

import yaml
from fastapi import APIRouter, HTTPException, UploadFile, File

from config import settings
from database import get_db
from pagination import paginate_content
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
    content = content_bytes.decode("utf-8")

    try:
        parsed = parse_library_entry(content)
    except (ValueError, yaml.YAMLError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid library entry: {e}")

    entry_id = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    meta = parsed["metadata"]

    ss_pages = paginate_content(parsed["shortsummary"], settings.page_max_chars)
    s_pages = paginate_content(parsed["summary"], settings.page_max_chars)
    ft_pages = paginate_content(parsed["fulltext"], settings.page_max_chars)

    db = get_db()

    # Extract chapter markers from all sections.
    all_chapters = []
    all_chapters.extend(extract_chapters(ss_pages, "shortsummary"))
    all_chapters.extend(extract_chapters(s_pages, "summary"))
    all_chapters.extend(extract_chapters(ft_pages, "fulltext"))

    # Delete old data for this entry (idempotent re-upload).
    for table in ("chapters", "shortsummary", "summary", "fulltext", "metadata"):
        db.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))

    db.execute(
        """INSERT INTO metadata
           (id, title, author, publication_year, genre, custom_tags,
            shortsummary_pages, summary_pages, fulltext_pages)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry_id,
            meta["title"],
            meta["author"],
            meta.get("publication_year"),
            meta.get("genre"),
            json.dumps(meta.get("custom_tags", [])),
            len(ss_pages),
            len(s_pages),
            len(ft_pages),
        ),
    )

    for page_num, page_content in enumerate(ss_pages, 1):
        db.execute(
            "INSERT INTO shortsummary (id, page, content) VALUES (?, ?, ?)",
            (entry_id, page_num, page_content),
        )
    for page_num, page_content in enumerate(s_pages, 1):
        db.execute(
            "INSERT INTO summary (id, page, content) VALUES (?, ?, ?)",
            (entry_id, page_num, page_content),
        )
    for page_num, page_content in enumerate(ft_pages, 1):
        db.execute(
            "INSERT INTO fulltext (id, page, content) VALUES (?, ?, ?)",
            (entry_id, page_num, page_content),
        )

    for ch in all_chapters:
        db.execute(
            "INSERT INTO chapters (id, section, page, heading, level) VALUES (?, ?, ?, ?, ?)",
            (entry_id, ch["section"], ch["page"], ch["heading"], ch["level"]),
        )

    db.commit()

    return UploadResponse(
        status="ok",
        entry_id=entry_id,
        title=meta["title"],
        message=f"Uploaded '{meta['title']}' by {meta['author']}",
    )
