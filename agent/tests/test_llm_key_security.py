"""Verify LLM API keys are never exposed through the API or stored in plaintext."""
import pytest
from sqlmodel import select
from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.services import security

RAW_KEY = "AIzaSyFakeGeminiKey_ForTesting"


def _skip_validation(monkeypatch):
    monkeypatch.setattr(
        "flowboard.routes.account_settings._validate_api_key",
        lambda provider, key: None,
    )


def _save_key(client, auth, monkeypatch):
    _skip_validation(monkeypatch)
    resp = client.patch(
        "/api/account/settings",
        json={"llm_provider": "gemini", "llm_api_key": RAW_KEY},
        headers=auth,
    )
    assert resp.status_code == 200


def test_patch_response_never_exposes_raw_key(client, auth, monkeypatch):
    _save_key(client, auth, monkeypatch)
    resp = client.patch(
        "/api/account/settings",
        json={"llm_provider": "gemini", "llm_api_key": RAW_KEY},
        headers=auth,
    )
    assert RAW_KEY not in resp.text
    assert "llm_api_key" not in resp.json()


def test_get_response_never_exposes_raw_key(client, auth, monkeypatch):
    _save_key(client, auth, monkeypatch)
    resp = client.get("/api/account/settings", headers=auth)
    assert resp.status_code == 200
    assert RAW_KEY not in resp.text
    data = resp.json()
    assert "llm_api_key" not in data
    assert data["llm_api_key_configured"] is True


def test_key_stored_encrypted_not_plaintext(client, auth, monkeypatch):
    _save_key(client, auth, monkeypatch)
    with get_session() as s:
        acct = s.exec(
            select(Account).where(Account.email == "fixture@example.com")
        ).first()
    raw_bytes = RAW_KEY.encode()
    assert acct.llm_api_key_enc != raw_bytes
    assert raw_bytes not in (acct.llm_api_key_enc or b"")


def test_key_decryptable_to_original(client, auth, monkeypatch):
    _save_key(client, auth, monkeypatch)
    with get_session() as s:
        acct = s.exec(
            select(Account).where(Account.email == "fixture@example.com")
        ).first()
    assert security.decrypt_secret(acct.llm_api_key_enc) == RAW_KEY


def test_no_key_make_account_provider_returns_none():
    """make_account_provider must return None (not raise) when no key is configured."""
    from flowboard.db.models import Account
    from flowboard.services.llm.api_providers import make_account_provider
    acct = Account(id=99, email="nokey@example.com", password_hash="x")
    assert make_account_provider(acct) is None
