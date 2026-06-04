"""Integration tests for GET/PATCH /api/account/settings."""
import pytest
from sqlmodel import select
from flowboard.db.models import Account
from flowboard.db import get_session
from flowboard.services import security


def test_get_settings_unconfigured(client, auth):
    resp = client.get("/api/account/settings", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] is None
    assert data["llm_api_key_configured"] is False


def test_patch_settings_stores_encrypted_key(client, auth, monkeypatch):
    monkeypatch.setattr(
        "flowboard.routes.account_settings._validate_api_key",
        lambda provider, key: None,
    )
    resp = client.patch(
        "/api/account/settings",
        json={"llm_provider": "gemini", "llm_api_key": "AIzaFakeKey"},
        headers=auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] == "gemini"
    assert data["llm_api_key_configured"] is True
    assert "llm_api_key" not in data  # raw key must never be returned

    with get_session() as s:
        acct = s.exec(
            select(Account).where(Account.email == "fixture@example.com")
        ).first()
    assert acct.llm_api_key_enc is not None
    assert security.decrypt_secret(acct.llm_api_key_enc) == "AIzaFakeKey"


def test_patch_settings_rejects_invalid_provider(client, auth):
    resp = client.patch(
        "/api/account/settings",
        json={"llm_provider": "unknown_provider", "llm_api_key": "key"},
        headers=auth,
    )
    assert resp.status_code == 422


def test_patch_settings_rejects_empty_key(client, auth):
    resp = client.patch(
        "/api/account/settings",
        json={"llm_provider": "gemini", "llm_api_key": "   "},
        headers=auth,
    )
    assert resp.status_code == 422


def test_patch_settings_rejects_bad_api_key(client, auth, monkeypatch):
    from flowboard.services.llm.base import LLMError

    def _raise(provider: str, key: str) -> None:
        raise LLMError("auth failed")

    monkeypatch.setattr("flowboard.routes.account_settings._validate_api_key", _raise)
    resp = client.patch(
        "/api/account/settings",
        json={"llm_provider": "gemini", "llm_api_key": "bad-key"},
        headers=auth,
    )
    assert resp.status_code == 422
    assert "auth failed" in resp.json()["detail"]


def test_get_settings_shows_configured_after_patch(client, auth, monkeypatch):
    monkeypatch.setattr(
        "flowboard.routes.account_settings._validate_api_key",
        lambda provider, key: None,
    )
    client.patch(
        "/api/account/settings",
        json={"llm_provider": "claude", "llm_api_key": "sk-ant-real"},
        headers=auth,
    )
    resp = client.get("/api/account/settings", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] == "claude"
    assert data["llm_api_key_configured"] is True


def test_settings_requires_auth(client):
    resp = client.get("/api/account/settings")
    assert resp.status_code == 401
    resp2 = client.patch(
        "/api/account/settings",
        json={"llm_provider": "gemini", "llm_api_key": "k"},
    )
    assert resp2.status_code == 401
