import { spawn } from 'child_process';
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import { app, shell } from 'electron';

let logStream: fs.WriteStream | null = null;

function log(level: 'INFO' | 'WARN' | 'ERROR', msg: string): void {
  const line = `[${new Date().toISOString()}] [${level}] [extension] ${msg}`;
  console.log(line);
  if (!logStream) {
    const logsDir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(logsDir, { recursive: true });
    logStream = fs.createWriteStream(path.join(logsDir, 'extension.log'), { flags: 'a' });
    logStream.write(`\n=== Extension launcher start ${new Date().toISOString()} ===\n`);
  }
  logStream.write(line + '\n');
}

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

// Chrome User Data directory per platform
function getChromeUserDataDir(): string | null {
  if (process.platform === 'win32') {
    return path.join(process.env.LOCALAPPDATA ?? '', 'Google', 'Chrome', 'User Data');
  }
  if (process.platform === 'darwin') {
    return path.join(process.env.HOME ?? '', 'Library', 'Application Support', 'Google', 'Chrome');
  }
  if (process.platform === 'linux') {
    return path.join(process.env.HOME ?? '', '.config', 'google-chrome');
  }
  return null;
}

/**
 * Find the active Chrome profile directory name by reading Local State.
 * Falls back to "Default" if Local State is missing or unreadable.
 */
function getActiveProfileDir(userDataDir: string): string {
  const localStatePath = path.join(userDataDir, 'Local State');
  try {
    const raw = fs.readFileSync(localStatePath, 'utf-8');
    const state = JSON.parse(raw);
    const lastUsed = state?.profile?.last_used as string | undefined;
    if (lastUsed) {
      log('INFO', `Active Chrome profile from Local State: ${lastUsed}`);
      return lastUsed;
    }
  } catch {
    log('INFO', 'Could not read Local State — using Default profile');
  }
  return 'Default';
}

function setDeveloperModeInPrefs(prefsPath: string): void {
  try {
    const raw = fs.existsSync(prefsPath) ? fs.readFileSync(prefsPath, 'utf-8') : '{}';
    const prefs = JSON.parse(raw);
    if (!prefs.extensions) prefs.extensions = {};
    if (!prefs.extensions.ui) prefs.extensions.ui = {};
    if (prefs.extensions.ui.developer_mode === true) {
      log('INFO', `Developer mode already on: ${prefsPath}`);
      return;
    }
    prefs.extensions.ui.developer_mode = true;
    fs.mkdirSync(path.dirname(prefsPath), { recursive: true });
    fs.writeFileSync(prefsPath, JSON.stringify(prefs));
    log('INFO', `Developer mode enabled: ${prefsPath}`);
  } catch (err) {
    log('ERROR', `Failed to write ${prefsPath}: ${(err as Error).message}`);
  }
}

/**
 * Enable Chrome Developer Mode across all found profiles.
 * If no Preferences file exists, create the Default profile directory and file.
 * Must be called while Chrome is NOT running (Chrome overwrites Preferences on exit).
 */
function enableChromeDeveloperMode(): void {
  const userDataDir = getChromeUserDataDir();
  log('INFO', `Chrome User Data dir: ${userDataDir ?? 'unknown'}`);

  if (!userDataDir) {
    log('WARN', 'Unknown platform — cannot locate Chrome User Data');
    return;
  }

  const profileDir = getActiveProfileDir(userDataDir);
  const prefsPath = path.join(userDataDir, profileDir, 'Preferences');
  log('INFO', `Target Preferences: ${prefsPath}`);
  setDeveloperModeInPrefs(prefsPath);
}

function findChrome(): string | null {
  const candidates = CHROME_PATHS[process.platform] ?? [];
  for (const p of candidates) {
    if (p && fs.existsSync(p)) {
      log('INFO', `Chrome found at: ${p}`);
      return p;
    }
    log('INFO', `Chrome not at: ${p}`);
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
  log('INFO', 'Starting Chrome launch sequence');

  const chromePath = findChrome();
  const extensionDir = resolveExtensionDir();
  log('INFO', `Extension directory: ${extensionDir}`);
  log('INFO', `Extension directory exists: ${fs.existsSync(extensionDir)}`);

  if (!chromePath) {
    log('WARN', 'Chrome binary not found on any known path — falling back to default browser');
    void shell.openExternal(FLOW_URL);
    return;
  }

  if (!fs.existsSync(extensionDir)) {
    log('ERROR', `Extension directory not found at ${extensionDir} — falling back to default browser`);
    void shell.openExternal(FLOW_URL);
    return;
  }

  log('INFO', 'Step 1: Enabling Chrome developer mode');
  enableChromeDeveloperMode();

  log('INFO', `Step 2: Spawning Chrome with --load-extension=${extensionDir}`);
  log('INFO', `Step 3: Navigating to ${FLOW_URL}`);

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
  child.on('error', (err) => log('ERROR', `Chrome spawn error: ${err.message}`));
  child.unref();

  log('INFO', 'Chrome spawned — waiting for extension to connect');
}

/**
 * After agent is ready: if extension is not connected, auto-launch Chrome.
 * Polls /api/health until extension_connected = true or timeout.
 */
export async function ensureExtensionConnected(
  httpPort: number,
  opts = { timeoutMs: 60_000, intervalMs: 2_000 }
): Promise<boolean> {
  log('INFO', `Checking extension connection on port ${httpPort}`);

  if (await isExtensionConnected(httpPort)) {
    log('INFO', 'Extension already connected — no action needed');
    return true;
  }

  log('INFO', 'Extension not connected — launching Chrome with extension');
  launchChromeWithExtension();

  const deadline = Date.now() + opts.timeoutMs;
  let attempt = 0;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, opts.intervalMs));
    attempt++;
    const connected = await isExtensionConnected(httpPort);
    log('INFO', `Poll attempt ${attempt}: extension_connected=${connected}`);
    if (connected) {
      log('INFO', 'Extension connected successfully');
      return true;
    }
  }

  log('WARN', `Extension did not connect after ${attempt} attempts (${opts.timeoutMs / 1000}s timeout)`);
  return false;
}
