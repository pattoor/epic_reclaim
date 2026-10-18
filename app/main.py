"""Web mode entrypoint: FastAPI app serving the API + optional dashboard and
owning the scheduler lifecycle. The console CLI uses the same services via
`app.cli`. Run with: `python -m app.main` under uvicorn or import `create_app`
in tests.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .bootstrap import (
    Runtime,
    build_runtime,
    database_ok,
    playwright_status,
)
from .config import Settings

logger = logging.getLogger(__name__)


def create_app(
    overrides: dict[str, str] | None = None,
    screen=None,
    auth_browser=None,
    workflow_adapter=None,
    delay_between_actions=None,
    clock=None,
):
    """Web mode: FastAPI app with scheduler; the console uses services directly."""
    return _fastapi_from_runtime(
        build_runtime(
            Settings.from_env(overrides),
            screen=screen,
            auth_browser=auth_browser,
            workflow_adapter=workflow_adapter,
            delay_between_actions=delay_between_actions,
            with_scheduler=True,
            clock=clock,
        )
    )


def _fastapi_from_runtime(runtime: Runtime) -> FastAPI:
    runtime.database.initialize()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        scheduler = runtime.scheduler
        state = fastapi_app.state
        state.settings = runtime.settings
        state.database = runtime.database
        state.account_service = runtime.account_service
        state.auth_service = runtime.auth_service
        state.settings_service = runtime.settings_service
        state.notifier = runtime.notifier
        state.workflow = runtime.workflow
        state.accounts_repository = runtime.accounts_repository
        state.games_repository = runtime.games_repository
        state.claims_repository = runtime.claims_repository
        state.attempts_repository = runtime.attempts_repository
        state.runs_repository = runtime.runs_repository
        state.events_repository = runtime.events_repository
        state.screen = runtime.screen
        state.scheduler = runtime.scheduler
        state.playwright_status = playwright_status()
        await scheduler.start()
        logger.info("application_started", extra={"context": {"app": "epic_reclaim"}})
        try:
            yield
        finally:
            await scheduler.stop()
            runtime.auth_service.close_all()
            logger.info("application_stopped", extra={"context": {"app": "epic_reclaim"}})

    app = FastAPI(title="Epic Reclaim", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        database_status = "ok" if database_ok(runtime.database) else "error"
        diagnostics = runtime.screen.diagnostics()
        tools = diagnostics.get("tools", {})
        local_headed = diagnostics.get("mode") == "local-headed"
        tools_ok = (all(tools.values()) if tools else local_headed)
        return {
            "status": "ok" if database_status == "ok" else "error",
            "database": database_status,
            "playwright": playwright_status(),
            "remote_screen": "available" if runtime.screen.available() else "unavailable",
            "remote_screen_diagnostics": {
                "tools_present": bool(tools_ok),
                "novnc_web_dir_exists": bool(
                    diagnostics.get("novnc_web_dir_exists", True)
                ),
                "last_error": diagnostics.get("last_error"),
            },
            "scheduler_next_run_at": getattr(runtime.scheduler, "next_run_at", None)
            if runtime.scheduler is not None
            else None,
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
