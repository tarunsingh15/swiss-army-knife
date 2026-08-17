"""FastAPI application factory for the email parser web UI."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create shared resources for the app lifetime."""
    # Parsing is CPU-heavy; keep the event loop free for SSE and uploads.
    app.state.process_pool = ProcessPoolExecutor(max_workers=2)
    yield
    app.state.process_pool.shutdown(wait=False)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="Email Parser", lifespan=lifespan)
    from web.routes import router

    app.include_router(router)
    static = Path(__file__).parent / "static"
    if static.exists():
        app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app()
