'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  onServerReady:        (cb)  => ipcRenderer.on('server-ready', (_event) => cb()),
  onServerError:        (cb)  => ipcRenderer.on('server-error', (_event, msg) => cb(msg)),
  minimize:             ()    => ipcRenderer.send('win-minimize'),
  maximize:             ()    => ipcRenderer.send('win-maximize'),
  close:                ()    => ipcRenderer.send('win-close'),
  openExternal:         (url) => ipcRenderer.send('open-external', url),
  getAccentColor:       ()    => ipcRenderer.invoke('get-accent-color'),
  onAccentColorChanged: (cb)  => ipcRenderer.on('accent-color-changed', (_event, color) => cb(color)),
  getLocale:            ()    => ipcRenderer.invoke('get-locale'),
  getLocaleStrings:     ()    => ipcRenderer.invoke('get-locale-strings'),
});
