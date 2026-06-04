"""Integration tests for the /ext WebSocket endpoint."""
import pytest
from starlette.websockets import WebSocketDisconnect

from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken
from flowboard.services.registry import registry
from flowboard.services.security import generate_token, hash_token


def _create_device_token(email: str) -> tuple[int, str]:
    """Seed an account + device token; return (account_id, raw_token)."""
    with get_session() as s:
        acct = Account(email=email, password_hash="x")
        s.add(acct); s.commit(); s.refresh(acct)
        raw = generate_token()
        s.add(DeviceToken(account_id=acct.id, token_hash=hash_token(raw)))
        s.commit()
        return acct.id, raw


def test_valid_token_connects_and_registers(client):
    account_id, raw = _create_device_token("ws1@example.com")
    with client.websocket_connect(f"/ext?token={raw}"):
        assert registry.is_online(account_id)
    assert not registry.is_online(account_id)


def test_invalid_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ext?token=not-a-real-token"):
            pass
    assert exc_info.value.code == 4401


def test_missing_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ext"):
            pass
    assert exc_info.value.code == 4401


def test_revoked_token_is_rejected(client):
    from datetime import datetime, timezone
    from sqlmodel import select
    account_id, raw = _create_device_token("ws4@example.com")
    with get_session() as s:
        dt = s.exec(select(DeviceToken).where(
            DeviceToken.token_hash == hash_token(raw))).one()
        dt.revoked_at = datetime.now(timezone.utc)
        s.add(dt); s.commit()
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ext?token={raw}"):
            pass
    assert exc_info.value.code == 4401
