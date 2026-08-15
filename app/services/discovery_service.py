from __future__ import annotations

from app.integrations.epic_adapter import EpicAdapter
from app.repositories import GamesRepository


class DiscoveryService:
    def __init__(self, adapter: EpicAdapter, repository: GamesRepository):
        self._adapter = adapter
        self._repository = repository

    def discover(self, connection) -> list:
        candidates = self._adapter.discover_free_games()
        games = []
        for candidate in candidates:
            games.append(
                self._repository.upsert(
                    connection,
                    epic_id=candidate.epic_id,
                    name=candidate.name,
                    url=candidate.url,
                )
            )
        return games
