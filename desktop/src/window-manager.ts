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
