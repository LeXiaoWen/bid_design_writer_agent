import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("bidDesignWriterDesktop", {
  platform: process.platform,
  selectDirectory: () => ipcRenderer.invoke("workspace:select-directory"),
  getAppAuthSecret: () => ipcRenderer.invoke("auth:get-app-secret"),
  getBackendUrl: () => ipcRenderer.invoke("backend:get-url"),
});
