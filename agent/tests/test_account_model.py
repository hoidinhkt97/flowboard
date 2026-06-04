from flowboard.db import get_session
from flowboard.db.models import Account
from sqlmodel import select


def test_account_round_trips():
    with get_session() as s:
        acct = Account(email="a@example.com", password_hash="x")
        s.add(acct)
        s.commit()
        s.refresh(acct)
        assert isinstance(acct.id, int)

    with get_session() as s:
        got = s.exec(select(Account).where(Account.email == "a@example.com")).one()
        assert got.password_hash == "x"
        assert got.llm_provider is None
        assert got.llm_api_key_enc is None
