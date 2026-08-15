import json

from fastapi.testclient import TestClient

from app.database import Database, SCHEMA_VERSION
from app.main import create_app
from app.services.backup_service import BackupError, export_backup, import_backup
from app.repositories import AccountsRepository, GamesRepository, ClaimsRepository
from tests.fakes import FakeEpicAdapter


def _make_app(tmp_path):
    return create_app(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": "false",
        },
        workflow_adapter=FakeEpicAdapter(),
        delay_between_actions=lambda: None,
    )


def test_export_and_import_roundtrip(tmp_path):
    source = Database(str(tmp_path / "source.db"))
    source.initialize()
    accounts = AccountsRepository()
    games = GamesRepository()
    claims = ClaimsRepository()
    with source.connect() as connection:
        account = accounts.create(connection, "Personal")
        game = games.upsert(connection, "g1", "Game One", "https://store/g1")
        claims.create(connection, account.id, game.id, "claimed")

    payload = None
    with source.connect() as connection:
        payload = export_backup(connection)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert len(payload["tables"]["accounts"]) == 1

    target = Database(str(tmp_path / "target.db"))
    target.initialize()
    with target.connect() as connection:
        restored = import_backup(connection, payload)
    assert restored == 3

    with target.connect() as connection:
        stored = accounts.list(connection)
    assert len(stored) == 1
    assert stored[0].display_name == "Personal"


def test_import_requires_empty_or_overwrite(tmp_path):
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    accounts = AccountsRepository()
    with database.connect() as connection:
        accounts.create(connection, "Existing")

    payload = None
    with database.connect() as connection:
        payload = export_backup(connection)

    with database.connect() as connection:
        try:
            import_backup(connection, payload)
            raise AssertionError("import into non-empty database must be rejected")
        except BackupError:
            pass

    with database.connect() as connection:
        restored = import_backup(connection, payload, overwrite=True)
    assert restored == 1


def test_import_rejects_wrong_schema_version(tmp_path):
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    with database.connect() as connection:
        try:
            import_backup(connection, {"schema_version": 999, "tables": {}})
            raise AssertionError("wrong schema version must be rejected")
        except BackupError:
            pass


def test_backup_api_export_and_import(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        account_id = client.post("/api/accounts", json={"display_name": "Personal"}).json()["id"]
        backup = client.get("/api/backup")
        assert backup.status_code == 200
        payload = backup.json()
        assert len(payload["tables"]["accounts"]) == 1

    with TestClient(app) as client:
        response = client.post("/api/backup/import", json=payload)
        assert response.status_code == 400

        response = client.post("/api/backup/import?overwrite=true", json=payload)
        assert response.status_code == 200
        assert response.json()["restored_rows"] == 1
