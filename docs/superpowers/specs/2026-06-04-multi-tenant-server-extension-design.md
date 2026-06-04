# Multi-tenant Server + Client Extension — Design Spec

**Date:** 2026-06-04
**Status:** Approved design, pending implementation plan
**Scope:** v1 — nền tảng (auth tối thiểu + multi-tenant + extension routing). Billing, email verify/reset, desktop app: **ngoài phạm vi** (sub-project sau).

---

## 1. Bối cảnh & mục tiêu

Flowboard hiện là công cụ **local-only, single-user**:

- **Frontend** (React/Vite, `:5173`) gọi agent, không gọi thẳng Google Flow.
- **Agent** (FastAPI + SQLite, `:8101`) sở hữu toàn bộ board state, chạy worker queue, có **WS server `:9223`** cho extension, shell ra LLM CLI (OAuth máy local).
- **Extension** (Chrome MV3) sống trên `labs.google/fx/tools/flow`, proxy mọi request Flow qua **WebSocket localhost** về agent. Bảo mật bằng HMAC `X-Callback-Secret` sinh mỗi lần agent khởi động.
- `flow_client` là **singleton toàn cục** (1 extension duy nhất); models **chưa có owner/account**; `routes/auth.py` hiện chỉ surface profile Google từ extension (KHÔNG phải auth thật).

**Mục tiêu chuyển đổi:**

- **agent + frontend** deploy trên server (đa tenant).
- **extension** cài trên máy client.
- Thêm **đăng ký / đăng nhập tài khoản** (SaaS công khai, nhưng v1 chỉ auth tối thiểu).
- Phục vụ nhiều tài khoản; **khi đăng nhập sẽ điều khiển đúng extension tương ứng**.

### Quyết định đã chốt

| Chủ đề | Quyết định |
|---|---|
| Quy mô | SaaS công khai (nhưng v1 = auth tối thiểu) |
| Ghép nối extension | **Auto-pair qua session web + mint device token** |
| LLM trên server | **Mỗi user nhập API key riêng**, lưu mã hoá |
| Lưu trữ | **Object storage (S3/R2/MinIO) + PostgreSQL** |
| Desktop app | Ngoài phạm vi (sub-project riêng) |
| Phạm vi v1 | Auth tối thiểu (email+mật khẩu), **chưa** email verify/reset/billing |
| Topology | **Hướng A — single-instance + connection registry in-memory** |
| Migrate dữ liệu local cũ | **Không** — v1 khởi tạo DB rỗng |

---

## 2. Kiến trúc tổng thể (topology mới)

```
  MÁY CLIENT (Chrome profile của user)              SERVER (1 instance)
┌─────────────────────────────────┐         ┌──────────────────────────────────┐
│  Web app (tab trình duyệt)       │ HTTPS   │  Frontend (React, static)         │
│   - đăng nhập → session cookie   │────────►│  Agent (FastAPI :8101)            │
│                                  │  JWT    │   - REST API (scope theo account) │
│  Chrome Extension                │         │   - Auth service (email/mật khẩu) │
│   - background SW                │         │   - Connection Registry           │
│   - đọc cookie app domain        │  pair   │       {account_id → WS ext}       │
│   - mint device token ───────────┼────────►│   - Worker queue (job mang        │
│   - wss:// tới /ext?token=…  ◄────┼─ wss ──►│        account_id)                │
│   - content script trên          │         └───────┬───────────────┬──────────┘
│     labs.google/fx/tools/flow    │                 │               │
│     (proxy Flow API)             │                 ▼               ▼
└────────────┬────────────────────┘          ┌────────────┐   ┌────────────┐
             │                                │ PostgreSQL │   │  S3 / R2   │
             ▼ (cookies của user)             │ (đa tenant)│   │  (media)   │
      Google Flow labs.google                 └────────────┘   └────────────┘
```

### Năm thay đổi cốt lõi

1. **WS server `:9223` localhost → endpoint `wss://` có auth trên server.** Không còn handler global; mỗi kết nối extension mang **device token** → server resolve `account_id` → đăng ký vào **Connection Registry**.
2. **`flow_client` singleton → một instance / account** sống trong registry. Mỗi job mang `account_id` để tra đúng connection.
3. **Web tier có auth thật** (email+mật khẩu, JWT). Profile Google từ extension gắn vào account.
4. **Storage:** SQLite → PostgreSQL; `storage/media/` → S3/R2 (URL ký), tách theo `account_id`.
5. **Callback HMAC per-boot → device token per-account** (revoke được).

### Vì sao Hướng A (single-instance + registry in-memory)

- Gần kiến trúc hiện tại nhất, build nhanh, ít hạ tầng (1 VPS + Postgres + S3) — phù hợp mục tiêu ship nhanh để kiểm chứng mô hình.
- Đường tiến hoá rõ ràng: registry in-memory → registry Redis + pub/sub (Hướng B) hoặc tách gateway service (Hướng C) chỉ là thay backend của registry, không phá vỡ interface.
- Đánh đổi: chỉ scale dọc (1 instance); restart → registry rỗng nhưng extension tự reconnect, không mất dữ liệu.

---

## 3. Account & luồng Auth / Pairing

### Bảng mới

```
Account
  id              PK
  email           unique, index
  password_hash   (bcrypt/argon2)
  created_at
  llm_provider    "claude" | "gemini" | "codex"
  llm_api_key_enc bytea   -- mã hoá (Fernet/AES-GCM), khoá giải mã từ ENCRYPTION_KEY env
  google_email, google_name, google_picture   nullable  -- do extension push

Session            -- access token là JWT stateless; refresh token lưu hash
  id, account_id FK, refresh_token_hash, expires_at, created_at

DeviceToken        -- token để extension nối WS, revoke được
  id, account_id FK, token_hash (index), label, created_at,
  last_seen_at, revoked_at nullable
```

### Luồng đăng ký / đăng nhập (web)

1. `POST /api/auth/register {email, password}` → tạo Account (hash mật khẩu). (v1: chưa email verify.)
2. `POST /api/auth/login {email, password}` → trả **access JWT** (~15ph, mang `account_id`) + set **refresh cookie** HttpOnly (dài hạn).
3. Mọi REST request kèm `Authorization: Bearer <JWT>` → dependency `get_current_account()` resolve `account_id`, inject vào route.
4. `POST /api/auth/logout` → revoke refresh + (tuỳ chọn) revoke device token để extension ngắt.

### Luồng auto-pair extension

```
1. User đăng nhập web (cùng Chrome profile có extension)
   → refresh cookie HttpOnly set trên app domain.
2. Extension background SW (permission `cookies` + host permission app domain)
   đọc cookie phiên web: chrome.cookies.get({url: APP_URL, name: "fb_refresh"}).
3. Extension gọi POST /api/extension/pair (cookie tự đính cùng host)
   → server xác thực cookie → biết account_id → tạo DeviceToken
     (lưu token_hash), trả token thô 1 lần.
4. Extension lưu device token vào chrome.storage.local.
5. Extension mở wss://server/ext?token=<device_token>
   → server hash & tra DeviceToken → account_id
   → đăng ký connection vào Registry[account_id]; cập nhật last_seen_at.
6. User logout web → server revoke DeviceToken
   → reconnect kế bị từ chối (4401) → extension xoá token,
     hiển thị "Chưa kết nối — đăng nhập lại trên web".
```

**Fallback thủ công (ngoài v1):** web sinh mã ghép nối ngắn hạn; user dán vào popup extension nếu khác Chrome profile.

**Bảo mật pairing:** device token scope hẹp (chỉ proxy Flow + push signal, không full API); hash trước khi lưu; revoke khi logout/đổi mật khẩu; extension chỉ đọc cookie từ **đúng app domain** (host permission khai báo tường minh trong manifest).

---

## 4. Multi-tenant data model & migration

### Chiến lược scope

`Board` là **gốc tenant**. Thêm `account_id` FK vào `Board`; mọi entity con (`Node`, `Edge`, `Request`, `Asset`, `Plan`, `ChatMessage`, `BoardFlowProject`, `MediaProjectMapping`) thuộc về board → gián tiếp thuộc account.

```
Account (1) ──< Board (account_id FK, index)
                 └──< Node ──< Edge, Request, Asset, ...
```

### Enforce isolation (yếu tố bảo mật quan trọng nhất)

- Mọi route lấy `account_id` từ **JWT** — không bao giờ từ client param.
- Truy vấn board luôn `WHERE board.account_id = :account_id`. Truy cập board theo id sai chủ → trả **404** (không lộ tồn tại); log cảnh báo cross-tenant.
- **Denormalize `account_id` xuống các bảng con hay truy vấn trực tiếp** (`Node`, `Request`, `Asset`): thêm cột `account_id` index, set khi tạo. Đánh đổi có chủ đích — thừa 1 cột để mọi query con filter trực tiếp, giảm rủi ro rò rỉ chéo tenant.
- Gói một helper `scoped_query(model, account_id)` / dependency dùng nhất quán ở mọi route, thay vì rải filter thủ công.

### Migration SQLite → PostgreSQL

- **Schema:** thêm **Alembic** (chưa có). Migration đầu tạo toàn bộ bảng trên Postgres + cột `account_id` + index.
- **Code model:** SQLModel/SQLAlchemy giữ gần như nguyên; đổi `DATABASE_URL` sang `postgresql+psycopg://…`. Rà các chỗ SQLite-specific (JSON, `PRAGMA`, autoincrement).
- **Dữ liệu cũ:** không migrate; v1 khởi tạo DB rỗng. (Nếu cần, viết script một lần gán board cũ cho 1 account seed.)
- **Config:** `config.py` thêm `DATABASE_URL`, `S3_*`, `JWT_SECRET`, `ENCRYPTION_KEY`, `APP_DOMAIN`, `EXTENSION_TOKEN_TTL`… đọc từ env (12-factor), không hardcode.

`Request` (và job payload) **bắt buộc mang `account_id`** — khoá nối giữa job và connection ở §5.

---

## 5. Connection Registry & WS routing (lõi)

### Từ singleton → registry

```python
# services/registry.py (mới)
class ConnectionRegistry:
    _conns: dict[int, FlowClient]          # account_id -> per-account FlowClient
    def register(account_id, websocket) -> FlowClient
    def unregister(account_id, websocket)  # chỉ gỡ nếu đúng ws hiện tại
    def get(account_id) -> FlowClient | None
    def is_online(account_id) -> bool
```

- `FlowClient` đổi từ singleton thành **một instance / account** (giữ nguyên logic proxy/`handle_message`, bỏ tính toàn cục). Mỗi instance giữ: ws hiện tại, paygate tier, Flow token, pending requests của account đó.
- Registry sống trong process (Hướng A). Restart → rỗng → extension reconnect tự nạp lại.

### WS handler mới (`/ext` trên server, thay `:9223` localhost)

```
1. Extension nối wss://server/ext?token=<device_token>
2. Hash token → tra DeviceToken → account_id.
   Token sai/revoked → đóng close code 4401, KHÔNG đăng ký.
3. registry.register(account_id, websocket).
   Nếu account đã có connection cũ → policy "last-wins":
   đóng cái cũ (4408 "replaced"), giữ cái mới.
4. Cập nhật DeviceToken.last_seen_at.
5. Vòng lặp nhận message → flow_client.handle_message(...) trên instance của account.
6. Ngắt → registry.unregister(account_id, websocket) (chỉ nếu đúng ws).
```

**Heartbeat:** ping/pong ~30s phát hiện connection chết → unregister, đánh dấu offline.

### Luồng một job generation (end-to-end)

```
1. Frontend (đã login) → POST /api/.../generate [Bearer JWT]
2. Route resolve account_id từ JWT → tạo Request{account_id, ...} → enqueue.
3. Worker pop job → conn = registry.get(job.account_id)
   - conn None/offline → Request.status="failed", error="extension_offline",
     phát event cho frontend ("Mở tab Flow / kiểm tra extension").
   - conn online → proxy request qua WS tới extension của đúng account
     → extension gọi Google Flow bằng cookie của user → kết quả về qua WS
     → worker cập nhật Request + Asset.
4. Media bytes → tải về & đẩy lên S3 dưới prefix account_id/ (§6).
5. Event/SSE bắn cho đúng account → frontend cập nhật node.
```

**Cách ly tuyệt đối:** worker chỉ tra `registry.get(job.account_id)`. Không có đường nào để job của account A chạm extension của account B.

**Callback HTTP:** `X-Callback-Secret` per-boot → callback kèm **device token** (hoặc callback-token ngắn hạn cấp khi dispatch), server resolve account_id; không còn secret chung.

---

## 6. LLM per-user key + Media S3

### LLM per-user

- Mỗi account lưu `llm_provider` + `llm_api_key_enc` (mã hoá Fernet/AES-GCM, khoá từ `ENCRYPTION_KEY` env). Settings UI cho user dán key + chọn provider; server **validate key bằng 1 call test** rồi mới lưu.
- Tầng LLM (`services/claude_cli.py`, `services/llm/`) chuyển từ **shell CLI** sang **gọi API trực tiếp** bằng key của account. Giữ nguyên interface `vision describe / auto-prompt / planner`, mỗi call nhận `account` để lấy đúng key.
- Chưa có key → tính năng LLM báo "Hãy nhập API key trong Settings" (fail rõ ràng, không dùng key người khác).
- **Bảo mật:** key không bao giờ trả về client sau khi lưu (chỉ hiện "đã cấu hình ••••"); không log key.

### Media trên S3 / R2

- `services/media.py`: bytes từ Flow CDN → upload lên bucket dưới prefix **`{account_id}/{media_id}`**. `Asset.local_path` → `Asset.s3_key`.
- Frontend xem media → agent trả **presigned GET URL** ngắn hạn (vài phút) cho đúng object của account, **sau khi check ownership**.
- Giữ logic "tải sớm để vượt TTL 1h của Flow" — đích đến là S3 thay vì disk.
- Env: `S3_ENDPOINT/BUCKET/KEY/SECRET/REGION` (tương thích AWS S3, Cloudflare R2, MinIO).

---

## 7. Error handling & edge cases

| Tình huống | Xử lý |
|---|---|
| Extension offline khi có job | `Request.status="failed"`, `error="extension_offline"`; banner "Mở tab Flow / kiểm tra extension". Không treo job vô hạn. |
| Device token bị revoke (logout/đổi mật khẩu) | WS đóng `4401`; extension xoá token, hiện "Đăng nhập lại trên web". |
| 2 connection cùng account | **last-wins**: đóng cái cũ `4408`, giữ cái mới. |
| User chưa nhập LLM key | Fail rõ ràng "Nhập API key trong Settings", không fallback key người khác. |
| Truy cập board không thuộc account | Trả **404** (không lộ tồn tại), log cảnh báo cross-tenant. |
| Flow token hết hạn / paygate unknown | Giữ hành vi hiện tại: fail loud, không stamp tier sai vào DB. |
| Presigned URL hết hạn khi xem | Frontend xin URL mới qua agent (check ownership rồi ký lại). |
| Server restart | Registry rỗng → extension reconnect (backoff); job đang chạy đánh dấu lại/timeout. |
| Mất `ENCRYPTION_KEY` | Key LLM không giải mã được → buộc user nhập lại; tài liệu hoá env bắt buộc. |

---

## 8. Testing

- **Auth:** đăng ký/đăng nhập, JWT hết hạn, refresh, logout revoke; sai mật khẩu; trùng email.
- **Multi-tenant isolation (bộ test riêng, quan trọng nhất):** account A không đọc/sửa được board/node/asset của B (kỳ vọng 404); job của A không tra được connection của B.
- **Pairing & WS:** `/api/extension/pair` cấp device token đúng account; WS từ chối token sai/revoked (`4401`); last-wins khi 2 connection.
- **Routing:** job mang `account_id` → registry tra đúng connection; extension offline → `failed` với error đúng.
- **LLM:** key mã hoá lưu/đọc đúng; thiếu key → lỗi rõ ràng; key không lộ qua API/log.
- **S3:** upload theo prefix account; presigned URL check ownership; URL hết hạn → cấp lại.
- Giữ **333 test agent hiện có** chạy được sau refactor singleton→registry (đa số dùng 1 account seed).
- Framework: pytest (đã có); thêm fixture tạo account + token; mock S3 (moto/minio) + WS.

---

## 9. Phạm vi & decomposition (gợi ý cho bản plan)

Spec lớn nhưng gắn kết. Gợi ý chia phase khi sang writing-plans:

1. **Nền DB & migration** — Postgres + Alembic + `account_id` scoping + helper isolation.
2. **Auth** — Account model, register/login/JWT/refresh, dependency `get_current_account`.
3. **Registry & WS** — singleton→registry, `/ext` WS có auth, pairing endpoint.
4. **Extension client** — đọc cookie, mint device token, `wss://`, reconnect.
5. **LLM per-user key + S3 media.**
6. **Isolation test pass + hardening.**

### Out of scope (sub-project sau)

- Email verify, quên/đổi mật khẩu (ngoài revoke cơ bản), billing/gói cước/quota.
- Desktop app (Electron) trong mô hình mới.
- Scale ngang (Hướng B/C): Redis registry, nhiều instance, gateway service.
- Migrate dữ liệu local cũ lên server.
