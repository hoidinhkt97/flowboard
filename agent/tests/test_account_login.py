def _register(client, email="login@example.com", pw="pw123456"):
    client.post("/api/account/register", json={"email": email, "password": pw})


def test_login_returns_access_token_and_sets_refresh_cookie(client):
    _register(client)
    r = client.post("/api/account/login",
                    json={"email": "login@example.com", "password": "pw123456"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert "fb_refresh" in r.cookies


def test_login_rejects_wrong_password(client):
    _register(client)
    r = client.post("/api/account/login",
                    json={"email": "login@example.com", "password": "WRONG"})
    assert r.status_code == 401


def test_login_rejects_unknown_email(client):
    r = client.post("/api/account/login",
                    json={"email": "ghost@example.com", "password": "pw123456"})
    assert r.status_code == 401
