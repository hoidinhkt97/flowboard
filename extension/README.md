# Flowboard Bridge (Chrome MV3)

Local extension that proxies Flowboard agent requests to authenticated labs.google sessions.

## Build & Install

**Bắt buộc phải build trước khi load vào Chrome** — source files chứa placeholder `__APP_ORIGIN__` cần được thay thế bằng URL thực.

### Bước 1 — Build

```bash
cd extension

# Local dev (mặc định http://localhost:8101)
node build.js

# Custom domain
FLOWBOARD_APP_ORIGIN=https://app.yourdomain.com node build.js
```

Output: thư mục `extension/dist/`

### Bước 2 — Load vào Chrome

1. Mở `chrome://extensions`
2. Bật **Developer mode** (góc trên phải)
3. Nhấn **Load unpacked** → chọn thư mục **`extension/dist/`** (không phải `extension/`)
4. Build lại → nhấn **↺ Reload** trên card extension

### Biến môi trường

| Biến | Mô tả | Mặc định |
|---|---|---|
| `FLOWBOARD_APP_ORIGIN` | Origin của Flowboard server | `http://localhost:8101` |

---

## How it works

- Extension kiểm tra `chrome.storage` xem đã có `deviceToken` chưa.
- Nếu chưa: gọi `pairWithServer()` — đọc cookie `fb_refresh` tại `APP_ORIGIN/api/account/login` rồi POST `/api/extension/pair` để lấy device token.
- Sau khi pair: kết nối WebSocket tới `APP_ORIGIN/ext?token=<device_token>`.
- `Authorization: Bearer ya29.*` token được capture từ outbound request headers tới aisandbox-pa.
- Responses từ `api_request` được gửi về server qua `POST /api/ext/callback` với header `X-Device-Token`.
- Ping keepalive mỗi ~24 s; disconnect → reconnect ~5 s.
- `captchaAction` → extension giải reCAPTCHA Enterprise qua `injected.js` trên Flow tab.

**Badge màu:**

| Badge | Màu | Ý nghĩa |
|---|---|---|
| `●` | Xanh | Đã kết nối |
| `▶` | Vàng | Đang xử lý |
| `○` | Xám | Mất kết nối, đang reconnect |
| `?` | Đỏ | Chưa pair — cần đăng nhập web app |

## Troubleshooting

| Triệu chứng | Nguyên nhân | Fix |
|---|---|---|
| `Invalid url: "__APP_ORIGIN__/..."` | Load từ `extension/` thay vì `extension/dist/` | Chạy `node build.js` → load `dist/` |
| Badge `?` đỏ | Chưa đăng nhập tại `APP_ORIGIN` | Login trên web → extension tự pair trong ~24 s |
| WS close 4401 | Device token bị revoke | Logout → login lại → extension re-pair |
| WS close 4408 | Tab/thiết bị khác cùng account connect sau | Bình thường — connection mới được ưu tiên |

## Content script + injected script

`content.js` chạy ở `document_start` trên `labs.google/fx/tools/flow*`. Nó inject `injected.js` vào MAIN world để truy cập `window.grecaptcha.enterprise`. Hai script giao tiếp qua `CustomEvent` (`GET_CAPTCHA` / `CAPTCHA_RESULT`).
