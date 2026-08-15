from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeEpicAdapter


def _make_app(tmp_path, adapter=None):
    return create_app(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": "false",
        },
        workflow_adapter=adapter,
        delay_between_actions=lambda: None,
    )


def _seed_claim(app) -> int:
    database = app.state.database
    account_service = app.state.account_service
    claims_repo = app.state.claims_repository
    games_repo = app.state.games_repository
    with database.connect() as connection:
        account = account_service.create(connection, "Personal")
        game = games_repo.upsert(connection, "g1", "Game One", "https://store/g1")
        claims_repo.create(connection, account.id, game.id, "claimed")
    return account.id


def test_dashboard_served(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Epic Reclaim" in response.text
    assert "app.js" in response.text


def test_export_csv(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_claim(app)
        response = client.get("/api/claims/export?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Game One" in response.text
    assert "claimed" in response.text


def test_export_json(tmp_path):
    import json

    app = _make_app(tmp_path)
    with TestClient(app) as client:
        _seed_claim(app)
        response = client.get("/api/claims/export?format=json")
    assert response.status_code == 200
    data = json.loads(response.text)
    assert data[0]["game"] == "Game One"
    assert data[0]["status"] == "claimed"
