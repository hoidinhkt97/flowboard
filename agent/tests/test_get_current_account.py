import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.deps import get_current_account
from flowboard.services.security import create_access_token


@pytest.fixture
def mini_app():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(acct: Account = Depends(get_current_account)):
        return {"id": acct.id, "email": acct.email}

    return TestClient(app)


def _make_account(email="dep@example.com") -> int:
    with get_session() as s:
        a = Account(email=email, password_hash="x")
        s.add(a); s.commit(); s.refresh(a)
        return a.id


def test_valid_token_resolves_account(mini_app):
    aid = _make_account()
    tok = create_access_token(aid)
    r = mini_app.get("/whoami", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json() == {"id": aid, "email": "dep@example.com"}


def test_missing_header_is_401(mini_app):
    assert mini_app.get("/whoami").status_code == 401


def test_garbage_token_is_401(mini_app):
    r = mini_app.get("/whoami", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
