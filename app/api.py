from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.domain.errors import NotFoundError
from app.domain.models import RunTrigger
from app.services.backup_service import BackupError, export_backup, import_backup

router = APIRouter(prefix="/api")


class AccountCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


class AccountUpdate(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    processing_order: int | None = None


class SettingsUpdate(BaseModel):
    scheduler_enabled: bool | None = None
    scheduler_days: str | None = None
    scheduler_times: str | None = None
    scheduler_daily: bool | None = None
    claim_delay_min_seconds: float | None = None
    claim_delay_max_seconds: float | None = None
    telegram_enabled: bool | None = None


def _validate_settings_update(request: Request, updates: dict) -> None:
    from app.domain import scheduling

    with _db(request).connect() as connection:
        effective = _settings_service(request).load(connection)

    days = updates.get("scheduler_days", effective.scheduler_days)
    times = updates.get("scheduler_times", effective.scheduler_times)
    daily = updates.get("scheduler_daily", effective.scheduler_daily)
    try:
        scheduling.normalize_days(days)
        scheduling.normalize_times(times)
    except scheduling.ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not scheduling.build_slots(days, times, daily=daily):
        raise HTTPException(
            status_code=422,
            detail="schedule must contain at least one valid day and time",
        )

    delay_min = updates.get("claim_delay_min_seconds", effective.claim_delay_min_seconds)
    delay_max = updates.get("claim_delay_max_seconds", effective.claim_delay_max_seconds)
    if delay_min < 0:
        raise HTTPException(status_code=422, detail="claim_delay_min_seconds must be >= 0")
    if delay_max < delay_min:
        raise HTTPException(
            status_code=422,
            detail="claim_delay_max_seconds must be >= claim_delay_min_seconds",
        )
    if updates.get("telegram_enabled") is True:
        if not effective.telegram_bot_token or not effective.telegram_chat_id:
            raise HTTPException(
                status_code=422,
                detail="Telegram requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
            )


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
def delete_account(account_id: int, request: Request, confirm: bool = False):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="permanent deletion requires confirm=true",
        )
    try:
        _auth_service(request).revoke_account(account_id)
        with _db(request).connect() as connection:
            _account_service(request).delete(connection, account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "deleted"}


class AuthCodeSubmit(BaseModel):
    code: str


@router.post("/accounts/{account_id}/authenticate")
def authenticate(account_id: int, request: Request, mode: str = "screen"):
    try:
        if mode not in {"screen", "device", "local", "unlock"}:
            mode = "screen"
        session = _auth_service(request).start(account_id, mode=mode)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if session.status == "unavailable":
        raise HTTPException(status_code=503, detail=session.error)
    return {
        "token": session.token,
        "screen_url": session.screen_url,
        "auth_url": session.auth_url,
        "status": session.status,
    }


@router.post("/auth/{token}/code")
def submit_auth_code(token: str, body: AuthCodeSubmit, request: Request):
    session = _auth_service(request).submit_code(token, body.code)
    if session is None:
        raise HTTPException(status_code=404, detail="no active authentication session for this token")
    if session.error and session.status == "running":
        # Epic rejected the code but the session stays open for a retry.
        raise HTTPException(status_code=400, detail=session.error)
    return {
        "token": session.token,
        "status": session.status,
        "auth_url": session.auth_url,
    }


@router.post("/accounts/{account_id}/resolve-intervention")
def resolve_intervention(account_id: int, request: Request):
    try:
        with _db(request).connect() as connection:
            account = _account_service(request).resolve_intervention(connection, account_id)
        notifier = getattr(request.app.state, "notifier", None)
        if notifier is not None:
            notifier.notify_resolved(f"account {account_id} back to active")
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
        "auth_url": session.auth_url,
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


@router.get("/claims/export")
def export_claims(
    request: Request,
    account_id: int | None = None,
    status: str | None = None,
    since: str | None = None,
    format: str = "csv",
):
    from io import StringIO

    from fastapi.responses import Response

    with _db(request).connect() as connection:
        claims = request.app.state.claims_repository.list(
            connection, account_id=account_id, status=status, since=since
        )
        games = {g.id: g for g in request.app.state.games_repository.list(connection)}

    rows = [
        {
            "account_id": claim.account_id,
            "game": games.get(claim.game_id).name if claim.game_id in games else "",
            "status": claim.status,
            "attempts": claim.attempts,
            "error": claim.error or "",
            "claimed_at": claim.claimed_at or "",
            "updated_at": claim.updated_at,
        }
        for claim in claims
    ]

    if format == "json":
        return Response(
            json.dumps(rows, ensure_ascii=True),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=claims.json"},
        )

    import csv

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else ["account_id", "game", "status", "attempts", "error", "claimed_at", "updated_at"])
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=claims.csv"},
    )


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


@router.post("/runs/manual")
def trigger_run_manual(request: Request):
    outcome = _workflow(request).start(RunTrigger.MANUAL)
    if outcome.status == "conflict":
        raise HTTPException(status_code=409, detail=outcome.error)
    return {"run_id": outcome.run_id, "status": outcome.status}


# Backup / restore


@router.get("/backup")
def download_backup(request: Request):
    from fastapi.responses import Response

    with _db(request).connect() as connection:
        payload = export_backup(connection)
    return Response(
        json.dumps(payload, ensure_ascii=True, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=epic-reclaim-backup.json"},
    )


@router.post("/backup/import")
async def upload_backup(request: Request, overwrite: bool = False):
    from fastapi.responses import JSONResponse

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    try:
        with _db(request).connect() as connection:
            restored = import_backup(connection, payload, overwrite=overwrite)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({"restored_rows": restored})


# Settings


_EDITABLE_KEYS = {
    "scheduler_enabled",
    "scheduler_days",
    "scheduler_times",
    "scheduler_daily",
    "claim_delay_min_seconds",
    "claim_delay_max_seconds",
    "telegram_enabled",
}


@router.get("/settings")
def get_settings(request: Request):
    with _db(request).connect() as connection:
        effective = _settings_service(request).load(connection)
    return {
        "scheduler_enabled": effective.scheduler_enabled,
        "scheduler_days": effective.scheduler_days,
        "scheduler_times": effective.scheduler_times,
        "scheduler_daily": effective.scheduler_daily,
        "claim_delay_min_seconds": effective.claim_delay_min_seconds,
        "claim_delay_max_seconds": effective.claim_delay_max_seconds,
        "max_retry_attempts": effective.max_retry_attempts,
        "telegram_enabled": effective.telegram_enabled,
        "next_run_at": getattr(request.app.state.scheduler, "next_run_at", None),
    }


@router.patch("/settings")
def update_settings(body: SettingsUpdate, request: Request):
    updates = {
        "scheduler_enabled": body.scheduler_enabled,
        "scheduler_days": body.scheduler_days,
        "scheduler_times": body.scheduler_times,
        "scheduler_daily": body.scheduler_daily,
        "claim_delay_min_seconds": body.claim_delay_min_seconds,
        "claim_delay_max_seconds": body.claim_delay_max_seconds,
        "telegram_enabled": body.telegram_enabled,
    }
    updates = {key: value for key, value in updates.items() if value is not None}
    _validate_settings_update(request, updates)
    with _db(request).connect() as connection:
        _settings_service(request).update(connection, updates, _EDITABLE_KEYS)
        effective = _settings_service(request).load(connection)
    return {
        "scheduler_enabled": effective.scheduler_enabled,
        "scheduler_days": effective.scheduler_days,
        "scheduler_times": effective.scheduler_times,
        "scheduler_daily": effective.scheduler_daily,
        "claim_delay_min_seconds": effective.claim_delay_min_seconds,
        "claim_delay_max_seconds": effective.claim_delay_max_seconds,
        "telegram_enabled": effective.telegram_enabled,
    }
