from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.domain.errors import NotFoundError
from app.domain.models import AccountState, RunTrigger

router = APIRouter(prefix="/api")


class AccountCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


class AccountUpdate(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    processing_order: int | None = None


class SettingsUpdate(BaseModel):
    scheduler_enabled: bool | None = None
    scheduler_interval_seconds: int | None = None
    claim_delay_min_seconds: float | None = None
    claim_delay_max_seconds: float | None = None
    telegram_enabled: bool | None = None


def _state(request: Request):
    return request.app.state


def _db(request: Request):
    return request.app.state.database


def _account_service(request: Request):
    return request.app.state.account_service


def _auth_service(request: Request):
    return request.app.state.auth_service


def _workflow(request: Request):
    return request.app.state.workflow


def _settings_service(request: Request):
    return request.app.state.settings_service


def _guard_api_key(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.external_api_key_enabled:
        return
    provided = request.headers.get("X-API-Key")
    if provided != settings.external_api_key:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


# Accounts


@router.get("/accounts")
def list_accounts(request: Request):
    with _db(request).connect() as connection:
        accounts = _account_service(request).list(connection)
    return [
        {
            "id": account.id,
            "display_name": account.display_name,
            "epic_identity": account.epic_identity,
            "state": account.state,
            "enabled": account.enabled,
            "processing_order": account.processing_order,
            "last_block_reason": account.last_block_reason,
        }
        for account in accounts
    ]


@router.post("/accounts")
def create_account(body: AccountCreate, request: Request):
    with _db(request).connect() as connection:
        account = _account_service(request).create(connection, body.display_name)
    return {
        "id": account.id,
        "display_name": account.display_name,
        "state": account.state,
        "enabled": account.enabled,
    }


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, body: AccountUpdate, request: Request):
    updates = {
        "display_name": body.display_name,
        "enabled": body.enabled,
        "processing_order": body.processing_order,
    }
    updates = {key: value for key, value in updates.items() if value is not None}
    try:
        with _db(request).connect() as connection:
            account = _account_service(request).update(connection, account_id, **updates)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": account.id,
        "display_name": account.display_name,
        "state": account.state,
        "enabled": account.enabled,
        "processing_order": account.processing_order,
    }


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, request: Request):
    try:
        with _db(request).connect() as connection:
            _account_service(request).delete(connection, account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "deleted"}


@router.post("/accounts/{account_id}/authenticate")
def authenticate(account_id: int, request: Request):
    try:
        session = _auth_service(request).start(account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if session.status == "unavailable":
        raise HTTPException(status_code=503, detail=session.error)
    return {
        "token": session.token,
        "screen_url": session.screen_url,
        "status": session.status,
    }


@router.post("/accounts/{account_id}/resolve-intervention")
def resolve_intervention(account_id: int, request: Request):
    try:
        with _db(request).connect() as connection:
            account = _account_service(request).resolve_intervention(connection, account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": account.id,
        "state": account.state,
        "display_name": account.display_name,
    }


@router.get("/auth/{token}")
def auth_status(token: str, request: Request):
    session = _auth_service(request).get(token)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "token": session.token,
        "account_id": session.account_id,
        "screen_url": session.screen_url,
        "status": session.status,
        "error": session.error,
    }


@router.post("/auth/{token}/revoke")
def revoke_auth(token: str, request: Request):
    _auth_service(request).revoke(token)
    return {"status": "revoked"}


# Games


@router.get("/games")
def list_games(request: Request):
    with _db(request).connect() as connection:
        games = request.app.state.games_repository.list(connection)
    return [
        {"id": game.id, "epic_id": game.epic_id, "name": game.name, "url": game.url}
        for game in games
    ]


# Claims


@router.get("/claims")
def list_claims(
    request: Request,
    account_id: int | None = None,
    status: str | None = None,
    since: str | None = None,
):
    with _db(request).connect() as connection:
        claims = request.app.state.claims_repository.list(
            connection, account_id=account_id, status=status, since=since
        )
        games = {g.id: g for g in request.app.state.games_repository.list(connection)}
    return [
        {
            "id": claim.id,
            "account_id": claim.account_id,
            "game_id": claim.game_id,
            "game_name": games.get(claim.game_id).name if claim.game_id in games else None,
            "status": claim.status,
            "attempts": claim.attempts,
            "error": claim.error,
            "claimed_at": claim.claimed_at,
            "updated_at": claim.updated_at,
        }
        for claim in claims
    ]


# Runs


@router.get("/runs")
def list_runs(request: Request, limit: int = 50):
    with _db(request).connect() as connection:
        runs = request.app.state.runs_repository.list(connection, limit=limit)
    return [
        {
            "id": run.id,
            "trigger_source": run.trigger_source,
            "status": run.status,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "games_detected": run.games_detected,
            "accounts_processed": run.accounts_processed,
            "claimed_count": run.claimed_count,
            "already_owned_count": run.already_owned_count,
            "failed_count": run.failed_count,
            "skipped_count": run.skipped_count,
            "error": run.error,
        }
        for run in runs
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: int, request: Request):
    try:
        with _db(request).connect() as connection:
            run = request.app.state.runs_repository.get(connection, run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": run.id,
        "trigger_source": run.trigger_source,
        "status": run.status,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "games_detected": run.games_detected,
        "accounts_processed": run.accounts_processed,
        "claimed_count": run.claimed_count,
        "already_owned_count": run.already_owned_count,
        "failed_count": run.failed_count,
        "skipped_count": run.skipped_count,
        "error": run.error,
    }


@router.get("/runs/{run_id}/events")
def get_run_events(run_id: int, request: Request):
    with _db(request).connect() as connection:
        events = request.app.state.events_repository.list_by_run(connection, run_id)
    return [
        {
            "id": event.id,
            "run_id": event.run_id,
            "event_type": event.event_type,
            "account_id": event.account_id,
            "game_id": event.game_id,
            "message": event.message,
            "created_at": event.created_at,
        }
        for event in events
    ]


@router.post("/runs")
def trigger_run(request: Request):
    _guard_api_key(request)
    outcome = _workflow(request).start(RunTrigger.API)
    if outcome.status == "conflict":
        raise HTTPException(status_code=409, detail=outcome.error)
    return {"run_id": outcome.run_id, "status": outcome.status}


# Settings


_EDITABLE_KEYS = {
    "scheduler_enabled",
    "scheduler_interval_seconds",
    "claim_delay_min_seconds",
    "claim_delay_max_seconds",
    "telegram_enabled",
}


@router.get("/settings")
def get_settings(request: Request):
    settings = request.app.state.settings
    with _db(request).connect() as connection:
        effective = _settings_service(request).load(connection)
    return {
        "scheduler_enabled": effective.scheduler_enabled,
        "scheduler_interval_seconds": effective.scheduler_interval_seconds,
        "claim_delay_min_seconds": effective.claim_delay_min_seconds,
        "claim_delay_max_seconds": effective.claim_delay_max_seconds,
        "max_retry_attempts": effective.max_retry_attempts,
        "telegram_enabled": effective.telegram_enabled,
        "app_port": settings.app_port,
    }


@router.patch("/settings")
def update_settings(body: SettingsUpdate, request: Request):
    updates = {
        "scheduler_enabled": body.scheduler_enabled,
        "scheduler_interval_seconds": body.scheduler_interval_seconds,
        "claim_delay_min_seconds": body.claim_delay_min_seconds,
        "claim_delay_max_seconds": body.claim_delay_max_seconds,
        "telegram_enabled": body.telegram_enabled,
    }
    updates = {key: value for key, value in updates.items() if value is not None}
    with _db(request).connect() as connection:
        stored = _settings_service(request).update(connection, updates, _EDITABLE_KEYS)
    return {key: stored.get(key) for key in _EDITABLE_KEYS}
