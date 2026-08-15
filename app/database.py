from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    epic_identity TEXT,
    state TEXT NOT NULL DEFAULT 'needs_authentication',
    enabled INTEGER NOT NULL DEFAULT 1,
    processing_order INTEGER NOT NULL DEFAULT 0,
    last_block_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    epic_id TEXT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    games_detected INTEGER NOT NULL DEFAULT 0,
    accounts_processed INTEGER NOT NULL DEFAULT 0,
    claimed_count INTEGER NOT NULL DEFAULT 0,
    already_owned_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    game_id INTEGER NOT NULL REFERENCES games(id),
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    retryable INTEGER NOT NULL DEFAULT 0,
    intervention_required INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    claimed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, game_id)
);

CREATE TABLE IF NOT EXISTS claim_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES claims(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    retryable INTEGER NOT NULL DEFAULT 0,
    intervention_required INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    event_type TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    game_id INTEGER REFERENCES games(id),
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_epic_id ON games(epic_id);
CREATE INDEX IF NOT EXISTS idx_claims_account ON claims(account_id);
CREATE INDEX IF NOT EXISTS idx_claims_game ON claims(game_id);
CREATE INDEX IF NOT EXISTS idx_claims_updated ON claims(updated_at);
CREATE INDEX IF NOT EXISTS idx_claim_attempts_run ON claim_attempts(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_accounts_order ON accounts(processing_order);
"""


class Database:
    def __init__(self, path: str):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                connection.executescript(SCHEMA)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def check(self) -> bool:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True
