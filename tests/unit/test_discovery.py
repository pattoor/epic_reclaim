from app.database import Database
from app.integrations.epic_adapter import GameCandidate
from app.integrations.epic_playwright import classify_offer
from app.repositories import GamesRepository
from app.services.discovery_service import DiscoveryService
from tests.fakes import FakeEpicAdapter


def _database(tmp_path) -> Database:
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    return database


def test_classify_offer_accepts_eligible():
    candidate = classify_offer("Subnautica", None)
    assert candidate is not None
    assert candidate.name == "Subnautica"


def test_classify_offer_excludes_coming_soon_and_demos():
    assert classify_offer("Upcoming Title", "Coming Soon") is None
    assert classify_offer("Demo Game", None) is None
    assert classify_offer("Fortnite", "Free to Play") is None


def test_discovery_persists_games(tmp_path):
    database = _database(tmp_path)
    games = [
        GameCandidate(epic_id="game-a", name="Game A", url="https://store.epicgames.com/game-a"),
        GameCandidate(epic_id="game-b", name="Game B", url="https://store.epicgames.com/game-b"),
    ]
    service = DiscoveryService(FakeEpicAdapter(games=games), GamesRepository())

    with database.connect() as connection:
        discovered = service.discover(connection)

    assert len(discovered) == 2
    with database.connect() as connection:
        stored = GamesRepository().list(connection)
    assert {g.name for g in stored} == {"Game A", "Game B"}


def test_discovery_upsert_is_idempotent(tmp_path):
    database = _database(tmp_path)
    games = [GameCandidate(epic_id="game-a", name="Game A", url="https://store/game-a")]
    service = DiscoveryService(FakeEpicAdapter(games=games), GamesRepository())

    with database.connect() as connection:
        service.discover(connection)
        service.discover(connection)

    with database.connect() as connection:
        stored = GamesRepository().list(connection)
    assert len(stored) == 1
