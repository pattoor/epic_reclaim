import pytest

from app.cli import main


@pytest.fixture()
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "epic.db"))
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state"))
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")


def test_cli_exits_cleanly_on_quit(monkeypatch, cli_env, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "0")
    assert main() == 0


def test_cli_creates_account_from_menus(monkeypatch, cli_env):
    import os

    from app.database import Database
    from app.repositories import AccountsRepository

    sequence = iter(["2", "1", "Personal", "n", "0", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(sequence))

    assert main() == 0

    database = Database(os.environ["DATABASE_PATH"])
    with database.connect() as connection:
        accounts = AccountsRepository().list(connection)
    assert len(accounts) == 1
    assert accounts[0].display_name == "Personal"


def test_cli_shows_status(monkeypatch, cli_env, capsys):
    sequence = iter(["1", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(sequence))
    assert main() == 0
    output = capsys.readouterr().out
    assert "database" in output
    assert "scheduler" in output
