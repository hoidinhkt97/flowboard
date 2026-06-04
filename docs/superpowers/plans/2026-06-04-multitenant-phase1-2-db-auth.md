# Multi-tenant Phase 1+2 — DB Foundation & Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the multi-tenant database foundation (Account model, `account_id` scoping, configurable Postgres-capable engine, Alembic) and minimal email/password auth (register/login/refresh/logout/me + a `get_current_account` dependency), then enforce tenant isolation on the Board routes as the reference pattern.

**Architecture:** Keep the existing FastAPI + SQLModel agent. Make the DB engine read `DATABASE_URL` (default SQLite for tests/dev, `postgresql+psycopg://…` in production). Add `Account`, `RefreshToken`, `DeviceToken` tables and an `account_id` foreign key on `Board` (denormalized onto `Node`, `Request`, `Asset`). Add a new auth router under `/api/account` (the existing `/api/auth/*` routes are the extension-identity surface and stay untouched). All board access resolves `account_id` from the JWT and returns 404 on cross-tenant access.

**Tech Stack:** Python 3.10+, FastAPI, SQLModel/SQLAlchemy, Alembic, PyJWT, passlib[bcrypt], cryptography (Fernet), psycopg (prod), pytest + TestClient.

**Supersedes:** `docs/superpowers/plans/2026-05-18-saas-hosting.md` (an earlier single-shared-token approach — not multi-tenant). Do not implement both.

---

## Design notes (read before starting)

- **Tests stay on SQLite.** `agent/tests/conftest.py` sets `FLOWBOARD_DB` and drops/recreates `SQLModel.metadata` per test. We add `DATABASE_URL` support but the default keeps tests on SQLite. Alembic targets whatever `DATABASE_URL` points at (Postgres in prod); tests do NOT run Alembic — they use `metadata.create_all` as today.
- **New auth lives at `/api/account`,** not `/api/auth`. `routes/auth.py` already owns `/api/auth/me`, `/api/auth/logout`, `/api/auth/scan` for the extension identity surface and is covered by `test_auth.py`. Do not touch it.
- **`account_id` is nullable** on `Board`/`Node`/`Request`/`Asset` for transition safety. Routes always set it from the JWT; isolation is enforced in the route layer, not by a NOT NULL constraint (yet).
- **Naming locked for cross-task consistency:** `Account`, `RefreshToken`, `DeviceToken`; functions `hash_password`, `verify_password`, `create_access_token`, `decode_access_token`, `generate_token`, `hash_token`, `encrypt_secret`, `decrypt_secret`; dependency `get_current_account`; helper `owned_or_404`.

---

# PHASE 1 — DB Foundation & Multi-tenancy

## Task 1: Add Python dependencies

**Files:**
- Modify: `agent/requirements.txt`
- Modify: `agent/pyproject.toml:6-14`

- [ ] **Step 1: Add runtime deps to `requirements.txt`**

Append these lines to `agent/requirements.txt`:

```
alembic>=1.13
psycopg[binary]>=3.2
passlib[bcrypt]>=1.7
pyjwt>=2.9
cryptography>=43.0
email-validator>=2.0
```

- [ ] **Step 2: Mirror deps in `pyproject.toml`**

In `agent/pyproject.toml`, extend the `dependencies` list (lines 6-14) so it reads:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlmodel>=0.0.22",
    "pydantic>=2.8",
    "websockets>=12.0",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "passlib[bcrypt]>=1.7",
    "pyjwt>=2.9",
    "cryptography>=43.0",
    "email-validator>=2.0",
]
```

- [ ] **Step 3: Install and verify imports**

Run: `cd agent && python -m pip install -e ".[dev]"`
Then run: `cd agent && python -c "import alembic, jwt, passlib.hash, cryptography.fernet, psycopg, email_validator; print('ok')"`
Expected: prints `ok` (psycopg import works even without a live Postgres).

- [ ] **Step 4: Commit**

```bash
git add agent/requirements.txt agent/pyproject.toml
git commit -m "build: add alembic, auth, and postgres deps"
```

---

## Task 2: Make the DB engine configurable via DATABASE_URL

**Files:**
- Modify: `agent/flowboard/config.py:1-18`
- Modify: `agent/flowboard/db/session.py:1-19`
- Test: `agent/tests/test_engine_config.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_engine_config.py`:

```python
"""The engine URL must come from config so production can point at Postgres
while tests/dev stay on SQLite."""
from flowboard.config import DATABASE_URL


def test_database_url_defaults_to_sqlite():
    assert DATABASE_URL.startswith("sqlite")


def test_engine_uses_database_url():
    from flowboard.db.session import engine
    assert engine.url.get_backend_name() == "sqlite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_engine_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'DATABASE_URL'`.

- [ ] **Step 3: Add `DATABASE_URL` (and future config) to `config.py`**

In `agent/flowboard/config.py`, after the `DB_PATH` line (line 6), add:

```python
DATABASE_URL = os.getenv("FLOWBOARD_DATABASE_URL", f"sqlite:///{DB_PATH}")

# --- Auth / security config (used in Phase 2) ---
JWT_SECRET = os.getenv("FLOWBOARD_JWT_SECRET", "dev-insecure-jwt-secret-change-me")
JWT_ALG = "HS256"
ACCESS_TOKEN_TTL_MIN = int(os.getenv("FLOWBOARD_ACCESS_TTL_MIN", "15"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("FLOWBOARD_REFRESH_TTL_DAYS", "30"))
DEVICE_TOKEN_TTL_DAYS = int(os.getenv("FLOWBOARD_DEVICE_TOKEN_TTL_DAYS", "90"))
# Fernet key (urlsafe-base64, 32 bytes). Empty in dev/tests → a fixed insecure
# dev key is derived in services/security.py so encryption round-trips locally.
ENCRYPTION_KEY = os.getenv("FLOWBOARD_ENCRYPTION_KEY", "")
```

- [ ] **Step 4: Use `DATABASE_URL` in `session.py`**

Replace the top of `agent/flowboard/db/session.py` (lines 1-19) with:

```python
from contextlib import contextmanager

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from flowboard.config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
```

Leave `init_db()` and `get_session()` (lines 22-59) unchanged.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_engine_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `cd agent && python -m pytest -q`
Expected: all existing tests still pass (333 + 2 new).

- [ ] **Step 7: Commit**

```bash
git add agent/flowboard/config.py agent/flowboard/db/session.py agent/tests/test_engine_config.py
git commit -m "feat: read engine URL from DATABASE_URL (postgres-capable)"
```

---

## Task 3: Add the Account model

**Files:**
- Modify: `agent/flowboard/db/models.py:12` (insert above `Board`)
- Test: `agent/tests/test_account_model.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_model.py`:

```python
from flowboard.db import get_session
from flowboard.db.models import Account
from sqlmodel import select


def test_account_round_trips():
    with get_session() as s:
        acct = Account(email="a@example.com", password_hash="x")
        s.add(acct)
        s.commit()
        s.refresh(acct)
        assert isinstance(acct.id, int)

    with get_session() as s:
        got = s.exec(select(Account).where(Account.email == "a@example.com")).one()
        assert got.password_hash == "x"
        assert got.llm_provider is None
        assert got.llm_api_key_enc is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'Account'`.

- [ ] **Step 3: Add the `Account` model**

In `agent/flowboard/db/models.py`, after the `_utcnow` helper (line 9) and before `class Board` (line 12), insert:

```python
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=_utcnow)
    # Per-user LLM credentials (populated in a later phase).
    llm_provider: Optional[str] = None  # "claude" | "gemini" | "codex"
    llm_api_key_enc: Optional[bytes] = None  # Fernet-encrypted ciphertext
    # Google profile pushed by the extension (optional, filled later).
    google_email: Optional[str] = None
    google_name: Optional[str] = None
    google_picture: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_model.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/db/models.py agent/tests/test_account_model.py
git commit -m "feat: add Account model"
```

---

## Task 4: Add RefreshToken and DeviceToken models

**Files:**
- Modify: `agent/flowboard/db/models.py` (append after `Account`)
- Test: `agent/tests/test_token_models.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_token_models.py`:

```python
from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken, RefreshToken
from sqlmodel import select


def _make_account(s) -> int:
    a = Account(email="t@example.com", password_hash="x")
    s.add(a)
    s.commit()
    s.refresh(a)
    return a.id


def test_refresh_token_round_trips():
    with get_session() as s:
        aid = _make_account(s)
        s.add(RefreshToken(account_id=aid, token_hash="abc"))
        s.commit()
        row = s.exec(select(RefreshToken).where(RefreshToken.token_hash == "abc")).one()
        assert row.account_id == aid
        assert row.revoked_at is None


def test_device_token_round_trips():
    with get_session() as s:
        aid = _make_account(s)
        s.add(DeviceToken(account_id=aid, token_hash="dev", label="chrome"))
        s.commit()
        row = s.exec(select(DeviceToken).where(DeviceToken.token_hash == "dev")).one()
        assert row.account_id == aid
        assert row.label == "chrome"
        assert row.revoked_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_token_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'DeviceToken'`.

- [ ] **Step 3: Add both models**

In `agent/flowboard/db/models.py`, immediately after the `Account` class, add:

```python
class RefreshToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    token_hash: str = Field(index=True)  # sha256 of the raw refresh token
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)


class DeviceToken(SQLModel, table=True):
    """Token the Chrome extension presents to open its authenticated WS.
    Minted by the pairing endpoint (later phase); revocable on logout."""
    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    token_hash: str = Field(index=True)  # sha256 of the raw device token
    label: str = ""
    expires_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_token_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/db/models.py agent/tests/test_token_models.py
git commit -m "feat: add RefreshToken and DeviceToken models"
```

---

## Task 5: Add account_id to Board (denormalized onto Node, Request, Asset)

**Files:**
- Modify: `agent/flowboard/db/models.py` (`Board`, `Node`, `Request`, `Asset`)
- Test: `agent/tests/test_account_columns.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_columns.py`:

```python
from flowboard.db import get_session
from flowboard.db.models import Account, Asset, Board, Node, Request


def test_board_and_children_carry_account_id():
    with get_session() as s:
        a = Account(email="own@example.com", password_hash="x")
        s.add(a)
        s.commit()
        s.refresh(a)

        b = Board(name="B", account_id=a.id)
        s.add(b)
        s.commit()
        s.refresh(b)
        assert b.account_id == a.id

        n = Node(board_id=b.id, account_id=a.id, short_id="n1", type="image")
        r = Request(type="proxy", account_id=a.id)
        asset = Asset(kind="image", account_id=a.id)
        s.add(n); s.add(r); s.add(asset)
        s.commit()
        s.refresh(n); s.refresh(r); s.refresh(asset)
        assert n.account_id == a.id
        assert r.account_id == a.id
        assert asset.account_id == a.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_columns.py -v`
Expected: FAIL with `TypeError: 'account_id' is an invalid keyword argument for Board`.

- [ ] **Step 3: Add the columns**

In `agent/flowboard/db/models.py`:

In `class Board` (after the `name` field, line 14) add:

```python
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
```

In `class Node` (after `board_id`, line 20) add:

```python
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
```

In `class Request` (after `node_id`, line 54) add:

```python
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
```

In `class Asset` (after `node_id`, line 68) add:

```python
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_columns.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full suite**

Run: `cd agent && python -m pytest -q`
Expected: all green (existing tests create boards without `account_id`, which is now nullable — still fine).

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/db/models.py agent/tests/test_account_columns.py
git commit -m "feat: add nullable account_id to Board/Node/Request/Asset"
```

---

## Task 6: Add the `owned_or_404` scoping helper

**Files:**
- Create: `agent/flowboard/db/scoping.py`
- Test: `agent/tests/test_scoping_helper.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_scoping_helper.py`:

```python
import pytest
from fastapi import HTTPException

from flowboard.db import get_session
from flowboard.db.models import Account, Board
from flowboard.db.scoping import owned_or_404


def _account(s, email):
    a = Account(email=email, password_hash="x")
    s.add(a); s.commit(); s.refresh(a)
    return a.id


def test_owned_or_404_returns_row_for_owner():
    with get_session() as s:
        aid = _account(s, "owner@example.com")
        b = Board(name="b", account_id=aid)
        s.add(b); s.commit(); s.refresh(b)
        got = owned_or_404(s, Board, b.id, aid)
        assert got.id == b.id


def test_owned_or_404_raises_404_for_other_account():
    with get_session() as s:
        owner = _account(s, "owner2@example.com")
        other = _account(s, "other@example.com")
        b = Board(name="b", account_id=owner)
        s.add(b); s.commit(); s.refresh(b)
        with pytest.raises(HTTPException) as ei:
            owned_or_404(s, Board, b.id, other)
        assert ei.value.status_code == 404


def test_owned_or_404_raises_404_for_missing_row():
    with get_session() as s:
        aid = _account(s, "owner3@example.com")
        with pytest.raises(HTTPException) as ei:
            owned_or_404(s, Board, 999999, aid)
        assert ei.value.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_scoping_helper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowboard.db.scoping'`.

- [ ] **Step 3: Write the helper**

Create `agent/flowboard/db/scoping.py`:

```python
"""Tenant-isolation helpers. Every multi-tenant route resolves rows through
these so a cross-tenant id always looks like 'not found' (404), never 403 —
we don't leak the existence of another account's data."""
from __future__ import annotations

from fastapi import HTTPException


def owned_or_404(session, model, pk, account_id):
    """Fetch `model` by primary key, but only if it belongs to `account_id`.
    Raises 404 for missing rows AND for rows owned by a different account."""
    row = session.get(model, pk)
    if row is None or getattr(row, "account_id", None) != account_id:
        raise HTTPException(status_code=404, detail=f"{model.__name__.lower()} not found")
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_scoping_helper.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/db/scoping.py agent/tests/test_scoping_helper.py
git commit -m "feat: add owned_or_404 tenant-isolation helper"
```

---

## Task 7: Alembic scaffolding + baseline migration (production Postgres)

**Files:**
- Create: `agent/alembic.ini`
- Create: `agent/migrations/env.py`
- Create: `agent/migrations/script.py.mako`
- Create: `agent/migrations/versions/0001_baseline.py` (autogenerated, then reviewed)

> Migrations are verification-driven, not TDD — they target production Postgres. Tests keep using `metadata.create_all` (Task 2 design note).

- [ ] **Step 1: Initialise Alembic**

Run: `cd agent && python -m alembic init migrations`
This creates `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, and an empty `migrations/versions/`.

- [ ] **Step 2: Point Alembic at our models + DATABASE_URL**

Replace the body of `agent/migrations/env.py` so it imports our metadata and URL. Ensure these key lines are present (adapt around the Alembic template scaffolding):

```python
from flowboard.config import DATABASE_URL
from flowboard.db import models  # noqa: F401  (import side-effect: registers tables)
from sqlmodel import SQLModel

config.set_main_option("sqlalchemy.url", DATABASE_URL)
target_metadata = SQLModel.metadata
```

In `agent/alembic.ini`, leave `sqlalchemy.url` blank (it is overridden in `env.py` from `DATABASE_URL`).

- [ ] **Step 3: Autogenerate the baseline against a scratch Postgres**

Run (with a disposable Postgres, e.g. `docker run --rm -e POSTGRES_PASSWORD=pw -p 5432:5432 -d postgres:16`):

```bash
cd agent && FLOWBOARD_DATABASE_URL="postgresql+psycopg://postgres:pw@localhost:5432/postgres" \
  python -m alembic revision --autogenerate -m "baseline"
```

Rename the generated file to `migrations/versions/0001_baseline.py`. Open it and confirm it creates: `account`, `refreshtoken`, `devicetoken`, `board` (+`account_id`), `node` (+`account_id`), `edge`, `request` (+`account_id`), `asset` (+`account_id`), and every other existing table. Remove any spurious drops.

- [ ] **Step 4: Apply and verify**

Run:

```bash
cd agent && FLOWBOARD_DATABASE_URL="postgresql+psycopg://postgres:pw@localhost:5432/postgres" \
  python -m alembic upgrade head
```

Expected: completes without error; `\dt` in psql shows all tables including `account`, `devicetoken`, `refreshtoken`.

- [ ] **Step 5: Commit**

```bash
git add agent/alembic.ini agent/migrations
git commit -m "build: alembic baseline migration for postgres"
```

---

# PHASE 2 — Minimal Auth (email/password)

## Task 8: Password hashing utilities

**Files:**
- Create: `agent/flowboard/services/security.py`
- Test: `agent/tests/test_security_password.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_security_password.py`:

```python
from flowboard.services.security import hash_password, verify_password


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("s3cret!")
    assert h != "s3cret!"
    assert verify_password("s3cret!", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("s3cret!")
    assert verify_password("nope", h) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_security_password.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowboard.services.security'`.

- [ ] **Step 3: Write the password helpers**

Create `agent/flowboard/services/security.py`:

```python
"""Auth primitives: password hashing, JWT, opaque token gen/hash, and
Fernet encryption for per-user secrets."""
from __future__ import annotations

from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plaintext: str) -> str:
    return _pwd.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    return _pwd.verify(plaintext, hashed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_security_password.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/services/security.py agent/tests/test_security_password.py
git commit -m "feat: password hashing helpers"
```

---

## Task 9: JWT access tokens

**Files:**
- Modify: `agent/flowboard/services/security.py`
- Test: `agent/tests/test_security_jwt.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_security_jwt.py`:

```python
import pytest

from flowboard.services.security import create_access_token, decode_access_token


def test_round_trip_carries_account_id():
    tok = create_access_token(account_id=42)
    claims = decode_access_token(tok)
    assert claims["sub"] == "42"


def test_decode_rejects_garbage():
    with pytest.raises(Exception):
        decode_access_token("not-a-jwt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_security_jwt.py -v`
Expected: FAIL with `ImportError: cannot import name 'create_access_token'`.

- [ ] **Step 3: Add JWT helpers**

Append to `agent/flowboard/services/security.py`:

```python
from datetime import datetime, timedelta, timezone

import jwt

from flowboard.config import ACCESS_TOKEN_TTL_MIN, JWT_ALG, JWT_SECRET


def create_access_token(account_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(account_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_TTL_MIN)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_security_jwt.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/services/security.py agent/tests/test_security_jwt.py
git commit -m "feat: JWT access token helpers"
```

---

## Task 10: Opaque token gen/hash + Fernet encryption

**Files:**
- Modify: `agent/flowboard/services/security.py`
- Test: `agent/tests/test_security_tokens.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_security_tokens.py`:

```python
from flowboard.services.security import (
    decrypt_secret,
    encrypt_secret,
    generate_token,
    hash_token,
)


def test_generate_token_is_random_and_long():
    a, b = generate_token(), generate_token()
    assert a != b
    assert len(a) >= 32


def test_hash_token_is_stable_and_opaque():
    raw = "abc123"
    assert hash_token(raw) == hash_token(raw)
    assert hash_token(raw) != raw


def test_encrypt_decrypt_round_trips():
    blob = encrypt_secret("sk-ant-secret")
    assert isinstance(blob, bytes)
    assert blob != b"sk-ant-secret"
    assert decrypt_secret(blob) == "sk-ant-secret"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_security_tokens.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_token'`.

- [ ] **Step 3: Add token + encryption helpers**

Append to `agent/flowboard/services/security.py`:

```python
import hashlib
import secrets

from cryptography.fernet import Fernet

from flowboard.config import ENCRYPTION_KEY

# Dev/test fallback so encryption round-trips without a configured key.
# Production MUST set FLOWBOARD_ENCRYPTION_KEY to a real Fernet key.
_DEV_FERNET_KEY = "ZmtkZXZrZXlfZmtkZXZrZXlfZmtkZXZrZXlfZmtkZXY="
_fernet = Fernet((ENCRYPTION_KEY or _DEV_FERNET_KEY).encode())


def generate_token() -> str:
    """Opaque, URL-safe random token (refresh + device tokens)."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Stable sha256 hex digest stored in place of the raw token."""
    return hashlib.sha256(raw.encode()).hexdigest()


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode())


def decrypt_secret(blob: bytes) -> str:
    return _fernet.decrypt(blob).decode()
```

> Note: `_DEV_FERNET_KEY` must be a valid 32-byte urlsafe-base64 Fernet key. If `Fernet(...)` raises at import time, regenerate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and paste it in.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_security_tokens.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/services/security.py agent/tests/test_security_tokens.py
git commit -m "feat: opaque token gen/hash + Fernet secret encryption"
```

---

## Task 11: The `get_current_account` dependency

**Files:**
- Create: `agent/flowboard/deps.py`
- Test: `agent/tests/test_get_current_account.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_get_current_account.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.deps import get_current_account
from flowboard.services.security import create_access_token


@pytest.fixture
def mini_app():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(acct: Account = Depends(get_current_account)):
        return {"id": acct.id, "email": acct.email}

    return TestClient(app)


def _make_account(email="dep@example.com") -> int:
    with get_session() as s:
        a = Account(email=email, password_hash="x")
        s.add(a); s.commit(); s.refresh(a)
        return a.id


def test_valid_token_resolves_account(mini_app):
    aid = _make_account()
    tok = create_access_token(aid)
    r = mini_app.get("/whoami", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json() == {"id": aid, "email": "dep@example.com"}


def test_missing_header_is_401(mini_app):
    assert mini_app.get("/whoami").status_code == 401


def test_garbage_token_is_401(mini_app):
    r = mini_app.get("/whoami", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_get_current_account.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'flowboard.deps'`.

- [ ] **Step 3: Write the dependency**

Create `agent/flowboard/deps.py`:

```python
"""Shared FastAPI dependencies for tenant-aware routes."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.services.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_account(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Account:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = decode_access_token(creds.credentials)
        account_id = int(claims["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    with get_session() as s:
        acct = s.get(Account, account_id)
    if acct is None:
        raise HTTPException(status_code=401, detail="account not found")
    return acct
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_get_current_account.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/deps.py agent/tests/test_get_current_account.py
git commit -m "feat: get_current_account bearer dependency"
```

---

## Task 12: Register endpoint

**Files:**
- Create: `agent/flowboard/routes/account_auth.py`
- Modify: `agent/flowboard/main.py:12,103`
- Test: `agent/tests/test_account_register.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_register.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_register.py -v`
Expected: FAIL with 404 (route not mounted yet).

- [ ] **Step 3: Create the router with `/register`**

Create `agent/flowboard/routes/account_auth.py`:

```python
"""Email/password account auth (multi-tenant). Distinct from routes/auth.py,
which is the extension-identity surface (/api/auth/*)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Account
from flowboard.services.security import hash_password

router = APIRouter(prefix="/api/account", tags=["account"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
def register(body: RegisterBody):
    with get_session() as s:
        exists = s.exec(select(Account).where(Account.email == body.email)).first()
        if exists:
            raise HTTPException(status_code=409, detail="email already registered")
        acct = Account(email=str(body.email), password_hash=hash_password(body.password))
        s.add(acct)
        s.commit()
        s.refresh(acct)
        return {"id": acct.id, "email": acct.email}
```

- [ ] **Step 4: Mount the router in `main.py`**

In `agent/flowboard/main.py`, line 12, add `account_auth` to the route imports:

```python
from flowboard.routes import account_auth, activity, auth, boards, chat, edges, flow_projects, llm, media, nodes, plans, projects, prompt, upload, vision
```

After `app.include_router(auth.router)` (line 103) add:

```python
app.include_router(account_auth.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_register.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/routes/account_auth.py agent/flowboard/main.py agent/tests/test_account_register.py
git commit -m "feat: account register endpoint"
```

---

## Task 13: Login endpoint (access token + refresh cookie)

**Files:**
- Modify: `agent/flowboard/routes/account_auth.py`
- Test: `agent/tests/test_account_login.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_login.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_login.py -v`
Expected: FAIL with 404/405 (route missing).

- [ ] **Step 3: Add the `/login` endpoint**

Replace the import block at the top of `agent/flowboard/routes/account_auth.py` with:

```python
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlmodel import select

from flowboard.config import REFRESH_TOKEN_TTL_DAYS
from flowboard.db import get_session
from flowboard.db.models import Account, DeviceToken, RefreshToken
from flowboard.deps import get_current_account
from flowboard.services.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
```

(That import block is the final shape used by Tasks 13–16; later tasks reuse `Cookie`, `Depends`, `DeviceToken`, etc.)

Append the login route:

```python
class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(body: LoginBody, response: Response):
    with get_session() as s:
        acct = s.exec(select(Account).where(Account.email == body.email)).first()
        if acct is None or not verify_password(body.password, acct.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")

        raw_refresh = generate_token()
        s.add(RefreshToken(
            account_id=acct.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
        ))
        s.commit()
        access = create_access_token(acct.id)

    response.set_cookie(
        key="fb_refresh",
        value=raw_refresh,
        httponly=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_TTL_DAYS * 24 * 3600,
        path="/api/account",
    )
    return {"access_token": access, "token_type": "bearer"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_login.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/routes/account_auth.py agent/tests/test_account_login.py
git commit -m "feat: account login (access token + refresh cookie)"
```

---

## Task 14: Refresh endpoint

**Files:**
- Modify: `agent/flowboard/routes/account_auth.py`
- Test: `agent/tests/test_account_refresh.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_refresh.py`:

```python
def _login(client, email="ref@example.com", pw="pw123456"):
    client.post("/api/account/register", json={"email": email, "password": pw})
    return client.post("/api/account/login", json={"email": email, "password": pw})


def test_refresh_with_cookie_returns_new_access_token(client):
    _login(client)  # TestClient persists the fb_refresh cookie on the client
    r = client.post("/api/account/refresh")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["access_token"], str) and r.json()["access_token"]


def test_refresh_without_cookie_is_401(client):
    r = client.post("/api/account/refresh")
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_refresh.py -v`
Expected: FAIL with 404/405.

- [ ] **Step 3: Add the `/refresh` endpoint**

Append to `agent/flowboard/routes/account_auth.py` (imports already include `Cookie`):

```python
@router.post("/refresh")
def refresh(fb_refresh: str | None = Cookie(default=None)):
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
        access = create_access_token(row.account_id)
    return {"access_token": access, "token_type": "bearer"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_refresh.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/routes/account_auth.py agent/tests/test_account_refresh.py
git commit -m "feat: account token refresh endpoint"
```

---

## Task 15: Account logout endpoint (revoke refresh + device tokens)

**Files:**
- Modify: `agent/flowboard/routes/account_auth.py`
- Test: `agent/tests/test_account_logout.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_logout.py`:

```python
def _login(client, email="lo@example.com", pw="pw123456"):
    client.post("/api/account/register", json={"email": email, "password": pw})
    return client.post("/api/account/login", json={"email": email, "password": pw})


def test_logout_revokes_refresh_then_refresh_fails(client):
    _login(client)
    assert client.post("/api/account/logout").status_code == 200
    # Cookie still present on the client but the token is now revoked.
    assert client.post("/api/account/refresh").status_code == 401


def test_logout_without_cookie_is_ok(client):
    r = client.post("/api/account/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_logout.py -v`
Expected: FAIL with 404/405.

- [ ] **Step 3: Add the `/logout` endpoint**

Append to `agent/flowboard/routes/account_auth.py` (imports already include `Cookie`, `DeviceToken`):

```python
@router.post("/logout")
def logout(response: Response, fb_refresh: str | None = Cookie(default=None)):
    if fb_refresh:
        now = datetime.now(timezone.utc)
        with get_session() as s:
            row = s.exec(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(fb_refresh))
            ).first()
            if row is not None and row.revoked_at is None:
                row.revoked_at = now
                s.add(row)
                # Revoke this account's device tokens so the extension WS drops.
                devs = s.exec(
                    select(DeviceToken).where(
                        DeviceToken.account_id == row.account_id,
                        DeviceToken.revoked_at.is_(None),
                    )
                ).all()
                for d in devs:
                    d.revoked_at = now
                    s.add(d)
                s.commit()
    response.delete_cookie("fb_refresh", path="/api/account")
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_logout.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/routes/account_auth.py agent/tests/test_account_logout.py
git commit -m "feat: account logout revokes refresh + device tokens"
```

---

## Task 16: Account `/me` endpoint

**Files:**
- Modify: `agent/flowboard/routes/account_auth.py`
- Test: `agent/tests/test_account_me.py`

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_account_me.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_account_me.py -v`
Expected: FAIL with 404.

- [ ] **Step 3: Add the `/me` endpoint**

Append to `agent/flowboard/routes/account_auth.py` (imports already include `Depends`, `get_current_account`):

```python
@router.get("/me")
def me(acct: Account = Depends(get_current_account)):
    return {
        "id": acct.id,
        "email": acct.email,
        "llm_provider": acct.llm_provider,
        "google_email": acct.google_email,
        "google_name": acct.google_name,
        "google_picture": acct.google_picture,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_account_me.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/flowboard/routes/account_auth.py agent/tests/test_account_me.py
git commit -m "feat: account /me endpoint"
```

---

## Task 17: Enforce tenant isolation on Board routes (reference pattern)

**Files:**
- Modify: `agent/flowboard/routes/boards.py` (all handlers)
- Modify: `agent/tests/test_boards.py` (existing tests must send auth)
- Test: `agent/tests/test_board_isolation.py`

> This is the reference implementation other routers copy in Task 18. Boards become account-scoped: list returns only the caller's boards; get/patch/delete use `owned_or_404`; create stamps `account_id`.

- [ ] **Step 1: Write the failing isolation test**

Create `agent/tests/test_board_isolation.py`:

```python
def _token(client, email):
    client.post("/api/account/register", json={"email": email, "password": "pw123456"})
    return client.post("/api/account/login",
                       json={"email": email, "password": "pw123456"}).json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_account_only_sees_own_boards(client):
    a = _token(client, "a@example.com")
    b = _token(client, "b@example.com")
    client.post("/api/boards", json={"name": "A-board"}, headers=_auth(a))

    a_list = client.get("/api/boards", headers=_auth(a)).json()
    b_list = client.get("/api/boards", headers=_auth(b)).json()
    assert any(x["name"] == "A-board" for x in a_list)
    assert b_list == []


def test_cross_tenant_board_get_is_404(client):
    a = _token(client, "a2@example.com")
    b = _token(client, "b2@example.com")
    board = client.post("/api/boards", json={"name": "secret"}, headers=_auth(a)).json()
    r = client.get(f"/api/boards/{board['id']}", headers=_auth(b))
    assert r.status_code == 404


def test_unauthenticated_board_access_is_401(client):
    assert client.get("/api/boards").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_board_isolation.py -v`
Expected: FAIL — currently `/api/boards` requires no auth and ignores `account_id`.

- [ ] **Step 3: Rewrite `boards.py` to be account-scoped**

Replace `agent/flowboard/routes/boards.py` with:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import delete as sql_delete, select

from flowboard.db import get_session
from flowboard.db.models import (
    Account,
    Asset,
    Board,
    BoardFlowProject,
    ChatMessage,
    Edge,
    Node,
    PipelineRun,
    Plan,
    PlanRevision,
    Request,
)
from flowboard.db.scoping import owned_or_404
from flowboard.deps import get_current_account

router = APIRouter(prefix="/api/boards", tags=["boards"])


class BoardCreate(BaseModel):
    name: str


class BoardUpdate(BaseModel):
    name: str


@router.get("")
def list_boards(acct: Account = Depends(get_current_account)):
    with get_session() as s:
        return s.exec(select(Board).where(Board.account_id == acct.id)).all()


@router.post("")
def create_board(body: BoardCreate, acct: Account = Depends(get_current_account)):
    with get_session() as s:
        board = Board(name=body.name, account_id=acct.id)
        s.add(board)
        s.commit()
        s.refresh(board)
        return board


@router.get("/{board_id}")
def get_board(board_id: int, acct: Account = Depends(get_current_account)):
    with get_session() as s:
        board = owned_or_404(s, Board, board_id, acct.id)
        nodes = s.exec(select(Node).where(Node.board_id == board_id)).all()
        edges = s.exec(select(Edge).where(Edge.board_id == board_id)).all()
        return {"board": board, "nodes": nodes, "edges": edges}


@router.patch("/{board_id}")
def update_board(board_id: int, body: BoardUpdate, acct: Account = Depends(get_current_account)):
    with get_session() as s:
        board = owned_or_404(s, Board, board_id, acct.id)
        board.name = body.name
        s.add(board)
        s.commit()
        s.refresh(board)
        return board


@router.delete("/{board_id}")
def delete_board(board_id: int, acct: Account = Depends(get_current_account)):
    """Cascade-delete a board and everything that hangs off it. Scoped to the
    caller's account — a cross-tenant id returns 404 via owned_or_404."""
    with get_session() as s:
        board = owned_or_404(s, Board, board_id, acct.id)

        node_ids = [
            n.id for n in s.exec(select(Node).where(Node.board_id == board_id)).all()
        ]
        if node_ids:
            s.exec(sql_delete(Asset).where(Asset.node_id.in_(node_ids)))
            s.exec(sql_delete(Request).where(Request.node_id.in_(node_ids)))

        plan_ids = [
            p.id for p in s.exec(select(Plan).where(Plan.board_id == board_id)).all()
        ]
        if plan_ids:
            s.exec(sql_delete(PipelineRun).where(PipelineRun.plan_id.in_(plan_ids)))
            s.exec(sql_delete(PlanRevision).where(PlanRevision.plan_id.in_(plan_ids)))

        s.exec(sql_delete(Edge).where(Edge.board_id == board_id))
        s.exec(sql_delete(Node).where(Node.board_id == board_id))
        s.exec(sql_delete(Plan).where(Plan.board_id == board_id))
        s.exec(sql_delete(ChatMessage).where(ChatMessage.board_id == board_id))
        s.exec(sql_delete(BoardFlowProject).where(BoardFlowProject.board_id == board_id))
        s.delete(board)
        s.commit()
        return {"deleted": board_id}
```

- [ ] **Step 4: Add an auth fixture and update existing board tests**

At the top of `agent/tests/test_boards.py`, add this fixture (before `test_create_list_get_board`):

```python
import pytest


@pytest.fixture
def auth(client):
    client.post("/api/account/register",
                json={"email": "boards@example.com", "password": "pw123456"})
    tok = client.post("/api/account/login",
                      json={"email": "boards@example.com", "password": "pw123456"}
                      ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}
```

Then update every test in `test_boards.py`: add `auth` to the signature and pass `headers=auth` on each board request. Example for the first test:

```python
def test_create_list_get_board(client, auth):
    r = client.post("/api/boards", json={"name": "Scene 01"}, headers=auth)
    ...
    r = client.get("/api/boards", headers=auth)
    ...
    r = client.get(f"/api/boards/{board['id']}", headers=auth)
```

For `test_delete_board_cascades_children`, the board create/delete calls take `headers=auth`; the node/edge/request creates via `client.post` will require auth too once Task 18 retrofits those routers — until then, in THIS task only, leave that one test creating its children directly through `get_session` (it already seeds Asset/ChatMessage/Plan/etc. that way) and route the node/edge/request creation through `get_session` seeding instead of the HTTP API. Concretely, replace the three `client.post("/api/nodes"/"/api/edges"/"/api/requests", ...)` calls with direct `get_session()` inserts of `Node(board_id=bid, ...)`, `Edge(...)`, `Request(...)`. The 404/missing-row assertions afterward are unchanged.

For `test_get_missing_board_returns_404`, `test_patch_board_rename`, `test_patch_missing_board_returns_404`, `test_delete_missing_board_returns_404`: add `auth` and `headers=auth` the same way.

- [ ] **Step 5: Run the board tests**

Run: `cd agent && python -m pytest tests/test_boards.py tests/test_board_isolation.py -v`
Expected: PASS (all board tests + 3 isolation tests).

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/routes/boards.py agent/tests/test_boards.py agent/tests/test_board_isolation.py
git commit -m "feat: enforce tenant isolation on board routes"
```

---

## Task 18: Retrofit remaining routers with the same scoping pattern

**Files (each modified the same mechanical way):**
- `agent/flowboard/routes/nodes.py`
- `agent/flowboard/routes/edges.py`
- `agent/flowboard/routes/requests.py`
- `agent/flowboard/routes/chat.py`
- `agent/flowboard/routes/plans.py`
- `agent/flowboard/routes/projects.py`
- `agent/flowboard/routes/flow_projects.py`
- `agent/flowboard/routes/references.py`
- `agent/flowboard/routes/media.py`
- `agent/flowboard/routes/upload.py`
- `agent/flowboard/routes/vision.py`
- `agent/flowboard/routes/prompt.py`
- `agent/flowboard/routes/llm.py`
- `agent/flowboard/routes/activity.py`
- Test: `agent/tests/test_cross_router_isolation.py`

> The transformation is identical for every handler. Do one router per commit, running that router's existing test file after each.

**The mechanical pattern (apply to every handler in each file):**

1. Add imports:
```python
from fastapi import Depends
from flowboard.db.models import Account, Board
from flowboard.db.scoping import owned_or_404
from flowboard.deps import get_current_account
```
2. Add `acct: Account = Depends(get_current_account)` to every route handler signature.
3. When **creating** a row that has an `account_id` column (`Node`, `Request`, `Asset`), pass `account_id=acct.id`.
4. When **reading/mutating by `board_id`**, first resolve the board with `owned_or_404(s, Board, board_id, acct.id)` before touching children.
5. When **reading/mutating a child by its own id** (e.g. a node id), load it, then resolve its parent board via `owned_or_404(s, Board, row.board_id, acct.id)` to confirm ownership (404 otherwise).
6. Update that router's existing test file(s) to send the `auth` header (reuse the fixture from Task 17 Step 4 — copy it into each test module or move it into `conftest.py` as a shared fixture; if shared, place it in `conftest.py` without `autouse` so only tests that name `auth` get it).

- [ ] **Step 1: Promote the `auth` fixture to `conftest.py`**

Add to `agent/tests/conftest.py` (after the `client` fixture):

```python
@pytest.fixture
def auth(client):
    client.post("/api/account/register",
                json={"email": "fixture@example.com", "password": "pw123456"})
    tok = client.post("/api/account/login",
                      json={"email": "fixture@example.com", "password": "pw123456"}
                      ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}
```

Then remove the duplicated local `auth` fixture from `test_boards.py` (Task 17 Step 4) so there is a single definition. Run `cd agent && python -m pytest tests/test_boards.py -q` to confirm boards still pass with the shared fixture.

- [ ] **Step 2: Write the cross-router isolation test**

Create `agent/tests/test_cross_router_isolation.py`:

```python
def _token(client, email):
    client.post("/api/account/register", json={"email": email, "password": "pw123456"})
    return client.post("/api/account/login",
                       json={"email": email, "password": "pw123456"}).json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_nodes_are_scoped_to_account(client):
    a = _token(client, "na@example.com")
    b = _token(client, "nb@example.com")
    board = client.post("/api/boards", json={"name": "A"}, headers=_auth(a)).json()
    # Account A creates a node on its board.
    node = client.post("/api/nodes",
                       json={"board_id": board["id"], "type": "image"},
                       headers=_auth(a)).json()
    assert "id" in node
    # Account B cannot create a node on A's board.
    r = client.post("/api/nodes",
                    json={"board_id": board["id"], "type": "image"},
                    headers=_auth(b))
    assert r.status_code == 404


def test_unauthenticated_node_create_is_401(client):
    assert client.post("/api/nodes", json={"board_id": 1, "type": "image"}).status_code == 401
```

- [ ] **Step 3: Retrofit `nodes.py` first and verify**

Read `agent/flowboard/routes/nodes.py`, apply the mechanical pattern (add imports, add the `acct` dependency to each handler, stamp `account_id=acct.id` on node creation, guard every `board_id` with `owned_or_404(s, Board, board_id, acct.id)`). Update `agent/tests/test_nodes.py` to take the shared `auth` fixture and pass `headers=auth` on every request.

Run: `cd agent && python -m pytest tests/test_nodes.py tests/test_cross_router_isolation.py -v`
Expected: PASS.

Commit:
```bash
git add agent/flowboard/routes/nodes.py agent/tests/test_nodes.py agent/tests/test_cross_router_isolation.py agent/tests/conftest.py
git commit -m "feat: enforce tenant isolation on node routes"
```

- [ ] **Step 4: Retrofit the remaining routers one at a time**

For each remaining file (edges, requests, chat, plans, projects, flow_projects, references, media, upload, vision, prompt, llm, activity): apply the same mechanical pattern, update that router's existing test file to use the shared `auth` fixture + `headers=auth`, run that test file until green, and commit per router:

```bash
git add agent/flowboard/routes/<name>.py agent/tests/test_<name>*.py
git commit -m "feat: enforce tenant isolation on <name> routes"
```

- [ ] **Step 5: Run the full suite**

Run: `cd agent && python -m pytest -q`
Expected: all green.

---

## Task 19: Plan self-review & full verification

- [ ] **Step 1: Run the complete suite**

Run: `cd agent && python -m pytest -q`
Expected: all tests pass (original 333 + new auth/isolation tests).

- [ ] **Step 2: Lint**

Run: `cd agent && python -m ruff check flowboard`
Expected: no errors (fix any import-ordering / unused-import issues introduced).

- [ ] **Step 3: Smoke-check the account routes are mounted**

Run: `cd agent && python -c "from flowboard.main import app; print(sorted(r.path for r in app.routes if r.path.startswith('/api/account')))"`
Expected: lists `/api/account/login`, `/api/account/logout`, `/api/account/me`, `/api/account/refresh`, `/api/account/register`.

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: phase 1+2 cleanup"
```

---

## Spec coverage check (Phase 1+2 scope only)

| Spec requirement (§3, §4) | Task |
|---|---|
| `Account` table (email, password_hash, llm fields, google profile) | Task 3 |
| `RefreshToken` + `DeviceToken` tables | Task 4 |
| `account_id` on Board + denormalized Node/Request/Asset | Task 5 |
| Isolation helper / consistent scoping | Task 6, 17, 18 |
| SQLite→Postgres engine + Alembic | Task 2, 7 |
| Config from env (DATABASE_URL, JWT, ENCRYPTION_KEY, TTLs) | Task 2 |
| Register / Login / JWT access + refresh cookie | Task 12, 13 |
| Refresh + Logout (revoke refresh & device tokens) | Task 14, 15 |
| `get_current_account` dependency | Task 11 |
| Password hashing, token hashing, Fernet for llm key | Task 8, 9, 10 |
| Cross-tenant access → 404 | Task 17, 18 |

**Out of this plan (later phases):** Connection Registry & WS routing (Phase 3), extension auto-pair / device-token minting endpoint (Phase 3/4), per-user LLM key wiring into the LLM services + S3 media (Phase 5), email verify/reset/billing (out of scope entirely).
