from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.domain.errors import NotFoundError


def _auth_state(request: Request):
    return request.app.state.auth_service


def _account_state(request: Request):
    return request.app.state.account_service


def _db(request: Request):
    return request.app.state.database


router = APIRouter(prefix="/api")


@router.post("/accounts/{account_id}/authenticate")
def authenticate(account_id: int, request: Request):
    try:
        session = _auth_state(request).start(account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if session.status == "unavailable":
        raise HTTPException(status_code=503, detail=session.error)
    return {
        "token": session.token,
        "screen_url": session.screen_url,
        "status": session.status,
    }


@router.get("/auth/{token}")
def auth_status(token: str, request: Request):
    session = _auth_state(request).get(token)
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
    _auth_state(request).revoke(token)
    return {"status": "revoked"}


@router.post("/accounts/{account_id}/resolve-intervention")
def resolve_intervention(account_id: int, request: Request):
    try:
        with _db(request).connect() as connection:
            account = _account_state(request).resolve_intervention(connection, account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": account.id,
        "state": account.state,
        "display_name": account.display_name,
    }
