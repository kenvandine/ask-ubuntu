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

const downloadProgress = document.getElementById('download-progress');
const downloadBarFill  = document.getElementById('download-bar-fill');
const downloadDetail   = document.getElementById('download-detail');

const INPUT_PLACEHOLDER = 'Ask something about Ubuntu…';

let ws = null;            // currently active WebSocket (null while connecting)
let isWaiting = false;
let thinkingBubble = null;

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
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => {
      const codeEl = pre.querySelector('code');
      const text = (codeEl ? codeEl.innerText : pre.innerText).trimEnd();
      navigator.clipboard.writeText(text).then(() => {
        copyBtn.textContent = 'Copied!';
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.textContent = 'Copy';
          copyBtn.classList.remove('copied');
        }, 2000);
      }).catch(() => {
        copyBtn.textContent = 'Failed';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
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
  summary.textContent = `🔧 ${calls.length} tool call${calls.length > 1 ? 's' : ''}`;
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
  statusText.textContent = `Downloading ${model}…`;

  if (total > 0) {
    const pct = Math.min((completed / total) * 100, 100);
    downloadBarFill.classList.remove('indeterminate');
    downloadBarFill.style.width = `${pct}%`;
    downloadDetail.textContent = `${formatBytes(completed)} / ${formatBytes(total)}  (${pct.toFixed(0)}%)`;
  } else {
    downloadBarFill.classList.add('indeterminate');
    downloadBarFill.style.width = '';
    downloadDetail.textContent = status || 'Preparing…';
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
  userInput.placeholder = placeholder || INPUT_PLACEHOLDER;
  if (ready && !isWaiting) userInput.focus();
}

function setWaiting(waiting) {
  isWaiting = waiting;
  userInput.disabled = waiting;
  sendBtn.disabled = waiting;
  sendBtn.textContent = waiting ? '…' : 'Ask';
  if (waiting) showThinking();
  else hideThinking();
}

// ── Load system info into the sidebar ────────────────────────────────────────
function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function loadSystemInfo() {
  try {
    const res = await fetch(`${SERVER_HTTP}/system-info`);
    const data = await res.json();
    const fields = data.fields || [];
    if (fields.length === 0) {
      sysInfoEl.innerHTML = '<dd>(unavailable)</dd>';
      return;
    }
    sysInfoEl.innerHTML = fields
      .map(f => `<div class="nf-row"><dt>${escapeHtml(f.label)}</dt><dd>${escapeHtml(f.value)}</dd></div>`)
      .join('');
  } catch (_) {
    sysInfoEl.innerHTML = '<dd>(unavailable)</dd>';
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
  };

  sock.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'download_progress') {
        if (data.status === 'complete') {
          hideDownloadProgress();
          showStatus('Initializing engine…');
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
        appendBubble('assistant', `❌ **Error:** ${data.message}`);
        userInput.focus();
      } else if (data.type === 'cleared') {
        messagesEl.innerHTML = '';
      }
    } catch (err) {
      setWaiting(false);
      appendBubble('assistant', `❌ **Client error in onmessage:** ${err.message}`);
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
    // Reconnect silently — no full-screen overlay, just disable the input
    setInputReady(false, 'Reconnecting…');
    setTimeout(connectWS, 1500);
  };
}

// ── Send a message ────────────────────────────────────────────────────────────
function sendMessage() {
  const text = userInput.value.trim();
  if (!text || isWaiting || !ws || ws.readyState !== WebSocket.OPEN) return;

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
        showStatus(`Backend error: ${data.error}`);
        return;
      }
      if (data.downloading) {
        const dl = data.downloading;
        showDownloadProgress(dl.model, dl.status, dl.completed, dl.total);
      } else {
        showStatus('Initializing engine…');
      }
    } catch (_) {
      showStatus('Starting backend…');
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

showStatus('Starting backend…');
waitForServerReady();

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

// ── Custom title bar controls ─────────────────────────────────────────────────
document.getElementById('btn-minimize').addEventListener('click', () => window.electronAPI.minimize());
document.getElementById('btn-maximize').addEventListener('click', () => window.electronAPI.maximize());
document.getElementById('btn-close').addEventListener('click', () => window.electronAPI.close());
