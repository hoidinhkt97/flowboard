# Flowboard Desktop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package Flowboard (React SPA + FastAPI agent) as a cross-platform desktop application for Windows and macOS, where users can install and run a single binary without needing Python or Docker.

**Architecture:** Electron main process spawns a PyInstaller-bundled FastAPI agent as a subprocess. React SPA is loaded into a `BrowserWindow` and connects to the agent at `localhost:8101`. Chrome Extension dependency is preserved unchanged. Data is stored in OS-standard `userData` directory.

**Tech Stack:**
- **Desktop shell:** Electron 32+, TypeScript 5.x
- **Backend bundling:** PyInstaller 6.x (onedir mode)
- **Packaging:** electron-builder (NSIS for Windows, DMG for macOS)
- **Testing:** vitest for Electron main process unit tests (pure logic only)
- **Existing code (unchanged):** React 18 + Vite 5 frontend, FastAPI + SQLModel agent

**Reference spec:** [docs/superpowers/specs/2026-05-23-desktop-app-design.md](../specs/2026-05-23-desktop-app-design.md)

**Branch:** `feat/desktop-app` (already created)

---

## Task 1: Bootstrap `desktop/` directory and dependencies

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/tsconfig.json`
- Create: `desktop/.gitignore`
- Create: `desktop/vitest.config.ts`

- [ ] **Step 1: Create `desktop/package.json`**

Write to `desktop/package.json`:

```json
{
  "name": "flowboard-desktop",
  "version": "1.2.20",
  "description": "Flowboard desktop wrapper (Electron)",
  "main": "dist/main.js",
  "private": true,
  "scripts": {
    "build": "tsc",
    "dev": "cross-env FLOWBOARD_DEV=1 npm run build && electron .",
    "start": "electron .",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@types/node": "^20.11.0",
    "cross-env": "^7.0.3",
    "electron": "^32.0.0",
    "electron-builder": "^25.0.0",
    "typescript": "^5.6.2",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Create `desktop/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "Node",
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "sourceMap": true,
    "declaration": false
  },
  "include": ["src/**/*"],
  "exclude": ["dist", "node_modules", "src/**/*.test.ts"]
}
```

- [ ] **Step 3: Create `desktop/.gitignore`**

```
node_modules/
dist/
release/
*.log
.DS_Store
```

- [ ] **Step 4: Create `desktop/vitest.config.ts`**

```typescript
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
```

- [ ] **Step 5: Install dependencies**

Run from `desktop/` directory:
```bash
npm install
```

Expected: `node_modules/` created, no errors.

- [ ] **Step 6: Commit**

```bash
git add desktop/package.json desktop/tsconfig.json desktop/.gitignore desktop/vitest.config.ts desktop/package-lock.json
git commit -m "feat(desktop): bootstrap Electron app scaffolding"
```

---

## Task 2: Minimal Electron main process — hello world window

**Files:**
- Create: `desktop/src/main.ts`

- [ ] **Step 1: Create `desktop/src/main.ts`**

```typescript
import { app, BrowserWindow } from 'electron';

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadURL('data:text/html;charset=utf-8,<h1>Flowboard Desktop — bootstrap OK</h1>');
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
```

- [ ] **Step 2: Build TypeScript**

Run from `desktop/`:
```bash
npm run build
```

Expected: `dist/main.js` created, no TS errors.

- [ ] **Step 3: Run Electron**

```bash
npm start
```

Expected: A window opens showing "Flowboard Desktop — bootstrap OK". Close the window.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/main.ts
git commit -m "feat(desktop): minimal Electron main process"
```

---

## Task 3: Splash window

**Files:**
- Create: `desktop/src/window-manager.ts`
- Create: `desktop/assets/splash.html`
- Modify: `desktop/src/main.ts` (full replace)

- [ ] **Step 1: Create `desktop/assets/splash.html`**

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Flowboard</title>
  <style>
    body {
      margin: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #1a1a2e, #16213e);
      color: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    h1 { margin: 0 0 16px; font-size: 32px; }
    .status { font-size: 14px; opacity: 0.7; }
    .spinner {
      margin-top: 24px;
      width: 32px;
      height: 32px;
      border: 3px solid rgba(255,255,255,0.2);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <h1>Flowboard</h1>
  <div class="status" id="status">Starting agent...</div>
  <div class="spinner"></div>
</body>
</html>
```

- [ ] **Step 2: Create `desktop/src/window-manager.ts`**

```typescript
import { BrowserWindow } from 'electron';
import * as path from 'path';

let splashWindow: BrowserWindow | null = null;
let mainWindow: BrowserWindow | null = null;

export function createSplashWindow(): BrowserWindow {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 300,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    transparent: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWindow.loadFile(path.join(__dirname, '..', 'assets', 'splash.html'));
  return splashWindow;
}

export function createMainWindow(url: string): BrowserWindow {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  mainWindow.loadURL(url);
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  return mainWindow;
}

export function closeSplash(): void {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close();
    splashWindow = null;
  }
}

export function getMainWindow(): BrowserWindow | null {
  return mainWindow;
}
```

- [ ] **Step 3: Replace `desktop/src/main.ts`**

```typescript
import { app, BrowserWindow } from 'electron';
import { createSplashWindow, createMainWindow, closeSplash } from './window-manager';

app.whenReady().then(async () => {
  createSplashWindow();

  // Simulate agent boot delay for now (Task 10 will replace with real wait)
  await new Promise((r) => setTimeout(r, 2000));

  createMainWindow('data:text/html;charset=utf-8,<h1>Main window</h1>');
  closeSplash();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
```

- [ ] **Step 4: Build and run**

```bash
npm run build && npm start
```

Expected: splash window with spinner shows for 2s, then main window appears, splash closes.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/window-manager.ts desktop/src/main.ts desktop/assets/splash.html
git commit -m "feat(desktop): splash window with spinner"
```

---

## Task 4: Pure logic — `resolveAgentBinaryPath` (TDD)

**Files:**
- Create: `desktop/src/paths.ts`
- Create: `desktop/src/paths.test.ts`

- [ ] **Step 1: Write failing test in `desktop/src/paths.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { resolveAgentBinaryPath } from './paths';

describe('resolveAgentBinaryPath', () => {
  it('returns .exe path on Windows in packaged mode', () => {
    const result = resolveAgentBinaryPath({
      platform: 'win32',
      isPackaged: true,
      resourcesPath: 'C:\\Program Files\\Flowboard\\resources',
      appPath: 'C:\\Program Files\\Flowboard\\resources\\app',
    });
    expect(result).toBe('C:\\Program Files\\Flowboard\\resources\\agent\\flowboard-agent.exe');
  });

  it('returns binary without extension on macOS in packaged mode', () => {
    const result = resolveAgentBinaryPath({
      platform: 'darwin',
      isPackaged: true,
      resourcesPath: '/Applications/Flowboard.app/Contents/Resources',
      appPath: '/Applications/Flowboard.app/Contents/Resources/app',
    });
    expect(result).toBe('/Applications/Flowboard.app/Contents/Resources/agent/flowboard-agent');
  });

  it('returns dev path when not packaged', () => {
    const result = resolveAgentBinaryPath({
      platform: 'win32',
      isPackaged: false,
      resourcesPath: '',
      appPath: 'D:\\Workspace\\flowboard-ai\\desktop',
    });
    expect(result).toBe('D:\\Workspace\\flowboard-ai\\agent\\dist\\flowboard-agent\\flowboard-agent.exe');
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

```bash
npm test
```

Expected: FAIL with "Cannot find module './paths'".

- [ ] **Step 3: Implement `desktop/src/paths.ts`**

```typescript
import * as path from 'path';

export interface PathContext {
  platform: NodeJS.Platform;
  isPackaged: boolean;
  resourcesPath: string;
  appPath: string;
}

export function resolveAgentBinaryPath(ctx: PathContext): string {
  const ext = ctx.platform === 'win32' ? '.exe' : '';
  const binaryName = `flowboard-agent${ext}`;

  if (ctx.isPackaged) {
    return path.join(ctx.resourcesPath, 'agent', binaryName);
  }

  // Dev mode: <repo>/agent/dist/flowboard-agent/<binaryName>
  // appPath in dev = <repo>/desktop, so go up one level to repo root
  const repoRoot = path.resolve(ctx.appPath, '..');
  return path.join(repoRoot, 'agent', 'dist', 'flowboard-agent', binaryName);
}

export function getFrontendUrl(ctx: PathContext): string {
  if (ctx.isPackaged) {
    const indexHtml = path.join(ctx.resourcesPath, 'frontend', 'index.html');
    return `file://${indexHtml}`;
  }
  return 'http://127.0.0.1:8101/app/';
}
```

- [ ] **Step 4: Run test, verify it passes**

```bash
npm test
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/paths.ts desktop/src/paths.test.ts
git commit -m "feat(desktop): path resolution for agent binary and frontend URL"
```

---

## Task 5: Pure logic — `findAvailablePort` (TDD)

**Files:**
- Create: `desktop/src/port-finder.ts`
- Create: `desktop/src/port-finder.test.ts`

- [ ] **Step 1: Write failing test in `desktop/src/port-finder.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import * as net from 'net';
import { findAvailablePort } from './port-finder';

function occupyPort(port: number): Promise<net.Server> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

describe('findAvailablePort', () => {
  it('returns the first port if it is free', async () => {
    const port = await findAvailablePort(18101, 18110);
    expect(port).toBe(18101);
  });

  it('skips occupied ports and returns the next free one', async () => {
    const blocker = await occupyPort(18201);
    try {
      const port = await findAvailablePort(18201, 18210);
      expect(port).toBe(18202);
    } finally {
      blocker.close();
    }
  });

  it('throws when no port is available in range', async () => {
    const b1 = await occupyPort(18301);
    const b2 = await occupyPort(18302);
    try {
      await expect(findAvailablePort(18301, 18302)).rejects.toThrow(/no available port/i);
    } finally {
      b1.close();
      b2.close();
    }
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

```bash
npm test port-finder
```

Expected: FAIL with "Cannot find module './port-finder'".

- [ ] **Step 3: Implement `desktop/src/port-finder.ts`**

```typescript
import * as net from 'net';

export function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

export async function findAvailablePort(start: number, end: number): Promise<number> {
  for (let p = start; p <= end; p++) {
    if (await isPortAvailable(p)) return p;
  }
  throw new Error(`No available port in range ${start}-${end}`);
}
```

- [ ] **Step 4: Run test, verify it passes**

```bash
npm test
```

Expected: all tests PASS (paths + port-finder).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/port-finder.ts desktop/src/port-finder.test.ts
git commit -m "feat(desktop): port-finder with fallback range"
```

---

## Task 6: Pure logic — `readLogTail` (TDD)

**Files:**
- Create: `desktop/src/log-tail.ts`
- Create: `desktop/src/log-tail.test.ts`

- [ ] **Step 1: Write failing test in `desktop/src/log-tail.test.ts`**

```typescript
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { readLogTail } from './log-tail';

describe('readLogTail', () => {
  let tmpFile: string;

  beforeEach(() => {
    tmpFile = path.join(os.tmpdir(), `flowboard-test-${Date.now()}-${Math.random()}.log`);
  });

  afterEach(() => {
    if (fs.existsSync(tmpFile)) fs.unlinkSync(tmpFile);
  });

  it('returns empty string if file does not exist', async () => {
    const result = await readLogTail('/nonexistent/path.log', 10);
    expect(result).toBe('');
  });

  it('returns last N lines of a multi-line file', async () => {
    const lines = Array.from({ length: 100 }, (_, i) => `line ${i + 1}`).join('\n');
    fs.writeFileSync(tmpFile, lines);

    const result = await readLogTail(tmpFile, 5);
    const resultLines = result.split('\n').filter(Boolean);
    expect(resultLines).toEqual(['line 96', 'line 97', 'line 98', 'line 99', 'line 100']);
  });

  it('returns entire file if fewer lines than requested', async () => {
    fs.writeFileSync(tmpFile, 'a\nb\nc');
    const result = await readLogTail(tmpFile, 50);
    expect(result.trim()).toBe('a\nb\nc');
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

```bash
npm test log-tail
```

Expected: FAIL with "Cannot find module".

- [ ] **Step 3: Implement `desktop/src/log-tail.ts`**

```typescript
import * as fs from 'fs/promises';

export async function readLogTail(filePath: string, lineCount: number): Promise<string> {
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    const lines = content.split('\n');
    return lines.slice(-lineCount).join('\n');
  } catch (err: unknown) {
    const e = err as NodeJS.ErrnoException;
    if (e.code === 'ENOENT') return '';
    throw err;
  }
}
```

- [ ] **Step 4: Run test, verify it passes**

```bash
npm test
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/log-tail.ts desktop/src/log-tail.test.ts
git commit -m "feat(desktop): log-tail utility for crash diagnostics"
```

---

## Task 7: Pure logic — `waitForHealth` (TDD)

**Files:**
- Create: `desktop/src/health-check.ts`
- Create: `desktop/src/health-check.test.ts`

- [ ] **Step 1: Write failing test in `desktop/src/health-check.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import * as http from 'http';
import { waitForHealth } from './health-check';

function startMockServer(port: number, responder: (req: http.IncomingMessage, res: http.ServerResponse) => void): http.Server {
  const server = http.createServer(responder);
  server.listen(port, '127.0.0.1');
  return server;
}

describe('waitForHealth', () => {
  it('resolves true when health endpoint returns ok', async () => {
    const server = startMockServer(19101, (_, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    });
    try {
      const result = await waitForHealth('http://127.0.0.1:19101/api/health', { timeoutMs: 3000, intervalMs: 100 });
      expect(result).toBe(true);
    } finally {
      server.close();
    }
  });

  it('resolves false when timeout exceeded with no server', async () => {
    const result = await waitForHealth('http://127.0.0.1:19102/api/health', { timeoutMs: 500, intervalMs: 100 });
    expect(result).toBe(false);
  });

  it('keeps polling on connection refused, resolves when server becomes available', async () => {
    let server: http.Server | null = null;
    setTimeout(() => {
      server = startMockServer(19103, (_, res) => {
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true }));
      });
    }, 300);

    const result = await waitForHealth('http://127.0.0.1:19103/api/health', { timeoutMs: 2000, intervalMs: 100 });
    expect(result).toBe(true);
    server?.close();
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

```bash
npm test health-check
```

Expected: FAIL "Cannot find module".

- [ ] **Step 3: Implement `desktop/src/health-check.ts`**

```typescript
import * as http from 'http';

export interface HealthCheckOptions {
  timeoutMs: number;
  intervalMs: number;
}

function probe(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 1500 }, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          resolve(res.statusCode === 200 && json.ok === true);
        } catch {
          resolve(false);
        }
      });
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

export async function waitForHealth(url: string, opts: HealthCheckOptions): Promise<boolean> {
  const deadline = Date.now() + opts.timeoutMs;
  while (Date.now() < deadline) {
    if (await probe(url)) return true;
    await new Promise((r) => setTimeout(r, opts.intervalMs));
  }
  return false;
}
```

- [ ] **Step 4: Run test, verify it passes**

```bash
npm test
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/health-check.ts desktop/src/health-check.test.ts
git commit -m "feat(desktop): health-check polling utility"
```

---

## Task 8: Agent manager — process spawning

**Files:**
- Create: `desktop/src/agent-manager.ts`

> Note: No unit test for this module — it integrates Node `child_process` + filesystem + Electron app paths. Verified via Task 11 (dev mode) and Task 14 (production smoke test).

- [ ] **Step 1: Create `desktop/src/agent-manager.ts`**

```typescript
import { spawn, ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { findAvailablePort } from './port-finder';
import { waitForHealth } from './health-check';

export interface AgentConfig {
  binaryPath: string;
  storageDir: string;
  logsDir: string;
  startPort: number;
  endPort: number;
  wsPort: number;
}

export interface AgentStatus {
  running: boolean;
  httpPort: number | null;
  pid: number | null;
}

export class AgentManager {
  private process: ChildProcess | null = null;
  private httpPort: number | null = null;
  private logStream: fs.WriteStream | null = null;
  private intentionalShutdown = false;
  private onCrash: (() => void) | null = null;

  async start(config: AgentConfig): Promise<{ httpPort: number }> {
    if (this.process) throw new Error('Agent already running');

    if (!fs.existsSync(config.binaryPath)) {
      throw new Error(`Agent binary not found at ${config.binaryPath}`);
    }

    fs.mkdirSync(config.storageDir, { recursive: true });
    fs.mkdirSync(config.logsDir, { recursive: true });

    const httpPort = await findAvailablePort(config.startPort, config.endPort);
    this.httpPort = httpPort;

    const logPath = path.join(config.logsDir, 'agent.log');
    this.logStream = fs.createWriteStream(logPath, { flags: 'a' });
    this.logStream.write(`\n=== Agent start ${new Date().toISOString()} (port ${httpPort}) ===\n`);

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      FLOWBOARD_STORAGE: config.storageDir,
      FLOWBOARD_HTTP_PORT: String(httpPort),
      FLOWBOARD_EXT_WS_PORT: String(config.wsPort),
      FLOWBOARD_WS_HOST: '127.0.0.1',
      PYTHONUNBUFFERED: '1',
    };

    this.process = spawn(config.binaryPath, [], {
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false,
    });

    this.process.stdout?.pipe(this.logStream, { end: false });
    this.process.stderr?.pipe(this.logStream, { end: false });

    this.process.once('exit', (code, signal) => {
      this.logStream?.write(`=== Agent exit code=${code} signal=${signal} ===\n`);
      const wasIntentional = this.intentionalShutdown;
      this.process = null;
      this.httpPort = null;
      this.intentionalShutdown = false;
      if (!wasIntentional && this.onCrash) this.onCrash();
    });

    const healthy = await waitForHealth(`http://127.0.0.1:${httpPort}/api/health`, {
      timeoutMs: 30_000,
      intervalMs: 500,
    });

    if (!healthy) {
      await this.shutdown();
      throw new Error('Agent failed to become healthy within 30s');
    }

    return { httpPort };
  }

  async shutdown(): Promise<void> {
    if (!this.process) return;
    this.intentionalShutdown = true;

    const pid = this.process.pid;
    const exited = new Promise<void>((resolve) => {
      this.process?.once('exit', () => resolve());
    });

    if (process.platform === 'win32' && pid) {
      // Use taskkill /T to kill the process tree (PyInstaller bootloader spawns child)
      spawn('taskkill', ['/PID', String(pid), '/T', '/F']);
    } else {
      this.process.kill('SIGTERM');
    }

    // Wait up to 5 seconds for graceful exit, then force-kill
    const timeout = new Promise<void>((resolve) =>
      setTimeout(() => {
        this.process?.kill('SIGKILL');
        resolve();
      }, 5000)
    );

    await Promise.race([exited, timeout]);
    this.logStream?.end();
    this.logStream = null;
  }

  setCrashHandler(handler: () => void): void {
    this.onCrash = handler;
  }

  getStatus(): AgentStatus {
    return {
      running: this.process !== null,
      httpPort: this.httpPort,
      pid: this.process?.pid ?? null,
    };
  }
}
```

- [ ] **Step 2: Build to verify TypeScript compiles**

```bash
npm run build
```

Expected: `dist/agent-manager.js` created, no errors.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/agent-manager.ts
git commit -m "feat(desktop): agent subprocess manager"
```

---

## Task 9: Native menu

**Files:**
- Create: `desktop/src/menu.ts`

- [ ] **Step 1: Create `desktop/src/menu.ts`**

```typescript
import { Menu, MenuItemConstructorOptions, shell, app, dialog } from 'electron';

export function buildMenu(logsDir: string): Menu {
  const isMac = process.platform === 'darwin';

  const template: MenuItemConstructorOptions[] = [
    ...(isMac
      ? ([
          {
            label: app.name,
            submenu: [
              { role: 'about' },
              { type: 'separator' },
              { role: 'services' },
              { type: 'separator' },
              { role: 'hide' },
              { role: 'hideOthers' },
              { role: 'unhide' },
              { type: 'separator' },
              { role: 'quit' },
            ],
          },
        ] as MenuItemConstructorOptions[])
      : []),
    {
      label: 'File',
      submenu: [isMac ? { role: 'close' } : { role: 'quit' }],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Open Logs Folder',
          click: () => { void shell.openPath(logsDir); },
        },
        {
          label: 'About Flowboard',
          click: () => {
            void dialog.showMessageBox({
              type: 'info',
              title: 'About Flowboard',
              message: `Flowboard Desktop v${app.getVersion()}`,
              detail: 'Local infinite-canvas workspace for AI-driven media workflows.',
            });
          },
        },
      ],
    },
  ];

  return Menu.buildFromTemplate(template);
}
```

- [ ] **Step 2: Build**

```bash
npm run build
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/menu.ts
git commit -m "feat(desktop): native menu with logs folder and about"
```

---

## Task 10: Wire up full lifecycle in `main.ts`

**Files:**
- Modify: `desktop/src/main.ts` (full replace)

- [ ] **Step 1: Replace `desktop/src/main.ts`**

```typescript
import { app, BrowserWindow, dialog, Menu } from 'electron';
import * as path from 'path';
import { AgentManager } from './agent-manager';
import { resolveAgentBinaryPath, getFrontendUrl } from './paths';
import { readLogTail } from './log-tail';
import { createSplashWindow, createMainWindow, closeSplash } from './window-manager';
import { buildMenu } from './menu';

const isDev = process.env.FLOWBOARD_DEV === '1';
const agentManager = new AgentManager();

let isQuitting = false;

function getPathContext() {
  return {
    platform: process.platform,
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    appPath: app.getAppPath(),
  };
}

function getStorageDir(): string {
  return path.join(app.getPath('userData'), 'storage');
}

function getLogsDir(): string {
  return path.join(app.getPath('userData'), 'logs');
}

async function showStartupError(message: string, detail: string): Promise<void> {
  await dialog.showMessageBox({
    type: 'error',
    title: 'Flowboard — startup error',
    message,
    detail,
    buttons: ['Quit'],
  });
}

async function startup(): Promise<void> {
  createSplashWindow();

  const logsDir = getLogsDir();
  Menu.setApplicationMenu(buildMenu(logsDir));

  let httpPort: number;
  try {
    if (isDev) {
      httpPort = 8101;
      console.log('[dev] Skipping agent spawn, expecting agent on port 8101');
    } else {
      const binaryPath = resolveAgentBinaryPath(getPathContext());
      const result = await agentManager.start({
        binaryPath,
        storageDir: getStorageDir(),
        logsDir,
        startPort: 8101,
        endPort: 8110,
        wsPort: 9223,
      });
      httpPort = result.httpPort;
    }
  } catch (err) {
    const tail = await readLogTail(path.join(logsDir, 'agent.log'), 50);
    await showStartupError(
      'Failed to start Flowboard agent',
      `${(err as Error).message}\n\nLast 50 log lines:\n${tail || '(no log)'}`
    );
    app.exit(1);
    return;
  }

  agentManager.setCrashHandler(() => {
    if (isQuitting) return;
    void dialog.showMessageBox({
      type: 'warning',
      title: 'Flowboard',
      message: 'Agent disconnected',
      detail: 'The Flowboard agent stopped unexpectedly. Restart the app to continue.',
      buttons: ['Quit'],
    }).then(() => app.quit());
  });

  const ctx = getPathContext();
  const frontendUrl = isDev
    ? `http://127.0.0.1:${httpPort}/app/`
    : getFrontendUrl(ctx);

  createMainWindow(frontendUrl);
  closeSplash();
}

app.whenReady().then(startup);

app.on('before-quit', async (e) => {
  if (isQuitting) return;
  isQuitting = true;
  e.preventDefault();
  try {
    await agentManager.shutdown();
  } catch (err) {
    console.error('Error during agent shutdown:', err);
  }
  app.exit(0);
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0 && !isQuitting) {
    const status = agentManager.getStatus();
    if (status.running && status.httpPort) {
      createMainWindow(`http://127.0.0.1:${status.httpPort}/app/`);
    }
  }
});
```

- [ ] **Step 2: Build**

```bash
npm run build
```

Expected: no TS errors.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main.ts
git commit -m "feat(desktop): wire agent manager into Electron lifecycle"
```

---

## Task 11: Serve frontend from the agent

> Background: The Electron app loads the frontend from `http://127.0.0.1:<port>/app/` in dev mode and from `file://` in packaged mode. To unify the dev experience and avoid CORS, we mount the frontend's `dist/` directory as static files on the agent.

**Files:**
- Modify: `agent/flowboard/main.py`

- [ ] **Step 1: Inspect current `agent/flowboard/main.py`**

Read the file to find where routers are included and where `/api/health` is defined. The mount should go after all `app.include_router(...)` calls and before `@app.get("/api/health")`.

- [ ] **Step 2: Add static file mount for frontend**

In `agent/flowboard/main.py`, after the last `app.include_router(activity.router)` line and before the `@app.get("/api/health")` decorator, insert:

```python
# Mount frontend static files if frontend/dist exists (desktop app deployment)
from pathlib import Path as _Path
import os as _os
from fastapi.staticfiles import StaticFiles as _StaticFiles

_frontend_dist = _os.getenv("FLOWBOARD_FRONTEND_DIST")
if _frontend_dist:
    _frontend_path = _Path(_frontend_dist)
else:
    _frontend_path = _Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _frontend_path.exists() and (_frontend_path / "index.html").exists():
    app.mount("/app", _StaticFiles(directory=str(_frontend_path), html=True), name="frontend")
    logger.info("mounted frontend static files from %s", _frontend_path)
else:
    logger.info("frontend dist not found at %s (skipping static mount)", _frontend_path)
```

- [ ] **Step 3: Build frontend**

```bash
cd frontend
npm install
npm run build
```

Expected: `frontend/dist/index.html` created.

- [ ] **Step 4: Run agent and verify `/app/` serves**

In a terminal:
```bash
cd agent
uvicorn flowboard.main:app --port 8101
```

Verify log shows: `mounted frontend static files from ...`

Then in browser open `http://127.0.0.1:8101/app/`.

Expected: the React SPA loads.

- [ ] **Step 5: Verify in Electron dev mode**

In `desktop/`:
```bash
npm run dev
```

Expected: Splash → main window opens the full Flowboard React UI.

- [ ] **Step 6: Commit**

```bash
git add agent/flowboard/main.py
git commit -m "feat(agent): mount frontend static files at /app for desktop deployment"
```

---

## Task 12: PyInstaller entry point and spec

**Files:**
- Create: `agent/flowboard/__main__.py`
- Create: `agent/flowboard-agent.spec`
- Create or modify: `agent/.gitignore`

- [ ] **Step 1: Create `agent/flowboard/__main__.py`**

```python
"""Entry point for the bundled desktop agent.

PyInstaller uses this as the main module. Calls uvicorn programmatically
instead of going through the CLI so we don't depend on its argv parser.
"""
import uvicorn

from flowboard.config import HTTP_PORT


def main() -> None:
    uvicorn.run(
        "flowboard.main:app",
        host="127.0.0.1",
        port=HTTP_PORT,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `agent/flowboard-agent.spec`**

```python
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for flowboard-agent.
# Build: pyinstaller flowboard-agent.spec --clean

block_cipher = None

a = Analysis(
    ['flowboard/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # uvicorn dynamic imports
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # sqlmodel / sqlalchemy
        'sqlmodel',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.sqlite.pysqlite',
        # websockets
        'websockets.legacy',
        'websockets.legacy.server',
        # flowboard routes (force include in case PyInstaller misses dynamic imports)
        'flowboard.routes.activity',
        'flowboard.routes.auth',
        'flowboard.routes.boards',
        'flowboard.routes.chat',
        'flowboard.routes.edges',
        'flowboard.routes.flow_projects',
        'flowboard.routes.llm',
        'flowboard.routes.media',
        'flowboard.routes.nodes',
        'flowboard.routes.plans',
        'flowboard.routes.projects',
        'flowboard.routes.prompt',
        'flowboard.routes.upload',
        'flowboard.routes.vision',
        'flowboard.routes.references',
        'flowboard.routes.requests',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy.tests', 'IPython', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='flowboard-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='flowboard-agent',
)
```

- [ ] **Step 3: Ensure `agent/.gitignore` excludes build artifacts**

Read `agent/.gitignore` if it exists. Add these lines if missing:
```
dist/
build/
test-storage/
```

If the file doesn't exist, create it:
```
__pycache__/
*.pyc
.pytest_cache/
dist/
build/
*.egg-info/
test-storage/
```

- [ ] **Step 4: Install PyInstaller**

```bash
cd agent
pip install pyinstaller
```

Expected: `pyinstaller` available in venv.

- [ ] **Step 5: Build the agent binary**

```bash
cd agent
pyinstaller flowboard-agent.spec --clean
```

Expected: `agent/dist/flowboard-agent/flowboard-agent[.exe]` created. Build takes 30-90 seconds.

- [ ] **Step 6: Smoke-test the binary directly**

Windows (PowerShell):
```powershell
cd agent\dist\flowboard-agent
$env:FLOWBOARD_STORAGE = "$PWD\test-storage"
.\flowboard-agent.exe
```

macOS / Linux:
```bash
cd agent/dist/flowboard-agent
FLOWBOARD_STORAGE="$PWD/test-storage" ./flowboard-agent
```

Expected: agent logs "flowboard agent started" and listens on :8101.

In another terminal:
```bash
curl http://127.0.0.1:8101/api/health
```

Expected: `{"ok": true, ...}`.

Stop the binary (Ctrl-C). Delete `agent/dist/flowboard-agent/test-storage`.

> If `ModuleNotFoundError` occurs at runtime, add the missing module to `hiddenimports` in `flowboard-agent.spec` and rebuild.

- [ ] **Step 7: Commit**

```bash
git add agent/flowboard-agent.spec agent/flowboard/__main__.py agent/.gitignore
git commit -m "feat(agent): PyInstaller spec and __main__ entry point"
```

---

## Task 13: Verify production-mode Electron with bundled agent

**Files:** none (integration verification)

> Prereqs: Frontend built (`frontend/dist/index.html` exists), agent binary built (`agent/dist/flowboard-agent/flowboard-agent[.exe]` exists). Both completed in Task 11 and Task 12.

- [ ] **Step 1: Ensure `FLOWBOARD_DEV` is NOT set**

PowerShell:
```powershell
Remove-Item Env:FLOWBOARD_DEV -ErrorAction SilentlyContinue
```

Bash:
```bash
unset FLOWBOARD_DEV
```

- [ ] **Step 2: Build and run Electron in production-like mode (unpackaged but spawning binary)**

```bash
cd desktop
npm run build
npm start
```

Expected:
- Splash window appears
- Console logs show `Agent start ... (port 8101)`
- Within ~5 seconds, health check passes
- Main window opens, loads `http://127.0.0.1:8101/app/`, shows the Flowboard SPA
- Quit via File menu → splash gone, agent process killed

- [ ] **Step 3: Verify storage location**

After running, check userData storage:

PowerShell:
```powershell
Get-ChildItem "$env:APPDATA\flowboard-desktop\storage"
```

macOS:
```bash
ls ~/Library/Application\ Support/flowboard-desktop/storage
```

Expected: `flowboard.db` exists.

- [ ] **Step 4: Verify no zombie agent process**

Right after closing the app:

Windows:
```powershell
Get-Process flowboard-agent -ErrorAction SilentlyContinue
```

macOS / Linux:
```bash
ps aux | grep flowboard-agent | grep -v grep
```

Expected: no output (no zombie process).

- [ ] **Step 5: Commit milestone**

```bash
git commit --allow-empty -m "chore(desktop): production-path smoke test passed"
```

---

## Task 14: electron-builder configuration

**Files:**
- Create: `desktop/electron-builder.yml`
- Create: `desktop/assets/icon.png` (placeholder 512x512 PNG)
- Modify: `desktop/package.json` (add `dist:win` and `dist:mac` scripts)

- [ ] **Step 1: Create `desktop/electron-builder.yml`**

```yaml
appId: ai.flowboard.desktop
productName: Flowboard
copyright: Copyright © 2026 Flowboard
directories:
  output: release
  buildResources: assets

files:
  - dist/**/*
  - assets/**/*
  - package.json
  - "!**/*.test.*"
  - "!**/*.map"

extraResources:
  - from: "../frontend/dist"
    to: "frontend"
    filter: ["**/*"]
  - from: "../agent/dist/flowboard-agent"
    to: "agent"
    filter: ["**/*"]

asar: true
asarUnpack: []

win:
  target:
    - target: nsis
      arch: [x64]
  icon: assets/icon.png

nsis:
  oneClick: false
  perMachine: false
  allowToChangeInstallationDirectory: true
  artifactName: "Flowboard-Setup-${version}.${ext}"

mac:
  target:
    - target: dmg
      arch: [x64, arm64]
  icon: assets/icon.png
  identity: null
  category: public.app-category.graphics-design
  artifactName: "Flowboard-${version}-${arch}.${ext}"

dmg:
  title: "Flowboard ${version}"
```

- [ ] **Step 2: Create placeholder icon at `desktop/assets/icon.png`**

The icon must be a 512x512 PNG. Any solid-color or simple image works as a placeholder. electron-builder will auto-generate `.ico` (Windows) and `.icns` (macOS) at packaging time.

Quick options to create one:

Windows PowerShell with ImageMagick:
```powershell
magick -size 512x512 xc:"#1a1a2e" desktop\assets\icon.png
```

macOS with ImageMagick:
```bash
magick -size 512x512 xc:"#1a1a2e" desktop/assets/icon.png
```

Or copy any existing 512x512 PNG into `desktop/assets/icon.png`. Replace with the real logo before any non-internal release.

- [ ] **Step 3: Modify `desktop/package.json` scripts section**

Add `dist:win` and `dist:mac` to the `scripts` object. The final `scripts` block should be:

```json
{
  "scripts": {
    "build": "tsc",
    "dev": "cross-env FLOWBOARD_DEV=1 npm run build && electron .",
    "start": "electron .",
    "test": "vitest run",
    "test:watch": "vitest",
    "dist:win": "electron-builder --win --x64",
    "dist:mac": "electron-builder --mac"
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add desktop/electron-builder.yml desktop/assets/icon.png desktop/package.json
git commit -m "feat(desktop): electron-builder config for Win NSIS and macOS DMG"
```

---

## Task 15: Windows build script

**Files:**
- Create: `scripts/build-desktop.ps1`

- [ ] **Step 1: Create `scripts/build-desktop.ps1`**

```powershell
#!/usr/bin/env pwsh
# Build the Flowboard desktop app for Windows.
# Output: desktop\release\Flowboard-Setup-<version>.exe

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

Write-Host "=== Flowboard desktop build (Windows) ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

# Step 1: Build frontend
Write-Host "`n[1/4] Building frontend..." -ForegroundColor Yellow
Set-Location (Join-Path $RepoRoot 'frontend')
npm ci
npm run build
if (-not (Test-Path 'dist/index.html')) {
    throw "Frontend build failed: dist/index.html not found"
}

# Step 2: Build agent binary
Write-Host "`n[2/4] Building Python agent (PyInstaller)..." -ForegroundColor Yellow
Set-Location (Join-Path $RepoRoot 'agent')
pip install -e . --quiet
pip install pyinstaller --quiet
pyinstaller flowboard-agent.spec --clean --noconfirm
if (-not (Test-Path 'dist\flowboard-agent\flowboard-agent.exe')) {
    throw "Agent build failed: flowboard-agent.exe not found"
}

# Step 3: Compile Electron TypeScript
Write-Host "`n[3/4] Compiling Electron TypeScript..." -ForegroundColor Yellow
Set-Location (Join-Path $RepoRoot 'desktop')
npm ci
npm run build
if (-not (Test-Path 'dist\main.js')) {
    throw "Electron TS build failed: dist\main.js not found"
}

# Step 4: Package with electron-builder
Write-Host "`n[4/4] Packaging with electron-builder..." -ForegroundColor Yellow
npm run dist:win

$installer = Get-ChildItem 'release\*.exe' | Select-Object -First 1
if ($installer) {
    Write-Host "`n=== Build complete ===" -ForegroundColor Green
    Write-Host "Installer: $($installer.FullName)" -ForegroundColor Green
    Write-Host "Size: $([math]::Round($installer.Length / 1MB, 1)) MB"
} else {
    throw "electron-builder did not produce an installer"
}
```

- [ ] **Step 2: Commit**

```bash
git add scripts/build-desktop.ps1
git commit -m "feat(desktop): Windows build script"
```

- [ ] **Step 3: (Windows only) Run the script**

```powershell
.\scripts\build-desktop.ps1
```

Expected: 4 steps run sequentially, ends with "Build complete", installer at `desktop\release\Flowboard-Setup-1.2.20.exe`.

If a step fails: fix the underlying issue (commonly missing hidden import in PyInstaller spec) and rerun.

- [ ] **Step 4: Install and smoke-test the produced installer**

Double-click `Flowboard-Setup-1.2.20.exe`, complete the installer wizard, launch from Start Menu.

Run this smoke test checklist:

1. App opens, splash hides after agent ready
2. Main window loads Flowboard UI (no console errors)
3. Open Chrome Extension — verify it connects to `ws://127.0.0.1:9223`
4. Create a board, add a node
5. Submit a generation request — verify it completes
6. Quit via File menu
7. Verify no zombie `flowboard-agent.exe` process (`Get-Process flowboard-agent`)
8. Re-launch — verify previous board is restored

If all pass, commit a milestone:
```bash
git commit --allow-empty -m "chore(desktop): Windows installer smoke test passed"
```

---

## Task 16: macOS build script

**Files:**
- Create: `scripts/build-desktop.sh`

- [ ] **Step 1: Create `scripts/build-desktop.sh`**

```bash
#!/usr/bin/env bash
# Build the Flowboard desktop app for macOS.
# Output: desktop/release/Flowboard-<version>-<arch>.dmg

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Flowboard desktop build (macOS) ==="
echo "Repo: $REPO_ROOT"

# Step 1: Build frontend
echo ""
echo "[1/4] Building frontend..."
cd "$REPO_ROOT/frontend"
npm ci
npm run build
test -f dist/index.html || { echo "Frontend build failed"; exit 1; }

# Step 2: Build agent binary
echo ""
echo "[2/4] Building Python agent (PyInstaller)..."
cd "$REPO_ROOT/agent"
pip install -e . --quiet
pip install pyinstaller --quiet
pyinstaller flowboard-agent.spec --clean --noconfirm
test -f dist/flowboard-agent/flowboard-agent || { echo "Agent build failed"; exit 1; }

# Step 3: Compile Electron TypeScript
echo ""
echo "[3/4] Compiling Electron TypeScript..."
cd "$REPO_ROOT/desktop"
npm ci
npm run build
test -f dist/main.js || { echo "Electron TS build failed"; exit 1; }

# Step 4: Package with electron-builder
echo ""
echo "[4/4] Packaging with electron-builder..."
npm run dist:mac

dmg=$(ls release/*.dmg 2>/dev/null | head -n1)
if [[ -z "$dmg" ]]; then
    echo "electron-builder did not produce a DMG"
    exit 1
fi

echo ""
echo "=== Build complete ==="
echo "DMG: $dmg"
echo "Size: $(du -h "$dmg" | cut -f1)"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/build-desktop.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/build-desktop.sh
git commit -m "feat(desktop): macOS build script"
```

- [ ] **Step 4: (macOS only) Run the script**

```bash
./scripts/build-desktop.sh
```

Expected: build completes, DMG at `desktop/release/Flowboard-1.2.20-<arch>.dmg`.

- [ ] **Step 5: (macOS only) Install and smoke test**

Open the DMG, drag Flowboard.app to Applications, launch.

> macOS will block the unsigned app on first launch. User must right-click → Open → confirm in the security dialog. Expected for internal use (no notarization).

Run the same 8-item smoke test checklist as Task 15 Step 4 (use `ps aux | grep flowboard-agent` instead of PowerShell).

If all pass:
```bash
git commit --allow-empty -m "chore(desktop): macOS installer smoke test passed"
```

---

## Task 17: Documentation

**Files:**
- Create: `desktop/README.md`

- [ ] **Step 1: Create `desktop/README.md`**

````markdown
# Flowboard Desktop

Electron wrapper that packages Flowboard (React SPA + FastAPI agent) into a cross-platform desktop application for Windows and macOS.

## Architecture

```
Electron main process
├── Spawns flowboard-agent (PyInstaller-bundled FastAPI) on localhost:8101
├── Opens splash window during startup
├── Opens main BrowserWindow loading http://127.0.0.1:8101/app/
└── Forwards agent stdout/stderr to userData/logs/agent.log
```

The Chrome Extension dependency is preserved — users still install the extension as before for Google Flow auth.

## Data Storage

User data (SQLite DB + media) is stored at:

| OS      | Path                                                       |
|---------|------------------------------------------------------------|
| Windows | `%APPDATA%\flowboard-desktop\storage\`                     |
| macOS   | `~/Library/Application Support/flowboard-desktop/storage/` |

Logs at the same parent path under `logs/`.

## Development

Run the agent, frontend, and Electron separately:

```bash
# Terminal 1: agent
cd agent
uvicorn flowboard.main:app --reload --port 8101

# Terminal 2: frontend (build once; rebuild on UI changes)
cd frontend
npm run build   # served by agent at /app/

# Terminal 3: Electron
cd desktop
npm run dev     # sets FLOWBOARD_DEV=1, skips agent spawn
```

`FLOWBOARD_DEV=1` makes Electron skip spawning the agent binary and assume the agent is already running on port 8101.

## Production Build

### Windows

```powershell
.\scripts\build-desktop.ps1
```

Output: `desktop\release\Flowboard-Setup-<version>.exe`

### macOS

```bash
./scripts/build-desktop.sh
```

Output: `desktop/release/Flowboard-<version>-<arch>.dmg`

> PyInstaller does not cross-compile. Windows binaries must be built on Windows; macOS binaries must be built on macOS.

## Testing

```bash
cd desktop
npm test       # vitest unit tests: paths, port-finder, log-tail, health-check
```

Smoke testing the built installer is manual — see the checklist in Task 15 / 16 of the implementation plan.

## Bundle Size

Approximate:
- Electron framework: ~150 MB
- PyInstaller agent (onedir): ~80-120 MB
- Frontend dist: ~5 MB
- Total installed: ~250-300 MB
- Installer size: ~100-150 MB

## Troubleshooting

**"Agent failed to start within 30s"**
- Check `userData/logs/agent.log` for Python errors
- Common cause: missing `hiddenimports` in `agent/flowboard-agent.spec`. Add the failing module and rebuild.

**Zombie agent process after quit**
- On Windows: ensure `taskkill /T` runs (process tree kill — `AgentManager.shutdown` does this)
- On POSIX: SIGTERM then SIGKILL after 5s

**Port 8101 already in use**
- The app tries 8101 → 8110 automatically. If all blocked, free one or change `startPort`/`endPort` in `main.ts`.

**Chrome Extension can't connect**
- Verify agent is running: `curl http://127.0.0.1:8101/api/health`
- Verify extension WS port is open: agent log should show "extension WS listening on 127.0.0.1:9223"

## Distribution

This build is internal use only:
- No code signing → Windows SmartScreen and macOS Gatekeeper will warn on first launch
- No auto-update mechanism
- No installer signing

For public distribution, additional work is needed: signing certs, notarization (macOS), and an auto-update channel.
````

- [ ] **Step 2: Commit**

```bash
git add desktop/README.md
git commit -m "docs(desktop): README with dev workflow, build, and troubleshooting"
```

---

## Task 18: Push branch and final verification

**Files:** none

- [ ] **Step 1: Verify all unit tests pass**

```bash
cd desktop
npm test
```

Expected: all vitest tests PASS (paths, port-finder, log-tail, health-check).

- [ ] **Step 2: Verify branch commit log**

```bash
git log --oneline feat/desktop-app ^main
```

Expected: ~17-20 commits matching the task list above.

- [ ] **Step 3: Verify required files are tracked**

```bash
git ls-files -- desktop scripts agent/flowboard-agent.spec agent/flowboard/__main__.py
```

Expected files present:
- `desktop/package.json`
- `desktop/tsconfig.json`
- `desktop/.gitignore`
- `desktop/vitest.config.ts`
- `desktop/electron-builder.yml`
- `desktop/README.md`
- `desktop/src/main.ts`
- `desktop/src/agent-manager.ts`
- `desktop/src/window-manager.ts`
- `desktop/src/menu.ts`
- `desktop/src/paths.ts`
- `desktop/src/paths.test.ts`
- `desktop/src/port-finder.ts`
- `desktop/src/port-finder.test.ts`
- `desktop/src/log-tail.ts`
- `desktop/src/log-tail.test.ts`
- `desktop/src/health-check.ts`
- `desktop/src/health-check.test.ts`
- `desktop/assets/splash.html`
- `desktop/assets/icon.png`
- `scripts/build-desktop.ps1`
- `scripts/build-desktop.sh`
- `agent/flowboard-agent.spec`
- `agent/flowboard/__main__.py`

- [ ] **Step 4: Push branch**

```bash
git push -u origin feat/desktop-app
```

Expected: branch pushed.

- [ ] **Step 5: Final Definition-of-Done check**

- Windows: `scripts/build-desktop.ps1` produces a working `.exe` installer; install on a clean machine → app starts, generates one request successfully.
- macOS: `scripts/build-desktop.sh` produces a working `.dmg`; install → app starts. (Defer if no macOS hardware available.)
- Branch `feat/desktop-app` pushed to remote.
- `desktop/README.md` documents dev workflow + build instructions + troubleshooting.

---

## Implementation Notes

- **Python version:** PyInstaller uses whichever `python` is active. Ensure the venv has Python ≥ 3.10 (matches `agent/pyproject.toml`).
- **Hidden imports troubleshooting:** PyInstaller's static analysis misses dynamic imports. If runtime errors mention `ModuleNotFoundError`, add the module to `hiddenimports` in `agent/flowboard-agent.spec` and rebuild.
- **No CLI bundling:** Claude/Gemini CLIs are NOT bundled. Users install them separately into PATH. The existing `ForcedSetupGate` component will warn if missing.
- **Chrome Extension unchanged:** No work needed in `extension/`. The extension still connects to `ws://127.0.0.1:9223` as before.
- **macOS arm64 vs x64:** Build config produces both. To build only one, change `mac.target.arch` in `electron-builder.yml`.
- **Icon quality:** The placeholder `icon.png` is a flat color. Replace with the actual Flowboard logo (512x512 PNG) before any non-internal release.
- **Storage migration:** Existing users running the Docker-based app have data in `./data/storage/flowboard.db`. To migrate, copy that file to `%APPDATA%\flowboard-desktop\storage\flowboard.db` (Windows) or `~/Library/Application Support/flowboard-desktop/storage/flowboard.db` (macOS) before first launch.
