'use strict';

// ── Configure marked ─────────────────────────────────────────────────────────
marked.use({ breaks: true, gfm: true });

const SERVER_WS = 'ws://127.0.0.1:8765/ws';
const SERVER_HTTP = 'http://127.0.0.1:8765';

// ── DOM refs ─────────────────────────────────────────────────────────────────
const statusOverlay = document.getElementById('status-overlay');
const statusText    = document.getElementById('status-text');
const messagesEl    = document.getElementById('messages');
const userInput     = document.getElementById('user-input');
const sendBtn       = document.getElementById('send-btn');
const clearBtn      = document.getElementById('clear-btn');
const sysInfoEl     = document.getElementById('system-info-content');
const appEl         = document.getElementById('app');
const sidebarToggle = document.getElementById('btn-sidebar-toggle');
const helpBtn       = document.getElementById('help-btn');
const newChatBtn    = document.getElementById('new-chat-btn');

const downloadProgress = document.getElementById('download-progress');
const downloadBarFill  = document.getElementById('download-bar-fill');
const downloadDetail   = document.getElementById('download-detail');

let ws = null;            // currently active WebSocket (null while connecting)
let isWaiting = false;
let thinkingBubble = null;
let sysInfoRefreshTimer = null;

// ── Welcome state ───────────────────────────────────────────────────────────
let welcomeEl = null;

function showWelcome() {
  if (welcomeEl) return;

  welcomeEl = document.createElement('div');
  welcomeEl.id = 'welcome-state';

  const logo = document.createElement('img');
  logo.src = 'ubuntu-logo.svg';
  logo.alt = 'Ubuntu';
  logo.className = 'welcome-logo';
  welcomeEl.appendChild(logo);

  const heading = document.createElement('h2');
  heading.textContent = t('welcome.heading');
  welcomeEl.appendChild(heading);

  const desc = document.createElement('p');
  desc.className = 'welcome-desc';
  desc.textContent = t('welcome.description');
  welcomeEl.appendChild(desc);

  const suggestions = [
    t('suggestion.packages'),
    t('suggestion.docker'),
    t('suggestion.disk'),
    t('suggestion.gpu'),
  ];

  const chips = document.createElement('div');
  chips.className = 'suggestion-chips';
  suggestions.forEach((text) => {
    const chip = document.createElement('button');
    chip.className = 'suggestion-chip';
    chip.textContent = text;
    chip.addEventListener('click', () => {
      userInput.value = text;
      sendMessage();
    });
    chips.appendChild(chip);
  });
  welcomeEl.appendChild(chips);

  const zoomHint = document.createElement('p');
  zoomHint.className = 'welcome-zoom-hint';
  zoomHint.textContent = t('welcome.zoom_hint');
  welcomeEl.appendChild(zoomHint);

  // Insert before #messages so it takes flex space
  const chatArea = document.getElementById('chat-area');
  chatArea.insertBefore(welcomeEl, messagesEl);
  messagesEl.style.display = 'none';
}

function hideWelcome() {
  if (welcomeEl) {
    welcomeEl.remove();
    welcomeEl = null;
    messagesEl.style.display = '';
  }
}

// ── Sidebar toggle ──────────────────────────────────────────────────────────
function initSidebarToggle() {
  const collapsed = localStorage.getItem('sidebar-collapsed') === 'true';
  if (collapsed) {
    appEl.classList.add('sidebar-collapsed');
  }

  sidebarToggle.addEventListener('click', () => {
    appEl.classList.toggle('sidebar-collapsed');
    const isCollapsed = appEl.classList.contains('sidebar-collapsed');
    localStorage.setItem('sidebar-collapsed', isCollapsed);

    // Manage live refresh based on visibility
    if (isCollapsed) {
      stopSysInfoRefresh();
    } else {
      startSysInfoRefresh();
    }
  });
}

initSidebarToggle();

// ── Utility: highlight code blocks inside a DOM node ─────────────────────────
function highlightIn(node) {
  if (typeof hljs === 'undefined') return;
  node.querySelectorAll('pre code').forEach((block) => {
    hljs.highlightElement(block);
  });
}

// ── Utility: render markdown string to an HTML element ───────────────────────
function renderMarkdown(text) {
  const div = document.createElement('div');
  div.className = 'markdown-body';
  div.innerHTML = marked.parse(text);
  highlightIn(div);
  // Wrap all <pre> in an orange-bordered panel with a copy button
  div.querySelectorAll('pre').forEach((pre) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'code-panel';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.textContent = t('button.copy');
    copyBtn.addEventListener('click', () => {
      const codeEl = pre.querySelector('code');
      const text = (codeEl ? codeEl.innerText : pre.innerText).trimEnd();
      navigator.clipboard.writeText(text).then(() => {
        copyBtn.textContent = t('button.copied');
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.textContent = t('button.copy');
          copyBtn.classList.remove('copied');
        }, 2000);
      }).catch(() => {
        copyBtn.textContent = t('button.copy_failed');
        setTimeout(() => { copyBtn.textContent = t('button.copy'); }, 2000);
      });
    });

    pre.replaceWith(wrapper);
    wrapper.appendChild(copyBtn);
    wrapper.appendChild(pre);
  });
  return div;
}

// ── Append a bubble to the messages area ─────────────────────────────────────
function appendBubble(role, content) {
  const bubble = document.createElement('div');
  bubble.className = `bubble bubble-${role}`;

  if (role === 'user') {
    bubble.textContent = content;
  } else {
    bubble.appendChild(renderMarkdown(content));
  }

  messagesEl.appendChild(bubble);
  bubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return bubble;
}

// ── Thinking indicator ────────────────────────────────────────────────────────
function showThinking() {
  if (thinkingBubble) return;
  thinkingBubble = document.createElement('div');
  thinkingBubble.className = 'bubble bubble-assistant thinking-bubble';
  thinkingBubble.innerHTML =
    '<span class="thinking-dots">' +
    '<span></span><span></span><span></span>' +
    '</span>';
  messagesEl.appendChild(thinkingBubble);
  thinkingBubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function hideThinking() {
  if (thinkingBubble) {
    thinkingBubble.remove();
    thinkingBubble = null;
  }
}

// ── Append a collapsible tool-call block ──────────────────────────────────────
function appendToolCalls(calls) {
  const details = document.createElement('details');
  details.className = 'tool-calls';

  const summary = document.createElement('summary');
  const toolCallText = t('tool_calls.summary', { count: calls.length });
  summary.textContent = `\uD83D\uDD27 ${toolCallText}`;
  details.appendChild(summary);

  const pre = document.createElement('pre');
  pre.className = 'tool-calls-body';
  pre.textContent = calls
    .map((c) => `${c.name}(${JSON.stringify(c.args)}) → ${c.result}`)
    .join('\n');
  details.appendChild(pre);

  messagesEl.appendChild(details);
  details.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

// ── Download progress helpers ──────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${val.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

function showDownloadProgress(model, status, completed, total) {
  downloadProgress.style.display = 'block';
  statusText.textContent = t('status.downloading', { model });

  if (total > 0) {
    const pct = Math.min((completed / total) * 100, 100);
    downloadBarFill.classList.remove('indeterminate');
    downloadBarFill.style.width = `${pct}%`;
    downloadDetail.textContent = `${formatBytes(completed)} / ${formatBytes(total)}  (${pct.toFixed(0)}%)`;
  } else {
    downloadBarFill.classList.add('indeterminate');
    downloadBarFill.style.width = '';
    downloadDetail.textContent = status || t('status.preparing');
  }
}

function hideDownloadProgress() {
  downloadProgress.style.display = 'none';
  downloadBarFill.classList.remove('indeterminate');
  downloadBarFill.style.width = '0%';
  downloadDetail.textContent = '';
}

// ── Show / hide the startup loading overlay ───────────────────────────────────
function showStatus(msg) {
  statusText.textContent = msg;
  statusOverlay.style.display = 'flex';
}

function hideStatus() {
  statusOverlay.style.display = 'none';
}

// ── Input state helpers ───────────────────────────────────────────────────────
function setInputReady(ready, placeholder) {
  userInput.disabled = !ready;
  sendBtn.disabled = !ready;
  userInput.placeholder = placeholder || t('input.placeholder');
  if (ready && !isWaiting) userInput.focus();
}

function setWaiting(waiting) {
  isWaiting = waiting;
  userInput.disabled = waiting;
  sendBtn.disabled = waiting;
  sendBtn.textContent = waiting ? t('button.waiting') : t('button.ask');
  if (waiting) showThinking();
  else hideThinking();
}

// ── Load system info into the sidebar (grouped) ──────────────────────────────
function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Translate a system-info field label from the server.
 * Handles dynamic labels like "Disk (/home)" by translating the base "Disk" part.
 */
function translateFieldLabel(label) {
  // Try exact match first: "sysinfo.Battery" → "Batería"
  const exact = t(`sysinfo.${label}`);
  if (exact !== `sysinfo.${label}`) return exact;

  // Handle "Disk (/home)" → translate "Disk", keep the suffix
  const match = label.match(/^(.+?)(\s*\(.+\))$/);
  if (match) {
    const base = t(`sysinfo.${match[1]}`);
    if (base !== `sysinfo.${match[1]}`) return `${base}${match[2]}`;
  }

  return label;
}

// Define which fields belong to which group
const SYSINFO_GROUPS = [
  { labelKey: 'sidebar.group.device',      keys: ['OS', 'Host', 'Type', 'Kernel', 'Uptime'] },
  { labelKey: 'sidebar.group.environment', keys: ['Shell', 'DE'] },
  { labelKey: 'sidebar.group.hardware',    keys: ['CPU', 'GPU', 'GPU GTT', 'GPU VRAM', 'Memory'] },
  { labelKey: 'sidebar.group.storage',     keys: ['Disk', 'Disk (/home)'] },
  { labelKey: 'sidebar.group.power',       keys: ['Battery', 'Temps'] },
  { labelKey: 'sidebar.group.packages',    keys: ['Deb pkgs', 'Snap pkgs'] },
];

async function loadSystemInfo() {
  try {
    const res = await fetch(`${SERVER_HTTP}/system-info`);
    const data = await res.json();
    const fields = data.fields || [];
    if (fields.length === 0) {
      sysInfoEl.innerHTML = `<dd>${escapeHtml(t('sidebar.unavailable'))}</dd>`;
      return;
    }

    // Build a lookup map from field label to value
    const fieldMap = new Map();
    fields.forEach(f => fieldMap.set(f.label, f.value));

    // Build grouped HTML
    let html = '';
    for (const group of SYSINFO_GROUPS) {
      // Collect fields matching exact keys, plus prefix matches for dynamic
      // labels like "Disk (/)" or "Disk (/home)"
      const groupFields = [];
      for (const key of group.keys) {
        if (fieldMap.has(key)) {
          groupFields.push({ label: key, value: fieldMap.get(key) });
        } else {
          // Prefix match: "Disk" matches "Disk (/home)"
          for (const [fLabel, fValue] of fieldMap) {
            if (fLabel.startsWith(key + ' (')) {
              groupFields.push({ label: fLabel, value: fValue });
            }
          }
        }
      }

      if (groupFields.length === 0) continue;

      html += `<div class="sysinfo-group">`;
      html += `<div class="sysinfo-group-label">${escapeHtml(t(group.labelKey))}</div>`;
      html += groupFields
        .map(f => `<div class="nf-row"><dt>${escapeHtml(translateFieldLabel(f.label))}</dt><dd>${escapeHtml(f.value)}</dd></div>`)
        .join('');
      html += `</div>`;
    }

    // Any remaining fields not in a group
    const groupedKeys = SYSINFO_GROUPS.flatMap(g => g.keys);
    const ungrouped = fields.filter(f =>
      !groupedKeys.some(k => f.label === k || f.label.startsWith(k + ' ('))
    );
    if (ungrouped.length > 0) {
      html += `<div class="sysinfo-group">`;
      html += `<div class="sysinfo-group-label">${escapeHtml(t('sidebar.group.other'))}</div>`;
      html += ungrouped
        .map(f => `<div class="nf-row"><dt>${escapeHtml(translateFieldLabel(f.label))}</dt><dd>${escapeHtml(f.value)}</dd></div>`)
        .join('');
      html += `</div>`;
    }

    sysInfoEl.innerHTML = html;
  } catch (_) {
    sysInfoEl.innerHTML = `<dd>${escapeHtml(t('sidebar.unavailable'))}</dd>`;
  }
}

// ── Live system info refresh ────────────────────────────────────────────────
function startSysInfoRefresh() {
  stopSysInfoRefresh();
  sysInfoRefreshTimer = setInterval(() => {
    if (!appEl.classList.contains('sidebar-collapsed')) {
      loadSystemInfo();
    }
  }, 60000);
}

function stopSysInfoRefresh() {
  if (sysInfoRefreshTimer) {
    clearInterval(sysInfoRefreshTimer);
    sysInfoRefreshTimer = null;
  }
}

// ── WebSocket setup ───────────────────────────────────────────────────────────
function connectWS() {
  const sock = new WebSocket(SERVER_WS);

  sock.onopen = () => {
    ws = sock;
    hideStatus();            // hide the boot overlay if still showing
    setInputReady(true);
    loadSystemInfo();
    // Start live refresh if sidebar is visible
    if (!appEl.classList.contains('sidebar-collapsed')) {
      startSysInfoRefresh();
    }
    // Show welcome state if no messages
    if (messagesEl.children.length === 0) {
      showWelcome();
    }
  };

  sock.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'download_progress') {
        if (data.status === 'complete') {
          hideDownloadProgress();
          showStatus(t('status.initializing'));
        } else {
          showDownloadProgress(data.model, data.status, data.completed, data.total);
        }
        return;
      } else if (data.type === 'tool_calls') {
        // Show tool calls between thinking pulses
        hideThinking();
        appendToolCalls(data.calls);
        showThinking();
      } else if (data.type === 'response') {
        setWaiting(false);
        appendBubble('assistant', data.text);
        userInput.focus();
      } else if (data.type === 'error') {
        setWaiting(false);
        appendBubble('assistant', `**Error:** ${data.message}`);
        userInput.focus();
      } else if (data.type === 'cleared') {
        messagesEl.innerHTML = '';
        showWelcome();
      }
    } catch (err) {
      setWaiting(false);
      appendBubble('assistant', `**Client error in onmessage:** ${err.message}`);
      userInput.focus();
      console.error('onmessage error:', err, 'raw event:', event.data);
    }
  };

  sock.onerror = () => {
    // onerror is always followed by onclose — let onclose handle reconnect
  };

  sock.onclose = () => {
    // Only act if this is still the active socket
    if (sock !== ws) return;
    ws = null;
    hideThinking();
    setWaiting(false);
    stopSysInfoRefresh();
    // Reconnect silently — no full-screen overlay, just disable the input
    setInputReady(false, t('status.reconnecting'));
    setTimeout(connectWS, 1500);
  };
}

// ── Send a message ────────────────────────────────────────────────────────────
function sendMessage() {
  const text = userInput.value.trim();
  if (!text || isWaiting || !ws || ws.readyState !== WebSocket.OPEN) return;

  hideWelcome();
  appendBubble('user', text);
  userInput.value = '';
  userInput.style.height = 'auto';
  setWaiting(true);

  ws.send(JSON.stringify({ type: 'chat', message: text }));
}

// ── Event listeners ───────────────────────────────────────────────────────────
sendBtn.addEventListener('click', sendMessage);

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Auto-grow textarea
userInput.addEventListener('input', () => {
  userInput.style.height = 'auto';
  userInput.style.height = `${Math.min(userInput.scrollHeight, 200)}px`;
});

clearBtn.addEventListener('click', () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'clear' }));
  }
});

newChatBtn.addEventListener('click', () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'clear' }));
  }
});

// ── Help overlay ──────────────────────────────────────────────────────────
let helpOverlay = null;

function showHelp() {
  if (helpOverlay) return;

  helpOverlay = document.createElement('div');
  helpOverlay.className = 'help-overlay';
  helpOverlay.addEventListener('click', (e) => {
    if (e.target === helpOverlay) hideHelp();
  });

  const panel = document.createElement('div');
  panel.className = 'help-panel';

  const title = document.createElement('h2');
  title.textContent = t('help.title');
  panel.appendChild(title);

  // Keyboard Shortcuts section
  const shortcutsSection = document.createElement('div');
  shortcutsSection.className = 'help-section';
  const shortcutsHeading = document.createElement('h3');
  shortcutsHeading.textContent = t('help.keyboard_shortcuts');
  shortcutsSection.appendChild(shortcutsHeading);

  const shortcuts = [
    ['Ctrl+=', t('help.shortcut.zoom_in')],
    ['Ctrl+\u2212', t('help.shortcut.zoom_out')],
    ['Ctrl+0', t('help.shortcut.zoom_reset')],
    ['F1', t('help.shortcut.help')],
    ['Ctrl+B', t('help.shortcut.toggle_sidebar')],
    ['Ctrl+L', t('help.shortcut.new_chat')],
    ['Escape', t('help.shortcut.escape')],
  ];

  const table = document.createElement('table');
  table.className = 'shortcuts-table';
  shortcuts.forEach(([key, desc]) => {
    const tr = document.createElement('tr');
    const tdKey = document.createElement('td');
    const tdDesc = document.createElement('td');
    const kbd = document.createElement('span');
    kbd.className = 'kbd';
    kbd.textContent = key;
    tdKey.appendChild(kbd);
    tdDesc.textContent = desc;
    tr.appendChild(tdKey);
    tr.appendChild(tdDesc);
    table.appendChild(tr);
  });
  shortcutsSection.appendChild(table);
  panel.appendChild(shortcutsSection);

  // Sidebar section
  const sidebarSection = document.createElement('div');
  sidebarSection.className = 'help-section';
  const sidebarHeading = document.createElement('h3');
  sidebarHeading.textContent = t('help.sidebar_section');
  sidebarSection.appendChild(sidebarHeading);
  const sidebarDesc = document.createElement('p');
  sidebarDesc.textContent = t('help.sidebar_description');
  sidebarSection.appendChild(sidebarDesc);
  panel.appendChild(sidebarSection);

  // How It Works section
  const howSection = document.createElement('div');
  howSection.className = 'help-section';
  const howHeading = document.createElement('h3');
  howHeading.textContent = t('help.how_it_works_section');
  howSection.appendChild(howHeading);
  const howDesc = document.createElement('p');
  howDesc.textContent = t('help.how_it_works_description');
  howSection.appendChild(howDesc);
  panel.appendChild(howSection);

  // Suggestions section
  const suggestSection = document.createElement('div');
  suggestSection.className = 'help-section';
  const suggestHeading = document.createElement('h3');
  suggestHeading.textContent = t('help.suggestions_section');
  suggestSection.appendChild(suggestHeading);
  const suggestDesc = document.createElement('p');
  suggestDesc.textContent = t('help.suggestions_description');
  suggestSection.appendChild(suggestDesc);
  panel.appendChild(suggestSection);

  helpOverlay.appendChild(panel);
  document.body.appendChild(helpOverlay);
}

function hideHelp() {
  if (helpOverlay) {
    helpOverlay.remove();
    helpOverlay = null;
  }
}

function toggleHelp() {
  if (helpOverlay) hideHelp();
  else showHelp();
}

helpBtn.addEventListener('click', toggleHelp);

// ── Global keyboard shortcuts ─────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'F1') {
    e.preventDefault();
    toggleHelp();
  } else if (e.key === '?' && e.ctrlKey) {
    e.preventDefault();
    toggleHelp();
  } else if (e.key === 'Escape' && helpOverlay) {
    e.preventDefault();
    hideHelp();
  } else if (e.key === 'b' && e.ctrlKey && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    sidebarToggle.click();
  } else if (e.key === 'l' && e.ctrlKey && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    newChatBtn.click();
  }
});

// ── Boot sequence ─────────────────────────────────────────────────────────────
async function waitForServerReady() {
  while (true) {
    try {
      const res = await fetch(`${SERVER_HTTP}/health`);
      const data = await res.json();
      if (data.ready) {
        hideDownloadProgress();
        connectWS();
        return;
      }
      if (data.error) {
        hideDownloadProgress();
        showStatus(t('status.backend_error', { error: data.error }));
        return;
      }
      if (data.downloading) {
        const dl = data.downloading;
        showDownloadProgress(dl.model, dl.status, dl.completed, dl.total);
      } else {
        showStatus(t('status.initializing'));
      }
    } catch (_) {
      showStatus(t('status.starting'));
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

// ── Initialize i18n then boot ─────────────────────────────────────────────────
async function boot() {
  await initI18n();

  // Apply translated static text to HTML elements
  document.title = t('app.title');
  document.querySelector('#sidebar-panel h1').textContent = t('app.title');
  document.getElementById('btn-sidebar-toggle').title = t('sidebar.toggle');
  document.getElementById('help-btn').title = t('sidebar.help');
  document.getElementById('new-chat-btn').title = t('sidebar.new_chat');
  document.getElementById('clear-btn').textContent = t('sidebar.new_chat');
  document.getElementById('clear-btn').title = t('sidebar.new_chat');
  document.getElementById('user-input').placeholder = t('input.placeholder');
  document.getElementById('send-btn').textContent = t('button.ask');

  // Set initial sidebar panel text
  document.getElementById('system-info-heading').textContent = t('sidebar.system_context');
  document.getElementById('system-info-subtitle').textContent = t('sidebar.system_subtitle');
  sysInfoEl.innerHTML = `<dd>${t('sidebar.loading')}</dd>`;

  showStatus(t('status.starting'));
  waitForServerReady();
}

boot();

// ── Accent colour — follows system setting ────────────────────────────────────
function applyAccentColor(hex) {
  const root = document.documentElement;
  root.style.setProperty('--accent-orange', hex);
  // Derive a semi-transparent border colour from the accent
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  root.style.setProperty('--border-code', `rgba(${r},${g},${b},0.45)`);
}

window.electronAPI.getAccentColor().then(applyAccentColor).catch(() => {});
window.electronAPI.onAccentColorChanged(applyAccentColor);

// ── System font settings — follows GNOME text-scaling-factor & font-name ────
function applyFontSettings({ fontFamily, monoFamily, fontSize, scalingFactor }) {
  const root = document.documentElement;
  // Convert GNOME point size to CSS pixels: points × (DPI / 72) × scaling factor
  // GNOME uses 96 DPI as its baseline, so 11pt × 96/72 × 1.0 ≈ 14.67px
  const PT_TO_PX = 96 / 72;
  const effectiveSize = Math.round(fontSize * PT_TO_PX * scalingFactor * 10) / 10;
  // Set font families on :root (inherited everywhere)
  root.style.setProperty('--system-font', `'${fontFamily}', system-ui, sans-serif`);
  root.style.setProperty('--system-mono', `'${monoFamily}', monospace`);
  root.style.setProperty('--system-font-size', `${effectiveSize}px`);
}

window.electronAPI.getFontSettings().then(applyFontSettings).catch(() => {});
window.electronAPI.onFontSettingsChanged(applyFontSettings);

// ── Open external links in the system default browser ────────────────────────
document.addEventListener('click', (e) => {
  const anchor = e.target.closest('a[href]');
  if (!anchor) return;
  const href = anchor.getAttribute('href');
  if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
    e.preventDefault();
    window.electronAPI.openExternal(href);
  }
});
