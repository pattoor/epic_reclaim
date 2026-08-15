from __future__ import annotations


class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    pass


class EpicError(DomainError):
    pass


class TransientError(EpicError):
    pass


class InterventionRequiredError(EpicError):
    pass


class AuthenticationRequiredError(EpicError):
    pass


class RateLimitError(EpicError):
    pass


class AccountBlockedError(EpicError):
    pass
