'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onServerReady: (cb) => ipcRenderer.on('server-ready', (_event) => cb()),
  onServerError: (cb) => ipcRenderer.on('server-error', (_event, msg) => cb(msg)),
  minimize: () => ipcRenderer.send('win-minimize'),
  maximize: () => ipcRenderer.send('win-maximize'),
  close:    () => ipcRenderer.send('win-close'),
});
