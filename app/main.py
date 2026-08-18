from __future__ import annotations

import importlib.util
import logging
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .auth_proxy import AuthProxy
from .config import Settings
from .database import Database
from .integrations.auth_browser import PlaywrightAuthBrowser
from .integrations.epic_playwright import PlaywrightEpicAdapter
from .integrations.remote_screen import NoVNCProvider
from .integrations.telegram import TelegramNotifier
from .logging_config import configure_logging
from .repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
    SettingsRepository,
)
from .scheduler import Scheduler
from .services.account_service import AccountService
from .services.auth_service import AuthService
from .services.run_workflow import RunLock, RunWorkflow
from .services.settings_service import SettingsService

logger = logging.getLogger(__name__)


def _playwright_status() -> str:
    return "available" if importlib.util.find_spec("playwright") else "unavailable"


def create_app(
    overrides: dict[str, str] | None = None,
    screen=None,
    auth_browser=None,
    workflow_adapter=None,
    delay_between_actions=None,
) -> FastAPI:
    settings = Settings.from_env(overrides)
    database = Database(settings.database_path)
    if screen is None:
        screen = NoVNCProvider()
    if auth_browser is None:
        auth_browser = PlaywrightAuthBrowser()
    if workflow_adapter is None:
        workflow_adapter = PlaywrightEpicAdapter(settings.sessions_path)

    accounts_repo = AccountsRepository()
    games_repo = GamesRepository()
    claims_repo = ClaimsRepository()
    attempts_repo = ClaimAttemptsRepository()
    runs_repo = RunsRepository()
    events_repo = RunEventsRepository()
    settings_repo = SettingsRepository()

    account_service = AccountService(accounts_repo, settings.sessions_path)
    auth_service = AuthService(
        database=database,
        repository=accounts_repo,
        browser=auth_browser,
        screen=screen,
        sessions_path=settings.sessions_path,
    )
    settings_service = SettingsService(settings, settings_repo)
    notifier = TelegramNotifier(settings_service, database)

    def settings_provider(connection):
        return settings_service.load(connection)

    if delay_between_actions is None:
        def delay_between_actions():
            with database.connect() as connection:
                effective = settings_service.load(connection)
            time.sleep(
                random.uniform(
                    effective.claim_delay_min_seconds,
                    effective.claim_delay_max_seconds,
                )
            )

    workflow = RunWorkflow(
        database=database,
        adapter=workflow_adapter,
        accounts_repository=accounts_repo,
        games_repository=games_repo,
        claims_repository=claims_repo,
        attempts_repository=attempts_repo,
        runs_repository=runs_repo,
        events_repository=events_repo,
        lock=RunLock(),
        settings_provider=settings_provider,
        delay_between_actions=delay_between_actions,
        notifier=notifier,
    )
    scheduler = Scheduler(workflow, settings_service, database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        settings.ensure_directories()
        database.initialize()
        app.state.database = database
        app.state.settings = settings
        app.state.account_service = account_service
        app.state.auth_service = auth_service
        app.state.settings_service = settings_service
        app.state.notifier = notifier
        app.state.workflow = workflow
        app.state.accounts_repository = accounts_repo
        app.state.games_repository = games_repo
        app.state.claims_repository = claims_repo
        app.state.attempts_repository = attempts_repo
        app.state.runs_repository = runs_repo
        app.state.events_repository = events_repo
        app.state.scheduler = scheduler
        await scheduler.start()
        logger.info("application_started", extra={"context": {"app": "epic_reclaim"}})
        yield
        await scheduler.stop()
        auth_service.close_all()
        await auth_proxy.close()
        logger.info("application_stopped", extra={"context": {"app": "epic_reclaim"}})

    app = FastAPI(title="Epic Reclaim", lifespan=lifespan)

    auth_proxy = AuthProxy(
        auth_service,
        ws_port=getattr(screen, "_ws_port", getattr(screen, "ws_port", 6080)),
    )
    app.include_router(auth_proxy.router())

    @app.get("/health")
    def health() -> dict:
        try:
            database_status = "ok" if database.check() else "error"
        except Exception:
            database_status = "error"
        diagnostics = screen.diagnostics()
        available = diagnostics.get("tools", {})
        tools_ok = all(available.values()) if available else False
        novnc_ok = diagnostics.get("novnc_web_dir_exists", False)
        return {
            "status": "ok" if database_status == "ok" else "error",
            "database": database_status,
            "playwright": _playwright_status(),
            "remote_screen": "available" if screen.available() else "unavailable",
            "remote_screen_diagnostics": {
                "tools_present": tools_ok,
                "novnc_web_dir_exists": novnc_ok,
                "last_error": diagnostics.get("last_error"),
            },
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
