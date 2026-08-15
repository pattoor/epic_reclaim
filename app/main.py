from __future__ import annotations

import importlib.util
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import Settings
from .database import Database
from .integrations.auth_browser import PlaywrightAuthBrowser
from .integrations.remote_screen import NoVNCProvider
from .logging_config import configure_logging
from .repositories import AccountsRepository
from .services.account_service import AccountService
from .services.auth_service import AuthService

logger = logging.getLogger(__name__)


def _playwright_status() -> str:
    return "available" if importlib.util.find_spec("playwright") else "unavailable"


def create_app(
    overrides: dict[str, str] | None = None,
    screen=None,
) -> FastAPI:
    settings = Settings.from_env(overrides)
    database = Database(settings.database_path)
    if screen is None:
        screen = NoVNCProvider()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        settings.ensure_directories()
        database.initialize()
        account_repository = AccountsRepository()
        app.state.database = database
        app.state.settings = settings
        app.state.account_service = AccountService(account_repository)
        app.state.auth_service = AuthService(
            database=database,
            repository=account_repository,
            browser=PlaywrightAuthBrowser(),
            screen=screen,
            sessions_path=settings.sessions_path,
        )
        logger.info("application_started", extra={"context": {"app": "epic_reclaim"}})
        yield
        app.state.auth_service.close_all()
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
            "remote_screen": "available" if screen.available() else "unavailable",
        }

    app.include_router(router)

    static_path = Path(__file__).parent / "static"
    static_path.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(static_path / "index.html")

    return app


app = create_app()
