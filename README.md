# Straight Library

![Straight Library](straightlibrary.png)

A library browser exposing book metadata, summaries, and full texts via API, MCP, and Web UI. Content is pre-paginated in SQLite for fast retrieval.

## Architecture

```
prepare_library.py  ->  _libraryentry.md files
                              |
               upload_library.py ---> POST /api/upload ---> SQLite
               Web UI (Upload)  ---> POST /api/upload ---> SQLite
                              |
               API / MCP / Web UI  <--- read from SQLite
```

- **API** (port 9821): FastAPI serving REST endpoints and the Web UI
- **MCP** (port 9823): FastMCP server with `list_entries` and `get_page` tools
- **SQLite**: Persistent bind-mounted database (`library.db`)

## Quick Start

```bash
# 1. Prepare library entry files from source data
python prepare_library.py

# 2. Start services
docker compose up --build -d

# 3. Upload all entries via CLI
pip install requests
python upload_library.py

# 4. Open the Web UI
open http://localhost:9821
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload a `_libraryentry.md` file |
| `GET` | `/api/entries` | List entries (paginated, filterable) |
| `GET` | `/api/entries/{id}/page` | Get a page of content |
| `DELETE` | `/api/entries/{id}` | Delete an entry |
| `GET` | `/api/status` | Health check |

### Filters for `GET /api/entries`

`title`, `author`, `genre`, `tag` (substring match), `year_min`, `year_max`, `skip`, `limit`

### Query params for `GET /api/entries/{id}/page`

`section` (shortsummary, summary, fulltext), `page` (1-based)

## MCP Tools

- **`list_entries`** — Browse and filter the library catalog
- **`get_page`** — Read a specific page of a section

Connect via streamable-http at `http://localhost:9823`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PAGE_MAX_CHARS` | `4000` | Max characters per page |
| `API_PORT` | `9821` | API service port |
| `MCP_PORT` | `9823` | MCP service port |

Copy `.env.example` to `.env` to customize.

## Library Entry Format

Each `_libraryentry.md` file has 4 sections separated by `---`:

```
---
title: Book Title
author: Author Name
publication_year: 2024
genre: Fiction
custom_tags:
- tag1
- tag2
---
Short summary content...
---
Detailed summary content...
---
Full text content...
```

Pages are pre-split at upload time by aggregating paragraph blocks up to `PAGE_MAX_CHARS`.
