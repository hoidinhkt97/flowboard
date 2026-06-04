"""Multi-tenant isolation tests.

Alice creates boards/nodes/assets. Bob tries to access them.
Every cross-tenant access must return 404 — never 403 or 200.
"""
import pytest
from flowboard.db import get_session
from flowboard.db.models import Asset


# ── helpers ──────────────────────────────────────────────────────────────────

def _register(client, email: str, password: str = "password123") -> None:
    r = client.post("/api/account/register", json={"email": email, "password": password})
    assert r.status_code == 200, f"register failed for {email}: {r.text}"


def _login(client, email: str, password: str = "password123") -> dict:
    r = client.post("/api/account/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_board(client, auth: dict, name: str = "Test Board") -> int:
    r = client.post("/api/boards", json={"name": name}, headers=auth)
    assert r.status_code == 200, f"create board failed: {r.text}"
    return r.json()["id"]


def _create_node(client, auth: dict, board_id: int) -> int:
    r = client.post(
        "/api/nodes",
        json={"board_id": board_id, "type": "note", "x": 0, "y": 0},
        headers=auth,
    )
    assert r.status_code == 200, f"create node failed: {r.text}"
    return r.json()["id"]


def _get_account_id(client, auth: dict) -> int:
    r = client.get("/api/account/me", headers=auth)
    assert r.status_code == 200
    return r.json()["id"]


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def alice(client):
    _register(client, "alice@example.com")
    return _login(client, "alice@example.com")


@pytest.fixture()
def bob(client):
    _register(client, "bob@example.com")
    return _login(client, "bob@example.com")


@pytest.fixture()
def alice_board(client, alice) -> int:
    return _create_board(client, alice)


@pytest.fixture()
def alice_node(client, alice, alice_board) -> int:
    return _create_node(client, alice, alice_board)


# ── board isolation ───────────────────────────────────────────────────────────

def test_bob_cannot_get_alice_board(client, bob, alice_board):
    resp = client.get(f"/api/boards/{alice_board}", headers=bob)
    assert resp.status_code == 404


def test_bob_cannot_patch_alice_board(client, bob, alice_board):
    resp = client.patch(
        f"/api/boards/{alice_board}",
        json={"name": "Hacked"},
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_delete_alice_board(client, bob, alice_board):
    resp = client.delete(f"/api/boards/{alice_board}", headers=bob)
    assert resp.status_code == 404


def test_board_list_scoped_to_account(client, alice, bob, alice_board):
    alice_resp = client.get("/api/boards", headers=alice)
    bob_resp = client.get("/api/boards", headers=bob)
    alice_ids = {b["id"] for b in alice_resp.json()}
    bob_ids = {b["id"] for b in bob_resp.json()}
    assert alice_board in alice_ids
    assert alice_board not in bob_ids


# ── node isolation ────────────────────────────────────────────────────────────

def test_bob_cannot_get_alice_node(client, bob, alice_board, alice_node):
    # Nodes are fetched via the board GET; board isolation means bob cannot
    # see alice's nodes either. Verify via the board endpoint (nodes are
    # embedded in the board response).
    resp = client.get(f"/api/boards/{alice_board}", headers=bob)
    assert resp.status_code == 404


def test_bob_cannot_patch_alice_node(client, bob, alice_board, alice_node):
    resp = client.patch(
        f"/api/nodes/{alice_node}",
        json={"data": {"text": "hacked"}},
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_delete_alice_node(client, bob, alice_board, alice_node):
    resp = client.delete(f"/api/nodes/{alice_node}", headers=bob)
    assert resp.status_code == 404


def test_bob_cannot_create_node_on_alice_board(client, bob, alice_board):
    resp = client.post(
        "/api/nodes",
        json={"board_id": alice_board, "type": "note", "x": 0, "y": 0},
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_list_alice_nodes(client, bob, alice_board):
    # Listing nodes requires knowing the board_id; querying by alice's board as bob
    # should 404 because bob doesn't own the board.
    resp = client.get(f"/api/boards/{alice_board}", headers=bob)
    assert resp.status_code == 404


# ── asset isolation ───────────────────────────────────────────────────────────

def test_bob_cannot_get_presigned_url_for_alice_asset(client, alice, bob):
    """GET /api/media/{id}/url must return 404 for a different account's asset."""
    media_id = "ffffffffffffffffffffffffffffffffffffffff"
    alice_id = _get_account_id(client, alice)

    with get_session() as s:
        s.add(Asset(
            uuid_media_id=media_id,
            kind="image",
            mime="image/jpeg",
            account_id=alice_id,
            s3_key=f"{alice_id}/{media_id}.jpg",
        ))
        s.commit()

    resp = client.get(f"/api/media/{media_id}/url", headers=bob)
    assert resp.status_code == 404
