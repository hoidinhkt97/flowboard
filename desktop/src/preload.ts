import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('flowboardDesktop', {
  launchChrome: () => ipcRenderer.invoke('launch-chrome'),
});
