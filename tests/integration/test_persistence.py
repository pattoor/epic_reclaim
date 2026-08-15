from app.database import Database
from app.domain.errors import NotFoundError
from app.domain.models import AccountState, ClaimState, RunState, RunTrigger
from app.repositories import (
    AccountsRepository,
    ClaimAttemptsRepository,
    ClaimsRepository,
    GamesRepository,
    RunEventsRepository,
    RunsRepository,
    SettingsRepository,
)


def _database(tmp_path) -> Database:
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    return database


def test_account_crud(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Personal")
        assert account.state == AccountState.NEEDS_AUTHENTICATION
        assert account.enabled is True

        updated = accounts.update(
            connection,
            account.id,
            display_name="Mi cuenta",
            processing_order=3,
            state=AccountState.ACTIVE,
        )
        assert updated.display_name == "Mi cuenta"
        assert updated.processing_order == 3
        assert updated.state == AccountState.ACTIVE

        listed = accounts.list(connection)
        assert [a.id for a in listed] == [account.id]

        accounts.delete(connection, account.id)
        try:
            accounts.get(connection, account.id)
            raise AssertionError("account should be deleted")
        except NotFoundError:
            pass


def test_account_state_transitions_and_history_preserved_on_disable(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "A")
        games = GamesRepository()
        game = games.upsert(connection, "epic-1", "Game One", "https://store.epicgames.com/game-one")

        claims = ClaimsRepository()
        claim = claims.create(connection, account.id, game.id, ClaimState.CLAIMED)
        assert claim.status == ClaimState.CLAIMED

        accounts.update(connection, account.id, enabled=0)
        assert accounts.get(connection, account.id).enabled is False
        assert claims.get(connection, account.id, game.id) is not None


def test_claim_idempotency_unique_account_game(tmp_path):
    import sqlite3

    database = _database(tmp_path)
    accounts = AccountsRepository()
    games = GamesRepository()
    claims = ClaimsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "A")
        game = games.upsert(connection, "epic-1", "Game One", "https://store/game-one")
        claims.create(connection, account.id, game.id, ClaimState.CLAIMED)

        try:
            claims.create(connection, account.id, game.id, ClaimState.CLAIMED)
            raise AssertionError("duplicate claim should violate unique constraint")
        except sqlite3.IntegrityError:
            pass

        assert claims.get(connection, account.id, game.id) is not None
        assert len(claims.list(connection)) == 1


def test_claim_attempts_history_retained(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    games = GamesRepository()
    claims = ClaimsRepository()
    attempts = ClaimAttemptsRepository()
    runs = RunsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "A")
        game = games.upsert(connection, "epic-1", "Game One", "https://store/game-one")
        claim = claims.create(connection, account.id, game.id, ClaimState.FAILED)
        run = runs.create(connection, RunTrigger.MANUAL)

        attempt = attempts.create(
            connection,
            claim.id,
            run.id,
            status=ClaimState.FAILED,
            attempts=1,
            error="timeout",
        )
        assert attempt.retryable is False

        history = attempts.list_by_claim(connection, claim.id)
        assert len(history) == 1
        assert history[0].error == "timeout"


def test_claim_list_filters(tmp_path):
    database = _database(tmp_path)
    accounts = AccountsRepository()
    games = GamesRepository()
    claims = ClaimsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "A")
        game1 = games.upsert(connection, "e1", "Game One", "https://store/g1")
        game2 = games.upsert(connection, "e2", "Game Two", "https://store/g2")
        claims.create(connection, account.id, game1.id, ClaimState.CLAIMED)
        claims.create(connection, account.id, game2.id, ClaimState.ALREADY_OWNED)

        all_claims = claims.list(connection)
        assert len(all_claims) == 2

        claimed = claims.list(connection, status=ClaimState.CLAIMED)
        assert len(claimed) == 1
        assert claimed[0].game_id == game1.id

        by_account = claims.list(connection, account_id=account.id)
        assert len(by_account) == 2


def test_runs_lifecycle(tmp_path):
    database = _database(tmp_path)
    runs = RunsRepository()
    events = RunEventsRepository()
    with database.connect() as connection:
        run = runs.create(connection, RunTrigger.SCHEDULER)
        assert run.status == RunState.RUNNING
        assert runs.get_active(connection).id == run.id

        events.add(connection, run.id, "games_detected", message="2 games")
        stored_events = events.list_by_run(connection, run.id)
        assert len(stored_events) == 1

        finished = runs.finish(
            connection,
            run.id,
            status=RunState.COMPLETED,
            games_detected=2,
            accounts_processed=1,
            claimed_count=1,
        )
        assert finished.status == RunState.COMPLETED
        assert finished.games_detected == 2
        assert finished.ended_at is not None
        assert runs.get_active(connection) is None


def test_settings_persistence(tmp_path):
    database = _database(tmp_path)
    settings = SettingsRepository()
    with database.connect() as connection:
        settings.set(connection, "scheduler_interval_seconds", "7200")
        assert settings.get(connection, "scheduler_interval_seconds") == "7200"
        assert settings.all(connection) == {"scheduler_interval_seconds": "7200"}


def test_persistence_survives_reopen(tmp_path):
    path = str(tmp_path / "epic.db")
    database = Database(path)
    database.initialize()
    accounts = AccountsRepository()
    with database.connect() as connection:
        account = accounts.create(connection, "Persistente")

    reopened = Database(path)
    reopened.initialize()
    with reopened.connect() as connection:
        assert accounts.get(connection, account.id).display_name == "Persistente"
