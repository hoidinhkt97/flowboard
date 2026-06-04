def _token(client, email):
    client.post("/api/account/register", json={"email": email, "password": "pw123456"})
    return client.post("/api/account/login",
                       json={"email": email, "password": "pw123456"}).json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_account_only_sees_own_boards(client):
    a = _token(client, "a@example.com")
    b = _token(client, "b@example.com")
    client.post("/api/boards", json={"name": "A-board"}, headers=_auth(a))

    a_list = client.get("/api/boards", headers=_auth(a)).json()
    b_list = client.get("/api/boards", headers=_auth(b)).json()
    assert any(x["name"] == "A-board" for x in a_list)
    assert b_list == []


def test_cross_tenant_board_get_is_404(client):
    a = _token(client, "a2@example.com")
    b = _token(client, "b2@example.com")
    board = client.post("/api/boards", json={"name": "secret"}, headers=_auth(a)).json()
    r = client.get(f"/api/boards/{board['id']}", headers=_auth(b))
    assert r.status_code == 404


def test_unauthenticated_board_access_is_401(client):
    assert client.get("/api/boards").status_code == 401
