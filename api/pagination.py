from typing import Tuple


def paginate_content(content: str, page_max_chars: int) -> list[str]:
    """
    Split content into pages by paragraph blocks.

    Blocks are separated by empty lines (double newline).
    Blocks are aggregated into pages until hitting page_max_chars.
    """
    if not content or not content.strip():
        return []

    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
    if not blocks:
        return []

    pages = []
    current_page_blocks = []
    current_char_count = 0

    for block in blocks:
        block_len = len(block)
        if current_char_count + block_len > page_max_chars and current_page_blocks:
            pages.append("\n\n".join(current_page_blocks))
            current_page_blocks = [block]
            current_char_count = block_len
        else:
            current_page_blocks.append(block)
            current_char_count += block_len

    if current_page_blocks:
        pages.append("\n\n".join(current_page_blocks))

    return pages


def count_pages(content: str, page_max_chars: int) -> int:
    """Count total pages for a content section."""
    return len(paginate_content(content, page_max_chars))


def get_page(content: str, page_number: int, page_max_chars: int) -> Tuple[str, int]:
    """
    Get a specific page of content.

    Args:
        content: Full text content.
        page_number: 1-based page number.
        page_max_chars: Maximum characters per page.

    Returns:
        Tuple of (page_content, total_pages).

    Raises:
        ValueError: If page_number is out of range.
    """
    pages = paginate_content(content, page_max_chars)
    total_pages = len(pages)

    if total_pages == 0:
        return ("", 0)

    if page_number < 1 or page_number > total_pages:
        raise ValueError(f"Page {page_number} out of range (1-{total_pages})")

    return (pages[page_number - 1], total_pages)
