"""
Lightweight i18n module for Ask Ubuntu CLI.

Usage:
    import i18n
    i18n.init()               # detect locale, load strings
    i18n.t('cli.goodbye')     # → "Goodbye!"
    i18n.t('cli.downloading', model='llama3')  # → "Downloading llama3…"
"""

import json
import locale
import os
from pathlib import Path

_strings: dict = {}
_locale_code: str = 'en'


def _detect_locale() -> str:
    """Detect language code from LANG environment variable."""
    lang = os.environ.get('LANG', '')
    # e.g. "es_ES.UTF-8" → "es_ES" → try exact then language-only
    code = lang.split('.')[0]  # strip encoding
    return code if code else 'en'


def _resolve_locale(code: str, locales_dir: Path) -> str:
    """Resolve locale code to an available JSON file.

    Resolution order: exact match (en_GB) → language only (en) → fallback 'en'.
    """
    # Exact match
    if (locales_dir / f'{code}.json').is_file():
        return code
    # Language-only fallback (e.g. es_ES → es)
    lang = code.split('_')[0]
    if lang != code and (locales_dir / f'{lang}.json').is_file():
        return lang
    return 'en'


def _find_locales_dir() -> Path:
    """Locate the locales/ directory, handling snap and dev environments."""
    snap = os.environ.get('SNAP')
    if snap:
        snap_dir = Path(snap) / 'locales'
        if snap_dir.is_dir():
            return snap_dir
    return Path(__file__).resolve().parent / 'locales'


def init(locale_override: str = None):
    """Initialize i18n: detect locale, load base English + locale overlay."""
    global _strings, _locale_code

    locales_dir = _find_locales_dir()

    # Load base English strings
    en_path = locales_dir / 'en.json'
    if en_path.is_file():
        with open(en_path, encoding='utf-8') as f:
            _strings = json.load(f)

    # Determine and resolve locale
    raw_code = locale_override or _detect_locale()
    _locale_code = _resolve_locale(raw_code, locales_dir)

    # Overlay locale-specific strings on top of English base
    if _locale_code != 'en':
        loc_path = locales_dir / f'{_locale_code}.json'
        if loc_path.is_file():
            with open(loc_path, encoding='utf-8') as f:
                _strings.update(json.load(f))

    # Try to set the system locale for number/date formatting
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        pass


def t(key: str, **kwargs) -> str:
    """Look up a translated string by key, with optional placeholder interpolation.

    Placeholders use {name} syntax: t('cli.downloading', model='llama3')
    For plural forms, use pipe-separated singular|plural with {count}:
        "tool_calls.summary": "{count} tool call|{count} tool calls"
    """
    text = _strings.get(key, key)

    # Handle simple plural: "singular|plural" split by pipe
    if '|' in text and 'count' in kwargs:
        parts = text.split('|', 1)
        text = parts[0] if kwargs['count'] == 1 else parts[1]

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return text


def get_locale() -> str:
    """Return the resolved locale code."""
    return _locale_code


def format_number(n) -> str:
    """Format a number with locale-aware thousand separators."""
    try:
        return locale.format_string('%g', n, grouping=True)
    except (ValueError, TypeError):
        return str(n)


def format_temperature(celsius: float) -> str:
    """Format temperature, using Fahrenheit for US locale, Celsius otherwise."""
    if _locale_code in ('en', 'en_US'):
        f = celsius * 9 / 5 + 32
        return f'{f:.0f}\u00b0F'
    return f'{celsius:.0f}\u00b0C'


def format_bytes_localized(n: int) -> str:
    """Format byte count with locale-aware number formatting."""
    if n == 0:
        return '0 B'
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    val = float(n)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024
        i += 1
    formatted = locale.format_string('%.1f', val, grouping=True) if i > 1 else locale.format_string('%.0f', val, grouping=True)
    return f'{formatted} {units[i]}'
