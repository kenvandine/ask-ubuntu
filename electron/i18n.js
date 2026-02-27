'use strict';

/**
 * Lightweight i18n module for Ask Ubuntu Electron renderer.
 *
 * Usage:
 *   await initI18n();
 *   t('welcome.heading')  // → "Ask Ubuntu"
 *   t('status.downloading', { model: 'llama3' })  // → "Downloading llama3…"
 */

let _strings = {};
let _locale = 'en';

/**
 * Initialize i18n by loading locale strings from the main process via IPC.
 */
async function initI18n() {
  try {
    _locale = await window.electronAPI.getLocale();
  } catch (_) {
    _locale = 'en';
  }
  try {
    _strings = await window.electronAPI.getLocaleStrings();
  } catch (_) {
    _strings = {};
  }
}

/**
 * Look up a translated string by key with optional placeholder interpolation.
 *
 * Placeholders use {name} syntax: t('status.downloading', { model: 'llama3' })
 * For plural forms, use pipe-separated singular|plural with {count}:
 *   "tool_calls.summary": "{count} tool call|{count} tool calls"
 *
 * @param {string} key
 * @param {Object} [params]
 * @returns {string}
 */
function t(key, params) {
  let text = _strings[key] || key;

  // Handle simple plural: "singular|plural" split by pipe
  if (text.includes('|') && params && 'count' in params) {
    const parts = text.split('|');
    text = params.count === 1 ? parts[0] : parts[1];
  }

  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
    }
  }

  return text;
}

/**
 * Get the resolved locale code.
 * @returns {string}
 */
function getResolvedLocale() {
  return _locale;
}

// ── Intl-based formatters ─────────────────────────────────────────────────────

/**
 * Format a number with locale-aware thousand separators.
 * @param {number} n
 * @returns {string}
 */
function formatNumber(n) {
  return new Intl.NumberFormat(_locale).format(n);
}

/**
 * Format temperature — °F for en-US, °C everywhere else.
 * @param {number} celsius
 * @returns {string}
 */
function formatTemperature(celsius) {
  if (_locale === 'en' || _locale === 'en-US') {
    const f = celsius * 9 / 5 + 32;
    return `${Math.round(f)}°F`;
  }
  return `${Math.round(celsius)}°C`;
}

/**
 * Format a time using locale-appropriate 12h/24h convention.
 * @param {Date} date
 * @returns {string}
 */
function formatTime(date) {
  return new Intl.DateTimeFormat(_locale, {
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

/**
 * Format a date using locale-appropriate date order.
 * @param {Date} date
 * @returns {string}
 */
function formatDate(date) {
  return new Intl.DateTimeFormat(_locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

/**
 * Format a currency amount.
 * @param {number} amount
 * @param {string} code - ISO 4217 currency code (e.g. 'USD', 'EUR')
 * @returns {string}
 */
function formatCurrency(amount, code) {
  return new Intl.NumberFormat(_locale, {
    style: 'currency',
    currency: code,
  }).format(amount);
}
