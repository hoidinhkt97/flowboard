def _token(client, email):
    client.post("/api/account/register", json={"email": email, "password": "pw123456"})
    return client.post("/api/account/login",
                       json={"email": email, "password": "pw123456"}).json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_nodes_are_scoped_to_account(client):
    a = _token(client, "na@example.com")
    b = _token(client, "nb@example.com")
    board = client.post("/api/boards", json={"name": "A"}, headers=_auth(a)).json()
    node = client.post("/api/nodes",
                       json={"board_id": board["id"], "type": "image"},
                       headers=_auth(a)).json()
    assert "id" in node
    r = client.post("/api/nodes",
                    json={"board_id": board["id"], "type": "image"},
                    headers=_auth(b))
    assert r.status_code == 404


def test_unauthenticated_node_create_is_401(client):
    assert client.post("/api/nodes", json={"board_id": 1, "type": "image"}).status_code == 401
