"""Email/password account auth (multi-tenant). Distinct from routes/auth.py,
which is the extension-identity surface (/api/auth/*)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlmodel import select

from flowboard.config import REFRESH_TOKEN_TTL_DAYS
from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken, RefreshToken
from flowboard.deps import get_current_account
from flowboard.services.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)

router = APIRouter(prefix="/api/account", tags=["account"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
def register(body: RegisterBody):
    with get_session() as s:
        exists = s.exec(select(Account).where(Account.email == body.email)).first()
        if exists:
            raise HTTPException(status_code=409, detail="email already registered")
        acct = Account(email=str(body.email), password_hash=hash_password(body.password))
        s.add(acct)
        s.commit()
        s.refresh(acct)
        return {"id": acct.id, "email": acct.email}


@router.post("/login")
def login(body: LoginBody, response: Response):
    with get_session() as s:
        acct = s.exec(select(Account).where(Account.email == body.email)).first()
        if acct is None or not verify_password(body.password, acct.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")

        raw_refresh = generate_token()
        s.add(RefreshToken(
            account_id=acct.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
        ))
        s.commit()
        access = create_access_token(acct.id)

    response.set_cookie(
        key="fb_refresh",
        value=raw_refresh,
        httponly=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_TTL_DAYS * 24 * 3600,
        path="/api/account",
    )
    return {"access_token": access, "token_type": "bearer"}


@router.post("/refresh")
def refresh(fb_refresh: str | None = Cookie(default=None)):
    if not fb_refresh:
        raise HTTPException(status_code=401, detail="missing refresh cookie")
    with get_session() as s:
        row = s.exec(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(fb_refresh))
        ).first()
        if row is None or row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="invalid refresh token")
        if row.expires_at is not None and row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="refresh token expired")
        access = create_access_token(row.account_id)
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response, fb_refresh: str | None = Cookie(default=None)):
    if fb_refresh:
        now = datetime.now(timezone.utc)
        with get_session() as s:
            row = s.exec(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(fb_refresh))
            ).first()
            if row is not None and row.revoked_at is None:
                row.revoked_at = now
                s.add(row)
                devs = s.exec(
                    select(DeviceToken).where(
                        DeviceToken.account_id == row.account_id,
                        DeviceToken.revoked_at.is_(None),
                    )
                ).all()
                for d in devs:
                    d.revoked_at = now
                    s.add(d)
                s.commit()
    response.delete_cookie("fb_refresh", path="/api/account")
    return {"ok": True}


@router.get("/me")
def me(acct: Account = Depends(get_current_account)):
    return {
        "id": acct.id,
        "email": acct.email,
        "llm_provider": acct.llm_provider,
        "google_email": acct.google_email,
        "google_name": acct.google_name,
        "google_picture": acct.google_picture,
    }
