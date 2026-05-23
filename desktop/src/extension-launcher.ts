import { spawn } from 'child_process';
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import { app, shell } from 'electron';

const FLOW_URL = 'https://labs.google/fx/tools/flow';

// Known Chrome executable paths per platform
const CHROME_PATHS: Record<string, string[]> = {
  win32: [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    `${process.env.LOCALAPPDATA ?? ''}\\Google\\Chrome\\Application\\chrome.exe`,
  ],
  darwin: [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ],
  linux: [
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
  ],
};

function findChrome(): string | null {
  const candidates = CHROME_PATHS[process.platform] ?? [];
  for (const p of candidates) {
    if (p && fs.existsSync(p)) return p;
  }
  return null;
}

function resolveExtensionDir(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'extension');
  }
  // Dev mode: <repo>/extension/ (appPath = <repo>/desktop)
  return path.join(app.getAppPath(), '..', 'extension');
}

/** Check /api/health for extension_connected flag. */
export function isExtensionConnected(httpPort: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(
      `http://127.0.0.1:${httpPort}/api/health`,
      { timeout: 2000 },
      (res) => {
        let data = '';
        res.on('data', (chunk: Buffer) => (data += chunk));
        res.on('end', () => {
          try {
            const json = JSON.parse(data);
            resolve(json.extension_connected === true);
          } catch {
            resolve(false);
          }
        });
      }
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

/**
 * Launch Chrome with the Flowboard extension loaded and open labs.google/flow.
 * Uses --load-extension + dedicated --user-data-dir so the flag works
 * even when Chrome is already open.
 * Falls back to shell.openExternal if Chrome binary is not found.
 */
export function launchChromeWithExtension(): void {
  const chromePath = findChrome();
  const extensionDir = resolveExtensionDir();

  if (!chromePath) {
    console.log('[extension-launcher] Chrome not found, opening default browser');
    void shell.openExternal(FLOW_URL);
    return;
  }

  if (!fs.existsSync(extensionDir)) {
    console.warn('[extension-launcher] Extension directory not found at', extensionDir);
    void shell.openExternal(FLOW_URL);
    return;
  }

  console.log('[extension-launcher] Launching Chrome with extension:', extensionDir);

  // Dedicated profile dir so --load-extension works even if Chrome is already running
  const chromeDataDir = path.join(app.getPath('userData'), 'chrome-profile');
  fs.mkdirSync(chromeDataDir, { recursive: true });

  const child = spawn(
    chromePath,
    [
      `--load-extension=${extensionDir}`,
      `--user-data-dir=${chromeDataDir}`,
      '--no-first-run',
      '--no-default-browser-check',
      FLOW_URL,
    ],
    { detached: true, stdio: 'ignore' }
  );
  child.unref(); // Chrome outlives the Electron app
}

/**
 * After agent ready: if extension is not connected, auto-launch Chrome.
 * Resolves true when connected, false if timeout reached.
 */
export async function ensureExtensionConnected(
  httpPort: number,
  opts = { timeoutMs: 60_000, intervalMs: 2_000 }
): Promise<boolean> {
  if (await isExtensionConnected(httpPort)) return true;

  console.log('[extension-launcher] Extension not connected — launching Chrome');
  launchChromeWithExtension();

  const deadline = Date.now() + opts.timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, opts.intervalMs));
    if (await isExtensionConnected(httpPort)) {
      console.log('[extension-launcher] Extension connected');
      return true;
    }
  }

  console.warn('[extension-launcher] Extension did not connect within timeout');
  return false;
}
