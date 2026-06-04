from flowboard.db import get_session
from flowboard.db.models import Account, Asset, Board, Node, Request


def test_board_and_children_carry_account_id():
    with get_session() as s:
        a = Account(email="own@example.com", password_hash="x")
        s.add(a)
        s.commit()
        s.refresh(a)

        b = Board(name="B", account_id=a.id)
        s.add(b)
        s.commit()
        s.refresh(b)
        assert b.account_id == a.id

        n = Node(board_id=b.id, account_id=a.id, short_id="n1", type="image")
        r = Request(type="proxy", account_id=a.id)
        asset = Asset(kind="image", account_id=a.id)
        s.add(n); s.add(r); s.add(asset)
        s.commit()
        s.refresh(n); s.refresh(r); s.refresh(asset)
        assert n.account_id == a.id
        assert r.account_id == a.id
        assert asset.account_id == a.id
