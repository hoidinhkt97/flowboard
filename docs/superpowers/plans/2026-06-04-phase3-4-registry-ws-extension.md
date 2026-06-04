# Phase 3+4: Connection Registry, WS Auth & Extension Pairing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the global `flow_client` singleton with a per-account `ConnectionRegistry` so multiple users each get their own extension connection; add an authenticated WebSocket endpoint (`/ext`) and pairing endpoint (`/api/extension/pair`); update the Chrome extension to auto-pair via refresh cookie and connect via device token.

**Architecture:** `ConnectionRegistry` maps `account_id → FlowClient`. The new `GET /ext` WebSocket endpoint (FastAPI native, replaces `:9223` standalone server) authenticates via device token from DB. `POST /api/extension/pair` validates the refresh cookie and mints a `DeviceToken`. Worker and callback handler resolve the right `FlowClient` from the registry by `account_id`. The Chrome extension reads the `fb_refresh` cookie, pairs, then connects with `?token=<device_token>`.

**Tech Stack:** Python 3.10+, FastAPI native WebSocket, SQLModel, pytest + TestClient, JavaScript MV3 Chrome extension.

---

## Design notes (read before starting)

**Naming locked for cross-task consistency:**
- Class `ConnectionRegistry`, singleton `registry` in `services/registry.py`
- Methods: `register(account_id, ws) -> FlowClient`, `unregister(account_id, ws)`, `get(account_id) -> FlowClient | None`, `is_online(account_id) -> bool`
- WS close codes: `4401` = unauthorized/revoked, `4408` = replaced by newer connection
- Pair endpoint: `POST /api/extension/pair` — auth via `fb_refresh` cookie — returns `{"device_token": raw_str}`
- WS endpoint: `GET /ext?token=<raw>` — FastAPI `@router.websocket`
- Callback auth: `X-Device-Token` header (replaces `X-Callback-Secret`)
- Extension constants: `APP_ORIGIN`, `PAIR_URL`, `CALLBACK_URL`

**FlowSDK note:** `FlowSDK.__init__` already accepts an optional `client` arg: `self._client = client or flow_client`. In Task 4 we require the argument explicitly by removing the global fallback.

**Test note for WS:** Use `with client.websocket_connect("/ext?token=X") as ws:` — TestClient supports WebSocket. Close code assertions use `pytest.raises(WebSocketDisconnect)` then check `.code`.

---

# PHASE 3 — Server-side

## Task 1: ConnectionRegistry

**Files:**
- Create: `agent/flowboard/services/registry.py`
- Test: `agent/tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_registry.py`:

```python
"""Unit tests for ConnectionRegistry.

We don't use real WebSockets — a FakeWs records close calls so we can
verify the last-wins eviction logic without spinning up a server."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import ConnectionRegistry


def _fake_ws():
    ws = MagicMock()
    ws.close = AsyncMock()
    return ws


def test_register_returns_flow_client():
    reg = ConnectionRegistry()
    fc = reg.register(1, _fake_ws())
    assert isinstance(fc, FlowClient)


def test_get_returns_registered_client():
    reg = ConnectionRegistry()
    reg.register(1, _fake_ws())
    assert reg.get(1) is not None


def test_get_returns_none_for_unknown_account():
    reg = ConnectionRegistry()
    assert reg.get(999) is None


def test_is_online_true_after_register():
    reg = ConnectionRegistry()
    reg.register(1, _fake_ws())
    assert reg.is_online(1) is True


def test_is_online_false_after_unregister():
    reg = ConnectionRegistry()
    ws = _fake_ws()
    reg.register(1, ws)
    reg.unregister(1, ws)
    assert reg.is_online(1) is False


def test_unregister_wrong_ws_does_not_remove():
    """Stale unregister (old ws after reconnect) must not evict the new one."""
    reg = ConnectionRegistry()
    old_ws = _fake_ws()
    new_ws = _fake_ws()
    reg.register(1, old_ws)
    reg.register(1, new_ws)    # last-wins
    reg.unregister(1, old_ws)  # stale — should be no-op
    assert reg.is_online(1) is True


@pytest.mark.asyncio
async def test_last_wins_closes_old_connection():
    """Second register on the same account closes the first ws with 4408."""
    reg = ConnectionRegistry()
    old_ws = _fake_ws()
    new_ws = _fake_ws()
    reg.register(1, old_ws)
    reg.register(1, new_ws)
    await asyncio.sleep(0)   # let the close task fire
    old_ws.close.assert_awaited_once_with(code=4408, reason="replaced")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowboard.services.registry'`.

- [ ] **Step 3: Write the registry**

Create `agent/flowboard/services/registry.py`:

```python
"""Per-account ConnectionRegistry: maps account_id → FlowClient instance.

Lives in-process (Hướng A). Server restart empties the registry; the
extension reconnects automatically via backoff and re-populates it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from flowboard.services.flow_client import FlowClient

logger = logging.getLogger(__name__)

_CLOSE_REPLACED = 4408


class ConnectionRegistry:
    def __init__(self) -> None:
        self._conns: dict[int, tuple[FlowClient, Any]] = {}  # account_id → (fc, ws)

    def register(self, account_id: int, websocket: Any) -> FlowClient:
        """Register websocket for account_id. Last-wins: any existing
        connection is evicted with close code 4408."""
        existing = self._conns.get(account_id)
        if existing is not None:
            old_fc, old_ws = existing
            asyncio.create_task(
                old_ws.close(code=_CLOSE_REPLACED, reason="replaced"),
                name=f"evict-{account_id}",
            )
            old_fc.clear_extension()

        fc = FlowClient()
        fc.set_extension(websocket)
        self._conns[account_id] = (fc, websocket)
        logger.info("registry: account %d connected", account_id)
        return fc

    def unregister(self, account_id: int, websocket: Any) -> None:
        """Remove the connection only if it matches the given websocket.
        A stale unregister (old ws after last-wins eviction) is a no-op."""
        entry = self._conns.get(account_id)
        if entry is None:
            return
        fc, ws = entry
        if ws is not websocket:
            return
        fc.clear_extension()
        del self._conns[account_id]
        logger.info("registry: account %d disconnected", account_id)

    def get(self, account_id: int) -> Optional[FlowClient]:
        entry = self._conns.get(account_id)
        return entry[0] if entry is not None else None

    def is_online(self, account_id: int) -> bool:
        return account_id in self._conns


registry = ConnectionRegistry()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_registry.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/services/registry.py agent/tests/test_registry.py
git commit -m "feat: ConnectionRegistry — per-account FlowClient map"
```

---

## Task 2: Pairing endpoint — `POST /api/extension/pair`

**Files:**
- Create: `agent/flowboard/routes/extension.py`
- Modify: `agent/flowboard/main.py` (mount router)
- Test: `agent/tests/test_pair_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_pair_endpoint.py`:

```python
"""Tests for POST /api/extension/pair."""


def _register_and_login(client, email="pair@example.com"):
    client.post("/api/account/register",
                json={"email": email, "password": "pw123456"})
    client.post("/api/account/login",
                json={"email": email, "password": "pw123456"})
    # fb_refresh cookie is now stored in the TestClient cookie jar


def test_pair_returns_device_token(client):
    _register_and_login(client)
    r = client.post("/api/extension/pair")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "device_token" in body
    assert isinstance(body["device_token"], str)
    assert len(body["device_token"]) >= 32


def test_pair_without_cookie_is_401(client):
    r = client.post("/api/extension/pair")
    assert r.status_code == 401


def test_pair_with_invalid_cookie_is_401(client):
    r = client.post("/api/extension/pair",
                    cookies={"fb_refresh": "definitely-not-valid"})
    assert r.status_code == 401


def test_pair_twice_returns_different_tokens(client):
    _register_and_login(client)
    t1 = client.post("/api/extension/pair").json()["device_token"]
    t2 = client.post("/api/extension/pair").json()["device_token"]
    assert t1 != t2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_pair_endpoint.py -v`
Expected: FAIL with 404 (route not mounted).

- [ ] **Step 3: Write the pairing route**

Create `agent/flowboard/routes/extension.py`:

```python
"""Extension pairing: mint a DeviceToken from the refresh cookie.

The Chrome extension reads the fb_refresh cookie (same origin) and
calls this endpoint to get a device token it can use to open the
authenticated WebSocket at /ext."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import DeviceToken, RefreshToken
from flowboard.services.security import generate_token, hash_token

router = APIRouter(prefix="/api/extension", tags=["extension"])


@router.post("/pair")
def pair(fb_refresh: str | None = Cookie(default=None)):
    if not fb_refresh:
        raise HTTPException(status_code=401, detail="missing refresh cookie")

    with get_session() as s:
        row = s.exec(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(fb_refresh))
        ).first()
        if row is None or row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="invalid refresh token")
        if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="refresh token expired")

        raw = generate_token()
        s.add(DeviceToken(
            account_id=row.account_id,
            token_hash=hash_token(raw),
            label="chrome",
        ))
        s.commit()

    return {"device_token": raw}
```

- [ ] **Step 4: Mount the router in `main.py`**

In `agent/flowboard/main.py`, add `extension` to the route imports:

```python
from flowboard.routes import account_auth, activity, auth, boards, chat, edges, extension, flow_projects, llm, media, nodes, plans, projects, prompt, upload, vision
```

After `app.include_router(account_auth.router)` add:

```python
app.include_router(extension.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_pair_endpoint.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/routes/extension.py agent/flowboard/main.py agent/tests/test_pair_endpoint.py
git commit -m "feat: POST /api/extension/pair mints DeviceToken from refresh cookie"
```

---

## Task 3: WebSocket `/ext` endpoint with device token auth

**Files:**
- Create: `agent/flowboard/routes/ext_ws.py`
- Modify: `agent/flowboard/main.py` (mount router)
- Test: `agent/tests/test_ext_ws.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_ext_ws.py`:

```python
"""Integration tests for the /ext WebSocket endpoint."""
import pytest
from starlette.testclient import WebSocketDisconnect

from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken
from flowboard.services.registry import registry
from flowboard.services.security import generate_token, hash_token


def _create_device_token(email="ws@example.com") -> tuple[int, str]:
    """Create an account + device token in the DB. Returns (account_id, raw_token)."""
    with get_session() as s:
        acct = Account(email=email, password_hash="x")
        s.add(acct); s.commit(); s.refresh(acct)
        raw = generate_token()
        s.add(DeviceToken(account_id=acct.id, token_hash=hash_token(raw)))
        s.commit()
        return acct.id, raw


def test_valid_token_connects_and_registers(client):
    account_id, raw = _create_device_token("ws1@example.com")
    with client.websocket_connect(f"/ext?token={raw}"):
        assert registry.is_online(account_id)
    assert not registry.is_online(account_id)


def test_invalid_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ext?token=not-a-real-token"):
            pass
    assert exc_info.value.code == 4401


def test_missing_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ext"):
            pass
    assert exc_info.value.code == 4401


def test_revoked_token_is_rejected(client):
    from datetime import datetime, timezone
    from sqlmodel import select
    account_id, raw = _create_device_token("ws4@example.com")
    with get_session() as s:
        dt = s.exec(select(DeviceToken).where(DeviceToken.token_hash == hash_token(raw))).one()
        dt.revoked_at = datetime.now(timezone.utc)
        s.add(dt); s.commit()
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ext?token={raw}"):
            pass
    assert exc_info.value.code == 4401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_ext_ws.py -v`
Expected: FAIL (route not mounted yet).

- [ ] **Step 3: Write the WebSocket route**

Create `agent/flowboard/routes/ext_ws.py`:

```python
"""Authenticated WebSocket endpoint for the Chrome extension.

The extension connects as:  wss://server/ext?token=<raw_device_token>

Protocol:
1. Hash token → look up DeviceToken → account_id.
   Bad/revoked → close 4401.
2. registry.register(account_id, ws) — last-wins, evicts stale with 4408.
3. Update DeviceToken.last_seen_at.
4. Message loop: forward to fc.handle_message(data).
5. Disconnect → registry.unregister(account_id, ws).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import DeviceToken
from flowboard.services.registry import registry
from flowboard.services.security import hash_token

logger = logging.getLogger(__name__)
router = APIRouter()

_CLOSE_UNAUTHORIZED = 4401
_PING_INTERVAL_S = 30.0
_PONG_TIMEOUT_S = 10.0


@router.websocket("/ext")
async def ext_ws(websocket: WebSocket, token: str = ""):
    if not token:
        await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="missing token")
        return

    with get_session() as s:
        row = s.exec(
            select(DeviceToken).where(DeviceToken.token_hash == hash_token(token))
        ).first()
        if row is None or row.revoked_at is not None:
            await websocket.close(code=_CLOSE_UNAUTHORIZED, reason="invalid token")
            return
        account_id = row.account_id
        row.last_seen_at = datetime.now(timezone.utc)
        s.add(row)
        s.commit()

    await websocket.accept()
    fc = registry.register(account_id, websocket)
    logger.info("ext WS: account %d connected", account_id)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=_PING_INTERVAL_S)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=_PONG_TIMEOUT_S)
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    logger.info("ext WS: account %d heartbeat timeout", account_id)
                    break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("ext WS: invalid JSON from account %d", account_id)
                continue
            try:
                await fc.handle_message(data)
            except Exception:
                logger.exception("ext WS: error handling message for account %d", account_id)
    except WebSocketDisconnect:
        pass
    finally:
        registry.unregister(account_id, websocket)
        logger.info("ext WS: account %d disconnected", account_id)
```

- [ ] **Step 4: Mount the WebSocket router in `main.py`**

Add `ext_ws` to the imports in `agent/flowboard/main.py`:

```python
from flowboard.routes import account_auth, activity, auth, boards, chat, edges, ext_ws, extension, flow_projects, llm, media, nodes, plans, projects, prompt, upload, vision
```

After `app.include_router(extension.router)` add:

```python
app.include_router(ext_ws.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_ext_ws.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/routes/ext_ws.py agent/flowboard/main.py agent/tests/test_ext_ws.py
git commit -m "feat: authenticated WebSocket /ext endpoint with device token"
```

---

## Task 4: Refactor `FlowSDK` — require explicit FlowClient, remove global

**Files:**
- Modify: `agent/flowboard/services/flow_sdk.py` (lines 20, 312-313, 1344-1351)

- [ ] **Step 1: Establish baseline**

Run: `cd agent && python -m pytest tests/test_flow_sdk.py tests/test_flow_client.py -v`
Note the pass count. This must still pass after the change.

- [ ] **Step 2: Update `flow_sdk.py`**

**Line 20** — change:
```python
from flowboard.services.flow_client import FlowClient, flow_client
```
to:
```python
from flowboard.services.flow_client import FlowClient
```

**`FlowSDK.__init__`** (around line 312) — change:
```python
    def __init__(self, client: Optional[FlowClient] = None) -> None:
        self._client = client or flow_client
```
to:
```python
    def __init__(self, client: FlowClient) -> None:
        self._client = client
```

**`_sdk` singleton and `get_flow_sdk`** (around lines 1344-1351) — replace:
```python
_sdk: Optional[FlowSDK] = None


def get_flow_sdk() -> FlowSDK:
    global _sdk
    if _sdk is None:
        _sdk = FlowSDK()
    return _sdk
```
with:
```python
def get_flow_sdk(client: FlowClient) -> "FlowSDK":
    """Return a FlowSDK bound to the given per-account FlowClient instance."""
    return FlowSDK(client=client)
```

- [ ] **Step 3: Fix any callers in `test_flow_sdk.py` if needed**

Run: `cd agent && python -m pytest tests/test_flow_sdk.py tests/test_flow_client.py -v`

If `test_flow_sdk.py` calls `get_flow_sdk()` with no args, update each call to `get_flow_sdk(FlowClient())`. `test_flow_client.py` instantiates `FlowClient()` directly — no change needed there.

Expected: same pass count as Step 1.

- [ ] **Step 4: Commit**

```bash
git add agent/flowboard/services/flow_sdk.py agent/tests/test_flow_sdk.py
git commit -m "refactor: FlowSDK requires explicit FlowClient — remove global singleton fallback"
```

---

## Task 5: Refactor `worker/processor.py` — pass registry-resolved FlowClient

**Files:**
- Modify: `agent/flowboard/worker/processor.py`
- Modify: `agent/tests/test_processor_tier_fallback.py`
- Test: `agent/tests/test_worker_registry.py`

- [ ] **Step 1: Write the failing registry-dispatch test**

Create `agent/tests/test_worker_registry.py`:

```python
"""Worker dispatches proxy jobs through the registry, not the global singleton."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from flowboard.db import get_session
from flowboard.db.models import Account, Board, Node, Request
from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import registry
from flowboard.worker.processor import _process_one


def _seed_request(account_id: int) -> int:
    with get_session() as s:
        board = Board(name="b", account_id=account_id)
        s.add(board); s.commit(); s.refresh(board)
        node = Node(board_id=board.id, account_id=account_id, short_id="n1", type="image")
        s.add(node); s.commit(); s.refresh(node)
        req = Request(
            node_id=node.id, account_id=account_id, type="proxy",
            params={"url": "https://aisandbox-pa.googleapis.com/v1/test"},
            status="queued",
        )
        s.add(req); s.commit(); s.refresh(req)
        return req.id


def _seed_account(email: str) -> int:
    with get_session() as s:
        a = Account(email=email, password_hash="x")
        s.add(a); s.commit(); s.refresh(a)
        return a.id


@pytest.mark.asyncio
async def test_proxy_fails_with_extension_offline():
    account_id = _seed_account("offline@example.com")
    req_id = _seed_request(account_id)
    # Do NOT register a FlowClient → offline
    await _process_one(req_id)
    with get_session() as s:
        req = s.get(Request, req_id)
        assert req.status == "failed"
        assert req.error == "extension_offline"


@pytest.mark.asyncio
async def test_proxy_uses_registry_connection():
    account_id = _seed_account("online@example.com")
    req_id = _seed_request(account_id)

    fc = FlowClient()
    fake_ws = MagicMock()
    fake_ws.close = AsyncMock()
    fc.set_extension(fake_ws)
    fc.api_request = AsyncMock(return_value={"status": 200, "data": {"ok": True}})

    registry._conns[account_id] = (fc, fake_ws)
    try:
        await _process_one(req_id)
        fc.api_request.assert_awaited_once()
        with get_session() as s:
            req = s.get(Request, req_id)
            assert req.status == "done"
    finally:
        registry._conns.pop(account_id, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_worker_registry.py -v`
Expected: FAIL — `_process_one` uses the global singleton, not registry.

- [ ] **Step 3: Update `processor.py` import block**

In `agent/flowboard/worker/processor.py`, replace:
```python
from flowboard.services.flow_client import flow_client
from flowboard.services.flow_sdk import get_flow_sdk
```
with:
```python
from flowboard.services.flow_client import FlowClient
from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services.registry import registry
```

- [ ] **Step 4: Add `fc: FlowClient` parameter to every handler**

For each handler function (`_handle_proxy`, `_handle_create_project`, `_handle_gen_image`, `_handle_gen_video`, `_handle_edit_image`, `_handle_upload_image`):

1. Add `fc: FlowClient` as the second parameter.
2. Replace `flow_client.api_request(...)` with `fc.api_request(...)`.
3. Replace `flow_client.paygate_tier` with `fc.paygate_tier`.
4. Replace `get_flow_sdk().method(...)` with `get_flow_sdk(fc).method(...)`.

Example for `_handle_proxy`:
```python
async def _handle_proxy(params: dict, fc: FlowClient) -> tuple[dict, Optional[str]]:
    url = params.get("url")
    method = params.get("method", "POST")
    if not isinstance(url, str) or not url:
        return {}, "missing_url"
    if not any(url.startswith(p) for p in _ALLOWED_URL_PREFIXES):
        return {}, "url_not_allowed"
    resp = await fc.api_request(
        url=url,
        method=method,
        headers=params.get("headers") or {},
        body=params.get("body"),
    )
    if not isinstance(resp, dict):
        return {"value": resp}, None
    if resp.get("error"):
        return resp, str(resp["error"])
    status = resp.get("status")
    if isinstance(status, int) and status >= 400:
        return resp, f"API_{status}"
    return resp, None
```

Example for `_handle_gen_image` (tier resolution + sdk):
```python
async def _handle_gen_image(params: dict, fc: FlowClient) -> tuple[dict, Optional[str]]:
    ...
    tier = params.get("paygate_tier") or fc.paygate_tier
    if tier is None:
        return {}, "paygate_tier_unknown"
    ...
    resp = await get_flow_sdk(fc).gen_image(...)
```

Apply the same pattern to every other handler.

- [ ] **Step 5: Update the dispatch function (`_process_one`) to resolve FlowClient from registry**

Find the function in `processor.py` that loads a `Request` by id and dispatches to handlers. Add registry lookup before the handler dispatch, and fail with `extension_offline` when offline:

```python
async def _process_one(request_id: int) -> None:
    with get_session() as s:
        req = s.get(Request, request_id)
        if req is None:
            return
        req.status = "running"
        s.add(req)
        s.commit()

    # Resolve per-account FlowClient for handlers that need the extension.
    _EXTENSION_TYPES = {"proxy", "gen_image", "gen_video", "edit_image", "upload_image"}
    fc = registry.get(req.account_id) if req.account_id is not None else None
    if fc is None and req.type in _EXTENSION_TYPES:
        with get_session() as s:
            req = s.get(Request, request_id)
            req.status = "failed"
            req.error = "extension_offline"
            req.finished_at = datetime.now(timezone.utc)
            s.add(req)
            s.commit()
        return

    # ... existing dispatch logic, but every handler call gains `fc`:
    # await _handle_proxy(params, fc)
    # await _handle_gen_image(params, fc)
    # etc.
```

> Read the full current body of `_process_one` (or whatever the dispatch function is named), then apply these changes to it. Do not rewrite logic you don't understand; only add the registry lookup at the top and thread `fc` into each handler call.

- [ ] **Step 6: Update `test_processor_tier_fallback.py`**

Remove `_reset_flow_client_tier` autouse fixture. Add a `fc` fixture and thread it into every test:

```python
import pytest
from unittest.mock import AsyncMock, patch

from flowboard.services.flow_client import FlowClient
from flowboard.worker import processor as proc


@pytest.fixture
def fc():
    client = FlowClient()
    client._paygate_tier = "PAYGATE_TIER_ONE"
    return client


@pytest.mark.asyncio
async def test_gen_image_uses_caller_stamped_tier_first(fc):
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.gen_image = AsyncMock(return_value={"media_ids": ["m"], "media_entries": []})
        await proc._handle_gen_image(
            {"prompt": "x", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04",
             "paygate_tier": "PAYGATE_TIER_ONE"}, fc)
        assert m.return_value.gen_image.call_args.kwargs["paygate_tier"] == "PAYGATE_TIER_ONE"


@pytest.mark.asyncio
async def test_gen_image_falls_back_to_live_flow_client_tier(fc):
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.gen_image = AsyncMock(return_value={"media_ids": ["m"], "media_entries": []})
        await proc._handle_gen_image(
            {"prompt": "x", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04"}, fc)
        assert m.return_value.gen_image.call_args.kwargs["paygate_tier"] == "PAYGATE_TIER_TWO"


@pytest.mark.asyncio
async def test_gen_image_fails_loud_when_no_tier_signal_anywhere():
    no_tier_fc = FlowClient()
    no_tier_fc._paygate_tier = None
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.gen_image = AsyncMock()
        result, err = await proc._handle_gen_image(
            {"prompt": "x", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04"}, no_tier_fc)
        assert err == "paygate_tier_unknown"
        m.return_value.gen_image.assert_not_called()


@pytest.mark.asyncio
async def test_gen_video_fails_loud_when_no_tier_signal_anywhere():
    no_tier_fc = FlowClient()
    no_tier_fc._paygate_tier = None
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.gen_video = AsyncMock(return_value={"operation_names": []})
        result, err = await proc._handle_gen_video(
            {"prompt": "x", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04",
             "start_media_id": "src-1"}, no_tier_fc)
        assert err == "paygate_tier_unknown"
        m.return_value.gen_video.assert_not_called()


@pytest.mark.asyncio
async def test_edit_image_fails_loud_when_no_tier_signal_anywhere():
    no_tier_fc = FlowClient()
    no_tier_fc._paygate_tier = None
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.edit_image = AsyncMock(return_value={"media_ids": ["m"], "media_entries": []})
        result, err = await proc._handle_edit_image(
            {"prompt": "pop", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04",
             "source_media_id": "src-1"}, no_tier_fc)
        assert err == "paygate_tier_unknown"
        m.return_value.edit_image.assert_not_called()


@pytest.mark.asyncio
async def test_gen_video_applies_same_resolution_chain(fc):
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.gen_video = AsyncMock(return_value={"operation_names": []})
        await proc._handle_gen_video(
            {"prompt": "x", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04",
             "start_media_id": "src-1"}, fc)
        assert m.return_value.gen_video.call_args.kwargs["paygate_tier"] == "PAYGATE_TIER_TWO"


@pytest.mark.asyncio
async def test_edit_image_applies_same_resolution_chain(fc):
    fc._paygate_tier = "PAYGATE_TIER_TWO"
    with patch("flowboard.worker.processor.get_flow_sdk") as m:
        m.return_value.edit_image = AsyncMock(return_value={"media_ids": ["m"], "media_entries": []})
        await proc._handle_edit_image(
            {"prompt": "pop", "project_id": "8b62385c-4916-4abd-b01f-b28173d8eb04",
             "source_media_id": "src-1"}, fc)
        assert m.return_value.edit_image.call_args.kwargs["paygate_tier"] == "PAYGATE_TIER_TWO"
```

- [ ] **Step 7: Run all processor tests**

Run: `cd agent && python -m pytest tests/test_processor_tier_fallback.py tests/test_worker_registry.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agent/flowboard/worker/processor.py agent/tests/test_processor_tier_fallback.py agent/tests/test_worker_registry.py
git commit -m "refactor: processor handlers accept FlowClient param, dispatch via registry"
```

---

## Task 6: Remove singleton, delete `ws_server.py`, update `main.py` + `routes/auth.py` + conftest

**Files:**
- Modify: `agent/flowboard/services/flow_client.py` (remove singleton + `callback_secret`)
- Delete: `agent/flowboard/services/ws_server.py`
- Modify: `agent/flowboard/config.py` (remove `WS_HOST`, `EXTENSION_WS_PORT`)
- Modify: `agent/flowboard/main.py` (remove ws_task + WS_HOST guard, update callback + health)
- Modify: `agent/flowboard/routes/auth.py` (use registry)
- Modify: `agent/tests/conftest.py` (remove `_seed_default_paygate_tier`)
- Modify: `agent/tests/test_ext_callback.py` (remove; migrated to new test)
- Modify: `agent/tests/test_auth.py` (add auth header where needed)
- Test: `agent/tests/test_callback_auth.py`

> This task removes all singleton references in a single commit to avoid intermediate broken state. Write and verify the new callback test first, then make all changes atomically.

- [ ] **Step 1: Write the new callback auth test**

Create `agent/tests/test_callback_auth.py`:

```python
"""Tests for /api/ext/callback after migration to X-Device-Token auth."""
import asyncio

import pytest

from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken
from flowboard.services.flow_client import FlowClient
from flowboard.services.registry import registry
from flowboard.services.security import generate_token, hash_token


def _seed_account_and_token(email: str) -> tuple[int, str]:
    with get_session() as s:
        acct = Account(email=email, password_hash="x")
        s.add(acct); s.commit(); s.refresh(acct)
        raw = generate_token()
        s.add(DeviceToken(account_id=acct.id, token_hash=hash_token(raw)))
        s.commit()
        return acct.id, raw


def test_callback_rejects_missing_device_token(client):
    r = client.post("/api/ext/callback", json={"id": "x", "status": 200, "data": {}})
    assert r.status_code == 401


def test_callback_rejects_unknown_device_token(client):
    r = client.post(
        "/api/ext/callback",
        json={"id": "x", "status": 200, "data": {}},
        headers={"X-Device-Token": generate_token()},
    )
    assert r.status_code == 401


def test_callback_rejects_revoked_device_token(client):
    from datetime import datetime, timezone
    from sqlmodel import select
    account_id, raw = _seed_account_and_token("cb2@example.com")
    with get_session() as s:
        dt = s.exec(select(DeviceToken).where(DeviceToken.token_hash == hash_token(raw))).one()
        dt.revoked_at = datetime.now(timezone.utc)
        s.add(dt); s.commit()
    r = client.post(
        "/api/ext/callback",
        json={"id": "x", "status": 200, "data": {}},
        headers={"X-Device-Token": raw},
    )
    assert r.status_code == 401


def test_callback_ok_but_no_pending_match(client):
    account_id, raw = _seed_account_and_token("cb3@example.com")
    r = client.post(
        "/api/ext/callback",
        json={"id": "no-match", "status": 200, "data": {}},
        headers={"X-Device-Token": raw},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False}


@pytest.mark.asyncio
async def test_callback_resolves_pending_future(client):
    account_id, raw = _seed_account_and_token("cb4@example.com")
    fc = FlowClient()
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    fc._pending["probe-id"] = fut
    registry._conns[account_id] = (fc, None)
    try:
        r = client.post(
            "/api/ext/callback",
            json={"id": "probe-id", "status": 200, "data": {"ok": True}},
            headers={"X-Device-Token": raw},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        resolved = await asyncio.wait_for(fut, timeout=1.0)
        assert resolved["data"] == {"ok": True}
    finally:
        registry._conns.pop(account_id, None)
```

- [ ] **Step 2: Remove singleton + `callback_secret` from `flow_client.py`**

In `agent/flowboard/services/flow_client.py`:

Remove `self._callback_secret: str = secrets.token_urlsafe(32)` from `__init__`.

Remove the `callback_secret` property:
```python
@property
def callback_secret(self) -> str:
    return self._callback_secret
```

Remove `import secrets` only if it has no other usages in the file (check first with `grep -n "secrets\." agent/flowboard/services/flow_client.py`).

Delete the last line: `flow_client = FlowClient()`.

- [ ] **Step 3: Delete `ws_server.py` and remove WS config**

```bash
git rm agent/flowboard/services/ws_server.py
```

In `agent/flowboard/config.py`, remove:
```python
WS_HOST = os.getenv("FLOWBOARD_WS_HOST", "127.0.0.1")
EXTENSION_WS_PORT = int(os.getenv("FLOWBOARD_EXT_WS_PORT", "9223"))
```

- [ ] **Step 4: Update `main.py`**

Remove these imports:
```python
from flowboard.config import WS_HOST
from flowboard.services.flow_client import flow_client
from flowboard.services.ws_server import run_ws_server
```

Add these imports:
```python
from flowboard.db.models import DeviceToken
from flowboard.services.registry import registry
from flowboard.services.security import hash_token
from sqlmodel import select as _select_dt
```

Remove the WS_HOST guard block (the `if WS_HOST not in (...)` block at lines 19-29).

In the `lifespan` function, remove `ws_task = asyncio.create_task(run_ws_server(), ...)` and its cancel/await. Update the log message from `"flowboard agent started (ws:9223 + worker)"` to `"flowboard agent started"`.

Replace `/api/health`:
```python
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "online_accounts": len(registry._conns)}
```

Replace `/api/ext/callback`:
```python
@app.post("/api/ext/callback")
async def ext_callback(
    body: FastAPIRequest,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict:
    if not x_device_token:
        raise HTTPException(status_code=401, detail="missing device token")

    with get_session() as s:
        row = s.exec(
            _select_dt(DeviceToken).where(DeviceToken.token_hash == hash_token(x_device_token))
        ).first()
        if row is None or row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="invalid device token")
        account_id = row.account_id

    try:
        payload = await body.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")
    if not isinstance(payload, dict) or "id" not in payload:
        raise HTTPException(status_code=400, detail="missing id")

    fc = registry.get(account_id)
    matched = fc.resolve_callback(payload) if fc is not None else False
    return {"ok": matched}
```

Remove the `import hmac` that was only used for the old callback.

- [ ] **Step 5: Update `routes/auth.py`**

Replace:
```python
from flowboard.services.flow_client import flow_client
```
with:
```python
from fastapi import Depends
from flowboard.db.models import Account
from flowboard.deps import get_current_account
from flowboard.services.registry import registry
```

Replace the three route implementations to accept `acct: Account = Depends(get_current_account)` and look up `fc = registry.get(acct.id)`:

```python
@router.get("/me")
def get_me(acct: Account = Depends(get_current_account)) -> dict:
    fc = registry.get(acct.id)
    info = (fc.user_info or {}) if fc else {}
    return {
        "email": info.get("email"),
        "name": info.get("name"),
        "picture": info.get("picture"),
        "verified_email": info.get("verified_email"),
        "paygate_tier": fc.paygate_tier if fc else None,
        "sku": fc.sku if fc else None,
        "credits": fc.credits if fc else None,
    }


@router.post("/logout")
async def logout(acct: Account = Depends(get_current_account)) -> dict:
    fc = registry.get(acct.id)
    extension_notified = False
    if fc is not None:
        extension_notified = await fc.notify({"type": "logout"})
        fc.clear_extension()
    return {"ok": True, "extension_notified": extension_notified}


@router.post("/scan")
async def scan_extension(acct: Account = Depends(get_current_account)) -> dict:
    fc = registry.get(acct.id)
    if fc is None:
        return {"extension_connected": False, "has_user_info": False,
                "has_paygate_tier": False, "userinfo_nudged": False, "tier_fetched": False}
    nudged = False
    if fc.connected and fc.user_info is None:
        nudged = await fc.notify({"type": "please_resend_userinfo"})
    tier_fetched = False
    if fc.paygate_tier is None:
        tier_fetched = await fc.fetch_paygate_tier()
    return {
        "extension_connected": fc.connected,
        "has_user_info": fc.user_info is not None,
        "has_paygate_tier": fc.paygate_tier is not None,
        "userinfo_nudged": nudged,
        "tier_fetched": tier_fetched,
    }
```

- [ ] **Step 6: Update `conftest.py` — remove `_seed_default_paygate_tier`**

In `agent/tests/conftest.py`, remove the entire `_seed_default_paygate_tier` autouse fixture (it set `flow_client._paygate_tier` — the processor tests now own their own `fc` setup).

- [ ] **Step 7: Remove `test_ext_callback.py`**

```bash
git rm agent/tests/test_ext_callback.py
```

- [ ] **Step 8: Update `test_auth.py` — add Bearer header**

Open `agent/tests/test_auth.py`. Each test that calls `/api/auth/me`, `/api/auth/scan`, or `/api/auth/logout` needs a Bearer token (these routes now use `get_current_account`).

Add an `auth` fixture (or use the shared one from conftest) and pass `headers=auth` on those requests. Remove any `from flowboard.services.flow_client import flow_client` import; replace usages with `registry.get(...)` if needed.

- [ ] **Step 9: Verify no remaining singleton imports**

Run: `grep -rn "from flowboard.services.flow_client import flow_client" agent/`
Expected: no output.

Run: `grep -rn "from flowboard.services.ws_server" agent/`
Expected: no output.

Run: `grep -rn "WS_HOST\|EXTENSION_WS_PORT" agent/flowboard/`
Expected: no output.

- [ ] **Step 10: Run the full suite**

Run: `cd agent && python -m pytest -q`
Expected: all green (fix any remaining failures by reading the error and applying the same singleton→registry substitution).

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: remove flow_client singleton — all extension connections through ConnectionRegistry"
```

---

# PHASE 4 — Extension client

## Task 7: Extension manifest — add `cookies` permission

**Files:**
- Modify: `extension/manifest.json`

- [ ] **Step 1: Add `"cookies"` to permissions**

In `extension/manifest.json`, update the `"permissions"` array:
```json
"permissions": [
  "storage", "alarms", "tabs", "webRequest", "scripting",
  "declarativeNetRequest", "cookies"
],
```

- [ ] **Step 2: Verify valid JSON**

Run: `node -e "require('./extension/manifest.json'); console.log('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add extension/manifest.json
git commit -m "feat(ext): add cookies permission for auto-pair"
```

---

## Task 8: Extension `background.js` — pairing, new WS connect, close codes, callback auth

**Files:**
- Modify: `extension/background.js`

- [ ] **Step 1: Replace constants at the top**

Replace:
```js
const AGENT_WS_URL  = 'ws://127.0.0.1:9223';
const CALLBACK_URL  = 'http://127.0.0.1:8101/api/ext/callback';
```
with:
```js
const APP_ORIGIN   = 'http://localhost:8101';   // override for prod: 'https://app.flowboard.ai'
const PAIR_URL     = APP_ORIGIN + '/api/extension/pair';
const CALLBACK_URL = APP_ORIGIN + '/api/ext/callback';
```

- [ ] **Step 2: Replace `callbackSecret` with `deviceToken`**

Remove:
```js
let callbackSecret   = null; // Auth secret received from agent on WS connect
```
Add:
```js
let deviceToken      = null; // Raw device token from /api/extension/pair
```

- [ ] **Step 3: Update `init()`**

Replace the body of `init()`:
```js
async function init() {
  const data = await chrome.storage.local.get(['flowKey', 'metrics', 'deviceToken']);
  if (data.flowKey)     flowKey     = data.flowKey;
  if (data.metrics)     Object.assign(metrics, data.metrics);
  if (data.deviceToken) deviceToken = data.deviceToken;

  if (deviceToken) {
    connectToServer(deviceToken);
  } else {
    await pairWithServer();
  }
  chrome.alarms.create('keepAlive', { periodInMinutes: 0.4 });
}
```

- [ ] **Step 4: Add `pairWithServer()`**

Insert this function before `connectToAgent` (which we'll replace next):

```js
async function pairWithServer() {
  try {
    const cookie = await chrome.cookies.get({ url: APP_ORIGIN, name: 'fb_refresh' });
    if (!cookie) {
      console.log('[Flowboard] No fb_refresh cookie — not logged in yet');
      setState('unpaired');
      scheduleReconnect();
      return null;
    }
    const resp = await fetch(PAIR_URL, { method: 'POST', credentials: 'include' });
    if (!resp.ok) {
      console.warn('[Flowboard] Pair failed:', resp.status);
      setState('unpaired');
      scheduleReconnect();
      return null;
    }
    const body = await resp.json();
    deviceToken = body.device_token;
    await chrome.storage.local.set({ deviceToken });
    console.log('[Flowboard] Paired — device token obtained');
    connectToServer(deviceToken);
    return deviceToken;
  } catch (e) {
    console.warn('[Flowboard] pairWithServer error:', e?.message || e);
    setState('unpaired');
    scheduleReconnect();
    return null;
  }
}
```

- [ ] **Step 5: Replace `connectToAgent()` with `connectToServer(token)`**

Replace the entire `connectToAgent` function:

```js
function connectToServer(token) {
  if (manualDisconnect) return;
  if (ws?.readyState === WebSocket.CONNECTING) return;
  if (ws?.readyState === WebSocket.OPEN) return;

  const wsUrl = APP_ORIGIN.replace(/^http/, 'ws') + '/ext?token=' + token;
  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    console.error('[Flowboard] WS connect error:', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[Flowboard] Connected to server');
    chrome.alarms.clear('reconnect');
    setState('idle');
    const tokenAge = flowKey && metrics.tokenCapturedAt
      ? Date.now() - metrics.tokenCapturedAt : null;
    ws.send(JSON.stringify({ type: 'extension_ready', flowKeyPresent: !!flowKey, tokenAge }));
    if (flowKey) ws.send(JSON.stringify({ type: 'token_captured', flowKey }));
    if (cachedUserInfo) {
      ws.send(JSON.stringify({ type: 'user_info', userInfo: cachedUserInfo }));
    } else if (flowKey) {
      fetchAndPushUserInfo(flowKey);
    }
  };

  ws.onmessage = async ({ data }) => {
    try {
      const msg = JSON.parse(data);
      if (msg.type === 'pong') {
        // keepalive — no-op
      } else if (msg.type === 'logout') {
        console.log('[Flowboard] logout by server');
        cachedUserInfo = null;
        flowKey = null;
      } else if (msg.type === 'please_resend_userinfo') {
        if (cachedUserInfo) ws.send(JSON.stringify({ type: 'user_info', userInfo: cachedUserInfo }));
        else if (flowKey) fetchAndPushUserInfo(flowKey);
      } else if (msg.method === 'api_request') {
        await handleApiRequest(msg);
      } else if (msg.method === 'trpc_request') {
        await handleTrpcRequest(msg);
      } else if (msg.method === 'get_status') {
        ws.send(JSON.stringify({
          id: msg.id,
          result: { state, flowKeyPresent: !!flowKey, manualDisconnect,
                    tokenAge: metrics.tokenCapturedAt ? Date.now() - metrics.tokenCapturedAt : null,
                    metrics },
        }));
      } else if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
      }
    } catch (e) {
      console.error('[Flowboard] message error:', e);
    }
  };

  ws.onerror = (e) => console.error('[Flowboard] WS error:', e);

  ws.onclose = (evt) => {
    ws = null;
    if (evt.code === 4401) {
      console.warn('[Flowboard] Device token rejected (4401) — must log in again on web');
      deviceToken = null;
      chrome.storage.local.remove('deviceToken');
      setState('unpaired');
      return;  // Do NOT auto-reconnect — user must log in first
    }
    if (evt.code === 4408) {
      console.log('[Flowboard] Replaced by newer connection (4408)');
      setState('off');
      return;  // Do NOT reconnect — newer tab took over
    }
    if (!manualDisconnect) {
      setState('off');
      scheduleReconnect();
    }
  };
}
```

- [ ] **Step 6: Update alarm handler**

Replace:
```js
if (alarm.name === 'reconnect') connectToAgent();
```
with:
```js
if (alarm.name === 'reconnect') {
  if (deviceToken) connectToServer(deviceToken);
  else pairWithServer();
}
```

- [ ] **Step 7: Update callback auth in `handleApiRequest` / `handleTrpcRequest`**

Find every place `callbackSecret` is used as a request header:
```
grep -n "callbackSecret\|X-Callback-Secret" extension/background.js
```

Replace each:
```js
'X-Callback-Secret': callbackSecret,
```
with:
```js
'X-Device-Token': deviceToken,
```

- [ ] **Step 8: Verify no stale references**

Run: `grep -n "callbackSecret\|AGENT_WS_URL\|9223\|callback_secret" extension/background.js`
Expected: no output.

- [ ] **Step 9: Update popup to handle `unpaired` state (if applicable)**

In `extension/popup.js` or inline in `popup.html`, find the status display logic and add a case for `'unpaired'`:

```js
case 'unpaired':
  // statusEl is whatever element shows connection status in your popup
  statusEl.textContent = 'Not connected — log in on the web first';
  break;
```

If `popup.js` has no state display or doesn't reference connection states, skip this step.

- [ ] **Step 10: Commit**

```bash
git add extension/background.js extension/popup.js
git commit -m "feat(ext): auto-pair via refresh cookie, wss:// with device token, close 4401/4408"
```

---

## Task 9: Manual browser verification

> Chrome extensions cannot be tested with pytest. Verify these scenarios against a locally running agent.

- [ ] **Scenario 1: Agent starts without `:9223`**

Run: `cd agent && python -m flowboard`
Expected log: `flowboard agent started` — **no** `WebSocket server listening on ws://` line.

- [ ] **Scenario 2: Unlogged extension shows unpaired state**

Load extension as unpacked (`chrome://extensions` → Load unpacked → select `extension/`).
Open popup.
Expected: "Not connected — log in on the web first".

- [ ] **Scenario 3: Login triggers auto-pair**

Open `http://localhost:8101`, register and log in.
Wait up to 30s for the reconnect alarm (or open the extension SW DevTools → Console and call `pairWithServer()`).
Expected: popup shows connected/idle; agent log shows `registry: account X connected`.

- [ ] **Scenario 4: Logout revokes device token**

Click logout in the web app.
Expected: extension popup shows "Not connected — log in on the web first"; agent log shows close code 4401.

- [ ] **Step: Commit any final tweaks**

```bash
git add extension/
git commit -m "chore(ext): verified auto-pair and logout flow"
```

---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| `ConnectionRegistry` with register/unregister/get/is_online | Task 1 |
| Last-wins: old connection closed with 4408 | Task 1 |
| `GET /ext` WebSocket — device token auth → account_id | Task 3 |
| WS close 4401 on bad/revoked token | Task 3 |
| Heartbeat ping/pong ~30s | Task 3 |
| `POST /api/extension/pair` — refresh cookie → DeviceToken | Task 2 |
| Worker uses `registry.get(account_id)` for all handlers | Task 5 |
| `extension_offline` error when no connection | Task 5 |
| `X-Callback-Secret` → `X-Device-Token` in callback route | Task 6 |
| Remove `flow_client` singleton | Task 6 |
| Remove `ws_server.py` `:9223` | Task 6 |
| `routes/auth.py` account-scoped via registry | Task 6 |
| Extension `cookies` permission | Task 7 |
| `pairWithServer()` — reads cookie, calls pair endpoint | Task 8 |
| `connectToServer(token)` — `ws://…/ext?token=` | Task 8 |
| Close 4401 → clear token, unpaired, no auto-reconnect | Task 8 |
| Close 4408 → silent, no reconnect | Task 8 |
| Callback `X-Device-Token` header | Task 8 |

**Out of this plan:** LLM per-user key wiring (Phase 5), S3 media prefix by account (Phase 5), full isolation hardening (Phase 6).
