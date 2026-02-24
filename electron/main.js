'use strict';

const { app, BrowserWindow, Menu, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const SERVER_PORT = 8765;
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;
const REPO_ROOT = path.join(__dirname, '..');

let mainWindow = null;
let serverProcess = null;
let pollInterval = null;

// ── Spawn the uvicorn backend ────────────────────────────────────────────────

function startServer() {
  // Try to find uvicorn inside the venv first, fall back to PATH
  const venvUvicorn = path.join(REPO_ROOT, '.venv', 'bin', 'uvicorn');

  // Get model argument from environment variable if provided
  const modelValue = process.env.ASK_UBUNTU_MODEL || null;

  const serverArgs = [
    'server:app',
    '--port', String(SERVER_PORT),
    '--host', '127.0.0.1',
    '--ws-ping-interval', '20',   // keep WS alive during long LLM calls
    '--ws-ping-timeout', '60',
  ];

  // Add model argument if provided
  if (modelValue) {
    serverArgs.push('--model', modelValue);
  }

  serverProcess = spawn(
    venvUvicorn,
    serverArgs,
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: REPO_ROOT,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );

  serverProcess.stdout.on('data', (d) => process.stdout.write(`[server] ${d}`));
  serverProcess.stderr.on('data', (d) => process.stderr.write(`[server] ${d}`));

  serverProcess.on('error', (err) => {
    if (mainWindow) {
      mainWindow.webContents.send('server-error', `Failed to start server: ${err.message}`);
    }
  });

  serverProcess.on('exit', (code) => {
    if (code !== 0 && mainWindow) {
      mainWindow.webContents.send('server-error', `Server exited with code ${code}`);
    }
  });
}

// ── Poll /health until the engine is ready ───────────────────────────────────

function pollHealth() {
  pollInterval = setInterval(() => {
    http.get(`${SERVER_URL}/health`, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        try {
          const data = JSON.parse(body);
          if (data.ready) {
            clearInterval(pollInterval);
            if (mainWindow) mainWindow.webContents.send('server-ready');
          } else if (data.error) {
            clearInterval(pollInterval);
            if (mainWindow) mainWindow.webContents.send('server-error', data.error);
          }
        } catch (_) {}
      });
    }).on('error', () => {
      // server not up yet — keep polling
    });
  }, 500);
}

// ── Create the browser window ────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: '#26071c',
    title: 'Ask Ubuntu',
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
  mainWindow.on('closed', () => { mainWindow = null; });

  // Open all external links in the system default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
}

// ── Window control IPC ────────────────────────────────────────────────────────

ipcMain.on('open-external', (_event, url) => shell.openExternal(url));

ipcMain.on('win-minimize', () => mainWindow?.minimize());
ipcMain.on('win-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on('win-close', () => mainWindow?.close());

// ── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  startServer();
  createWindow();
  pollHealth();
});

app.on('window-all-closed', () => {
  if (pollInterval) clearInterval(pollInterval);
  if (serverProcess) serverProcess.kill();
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
