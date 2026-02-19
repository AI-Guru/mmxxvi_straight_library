import sqlite3

from config import settings

_connection = None


def get_db() -> sqlite3.Connection:
    """Get or create the SQLite connection."""
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(
            settings.database_path,
            check_same_thread=False,
        )
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
    return _connection


def init_db():
    """Create tables and indexes if they don't exist."""
    db = get_db()
    db.executescript("""
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
            id TEXT NOT NULL,
            page INTEGER NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (id, page),
            FOREIGN KEY (id) REFERENCES metadata(id)
        );

        CREATE TABLE IF NOT EXISTS summary (
            id TEXT NOT NULL,
            page INTEGER NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (id, page),
            FOREIGN KEY (id) REFERENCES metadata(id)
        );

        CREATE TABLE IF NOT EXISTS fulltext (
            id TEXT NOT NULL,
            page INTEGER NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (id, page),
            FOREIGN KEY (id) REFERENCES metadata(id)
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id TEXT NOT NULL,
            section TEXT NOT NULL,
            page INTEGER NOT NULL,
            heading TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (id) REFERENCES metadata(id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
            id UNINDEXED,
            section UNINDEXED,
            page UNINDEXED,
            content
        );

        CREATE INDEX IF NOT EXISTS idx_metadata_title ON metadata(title);
        CREATE INDEX IF NOT EXISTS idx_metadata_author ON metadata(author);
        CREATE INDEX IF NOT EXISTS idx_metadata_genre ON metadata(genre);
        CREATE INDEX IF NOT EXISTS idx_metadata_year ON metadata(publication_year);
        CREATE INDEX IF NOT EXISTS idx_chapters_id ON chapters(id);
    """)


def close_db():
    """Close the database connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
