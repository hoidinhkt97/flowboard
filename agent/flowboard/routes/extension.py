"""Extension pairing: mint a DeviceToken from the refresh cookie."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import DeviceToken, RefreshToken
from flowboard.services.security import generate_token, hash_token

router = APIRouter(prefix="/api/extension", tags=["extension"])


@router.post("/pair")
def pair(fb_refresh: str | None = Cookie(default=None)):
    if not fb_refresh:
        raise HTTPException(status_code=401, detail="missing refresh cookie")

    with get_session() as s:
        row = s.exec(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(fb_refresh))
        ).first()
        if row is None or row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="invalid refresh token")
        expires = row.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires is not None and expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="refresh token expired")

        raw = generate_token()
        s.add(DeviceToken(
            account_id=row.account_id,
            token_hash=hash_token(raw),
            label="chrome",
        ))
        s.commit()

    return {"device_token": raw}
