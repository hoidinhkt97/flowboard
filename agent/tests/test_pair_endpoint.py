"""Tests for POST /api/extension/pair."""
from datetime import datetime, timezone

from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import RefreshToken
from flowboard.services.security import hash_token


def _seed_refresh_token(client) -> str:
    client.post("/api/account/register",
                json={"email": "pair@example.com", "password": "pw123456"})
    resp = client.post("/api/account/login",
                       json={"email": "pair@example.com", "password": "pw123456"})
    set_cookie = resp.headers.get("set-cookie", "")
    raw = None
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith("fb_refresh="):
            raw = part[len("fb_refresh="):]
            break
    assert raw, f"fb_refresh not found in Set-Cookie: {set_cookie}"
    return raw


def test_pair_returns_device_token(client):
    raw = _seed_refresh_token(client)
    r = client.post("/api/extension/pair", cookies={"fb_refresh": raw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "device_token" in body
    assert len(body["device_token"]) >= 32


def test_pair_without_cookie_is_401(client):
    assert client.post("/api/extension/pair").status_code == 401


def test_pair_with_invalid_cookie_is_401(client):
    r = client.post("/api/extension/pair", cookies={"fb_refresh": "bad-token"})
    assert r.status_code == 401


def test_pair_twice_returns_different_tokens(client):
    raw = _seed_refresh_token(client)
    t1 = client.post("/api/extension/pair", cookies={"fb_refresh": raw}).json()["device_token"]
    t2 = client.post("/api/extension/pair", cookies={"fb_refresh": raw}).json()["device_token"]
    assert t1 != t2


def test_pair_with_revoked_refresh_is_401(client):
    raw = _seed_refresh_token(client)
    with get_session() as s:
        row = s.exec(select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw))).first()
        row.revoked_at = datetime.now(timezone.utc)
        s.add(row); s.commit()
    r = client.post("/api/extension/pair", cookies={"fb_refresh": raw})
    assert r.status_code == 401
