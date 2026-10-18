"""Shared runtime bootstrap for the web mode and the console CLI.

Builds the database, repositories, services, workflow and optional scheduler
exactly once so CLI and web never duplicate business logic (docs/DECISIONS.md
D2). Injectables (screen, browser, adapter, clock) exist for tests and fakes.
"""

from __future__ import annotations

import importlib.util
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Settings
from .database import Database
from .integrations.auth_browser import PlaywrightAuthBrowser
from .integrations.epic_playwright import PlaywrightEpicAdapter
from .integrations.remote_screen import (
    RemoteScreen,
    create_default_screen,
)
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
from .services.locks import FileRunLock, MultiRunLock
from .services.run_workflow import RunLock, RunWorkflow
from .services.settings_service import EffectiveSettings, SettingsService


def playwright_status() -> str:
    return "available" if importlib.util.find_spec("playwright") else "unavailable"


def _random_delay_provider(settings_service: SettingsService, database: Database):
    def delay() -> None:
        with database.connect() as connection:
            effective = settings_service.load(connection)
        time.sleep(random.uniform(effective.claim_delay_min_seconds, effective.claim_delay_max_seconds))

    return delay


@dataclass
class Runtime:
    settings: Settings
    database: Database
    accounts_repository: AccountsRepository
    games_repository: GamesRepository
    claims_repository: ClaimsRepository
    attempts_repository: ClaimAttemptsRepository
    runs_repository: RunsRepository
    events_repository: RunEventsRepository
    settings_repository: SettingsRepository
    account_service: AccountService
    auth_service: AuthService
    settings_service: SettingsService
    notifier: TelegramNotifier
    workflow: RunWorkflow
    scheduler: Scheduler | None = None
    screen: RemoteScreen | None = None
    claims_view: object | None = None
    scheduler_started: bool = field(default=False)


def build_runtime(
    settings: Settings,
    *,
    screen: RemoteScreen | None = None,
    auth_browser=None,
    workflow_adapter=None,
    delay_between_actions=None,
    with_scheduler: bool = False,
    clock=None,
    configure_logs: bool = True,
) -> Runtime:
    if configure_logs:
        configure_logging()
    settings.ensure_directories()
    if screen is None:
        screen = create_default_screen(settings)

    database = Database(settings.database_path)
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
        browser=auth_browser or PlaywrightAuthBrowser(),
        screen=screen,
        sessions_path=settings.sessions_path,
    )
    settings_service = SettingsService(settings, settings_repo)
    notifier = TelegramNotifier(settings_service, database)

    def settings_provider(connection) -> EffectiveSettings:
        return settings_service.load(connection)

    workflow = RunWorkflow(
        database=database,
        adapter=workflow_adapter or PlaywrightEpicAdapter(settings.sessions_path, locale=settings.locale),
        accounts_repository=accounts_repo,
        games_repository=games_repo,
        claims_repository=claims_repo,
        attempts_repository=attempts_repo,
        runs_repository=runs_repo,
        events_repository=events_repo,
        lock=MultiRunLock(RunLock(), FileRunLock(file_lock_path(settings))),
        settings_provider=settings_provider,
        delay_between_actions=delay_between_actions
        if delay_between_actions is not None
        else _random_delay_provider(settings_service, database),
        notifier=notifier,
        restore_hook=auth_service.silent_restore,
    )

    scheduler = (
        Scheduler(workflow, settings_service, database, clock=clock)
        if with_scheduler
        else None
    )

    return Runtime(
        settings=settings,
        database=database,
        accounts_repository=accounts_repo,
        games_repository=games_repo,
        claims_repository=claims_repo,
        attempts_repository=attempts_repo,
        runs_repository=runs_repo,
        events_repository=events_repo,
        settings_repository=settings_repo,
        account_service=account_service,
        auth_service=auth_service,
        settings_service=settings_service,
        notifier=notifier,
        workflow=workflow,
        scheduler=scheduler,
        screen=screen,
    )


def file_lock_path(settings: Settings):
    from pathlib import Path

    path = Path(settings.state_path)
    path.mkdir(parents=True, exist_ok=True)
    return path / "run.lock"


def database_ok(database: Database) -> bool:
    try:
        return database.check()
    except Exception:
        return False
