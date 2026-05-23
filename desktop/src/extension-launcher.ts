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

// Chrome Preferences file path per platform
function getChromePreferencesPath(): string | null {
  if (process.platform === 'win32') {
    const base = process.env.LOCALAPPDATA ?? '';
    return path.join(base, 'Google', 'Chrome', 'User Data', 'Default', 'Preferences');
  }
  if (process.platform === 'darwin') {
    return path.join(
      process.env.HOME ?? '',
      'Library', 'Application Support', 'Google', 'Chrome', 'Default', 'Preferences'
    );
  }
  if (process.platform === 'linux') {
    return path.join(process.env.HOME ?? '', '.config', 'google-chrome', 'Default', 'Preferences');
  }
  return null;
}

/**
 * Enable Chrome Developer Mode in the Default profile Preferences file.
 * Must be called while Chrome is NOT running (Chrome overwrites Preferences on exit).
 */
function enableChromeDeveloperMode(): void {
  const prefsPath = getChromePreferencesPath();
  if (!prefsPath || !fs.existsSync(prefsPath)) {
    console.log('[extension-launcher] Chrome Preferences not found, skipping dev-mode enable');
    return;
  }
  try {
    const raw = fs.readFileSync(prefsPath, 'utf-8');
    const prefs = JSON.parse(raw);

    if (!prefs.extensions) prefs.extensions = {};
    if (!prefs.extensions.ui) prefs.extensions.ui = {};

    if (prefs.extensions.ui.developer_mode === true) {
      console.log('[extension-launcher] Chrome developer mode already enabled');
      return;
    }

    prefs.extensions.ui.developer_mode = true;
    fs.writeFileSync(prefsPath, JSON.stringify(prefs));
    console.log('[extension-launcher] Chrome developer mode enabled');
  } catch (err) {
    console.warn('[extension-launcher] Could not enable Chrome developer mode:', err);
  }
}

function findChrome(): string | null {
  const candidates = CHROME_PATHS[process.platform] ?? [];
  for (const p of candidates) {
    if (p && fs.existsSync(p)) return p;
  }
  return null;
}

export function resolveExtensionDir(): string {
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
 * Launch Chrome with Flowboard extension auto-loaded.
 *
 * Steps:
 * 1. Enable developer mode in Chrome Preferences (while Chrome is not running)
 * 2. Launch Chrome with --load-extension pointing to the bundled extension
 * 3. Navigate to labs.google/fx/tools/flow so the extension can capture the token
 *
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

  // Enable developer mode so --load-extension is accepted by Chrome
  enableChromeDeveloperMode();

  console.log('[extension-launcher] Launching Chrome with --load-extension:', extensionDir);

  const child = spawn(
    chromePath,
    [
      `--load-extension=${extensionDir}`,
      '--no-first-run',
      '--no-default-browser-check',
      FLOW_URL,
    ],
    { detached: true, stdio: 'ignore' }
  );
  child.unref();
}

/**
 * After agent is ready: if extension is not connected, auto-launch Chrome.
 * Polls /api/health until extension_connected = true or timeout.
 */
export async function ensureExtensionConnected(
  httpPort: number,
  opts = { timeoutMs: 60_000, intervalMs: 2_000 }
): Promise<boolean> {
  if (await isExtensionConnected(httpPort)) return true;

  console.log('[extension-launcher] Extension not connected — launching Chrome with extension');
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
