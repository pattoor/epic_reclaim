from app.database import Database
from app.integrations.epic_adapter import GameCandidate
from app.integrations.epic_playwright import classify_offer, classify_playwright_error
from app.domain.errors import TransientError
from app.repositories import GamesRepository
from app.services.discovery_service import DiscoveryService
from tests.fakes import FakeEpicAdapter


def _database(tmp_path) -> Database:
    database = Database(str(tmp_path / "epic.db"))
    database.initialize()
    return database


def test_classify_offer_accepts_eligible():
    candidate = classify_offer("Subnautica", None, price="Free", cta="Get")
    assert candidate is not None
    assert candidate.name == "Subnautica"


def test_classify_offer_requires_free_signal():
    assert classify_offer("Some Game", None, price=None, cta=None) is None
    assert classify_offer("Some Game", None, price="19,99 EUR", cta="Buy Now") is None


def test_classify_offer_excludes_coming_soon_and_demos():
    assert classify_offer("Upcoming Title", "Coming Soon", price="Free", cta="Get") is None
    assert classify_offer("Demo Game", None, price="Free", cta="Get") is None
    assert classify_offer("Fortnite", "Free to Play", price="Free", cta="Get") is None


def test_classify_offer_rejects_paid_price():
    assert classify_offer("AAA Game", None, price="$59.99", cta="Buy Now") is None
    assert classify_offer("Discounted", "Sale", price="€29.99", cta="Add to Cart") is None


def test_classify_offer_rejects_paid_cta_even_with_free_price():
    assert classify_offer("Tricky", None, price="Free", cta="Buy Now") is None
    assert classify_offer("Tricky", None, price="Free", cta="Add to Cart") is None


def test_playwright_timeout_is_transient():
    classified = classify_playwright_error(TimeoutError("page timeout"))
    assert isinstance(classified, TransientError)


def test_unknown_playwright_error_is_not_marked_transient():
    error = ValueError("unexpected selector state")
    assert classify_playwright_error(error) is error


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
