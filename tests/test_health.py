from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_application_and_database(tmp_path):
    app = create_app({
        "DATABASE_PATH": str(tmp_path / "epic.db"),
        "SESSIONS_PATH": str(tmp_path / "sessions"),
        "STATE_PATH": str(tmp_path / "state"),
        "SCHEDULER_ENABLED": "false",
    })

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"
    assert "playwright" in response.json()
