# Phase 3+4: Connection Registry, WS Auth & Extension Pairing — Design Spec

**Date:** 2026-06-04
**Status:** Approved, pending implementation plan
**Parent spec:** `2026-06-04-multi-tenant-server-extension-design.md`
**Scope:** Phase 3 (server-side registry + authenticated WS + pairing endpoint) + Phase 4 (extension client update). LLM per-user key, S3 media, isolation hardening: ngoài phạm vi (Phase 5+6).

---

## 1. Bối cảnh

Phases 1+2 đã xong: Account model, JWT auth, refresh tokens, `get_current_account` dependency, tenant-scoping helper, Alembic migrations.

**Vấn đề còn lại:** `flow_client` vẫn là singleton toàn cục — mọi board dùng chung một extension connection. Ba nơi cần refactor:

- `services/ws_server.py` — WS standalone `:9223` localhost, không auth
- `worker/processor.py` — gọi `flow_client.api_request(...)` trực tiếp
- `routes/auth.py` — đọc `flow_client.user_info` / `.paygate_tier`

Extension vẫn kết nối `ws://127.0.0.1:9223`, dùng `X-Callback-Secret` HMAC per-boot.

---

## 2. Kiến trúc tổng thể sau Phase 3+4

```
Extension (Chrome SW)                    Server (FastAPI :8101)
─────────────────────                    ──────────────────────
pairWithServer()                         POST /api/extension/pair
  → chrome.cookies.get fb_refresh   ──►    validate refresh cookie
  ← { device_token }                ◄──    create DeviceToken, return raw token

connectToServer(token)                   GET /ext  (WebSocket)
  ws = new WebSocket(                ──►    hash token → DeviceToken → account_id
    wss://server/ext?token=…)              registry.register(account_id, ws)
                                           message loop
                                           registry.unregister on close

handleApiRequest(msg)                    worker/processor.py
  → fetch Google Flow                      registry.get(account_id).api_request()
  → POST /api/ext/callback           ──►  routes/ext_callback.py
      X-Device-Token: <raw>                hash → account_id → resolve future
```

---

## 3. Server-side (Phase 3)

### 3.1 `services/registry.py` (mới)

```python
class ConnectionRegistry:
    _conns: dict[int, FlowClient]   # account_id → per-account FlowClient

    def register(account_id: int, websocket) -> FlowClient
    # Nếu đã có connection cũ → đóng với close code 4408 ("replaced")
    # Tạo FlowClient mới (hoặc reuse nếu đã có instance), gán ws mới

    def unregister(account_id: int, websocket)
    # Chỉ gỡ nếu websocket khớp với connection hiện tại (tránh race)

    def get(account_id: int) -> FlowClient | None

    def is_online(account_id: int) -> bool

registry = ConnectionRegistry()   # singleton registry (không phải singleton FlowClient)
```

Sống trong process (Hướng A). Server restart → registry rỗng, extension tự reconnect.

### 3.2 `services/flow_client.py` — bỏ singleton

Xóa dòng `flow_client = FlowClient()` ở cuối file. Logic proxy / `handle_message` / `api_request` / `fetch_paygate_tier` **giữ nguyên toàn bộ** — chỉ bỏ tính toàn cục. Mỗi instance giữ: ws hiện tại, paygate tier, flow token, pending requests của đúng account đó. `callback_secret` per-boot **xóa** — thay bằng device token auth.

### 3.3 `routes/ext_ws.py` (mới) — `GET /ext` WebSocket

```
1. Extension nối wss://server/ext?token=<device_token>
2. Server hash token → tra DeviceToken DB → account_id
   Token sai / revoked / hết hạn → close 4401; KHÔNG đăng ký
3. fc = registry.register(account_id, websocket)
   Nếu đã có connection cũ → đóng cái cũ 4408, giữ cái mới (last-wins)
4. Cập nhật DeviceToken.last_seen_at
5. Vòng lặp nhận message → fc.handle_message(data)  # per-account instance
6. Disconnect → registry.unregister(account_id, websocket)
```

**Heartbeat:** ping mỗi 30s; nếu không nhận pong sau timeout → unregister, đánh dấu offline.

Sử dụng `fastapi.WebSocket` (native) thay vì `websockets` library riêng — giữ mọi thứ trong một process.

### 3.4 `routes/extension.py` (mới) — `POST /api/extension/pair`

Auth bằng **refresh cookie** (không phải Bearer JWT) vì extension đính cookie tự động theo host:

```
1. Đọc cookie fb_refresh từ request
2. Validate: hash → tra RefreshToken DB → account_id (tái sử dụng logic refresh)
   Sai / hết hạn / revoked → 401
3. Tạo DeviceToken: raw = secrets.token_urlsafe(32), lưu hash(raw)
4. Trả { device_token: raw }  — chỉ trả một lần
```

### 3.5 Worker & Callback update

**`worker/processor.py`:**
```python
# trước
flow_client.api_request(...)

# sau
conn = registry.get(job.account_id)
if conn is None:
    return {}, "extension_offline"
conn.api_request(...)
```

**`routes/ext_callback.py`:**
- Đổi auth: `X-Callback-Secret` → `X-Device-Token`
- Hash token → tra DeviceToken → `account_id` → `registry.get(account_id).resolve_callback(id, result)`

**`routes/auth.py`** (Google profile endpoint `/api/auth/me`, `/api/auth/scan`):
- `flow_client.user_info` → `registry.get(current_account.id)?.user_info`
- `flow_client.connected` → `registry.is_online(current_account.id)`
- Route có auth (JWT), dùng `get_current_account` dependency bình thường.

### 3.6 Xóa

| File / symbol | Lý do |
|---|---|
| `services/ws_server.py` | Thay bằng `/ext` WebSocket trên FastAPI |
| `flow_client = FlowClient()` (cuối `flow_client.py`) | Bỏ singleton |
| `config.py`: `WS_HOST`, `EXTENSION_WS_PORT` | Không còn WS `:9223` |
| `main.py`: `asyncio.ensure_future(run_ws_server())` | WS tích hợp vào FastAPI rồi |
| `callback_secret` trong `FlowClient` | Thay bằng device token auth |

---

## 4. Extension client (Phase 4)

### 4.1 `manifest.json`

Thêm `"cookies"` vào `permissions`. Host permissions cho app domain đã có sẵn (`http://127.0.0.1:8101/*`, `http://localhost:8101/*`); khi deploy prod thêm `https://app.flowboard.ai/*`.

### 4.2 `background.js` — thay đổi

**Constants:**
```js
const APP_ORIGIN   = 'http://localhost:8101';   // configurable khi build
const PAIR_URL     = APP_ORIGIN + '/api/extension/pair';
const CALLBACK_URL = APP_ORIGIN + '/api/ext/callback';
// AGENT_WS_URL → xóa
```

**`init()`:**
```
Đọc chrome.storage.local { deviceToken }
→ có token → connectToServer(token)
→ không có → pairWithServer()
            → thành công → lưu token → connectToServer(token)
            → thất bại (chưa login) → setState('unpaired'), schedule retry 30s
```

**`pairWithServer()`:**
```js
const cookie = await chrome.cookies.get({ url: APP_ORIGIN, name: 'fb_refresh' });
if (!cookie) return null;   // chưa login

const resp = await fetch(PAIR_URL, { method: 'POST', credentials: 'include' });
if (!resp.ok) return null;

const { device_token } = await resp.json();
await chrome.storage.local.set({ deviceToken: device_token });
return device_token;
```

**`connectToServer(token)`:**
```js
const wsUrl = APP_ORIGIN.replace('http', 'ws') + '/ext?token=' + token;
ws = new WebSocket(wsUrl);
// onopen, onmessage, keepAlive giữ nguyên
```

**Xử lý close codes:**

| Code | Hành động |
|---|---|
| `4401` Unauthorized | Xóa `deviceToken` khỏi storage; setState `'unpaired'`; hiện "Đăng nhập lại trên web"; không auto-reconnect ngay |
| `4408` Replaced | Log "replaced by newer connection"; không reconnect (connection mới đã active) |
| Các code khác | Exponential backoff reconnect (giữ nguyên logic hiện tại) |

**Callback auth:**
```js
// trước
headers: { 'X-Callback-Secret': callbackSecret }

// sau
headers: { 'X-Device-Token': deviceToken }
```
`deviceToken` cache in-memory (đọc từ storage một lần khi pair, giữ suốt lifetime SW).

**Xóa:**
- Biến `callbackSecret`, `AGENT_WS_URL`
- Xử lý message type `callback_secret`
- `chrome.storage.local.set({ callbackSecret })` trong `init()`

**Giữ nguyên:**
- Token capture (`webRequest.onBeforeSendHeaders`)
- `fetchAndPushUserInfo()` — vẫn push user_info qua WS
- `handleApiRequest()`, `handleTrpcRequest()` — proxy logic không đổi
- `keepAlive` alarm

---

## 5. Error handling

| Tình huống | Xử lý |
|---|---|
| Extension nối WS với token revoked | Close 4401; extension xóa token, hiện "Đăng nhập lại" |
| 2 connection cùng account | last-wins: cũ close 4408, mới được register |
| Job chạy nhưng extension offline | `Request.status = "failed"`, `error = "extension_offline"` |
| Pair thất bại (cookie hết hạn) | Extension setState `'unpaired'`, retry sau 30s |
| Server restart | Registry rỗng; extension reconnect (backoff); job pending timeout theo logic hiện tại |
| `pairWithServer` gọi khi đã có token hợp lệ | Extension kiểm tra deviceToken trước, pair chỉ khi không có hoặc sau 4401 |

---

## 6. Testing

### Server (pytest)

| File | Kiểm tra |
|---|---|
| `test_registry.py` | register/unregister/get/is_online; last-wins đóng 4408; unregister sai ws không gỡ nhầm |
| `test_pair_endpoint.py` | Cookie hợp lệ → trả device token; cookie sai/hết hạn/revoked → 401; 2 lần pair → 2 token khác nhau |
| `test_ext_ws.py` | Token hợp lệ → kết nối OK; token sai → close 4401; 2 kết nối cùng account → close 4408 cái cũ |
| `test_worker_registry.py` | Job mang account_id → dùng đúng FlowClient; account offline → `failed` + `extension_offline` |
| `test_callback_auth.py` | `X-Device-Token` hợp lệ → resolve; token revoked → 401; sai token → 401 |

### Fixture update

Fixtures hiện có dùng `flow_client` singleton → cập nhật để inject mock vào `registry.register(account_id, mock_ws)`. 333 test hiện có dùng 1 account seed — chỉ cần fixture set up `registry` thay vì mock singleton.

### Extension (manual)

| Scenario | Kỳ vọng |
|---|---|
| Load extension, chưa login web | Popup: "Chưa kết nối — Đăng nhập trên web" |
| Login web → extension detect | Auto-pair, WS connect, popup: "Đã kết nối" |
| Logout web | Server revoke; WS close 4401; popup: "Đăng nhập lại" |
| Mở tab thứ 2 với cùng account | Tab 1 WS close 4408; tab 2 active |

---

## 7. File map

```
agent/
  flowboard/
    services/
      registry.py           ← mới
      flow_client.py        ← bỏ singleton + callback_secret
      ws_server.py          ← XÓA
    routes/
      ext_ws.py             ← mới (WebSocket /ext)
      extension.py          ← mới (POST /api/extension/pair)
      ext_callback.py       ← đổi X-Callback-Secret → X-Device-Token
      auth.py               ← dùng registry thay singleton
    config.py               ← bỏ WS_HOST, EXTENSION_WS_PORT
    main.py                 ← bỏ run_ws_server, mount ext_ws + extension routers
  tests/
    test_registry.py        ← mới
    test_pair_endpoint.py   ← mới
    test_ext_ws.py          ← mới
    test_worker_registry.py ← mới
    test_callback_auth.py   ← mới

extension/
  manifest.json             ← thêm cookies permission
  background.js             ← pairWithServer, connectToServer, close codes
```
