# SaaS Hosting Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nâng cấp Flowboard từ local-only thành bản hosted SaaS nhỏ theo đúng lộ trình trong `docs/saas-hosted-upgrade.md`.

**Architecture:** Backend FastAPI giữ nguyên, thêm CORS allowlist, auth middleware (Bearer token), SQLite WAL, và WS token handshake. Infrastructure thêm docker-compose.prod.yml + Caddyfile + nginx fallback. Frontend thêm app token vào localStorage và tự đính vào mọi request.

**Tech Stack:** Python/FastAPI, SQLite/SQLModel, websockets, React/TypeScript/Zustand, Docker Compose, Caddy, Nginx

---

## File Map

| File | Action | Mô tả |
|---|---|---|
| `agent/flowboard/config.py` | Modify | Thêm PUBLIC_ORIGIN, CORS_ORIGINS, APP_TOKEN, EXTENSION_TOKEN |
| `agent/flowboard/main.py` | Modify | Fix CORS, thêm auth middleware, cập nhật WS guard |
| `agent/flowboard/db/session.py` | Modify | Bật WAL mode |
| `agent/Dockerfile` | Modify | Thêm `--workers 1` vào CMD |
| `agent/flowboard/services/ws_server.py` | Modify | Thêm token handshake |
| `agent/tests/test_ws_token.py` | Create | Tests cho WS token handshake |
| `agent/tests/test_app_auth.py` | Create | Tests cho auth middleware |
| `docker-compose.prod.yml` | Create | Production compose |
| `Caddyfile` | Create | Caddy reverse proxy (recommended) |
| `nginx/nginx.conf` | Create | Nginx reverse proxy (fallback) |
| `.env.example` | Create | Template biến môi trường hosted |
| `frontend/src/store/settings.ts` | Modify | Thêm appToken vào SettingsState |
| `frontend/src/api/client.ts` | Modify | Đính Authorization header từ store |
| `frontend/src/components/SettingsPanel.tsx` | Modify | Thêm section "Connection" nhập token |

---

## Task 1: Expand config.py với hosted vars

**Files:**
- Modify: `agent/flowboard/config.py`

- [ ] **Step 1: Đọc file hiện tại**

Run: `cat agent/flowboard/config.py`

- [ ] **Step 2: Thay thế toàn bộ nội dung config.py**

```python
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = Path(os.getenv("FLOWBOARD_STORAGE", ROOT / "storage"))
DB_PATH = Path(os.getenv("FLOWBOARD_DB", STORAGE_DIR / "flowboard.db"))

HTTP_PORT = int(os.getenv("FLOWBOARD_HTTP_PORT", "8101"))
WS_HOST = os.getenv("FLOWBOARD_WS_HOST", "127.0.0.1")
EXTENSION_WS_PORT = int(os.getenv("FLOWBOARD_EXT_WS_PORT", "9223"))

PLANNER_MODEL = os.getenv("FLOWBOARD_PLANNER_MODEL", "claude-sonnet-4-6")
# "cli" -> always use claude CLI; "mock" -> always mock; "api" -> use API key;
# "auto" -> CLI if available, otherwise mock. Set "api" for hosted production.
PLANNER_BACKEND = os.getenv("FLOWBOARD_PLANNER_BACKEND", "auto")

# -- Hosted deployment --------------------------------------------------------

# Public-facing origin, e.g. "https://flowboard.example.com".
PUBLIC_ORIGIN = os.getenv("FLOWBOARD_PUBLIC_ORIGIN", "")

# Comma-separated list of origins allowed in CORS.
# When empty (local dev), the middleware falls back to allow_origins=["*"]
# with allow_credentials=False.
# Example: "https://flowboard.example.com,https://staging.example.com"
_raw_cors = os.getenv("FLOWBOARD_CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = (
    [o.strip() for o in _raw_cors.split(",") if o.strip()] if _raw_cors else []
)

# App-level auth token (MVP guard for all write endpoints).
# When set, every API request must include: Authorization: Bearer <APP_TOKEN>
# Exemptions: GET /api/health, POST /api/ext/callback, /api/auth/* paths.
# Leave empty to disable auth (local/dev only).
APP_TOKEN = os.getenv("FLOWBOARD_APP_TOKEN", "")

# Extension WebSocket auth token.
# When set, the Chrome extension must send
#   {"type": "auth", "token": "<EXTENSION_TOKEN>"}
# as the first WS message after connecting.
# Required when WS is exposed to the network (non-loopback host).
EXTENSION_TOKEN = os.getenv("FLOWBOARD_EXTENSION_TOKEN", "")

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: Chạy test để đảm bảo không có regression**

Run: `cd agent && python -m pytest tests/ -x -q 2>&1 | tail -15`

Expected: tất cả test pass.

- [ ] **Step 4: Commit**

```bash
git add agent/flowboard/config.py
git commit -m "feat(config): add hosted deployment vars (CORS_ORIGINS, APP_TOKEN, EXTENSION_TOKEN, PUBLIC_ORIGIN)"
```

---

## Task 2: Fix CORS + thêm app auth middleware trong main.py

**Files:**
- Modify: `agent/flowboard/main.py`
- Create: `agent/tests/test_app_auth.py`

- [ ] **Step 1: Tạo test file trước**

Tạo `agent/tests/test_app_auth.py` với nội dung sau:

```python
"""Tests for the app-level Bearer token auth middleware."""
import pytest
from fastapi.testclient import TestClient


def _make_client(monkeypatch, token: str):
    monkeypatch.setenv("FLOWBOARD_APP_TOKEN", token)
    import importlib
    import flowboard.config as cfg
    importlib.reload(cfg)
    import flowboard.main as m
    importlib.reload(m)
    return TestClient(m.app, raise_server_exceptions=False)


def test_health_always_public(monkeypatch):
    client = _make_client(monkeypatch, "test-secret")
    assert client.get("/api/health").status_code == 200


def test_auth_me_always_public(monkeypatch):
    client = _make_client(monkeypatch, "test-secret")
    assert client.get("/api/auth/me").status_code == 200


def test_boards_blocked_without_header(monkeypatch):
    client = _make_client(monkeypatch, "test-secret")
    assert client.get("/api/boards").status_code == 401


def test_boards_pass_with_correct_token(monkeypatch):
    client = _make_client(monkeypatch, "test-secret")
    resp = client.get("/api/boards", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200


def test_boards_blocked_with_wrong_token(monkeypatch):
    client = _make_client(monkeypatch, "test-secret")
    resp = client.get("/api/boards", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_no_token_configured_all_pass(monkeypatch):
    client = _make_client(monkeypatch, "")
    assert client.get("/api/boards").status_code == 200
```

- [ ] **Step 2: Chạy test để thấy fail**

Run: `cd agent && python -m pytest tests/test_app_auth.py -v 2>&1 | head -20`

Expected: FAIL — middleware chưa tồn tại.

- [ ] **Step 3: Thay thế toàn bộ main.py**

Đọc file gốc trước (`cat agent/flowboard/main.py`), sau đó ghi nội dung mới:

```python
import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from flowboard.config import (
    APP_TOKEN, CORS_ORIGINS, EXTENSION_TOKEN, EXTENSION_WS_PORT, WS_HOST,
)
from flowboard.db import get_session, init_db
from flowboard.db.models import Request
from flowboard.routes import (
    activity, auth, boards, chat, edges, llm, media,
    nodes, plans, projects, prompt, upload, vision,
)
from flowboard.routes import requests as requests_route
from flowboard.services.flow_client import flow_client
from flowboard.services.ws_server import run_ws_server
from flowboard.worker.processor import get_worker

# WS guard: unauthenticated WS must not bind to non-loopback.
# When EXTENSION_TOKEN is set, token handshake provides auth so any host is OK.
_loopback = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
if WS_HOST not in _loopback and not EXTENSION_TOKEN:
    raise RuntimeError(
        f"FLOWBOARD_WS_HOST={WS_HOST!r}: exposing WebSocket to the network "
        "requires FLOWBOARD_EXTENSION_TOKEN to be set. "
        "Set a strong random token or restrict FLOWBOARD_WS_HOST to loopback."
    )

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if WS_HOST not in _loopback:
    logger.warning(
        "WebSocket will bind to %s:%d with token auth active — "
        "ensure the port is firewall-protected or behind wss:// proxy.",
        WS_HOST, EXTENSION_WS_PORT,
    )


def _recover_orphan_running_requests() -> int:
    """Mark pre-existing 'running' requests as failed on restart."""
    from datetime import datetime, timezone
    from sqlmodel import select as _select

    touched = 0
    with get_session() as s:
        rows = s.exec(_select(Request).where(Request.status == "running")).all()
        for r in rows:
            r.status = "failed"
            r.error = "agent_restart_lost"
            r.finished_at = datetime.now(timezone.utc)
            s.add(r)
            touched += 1
        if touched:
            s.commit()
    return touched


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recovered = _recover_orphan_running_requests()
    if recovered:
        logger.info("recovered %d orphan running request(s) -> failed", recovered)
    worker = get_worker()
    ws_task = asyncio.create_task(run_ws_server(), name="ext-ws-server")
    worker_task = asyncio.create_task(worker.start(), name="request-worker")
    logger.info("flowboard agent started (ws:%d + worker)", EXTENSION_WS_PORT)
    try:
        yield
    finally:
        worker.request_shutdown()
        try:
            await asyncio.wait_for(worker.drain(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("worker drain timed out")
        for t in (ws_task, worker_task):
            t.cancel()
        await asyncio.gather(ws_task, worker_task, return_exceptions=True)
        logger.info("flowboard agent stopped")


app = FastAPI(title="Flowboard Agent", version="0.0.2", lifespan=lifespan)

# CORS: use specific allowlist when CORS_ORIGINS is configured.
# allow_credentials=True is only valid when origins are not a wildcard.
# MVP uses Bearer token in headers so credentials/cookies are not needed.
_cors_allow_origins = CORS_ORIGINS if CORS_ORIGINS else ["*"]
_cors_allow_credentials = bool(CORS_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# App-level Bearer token auth middleware.
# When APP_TOKEN is set, every request outside exempt paths must present:
#   Authorization: Bearer <APP_TOKEN>
_AUTH_EXEMPT = frozenset({"/api/health", "/api/ext/callback"})


@app.middleware("http")
async def _app_auth_middleware(request: FastAPIRequest, call_next):
    if not APP_TOKEN:
        return await call_next(request)
    path = request.url.path
    if path in _AUTH_EXEMPT or path.startswith("/api/auth/"):
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    token = auth_header[len("Bearer "):]
    if not hmac.compare_digest(token.encode(), APP_TOKEN.encode()):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


app.include_router(boards.router)
app.include_router(nodes.router)
app.include_router(edges.router)
app.include_router(chat.router)
app.include_router(projects.router)
app.include_router(requests_route.router)
app.include_router(media.bytes_router)
app.include_router(media.api_router)
app.include_router(upload.router)
app.include_router(plans.router)
app.include_router(vision.router)
app.include_router(prompt.router)
app.include_router(auth.router)
app.include_router(llm.router)
app.include_router(activity.router)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "extension_connected": flow_client.connected,
        "ws_stats": flow_client.ws_stats,
    }


@app.post("/api/ext/callback")
async def ext_callback(
    body: FastAPIRequest,
    x_callback_secret: str | None = Header(default=None, alias="X-Callback-Secret"),
) -> dict:
    """HTTP callback for the extension to deliver API responses."""
    if not x_callback_secret or not hmac.compare_digest(
        x_callback_secret, flow_client.callback_secret
    ):
        raise HTTPException(status_code=401, detail="invalid callback secret")

    try:
        payload = await body.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")

    if not isinstance(payload, dict) or "id" not in payload:
        raise HTTPException(status_code=400, detail="missing id")

    matched = flow_client.resolve_callback(payload)
    return {"ok": matched}
```

- [ ] **Step 4: Chạy test_app_auth.py**

Run: `cd agent && python -m pytest tests/test_app_auth.py -v`

Expected: 6/6 PASS.

- [ ] **Step 5: Chạy full test suite**

Run: `cd agent && python -m pytest tests/ -x -q 2>&1 | tail -15`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/main.py agent/tests/test_app_auth.py
git commit -m "feat(auth): Bearer token middleware + fix CORS allow_credentials with wildcard origins bug"
```

---

## Task 3: SQLite WAL mode + Dockerfile --workers 1

**Files:**
- Modify: `agent/flowboard/db/session.py`
- Modify: `agent/Dockerfile`

- [ ] **Step 1: Đọc session.py**

Run: `cat agent/flowboard/db/session.py`

- [ ] **Step 2: Thay hàm _enable_sqlite_fk sang _set_sqlite_pragmas**

Tìm đoạn:

```python
@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
```

Thay bằng:

```python
@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()
```

- [ ] **Step 3: Verify WAL mode**

Run:
```bash
cd agent && python -c "
from flowboard.db.session import engine
from sqlalchemy import text
with engine.connect() as conn:
    print('journal_mode:', conn.execute(text('PRAGMA journal_mode')).fetchone()[0])
"
```

Expected: `journal_mode: wal`

- [ ] **Step 4: Sửa Dockerfile CMD**

Đọc `agent/Dockerfile`. Tìm dòng CMD cuối:

```dockerfile
CMD ["sh", "-c", "uvicorn flowboard.main:app --host 0.0.0.0 --port ${FLOWBOARD_HTTP_PORT:-8101}"]
```

Thay bằng:

```dockerfile
CMD ["sh", "-c", "uvicorn flowboard.main:app --host 0.0.0.0 --port ${FLOWBOARD_HTTP_PORT:-8101} --workers 1"]
```

- [ ] **Step 5: Chạy tests**

Run: `cd agent && python -m pytest tests/ -x -q 2>&1 | tail -10`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/db/session.py agent/Dockerfile
git commit -m "fix(db): enable SQLite WAL mode; pin uvicorn to --workers 1 to prevent concurrent writes"
```

---

## Task 4: WS token handshake trong ws_server.py

**Files:**
- Modify: `agent/flowboard/services/ws_server.py`
- Create: `agent/tests/test_ws_token.py`

- [ ] **Step 1: Tạo test file**

Tạo `agent/tests/test_ws_token.py`:

```python
"""Tests for WebSocket extension token handshake."""
import asyncio
import json
import pytest
import websockets as _ws


async def _start_ws_server(host, port):
    from flowboard.services.ws_server import _handler
    server = await _ws.serve(_handler, host, port)
    return server


@pytest.mark.asyncio
async def test_ws_no_token_sends_callback_secret_immediately(monkeypatch):
    """Without EXTENSION_TOKEN, WS accepts connection and sends callback_secret."""
    monkeypatch.setenv("FLOWBOARD_EXTENSION_TOKEN", "")
    import importlib, flowboard.config as cfg, flowboard.services.ws_server as wsmod
    importlib.reload(cfg)
    importlib.reload(wsmod)

    server = await _ws.serve(wsmod._handler, "127.0.0.1", 19101)
    try:
        async with _ws.connect("ws://127.0.0.1:19101") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            msg = json.loads(raw)
            assert msg["type"] == "callback_secret"
            assert len(msg["secret"]) > 0
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ws_with_token_rejects_wrong_first_message(monkeypatch):
    """With EXTENSION_TOKEN set, wrong first message closes connection."""
    monkeypatch.setenv("FLOWBOARD_EXTENSION_TOKEN", "test-ext-token")
    import importlib, flowboard.config as cfg, flowboard.services.ws_server as wsmod
    importlib.reload(cfg)
    importlib.reload(wsmod)

    server = await _ws.serve(wsmod._handler, "127.0.0.1", 19102)
    try:
        async with _ws.connect("ws://127.0.0.1:19102") as ws:
            await ws.send(json.dumps({"type": "ping"}))
            with pytest.raises((_ws.ConnectionClosedError, _ws.ConnectionClosedOK)):
                await asyncio.wait_for(ws.recv(), timeout=2.0)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ws_with_token_accepts_correct_token(monkeypatch):
    """With EXTENSION_TOKEN set, correct auth token proceeds to callback_secret."""
    monkeypatch.setenv("FLOWBOARD_EXTENSION_TOKEN", "test-ext-token")
    import importlib, flowboard.config as cfg, flowboard.services.ws_server as wsmod
    importlib.reload(cfg)
    importlib.reload(wsmod)

    server = await _ws.serve(wsmod._handler, "127.0.0.1", 19103)
    try:
        async with _ws.connect("ws://127.0.0.1:19103") as ws:
            await ws.send(json.dumps({"type": "auth", "token": "test-ext-token"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            msg = json.loads(raw)
            assert msg["type"] == "callback_secret"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ws_with_token_rejects_wrong_token(monkeypatch):
    """Wrong token value closes connection with 4001."""
    monkeypatch.setenv("FLOWBOARD_EXTENSION_TOKEN", "test-ext-token")
    import importlib, flowboard.config as cfg, flowboard.services.ws_server as wsmod
    importlib.reload(cfg)
    importlib.reload(wsmod)

    server = await _ws.serve(wsmod._handler, "127.0.0.1", 19104)
    try:
        async with _ws.connect("ws://127.0.0.1:19104") as ws:
            await ws.send(json.dumps({"type": "auth", "token": "wrong-token"}))
            with pytest.raises((_ws.ConnectionClosedError, _ws.ConnectionClosedOK)):
                await asyncio.wait_for(ws.recv(), timeout=2.0)
    finally:
        server.close()
        await server.wait_closed()
```

- [ ] **Step 2: Chạy test để thấy fail**

Run: `cd agent && python -m pytest tests/test_ws_token.py -v 2>&1 | head -20`

Expected: fail — handshake chưa implement.

- [ ] **Step 3: Thay thế toàn bộ ws_server.py**

```python
"""Standalone WebSocket server on :9223 for the Chrome extension bridge.

Kept separate from the FastAPI :8101 app to match flowkit's pattern — the
extension's background.js connects to ws://127.0.0.1:9223 only.

When FLOWBOARD_EXTENSION_TOKEN is set, the extension must send:
    {"type": "auth", "token": "<EXTENSION_TOKEN>"}
as its first message. The server closes the connection with code 4001 if
the token is missing or wrong. This allows the WS port to be safely exposed
over the network (e.g. wss:// behind a reverse proxy).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging

import websockets

from flowboard.config import EXTENSION_TOKEN, EXTENSION_WS_PORT, WS_HOST
from flowboard.services.flow_client import flow_client

logger = logging.getLogger(__name__)

_AUTH_TIMEOUT_S = 10.0


async def _handler(websocket) -> None:
    remote = getattr(websocket, "remote_address", "?")

    # Token handshake — enforced only when EXTENSION_TOKEN is configured.
    if EXTENSION_TOKEN:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=_AUTH_TIMEOUT_S)
            msg = json.loads(raw)
        except asyncio.TimeoutError:
            logger.warning("WS auth timeout from %s", remote)
            await websocket.close(code=4001, reason="auth timeout")
            return
        except (json.JSONDecodeError, websockets.ConnectionClosed):
            await websocket.close(code=4001, reason="bad auth message")
            return

        incoming_token = str(msg.get("token", ""))
        if msg.get("type") != "auth" or not hmac.compare_digest(
            incoming_token.encode(), EXTENSION_TOKEN.encode()
        ):
            logger.warning("WS auth rejected from %s", remote)
            await websocket.close(code=4001, reason="unauthorized")
            return

        logger.info("extension authenticated from %s", remote)

    flow_client.set_extension(websocket)
    logger.info("extension connected from %s", remote)

    try:
        await websocket.send(
            json.dumps({"type": "callback_secret", "secret": flow_client.callback_secret})
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to send callback_secret")

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("invalid JSON from extension")
                continue
            try:
                await flow_client.handle_message(data)
            except Exception:  # noqa: BLE001
                logger.exception("error handling extension message")
    except websockets.ConnectionClosed:
        pass
    finally:
        flow_client.clear_extension()
        logger.info("extension disconnected from %s", remote)


async def run_ws_server() -> None:
    async with websockets.serve(_handler, WS_HOST, EXTENSION_WS_PORT):
        logger.info(
            "WebSocket server listening on ws://%s:%d", WS_HOST, EXTENSION_WS_PORT
        )
        await asyncio.Future()  # run forever
```

- [ ] **Step 4: Chạy test_ws_token.py**

Run: `cd agent && python -m pytest tests/test_ws_token.py -v`

Expected: 4/4 PASS.

- [ ] **Step 5: Full suite**

Run: `cd agent && python -m pytest tests/ -x -q 2>&1 | tail -10`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/services/ws_server.py agent/tests/test_ws_token.py
git commit -m "feat(ws): add EXTENSION_TOKEN handshake — WS can now be safely exposed to network"
```

---

## Task 5: Production Docker Compose + Caddy + Nginx

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `Caddyfile`
- Create: `nginx/nginx.conf`

- [ ] **Step 1: Tạo docker-compose.prod.yml**

```yaml
# docker-compose.prod.yml
# Dung cho hosted deployment. Sao chep .env.example thanh .env.prod roi chay:
#   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

services:
  agent:
    build:
      context: ./agent
    env_file: .env.prod
    environment:
      FLOWBOARD_STORAGE: /app/storage
      FLOWBOARD_WS_HOST: "0.0.0.0"
    volumes:
      - flowboard_storage:/app/storage
      - flowboard_secrets:/app/secrets
    expose:
      - "8101"
    ports:
      - "127.0.0.1:9223:9223"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8101/api/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

  frontend:
    build:
      context: ./frontend
    expose:
      - "80"
    restart: unless-stopped
    depends_on:
      - agent

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    environment:
      FLOWBOARD_PUBLIC_ORIGIN: ${FLOWBOARD_PUBLIC_ORIGIN}
    depends_on:
      - agent
      - frontend
    restart: unless-stopped

volumes:
  flowboard_storage:
  flowboard_secrets:
  caddy_data:
  caddy_config:
```

- [ ] **Step 2: Tạo Caddyfile**

```caddyfile
# Caddyfile — Caddy reverse proxy cho Flowboard hosted
# Caddy tu dong cap va gia han TLS certificate qua Let's Encrypt.
# Dat FLOWBOARD_PUBLIC_ORIGIN=https://flowboard.example.com trong .env.prod

{$FLOWBOARD_PUBLIC_ORIGIN} {
    handle /api/* {
        reverse_proxy agent:8101 {
            header_up X-Forwarded-Proto {scheme}
            header_up X-Real-IP {remote_host}
        }
    }

    handle /media/* {
        reverse_proxy agent:8101 {
            header_up X-Forwarded-Proto {scheme}
            header_up X-Real-IP {remote_host}
        }
    }

    handle {
        reverse_proxy frontend:80
    }

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    request_body {
        max_size 100MB
    }
}
```

- [ ] **Step 3: Tạo nginx/nginx.conf**

```nginx
# nginx/nginx.conf -- Nginx reverse proxy cho Flowboard hosted
# Dung khi khong dung Caddy. TLS phai duoc xu ly boi Certbot hoac ALB.

upstream flowboard_agent {
    server agent:8101;
    keepalive 32;
}

upstream flowboard_frontend {
    server frontend:80;
    keepalive 16;
}

server {
    listen 80;
    server_name _;

    client_max_body_size 100M;

    location /api/ {
        proxy_pass http://flowboard_agent;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
    }

    location /media/ {
        proxy_pass http://flowboard_agent;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        add_header Cache-Control "public, max-age=3600";
    }

    location / {
        proxy_pass http://flowboard_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **Step 4: Verify docker-compose.prod.yml syntax**

Run: `docker compose -f docker-compose.prod.yml config 2>&1 | head -20`

Expected: no parse errors (warning về biến env chưa set là OK).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.prod.yml Caddyfile nginx/nginx.conf
git commit -m "feat(infra): add production docker-compose with Caddy reverse proxy and nginx fallback"
```

---

## Task 6: Tạo .env.example

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Tạo .env.example ở root của project**

```bash
# .env.example -- Template bien moi truong cho Flowboard hosted deployment
# Sao chep thanh .env.prod va dien gia tri thuc truoc khi deploy:
#   cp .env.example .env.prod

# -- URL cong khai -----------------------------------------------------------
FLOWBOARD_PUBLIC_ORIGIN=https://flowboard.example.com

# Danh sach origin duoc phep trong CORS, cach nhau bang dau phay.
# De trong = wildcard (chi local/dev).
FLOWBOARD_CORS_ORIGINS=https://flowboard.example.com

# -- Auth --------------------------------------------------------------------
# Token bao ve toan bo API (tru /api/health va /api/auth/*).
# Frontend doc tu localStorage va dinh vao header: Authorization: Bearer <value>
# De trong = tat auth (chi local/dev).
# Tao token: openssl rand -base64 32
FLOWBOARD_APP_TOKEN=

# Token xac thuc ket noi WebSocket tu Chrome extension.
# Extension phai gui {"type":"auth","token":"<value>"} la message dau tien.
# Bat buoc khi WS port duoc expose ra network (khong phai loopback).
# Tao token: openssl rand -base64 32
FLOWBOARD_EXTENSION_TOKEN=

# -- Storage -----------------------------------------------------------------
FLOWBOARD_STORAGE=/app/storage
FLOWBOARD_DB=/app/storage/flowboard.db
FLOWBOARD_SECRETS_PATH=/app/secrets/secrets.json

# -- LLM ---------------------------------------------------------------------
# Dat "api" cho hosted de dung API key, tranh loi CLI OAuth.
# "cli" = codex CLI (local/dev only). "auto" = CLI neu co, nguoc lai mock.
FLOWBOARD_PLANNER_BACKEND=api
FLOWBOARD_PLANNER_MODEL=claude-sonnet-4-6

# -- Network (defaults on cho Docker) ----------------------------------------
FLOWBOARD_HTTP_PORT=8101
FLOWBOARD_EXT_WS_PORT=9223
FLOWBOARD_WS_HOST=0.0.0.0
```

- [ ] **Step 2: Verify không có secret thực trong file**

Run: `grep -E "FLOWBOARD_(APP_TOKEN|EXTENSION_TOKEN)=.+" .env.example`

Expected: output rỗng — các token fields đều trống.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "feat(config): add .env.example template for hosted deployment"
```

---

## Task 7: Frontend — app token trong settings store + API client

**Files:**
- Modify: `frontend/src/store/settings.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Đọc cả hai file**

Run: `cat frontend/src/store/settings.ts && echo "---" && cat frontend/src/api/client.ts | head -30`

- [ ] **Step 2: Thay thế toàn bộ settings.ts**

```typescript
import { create } from "zustand";

/**
 * Per-user model preferences + connection config.
 * Survives page reload via localStorage.
 */
export type ImageModelKey = "NANO_BANANA_PRO" | "NANO_BANANA_2";
export type VideoQuality =
  | "fast"
  | "lite"
  | "quality"
  | "lite_relaxed"
  | "fast_relaxed";

interface SettingsState {
  imageModel: ImageModelKey;
  videoQuality: VideoQuality;
  /** App-level Bearer token for hosted deployments. Empty string = no auth. */
  appToken: string;
  setImageModel(model: ImageModelKey): void;
  setVideoQuality(q: VideoQuality): void;
  setAppToken(token: string): void;
}

const STORAGE_KEY = "flowboard.settings.v1";

interface PersistShape {
  imageModel?: ImageModelKey;
  videoQuality?: VideoQuality;
  appToken?: string;
}

function loadPersisted(): PersistShape {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

function persist(state: PersistShape): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage disabled / quota exceeded — non-fatal.
  }
}

const persisted = loadPersisted();

export const useSettingsStore = create<SettingsState>((set, get) => ({
  imageModel: persisted.imageModel ?? "NANO_BANANA_PRO",
  videoQuality: persisted.videoQuality ?? "fast",
  appToken: persisted.appToken ?? "",
  setImageModel(model) {
    set({ imageModel: model });
    persist({ imageModel: model, videoQuality: get().videoQuality, appToken: get().appToken });
  },
  setVideoQuality(q) {
    set({ videoQuality: q });
    persist({ imageModel: get().imageModel, videoQuality: q, appToken: get().appToken });
  },
  setAppToken(token) {
    set({ appToken: token });
    persist({ imageModel: get().imageModel, videoQuality: get().videoQuality, appToken: token });
  },
}));

/**
 * Read the app token directly from localStorage without React context.
 * Used by api/client.ts outside the React component tree.
 */
export function getStoredAppToken(): string {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return "";
    const parsed = JSON.parse(raw);
    return typeof parsed?.appToken === "string" ? parsed.appToken : "";
  } catch {
    return "";
  }
}
```

- [ ] **Step 3: Sửa api/client.ts — thêm helper và patch mọi fetch call**

Đọc toàn bộ `frontend/src/api/client.ts`.

**3a. Thêm import và helper sau dòng đầu tiên (sau closing của hàm `api`):**

Thêm vào **đầu file**, trước hàm `api`:

```typescript
import { getStoredAppToken } from "../store/settings";

function getAuthHeaders(): Record<string, string> {
  const token = getStoredAppToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
```

**3b. Sửa hàm `api()` — thêm `...getAuthHeaders()` vào headers:**

```typescript
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<T>;
}
```

**3c. Sửa `uploadImage` — thêm getAuthHeaders() vào fetch:**

```typescript
export async function uploadImage(
  file: File,
  projectId: string,
  nodeId?: number,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("project_id", projectId);
  if (nodeId !== undefined) form.append("node_id", String(nodeId));
  form.append("file", file);

  const res = await fetch("/api/upload", {
    method: "POST",
    headers: getAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res));
  }
  return res.json() as Promise<UploadResponse>;
}
```

**3d. Sửa các hàm dùng raw fetch trực tiếp** — thêm `...getAuthHeaders()` vào headers object của từng hàm:
- `autoPromptBatch`: thêm `...getAuthHeaders()` vào `headers: { "Content-Type": "application/json", ...getAuthHeaders() }`
- `autoPrompt`: tương tự
- `describeMedia`: tương tự
- `uploadImageFromUrl`: tương tự
- `getLlmProviders`: `headers: { ...getAuthHeaders() }`
- `getLlmConfig`: `headers: { ...getAuthHeaders() }`
- `setLlmConfig`: `headers: { "Content-Type": "application/json", ...getAuthHeaders() }`
- `setLlmApiKey`: `headers: { "Content-Type": "application/json", ...getAuthHeaders() }`
- `testLlmProvider`: `headers: { ...getAuthHeaders() }`
- `getActivityList`: `headers: { ...getAuthHeaders() }` vào fetch options
- `getActivityDetail`: tương tự
- `cancelActivity`: tương tự

- [ ] **Step 4: Build frontend**

Run: `cd frontend && npm run build 2>&1 | tail -20`

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/settings.ts frontend/src/api/client.ts
git commit -m "feat(frontend): add appToken to settings store; attach Authorization header to all API calls"
```

---

## Task 8: Frontend — Connection section trong SettingsPanel

**Files:**
- Modify: `frontend/src/components/SettingsPanel.tsx`

- [ ] **Step 1: Đọc SettingsPanel.tsx**

Run: `cat frontend/src/components/SettingsPanel.tsx`

- [ ] **Step 2: Thêm import useSettingsStore nếu chưa có**

Tìm các import hiện có, đảm bảo có:

```typescript
import { useSettingsStore } from "../store/settings";
```

- [ ] **Step 3: Thêm hook vào component body**

Trong function body của SettingsPanel component, tìm nơi các existing hooks được gọi, thêm:

```typescript
const { appToken, setAppToken } = useSettingsStore();
```

- [ ] **Step 4: Thêm Connection section vào JSX**

Tìm phần cuối của JSX (trước closing tag của component), thêm section sau tất cả các section hiện có:

```tsx
{/* Connection — hosted deployment app token */}
<section className="mt-6 border-t border-white/10 pt-6">
  <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-white/40">
    Connection
  </h3>
  <div className="space-y-2">
    <label className="block text-xs text-white/60">
      App token
      <span className="ml-1 text-white/30">
        (required when hosted with auth enabled)
      </span>
    </label>
    <input
      type="password"
      placeholder="Leave empty for local dev"
      value={appToken}
      onChange={(e) => setAppToken(e.target.value)}
      className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 font-mono text-sm text-white/90 placeholder:text-white/20 focus:border-white/30 focus:outline-none"
    />
    {appToken && (
      <p className="text-xs text-emerald-400/70">
        Token set — all API requests will include Authorization header.
      </p>
    )}
  </div>
</section>
```

- [ ] **Step 5: Build frontend**

Run: `cd frontend && npm run build 2>&1 | tail -20`

Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SettingsPanel.tsx
git commit -m "feat(frontend): add Connection section to SettingsPanel for hosted app token input"
```

---

## Self-Review

### Spec Coverage Check

| Requirement (saas-hosted-upgrade.md) | Task |
|---|---|
| Fix CORS wildcard + allow_credentials bug | Task 2 |
| Thêm CORS_ORIGINS, APP_TOKEN, EXTENSION_TOKEN, PUBLIC_ORIGIN | Task 1 |
| App auth middleware cho API endpoints | Task 2 |
| WS guard: allow non-loopback khi EXTENSION_TOKEN set | Task 2 |
| WS token handshake (Phase 2) | Task 4 |
| SQLite WAL mode | Task 3 |
| uvicorn --workers 1 | Task 3 |
| docker-compose.prod.yml | Task 5 |
| Caddy reverse proxy | Task 5 |
| Nginx reverse proxy (fallback) | Task 5 |
| .env.example | Task 6 |
| FLOWBOARD_PLANNER_BACKEND=api documented | Task 6 |
| Frontend auth token gửi lên API | Task 7 |
| Extension config UI (token input) | Task 8 |

### Placeholder Scan

Không có TBD, TODO, implement later trong plan.

### Type Consistency

- `getStoredAppToken()` định nghĩa trong Task 7 settings.ts, import trong Task 7 client.ts — consistent.
- `APP_TOKEN` từ config.py Task 1, dùng trong main.py Task 2 — consistent.
- `EXTENSION_TOKEN` từ config.py Task 1, dùng trong ws_server.py Task 4 — consistent.
- `appToken` / `setAppToken` định nghĩa trong Task 7 settings.ts, dùng trong Task 8 SettingsPanel — consistent.
