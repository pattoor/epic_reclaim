import time

from fastapi.testclient import TestClient

from app.domain.models import AccountState, RunState, RunTrigger
from app.main import create_app
from tests.fakes import FakeEpicAdapter


def _make_app(tmp_path, adapter=None, extra=None):
    overrides = {
        "DATABASE_PATH": str(tmp_path / "epic.db"),
        "SESSIONS_PATH": str(tmp_path / "sessions"),
        "STATE_PATH": str(tmp_path / "state"),
        "SCHEDULER_ENABLED": "false",
    }
    if extra:
        overrides.update(extra)
    return create_app(
        overrides,
        workflow_adapter=adapter,
        delay_between_actions=lambda: None,
    )


def _active_account(app) -> int:
    database = app.state.database
    account_service = app.state.account_service
    with database.connect() as connection:
        account = account_service.create(connection, "Personal")
        account_service.set_state(connection, account.id, AccountState.ACTIVE)
    return account.id


def test_accounts_crud(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/accounts", json={"display_name": "Personal"})
        assert created.status_code == 200
        account_id = created.json()["id"]

        listed = client.get("/api/accounts")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        patched = client.patch(
            f"/api/accounts/{account_id}",
            json={"display_name": "Renamed", "processing_order": 2},
        )
        assert patched.status_code == 200
        assert patched.json()["display_name"] == "Renamed"
        assert patched.json()["processing_order"] == 2

        deleted = client.delete(f"/api/accounts/{account_id}")
        assert deleted.status_code == 200
        assert client.get("/api/accounts").json() == []


def test_resolve_intervention(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        account_id = client.post("/api/accounts", json={"display_name": "A"}).json()["id"]
        client.post(f"/api/accounts/{account_id}/resolve-intervention")
        accounts = client.get("/api/accounts").json()
        assert accounts[0]["state"] == AccountState.ACTIVE


def test_run_trigger_and_poll(tmp_path):
    app = _make_app(tmp_path, adapter=FakeEpicAdapter())
    with TestClient(app) as client:
        account_id = _active_account(app)
        response = client.post("/api/runs")
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        assert response.json()["status"] == RunState.RUNNING

        _wait_until(lambda: _run_status(client, run_id) != RunState.RUNNING)
        status = _run_status(client, run_id)
        assert status in (RunState.COMPLETED, RunState.PARTIAL)

        events = client.get(f"/api/runs/{run_id}/events")
        assert events.status_code == 200
        assert len(events.json()) >= 2


def test_run_trigger_conflict_returns_409(tmp_path):
    app = _make_app(tmp_path, adapter=FakeEpicAdapter())
    with TestClient(app) as client:
        lock = app.state.workflow._lock
        assert lock.acquire() is True
        try:
            response = client.post("/api/runs")
            assert response.status_code == 409
        finally:
            lock.release()


def test_settings_get_and_patch(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        settings = client.get("/api/settings")
        assert settings.status_code == 200
        assert settings.json()["scheduler_interval_seconds"] == 21600

        patched = client.patch("/api/settings", json={"scheduler_interval_seconds": 7200})
        assert patched.status_code == 200
        assert patched.json()["scheduler_interval_seconds"] == 7200

        settings = client.get("/api/settings")
        assert settings.json()["scheduler_interval_seconds"] == 7200


def test_external_api_key_protects_run_trigger(tmp_path):
    app = _make_app(
        tmp_path,
        adapter=FakeEpicAdapter(),
        extra={"EXTERNAL_API_KEY_ENABLED": "true", "EXTERNAL_API_KEY": "secret-key"},
    )
    with TestClient(app) as client:
        denied = client.post("/api/runs")
        assert denied.status_code == 401

        allowed = client.post("/api/runs", headers={"X-API-Key": "secret-key"})
        assert allowed.status_code in (200, 409)


def test_health_reports_application_components(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "database" in response.json()
    assert "playwright" in response.json()
    assert "remote_screen" in response.json()


def _run_status(client, run_id: int) -> str:
    return client.get(f"/api/runs/{run_id}").json()["status"]


def _wait_until(predicate, timeout_seconds: float = 10):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached within timeout")
