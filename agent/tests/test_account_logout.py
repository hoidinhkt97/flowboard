def _login(client, email="lo@example.com", pw="pw123456"):
    client.post("/api/account/register", json={"email": email, "password": pw})
    return client.post("/api/account/login", json={"email": email, "password": pw})


def test_logout_revokes_refresh_then_refresh_fails(client):
    _login(client)
    assert client.post("/api/account/logout").status_code == 200
    assert client.post("/api/account/refresh").status_code == 401


def test_logout_without_cookie_is_ok(client):
    r = client.post("/api/account/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
