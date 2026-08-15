from __future__ import annotations

import importlib.util
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .database import Database
from .logging_config import configure_logging

logger = logging.getLogger(__name__)


def _playwright_status() -> str:
    return "available" if importlib.util.find_spec("playwright") else "unavailable"


def create_app(overrides: dict[str, str] | None = None) -> FastAPI:
    settings = Settings.from_env(overrides)
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        settings.ensure_directories()
        database.initialize()
        logger.info("application_started", extra={"context": {"app": "epic_reclaim"}})
        app.state.settings = settings
        app.state.database = database
        yield
        logger.info("application_stopped", extra={"context": {"app": "epic_reclaim"}})

    app = FastAPI(title="Epic Reclaim", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            database_status = "ok" if database.check() else "error"
        except Exception:
            database_status = "error"
        return {
            "status": "ok" if database_status == "ok" else "error",
            "database": database_status,
            "playwright": _playwright_status(),
        }

    static_path = Path(__file__).parent / "static"
    static_path.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(static_path / "index.html")

    return app


app = create_app()
