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
const sysInfoEl     = document.getElementById('system-info-content');
const appEl         = document.getElementById('app');
const sidebarToggle = document.getElementById('btn-sidebar-toggle');
const helpBtn       = document.getElementById('help-btn');
const newChatBtn    = document.getElementById('new-chat-btn');
const audioAutoplayBtn = document.getElementById('audio-autoplay-btn');
const audioVoiceSelect = document.getElementById('audio-voice-select');
const audioStatusEl = document.getElementById('audio-status');

const downloadProgress = document.getElementById('download-progress');
const downloadBarFill  = document.getElementById('download-bar-fill');
const downloadDetail   = document.getElementById('download-detail');
const modelBtn         = document.getElementById('model-btn');

let ws = null;            // currently active WebSocket (null while connecting)
let isWaiting = false;
let thinkingBubble = null;
let sysInfoRefreshTimer = null;
let _exchangeIdx = 0;     // increments on each user send; tags DOM nodes for rewind
let _pendingExchange = -1; // exchange index of the in-flight request
let autoplayAudioEnabled = localStorage.getItem('audio-autoplay') === 'true';
let selectedTtsVoice = localStorage.getItem('audio-voice') || 'af_heart';
let activeAudio = null;
let activeAudioUrl = null;
const LEGACY_OPENAI_VOICES = new Set(['alloy', 'ash', 'coral', 'echo', 'fable', 'onyx', 'nova', 'sage', 'shimmer']);

const ICON_SPEAK =
  '<svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14" aria-hidden="true">' +
  '<path d="M3.5 6.5H1.75A.75.75 0 0 0 1 7.25v1.5c0 .414.336.75.75.75H3.5l3 2.5A.75.75 0 0 0 7.75 11V5a.75.75 0 0 0-1.25-.577z"/>' +
  '<path d="M10.156 6.469a.75.75 0 0 1 1.06 0 2.75 2.75 0 0 1 0 3.89.75.75 0 1 1-1.06-1.06 1.25 1.25 0 0 0 0-1.77.75.75 0 0 1 0-1.06z"/>' +
  '<path d="M12.278 4.347a.75.75 0 0 1 1.06 0 5.75 5.75 0 0 1 0 8.132.75.75 0 1 1-1.06-1.06 4.25 4.25 0 0 0 0-6.012.75.75 0 0 1 0-1.06z"/>' +
  '</svg>';

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

function updateAudioAutoplayUI() {
  if (!audioAutoplayBtn) return;
  audioAutoplayBtn.classList.toggle('is-active', autoplayAudioEnabled);
  audioAutoplayBtn.title = autoplayAudioEnabled
    ? t('audio.autoplay_on')
    : t('audio.autoplay_off');
}

function setAudioStatus(message, isError = false) {
  if (!audioStatusEl) return;
  audioStatusEl.textContent = message || '';
  audioStatusEl.classList.toggle('error', !!isError);
}

function stopActiveAudio() {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio = null;
  }
  if (activeAudioUrl) {
    URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = null;
  }
  setAudioStatus(t('audio.status_idle'));
}

function markdownToSpeechText(markdown) {
  const src = String(markdown || '').trim();
  if (!src) return '';
  try {
    const tmp = document.createElement('div');
    tmp.innerHTML = marked.parse(src);
    // textContent strips markdown formatting while preserving readable content.
    return (tmp.textContent || tmp.innerText || '')
      .replace(/\s+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
  } catch (_) {
    // Fallback: basic markdown marker stripping.
    return src
      .replace(/[*_`>#~-]+/g, ' ')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
  }
}

async function playTts(text, stateBtn = null) {
  const trimmed = markdownToSpeechText(text);
  if (!trimmed) return;
  if (stateBtn) {
    stateBtn.disabled = true;
    stateBtn.classList.add('is-playing');
  }
  try {
    stopActiveAudio();
    setAudioStatus(t('audio.status_generating'));
    const res = await fetch(`${SERVER_HTTP}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: trimmed, voice: selectedTtsVoice }),
    });
    if (!res.ok) {
      throw new Error(`TTS request failed (${res.status})`);
    }
    const mime = res.headers.get('content-type') || 'audio/mpeg';
    const audioBytes = await res.arrayBuffer();
    const blob = new Blob([audioBytes], { type: mime });
    activeAudioUrl = URL.createObjectURL(blob);
    activeAudio = new Audio(activeAudioUrl);
    activeAudio.preload = 'auto';
    activeAudio.volume = 1.0;
    activeAudio.addEventListener('ended', () => stopActiveAudio(), { once: true });
    activeAudio.addEventListener('error', (e) => {
      console.warn('Audio playback element error:', e);
      setAudioStatus(t('audio.status_error_decode'), true);
      stopActiveAudio();
    }, { once: true });
    activeAudio.load();
    setAudioStatus(t('audio.status_playing'));
    await activeAudio.play();
  } catch (err) {
    console.warn('TTS playback failed:', err);
    const blocked = String(err && err.name) === 'NotAllowedError';
    setAudioStatus(
      blocked ? t('audio.status_error_autoplay') : t('audio.status_error_play'),
      true
    );
  } finally {
    if (stateBtn) {
      stateBtn.disabled = false;
      stateBtn.classList.remove('is-playing');
    }
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

// ── SVG icons for copy button states ─────────────────────────────────────────
const ICON_COPY =
  '<svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14" aria-hidden="true">' +
  '<path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 ' +
  '.138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 ' +
  '16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/>' +
  '<path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 ' +
  '11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 ' +
  '0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/>' +
  '</svg>';
const ICON_COPIED =
  '<svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14" aria-hidden="true">' +
  '<path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 ' +
  '0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"/>' +
  '</svg>';
const ICON_FAILED =
  '<svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14" aria-hidden="true">' +
  '<path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 ' +
  '3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 ' +
  '0 0 1 0-1.06Z"/>' +
  '</svg>';

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
    copyBtn.title = t('button.copy');
    copyBtn.innerHTML = ICON_COPY;
    copyBtn.addEventListener('click', () => {
      const codeEl = pre.querySelector('code');
      const text = (codeEl ? codeEl.innerText : pre.innerText).trimEnd();
      navigator.clipboard.writeText(text).then(() => {
        copyBtn.innerHTML = ICON_COPIED;
        copyBtn.title = t('button.copied');
        copyBtn.classList.add('copied');
        setTimeout(() => {
          copyBtn.innerHTML = ICON_COPY;
          copyBtn.title = t('button.copy');
          copyBtn.classList.remove('copied');
        }, 2000);
      }).catch(() => {
        copyBtn.innerHTML = ICON_FAILED;
        setTimeout(() => {
          copyBtn.innerHTML = ICON_COPY;
          copyBtn.title = t('button.copy');
        }, 2000);
      });
    });

    pre.replaceWith(wrapper);
    wrapper.appendChild(copyBtn);
    wrapper.appendChild(pre);
  });
  return div;
}

// ── Append a bubble to the messages area ─────────────────────────────────────
function appendBubble(role, content, exchangeIdx) {
  const bubble = document.createElement('div');
  bubble.className = `bubble bubble-${role}`;
  if (exchangeIdx !== undefined) bubble.dataset.exchange = exchangeIdx;

  if (role === 'user') {
    const textSpan = document.createElement('span');
    textSpan.className = 'bubble-user-text';
    textSpan.textContent = content;
    bubble.appendChild(textSpan);

    const editBtn = document.createElement('button');
    editBtn.className = 'edit-msg-btn';
    editBtn.title = t('chat.edit_message');
    editBtn.innerHTML =
      '<svg viewBox="0 0 16 16" fill="currentColor" width="13" height="13">' +
      '<path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0' +
      ' 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.929-.928l' +
      '.929-3.251c.081-.286.235-.547.445-.756l8.612-8.61zm1.414 1.06a.25.25 0 0 0' +
      '-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354l-1.086-1.086z' +
      'M11.189 5.25 9.75 3.81 3.34 10.22a.25.25 0 0 0-.065.108l-.65 2.274 2.274-.65' +
      'a.25.25 0 0 0 .108-.065z"/></svg>';
    const capturedIdx = exchangeIdx;
    const capturedText = content;
    editBtn.addEventListener('click', () => editMessage(capturedIdx, capturedText));
    bubble.appendChild(editBtn);
  } else {
    const speakBtn = document.createElement('button');
    speakBtn.className = 'speak-msg-btn';
    speakBtn.title = t('audio.play_response');
    speakBtn.innerHTML = ICON_SPEAK;
    speakBtn.addEventListener('click', () => playTts(content, speakBtn));
    bubble.appendChild(speakBtn);
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
function appendToolCalls(calls, exchangeIdx) {
  const details = document.createElement('details');
  details.className = 'tool-calls';
  if (exchangeIdx !== undefined) details.dataset.exchange = exchangeIdx;

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
  sendBtn.disabled = false;
  sendBtn.textContent = waiting ? '⏹' : t('button.ask');
  sendBtn.classList.toggle('stop-mode', waiting);
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
        if (modelOverlay) {
          // Route progress to the model picker
          if (data.status === 'complete') {
            // wait for model_changed to close the picker
          } else {
            onModelDownloadProgress(data);
          }
        } else if (data.status === 'complete') {
          hideDownloadProgress();
          showStatus(t('status.initializing'));
        } else {
          showDownloadProgress(data.model, data.status, data.completed, data.total);
        }
        return;
      } else if (data.type === 'model_changing') {
        // picker already shows progress — nothing extra needed
        return;
      } else if (data.type === 'model_changed') {
        onModelChanged(data.model);
        return;
      } else if (data.type === 'tool_calls') {
        // Show tool calls between thinking pulses
        hideThinking();
        appendToolCalls(data.calls, _pendingExchange);
        showThinking();
      } else if (data.type === 'response') {
        setWaiting(false);
        appendBubble('assistant', data.text, _pendingExchange);
        if (autoplayAudioEnabled) {
          playTts(data.text);
        }
        userInput.focus();
      } else if (data.type === 'aborted') {
        setWaiting(false);
        userInput.focus();
      } else if (data.type === 'error') {
        if (modelPickerBusy) {
          onModelChangeFailed();
        }
        setWaiting(false);
        appendBubble('assistant', `**Error:** ${data.message}`, _pendingExchange);
        userInput.focus();
      } else if (data.type === 'cleared') {
        messagesEl.innerHTML = '';
        _exchangeIdx = 0;
        _pendingExchange = -1;
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
  const thisExchange = _exchangeIdx++;
  appendBubble('user', text, thisExchange);
  userInput.value = '';
  userInput.style.height = 'auto';
  setWaiting(true);
  _pendingExchange = thisExchange;

  ws.send(JSON.stringify({ type: 'chat', message: text, exchange: thisExchange }));
}

// ── Edit a previous user message ─────────────────────────────────────────────
function editMessage(exchangeIdx, text) {
  if (isWaiting) return;

  // Remove all DOM nodes (bubbles + tool-calls) from this exchange onward
  Array.from(messagesEl.children).forEach((el) => {
    const idx = parseInt(el.dataset.exchange, 10);
    if (!isNaN(idx) && idx >= exchangeIdx) el.remove();
  });

  // Rewind server-side conversation history
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'rewind', index: exchangeIdx }));
  }

  // Reset exchange counter to match
  _exchangeIdx = exchangeIdx;

  // Put the text back in the input and focus it
  userInput.value = text;
  userInput.style.height = 'auto';
  userInput.style.height = `${Math.min(userInput.scrollHeight, 200)}px`;
  userInput.focus();
}

// ── Event listeners ───────────────────────────────────────────────────────────
sendBtn.addEventListener('click', () => {
  if (isWaiting) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'abort' }));
    }
  } else {
    sendMessage();
  }
});

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

newChatBtn.addEventListener('click', () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'clear' }));
  }
});

audioAutoplayBtn.addEventListener('click', () => {
  autoplayAudioEnabled = !autoplayAudioEnabled;
  localStorage.setItem('audio-autoplay', autoplayAudioEnabled ? 'true' : 'false');
  updateAudioAutoplayUI();
  setAudioStatus(
    autoplayAudioEnabled ? t('audio.status_autoplay_on') : t('audio.status_autoplay_off')
  );
});

audioVoiceSelect.addEventListener('change', () => {
  selectedTtsVoice = audioVoiceSelect.value;
  localStorage.setItem('audio-voice', selectedTtsVoice);
});

// ── Model picker overlay ──────────────────────────────────────────────────
let modelOverlay = null;
let modelPickerBusy = false;   // true while a model change is in progress

function showModelPicker() {
  if (modelOverlay) return;
  modelOverlay = document.createElement('div');
  modelOverlay.className = 'model-overlay';
  modelOverlay.addEventListener('click', (e) => {
    if (e.target === modelOverlay && !modelPickerBusy) hideModelPicker();
  });

  const panel = document.createElement('div');
  panel.className = 'model-panel';

  // Header with title and search
  const header = document.createElement('div');
  header.className = 'model-panel-header';
  const title = document.createElement('h2');
  title.textContent = t('model.title');
  header.appendChild(title);

  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.className = 'model-search-input';
  searchInput.placeholder = t('model.search_placeholder');
  searchInput.setAttribute('autocomplete', 'off');
  searchInput.setAttribute('spellcheck', 'false');
  header.appendChild(searchInput);

  // Tab bar
  const tabBar = document.createElement('div');
  tabBar.className = 'model-tabs';

  const tabLocal = document.createElement('button');
  tabLocal.className = 'model-tab active';
  tabLocal.textContent = t('model.tab_local');
  tabLocal.dataset.tab = 'local';

  const tabRemote = document.createElement('button');
  tabRemote.className = 'model-tab';
  tabRemote.textContent = t('model.tab_remote');
  tabRemote.dataset.tab = 'remote';

  tabBar.appendChild(tabLocal);
  tabBar.appendChild(tabRemote);
  header.appendChild(tabBar);
  panel.appendChild(header);

  // Local tab content
  const localContent = document.createElement('div');
  localContent.className = 'model-tab-content';
  localContent.dataset.tabContent = 'local';

  const list = document.createElement('div');
  list.className = 'model-list';
  list.innerHTML = `<p style="color:var(--text-dim);font-size:0.85rem;padding:12px 4px">${escapeHtml(t('model.loading'))}</p>`;
  localContent.appendChild(list);
  panel.appendChild(localContent);

  // Remote tab content
  const remoteContent = document.createElement('div');
  remoteContent.className = 'model-tab-content';
  remoteContent.dataset.tabContent = 'remote';
  remoteContent.style.display = 'none';

  const remoteList = document.createElement('div');
  remoteList.className = 'model-list';
  remoteList.innerHTML = `<p style="color:var(--text-dim);font-size:0.85rem;padding:12px 4px">${escapeHtml(t('model.loading'))}</p>`;
  remoteContent.appendChild(remoteList);
  panel.appendChild(remoteContent);

  // Progress row (hidden until needed)
  const progressRow = document.createElement('div');
  progressRow.className = 'model-progress-row';
  progressRow.style.display = 'none';
  const progressLabel = document.createElement('div');
  progressLabel.className = 'model-progress-label';
  const progressTrack = document.createElement('div');
  progressTrack.className = 'model-progress-track';
  const progressFill = document.createElement('div');
  progressFill.className = 'model-progress-fill';
  progressTrack.appendChild(progressFill);
  progressRow.appendChild(progressLabel);
  progressRow.appendChild(progressTrack);
  panel.appendChild(progressRow);

  panel._list = list;
  panel._remoteList = remoteList;
  panel._progressRow = progressRow;
  panel._progressLabel = progressLabel;
  panel._progressFill = progressFill;
  panel._activeTab = 'local';

  modelOverlay.appendChild(panel);
  document.body.appendChild(modelOverlay);

  _loadModelList(panel);
  _loadRemoteProviders(panel);

  // Focus search input after render
  requestAnimationFrame(() => searchInput.focus());

  // Tab switching
  [tabLocal, tabRemote].forEach((tab) => {
    tab.addEventListener('click', () => {
      tabLocal.classList.toggle('active', tab === tabLocal);
      tabRemote.classList.toggle('active', tab === tabRemote);
      localContent.style.display = tab === tabLocal ? '' : 'none';
      remoteContent.style.display = tab === tabRemote ? '' : 'none';
      panel._activeTab = tab.dataset.tab;
      // Re-apply search filter
      const q = searchInput.value.toLowerCase();
      _applyModelFilter(panel, q);
    });
  });

  searchInput.addEventListener('input', () => {
    const q = searchInput.value.toLowerCase();
    _applyModelFilter(panel, q);
  });
}

function _applyModelFilter(panel, q) {
  if (panel._activeTab === 'local') {
    panel._list.querySelectorAll('.model-item').forEach((item) => {
      item.style.display = (!q || item.dataset.modelId.toLowerCase().includes(q)) ? '' : 'none';
    });
  } else {
    panel._remoteList.querySelectorAll('.model-item').forEach((item) => {
      item.style.display = (!q || item.dataset.modelId.toLowerCase().includes(q)) ? '' : 'none';
    });
  }
}

function hideModelPicker() {
  if (modelOverlay) {
    modelOverlay.remove();
    modelOverlay = null;
  }
}

async function _loadModelList(panel) {
  try {
    const res = await fetch(`${SERVER_HTTP}/models`);
    const data = await res.json();
    _renderModelList(panel, data.models || [], data.current_model);
  } catch (e) {
    panel._list.innerHTML = `<p style="color:var(--accent-red);font-size:0.85rem;padding:12px 4px">Failed to load models.</p>`;
  }
}

async function _loadRemoteProviders(panel) {
  try {
    const res = await fetch(`${SERVER_HTTP}/remote-providers`);
    const data = await res.json();
    _renderRemoteTab(panel, data);
  } catch (e) {
    panel._remoteList.innerHTML = `<p style="color:var(--accent-red);font-size:0.85rem;padding:12px 4px">Failed to load remote providers.</p>`;
  }
}

function _renderRemoteTab(panel, data) {
  const container = panel._remoteList;
  container.innerHTML = '';

  const providers = data.providers || [];
  const presets = data.presets || [];

  if (providers.length === 0) {
    // Show setup form
    _renderRemoteSetupForm(container, presets, panel);
    return;
  }

  // Render each configured provider
  providers.forEach((provider) => {
    const section = document.createElement('div');
    section.className = 'remote-provider-section';

    const sectionHeader = document.createElement('div');
    sectionHeader.className = 'remote-provider-header';

    const providerName = document.createElement('span');
    providerName.className = 'remote-provider-name';
    providerName.textContent = provider.name;

    const cloudBadge = document.createElement('span');
    cloudBadge.className = 'model-badge model-badge-cloud';
    cloudBadge.textContent = t('remote.cloud');

    const isCustom = !presets.includes(provider.id);

    if (!provider.from_env) {
      const editBtn = document.createElement('button');
      editBtn.className = 'remote-edit-btn';
      editBtn.textContent = t('remote.edit');
      editBtn.addEventListener('click', () => {
        _renderProviderEditForm(section, provider, isCustom, panel);
      });
      sectionHeader.appendChild(editBtn);
    }

    const removeBtn = document.createElement('button');
    removeBtn.className = 'remote-remove-btn';
    removeBtn.textContent = t('remote.remove');
    removeBtn.addEventListener('click', async () => {
      if (provider.from_env) return;
      await fetch(`${SERVER_HTTP}/remote-providers/${provider.id}`, { method: 'DELETE' });
      _loadRemoteProviders(panel);
    });
    if (provider.from_env) {
      removeBtn.disabled = true;
      removeBtn.title = t('remote.env_var_hint', { env_var: '' }).replace(' environment variable', '');
    }

    sectionHeader.appendChild(providerName);
    sectionHeader.appendChild(cloudBadge);
    sectionHeader.appendChild(removeBtn);
    section.appendChild(sectionHeader);

    // Models list placeholder — filled by _renderProviderModels
    const modelsContainer = document.createElement('div');
    modelsContainer.className = 'remote-provider-models';
    section.appendChild(modelsContainer);

    container.appendChild(section);

    // Render models: use preset list if available, otherwise discover from provider
    if (provider.models && provider.models.length > 0) {
      _renderProviderModelItems(modelsContainer, provider.models, provider.id, panel);
    } else {
      _discoverAndRenderModels(modelsContainer, provider, panel);
    }
  });

  // Add provider button at bottom
  const addBtn = document.createElement('button');
  addBtn.className = 'remote-add-btn';
  addBtn.textContent = t('remote.add_provider');
  addBtn.addEventListener('click', () => {
    container.innerHTML = '';
    _renderRemoteSetupForm(container, presets, panel);
  });
  container.appendChild(addBtn);
}

function _renderProviderEditForm(section, provider, isCustom, panel) {
  // Hide the models container while editing
  const modelsContainer = section.querySelector('.remote-provider-models');
  if (modelsContainer) modelsContainer.style.display = 'none';

  // Remove any existing edit form
  const existing = section.querySelector('.remote-edit-form');
  if (existing) existing.remove();

  const form = document.createElement('div');
  form.className = 'remote-edit-form';

  if (isCustom) {
    // Name field
    const nameGroup = document.createElement('div');
    nameGroup.className = 'remote-form-group';
    const nameLabel = document.createElement('label');
    nameLabel.textContent = t('remote.name_label');
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'remote-form-input';
    nameInput.value = provider.name || '';
    nameGroup.appendChild(nameLabel);
    nameGroup.appendChild(nameInput);
    form.appendChild(nameGroup);

    // Base URL field
    const urlGroup = document.createElement('div');
    urlGroup.className = 'remote-form-group';
    const urlLabel = document.createElement('label');
    urlLabel.textContent = t('remote.base_url_label');
    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.className = 'remote-form-input';
    urlInput.value = provider.base_url || '';
    urlGroup.appendChild(urlLabel);
    urlGroup.appendChild(urlInput);
    form.appendChild(urlGroup);

    // API Key field
    const keyGroup = document.createElement('div');
    keyGroup.className = 'remote-form-group';
    const keyLabel = document.createElement('label');
    keyLabel.textContent = t('remote.api_key_label');
    const keyInput = document.createElement('input');
    keyInput.type = 'password';
    keyInput.className = 'remote-form-input';
    keyInput.value = provider.api_key || '';
    keyGroup.appendChild(keyLabel);
    keyGroup.appendChild(keyInput);
    form.appendChild(keyGroup);

    const btnRow = document.createElement('div');
    btnRow.className = 'remote-edit-btn-row';

    const saveBtn = document.createElement('button');
    saveBtn.className = 'remote-save-btn remote-save-btn-inline';
    saveBtn.textContent = t('remote.save');
    saveBtn.addEventListener('click', async () => {
      const name = nameInput.value.trim();
      const baseUrl = urlInput.value.trim();
      const apiKey = keyInput.value.trim();
      if (!baseUrl || !apiKey) {
        (baseUrl ? keyInput : urlInput).focus();
        return;
      }
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      saveBtn.textContent = '…';
      try {
        await fetch(`${SERVER_HTTP}/remote-providers`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: provider.id, api_key: apiKey, base_url: baseUrl, name: name || 'Custom' }),
        });
        await _loadRemoteProviders(panel);
      } finally {
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
        saveBtn.textContent = t('remote.save');
      }
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'remote-cancel-btn';
    cancelBtn.textContent = t('remote.cancel');
    cancelBtn.addEventListener('click', () => {
      form.remove();
      if (modelsContainer) modelsContainer.style.display = '';
    });

    btnRow.appendChild(saveBtn);
    btnRow.appendChild(cancelBtn);
    form.appendChild(btnRow);
  } else {
    // Preset provider — only the API key is editable
    const keyGroup = document.createElement('div');
    keyGroup.className = 'remote-form-group';
    const keyLabel = document.createElement('label');
    keyLabel.textContent = t('remote.api_key_label');
    const keyInput = document.createElement('input');
    keyInput.type = 'password';
    keyInput.className = 'remote-form-input';
    keyInput.value = provider.api_key || '';
    keyGroup.appendChild(keyLabel);
    keyGroup.appendChild(keyInput);
    form.appendChild(keyGroup);

    const btnRow = document.createElement('div');
    btnRow.className = 'remote-edit-btn-row';

    const saveBtn = document.createElement('button');
    saveBtn.className = 'remote-save-btn remote-save-btn-inline';
    saveBtn.textContent = t('remote.save');
    saveBtn.addEventListener('click', async () => {
      const apiKey = keyInput.value.trim();
      if (!apiKey) { keyInput.focus(); return; }
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      saveBtn.textContent = '…';
      try {
        await fetch(`${SERVER_HTTP}/remote-providers`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: provider.id, api_key: apiKey }),
        });
        await _loadRemoteProviders(panel);
      } finally {
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
        saveBtn.textContent = t('remote.save');
      }
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'remote-cancel-btn';
    cancelBtn.textContent = t('remote.cancel');
    cancelBtn.addEventListener('click', () => {
      form.remove();
      if (modelsContainer) modelsContainer.style.display = '';
    });

    btnRow.appendChild(saveBtn);
    btnRow.appendChild(cancelBtn);
    form.appendChild(btnRow);
  }

  section.appendChild(form);
  // Focus first input in the form
  const first = form.querySelector('input');
  if (first) requestAnimationFrame(() => first.focus());
}

function _renderProviderModelItems(container, models, providerId, panel) {
  models.forEach((m) => {
    const item = document.createElement('div');
    item.className = 'model-item';
    item.dataset.modelId = m.id;

    const info = document.createElement('div');
    info.className = 'model-item-info';

    const name = document.createElement('div');
    name.className = 'model-item-name';
    name.textContent = m.name || m.id;
    info.appendChild(name);

    if (m.name && m.name !== m.id) {
      const idRow = document.createElement('div');
      idRow.className = 'model-item-meta';
      const idBadge = document.createElement('span');
      idBadge.className = 'model-badge model-badge-label';
      idBadge.textContent = m.id;
      idRow.appendChild(idBadge);
      info.appendChild(idRow);
    }

    const btn = document.createElement('button');
    btn.className = 'model-select-btn';
    btn.textContent = t('model.select');
    btn.addEventListener('click', () => _selectModel(m.id, panel, providerId));

    item.appendChild(info);
    item.appendChild(btn);
    container.appendChild(item);
  });
}

async function _discoverAndRenderModels(container, provider, panel) {
  // Show a loading indicator while we probe the provider
  const loading = document.createElement('p');
  loading.className = 'remote-discover-status';
  loading.textContent = t('remote.discovering');
  container.appendChild(loading);

  try {
    const res = await fetch(`${SERVER_HTTP}/remote-providers/${provider.id}/models`);
    const data = await res.json();
    container.removeChild(loading);

    if (res.ok && data.models && data.models.length > 0) {
      _renderProviderModelItems(container, data.models, provider.id, panel);
    } else {
      // Discovery returned nothing or failed — show manual entry
      _renderManualModelInput(container, provider.id, panel, data.error || null);
    }
  } catch (_) {
    container.removeChild(loading);
    _renderManualModelInput(container, provider.id, panel, null);
  }
}

function _renderManualModelInput(container, providerId, panel, errorMsg) {
  if (errorMsg) {
    const err = document.createElement('p');
    err.className = 'remote-discover-status remote-discover-error';
    err.textContent = t('remote.discover_error', { error: errorMsg });
    container.appendChild(err);
  }

  const row = document.createElement('div');
  row.className = 'remote-manual-model-row';

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'remote-form-input remote-manual-model-input';
  input.placeholder = t('remote.model_name_placeholder');
  input.setAttribute('autocomplete', 'off');
  input.setAttribute('spellcheck', 'false');

  const btn = document.createElement('button');
  btn.className = 'model-select-btn';
  btn.textContent = t('model.select');
  btn.addEventListener('click', () => {
    const modelId = input.value.trim();
    if (modelId) _selectModel(modelId, panel, providerId);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const modelId = input.value.trim();
      if (modelId) _selectModel(modelId, panel, providerId);
    }
  });

  row.appendChild(input);
  row.appendChild(btn);
  container.appendChild(row);
}

function _renderRemoteSetupForm(container, presets, panel) {
  const form = document.createElement('div');
  form.className = 'remote-setup-form';

  const heading = document.createElement('h3');
  heading.className = 'remote-setup-heading';
  heading.textContent = t('remote.setup_heading');
  form.appendChild(heading);

  const desc = document.createElement('p');
  desc.className = 'remote-setup-desc';
  desc.textContent = t('remote.no_providers');
  form.appendChild(desc);

  // Provider dropdown
  const providerGroup = document.createElement('div');
  providerGroup.className = 'remote-form-group';
  const providerLabel = document.createElement('label');
  providerLabel.textContent = t('remote.provider_label');
  const providerSelect = document.createElement('select');
  providerSelect.className = 'remote-form-select';

  presets.forEach((pid) => {
    const option = document.createElement('option');
    option.value = pid;
    // Capitalise preset names
    option.textContent = pid.charAt(0).toUpperCase() + pid.slice(1);
    providerSelect.appendChild(option);
  });
  // Custom option
  const customOpt = document.createElement('option');
  customOpt.value = 'custom';
  customOpt.textContent = 'Custom';
  providerSelect.appendChild(customOpt);

  providerGroup.appendChild(providerLabel);
  providerGroup.appendChild(providerSelect);
  form.appendChild(providerGroup);

  // API Key
  const keyGroup = document.createElement('div');
  keyGroup.className = 'remote-form-group';
  const keyLabel = document.createElement('label');
  keyLabel.textContent = t('remote.api_key_label');
  const keyInput = document.createElement('input');
  keyInput.type = 'password';
  keyInput.className = 'remote-form-input';
  keyInput.placeholder = 'sk-…';
  keyGroup.appendChild(keyLabel);
  keyGroup.appendChild(keyInput);
  form.appendChild(keyGroup);

  // Custom-only fields
  const customFields = document.createElement('div');
  customFields.style.display = 'none';

  const urlGroup = document.createElement('div');
  urlGroup.className = 'remote-form-group';
  const urlLabel = document.createElement('label');
  urlLabel.textContent = t('remote.base_url_label');
  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'remote-form-input';
  urlInput.placeholder = 'https://api.example.com/v1';
  urlGroup.appendChild(urlLabel);
  urlGroup.appendChild(urlInput);
  customFields.appendChild(urlGroup);

  const nameGroup = document.createElement('div');
  nameGroup.className = 'remote-form-group';
  const nameLabel = document.createElement('label');
  nameLabel.textContent = t('remote.name_label');
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'remote-form-input';
  nameInput.placeholder = 'My Provider';
  nameGroup.appendChild(nameLabel);
  nameGroup.appendChild(nameInput);
  customFields.appendChild(nameGroup);

  form.appendChild(customFields);

  providerSelect.addEventListener('change', () => {
    customFields.style.display = providerSelect.value === 'custom' ? '' : 'none';
  });

  // Save button
  const saveBtn = document.createElement('button');
  saveBtn.className = 'remote-save-btn';
  saveBtn.textContent = t('remote.save');
  saveBtn.addEventListener('click', async () => {
    const providerId = providerSelect.value === 'custom'
      ? ('custom_' + Date.now())
      : providerSelect.value;
    const apiKey = keyInput.value.trim();
    if (!apiKey) {
      keyInput.focus();
      return;
    }
    const body = { id: providerId, api_key: apiKey };
    if (providerSelect.value === 'custom') {
      body.base_url = urlInput.value.trim();
      body.name = nameInput.value.trim() || 'Custom';
    }
    saveBtn.disabled = true;
    saveBtn.textContent = '…';
    try {
      await fetch(`${SERVER_HTTP}/remote-providers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      await _loadRemoteProviders(panel);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = t('remote.save');
    }
  });
  form.appendChild(saveBtn);

  container.appendChild(form);
}

function _renderModelList(panel, models, currentModel) {
  const list = panel._list;
  list.innerHTML = '';

  models.forEach((m) => {
    const item = document.createElement('div');
    item.className = 'model-item' + (m.current ? ' is-current' : '');
    item.dataset.modelId = m.id;

    const info = document.createElement('div');
    info.className = 'model-item-info';

    const name = document.createElement('div');
    name.className = 'model-item-name';
    name.textContent = m.id;
    info.appendChild(name);

    const meta = document.createElement('div');
    meta.className = 'model-item-meta';

    if (m.priority === 'recommended') {
      const badge = document.createElement('span');
      badge.className = 'model-badge model-badge-recommended';
      badge.textContent = t('model.recommended');
      meta.appendChild(badge);
    }

    if (m.priority_reason === 'NPU-accelerated') {
      const badge = document.createElement('span');
      badge.className = 'model-badge model-badge-npu';
      badge.textContent = t('model.npu');
      meta.appendChild(badge);
    }

    if (m.current) {
      const badge = document.createElement('span');
      badge.className = 'model-badge model-badge-current';
      badge.textContent = t('model.current');
      meta.appendChild(badge);
    }

    m.labels.forEach((lbl) => {
      if (['reasoning', 'coding', 'hot', 'tool-calling', 'vision'].includes(lbl)) {
        const badge = document.createElement('span');
        badge.className = 'model-badge model-badge-label';
        badge.textContent = lbl;
        meta.appendChild(badge);
      }
    });

    info.appendChild(meta);

    const size = document.createElement('div');
    size.className = 'model-size';
    size.textContent = `${m.size_gb.toFixed(1)} GB`;

    const dlInd = document.createElement('div');
    dlInd.className = 'model-dl-indicator' + (m.downloaded ? '' : ' needs-download');
    dlInd.textContent = m.downloaded ? '✓ ' + t('model.downloaded') : '⬇ ' + t('model.needs_download');

    const btn = document.createElement('button');
    btn.className = 'model-select-btn' + (m.current ? ' is-active' : '');
    btn.textContent = m.current ? t('model.select_current') : t('model.select');
    btn.disabled = m.current;

    btn.addEventListener('click', () => _selectModel(m.id, panel));

    item.appendChild(info);
    item.appendChild(size);
    item.appendChild(dlInd);
    item.appendChild(btn);
    list.appendChild(item);
  });
}

function _selectModel(modelId, panel, providerId = null) {
  if (!ws || ws.readyState !== WebSocket.OPEN || modelPickerBusy) return;
  modelPickerBusy = true;

  // Disable all select buttons in the active tab
  const activeList = providerId ? panel._remoteList : panel._list;
  activeList.querySelectorAll('.model-select-btn').forEach((b) => { b.disabled = true; });

  // Show progress bar
  panel._progressLabel.textContent = t('model.changing', { model: modelId });
  panel._progressFill.style.width = '0%';
  panel._progressFill.classList.add('indeterminate');
  panel._progressRow.style.display = 'block';

  const msg = { type: 'change_model', model: modelId };
  if (providerId) msg.provider = providerId;
  ws.send(JSON.stringify(msg));
}

// Called from WS message handler
function onModelDownloadProgress(data) {
  if (!modelOverlay) return;
  const panel = modelOverlay.querySelector('.model-panel');
  if (!panel) return;
  panel._progressRow.style.display = 'block';
  panel._progressLabel.textContent = t('status.downloading', { model: data.model });
  if (data.total > 0) {
    const pct = Math.min((data.completed / data.total) * 100, 100);
    panel._progressFill.classList.remove('indeterminate');
    panel._progressFill.style.width = `${pct}%`;
  } else {
    panel._progressFill.classList.add('indeterminate');
  }
}

function onModelChanged(newModel) {
  modelPickerBusy = false;
  hideModelPicker();
}

function onModelChangeFailed() {
  modelPickerBusy = false;
  if (!modelOverlay) return;
  const panel = modelOverlay.querySelector('.model-panel');
  if (!panel) return;
  panel._progressRow.style.display = 'none';
  panel._list.querySelectorAll('.model-select-btn').forEach((b) => { b.disabled = false; });
  panel._remoteList.querySelectorAll('.model-select-btn').forEach((b) => { b.disabled = false; });
  // Re-mark the current button
  _loadModelList(panel);
}

modelBtn.addEventListener('click', showModelPicker);

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
  } else if (e.key === 'Escape' && modelOverlay && !modelPickerBusy) {
    e.preventDefault();
    hideModelPicker();
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
  document.getElementById('model-btn').title = t('model.button_title');
  document.getElementById('help-btn').title = t('sidebar.help');
  document.getElementById('new-chat-btn').title = t('sidebar.new_chat');
  document.getElementById('audio-voice-label').textContent = t('audio.voice_label');
  if (LEGACY_OPENAI_VOICES.has(selectedTtsVoice)) {
    selectedTtsVoice = 'af_heart';
    localStorage.setItem('audio-voice', selectedTtsVoice);
  }
  if (audioVoiceSelect) {
    const presetHasVoice = Array.from(audioVoiceSelect.options).some((o) => o.value === selectedTtsVoice);
    if (!presetHasVoice) {
      const custom = document.createElement('option');
      custom.value = selectedTtsVoice;
      custom.textContent = selectedTtsVoice;
      audioVoiceSelect.appendChild(custom);
    }
    audioVoiceSelect.value = selectedTtsVoice;
  }
  updateAudioAutoplayUI();
  setAudioStatus(t('audio.status_idle'));
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
