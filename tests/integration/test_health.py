from fastapi.testclient import TestClient

from app.main import create_app


def _make_app(tmp_path):
    return create_app(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": "false",
        }
    )


def test_health_reports_application_and_database(tmp_path):
    app = _make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"
    assert "playwright" in response.json()


def test_database_initialized_with_schema(tmp_path):
    from app.database import Database

    path = str(tmp_path / "epic.db")
    database = Database(path)
    database.initialize()

    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert {
        "accounts",
        "games",
        "runs",
        "claims",
        "claim_attempts",
        "run_events",
        "settings",
    } <= tables


def test_database_schema_idempotent(tmp_path):
    from app.database import Database

    path = str(tmp_path / "epic.db")
    database = Database(path)
    database.initialize()
    database.initialize()
    assert database.check() is True


def test_dashboard_root_served(tmp_path):
    app = _make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Epic Reclaim" in response.text
