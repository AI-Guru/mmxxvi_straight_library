from typing import List, Optional

from pydantic import BaseModel, Field


class EntryMetadata(BaseModel):
    id: str
    title: str
    author: str
    publication_year: Optional[int] = None
    genre: Optional[str] = None
    custom_tags: List[str] = Field(default_factory=list)
    shortsummary_pages: int
    summary_pages: int
    fulltext_pages: int


class EntryListResponse(BaseModel):
    entries: List[EntryMetadata]
    total: int
    skip: int
    limit: int


class PageResponse(BaseModel):
    entry_id: str
    section: str
    page_number: int
    total_pages: int
    content: str


class UploadResponse(BaseModel):
    status: str
    entry_id: str
    title: str
    message: str


class DeleteResponse(BaseModel):
    status: str
    entry_id: str
    message: str


class SearchResult(BaseModel):
    entry_id: str
    title: str
    section: str
    page: int
    snippet: str


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total_results: int
    query: str


class StatusResponse(BaseModel):
    status: str
    version: str = "1.0.0"
    total_entries: int
