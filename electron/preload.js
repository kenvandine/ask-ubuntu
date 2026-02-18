'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onServerReady: (cb) => ipcRenderer.on('server-ready', (_event) => cb()),
  onServerError: (cb) => ipcRenderer.on('server-error', (_event, msg) => cb(msg)),
});
