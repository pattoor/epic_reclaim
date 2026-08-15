from __future__ import annotations

import json
import sqlite3

from app.database import SCHEMA_VERSION
from app.domain.errors import NotFoundError

TABLES = (
    "accounts",
    "games",
    "runs",
    "claims",
    "claim_attempts",
    "run_events",
    "settings",
)


class BackupError(ValueError):
    pass


def export_backup(connection) -> dict:
    payload = {"schema_version": SCHEMA_VERSION, "tables": {}}
    for table in TABLES:
        rows = connection.execute(
            f"SELECT * FROM {table}"
        ).fetchall()
        payload["tables"][table] = [dict(row) for row in rows]
    return payload


def _validate(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise BackupError("backup must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BackupError(
            f"unsupported backup schema version {payload.get('schema_version')}"
        )
    tables = payload.get("tables")
    if not isinstance(tables, dict) or not all(
        isinstance(rows, list) for rows in tables.values()
    ):
        raise BackupError("backup is missing a valid tables payload")


def import_backup(connection, payload: dict, *, overwrite: bool = False) -> int:
    _validate(payload)
    if not overwrite:
        existing = sum(
            connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in TABLES
        )
        if existing:
            raise BackupError("target database already has data; confirmation required")
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
        for row in rows:
            columns = list(row.keys())
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return sum(len(payload["tables"].get(table, [])) for table in TABLES)
