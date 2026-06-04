def _login_token(client, email="me@example.com", pw="pw123456"):
    client.post("/api/account/register", json={"email": email, "password": pw})
    return client.post("/api/account/login",
                       json={"email": email, "password": pw}).json()["access_token"]


def test_me_returns_account_for_valid_token(client):
    tok = _login_token(client)
    r = client.get("/api/account/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "me@example.com"
    assert "password_hash" not in body
    assert body["llm_provider"] is None


def test_me_without_token_is_401(client):
    assert client.get("/api/account/me").status_code == 401
