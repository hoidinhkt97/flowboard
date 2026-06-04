"""Tests for Run 2 polish: enum constraints, coord bounds, FK enforcement."""


def _board(client, auth):
    return client.post("/api/boards", json={"name": "T"}, headers=auth).json()


def test_node_type_enum_rejects_unknown(client, auth):
    b = _board(client, auth)
    r = client.post("/api/nodes", json={"board_id": b["id"], "type": "robot"}, headers=auth)
    assert r.status_code == 422


def test_node_status_enum_rejects_unknown_on_update(client, auth):
    b = _board(client, auth)
    n = client.post(
        "/api/nodes", json={"board_id": b["id"], "type": "image"}, headers=auth
    ).json()
    r = client.patch(f"/api/nodes/{n['id']}", json={"status": "cooking"}, headers=auth)
    assert r.status_code == 422


def test_node_coord_upper_bound(client, auth):
    b = _board(client, auth)
    r = client.post(
        "/api/nodes",
        json={"board_id": b["id"], "type": "image", "x": 1e8, "y": 0},
        headers=auth,
    )
    assert r.status_code == 422


def test_node_coord_lower_bound(client, auth):
    b = _board(client, auth)
    r = client.post(
        "/api/nodes",
        json={"board_id": b["id"], "type": "image", "x": -1e8, "y": 0},
        headers=auth,
    )
    assert r.status_code == 422


def test_node_size_must_be_positive(client, auth):
    b = _board(client, auth)
    r = client.post(
        "/api/nodes",
        json={"board_id": b["id"], "type": "image", "w": 0, "h": 10},
        headers=auth,
    )
    assert r.status_code == 422


def test_edge_kind_enum_rejects_unknown(client, auth):
    b = _board(client, auth)
    a = client.post("/api/nodes", json={"board_id": b["id"], "type": "image"}, headers=auth).json()
    c = client.post("/api/nodes", json={"board_id": b["id"], "type": "image"}, headers=auth).json()
    r = client.post(
        "/api/edges",
        json={
            "board_id": b["id"],
            "source_id": a["id"],
            "target_id": c["id"],
            "kind": "spaghetti",
        },
    )
    assert r.status_code == 422


def test_node_on_missing_board_returns_404(client, auth):
    """With the existence check in Run 2, orphan nodes are rejected before FK."""
    r = client.post("/api/nodes", json={"board_id": 9999, "type": "image"}, headers=auth)
    assert r.status_code == 404
