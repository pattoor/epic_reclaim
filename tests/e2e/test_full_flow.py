"""Controlled end-to-end flow without contacting the live store.

Walks through the main user journey using the API and a fake Epic adapter:
create an account, trigger a run, poll until it finishes, and verify the
history shows the claimed games.
"""

import time

from fastapi.testclient import TestClient

from app.domain.models import AccountState, RunState
from app.main import create_app
from app.integrations.epic_adapter import GameCandidate
from tests.fakes import FakeEpicAdapter


def test_end_to_end_run_and_history(tmp_path):
    adapter = FakeEpicAdapter(
        games=[
            GameCandidate(epic_id="g1", name="Game One", url="https://store/g1"),
            GameCandidate(epic_id="g2", name="Game Two", url="https://store/g2"),
        ]
    )
    app = create_app(
        {
            "DATABASE_PATH": str(tmp_path / "epic.db"),
            "SESSIONS_PATH": str(tmp_path / "sessions"),
            "STATE_PATH": str(tmp_path / "state"),
            "SCHEDULER_ENABLED": "false",
        },
        workflow_adapter=adapter,
        delay_between_actions=lambda: None,
    )

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        created = client.post("/api/accounts", json={"display_name": "Personal"})
        assert created.status_code == 200
        account_id = created.json()["id"]

        resolved = client.post(f"/api/accounts/{account_id}/resolve-intervention")
        assert resolved.json()["state"] == AccountState.ACTIVE

        triggered = client.post("/api/runs/manual")
        assert triggered.status_code == 200
        run_id = triggered.json()["run_id"]

        _wait_until(lambda: _run_status(client, run_id) != RunState.RUNNING)
        final = client.get(f"/api/runs/{run_id}").json()
        assert final["status"] == RunState.COMPLETED
        assert final["games_detected"] == 2
        assert final["claimed_count"] == 2

        history = client.get("/api/claims").json()
        assert len(history) == 2
        assert {item["status"] for item in history} == {"claimed"}

        events = client.get(f"/api/runs/{run_id}/events").json()
        assert len(events) >= 4

        exported = client.get("/api/claims/export?format=csv")
        assert exported.status_code == 200
        assert "Game One" in exported.text

        backup = client.get("/api/backup").json()
        assert len(backup["tables"]["accounts"]) == 1


def _run_status(client, run_id: int) -> str:
    return client.get(f"/api/runs/{run_id}").json()["status"]


def _wait_until(predicate, timeout_seconds: float = 10):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached within timeout")
