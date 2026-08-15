from __future__ import annotations

import json
from app.database import SCHEMA_VERSION

TABLES = (
    "accounts",
    "games",
    "runs",
    "claims",
    "claim_attempts",
    "run_events",
    "settings",
)

SENSITIVE_SETTINGS = {"telegram_bot_token", "telegram_chat_id", "external_api_key"}


class BackupError(ValueError):
    pass


def export_backup(connection) -> dict:
    payload = {"schema_version": SCHEMA_VERSION, "tables": {}}
    for table in TABLES:
        rows = connection.execute(
            f"SELECT * FROM {table}"
        ).fetchall()
        records = [dict(row) for row in rows]
        if table == "settings":
            records = [
                record for record in records if record["key"] not in SENSITIVE_SETTINGS
            ]
        payload["tables"][table] = records
    return payload


def _validate(connection, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise BackupError("backup must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BackupError(
            f"unsupported backup schema version {payload.get('schema_version')}"
        )
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise BackupError("backup is missing a valid tables payload")
    for table in TABLES:
        if not isinstance(tables.get(table), list):
            raise BackupError(f"backup is missing the {table} table")
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for record in tables[table]:
            if not isinstance(record, dict) or set(record) != columns:
                raise BackupError(f"invalid columns in {table} backup")
            if table == "settings" and record["key"] in SENSITIVE_SETTINGS:
                raise BackupError(f"sensitive setting is not allowed: {record['key']}")


def import_backup(connection, payload: dict, *, overwrite: bool = False) -> int:
    _validate(connection, payload)
    if not overwrite:
        existing = sum(
            connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in TABLES
        )
        if existing:
            raise BackupError("target database already has data; confirmation required")
    connection.execute("SAVEPOINT backup_restore")
    try:
        # Children first to respect foreign key constraints.
        for table in (
            "run_events",
            "claim_attempts",
            "claims",
            "runs",
            "games",
            "accounts",
            "settings",
        ):
            connection.execute(f"DELETE FROM {table}")
        for table in TABLES:
            rows = payload["tables"].get(table, [])
            columns = list(
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            )
            placeholders = ", ".join("?" for _ in columns)
            for row in rows:
                connection.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    [row[column] for column in columns],
                )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    except Exception as error:
        connection.execute("ROLLBACK TO backup_restore")
        connection.execute("RELEASE backup_restore")
        raise BackupError("backup restore failed; existing data was preserved") from error
    connection.execute("RELEASE backup_restore")
    connection.commit()
    return sum(len(payload["tables"].get(table, [])) for table in TABLES)
