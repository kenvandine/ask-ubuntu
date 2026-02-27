'use strict';

const { app, BrowserWindow, Menu, ipcMain, shell, nativeTheme } = require('electron');
const { spawn, exec } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const SERVER_PORT = 8765;
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

// In a snap $SNAP points to the immutable snap root where the python part
// installs server.py and the uvicorn script.  Outside a snap we look for
// the dev venv one directory above the electron/ folder.
const IN_SNAP   = !!process.env.SNAP;
const REPO_ROOT = IN_SNAP ? process.env.SNAP : path.join(__dirname, '..');

let mainWindow = null;
let serverProcess = null;
let pollInterval = null;
let accentMonitorProcess = null;

// ── Accent colour — follows org.gnome.desktop.interface accent-color ──────────

const ACCENT_MAP = {
  orange:        '#E95420',
  bark:          '#787859',
  sage:          '#657B69',
  olive:         '#4B8501',
  viridian:      '#03875B',
  prussiangreen: '#308280',
  blue:          '#0073E5',
  purple:        '#7764D8',
  magenta:       '#B34CB3',
  red:           '#DA3450',
};

function parseAccentColor(raw) {
  const name = raw.trim().replace(/'/g, '').toLowerCase();
  return ACCENT_MAP[name] || '#E95420';
}

function getAccentColor(cb) {
  exec('gsettings get org.gnome.desktop.interface accent-color', (err, stdout) => {
    cb(err ? '#E95420' : parseAccentColor(stdout));
  });
}

function startAccentColorMonitor() {
  try {
    accentMonitorProcess = spawn('gsettings', [
      'monitor', 'org.gnome.desktop.interface', 'accent-color',
    ]);
    accentMonitorProcess.stdout.on('data', () => {
      // Any output means accent-color changed — re-read the current value
      getAccentColor((color) => {
        if (mainWindow) mainWindow.webContents.send('accent-color-changed', color);
      });
    });
    accentMonitorProcess.on('error', () => { accentMonitorProcess = null; });
  } catch (_) {
    accentMonitorProcess = null;
  }
}

// ── Spawn the uvicorn backend ────────────────────────────────────────────────

function startServer() {
  // Snap: uvicorn is installed by the python part at $SNAP/bin/uvicorn.
  // Dev: fall back to the venv inside the repo root.
  const uvicorn = IN_SNAP
    ? path.join(REPO_ROOT, 'bin', 'uvicorn')
    : path.join(REPO_ROOT, '.venv', 'bin', 'uvicorn');

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
    uvicorn,
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
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#2c2c2c' : '#F2F2F2',
    title: 'Ask Ubuntu',
    frame: true,
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

ipcMain.handle('get-accent-color', () =>
  new Promise((resolve) => getAccentColor(resolve))
);

// ── Locale / i18n IPC ──────────────────────────────────────────────────────────

function resolveLocaleCode(code) {
  const localesDir = path.join(REPO_ROOT, 'locales');
  // Normalise Electron's "en-GB" → "en_GB"
  const normalised = code.replace(/-/g, '_');
  if (fs.existsSync(path.join(localesDir, `${normalised}.json`))) return normalised;
  const lang = normalised.split('_')[0];
  if (lang !== normalised && fs.existsSync(path.join(localesDir, `${lang}.json`))) return lang;
  return 'en';
}

ipcMain.handle('get-locale', () => {
  const raw = app.getLocale();           // e.g. "es", "en-GB", "de"
  return resolveLocaleCode(raw);
});

ipcMain.handle('get-locale-strings', () => {
  const raw = app.getLocale();
  const resolved = resolveLocaleCode(raw);
  const localesDir = path.join(REPO_ROOT, 'locales');

  // Load English base
  let strings = {};
  const enPath = path.join(localesDir, 'en.json');
  if (fs.existsSync(enPath)) {
    strings = JSON.parse(fs.readFileSync(enPath, 'utf-8'));
  }

  // Overlay locale-specific strings
  if (resolved !== 'en') {
    const locPath = path.join(localesDir, `${resolved}.json`);
    if (fs.existsSync(locPath)) {
      Object.assign(strings, JSON.parse(fs.readFileSync(locPath, 'utf-8')));
    }
  }

  return strings;
});

// ── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  nativeTheme.themeSource = 'system';   // honour the OS dark/light preference
  Menu.setApplicationMenu(null);
  startServer();
  createWindow();
  pollHealth();
  startAccentColorMonitor();
});

app.on('window-all-closed', () => {
  if (pollInterval) clearInterval(pollInterval);
  if (serverProcess) serverProcess.kill();
  if (accentMonitorProcess) accentMonitorProcess.kill();
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
