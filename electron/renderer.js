'use strict';

// ── Configure marked ─────────────────────────────────────────────────────────
marked.setOptions({ breaks: true, gfm: true });

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

let ws = null;
let isWaiting = false;

// ── Utility: highlight code blocks inside a DOM node ─────────────────────────
function highlightIn(node) {
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
  // Wrap all <pre> in an orange-bordered panel
  div.querySelectorAll('pre').forEach((pre) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'code-panel';
    pre.replaceWith(wrapper);
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

// ── Show / hide the loading overlay ──────────────────────────────────────────
function showStatus(msg) {
  statusText.textContent = msg;
  statusOverlay.style.display = 'flex';
}

function hideStatus() {
  statusOverlay.style.display = 'none';
}

// ── Enable the input controls ─────────────────────────────────────────────────
function enableInput() {
  userInput.disabled = false;
  sendBtn.disabled = false;
  userInput.focus();
}

function setWaiting(waiting) {
  isWaiting = waiting;
  userInput.disabled = waiting;
  sendBtn.disabled = waiting;
  sendBtn.textContent = waiting ? '…' : 'Send';
}

// ── Load system info into the sidebar ────────────────────────────────────────
async function loadSystemInfo() {
  try {
    const res = await fetch(`${SERVER_HTTP}/system-info`);
    const data = await res.json();
    sysInfoEl.textContent = data.summary || '(unavailable)';
  } catch (_) {
    sysInfoEl.textContent = '(unavailable)';
  }
}

// ── WebSocket setup ───────────────────────────────────────────────────────────
function connectWS() {
  ws = new WebSocket(SERVER_WS);

  ws.onopen = () => {
    hideStatus();
    enableInput();
    loadSystemInfo();
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'tool_calls') {
      appendToolCalls(data.calls);
    } else if (data.type === 'response') {
      setWaiting(false);
      appendBubble('assistant', data.text);
    } else if (data.type === 'error') {
      setWaiting(false);
      appendBubble('assistant', `❌ **Error:** ${data.message}`);
    } else if (data.type === 'cleared') {
      messagesEl.innerHTML = '';
    }
  };

  ws.onerror = () => {
    setWaiting(false);
    showStatus('Connection lost. Reconnecting…');
    setTimeout(connectWS, 2000);
  };

  ws.onclose = () => {
    setWaiting(false);
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
// Poll /health directly instead of relying on IPC timing.
// This avoids the race where server-ready fires before the renderer listener
// is registered (common when the RAG index is already cached).
async function waitForServerReady() {
  while (true) {
    try {
      const res = await fetch(`${SERVER_HTTP}/health`);
      const data = await res.json();
      if (data.ready) {
        connectWS();
        return;
      }
      if (data.error) {
        showStatus(`Backend error: ${data.error}`);
        return;
      }
      showStatus('Initializing engine…');
    } catch (_) {
      showStatus('Starting backend…');
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

showStatus('Starting backend…');
waitForServerReady();
