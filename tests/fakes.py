from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.errors import (
    AccountBlockedError,
    AuthenticationRequiredError,
    InterventionRequiredError,
    RateLimitError,
    TransientError,
)
from app.integrations.epic_adapter import (
    AccountSession,
    AuthProgress,
    ClaimResult,
    EpicAdapter,
    GameCandidate,
    Outcome,
)


@dataclass
class FakeEpicAdapter(EpicAdapter):
    games: list[GameCandidate] = field(default_factory=list)
    owned: set[str] = field(default_factory=set)
    claim_outcomes: dict[str, str] = field(default_factory=dict)
    fail_discovery: Exception | None = None
    fail_claim: Exception | None = None
    fail_owned: Exception | None = None
    retries_before_success: dict[str, int] = field(default_factory=dict)
    _claim_calls: dict[str, int] = field(default_factory=dict)

    def _key(self, game: GameCandidate) -> str:
        return game.epic_id or game.url or game.name

    def discover_free_games(self) -> list[GameCandidate]:
        if self.fail_discovery is not None:
            raise self.fail_discovery
        return list(self.games)

    def open_account_session(self, account_id: int) -> AccountSession:
        return FakeSession()

    def is_owned(self, session: AccountSession, game: GameCandidate) -> bool:
        if self.fail_owned is not None:
            raise self.fail_owned
        return self._key(game) in self.owned

    def claim(self, session: AccountSession, game: GameCandidate) -> ClaimResult:
        if self.fail_claim is not None:
            raise self.fail_claim
        key = self._key(game)
        self._claim_calls[key] = self._claim_calls.get(key, 0) + 1
        if key in self.owned:
            return ClaimResult(outcome=Outcome.ALREADY_OWNED)

        outcome = self.claim_outcomes.get(key)
        if outcome:
            if outcome == Outcome.TRANSIENT:
                threshold = self.retries_before_success.get(key, 1)
                if self._claim_calls[key] <= threshold:
                    return ClaimResult(outcome=Outcome.TRANSIENT, error="transient failure")
            return ClaimResult(outcome=outcome)

        self.owned.add(key)
        return ClaimResult(outcome=Outcome.CLAIMED)

    def authenticate(self, account_id: int, mode: str) -> AuthProgress:
        return AuthProgress(completed=True, epic_identity="epic-identity", display_name="Epic User")


class FakeSession(AccountSession):
    def close(self) -> None:
        pass


# Convenience exception factories for tests
def transient_error() -> TransientError:
    return TransientError("transient network error")


def intervention_error() -> InterventionRequiredError:
    return InterventionRequiredError("captcha required")


def auth_error() -> AuthenticationRequiredError:
    return AuthenticationRequiredError("session expired")


def rate_limit_error() -> RateLimitError:
    return RateLimitError("rate limited")


def blocked_error() -> AccountBlockedError:
    return AccountBlockedError("account blocked")
