# Kế hoạch nâng cấp Flowboard từ local sang hosted SaaS nhỏ

## Mục tiêu

Tài liệu này mô tả lộ trình đưa Flowboard từ ứng dụng local-only lên bản hosted cho
một cá nhân hoặc một team nhỏ. Mục tiêu thực tế là có một bản chạy trên server
riêng, truy cập qua HTTPS, dữ liệu được lưu bền vững, có backup, và vẫn giữ
được luồng làm việc hiện tại với Chrome extension + Google Flow.

Phạm vi của bản đầu tiên:

- Một owner hoặc một team nhỏ dùng chung một instance.
- Frontend React được serve qua domain riêng.
- Backend FastAPI chạy như service riêng sau reverse proxy.
- Dữ liệu board/request/asset được lưu bền vững trên server.
- Chrome extension có thể kết nối đến backend hosted.
- Secret LLM và token liên quan không bị lưu trong repo hoặc image Docker.

Không nằm trong MVP:

- Multi-tenant SaaS công khai.
- Billing, subscription, quota theo user.
- RBAC phức tạp cho nhiều organization.
- Marketplace extension public.
- Tách worker thành hệ thống queue phân tán quy mô lớn.

## Hiện trạng local-only

Flowboard hiện gồm các phần chính:

- `frontend/`: React + Vite, gọi API theo same-origin path như `/api/boards`.
- `agent/`: FastAPI + SQLModel, mặc định lưu SQLite tại `FLOWBOARD_STORAGE`.
- `extension/`: Chrome MV3 bridge, kết nối WebSocket đến agent và proxy request
  sang Google Flow bằng phiên đăng nhập của trình duyệt.
- `data/storage`: volume local cho SQLite và media.
- `data/codex`: volume local cho cấu hình/credential CLI khi chạy Docker.

Các giả định local quan trọng:

- Backend mặc định mở HTTP port `8101` và extension WebSocket port `9223`.
- Dedicated extension WebSocket hiện không có auth app-level, nên được thiết kế để
  chỉ expose trên loopback.
- Secret LLM được lưu bằng JSON file local `~/.flowboard/secrets.json` hoặc path
  từ `FLOWBOARD_SECRETS_PATH`.
- SQLite file phù hợp local/single-user, chưa có migration/backup production rõ
  ràng.
- Frontend đang gọi API relative path, thuận lợi khi frontend và backend dùng
  chung origin sau reverse proxy.
- Auth hiện chủ yếu là profile Google Flow do extension đẩy lên agent, chưa phải
  auth riêng của ứng dụng.

## Kiến trúc hosted đề xuất

Bản hosted nhỏ nên giữ một deployment đơn giản:

```text
Internet
  |
  | HTTPS
  v
Reverse proxy (Caddy/Nginx/Traefik)
  |-- /                 -> frontend static build
  |-- /api/*            -> FastAPI agent :8101
  |-- /media/*          -> FastAPI agent :8101
  |-- /ext-ws or :9223  -> extension WebSocket, đã harden
  v
Docker host / VM
  |-- flowboard-agent
  |-- persistent storage volume
  |-- optional Postgres
```

Khuyến nghị giai đoạn đầu:

- Dùng một VM/VPS riêng, chỉ cho phép HTTPS public.
- Serve frontend và API chung domain, vì frontend đã dùng relative API path.
- Giữ SQLite nếu chỉ một user/team rất nhỏ, nhưng bắt buộc có backup định kỳ.
- Chỉ expose extension WebSocket sau khi đã có cơ chế xác thực hoặc token bắt tay.
- Lưu media và SQLite trong persistent volume ngoài container.

## Thay đổi code bắt buộc

### 1. Cấu hình public URL

Thêm các biến mới:

- `FLOWBOARD_PUBLIC_ORIGIN`: ví dụ `https://flowboard.example.com`.
- `FLOWBOARD_API_ORIGIN`: nếu frontend và API khác origin; mặc định dùng same-origin.
- `FLOWBOARD_EXT_WS_URL`: URL WebSocket mà extension sẽ kết nối.

Frontend nên có config build-time/runtime để extension và UI không hard-code
localhost. Nếu vẫn deploy chung origin, các API `/api/*` có thể giữ nguyên.

### 2. Harden CORS và HTTP headers

**Đây là hạng mục cần sửa trước Phase 0, không phải Phase 1.**

Hiện `CORSMiddleware` đang `allow_origins=["*"]` kết hợp với `allow_credentials=True`.
Theo CORS spec, combo này là invalid — browser hiện đại sẽ block request cross-origin
ngay lập tức. Lỗi này đang ẩn vì frontend và backend hiện chạy cùng origin; khi
tách ra hosted sẽ break ngay.

Cần đổi sang danh sách origin cụ thể:

- Domain production.
- Domain staging nếu có.
- Extension origin nếu Chrome extension cần gọi HTTP trực tiếp.

Và đảm bảo `allow_credentials` chỉ bật khi thực sự cần cookie/session. Nếu dùng
Bearer token trong header, có thể tắt `allow_credentials=False` để an toàn hơn.

Reverse proxy nên bật:

- HTTPS bắt buộc.
- HSTS sau khi domain ổn định.
- Giới hạn upload size phù hợp với image/video.
- Timeout dài hơn cho các request generation/polling nếu cần.

### 3. Xác thực app tối thiểu

Bản hosted không nên dựa hoàn toàn vào Google Flow profile từ extension. Cần một
lớp auth riêng của Flowboard:

- MVP đơn giản: one-time admin password hoặc bearer token trong env, lưu session
  bằng secure cookie.
- Team nhỏ: email/password hoặc OAuth provider, lưu user trong DB.
- Tất cả endpoint ghi dữ liệu (`POST/PATCH/DELETE`) cần yêu cầu auth.
- `/api/health` có thể public nhưng chỉ trả thông tin tối thiểu.

Google Flow account từ extension vẫn là "generation identity", không phải
"Flowboard app identity".

**Lưu ý về in-memory auth state:** Hiện tại toàn bộ thông tin user (`_user_info`,
`_flow_key`, paygate tier) được lưu in-memory trong `flow_client`. Mỗi lần container
restart — do crash, deploy, hoặc watchdog — extension phải reconnect lại để agent
biết user là ai. Đây là hành vi by-design với local/single-user, nhưng với hosted
cần phải document rõ cho người dùng và có cơ chế re-auth nhanh sau restart. Các
request đang chạy lúc restart sẽ được đánh dấu `failed` tự động bởi
`_recover_orphan_running_requests()`, nhưng user mất session và cần kết nối lại
extension.

### 4. Extension WebSocket hosted

Đây là điểm rủi ro lớn nhất. WebSocket hiện được thiết kế cho loopback và không
nên expose public như hiện tại.

**Lưu ý quan trọng:** Hiện tại `main.py` có guard cứng trong code từ chối boot
nếu `FLOWBOARD_WS_HOST` không phải loopback:

```python
if WS_HOST not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
    raise RuntimeError(...)
```

Phase 2 **bắt buộc phải sửa guard này trong code** (không chỉ thêm env var là đủ).
Chỉ remove guard sau khi đã có token handshake hoạt động.

Cần làm trước khi mở Internet:

- Thêm handshake token riêng cho extension, ví dụ `FLOWBOARD_EXTENSION_TOKEN`.
- Extension gửi token khi connect WebSocket.
- Server từ chối connection nếu token sai.
- Dùng `wss://` qua reverse proxy.
- Giới hạn origin/host nếu có thể.
- Log connect/disconnect và remote address.
- Document cách rotate extension token (hiện tại `callback_secret` được sinh
  in-memory mỗi lần connect, mất khi restart — cần có hướng dẫn thủ công
  cho người vận hành).

Xem thiết kế UI cho màn hình cấu hình extension: `docs/design/stitch-phase1/10-settings-extension.html`
— đã có input field cho hosted WebSocket URL, có thể reference trực tiếp khi implement.

Nếu chưa làm xong, chỉ nên dùng VPN/Tailscale/SSH tunnel để extension kết nối
đến server, không expose port WebSocket public.

### 5. Secret storage

Không dùng secret file nằm trong image Docker. Cần:

- Mount secret volume riêng hoặc dùng secret manager của platform.
- Đặt `FLOWBOARD_SECRETS_PATH` trỏ đến path trong persistent volume có permission
  hạn chế.
- Không log API key, bearer token, callback secret.
- Backup secret tách biệt với backup media nếu team có yêu cầu bảo mật cao hơn.

Về dài hạn, nên tách provider config vào DB và lưu secret bằng envelope
encryption hoặc secret manager.

Ngoài ra, `callback_secret` (HMAC key dùng xác thực HTTP callback từ extension)
hiện được sinh in-memory mỗi lần extension connect và mất khi server restart.
Cần mount volume cho secret này nếu muốn extension không bị ngắt khi agent restart.

### 6. Database và migration

Có hai lựa chọn:

- Giai đoạn 1: giữ SQLite trên persistent disk.
- Giai đoạn 2: chuyển sang Postgres khi cần nhiều người truy cập, backup tốt hơn,
  migration tốt hơn, hoặc worker riêng.

Nếu giữ SQLite:

- Đặt `FLOWBOARD_DB=/app/storage/flowboard.db`.
- Bật backup file DB theo lịch.
- Đảm bảo chỉ một backend process ghi DB — đặt `--workers 1` trong uvicorn command
  trong production compose để tránh nhiều worker ghi đồng thời.
- Bật WAL mode khi khởi động để tăng concurrency đọc/ghi:
  `PRAGMA journal_mode=WAL;`
- Không scale ngang agent.

Nếu chuyển Postgres:

- Đổi `flowboard.db.session` để nhận `DATABASE_URL`.
- Thêm migration bằng Alembic.
- Kiểm tra lại JSON column, datetime timezone, index, unique constraint
  `Asset.uuid_media_id`.

### 7. Media storage

Giai đoạn 1 có thể giữ media trong local persistent volume. Cần tài liệu hoá:

- Thư mục media nằm ở đâu.
- Dung lượng tối đa dự kiến.
- Chính sách prune file tạm/signed URL hết hạn.
- Backup media có cần đi cùng DB hay không.

**Lưu ý về cách serve media:** Hiện tại `/media/*` được serve trực tiếp qua FastAPI,
không qua nginx. Khi cấu hình reverse proxy cần quyết định rõ ràng:
- Giữ FastAPI serve media (đơn giản hơn, nhưng agent phải xử lý cả request tĩnh).
- Hoặc cấu hình nginx serve `/app/storage/media` trực tiếp (hiệu quả hơn, giảm tải
  cho agent).

Quyết định này ảnh hưởng đến cấu hình volume và reverse proxy ngay từ Phase 1.

Giai đoạn 2 nên chuyển sang object storage:

- S3/R2/GCS cho image/video.
- DB chỉ lưu object key, mime, size, metadata.
- Backend phát signed URL ngắn hạn cho frontend.

### 8. LLM provider trên server

Flowboard hiện hỗ trợ CLI provider và API key provider. Khi hosted, CLI provider
cần được xem như tác vụ vận hành:

- Cài CLI trong image hoặc trên host.
- Login/OAuth CLI bằng user riêng, không dùng credential cá nhân trên máy dev.
- Mount credential directory như volume secret.
- Giám sát subprocess timeout và lỗi auth.

**Biến quan trọng cho production:** Đặt `FLOWBOARD_PLANNER_BACKEND=api` trong
`.env` production để agent dùng API key thay vì gọi CLI subprocess. Giữ `cli`
hoặc `auto` chỉ cho local/dev. Đây là điều kiện cần thiết để hosted ổn định vì
CLI OAuth dễ lỗi do credential hết hạn, home directory sai, hoặc container rebuild
làm mất config.

Nếu muốn ổn định hơn, ưu tiên API-key provider cho hosted deployment và chỉ giữ
CLI provider cho local/dev.

## Lộ trình triển khai

### Phase 0: Đóng gói và cấu hình

Kết quả mong muốn: build chạy lặp lại được trên server.

- Chuẩn hoá biến môi trường cho public origin và extension WebSocket URL.
- Tạo Docker Compose production riêng, không mount thư mục dev không cần thiết.
- Tách volume: `storage`, `secrets`, optional `codex/cli credentials`.
- Build frontend static và serve sau reverse proxy.
- Viết `.env.example` cho hosted deployment.

### Phase 1: Hosted private MVP

Kết quả mong muốn: owner truy cập app qua HTTPS và chạy workflow end-to-end.

- Deploy lên một VM.
- Cấu hình domain + HTTPS.
- Reverse proxy `/api/*` và `/media/*` về agent.
- Giữ SQLite trên persistent volume.
- Thêm auth tối thiểu cho dashboard/API.
- Không expose WebSocket public nếu chưa có token; dùng VPN/tunnel tạm thời.
- Chạy smoke test: tạo board, upload image, generate image/video, xem media,
  reload app, restart container.

### Phase 2: Harden extension bridge

Kết quả mong muốn: extension có thể kết nối `wss://` an toàn.

- Thêm extension token handshake.
- Thêm config UI/file cho extension trỏ đến hosted URL.
- Kiểm tra callback secret và token Google Flow không bị log.
- Giới hạn CORS/origin.
- Thêm health detail riêng cho admin đã login.
- Tài liệu hoá cách rotate extension token.

### Phase 3: Vận hành team nhỏ

Kết quả mong muốn: 2-5 người có thể dùng cùng instance với rủi ro chấp nhận được.

- Thêm user table và session/cookie nếu MVP đang dùng admin token.
- Thêm ownership hoặc workspace field cho board.
- Thêm audit/activity theo user.
- Thêm backup tự động DB + media.
- Thêm log aggregation có redaction.
- Thêm rate limit cho API ghi và upload.
- Cân nhắc Postgres nếu có nhiều user ghi đồng thời.

## Checklist production

Trước khi mở domain public:

- `allow_origins` không còn là `"*"` và `allow_credentials` được kiểm tra lại.
- Dashboard/API có auth riêng.
- Extension WebSocket có token hoặc chỉ đi qua VPN/tunnel.
- `FLOWBOARD_STORAGE`, `FLOWBOARD_DB`, `FLOWBOARD_SECRETS_PATH` trỏ đến
  persistent volume.
- Backup DB đã được restore thử ít nhất một lần.
- Reverse proxy bật HTTPS và giới hạn upload size.
- Secret không nằm trong Git, image, log, hay frontend bundle.
- `/api/health` không lộ token, email, paygate tier chi tiết nếu public.
- Container restart không làm mất request/media.
- Extension có tài liệu cấu hình URL cho hosted instance.
- `FLOWBOARD_PLANNER_BACKEND=api` được đặt trong production env.
- uvicorn chạy với `--workers 1` để tránh SQLite concurrent write.

## Rủi ro chính

### Extension và Google Flow session

Chrome extension phụ thuộc phiên đăng nhập Google Flow của trình duyệt. Khi
chuyển lên hosted, app identity và generation identity cần được tách rõ. Nếu
nhiều người dùng chung instance, cần quy định ai là người kết nối extension và
request nào sẽ đi qua account Google nào.

### WebSocket unauthenticated

Không expose WebSocket hiện tại ra Internet. Nếu bắt buộc phải expose, phải có
token handshake trước. Đây là hạng mục chặn release hosted public.

### SQLite

SQLite chấp nhận được cho private MVP, nhưng không phải nền tảng scale ngang.
Nếu có nhiều user ghi đồng thời, worker riêng, hoặc cần migration nghiêm túc,
nên chuyển sang Postgres.

### LLM CLI trên server

CLI OAuth trên server dễ gây lỗi do credential hết hạn, home directory sai, hoặc
container rebuild làm mất config. Cần mount credential volume và có healthcheck
provider rõ ràng. API-key provider sẽ dễ vận hành hơn.

### Media và chi phí lưu trữ

Image/video có thể tăng dung lượng nhanh. Cần chính sách backup, retention, và
prune sớm, nếu không VPS sẽ đầy disk trước khi phát hiện qua UI.

## Đề xuất thứ tự làm việc gần nhất

**Khởi động bắt buộc (trước khi deploy bất kỳ thứ gì):**

1. **Sửa CORS ngay:** đổi `allow_origins=["*"]` sang allowlist, kiểm tra lại
   `allow_credentials` — đây là lỗi silent sẽ break ngay khi frontend và backend
   khác origin.
2. **Đặt `FLOWBOARD_PLANNER_BACKEND=api`** trong production env, cùng với API key
   LLM tương ứng.

**Phase 0 — đóng gói:**

3. Tạo production compose + reverse proxy mẫu; thêm `--workers 1` cho uvicorn.
4. Thêm `FLOWBOARD_PUBLIC_ORIGIN` và các biến hosted vào `.env.example`.
5. Quyết định cách serve media (FastAPI vs nginx serve static) và phản ánh vào
   compose + reverse proxy config.

**Phase 1 — hosted private MVP:**

6. Thêm auth tối thiểu cho dashboard/API.
7. Viết runbook deploy VM + backup/restore SQLite (bao gồm bật WAL mode).
8. Chạy smoke test end-to-end trên staging domain.

**Phase 2 — harden extension bridge:**

9. Sửa guard WS trong `main.py`, thêm token handshake `FLOWBOARD_EXTENSION_TOKEN`.
10. Thêm config UI cho extension (tham khảo `docs/design/stitch-phase1/10-settings-extension.html`).
11. Đổi CORS/origin cho extension WebSocket.
12. Tài liệu hoá cách rotate extension token và `callback_secret`.

Sau khi hoàn thành các mục trên, Flowboard có thể được coi là bản hosted private
có thể dùng thật cho một owner hoặc team nhỏ. Các bước multi-tenant, billing,
quota, và scale worker nên tách thành kế hoạch riêng.
