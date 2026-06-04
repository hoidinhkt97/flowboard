import pytest
from fastapi import HTTPException

from flowboard.db import get_session
from flowboard.db.models import Account, Board
from flowboard.db.scoping import owned_or_404


def _account(s, email):
    a = Account(email=email, password_hash="x")
    s.add(a); s.commit(); s.refresh(a)
    return a.id


def test_owned_or_404_returns_row_for_owner():
    with get_session() as s:
        aid = _account(s, "owner@example.com")
        b = Board(name="b", account_id=aid)
        s.add(b); s.commit(); s.refresh(b)
        got = owned_or_404(s, Board, b.id, aid)
        assert got.id == b.id


def test_owned_or_404_raises_404_for_other_account():
    with get_session() as s:
        owner = _account(s, "owner2@example.com")
        other = _account(s, "other@example.com")
        b = Board(name="b", account_id=owner)
        s.add(b); s.commit(); s.refresh(b)
        with pytest.raises(HTTPException) as ei:
            owned_or_404(s, Board, b.id, other)
        assert ei.value.status_code == 404


def test_owned_or_404_raises_404_for_missing_row():
    with get_session() as s:
        aid = _account(s, "owner3@example.com")
        with pytest.raises(HTTPException) as ei:
            owned_or_404(s, Board, 999999, aid)
        assert ei.value.status_code == 404
