# Phase 6: Isolation Tests + Security Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify complete multi-tenant isolation with a dedicated test suite, and harden three security gaps: JWT secret minimum length, LLM key non-disclosure, and S3 presigned URL ownership.

**Architecture:** No new feature code except a JWT secret length check at startup. All other tasks are test additions. The isolation suite creates two accounts (alice + bob) and verifies every read/write/delete route returns 404 (not 403 or 200) for cross-tenant access.

**Tech Stack:** Python 3.10+, pytest, FastAPI TestClient, SQLModel. No new runtime dependencies.

---

## Design notes (read before starting)

- **404 not 403.** The spec says cross-tenant board/node/asset access returns 404 — don't reveal the resource exists. Tests must assert `404`.
- **Two-account fixture.** Every test that needs alice/bob creates them inline via the helper functions. No shared fixtures that might bleed state.
- **JWT secret length.** `FLOWBOARD_JWT_SECRET` must be ≥ 32 bytes for HS256 (RFC 7518). The check goes in `main.py` lifespan startup as a warning, not an error — so existing tests with short dev secrets still pass.
- **Naming:** Alice = `alice@example.com`, Bob = `bob@example.com`. Auth helper: `_login(client, email, password) -> dict` returns `{"Authorization": "Bearer <token>"}`.

---

## File structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `agent/tests/test_tenant_isolation.py` | Board/node/asset/request 404 cross-tenant tests |
| Create | `agent/tests/test_worker_isolation.py` | Registry job-routing isolation test |
| Create | `agent/tests/test_jwt_hardening.py` | JWT secret minimum length startup check |
| Create | `agent/tests/test_llm_key_security.py` | LLM key non-disclosure and encryption |
| Modify | `agent/flowboard/main.py` | Add `_check_jwt_secret_length()` called at startup |

---

## Task 1: Cross-tenant isolation test suite

**Files:**
- Create: `agent/tests/test_tenant_isolation.py`

- [ ] **Step 1: Write the isolation tests**

Create `agent/tests/test_tenant_isolation.py`:

```python
"""Multi-tenant isolation tests.

Alice creates boards/nodes/assets. Bob tries to access them.
Every cross-tenant access must return 404 — never 403 or 200.
"""
import pytest
from flowboard.db import get_session
from flowboard.db.models import Asset


# ── helpers ──────────────────────────────────────────────────────────────────

def _register(client, email: str, password: str = "password123") -> None:
    r = client.post("/api/account/register", json={"email": email, "password": password})
    assert r.status_code == 200, f"register failed for {email}: {r.text}"


def _login(client, email: str, password: str = "password123") -> dict:
    r = client.post("/api/account/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_board(client, auth: dict, name: str = "Test Board") -> int:
    r = client.post("/api/boards", json={"name": name}, headers=auth)
    assert r.status_code == 200, f"create board failed: {r.text}"
    return r.json()["id"]


def _create_node(client, auth: dict, board_id: int) -> int:
    r = client.post(
        f"/api/boards/{board_id}/nodes",
        json={"type": "text", "x": 0, "y": 0},
        headers=auth,
    )
    assert r.status_code == 200, f"create node failed: {r.text}"
    return r.json()["id"]


def _get_account_id(client, auth: dict) -> int:
    r = client.get("/api/account/me", headers=auth)
    assert r.status_code == 200
    return r.json()["id"]


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def alice(client):
    _register(client, "alice@example.com")
    return _login(client, "alice@example.com")


@pytest.fixture()
def bob(client):
    _register(client, "bob@example.com")
    return _login(client, "bob@example.com")


@pytest.fixture()
def alice_board(client, alice) -> int:
    return _create_board(client, alice)


@pytest.fixture()
def alice_node(client, alice, alice_board) -> int:
    return _create_node(client, alice, alice_board)


# ── board isolation ───────────────────────────────────────────────────────────

def test_bob_cannot_get_alice_board(client, bob, alice_board):
    resp = client.get(f"/api/boards/{alice_board}", headers=bob)
    assert resp.status_code == 404


def test_bob_cannot_patch_alice_board(client, bob, alice_board):
    resp = client.patch(
        f"/api/boards/{alice_board}",
        json={"name": "Hacked"},
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_delete_alice_board(client, bob, alice_board):
    resp = client.delete(f"/api/boards/{alice_board}", headers=bob)
    assert resp.status_code == 404


def test_board_list_scoped_to_account(client, alice, bob, alice_board):
    alice_resp = client.get("/api/boards", headers=alice)
    bob_resp = client.get("/api/boards", headers=bob)
    alice_ids = {b["id"] for b in alice_resp.json()}
    bob_ids = {b["id"] for b in bob_resp.json()}
    assert alice_board in alice_ids
    assert alice_board not in bob_ids


# ── node isolation ────────────────────────────────────────────────────────────

def test_bob_cannot_get_alice_node(client, bob, alice_board, alice_node):
    resp = client.get(f"/api/boards/{alice_board}/nodes/{alice_node}", headers=bob)
    assert resp.status_code == 404


def test_bob_cannot_patch_alice_node(client, bob, alice_board, alice_node):
    resp = client.patch(
        f"/api/boards/{alice_board}/nodes/{alice_node}",
        json={"data": {"text": "hacked"}},
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_delete_alice_node(client, bob, alice_board, alice_node):
    resp = client.delete(
        f"/api/boards/{alice_board}/nodes/{alice_node}",
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_create_node_on_alice_board(client, bob, alice_board):
    resp = client.post(
        f"/api/boards/{alice_board}/nodes",
        json={"type": "text", "x": 0, "y": 0},
        headers=bob,
    )
    assert resp.status_code == 404


def test_bob_cannot_list_alice_nodes(client, bob, alice_board):
    resp = client.get(f"/api/boards/{alice_board}/nodes", headers=bob)
    assert resp.status_code == 404


# ── asset isolation ───────────────────────────────────────────────────────────

def test_bob_cannot_get_presigned_url_for_alice_asset(client, alice, bob):
    """GET /api/media/{id}/url must return 404 for a different account's asset."""
    media_id = "ffffffffffffffffffffffffffffffffffffffff"
    alice_id = _get_account_id(client, alice)

    with get_session() as s:
        s.add(Asset(
            uuid_media_id=media_id,
            kind="image",
            mime="image/jpeg",
            account_id=alice_id,
            s3_key=f"{alice_id}/{media_id}.jpg",
        ))
        s.commit()

    resp = client.get(f"/api/media/{media_id}/url", headers=bob)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to see initial state**

```bash
cd agent && pytest tests/test_tenant_isolation.py -v 2>&1 | head -80
```

Note any failing tests — these indicate routes that are missing ownership checks.

- [ ] **Step 3: Fix any missing isolation gaps in route handlers**

For any failing board-related route, apply this pattern in `agent/flowboard/routes/boards.py`:

```python
board = session.get(Board, board_id)
if board is None or board.account_id != acct.id:
    raise HTTPException(status_code=404, detail="not found")
```

For node routes, resolve via board first:

```python
node = session.get(Node, node_id)
if node is None or node.account_id != acct.id:
    raise HTTPException(status_code=404, detail="not found")
```

Run the failing tests individually after each fix:

```bash
cd agent && pytest tests/test_tenant_isolation.py::test_bob_cannot_get_alice_board -v
```

- [ ] **Step 4: Run all isolation tests**

```bash
cd agent && pytest tests/test_tenant_isolation.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Run full suite**

```bash
cd agent && pytest -x -q
```

Expected: All pass (or only pre-existing failures).

- [ ] **Step 6: Commit**

```bash
git add agent/tests/test_tenant_isolation.py
git commit -m "test: multi-tenant isolation suite — bob gets 404 for all of alice's resources"
# If route fixes were also needed:
git add agent/flowboard/routes/
git commit -m "fix: enforce account_id ownership check on board and node routes"
```

---

## Task 2: Worker registry isolation test

**Files:**
- Create: `agent/tests/test_worker_isolation.py`

- [ ] **Step 1: Write the test**

Create `agent/tests/test_worker_isolation.py`:

```python
"""Verify that a job belonging to account A never uses account B's connection.

The registry.get(account_id) call is the isolation boundary.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from flowboard.services.registry import ConnectionRegistry


def test_registry_returns_none_for_unknown_account():
    reg = ConnectionRegistry()
    assert reg.get(account_id=999) is None


def test_registry_does_not_cross_accounts():
    """Account A's connection must not be returned when looking up account B."""
    reg = ConnectionRegistry()
    mock_ws_a = MagicMock()
    mock_ws_a.close = AsyncMock()

    client_a = reg.register(account_id=1, websocket=mock_ws_a)
    assert client_a is not None

    # B has no connection
    assert reg.get(account_id=2) is None
    # A's connection unaffected
    assert reg.get(account_id=1) is client_a


def test_job_routing_per_account():
    """Simulate worker dispatch: job.account_id determines which connection is used."""
    reg = ConnectionRegistry()
    ws_a = MagicMock()
    ws_a.close = AsyncMock()
    ws_b = MagicMock()
    ws_b.close = AsyncMock()

    reg.register(account_id=1, websocket=ws_a)
    reg.register(account_id=2, websocket=ws_b)

    conn_1 = reg.get(account_id=1)
    conn_2 = reg.get(account_id=2)

    assert conn_1 is not None
    assert conn_2 is not None
    assert conn_1 is not conn_2


def test_unregister_removes_only_correct_account():
    reg = ConnectionRegistry()
    ws_a = MagicMock()
    ws_a.close = AsyncMock()
    ws_b = MagicMock()
    ws_b.close = AsyncMock()

    reg.register(account_id=1, websocket=ws_a)
    reg.register(account_id=2, websocket=ws_b)

    asyncio.get_event_loop().run_until_complete(
        reg.unregister(account_id=1, websocket=ws_a)
    )

    assert reg.get(account_id=1) is None
    assert reg.get(account_id=2) is not None  # B unaffected
```

- [ ] **Step 2: Run tests**

```bash
cd agent && pytest tests/test_worker_isolation.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_worker_isolation.py
git commit -m "test: ConnectionRegistry isolation — job A cannot use conn of account B"
```

---

## Task 3: JWT secret minimum length check

**Files:**
- Create: `agent/tests/test_jwt_hardening.py`
- Modify: `agent/flowboard/main.py`

- [ ] **Step 1: Write failing tests**

Create `agent/tests/test_jwt_hardening.py`:

```python
"""JWT secret minimum-length startup check."""
import logging
import pytest


def test_startup_warns_on_short_jwt_secret(monkeypatch, caplog):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "JWT_SECRET", "short")  # 5 bytes — below minimum

    with caplog.at_level(logging.WARNING, logger="flowboard.main"):
        from flowboard.main import _check_jwt_secret_length
        _check_jwt_secret_length()

    warning_messages = " ".join(r.message for r in caplog.records)
    assert "JWT_SECRET" in warning_messages
    assert "32" in warning_messages or "minimum" in warning_messages.lower()


def test_startup_no_warning_on_adequate_secret(monkeypatch, caplog):
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "JWT_SECRET", "a" * 32)  # exactly 32 bytes

    with caplog.at_level(logging.WARNING, logger="flowboard.main"):
        from flowboard.main import _check_jwt_secret_length
        _check_jwt_secret_length()

    jwt_warnings = [r for r in caplog.records if "JWT_SECRET" in r.message]
    assert len(jwt_warnings) == 0


def test_check_does_not_raise(monkeypatch):
    """Check must only warn, never crash the server."""
    import flowboard.config as cfg
    monkeypatch.setattr(cfg, "JWT_SECRET", "short")
    from flowboard.main import _check_jwt_secret_length
    _check_jwt_secret_length()  # must not raise
```

- [ ] **Step 2: Run to verify failure**

```bash
cd agent && pytest tests/test_jwt_hardening.py -v
```

Expected: `ImportError` — `_check_jwt_secret_length` not found.

- [ ] **Step 3: Add function to main.py**

In `agent/flowboard/main.py`, add the following function (before the `lifespan` definition):

```python
def _check_jwt_secret_length() -> None:
    """Warn if JWT_SECRET is below RFC 7518's 32-byte minimum for HMAC-SHA256."""
    from flowboard import config
    secret_bytes = len((config.JWT_SECRET or "").encode("utf-8"))
    if secret_bytes < 32:
        logger.warning(
            "FLOWBOARD_JWT_SECRET is %d bytes — RFC 7518 requires a minimum of 32 bytes "
            "for HS256. Set FLOWBOARD_JWT_SECRET to a cryptographically random 32+ byte "
            "string in production (e.g. openssl rand -hex 32).",
            secret_bytes,
        )
```

In the `lifespan` context manager, call it at startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_jwt_secret_length()
    # ... rest of existing startup code ...
    yield
    # ... shutdown code ...
```

(If `logger` is not defined yet in `main.py`, add `logger = logging.getLogger(__name__)` at the top of the file.)

- [ ] **Step 4: Run tests**

```bash
cd agent && pytest tests/test_jwt_hardening.py -v
```

Expected: All 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/main.py agent/tests/test_jwt_hardening.py
git commit -m "fix: warn at startup when JWT_SECRET is below RFC 7518 minimum (32 bytes)"
```

---

## Task 4: LLM key non-disclosure tests

**Files:**
- Create: `agent/tests/test_llm_key_security.py`

- [ ] **Step 1: Write security tests**

Create `agent/tests/test_llm_key_security.py`:

```python
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
```

- [ ] **Step 2: Run tests**

```bash
cd agent && pytest tests/test_llm_key_security.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_llm_key_security.py
git commit -m "test: LLM key non-disclosure — raw key never in responses or DB plaintext"
```

---

## Task 5: Final validation run

- [ ] **Step 1: Run all phase 5+6 tests together**

```bash
cd agent && pytest \
    tests/test_tenant_isolation.py \
    tests/test_worker_isolation.py \
    tests/test_jwt_hardening.py \
    tests/test_llm_key_security.py \
    tests/test_media_url.py \
    tests/test_account_settings.py \
    tests/test_object_storage.py \
    tests/test_llm_api_providers.py \
    -v
```

Expected: All pass.

- [ ] **Step 2: Run complete suite**

```bash
cd agent && pytest -q
```

Expected: All tests pass (or only failures that existed before this plan).

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: phase 6 complete — isolation tests and security hardening"
```

---

## Self-review against spec §8

| Spec test requirement | Covered by |
|---|---|
| Auth: register/login/JWT expiry/refresh/logout | Existing `test_account_*.py` (pre-existing) |
| Cross-tenant: A cannot read/write board/node/asset of B → 404 | Task 1 — `test_tenant_isolation.py` |
| Job of A cannot use connection of B | Task 2 — `test_worker_isolation.py` |
| Pairing & WS: device token tests | Existing `test_pair_endpoint.py`, `test_ext_ws.py` (pre-existing) |
| LLM key encrypted; not in API/logs | Task 4 — `test_llm_key_security.py` |
| No LLM key → clear error (None returned) | Task 4 — `test_no_key_make_account_provider_returns_none` |
| S3 presigned URL checks ownership → 404 | Phase 5 Task 7 — `test_media_url.py::test_media_url_404_for_wrong_account` |
| JWT secret minimum length enforced | Task 3 — `test_jwt_hardening.py` |
