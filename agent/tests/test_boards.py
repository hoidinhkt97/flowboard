def _make_board(client, auth, name="Test"):
    return client.post("/api/boards", json={"name": name}, headers=auth).json()


def test_create_list_get_board(client, auth):
    r = client.post("/api/boards", json={"name": "Scene 01"}, headers=auth)
    assert r.status_code == 200
    board = r.json()
    assert board["name"] == "Scene 01"
    assert isinstance(board["id"], int)

    r = client.get("/api/boards", headers=auth)
    assert r.status_code == 200
    listing = r.json()
    assert any(b["id"] == board["id"] for b in listing)

    r = client.get(f"/api/boards/{board['id']}", headers=auth)
    assert r.status_code == 200
    detail = r.json()
    assert detail["board"]["id"] == board["id"]
    assert detail["nodes"] == []
    assert detail["edges"] == []


def test_get_missing_board_returns_404(client, auth):
    r = client.get("/api/boards/999", headers=auth)
    assert r.status_code == 404


def test_patch_board_rename(client, auth):
    b = client.post("/api/boards", json={"name": "Old"}, headers=auth).json()
    r = client.patch(f"/api/boards/{b['id']}", json={"name": "New"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["name"] == "New"

    # persistence
    r = client.get(f"/api/boards/{b['id']}", headers=auth)
    assert r.json()["board"]["name"] == "New"


def test_patch_missing_board_returns_404(client, auth):
    r = client.patch("/api/boards/999", json={"name": "x"}, headers=auth)
    assert r.status_code == 404


def test_delete_board_cascades_children(client, auth):
    """DELETE /api/boards/{id} must remove every child row that references
    the board so a re-create with the same id (sqlite autoincrement edge
    case) doesn't pull in orphan rows."""
    from flowboard.db import get_session
    from flowboard.db.models import (
        Asset,
        BoardFlowProject,
        ChatMessage,
        Edge,
        Node,
        PipelineRun,
        Plan,
        PlanRevision,
        Request,
    )
    from sqlmodel import select

    b = client.post("/api/boards", json={"name": "to-be-deleted"}, headers=auth).json()
    bid = b["id"]

    # Seed child rows directly via DB session to avoid auth complexity on
    # other routers that are not yet fully wired.
    with get_session() as s:
        n1 = Node(board_id=bid, short_id="aa01", type="image")
        n2 = Node(board_id=bid, short_id="aa02", type="video")
        s.add(n1)
        s.add(n2)
        s.commit()
        s.refresh(n1)
        s.refresh(n2)

        edge = Edge(board_id=bid, source_id=n1.id, target_id=n2.id)
        req = Request(node_id=n1.id, type="proxy",
                      params={"url": "https://aisandbox-pa.googleapis.com/v1/x"})
        asset = Asset(uuid_media_id="11111111-2222-3333-4444-555555555555",
                      node_id=n1.id, kind="image")
        chat = ChatMessage(board_id=bid, role="user", content="hi")
        plan = Plan(board_id=bid, spec={"k": "v"})
        s.add(edge)
        s.add(req)
        s.add(asset)
        s.add(chat)
        s.add(plan)
        s.commit()
        s.refresh(plan)
        s.add(PlanRevision(plan_id=plan.id, rev_no=1, spec={}, edits={}))
        s.add(PipelineRun(plan_id=plan.id, status="pending"))
        s.add(BoardFlowProject(board_id=bid, flow_project_id="fpfpfpfp"))
        s.commit()
        n1_id, n2_id = n1.id, n2.id

    # Delete.
    r = client.delete(f"/api/boards/{bid}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": bid}

    # Board itself gone.
    assert client.get(f"/api/boards/{bid}", headers=auth).status_code == 404

    # Every child table swept.
    with get_session() as s:
        for table, where in [
            (Node, Node.board_id == bid),
            (Edge, Edge.board_id == bid),
            (ChatMessage, ChatMessage.board_id == bid),
            (Plan, Plan.board_id == bid),
            (BoardFlowProject, BoardFlowProject.board_id == bid),
        ]:
            rows = s.exec(select(table).where(where)).all()
            assert rows == [], f"{table.__name__} not cleared: {rows}"
        # Asset / Request reference node_id, which no longer exists.
        assert s.exec(select(Asset).where(Asset.node_id.in_([n1_id, n2_id]))).all() == []
        assert s.exec(select(Request).where(Request.node_id.in_([n1_id, n2_id]))).all() == []


def test_delete_missing_board_returns_404(client, auth):
    r = client.delete("/api/boards/999", headers=auth)
    assert r.status_code == 404
