def _login(client, email="ref@example.com", pw="pw123456"):
    client.post("/api/account/register", json={"email": email, "password": pw})
    return client.post("/api/account/login", json={"email": email, "password": pw})


def test_refresh_with_cookie_returns_new_access_token(client):
    _login(client)
    r = client.post("/api/account/refresh")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["access_token"], str) and r.json()["access_token"]


def test_refresh_without_cookie_is_401(client):
    r = client.post("/api/account/refresh")
    assert r.status_code == 401
