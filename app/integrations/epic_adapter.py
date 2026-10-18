from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameCandidate:
    epic_id: str | None
    name: str
    url: str


class Outcome:
    CLAIMED = "claimed"
    ALREADY_OWNED = "already_owned"
    TRANSIENT = "transient"
    INTERVENTION = "intervention"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ClaimResult:
    outcome: str
    error: str | None = None


@dataclass(frozen=True)
class AuthProgress:
    completed: bool
    epic_identity: str | None = None
    display_name: str | None = None
    error: str | None = None


class AccountSession(ABC):
    @abstractmethod
    def close(self) -> None:
        pass


class EpicAdapter(ABC):
    @abstractmethod
    def discover_free_games(self, profile_account_id: int | None = None) -> list[GameCandidate]:
        """Browse the Free Games section.

        `profile_account_id` optionally reuses that account's persistent
        browser profile (the user's own logged-in session) so store pages
        open with genuine cookies; discovery is only a public-page visit.
        """
        pass

    @abstractmethod
    def open_account_session(self, account_id: int) -> AccountSession:
        pass

    @abstractmethod
    def is_owned(self, session: AccountSession, game: GameCandidate) -> bool:
        pass

    @abstractmethod
    def claim(self, session: AccountSession, game: GameCandidate) -> ClaimResult:
        pass

    @abstractmethod
    def authenticate(self, account_id: int, mode: str) -> AuthProgress:
        pass
