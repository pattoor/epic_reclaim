from __future__ import annotations

from dataclasses import dataclass


class AccountState:
    ACTIVE = "active"
    DISABLED = "disabled"
    NEEDS_AUTHENTICATION = "needs_authentication"
    NEEDS_INTERVENTION = "needs_intervention"
    PAUSED = "paused"


class ClaimState:
    CLAIMED = "claimed"
    ALREADY_OWNED = "already_owned"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunState:
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class RunTrigger:
    SCHEDULER = "scheduler"
    MANUAL = "manual"
    API = "api"


class RunEventType:
    RUN_STARTED = "run_started"
    GAMES_DETECTED = "games_detected"
    ACCOUNT_STARTED = "account_started"
    GAME_CLAIMED = "game_claimed"
    GAME_ALREADY_OWNED = "game_already_owned"
    GAME_FAILED = "game_failed"
    GAME_SKIPPED = "game_skipped"
    ACCOUNT_PAUSED = "account_paused"
    RUN_FINISHED = "run_finished"


@dataclass(frozen=True)
class Account:
    id: int
    display_name: str
    epic_identity: str | None = None
    state: str = AccountState.NEEDS_AUTHENTICATION
    enabled: bool = True
    processing_order: int = 0
    last_block_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Game:
    id: int
    epic_id: str | None = None
    name: str = ""
    url: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Claim:
    id: int
    account_id: int
    game_id: int
    status: str = ClaimState.SKIPPED
    attempts: int = 0
    retryable: bool = False
    intervention_required: bool = False
    error: str | None = None
    claimed_at: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class ClaimAttempt:
    id: int
    claim_id: int
    run_id: int
    status: str
    attempts: int = 0
    retryable: bool = False
    intervention_required: bool = False
    error: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class Run:
    id: int
    trigger_source: str
    status: str = RunState.RUNNING
    started_at: str = ""
    ended_at: str | None = None
    games_detected: int = 0
    accounts_processed: int = 0
    claimed_count: int = 0
    already_owned_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class RunEvent:
    id: int
    run_id: int
    event_type: str
    account_id: int | None = None
    game_id: int | None = None
    message: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class SettingsEntry:
    key: str
    value: str
