# Flowboard Desktop App — Design Specification

**Date:** 2026-05-23
**Branch:** `feat/desktop-app`
**Status:** Approved — ready for implementation planning

## Overview

Đóng gói Flowboard (hiện là web app 2 tầng: React SPA + FastAPI agent) thành ứng dụng desktop chạy native trên **Windows** và **macOS**, để cá nhân dùng (internal use).

App desktop sẽ:
- Wrap React SPA bằng Electron `BrowserWindow`
- Spawn FastAPI agent (đã build PyInstaller) làm subprocess
- Giữ nguyên Chrome Extension cho Google Flow auth (không thay thế)
- Lưu data vào thư mục userData chuẩn của OS

## Goals & Non-Goals

### Goals
- User mở app như app desktop bình thường (double-click `.exe` hoặc `.app`)
- Không yêu cầu cài Python, không cần Docker
- Cross-platform: build được trên cả Windows và macOS
- Reuse 100% code hiện tại của frontend và agent (không refactor logic)

### Non-Goals
- Code signing / notarization (internal use)
- Auto-update mechanism
- Loại bỏ Chrome Extension dependency
- Bundle Claude/Gemini CLI vào app (user tự cài)
- System tray, native notifications, native file pickers tích hợp sâu
- CI/CD pipeline tự động

## Architecture

```
┌─────────────────────────────────────────────┐
│           Electron Desktop App               │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │         BrowserWindow                │    │
│  │   React SPA (file:// hoặc localhost) │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │         Electron Main Process        │    │
│  │  - Spawn/monitor agent subprocess    │    │
│  │  - Native menu                       │    │
│  │  - App lifecycle (quit, restart)     │    │
│  └──────────┬───────────────────────────┘    │
└─────────────│───────────────────────────────┘
              │ spawn subprocess
              ▼
┌─────────────────────────────────────────────┐
│   flowboard-agent(.exe/.bin)                 │
│   (PyInstaller bundled)                      │
│   FastAPI :8101 + Extension WS :9223         │
└─────────────────────────────────────────────┘
              │
              ▼ (giữ nguyên)
       Chrome Extension → Google Flow API
```

**Thay đổi so với hiện tại:**
- **Thêm mới:** `desktop/` directory chứa Electron main process code
- **Thêm mới:** `agent/flowboard-agent.spec` (PyInstaller spec)
- **Thêm mới:** `scripts/build-desktop.ps1`, `scripts/build-desktop.sh`
- **Không đổi:** `frontend/`, `agent/flowboard/`, `extension/`

## Component Design

### 1. Directory Structure

```
flowboard-ai/
├── desktop/                          # MỚI
│   ├── package.json                  # Electron app manifest
│   ├── src/
│   │   ├── main.ts                   # Electron entry, spawn agent
│   │   ├── agent-manager.ts          # Lifecycle agent subprocess
│   │   ├── window-manager.ts         # BrowserWindow + splash
│   │   ├── menu.ts                   # Native menu
│   │   └── preload.ts                # IPC bridge (minimal)
│   ├── assets/
│   │   ├── icon.ico                  # Windows
│   │   ├── icon.icns                 # macOS
│   │   └── icon.png
│   ├── electron-builder.yml
│   ├── tsconfig.json
│   └── README.md
│
├── frontend/                         # Không đổi
├── agent/
│   ├── flowboard/                    # Không đổi
│   └── flowboard-agent.spec          # MỚI
├── extension/                        # Không đổi
│
└── scripts/
    ├── build-desktop.ps1             # MỚI - Windows
    └── build-desktop.sh              # MỚI - macOS
```

### 2. Electron Main Process

**Trách nhiệm:**
- Spawn agent subprocess khi app khởi động
- Health check `/api/health` cho tới khi agent ready (timeout 30s)
- Mở splash window trong khi đợi agent
- Tạo `BrowserWindow` chính load React SPA
- Quản lý lifecycle (quit, restart, crash recovery)
- Native menu (File: Quit, Help: Open Logs, About)
- Forward stdout/stderr của agent vào log file

**File chính:**

| File | Mục đích |
|------|----------|
| `src/main.ts` | Entry point, hook `app.on('ready')`, `app.on('before-quit')` |
| `src/agent-manager.ts` | `start()`, `shutdown()`, `respawn()`, `getStatus()` |
| `src/window-manager.ts` | `createSplashWindow()`, `createMainWindow()` |
| `src/menu.ts` | Build native menu (template-based) |
| `src/preload.ts` | Tối thiểu — chỉ expose API cần thiết qua `contextBridge` |

### 3. Python Agent Bundling

**PyInstaller spec (`agent/flowboard-agent.spec`):**

- Mode: `onedir` (không phải `onefile` — startup nhanh hơn)
- Console mode: `true` (để Electron capture stdout/stderr)
- Hidden imports: các module được FastAPI/Uvicorn dynamic import
  - `uvicorn.logging`, `uvicorn.protocols.*`, `uvicorn.lifespan.*`
  - `sqlmodel`, các sub-module SQLAlchemy nếu cần
- Excludes (giảm size): `tkinter`, `matplotlib`, `numpy.tests`

**Cross-platform constraint:**
- PyInstaller **không cross-compile**
- Build Windows binary → phải chạy trên Windows
- Build macOS binary → phải chạy trên macOS

**Output:**
- Windows: `agent/dist/flowboard-agent/flowboard-agent.exe` + folder dependencies
- macOS: `agent/dist/flowboard-agent/flowboard-agent` (Mach-O)

### 4. App Lifecycle

**Startup sequence:**

1. `app.on('ready')` fired
2. Show splash window ngay lập tức
3. `agentManager.start()`:
   - Resolve binary path: `process.resourcesPath/agent/flowboard-agent[.exe]`
   - Spawn với env vars:
     - `FLOWBOARD_STORAGE` = `app.getPath('userData')/storage`
     - `FLOWBOARD_HTTP_PORT` = `8101` (fallback: 8102, 8103...)
     - `FLOWBOARD_EXT_WS_PORT` = `9223`
   - Pipe stdout/stderr → `userData/logs/agent.log`
4. Poll `http://127.0.0.1:8101/api/health` mỗi 500ms, timeout 30s
5. Khi ready: đóng splash, mở main `BrowserWindow` load frontend
6. Frontend kết nối tới agent như bình thường

**Shutdown sequence:**

1. `app.on('before-quit')`, `e.preventDefault()`
2. `agentManager.shutdown()`:
   - Gửi SIGTERM (POSIX) hoặc `taskkill /T` (Windows)
   - Đợi tối đa 5s cho graceful shutdown
   - SIGKILL nếu vẫn chạy
3. `app.exit(0)`

**Crash recovery:**

- Nếu agent subprocess exit với code != 0 khi đang chạy:
  - Show notification "Agent disconnected"
  - Tự respawn 1 lần (auto-retry)
  - Nếu vẫn fail: dialog "Agent crashed. View logs? / Restart? / Quit?"

### 5. Storage & Paths

| OS | Storage path | Logs path |
|----|--------------|-----------|
| Windows | `%APPDATA%\Flowboard\storage\` | `%APPDATA%\Flowboard\logs\` |
| macOS | `~/Library/Application Support/Flowboard/storage/` | `~/Library/Application Support/Flowboard/logs/` |

Dùng `app.getPath('userData')` của Electron — tự động đúng theo OS.

SQLite DB: `<storage>/flowboard.db`
Media files: `<storage>/media/`

### 6. Build Pipeline

**Dev mode (không build binary):**

```powershell
# Terminal 1: agent
cd agent && uvicorn flowboard.main:app --reload --port 8101

# Terminal 2: frontend
cd frontend && npm run dev   # Vite :5173

# Terminal 3: Electron
cd desktop && npm run dev    # FLOWBOARD_DEV=1, load http://localhost:5173, không spawn agent
```

**Production build (Windows — `scripts/build-desktop.ps1`):**

1. `cd frontend; npm ci; npm run build` → `frontend/dist/`
2. `cd agent; pip install -e .; pip install pyinstaller; pyinstaller flowboard-agent.spec --clean` → `agent/dist/flowboard-agent/`
3. `cd desktop; npm ci; npm run build` → `desktop/dist/`
4. `cd desktop; npx electron-builder --win --x64` → `desktop/release/Flowboard-Setup-x.y.z.exe`

**Production build (macOS — `scripts/build-desktop.sh`):**

Tương tự, bước cuối `npx electron-builder --mac` → `desktop/release/Flowboard-x.y.z.dmg`.

**`electron-builder.yml` (key fields):**

```yaml
appId: ai.flowboard.desktop
productName: Flowboard
directories:
  output: release
files:
  - dist/**/*
extraResources:
  - from: "../frontend/dist"
    to: "frontend"
  - from: "../agent/dist/flowboard-agent"
    to: "agent"
win:
  target: nsis
  icon: assets/icon.ico
mac:
  target: dmg
  icon: assets/icon.icns
  identity: null   # unsigned (internal use)
```

## Error Handling

| Trường hợp | Xử lý |
|-----------|-------|
| Agent binary không tồn tại | Dialog "Installation corrupted, please reinstall" → quit |
| Agent crash khi startup | Dialog với log tail (50 dòng cuối) → "Restart" / "Quit" |
| Port 8101 đã bị chiếm | Detect `EADDRINUSE`, thử port 8102...8110 |
| Health check timeout 30s | Dialog "Agent failed to start. View logs?" |
| Agent crash khi đang chạy | Notification "Agent disconnected. Reconnecting..." → respawn 1 lần |
| Frontend không load được | Auto-reload sau 2s, max 3 lần, rồi show error page |

## Testing Strategy

| Layer | Test type | Cách test |
|-------|-----------|-----------|
| Agent (Python) | Unit + integration | pytest hiện có (333 tests) — không đổi |
| Electron main | Unit | Jest cho `agent-manager.ts` (mock subprocess) |
| End-to-end | Manual smoke | Chạy installer, verify checklist dưới đây |

**Smoke test checklist:**

1. App khởi động, splash hiện ra
2. Agent subprocess spawn thành công (check log)
3. Health check `/api/health` pass trong < 30s
4. Main window load React SPA, không có lỗi console
5. Chrome Extension vẫn connect được WS :9223
6. Tạo board, tạo node, generate request thành công
7. Quit app — agent subprocess tắt sạch (không zombie)
8. Restart app — dữ liệu cũ vẫn còn trong `userData/storage/`

## Scope

### In scope (branch `feat/desktop-app`)

- Tạo `desktop/` (Electron main process, TypeScript)
- Tạo `agent/flowboard-agent.spec` (PyInstaller)
- Build scripts `scripts/build-desktop.ps1` và `.sh`
- Splash + main window, lifecycle, crash recovery
- Native menu cơ bản (Quit, Open Logs, About)
- Cross-platform storage paths
- `electron-builder.yml` cho Win NSIS + macOS DMG (unsigned)
- Smoke test manual trên ít nhất 1 OS
- `desktop/README.md` hướng dẫn build & dev

### Out of scope

- Auto-update (`electron-updater`)
- Code signing / notarization
- Loại bỏ Chrome Extension
- Bundle Claude/Gemini CLI
- System tray, native notifications
- CI/CD GitHub Actions
- Thay đổi frontend code hoặc agent code

## Definition of Done

1. Trên Windows: chạy `scripts/build-desktop.ps1` → output `.exe` installer → install trên máy sạch → app chạy được, generate được 1 request thành công.
2. Trên macOS: chạy `scripts/build-desktop.sh` → output `.dmg` → install → app chạy được.
3. Branch `feat/desktop-app` push lên remote.
4. `desktop/README.md` hướng dẫn rõ cách build + dev.

## Dependencies & Constraints

- **Chrome + Extension vẫn bắt buộc** — không thay đổi
- **PyInstaller không cross-compile** — phải build trên đúng OS
- **Claude/Gemini CLI** — user phải tự cài, không bundle
- **Google Flow account** — user phải có Pro/Ultra plan (như hiện tại)
- **Bundle size dự kiến:** ~250-300MB (installer ~100-150MB)

## Risks

| Risk | Mitigation |
|------|------------|
| PyInstaller miss hidden imports → crash khi runtime | Test kỹ smoke checklist; thêm vào `hiddenimports` khi phát hiện |
| Path resolution khác nhau giữa dev vs production | Dùng `app.isPackaged` để switch logic |
| Port conflict với app khác đang dùng :8101 | Fallback port logic (8102-8110) |
| Agent zombie process khi force quit | Process tree kill (`taskkill /T` Windows, `kill -- -PID` POSIX) |
| Bundle size lớn quá → user khó share | Acceptable cho internal use; có thể dùng `7z` compression sau |
