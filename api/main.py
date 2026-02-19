from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from routers import library_router, upload_router
from models.schemas import StatusResponse
from database import get_db, init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Library API starting up...")
    init_db()
    print("SQLite database initialized")
    yield
    print("Library API shutting down...")
    close_db()


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

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/status", response_model=StatusResponse, tags=["health"])
async def health_check():
    db = get_db()
    row = db.execute("SELECT COUNT(*) as cnt FROM metadata").fetchone()
    return StatusResponse(
        status="healthy",
        version="1.0.0",
        total_entries=row["cnt"],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
