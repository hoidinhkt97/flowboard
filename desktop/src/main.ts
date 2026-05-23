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
