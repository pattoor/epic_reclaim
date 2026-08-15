from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth_fakes import FakeScreen


def _create_account(app) -> int:
    database = app.state.database
    account_service = app.state.account_service
    with database.connect() as connection:
        account = account_service.create(connection, "Personal")
    return account.id


def _make_app(tmp_path, screen=None):
    return create_app(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": "false",
        },
        screen=screen,
    )


def test_health_reports_remote_screen(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert "remote_screen" in response.json()


def test_authenticate_creates_account_and_endpoint(tmp_path):
    app = _make_app(tmp_path, screen=FakeScreen(available=True))
    with TestClient(app) as client:
        account_id = _create_account(app)
        response = client.post(f"/api/accounts/{account_id}/authenticate")
        assert response.status_code == 200
        data = response.json()
        assert data["token"] != ""
        assert data["screen_url"] is not None

        status = client.get(f"/api/auth/{data['token']}")
        assert status.status_code == 200
        assert status.json()["status"] in ("running", "completed")

        revoked = client.post(f"/api/auth/{data['token']}/revoke")
        assert revoked.status_code == 200


def test_authenticate_unknown_account_404(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/accounts/999/authenticate")
    assert response.status_code == 404


def test_resolve_intervention_unknown_account_404(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/accounts/999/resolve-intervention")
    assert response.status_code == 404
