"""Tests for /api/auth/* routes and the WS user_info inbound message handler."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from flowboard.routes.auth import _reset_db_tier_cache_for_tests
from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import registry


def _get_fc(auth_headers: dict, client) -> FlowClient:
    """Return (or create) the FlowClient for the fixture account (id=1)."""
    fc = registry.get(1)
    if fc is None:
        fc = FlowClient()
        registry._conns[1] = (fc, None)
    return fc


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test gets a clean registry entry for account 1."""
    # Clean slate
    registry._conns.pop(1, None)
    _reset_db_tier_cache_for_tests()
    yield
    registry._conns.pop(1, None)
    _reset_db_tier_cache_for_tests()


def test_me_returns_null_fields_when_no_data_yet(client, auth):
    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "email": None,
        "name": None,
        "picture": None,
        "verified_email": None,
        "paygate_tier": None,
        "sku": None,
        "credits": None,
    }


def test_me_returns_cached_profile_after_user_info_message(client, auth):
    """Simulate the extension pushing a user_info WS message — the
    route must surface the profile straight from the registry FlowClient."""
    fc = FlowClient()
    fc._user_info = {
        "email": "tuan@example.com",
        "name": "Tuan Nguyen",
        "picture": "https://example.com/avatar.png",
        "verified_email": True,
    }
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    registry._conns[1] = (fc, None)

    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "tuan@example.com"
    assert body["name"] == "Tuan Nguyen"
    assert body["picture"] == "https://example.com/avatar.png"
    assert body["verified_email"] is True
    assert body["paygate_tier"] == "PAYGATE_TIER_TWO"
    assert "id" not in body
    assert "locale" not in body


@pytest.mark.asyncio
async def test_handle_message_caches_user_info():
    """The user_info WS frame from the extension populates
    fc._user_info and is visible via the public property."""
    fc = FlowClient()
    await fc.handle_message({
        "type": "user_info",
        "userInfo": {
            "email": "x@example.com",
            "name": "X User",
            "picture": "https://example.com/p.png",
        },
    })
    assert fc.user_info == {
        "email": "x@example.com",
        "name": "X User",
        "picture": "https://example.com/p.png",
    }


@pytest.mark.asyncio
async def test_handle_message_strips_extra_userinfo_fields():
    """Defense-in-depth — only the four whitelisted keys are cached."""
    fc = FlowClient()
    await fc.handle_message({
        "type": "user_info",
        "userInfo": {
            "email": "u@example.com",
            "name": "U",
            "picture": "https://x/p.png",
            "verified_email": True,
            "id": "1234567890",
            "locale": "vi",
            "hd": "example.com",
            "given_name": "U",
            "family_name": "Surname",
            "__proto__": "bad",
        },
    })
    info = fc.user_info
    assert info is not None
    assert set(info.keys()) == {"email", "name", "picture", "verified_email"}


@pytest.mark.asyncio
async def test_handle_message_ignores_non_dict_userinfo():
    """Defensive — a malformed frame must not crash the handler."""
    fc = FlowClient()
    fc._user_info = {"email": "kept@example.com"}
    await fc.handle_message({"type": "user_info", "userInfo": "garbage"})
    assert fc.user_info == {"email": "kept@example.com"}


@pytest.mark.asyncio
async def test_clear_extension_drops_cached_userinfo_and_tier():
    """When the extension disconnects we drop the cached profile + tier."""
    fc = FlowClient()
    fc._user_info = {"email": "stale@example.com"}
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    fc.clear_extension()
    assert fc.user_info is None
    assert fc.paygate_tier is None


@pytest.mark.asyncio
async def test_fetch_paygate_tier_resolves_authoritatively(monkeypatch):
    """Happy path — Bearer token cached, /v1/credits returns 200 with a known tier."""
    import httpx
    fc = FlowClient()
    fc._flow_key = "ya29.fake-bearer-token"
    fc._paygate_tier = None
    fc._sku = None
    fc._credits = None

    captured: dict = {}

    class _MockResponse:
        status_code = 200
        def json(self):
            return {
                "credits": 24340,
                "userPaygateTier": "PAYGATE_TIER_TWO",
                "sku": "WS_ULTRA",
                "serviceTier": "SERVICE_TIER_ADVANCED",
                "subscriptionCredits": 24340,
            }

    class _MockClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            captured["headers"] = kwargs.get("headers")
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    ok = await fc.fetch_paygate_tier()
    assert ok is True
    assert fc.paygate_tier == "PAYGATE_TIER_TWO"
    assert fc.sku == "WS_ULTRA"
    assert fc.credits == 24340
    assert captured["url"] == "https://aisandbox-pa.googleapis.com/v1/credits"
    assert captured["params"]["key"].startswith("AIza")
    assert captured["headers"]["authorization"] == "Bearer ya29.fake-bearer-token"
    assert captured["headers"]["origin"] == "https://labs.google"


@pytest.mark.asyncio
async def test_fetch_paygate_tier_returns_false_without_token():
    """No Bearer token cached → fetch is a no-op, returns False."""
    fc = FlowClient()
    fc._flow_key = None
    fc._paygate_tier = None
    ok = await fc.fetch_paygate_tier()
    assert ok is False
    assert fc.paygate_tier is None


@pytest.mark.asyncio
async def test_fetch_paygate_tier_handles_expired_token(monkeypatch):
    """HTTP 401 from /v1/credits = token expired. Returns False, doesn't poison cache."""
    import httpx
    fc = FlowClient()
    fc._flow_key = "ya29.expired"
    fc._paygate_tier = None

    class _MockResponse:
        status_code = 401
        def json(self):
            return {"error": "unauthenticated"}

    class _MockClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs):
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    ok = await fc.fetch_paygate_tier()
    assert ok is False
    assert fc.paygate_tier is None


@pytest.mark.asyncio
async def test_fetch_paygate_tier_rejects_unknown_tier_value(monkeypatch):
    """Unknown tier value must NOT silently set the cache."""
    import httpx
    fc = FlowClient()
    fc._flow_key = "ya29.fake"
    fc._paygate_tier = None

    class _MockResponse:
        status_code = 200
        def json(self):
            return {"userPaygateTier": "PAYGATE_TIER_FUTURE", "credits": 100}

    class _MockClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs):
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    ok = await fc.fetch_paygate_tier()
    assert ok is False
    assert fc.paygate_tier is None


def test_logout_clears_cached_identity_and_tier(client, auth):
    """POST /api/auth/logout drops the cached profile + tier."""
    fc = FlowClient()
    fc._user_info = {
        "email": "u@example.com", "name": "U",
        "picture": "https://x/p.png", "verified_email": True,
    }
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    registry._conns[1] = (fc, None)

    r = client.post("/api/auth/logout", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "extension_notified": False}

    me = client.get("/api/auth/me", headers=auth).json()
    assert me["email"] is None
    assert me["paygate_tier"] is None


def test_logout_notifies_extension_when_ws_connected(client, auth):
    """When the WebSocket is open, /logout pushes a `logout` message."""
    sent: list[dict] = []

    class _FakeWs:
        async def send(self, payload):
            import json
            sent.append(json.loads(payload))

    fc = FlowClient()
    fc.set_extension(_FakeWs())
    fc._user_info = {"email": "u@example.com"}
    registry._conns[1] = (fc, _FakeWs())

    r = client.post("/api/auth/logout", headers=auth)
    assert r.status_code == 200
    assert r.json()["extension_notified"] is True
    assert sent == [{"type": "logout"}]
    assert fc.user_info is None


def test_scan_reports_disconnected_state_when_no_extension(client, auth):
    """No registry entry → scan reports disconnected cleanly."""
    registry._conns.pop(1, None)

    r = client.post("/api/auth/scan", headers=auth)
    assert r.status_code == 200
    assert r.json() == {
        "extension_connected": False,
        "has_user_info": False,
        "has_paygate_tier": False,
        "userinfo_nudged": False,
        "tier_fetched": False,
    }


def test_scan_nudges_extension_when_connected_but_userinfo_empty(client, auth):
    """WS open + agent has no cached profile → scan asks extension to re-fetch."""
    sent: list[dict] = []

    class _FakeWs:
        async def send(self, payload):
            import json
            sent.append(json.loads(payload))

    fc = FlowClient()
    fc.set_extension(_FakeWs())
    fc._user_info = None
    fc._paygate_tier = None
    registry._conns[1] = (fc, _FakeWs())

    r = client.post("/api/auth/scan", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["extension_connected"] is True
    assert body["has_user_info"] is False
    assert body["userinfo_nudged"] is True
    assert sent == [{"type": "please_resend_userinfo"}]


def test_scan_does_not_nudge_when_userinfo_already_cached(client, auth):
    """Cache already populated → no nudge needed."""
    sent: list[dict] = []

    class _FakeWs:
        async def send(self, payload):
            import json
            sent.append(json.loads(payload))

    fc = FlowClient()
    fc.set_extension(_FakeWs())
    fc._user_info = {"email": "u@example.com"}
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    registry._conns[1] = (fc, _FakeWs())

    r = client.post("/api/auth/scan", headers=auth)
    assert r.json()["userinfo_nudged"] is False
    assert sent == []


def test_me_returns_null_tier_when_extension_has_not_pushed(client, auth):
    """Regression guard: /api/auth/me returns null paygate_tier when not set."""
    # No fc in registry → returns all nulls
    registry._conns.pop(1, None)

    from flowboard.db import get_session
    from flowboard.db.models import Request
    with get_session() as s:
        s.add(Request(
            type="gen_image",
            status="done",
            params={"paygate_tier": "PAYGATE_TIER_ONE", "prompt": "x"},
            result={"media_ids": ["m"]},
        ))
        s.commit()

    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["paygate_tier"] is None
