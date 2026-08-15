from __future__ import annotations

from datetime import datetime, timezone

from app.domain.errors import NotFoundError
from app.domain.models import (
    Account,
    AccountState,
    Claim,
    ClaimAttempt,
    Game,
    Run,
    RunEvent,
    SettingsEntry,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_account(row) -> Account:
    return Account(
        id=row["id"],
        display_name=row["display_name"],
        epic_identity=row["epic_identity"],
        state=row["state"],
        enabled=bool(row["enabled"]),
        processing_order=row["processing_order"],
        last_block_reason=row["last_block_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_game(row) -> Game:
    return Game(
        id=row["id"],
        epic_id=row["epic_id"],
        name=row["name"],
        url=row["url"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_claim(row) -> Claim:
    return Claim(
        id=row["id"],
        account_id=row["account_id"],
        game_id=row["game_id"],
        status=row["status"],
        attempts=row["attempts"],
        retryable=bool(row["retryable"]),
        intervention_required=bool(row["intervention_required"]),
        error=row["error"],
        claimed_at=row["claimed_at"],
        updated_at=row["updated_at"],
    )


def _row_claim_attempt(row) -> ClaimAttempt:
    return ClaimAttempt(
        id=row["id"],
        claim_id=row["claim_id"],
        run_id=row["run_id"],
        status=row["status"],
        attempts=row["attempts"],
        retryable=bool(row["retryable"]),
        intervention_required=bool(row["intervention_required"]),
        error=row["error"],
        created_at=row["created_at"],
    )


def _row_run(row) -> Run:
    return Run(
        id=row["id"],
        trigger_source=row["trigger_source"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        games_detected=row["games_detected"],
        accounts_processed=row["accounts_processed"],
        claimed_count=row["claimed_count"],
        already_owned_count=row["already_owned_count"],
        failed_count=row["failed_count"],
        skipped_count=row["skipped_count"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_run_event(row) -> RunEvent:
    return RunEvent(
        id=row["id"],
        run_id=row["run_id"],
        event_type=row["event_type"],
        account_id=row["account_id"],
        game_id=row["game_id"],
        message=row["message"],
        created_at=row["created_at"],
    )


class AccountsRepository:
    def create(
        self, connection, display_name: str, state: str = AccountState.NEEDS_AUTHENTICATION
    ) -> Account:
        now = utc_now()
        cursor = connection.execute(
            """INSERT INTO accounts (display_name, state, enabled, processing_order, created_at, updated_at)
               VALUES (?, ?, 1, 0, ?, ?)""",
            (display_name, state, now, now),
        )
        connection.commit()
        return self.get(connection, cursor.lastrowid)

    def get(self, connection, account_id: int) -> Account:
        row = connection.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"account {account_id} not found")
        return _row_account(row)

    def list(self, connection) -> list[Account]:
        rows = connection.execute(
            "SELECT * FROM accounts ORDER BY processing_order, id"
        ).fetchall()
        return [_row_account(row) for row in rows]

    def list_enabled(self, connection) -> list[Account]:
        rows = connection.execute(
            "SELECT * FROM accounts WHERE enabled = 1 ORDER BY processing_order, id"
        ).fetchall()
        return [_row_account(row) for row in rows]

    def list_active(self, connection) -> list[Account]:
        rows = connection.execute(
            "SELECT * FROM accounts WHERE enabled = 1 AND state = 'active' "
            "ORDER BY processing_order, id"
        ).fetchall()
        return [_row_account(row) for row in rows]

    def update(self, connection, account_id: int, **fields) -> Account:
        allowed = {
            "display_name",
            "epic_identity",
            "state",
            "enabled",
            "processing_order",
            "last_block_reason",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get(connection, account_id)
        updates["updated_at"] = utc_now()
        columns = ", ".join(f"{key} = ?" for key in updates)
        connection.execute(
            f"UPDATE accounts SET {columns} WHERE id = ?",
            [*updates.values(), account_id],
        )
        connection.commit()
        return self.get(connection, account_id)

    def set_state(
        self, connection, account_id: int, state: str, reason: str | None = None
    ) -> Account:
        return self.update(
            connection, account_id, state=state, last_block_reason=reason
        )

    def delete(self, connection, account_id: int) -> None:
        claim_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM claims WHERE account_id = ?", (account_id,)
            ).fetchall()
        ]
        for claim_id in claim_ids:
            connection.execute(
                "DELETE FROM claim_attempts WHERE claim_id = ?", (claim_id,)
            )
        connection.execute("DELETE FROM claims WHERE account_id = ?", (account_id,))
        connection.execute(
            "DELETE FROM run_events WHERE account_id = ?", (account_id,)
        )
        connection.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        connection.commit()


class GamesRepository:
    def upsert(self, connection, epic_id: str | None, name: str, url: str) -> Game:
        now = utc_now()
        row = None
        if epic_id:
            row = connection.execute(
                "SELECT * FROM games WHERE epic_id = ?", (epic_id,)
            ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT * FROM games WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            cursor = connection.execute(
                """INSERT INTO games (epic_id, name, url, first_seen_at, last_seen_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (epic_id, name, url, now, now, now, now),
            )
            connection.commit()
            return self.get(connection, cursor.lastrowid)
        connection.execute(
            """UPDATE games
               SET epic_id = COALESCE(?, epic_id), name = ?, url = ?,
                   last_seen_at = ?, updated_at = ?
               WHERE id = ?""",
            (epic_id, name, url, now, now, row["id"]),
        )
        connection.commit()
        return self.get(connection, row["id"])

    def get(self, connection, game_id: int) -> Game:
        row = connection.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"game {game_id} not found")
        return _row_game(row)

    def list(self, connection) -> list[Game]:
        rows = connection.execute("SELECT * FROM games ORDER BY name").fetchall()
        return [_row_game(row) for row in rows]


class ClaimsRepository:
    def get(self, connection, account_id: int, game_id: int) -> Claim | None:
        row = connection.execute(
            "SELECT * FROM claims WHERE account_id = ? AND game_id = ?",
            (account_id, game_id),
        ).fetchone()
        return _row_claim(row) if row else None

    def create(self, connection, account_id: int, game_id: int, status: str) -> Claim:
        now = utc_now()
        cursor = connection.execute(
            """INSERT INTO claims (account_id, game_id, status, attempts, updated_at)
               VALUES (?, ?, ?, 0, ?)""",
            (account_id, game_id, status, now),
        )
        connection.commit()
        return self.get(connection, account_id, game_id)

    def update_result(
        self,
        connection,
        claim_id: int,
        *,
        status: str | None = None,
        attempts: int | None = None,
        retryable: bool | None = None,
        intervention_required: bool | None = None,
        error: str | None = None,
        claimed_at: str | None = None,
    ) -> Claim:
        current = connection.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if current is None:
            raise NotFoundError(f"claim {claim_id} not found")
        fields = {
            "status": status if status is not None else current["status"],
            "attempts": attempts if attempts is not None else current["attempts"],
            "retryable": int(retryable) if retryable is not None else current["retryable"],
            "intervention_required": (
                int(intervention_required)
                if intervention_required is not None
                else current["intervention_required"]
            ),
            "error": error,
            "claimed_at": claimed_at,
            "updated_at": utc_now(),
        }
        connection.execute(
            """UPDATE claims SET status = ?, attempts = ?, retryable = ?,
               intervention_required = ?, error = ?, claimed_at = ?, updated_at = ?
               WHERE id = ?""",
            (
                fields["status"],
                fields["attempts"],
                fields["retryable"],
                fields["intervention_required"],
                fields["error"],
                fields["claimed_at"],
                fields["updated_at"],
                claim_id,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        return _row_claim(row)

    def list(
        self,
        connection,
        *,
        account_id: int | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> list[Claim]:
        clauses = []
        params: list = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if since is not None:
            clauses.append("updated_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("updated_at <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"SELECT * FROM claims {where} ORDER BY updated_at DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [_row_claim(row) for row in rows]


class ClaimAttemptsRepository:
    def create(
        self,
        connection,
        claim_id: int,
        run_id: int,
        *,
        status: str,
        attempts: int,
        retryable: bool = False,
        intervention_required: bool = False,
        error: str | None = None,
    ) -> ClaimAttempt:
        cursor = connection.execute(
            """INSERT INTO claim_attempts
               (claim_id, run_id, status, attempts, retryable, intervention_required, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                claim_id,
                run_id,
                status,
                attempts,
                int(retryable),
                int(intervention_required),
                error,
                utc_now(),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM claim_attempts WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_claim_attempt(row)

    def list_by_claim(self, connection, claim_id: int) -> list[ClaimAttempt]:
        rows = connection.execute(
            "SELECT * FROM claim_attempts WHERE claim_id = ? ORDER BY created_at",
            (claim_id,),
        ).fetchall()
        return [_row_claim_attempt(row) for row in rows]


class RunsRepository:
    def create(self, connection, trigger_source: str) -> Run:
        now = utc_now()
        cursor = connection.execute(
            """INSERT INTO runs (trigger_source, status, started_at, created_at, updated_at)
               VALUES (?, 'running', ?, ?, ?)""",
            (trigger_source, now, now, now),
        )
        connection.commit()
        return self.get(connection, cursor.lastrowid)

    def get(self, connection, run_id: int) -> Run:
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"run {run_id} not found")
        return _row_run(row)

    def get_active(self, connection) -> Run | None:
        row = connection.execute(
            "SELECT * FROM runs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_run(row) if row else None

    def list(self, connection, limit: int = 50) -> list[Run]:
        rows = connection.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_run(row) for row in rows]

    def finish(
        self,
        connection,
        run_id: int,
        *,
        status: str,
        games_detected: int | None = None,
        accounts_processed: int | None = None,
        claimed_count: int | None = None,
        already_owned_count: int | None = None,
        failed_count: int | None = None,
        skipped_count: int | None = None,
        error: str | None = None,
    ) -> Run:
        current = connection.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if current is None:
            raise NotFoundError(f"run {run_id} not found")
        connection.execute(
            """UPDATE runs SET status = ?, ended_at = ?, games_detected = ?, accounts_processed = ?,
               claimed_count = ?, already_owned_count = ?, failed_count = ?, skipped_count = ?,
               error = ?, updated_at = ?
               WHERE id = ?""",
            (
                status,
                utc_now(),
                games_detected if games_detected is not None else current["games_detected"],
                accounts_processed if accounts_processed is not None else current["accounts_processed"],
                claimed_count if claimed_count is not None else current["claimed_count"],
                already_owned_count if already_owned_count is not None else current["already_owned_count"],
                failed_count if failed_count is not None else current["failed_count"],
                skipped_count if skipped_count is not None else current["skipped_count"],
                error,
                utc_now(),
                run_id,
            ),
        )
        connection.commit()
        return self.get(connection, run_id)


class RunEventsRepository:
    def add(
        self,
        connection,
        run_id: int,
        event_type: str,
        *,
        account_id: int | None = None,
        game_id: int | None = None,
        message: str | None = None,
    ) -> RunEvent:
        cursor = connection.execute(
            """INSERT INTO run_events (run_id, event_type, account_id, game_id, message, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, event_type, account_id, game_id, message, utc_now()),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM run_events WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_run_event(row)

    def list_by_run(self, connection, run_id: int, limit: int = 200) -> list[RunEvent]:
        rows = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY id DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
        return [_row_run_event(row) for row in rows]


class SettingsRepository:
    def get(self, connection, key: str) -> str | None:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set(self, connection, key: str, value: str) -> SettingsEntry:
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        connection.commit()
        return SettingsEntry(key=key, value=value)

    def all(self, connection) -> dict[str, str]:
        rows = connection.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}
