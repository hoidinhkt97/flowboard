"""Shared FastAPI dependencies for tenant-aware routes."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.services.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_account(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Account:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = decode_access_token(creds.credentials)
        account_id = int(claims["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    with get_session() as s:
        acct = s.get(Account, account_id)
    if acct is None:
        raise HTTPException(status_code=401, detail="account not found")
    return acct
