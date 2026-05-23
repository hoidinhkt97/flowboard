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
