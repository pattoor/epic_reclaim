from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.domain.errors import (
    AccountBlockedError,
    AuthenticationRequiredError,
    EpicError,
    InterventionRequiredError,
    RateLimitError,
    TransientError,
)
from app.domain.models import AccountState, ClaimState, RunState, RunEventType
from app.integrations.epic_adapter import EpicAdapter, GameCandidate, Outcome
from app.repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
)

logger = logging.getLogger(__name__)

Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class RunOutcome:
    run_id: int | None
    status: str
    error: str | None = None
    claimed_count: int = 0
    already_owned_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    games_detected: int = 0
    accounts_processed: int = 0


class RunLock:
    def __init__(self):
        self._locked = False

    def acquire(self) -> bool:
        if self._locked:
            return False
        self._locked = True
        return True

    def release(self) -> None:
        self._locked = False


class RunWorkflow:
    def __init__(
        self,
        database,
        adapter: EpicAdapter,
        accounts_repository: AccountsRepository,
        games_repository: GamesRepository,
        claims_repository: ClaimsRepository,
        attempts_repository: ClaimAttemptsRepository,
        runs_repository: RunsRepository,
        events_repository: RunEventsRepository,
        lock: RunLock,
        settings_provider: Callable[[object], object],
        delay_between_actions: Callable[[], None] | None = None,
        sleeper: Sleeper = time.sleep,
        notifier: Any | None = None,
    ):
        self._database = database
        self._adapter = adapter
        self._accounts = accounts_repository
        self._games = games_repository
        self._claims = claims_repository
        self._attempts = attempts_repository
        self._runs = runs_repository
        self._events = events_repository
        self._lock = lock
        self._settings_provider = settings_provider
        self._delay = delay_between_actions or (lambda: None)
        self._sleeper = sleeper
        self._notifier = notifier

    def run(self, trigger: str) -> RunOutcome:
        if not self._lock.acquire():
            with self._database.connect() as connection:
                active = self._runs.get_active(connection)
            return RunOutcome(
                run_id=active.id if active else None,
                status="conflict",
                error="another run is already in progress",
            )
        try:
            return self._run_locked(trigger)
        finally:
            self._lock.release()

    def start(self, trigger: str) -> RunOutcome:
        """Acquires the lock and launches the run in a background thread."""
        if not self._lock.acquire():
            with self._database.connect() as connection:
                active = self._runs.get_active(connection)
            return RunOutcome(
                run_id=active.id if active else None,
                status="conflict",
                error="another run is already in progress",
            )
        with self._database.connect() as connection:
            run = self._runs.create(connection, trigger)
        thread = threading.Thread(
            target=self._execute, args=(trigger, run.id), daemon=True
        )
        thread.start()
        return RunOutcome(run_id=run.id, status=RunState.RUNNING)

    def _execute(self, trigger: str, run_id: int) -> None:
        try:
            self._run_locked(trigger, run_id=run_id)
        finally:
            self._lock.release()

    def _run_locked(self, trigger: str, run_id: int | None = None) -> RunOutcome:
        with self._database.connect() as connection:
            if run_id is None:
                run = self._runs.create(connection, trigger)
                run_id = run.id
            settings = self._settings_provider(connection)
            self._events.add(connection, run_id, RunEventType.RUN_STARTED)

        max_attempts = settings.max_retry_attempts
        counters = {
            "claimed": 0,
            "already_owned": 0,
            "failed": 0,
            "skipped": 0,
            "accounts_processed": 0,
        }
        games_detected = 0
        error: str | None = None
        final_status = RunState.COMPLETED

        try:
            with self._database.connect() as connection:
                candidates = self._retry_transient(
                    self._adapter.discover_free_games, max_attempts
                )
                games = []
                for candidate in candidates:
                    games.append(
                        self._games.upsert(
                            connection,
                            epic_id=candidate.epic_id,
                            name=candidate.name,
                            url=candidate.url,
                        )
                    )
                games_detected = len(games)
                self._events.add(
                    connection,
                    run_id,
                    RunEventType.GAMES_DETECTED,
                    message=f"{games_detected} games found",
                )

                accounts = self._accounts.list_active(connection)
                for account in accounts:
                    self._events.add(
                        connection,
                        run_id,
                        RunEventType.ACCOUNT_STARTED,
                        account_id=account.id,
                        message=account.display_name,
                    )
                    session = None
                    try:
                        session = self._retry_transient(
                            lambda: self._adapter.open_account_session(account.id),
                            max_attempts,
                        )
                        for game in games:
                            result = self._process_game(
                                connection,
                                run_id,
                                account.id,
                                game,
                                session,
                                max_attempts,
                                counters,
                            )
                            if result == "paused":
                                break
                            if result == "processed":
                                self._delay()
                        counters["accounts_processed"] += 1
                    except (InterventionRequiredError,) as exc:
                        self._pause_account(connection, run_id, account.id, AccountState.NEEDS_INTERVENTION, str(exc), counters)
                    except (AuthenticationRequiredError,) as exc:
                        self._pause_account(connection, run_id, account.id, AccountState.NEEDS_AUTHENTICATION, str(exc), counters)
                    except (RateLimitError, AccountBlockedError) as exc:
                        self._pause_account(connection, run_id, account.id, AccountState.PAUSED, str(exc), counters)
                    except TransientError as exc:
                        logger.warning("run_%s transient failure for account %s: %s", run_id, account.id, exc)
                        counters["failed"] += 1
                    finally:
                        if session is not None:
                            session.close()

        except InterventionRequiredError as exc:
            error = str(exc)
            final_status = RunState.FAILED
        except RateLimitError as exc:
            error = str(exc)
            final_status = RunState.FAILED
        except EpicError as exc:
            error = str(exc)
            final_status = RunState.FAILED
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("run_%s unexpected error", run_id)
            error = str(exc)
            final_status = RunState.FAILED

        if final_status == RunState.COMPLETED and counters["failed"] > 0:
            final_status = RunState.PARTIAL

        with self._database.connect() as connection:
            run = self._runs.finish(
                connection,
                run_id,
                status=final_status,
                games_detected=games_detected,
                accounts_processed=counters["accounts_processed"],
                claimed_count=counters["claimed"],
                already_owned_count=counters["already_owned"],
                failed_count=counters["failed"],
                skipped_count=counters["skipped"],
                error=error,
            )
            self._events.add(
                connection,
                run_id,
                RunEventType.RUN_FINISHED,
                message=f"run finished with status {final_status}",
            )

        outcome = RunOutcome(
            run_id=run_id,
            status=final_status,
            error=error,
            claimed_count=counters["claimed"],
            already_owned_count=counters["already_owned"],
            failed_count=counters["failed"],
            skipped_count=counters["skipped"],
            games_detected=games_detected,
            accounts_processed=counters["accounts_processed"],
        )
        if self._notifier is not None:
            self._notifier.notify_run_summary(outcome)
        return outcome

    def _process_game(
        self,
        connection,
        run_id: int,
        account_id: int,
        game,
        session,
        max_attempts: int,
        counters: dict[str, int],
    ) -> str:
        candidate = GameCandidate(epic_id=game.epic_id, name=game.name, url=game.url)
        claim = self._claims.get(connection, account_id, game.id)
        if claim is None:
            claim = self._claims.create(connection, account_id, game.id, ClaimState.SKIPPED)

        try:
            owned = self._retry_transient(
                lambda: self._adapter.is_owned(session, candidate), max_attempts
            )
            if owned:
                return self._record_claim(
                    connection,
                    run_id,
                    account_id,
                    game,
                    claim,
                    ClaimState.ALREADY_OWNED,
                    counters,
                    attempts=1,
                )
        except (InterventionRequiredError, AuthenticationRequiredError, RateLimitError, AccountBlockedError) as exc:
            return self._handle_blocking(connection, run_id, account_id, game, claim, exc, counters)
        except TransientError as exc:
            logger.warning("run_%s transient ownership failure for game %s: %s", run_id, game.id, exc)
            return self._record_claim(
                connection,
                run_id,
                account_id,
                game,
                claim,
                ClaimState.FAILED,
                counters,
                attempts=max_attempts,
                error=str(exc),
                retryable=True,
            )

        try:
            result, attempts = self._claim_with_retry(session, candidate, max_attempts)
        except (InterventionRequiredError, AuthenticationRequiredError, RateLimitError, AccountBlockedError) as exc:
            return self._handle_blocking(connection, run_id, account_id, game, claim, exc, counters)

        if result.outcome == Outcome.CLAIMED:
            return self._record_claim(
                connection,
                run_id,
                account_id,
                game,
                claim,
                ClaimState.CLAIMED,
                counters,
                attempts=attempts,
            )
        if result.outcome == Outcome.ALREADY_OWNED:
            return self._record_claim(
                connection,
                run_id,
                account_id,
                game,
                claim,
                ClaimState.ALREADY_OWNED,
                counters,
                attempts=attempts,
            )
        return self._record_claim(
            connection,
            run_id,
            account_id,
            game,
            claim,
            ClaimState.FAILED,
            counters,
            attempts=attempts,
            error=result.error,
            retryable=True,
        )

    def _claim_with_retry(self, session, candidate: GameCandidate, max_attempts: int):
        attempt = 0
        while True:
            attempt += 1
            result = self._adapter.claim(session, candidate)
            if result.outcome != Outcome.TRANSIENT or attempt >= max_attempts:
                return result, attempt
            self._sleeper(self._backoff(attempt))

    def _retry_transient(self, action, max_attempts: int):
        attempt = 0
        while True:
            attempt += 1
            try:
                return action()
            except TransientError:
                if attempt >= max_attempts:
                    raise
                self._sleeper(self._backoff(attempt))

    def _backoff(self, attempt: int) -> float:
        return min(2 ** (attempt - 1), 30)

    def _handle_blocking(self, connection, run_id, account_id, game, claim, exc, counters) -> str:
        if isinstance(exc, InterventionRequiredError):
            state = AccountState.NEEDS_INTERVENTION
        elif isinstance(exc, AuthenticationRequiredError):
            state = AccountState.NEEDS_AUTHENTICATION
        else:
            state = AccountState.PAUSED
        self._pause_account(connection, run_id, account_id, state, str(exc), counters)
        self._record_claim(
            connection,
            run_id,
            account_id,
            game,
            claim,
            ClaimState.FAILED,
            counters,
            attempts=1,
            error=str(exc),
            intervention_required=True,
        )
        return "paused"

    def _pause_account(self, connection, run_id, account_id, state, reason, counters) -> None:
        self._accounts.set_state(connection, account_id, state, reason=reason)
        self._events.add(
            connection,
            run_id,
            RunEventType.ACCOUNT_PAUSED,
            account_id=account_id,
            message=reason,
        )
        logger.warning("account_%s paused: %s", account_id, reason)
        if self._notifier is not None:
            self._notifier.notify_alert(f"account {account_id} paused ({state}): {reason}")

    def _record_claim(
        self,
        connection,
        run_id,
        account_id,
        game,
        claim,
        status: str,
        counters,
        *,
        attempts: int,
        error: str | None = None,
        retryable: bool = False,
        intervention_required: bool = False,
    ) -> str:
        claimed_at = None
        if status == ClaimState.CLAIMED:
            claimed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._claims.update_result(
            connection,
            claim.id,
            status=status,
            attempts=attempts,
            retryable=retryable,
            intervention_required=intervention_required,
            error=error,
            claimed_at=claimed_at,
        )
        self._attempts.create(
            connection,
            claim.id,
            run_id,
            status=status,
            attempts=attempts,
            retryable=retryable,
            intervention_required=intervention_required,
            error=error,
        )
        counters[status] += 1
        event_type = {
            ClaimState.CLAIMED: RunEventType.GAME_CLAIMED,
            ClaimState.ALREADY_OWNED: RunEventType.GAME_ALREADY_OWNED,
            ClaimState.FAILED: RunEventType.GAME_FAILED,
            ClaimState.SKIPPED: RunEventType.GAME_SKIPPED,
        }[status]
        self._events.add(
            connection,
            run_id,
            event_type,
            account_id=account_id,
            game_id=game.id,
            message=game.name,
        )
        return "processed"
