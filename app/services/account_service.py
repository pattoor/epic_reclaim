from __future__ import annotations

import shutil
from pathlib import Path

from app.domain.models import Account, AccountState
from app.repositories import AccountsRepository


class AccountService:
    def __init__(self, repository: AccountsRepository, sessions_path: str | None = None):
        self._repository = repository
        self._sessions_path = Path(sessions_path) if sessions_path else None

    def create(self, connection, display_name: str) -> Account:
        return self._repository.create(connection, display_name)

    def get(self, connection, account_id: int) -> Account:
        return self._repository.get(connection, account_id)

    def list(self, connection) -> list[Account]:
        return self._repository.list(connection)

    def update(
        self, connection, account_id: int, **fields
    ) -> Account:
        allowed = {
            "display_name",
            "epic_identity",
            "state",
            "enabled",
            "processing_order",
            "last_block_reason",
        }
        return self._repository.update(
            connection, account_id, **{k: v for k, v in fields.items() if k in allowed}
        )

    def set_enabled(self, connection, account_id: int, enabled: bool) -> Account:
        return self._repository.update(connection, account_id, enabled=int(enabled))

    def set_state(self, connection, account_id: int, state: str) -> Account:
        return self._repository.set_state(connection, account_id, state)

    def resolve_intervention(self, connection, account_id: int) -> Account:
        return self._repository.update(
            connection,
            account_id,
            state=AccountState.ACTIVE,
            last_block_reason=None,
        )

    def delete(self, connection, account_id: int) -> None:
        self._repository.delete(connection, account_id)
        if self._sessions_path is not None:
            shutil.rmtree(self._sessions_path / str(account_id), ignore_errors=True)
