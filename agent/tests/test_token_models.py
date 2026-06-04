from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken, RefreshToken
from sqlmodel import select


def _make_account(s) -> int:
    a = Account(email="t@example.com", password_hash="x")
    s.add(a)
    s.commit()
    s.refresh(a)
    return a.id


def test_refresh_token_round_trips():
    with get_session() as s:
        aid = _make_account(s)
        s.add(RefreshToken(account_id=aid, token_hash="abc"))
        s.commit()
        row = s.exec(select(RefreshToken).where(RefreshToken.token_hash == "abc")).one()
        assert row.account_id == aid
        assert row.revoked_at is None


def test_device_token_round_trips():
    with get_session() as s:
        aid = _make_account(s)
        s.add(DeviceToken(account_id=aid, token_hash="dev", label="chrome"))
        s.commit()
        row = s.exec(select(DeviceToken).where(DeviceToken.token_hash == "dev")).one()
        assert row.account_id == aid
        assert row.label == "chrome"
        assert row.revoked_at is None
