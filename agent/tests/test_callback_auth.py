"""Tests for /api/ext/callback with X-Device-Token auth."""
import asyncio
import pytest
from datetime import datetime, timezone
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken
from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import registry
from flowboard.services.security import generate_token, hash_token


def _seed(email: str) -> tuple[int, str]:
    with get_session() as s:
        acct = Account(email=email, password_hash="x")
        s.add(acct); s.commit(); s.refresh(acct)
        raw = generate_token()
        s.add(DeviceToken(account_id=acct.id, token_hash=hash_token(raw)))
        s.commit()
        return acct.id, raw


def test_callback_rejects_missing_token(client):
    r = client.post("/api/ext/callback", json={"id": "x", "status": 200, "data": {}})
    assert r.status_code == 401


def test_callback_rejects_unknown_token(client):
    r = client.post("/api/ext/callback",
                    json={"id": "x", "status": 200, "data": {}},
                    headers={"X-Device-Token": generate_token()})
    assert r.status_code == 401


def test_callback_rejects_revoked_token(client):
    account_id, raw = _seed("cb2@example.com")
    with get_session() as s:
        dt = s.exec(select(DeviceToken).where(DeviceToken.token_hash == hash_token(raw))).one()
        dt.revoked_at = datetime.now(timezone.utc)
        s.add(dt); s.commit()
    r = client.post("/api/ext/callback",
                    json={"id": "x", "status": 200, "data": {}},
                    headers={"X-Device-Token": raw})
    assert r.status_code == 401


def test_callback_ok_no_pending_match(client):
    account_id, raw = _seed("cb3@example.com")
    r = client.post("/api/ext/callback",
                    json={"id": "no-match", "status": 200, "data": {}},
                    headers={"X-Device-Token": raw})
    assert r.status_code == 200
    assert r.json() == {"ok": False}


@pytest.mark.asyncio
async def test_callback_resolves_pending_future(client):
    account_id, raw = _seed("cb4@example.com")
    fc = FlowClient()
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    fc._pending["probe-id"] = fut
    registry._conns[account_id] = (fc, None)
    try:
        r = client.post("/api/ext/callback",
                        json={"id": "probe-id", "status": 200, "data": {"ok": True}},
                        headers={"X-Device-Token": raw})
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        resolved = await asyncio.wait_for(fut, timeout=1.0)
        assert resolved["data"] == {"ok": True}
    finally:
        registry._conns.pop(account_id, None)
