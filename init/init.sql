-- Enable pgvector extension (required by LangGraph store for semantic search)
CREATE EXTENSION IF NOT EXISTS vector;

-- Library schema

CREATE TABLE IF NOT EXISTS metadata (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    publication_year INTEGER,
    genre TEXT,
    custom_tags TEXT,
    shortsummary_pages INTEGER DEFAULT 0,
    summary_pages INTEGER DEFAULT 0,
    fulltext_pages INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shortsummary (
    id TEXT NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (id, page)
);

CREATE TABLE IF NOT EXISTS summary (
    id TEXT NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (id, page)
);

CREATE TABLE IF NOT EXISTS fulltext (
    id TEXT NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (id, page)
);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    page INTEGER NOT NULL,
    heading TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS content_fts (
    id TEXT NOT NULL REFERENCES metadata(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    page INTEGER NOT NULL,
    content TEXT NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    PRIMARY KEY (id, section, page)
);

CREATE INDEX IF NOT EXISTS idx_metadata_title ON metadata(title);
CREATE INDEX IF NOT EXISTS idx_metadata_author ON metadata(author);
CREATE INDEX IF NOT EXISTS idx_metadata_genre ON metadata(genre);
CREATE INDEX IF NOT EXISTS idx_metadata_year ON metadata(publication_year);
CREATE INDEX IF NOT EXISTS idx_chapters_id ON chapters(id);
CREATE INDEX IF NOT EXISTS idx_content_fts_tsv ON content_fts USING GIN(tsv);

-- Note: LangGraph's AsyncPostgresStore creates its own tables automatically
-- via store.setup(). No custom table definitions needed for semantic search.
