def test_register_creates_account(client):
    r = client.post("/api/account/register",
                    json={"email": "new@example.com", "password": "pw123456"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "new@example.com"
    assert isinstance(body["id"], int)
    assert "password" not in body and "password_hash" not in body


def test_register_rejects_duplicate_email(client):
    client.post("/api/account/register",
                json={"email": "dup@example.com", "password": "pw123456"})
    r = client.post("/api/account/register",
                    json={"email": "dup@example.com", "password": "pw123456"})
    assert r.status_code == 409
