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
    claim_outcomes: dict[str, str | Exception] = field(default_factory=dict)
    fail_discovery: Exception | None = None
    fail_claim: Exception | None = None
    fail_owned: Exception | None = None
    retries_before_success: dict[str, int] = field(default_factory=dict)
    _claim_calls: dict[str, int] = field(default_factory=dict)
    _account_by_session: dict[int, int] = field(default_factory=dict)
    _owned_by_account: dict[int, set[str]] = field(default_factory=dict)

    def _key(self, game: GameCandidate) -> str:
        return game.epic_id or game.url or game.name

    def discover_free_games(self, profile_account_id: int | None = None) -> list[GameCandidate]:
        if self.fail_discovery is not None:
            raise self.fail_discovery
        return list(self.games)

    def open_account_session(self, account_id: int) -> AccountSession:
        session = FakeSession()
        self._account_by_session[id(session)] = account_id
        return session

    def _account_id(self, session: AccountSession) -> int | None:
        return self._account_by_session.get(id(session))

    def _owned_for(self, session: AccountSession) -> set[str]:
        account_id = self._account_id(session)
        return self._owned_by_account.setdefault(account_id, set())

    def _claim_key(self, session: AccountSession, game: GameCandidate) -> str:
        key = self._key(game)
        account_id = self._account_id(session)
        if account_id is not None and f"{account_id}:{key}" in self.claim_outcomes:
            return f"{account_id}:{key}"
        return key

    def is_owned(self, session: AccountSession, game: GameCandidate) -> bool:
        if self.fail_owned is not None:
            raise self.fail_owned
        key = self._key(game)
        return key in self.owned or key in self._owned_for(session)

    def claim(self, session: AccountSession, game: GameCandidate) -> ClaimResult:
        if self.fail_claim is not None:
            raise self.fail_claim
        key = self._claim_key(session, game)
        self._claim_calls[key] = self._claim_calls.get(key, 0) + 1
        base_key = self._key(game)
        if base_key in self.owned or base_key in self._owned_for(session):
            return ClaimResult(outcome=Outcome.ALREADY_OWNED)

        outcome = self.claim_outcomes.get(key)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == Outcome.TRANSIENT:
            threshold = self.retries_before_success.get(key)
            if threshold is None or self._claim_calls[key] <= threshold:
                return ClaimResult(outcome=Outcome.TRANSIENT, error="transient failure")
            self._owned_for(session).add(base_key)
            return ClaimResult(outcome=Outcome.CLAIMED)
        if outcome:
            return ClaimResult(outcome=outcome)

        self._owned_for(session).add(base_key)
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
