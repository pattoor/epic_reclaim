from __future__ import annotations

from app.integrations.epic_adapter import EpicAdapter, GameCandidate
from app.repositories import GamesRepository


class DiscoveryService:
    def __init__(self, adapter: EpicAdapter, repository: GamesRepository):
        self._adapter = adapter
        self._repository = repository

    def discover(self, connection) -> list[GameCandidate]:
        candidates = self._adapter.discover_free_games()
        for candidate in candidates:
            self._repository.upsert(
                connection,
                epic_id=candidate.epic_id,
                name=candidate.name,
                url=candidate.url,
            )
        return candidates
