#!/usr/bin/env python3
"""
Ask Ubuntu - An interactive shell tool for asking questions about Ubuntu
"""

import io
import sys
import json
import select
import shutil
import argparse
import threading
import warnings
from typing import List, Dict
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown, CodeBlock as _RichCodeBlock
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
from pygments.style import Style as _PygmentsStyle
from pygments.token import (
    Token, Comment, Keyword, Name, String, Number, Operator, Generic, Error
)
from rich.theme import Theme
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import ANSI, merge_formatted_text

from app_env import snap_user_common
from engine_orchestration import (
    resolve_local_models,
    pick_remote_fallback,
    resolve_explicit_provider_startup,
    switch_engine_model,
)
from chat_engine import (
    ChatEngine,
    ensure_model_available,
    get_chat_models,
    unload_model,
)
from remote_providers import (
    get_configured_providers,
    get_provider_info,
    save_provider,
    delete_provider,
    discover_provider_models,
    PROVIDER_PRESETS,
)
import i18n

# System info grouping — matches the Electron sidebar groups
SYSINFO_GROUPS = [
    {"label_key": "sidebar.group.device",      "keys": ["OS", "Host", "Type", "Kernel", "Uptime"]},
    {"label_key": "sidebar.group.environment",  "keys": ["Shell", "DE"]},
    {"label_key": "sidebar.group.hardware",     "keys": ["CPU", "GPU", "GPU GTT", "GPU VRAM", "Memory"]},
    {"label_key": "sidebar.group.storage",      "keys": ["Disk", "Disk (/home)"]},
    {"label_key": "sidebar.group.power",        "keys": ["Battery", "Temps"]},
    {"label_key": "sidebar.group.packages",     "keys": ["Deb pkgs", "Snap pkgs"]},
]

# Initialize Rich console with warm theme overrides (no cyan)
_ubuntu_theme = Theme({
    "markdown.code":       "bold #E95420",   # inline code: Ubuntu orange
    "markdown.code_block": "",               # handled by _BorderedCodeBlock
    "markdown.list":       "#E95420",        # list bullets: Ubuntu orange
    "markdown.link":       "bold #E95420",
    "markdown.link_url":   "underline #E95420",
})
console = Console(theme=_ubuntu_theme)


class _UbuntuCodeStyle(_PygmentsStyle):
    """Yaru-aligned syntax theme for terminal output."""
    background_color = "default"
    default_style = ""
    styles = {
        Token:                "#F7F7F7",
        Comment:              "#929292 italic",
        Comment.PreProc:      "#f99b11",
        Keyword:              "#E95420",         # Ubuntu orange
        Keyword.Constant:     "#0073E5",
        Operator:             "#f99b11",
        Operator.Word:        "#E95420",
        Name.Builtin:         "#E95420",
        Name.Function:        "#f99b11",
        Name.Class:           "#f99b11",
        Name.Namespace:       "#f99b11",
        Name.Variable:        "#F7F7F7",
        Name.Tag:             "#E95420",
        Name.Attribute:       "#f99b11",
        Name.Decorator:       "#E95420",
        String:               "#17a81a",
        String.Escape:        "#E95420",
        Number:               "#0073E5",
        Generic.Heading:      "#F7F7F7 bold",
        Generic.Prompt:       "#929292",
        Generic.Output:       "#c8c8c6",
        Generic.Error:        "#c7162b",
        Error:                "#c7162b",
    }


class _BorderedCodeBlock(_RichCodeBlock):
    """Render markdown code blocks as a bordered panel instead of a solid background."""

    def __rich_console__(self, console, options):
        code = str(self.text).rstrip()
        syntax = Syntax(
            code,
            self.lexer_name or "text",
            theme=_UbuntuCodeStyle,
            word_wrap=True,
            padding=(0, 1),
        )
        yield Panel(syntax, border_style="#E95420", padding=(0, 0))


# Register globally so every Markdown render uses bordered code blocks
Markdown.elements["fence"] = _BorderedCodeBlock
Markdown.elements["code_block"] = _BorderedCodeBlock


# Custom prompt style
prompt_style = Style.from_dict(
    {
        "prompt": "#E95420 bold",  # Ubuntu orange
        "input": "#ffffff",
    }
)


def _interactive_model_picker(models: list):
    """
    Full-screen live-filtering model picker built with prompt_toolkit.
    Accepts both local Lemonade models and remote provider models.
    Remote model dicts have is_remote=True, provider_id, provider_name.
    Returns the selected model dict, or None if cancelled.

    Controls: type to filter · ↑↓ navigate · PgUp/PgDn scroll · Enter select · Esc cancel
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.application.current import get_app

    sel   = [0]   # cursor index in filtered list
    top   = [0]   # scroll offset (first visible row)
    result = [None]
    search_buf = Buffer(name="search")

    def _filtered():
        q = search_buf.text.lower()
        return [m for m in models if not q or q in m["id"].lower()]

    def _vis_h():
        return max(5, shutil.get_terminal_size((80, 24)).lines - 6)

    def _fix():
        """Clamp sel and top so the selection is always visible."""
        items = _filtered()
        n = len(items)
        sel[0] = max(0, min(sel[0], n - 1)) if n else 0
        vh = _vis_h()
        if sel[0] < top[0]:
            top[0] = sel[0]
        elif sel[0] >= top[0] + vh:
            top[0] = sel[0] - vh + 1
        top[0] = max(0, top[0])

    def _sep():
        return "  " + "─" * max(20, shutil.get_terminal_size((80, 24)).columns - 4)

    def _priority_reason_text(reason: str) -> str:
        if reason == "NPU-accelerated":
            return i18n.t("cli.model_picker.priority_reason.npu_accelerated")
        if reason == "best for your hardware":
            return i18n.t("cli.model_picker.priority_reason.best_hardware")
        return reason

    def get_list_tokens():
        items = _filtered()
        if not items:
            return [("class:dim", f"  ({i18n.t('cli.model_picker.ui.no_matches')})")]
        vh = _vis_h()
        tokens = []
        prev_remote = None  # track section changes for header
        for i, m in enumerate(items[top[0]: top[0] + vh], start=top[0]):
            hi = (i == sel[0])
            is_remote = m.get("is_remote", False)
            row_handler = _row_mouse_handler(i)

            # Insert section header when transitioning local→remote
            if is_remote and prev_remote is False:
                tokens += [("class:dim", _sep() + "\n")]
                tokens += [("class:cloud", f"  ☁ {i18n.t('cli.model_picker.ui.remote_header')}\n")]
            prev_remote = is_remote

            tokens += [("class:cur" if hi else "", " ❯ " if hi else "   ", row_handler)]

            if is_remote and m.get("is_manual_entry"):
                tokens += [("class:dim", "✎ ")]
                tokens += [("class:sel" if hi else "class:dim", m.get("display_name", i18n.t("cli.remote.enter_model_name")), row_handler)]
                if m.get("provider_name"):
                    tokens += [("class:dim", f"  {m['provider_name']}", row_handler)]
            elif is_remote:
                tokens += [("class:cloud", "☁ ", row_handler)]
                label = m.get("display_name") or m["id"]
                tokens += [("class:sel" if hi else ("class:act" if m["current"] else ""), label, row_handler)]
                if m.get("provider_name"):
                    tokens += [("class:dim", f"  {m['provider_name']}", row_handler)]
            else:
                tokens += [("class:rec", "★ ", row_handler) if m["priority"] == "recommended" else ("", "  ", row_handler)]
                tokens += [("class:sel" if hi else ("class:act" if m["current"] else ""), m["id"], row_handler)]
                if m["priority_reason"]:
                    tokens += [("class:dim", f"  {_priority_reason_text(m['priority_reason'])}", row_handler)]
                tokens += [("class:dim", f"  {m['size_gb']:.1f} GB", row_handler)]
                tokens += [("class:ok", "  ✓", row_handler) if m["downloaded"] else ("class:warn", "  ⬇", row_handler)]

            if m["current"]:
                tokens += [("class:tag", f" [{i18n.t('cli.model_picker.ui.active_tag')}]", row_handler)]
            tokens += [("", "\n")]

        n = len(items)
        if n > vh:
            tokens += [(
                "class:dim",
                "\n  " + i18n.t(
                    "cli.model_picker.ui.range",
                    start=top[0] + 1,
                    end=min(top[0] + vh, n),
                    total=n,
                ),
            )]
        return tokens

    def _row_mouse_handler(idx: int):
        def handler(mouse_event):
            et = mouse_event.event_type
            if et == MouseEventType.SCROLL_UP:
                sel[0] = max(0, sel[0] - 1)
                _fix()
                get_app().invalidate()
                return None
            if et == MouseEventType.SCROLL_DOWN:
                sel[0] = min(max(0, len(_filtered()) - 1), sel[0] + 1)
                _fix()
                get_app().invalidate()
                return None
            if et == MouseEventType.MOUSE_DOWN:
                sel[0] = idx
                _fix()
                get_app().invalidate()
                return None
            if et == MouseEventType.MOUSE_UP:
                items = _filtered()
                if 0 <= idx < len(items):
                    sel[0] = idx
                    result[0] = items[idx]
                    get_app().exit()
            return None
        return handler

    kb = KeyBindings()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event): event.app.exit()

    @kb.add("enter")
    def _(event):
        items = _filtered()
        if items:
            result[0] = items[sel[0]]
        event.app.exit()

    @kb.add("up")
    def _(event):
        sel[0] = max(0, sel[0] - 1); _fix()

    @kb.add("down")
    def _(event):
        sel[0] = min(max(0, len(_filtered()) - 1), sel[0] + 1); _fix()

    @kb.add("pageup")
    def _(event):
        sel[0] = max(0, sel[0] - _vis_h()); _fix()

    @kb.add("pagedown")
    def _(event):
        sel[0] = min(max(0, len(_filtered()) - 1), sel[0] + _vis_h()); _fix()

    def _on_change(_):
        sel[0] = 0; top[0] = 0

    search_buf.on_text_changed += _on_change

    style = PTStyle.from_dict({
        "title":  "#E95420 bold",
        "sep":    "#444444",
        "flabel": "#E95420",
        "cur":    "#E95420 bold",
        "sel":    "bold",
        "act":    "bold",
        "rec":    "#E95420",
        "cloud":  "#0073E5",
        "tag":    "#888888",
        "dim":    "#666666",
        "ok":     "#17a81a",
        "warn":   "#f99b11",
    })

    layout = Layout(HSplit([
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:title", f"  ✦ {i18n.t('cli.model_picker.ui.title')}")])),
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:sep", _sep())])),
        VSplit([
            Window(width=11, content=FormattedTextControl(
                lambda: [("class:flabel", f"  {i18n.t('cli.model_picker.ui.filter')}: ")])),
            Window(height=1, content=BufferControl(buffer=search_buf)),
        ], height=1),
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:sep", _sep())])),
        Window(content=FormattedTextControl(get_list_tokens, focusable=False)),
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:dim", f"  {i18n.t('cli.model_picker.ui.controls')}")])),
    ]))

    Application(layout=layout, key_bindings=kb, style=style,
                full_screen=True, mouse_support=True).run()
    return result[0]


def _interactive_provider_picker(providers: list):
    """
    Full-screen provider picker with keyboard and mouse actions.
    Returns (action, index) where action is one of: add, edit, remove, done.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle
    from prompt_toolkit.mouse_events import MouseEventType

    sel = [0]
    top = [0]
    result = [("done", None)]

    def _vis_h():
        return max(4, shutil.get_terminal_size((80, 24)).lines - 10)

    def _fix():
        n = len(providers)
        sel[0] = max(0, min(sel[0], n - 1)) if n else 0
        vh = _vis_h()
        if sel[0] < top[0]:
            top[0] = sel[0]
        elif sel[0] >= top[0] + vh:
            top[0] = sel[0] - vh + 1
        top[0] = max(0, top[0])

    def _sep():
        return "  " + "─" * max(20, shutil.get_terminal_size((80, 24)).columns - 4)

    def _row_handler(idx: int):
        def handler(mouse_event):
            et = mouse_event.event_type
            if et == MouseEventType.SCROLL_UP:
                sel[0] = max(0, sel[0] - 1)
                _fix()
                get_app().invalidate()
                return None
            if et == MouseEventType.SCROLL_DOWN:
                sel[0] = min(max(0, len(providers) - 1), sel[0] + 1)
                _fix()
                get_app().invalidate()
                return None
            if et in (MouseEventType.MOUSE_DOWN, MouseEventType.MOUSE_UP):
                sel[0] = idx
                _fix()
                get_app().invalidate()
                if et == MouseEventType.MOUSE_UP:
                    result[0] = ("edit", idx)
                    get_app().exit()
            return None
        return handler

    def _action_handler(action: str):
        def handler(mouse_event):
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                idx = sel[0] if providers else None
                result[0] = (action, idx)
                get_app().exit()
            return None
        return handler

    def _list_tokens():
        if not providers:
            return [("class:dim", f"  ({i18n.t('cli.providers.none')})")]

        vh = _vis_h()
        tokens = []
        for i, p in enumerate(providers[top[0]: top[0] + vh], start=top[0]):
            hi = (i == sel[0])
            h = _row_handler(i)
            source = f" ({i18n.t('cli.providers.from_env')})" if p["from_env"] else ""
            kind = f" [{i18n.t('cli.providers.preset')}]" if p["id"] in PROVIDER_PRESETS else ""
            lead = " ❯ " if hi else "   "
            tokens += [("class:cur" if hi else "", lead, h)]
            tokens += [("class:name", p["name"], h)]
            tokens += [("class:dim", f"{kind}{source}", h)]
            if p["from_env"]:
                tokens += [("class:warn", f"  {i18n.t('cli.providers.cannot_remove_env')}", h)]
            tokens += [("", "\n")]
            if p["id"] not in PROVIDER_PRESETS:
                tokens += [("class:dim", f"      {p['base_url']}\n", h)]

        n = len(providers)
        if n > vh:
            tokens += [("class:dim", f"\n  {top[0]+1}–{min(top[0]+vh, n)} / {n}")]
        return tokens

    kb = KeyBindings()

    @kb.add("escape")
    @kb.add("c-c")
    @kb.add("q")
    def _(event):
        result[0] = ("done", None)
        event.app.exit()

    @kb.add("a")
    def _(event):
        result[0] = ("add", None)
        event.app.exit()

    @kb.add("enter")
    @kb.add("e")
    def _(event):
        if providers:
            result[0] = ("edit", sel[0])
            event.app.exit()

    @kb.add("r")
    def _(event):
        if providers:
            result[0] = ("remove", sel[0])
            event.app.exit()

    @kb.add("up")
    def _(event):
        sel[0] = max(0, sel[0] - 1); _fix()

    @kb.add("down")
    def _(event):
        sel[0] = min(max(0, len(providers) - 1), sel[0] + 1); _fix()

    @kb.add("pageup")
    def _(event):
        sel[0] = max(0, sel[0] - _vis_h()); _fix()

    @kb.add("pagedown")
    def _(event):
        sel[0] = min(max(0, len(providers) - 1), sel[0] + _vis_h()); _fix()

    style = PTStyle.from_dict({
        "title": "#E95420 bold",
        "sep": "#444444",
        "cur": "#E95420 bold",
        "name": "bold",
        "dim": "#666666",
        "warn": "#f99b11",
        "act": "#E95420 bold",
    })

    add_h = _action_handler("add")
    edit_h = _action_handler("edit")
    remove_h = _action_handler("remove")
    done_h = _action_handler("done")

    layout = Layout(HSplit([
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:title", f"  ☁ {i18n.t('cli.providers.title')}")])),
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:sep", _sep())])),
        Window(content=FormattedTextControl(_list_tokens, focusable=False)),
        Window(height=1, content=FormattedTextControl(
            lambda: [("class:sep", _sep())])),
        Window(height=1, content=FormattedTextControl(lambda: [
            ("", "  "),
            ("class:act", f"[{i18n.t('cli.providers.ui.add')}] ", add_h),
            ("class:dim", " "),
            ("class:act", f"[{i18n.t('cli.providers.ui.edit')}] ", edit_h),
            ("class:dim", " "),
            ("class:act", f"[{i18n.t('cli.providers.ui.remove')}] ", remove_h),
            ("class:dim", " "),
            ("class:act", f"[{i18n.t('cli.providers.ui.done')}]", done_h),
            ("class:dim", f"    {i18n.t('cli.providers.ui.controls')}"),
        ])),
    ]))

    Application(layout=layout, key_bindings=kb, style=style, full_screen=True, mouse_support=True).run()
    return result[0]


class AskUbuntuShell:
    def __init__(
        self,
        use_rag: bool = True,
        model_name: str = None,
        embed_model: str = None,
        debug: bool = False,
        provider_base_url: str = None,
        provider_api_key: str = None,
        defer_rag_setup: bool = False,
    ):
        self.session = None
        self.debug = debug
        self._info_visible = False
        self._info_panel_cache = None
        self._info_panel_width = 0
        self._defer_rag_setup = bool(defer_rag_setup and use_rag and provider_base_url is None)
        self._rag_setup_thread = None
        self.engine = ChatEngine(
            model_name=model_name,
            embed_model=embed_model,
            use_rag=use_rag,
            debug=debug,
            provider_base_url=provider_base_url,
            provider_api_key=provider_api_key,
        )

        console.print(f"🔍 {i18n.t('cli.initializing')}", style="#E95420")
        try:
            self.engine.initialize(defer_rag=self._defer_rag_setup)
        except Exception as e:
            console.print(f"❌ {i18n.t('cli.init_failed', error=e)}", style="bold red")
            sys.exit(1)

        if self._defer_rag_setup:
            self._start_background_rag_setup()

        if use_rag and not self.engine.use_rag and not self.engine.is_remote:
            console.print(
                f"⚠️  {i18n.t('cli.rag_unavailable')}",
                style="yellow",
            )

    def _start_background_rag_setup(self):
        """Finish embed model pull + RAG index load without blocking prompt startup."""
        engine_ref = self.engine
        embed_model = engine_ref.embed_model

        def _worker():
            ok, msg = ensure_model_available(embed_model)
            if not ok:
                if self.engine is engine_ref:
                    engine_ref.use_rag = False
                return
            if self.engine is engine_ref:
                engine_ref.load_rag_index(quiet=True)

        t = threading.Thread(target=_worker, name="ask-ubuntu-rag-setup", daemon=True)
        self._rag_setup_thread = t
        t.start()

    def setup_prompt_session(self):
        """Setup prompt_toolkit session with history"""
        from prompt_toolkit.formatted_text import HTML
        snap_common = snap_user_common()
        history_file = (
            Path(snap_common) / "history"
            if snap_common
            else Path.home() / ".ask_ubuntu_history"
        )

        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        @kb.add("f1")
        def _(event):
            self._info_visible = not self._info_visible
            if self._info_visible:
                self._info_panel_cache = ANSI(self._render_info_panel_ansi())
            else:
                self._info_panel_cache = None
            event.app.invalidate()

        def _bottom_toolbar():
            return HTML(
                '<style bg="#2C001E" fg="#E95420">'
                ' <b>F1</b> <style fg="#F7F7F7">{info}</style>'
                ' │ <b>Esc+Enter</b> <style fg="#F7F7F7">{newline}</style>'
                ' │ <b>↑↓</b> <style fg="#F7F7F7">{history}</style>'
                ' │ <b>Esc</b> <style fg="#F7F7F7">{cancel}</style>'
                ' │ <b>/help</b>'
                ' │ <b>/model</b>'
                ' │ <b>/providers</b>'
                ' │ <b>/clear</b>'
                ' │ <b>/exit</b>'
                ' </style>'.format(
                    info=i18n.t('cli.toolbar.info'),
                    newline=i18n.t('cli.toolbar.newline'),
                    history=i18n.t('cli.toolbar.history'),
                    cancel=i18n.t('cli.toolbar.cancel'),
                )
            )

        def _get_prompt_message():
            parts = []
            if self._info_visible:
                # Re-render if terminal width changed since last cache
                current_width = console.width
                if self._info_panel_cache is None or self._info_panel_width != current_width:
                    self._info_panel_cache = ANSI(self._render_info_panel_ansi())
                    self._info_panel_width = current_width
                parts.append(self._info_panel_cache)
            parts.append([("class:prompt", "❯ ")])
            return merge_formatted_text(parts)

        slash_completer = WordCompleter(
            ["/help", "/model", "/providers", "/info", "/clear", "/exit", "/quit"],
            ignore_case=True,
            sentence=True,
        )

        self.session = PromptSession(
            history=FileHistory(str(history_file)),
            style=prompt_style,
            multiline=False,
            key_bindings=kb,
            bottom_toolbar=_bottom_toolbar,
            completer=slash_completer,
        )
        self._prompt_message = _get_prompt_message

    def print_welcome(self):
        """Display welcome message"""
        rag_status = f"✓ {i18n.t('cli.rag_enabled')}" if self.engine.use_rag else f"✗ {i18n.t('cli.rag_disabled')}"

        model_display = self.engine.model_name
        if self.engine.is_remote:
            # Find provider name for display
            providers = get_configured_providers()
            for p in providers:
                if p["base_url"] == self.engine.provider_base_url:
                    model_display = f"☁ {p['name']} / {self.engine.model_name}"
                    break
            else:
                model_display = f"☁ {self.engine.model_name}"

        welcome_text = i18n.t(
            'cli.welcome',
            model=model_display,
            rag_status=rag_status,
        )
        console.print(Panel(Markdown(welcome_text), border_style="#E95420"))
        console.print()

    def _get_system_info_fields(self) -> list:
        """Get system info fields from the engine's indexer."""
        try:
            return self.engine.system_indexer.get_neofetch_fields()
        except Exception:
            return []

    def _build_system_info_table(self) -> Table:
        """Build a Rich Table of grouped system info."""
        fields = self._get_system_info_fields()
        table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
        table.add_column("Label", style="bold #E95420", no_wrap=True)
        table.add_column("Value", style="#F7F7F7")

        if not fields:
            table.add_row(f"[dim]{i18n.t('sidebar.unavailable')}[/]", "")
            return table

        # Build a lookup map
        field_map = {f["label"]: f["value"] for f in fields}

        for group in SYSINFO_GROUPS:
            group_fields = []
            for key in group["keys"]:
                if key in field_map:
                    group_fields.append((key, field_map[key]))
                else:
                    # Prefix match for dynamic labels like "Disk (/home)"
                    for f_label, f_value in field_map.items():
                        if f_label.startswith(key + " ("):
                            group_fields.append((f_label, f_value))

            if not group_fields:
                continue

            group_label = i18n.t(group["label_key"])
            table.add_row(f"[bold #f99b11]{group_label}[/]", "")
            for label, value in group_fields:
                t_label = i18n.t(f"sysinfo.{label}", default=label)
                table.add_row(f"  {t_label}", value)
            table.add_row("", "")  # spacing between groups

        # Any remaining fields not in a group
        grouped_keys = [k for g in SYSINFO_GROUPS for k in g["keys"]]
        ungrouped = [
            f for f in fields
            if not any(f["label"] == k or f["label"].startswith(k + " (") for k in grouped_keys)
        ]
        if ungrouped:
            table.add_row(f"[bold #f99b11]{i18n.t('sidebar.group.other')}[/]", "")
            for f in ungrouped:
                t_label = i18n.t(f"sysinfo.{f['label']}", default=f["label"])
                table.add_row(f"  {t_label}", f["value"])

        return table

    def _build_help_table(self) -> Table:
        """Build a Rich Table of help commands and tips."""
        help_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
        help_table.add_column("Label", style="bold #E95420", no_wrap=True)
        help_table.add_column("Value", style="#F7F7F7")

        help_table.add_row(f"[bold #f99b11]{i18n.t('cli.info_panel.commands_title')}[/]", "")
        help_table.add_row("  /help", i18n.t("cli.help.command.help"))
        help_table.add_row("  /model", i18n.t("cli.help.command.model"))
        help_table.add_row("  /providers", i18n.t("cli.help.command.providers"))
        help_table.add_row("  /info", i18n.t("cli.help.command.info"))
        help_table.add_row("  /clear", i18n.t("cli.help.command.clear"))
        help_table.add_row("  /exit", i18n.t("cli.help.command.exit"))
        help_table.add_row("", "")
        help_table.add_row(f"[bold #f99b11]{i18n.t('cli.info_panel.tips_title')}[/]", "")
        help_table.add_row("  Esc+Enter", i18n.t("cli.help.tip.multiline"))
        help_table.add_row("  ↑ / ↓", i18n.t("cli.help.tip.history"))
        help_table.add_row("  F1", i18n.t("cli.help.tip.info_panel"))
        help_table.add_row("  Esc", i18n.t("cli.help.tip.cancel_query"))
        help_table.add_row("  Ctrl+C", i18n.t("cli.help.tip.cancel_input"))
        help_table.add_row("  Ctrl+D", i18n.t("cli.help.tip.exit"))

        return help_table

    def _render_info_panel_ansi(self) -> str:
        """Render the info panel to an ANSI string for use as prompt_toolkit message."""
        buf = io.StringIO()
        c = Console(
            file=buf,
            force_terminal=True,
            color_system="truecolor",
            width=console.width,
            theme=_ubuntu_theme,
        )

        c.print()
        c.print(self._build_system_info_table())
        c.print(
            Panel(
                self._build_help_table(),
                title=i18n.t('cli.info_panel.help_title'),
                border_style="#E95420",
            )
        )
        c.print()

        return buf.getvalue()

    def handle_special_command(self, user_input: str) -> bool:
        """Handle special commands. Returns True if the app should exit."""
        command = user_input.strip().lower()

        if command in ["/exit", "/quit"]:
            console.print(f"\n👋 {i18n.t('cli.goodbye')}", style="#E95420")
            return True
        elif command == "/clear":
            console.clear()
            self.print_welcome()
        elif command == "/help":
            self.print_welcome()
        elif command == "/model":
            self._run_model_picker()
        elif command == "/providers":
            self._run_provider_manager()
        elif command == "/info":
            self._info_visible = not self._info_visible
            if self._info_visible:
                self._info_panel_cache = ANSI(self._render_info_panel_ansi())
            else:
                self._info_panel_cache = None

        return False

    def _run_model_picker(self):
        """Interactive model picker with live search filtering. Shows local and remote models."""
        with console.status(i18n.t("cli.status.loading_models"), spinner="dots"):
            local_models = get_chat_models(current_model=self.engine.model_name)
            remote_providers = get_configured_providers()

        # Build remote model entries — discover models if no preset list
        remote_models = []
        for provider in remote_providers:
            models = provider.get("models") or []
            if not models:
                with console.status(
                    i18n.t("cli.status.discovering_provider_models", provider=provider["name"]),
                    spinner="dots",
                ):
                    models = discover_provider_models(provider)

            if models:
                for m in models:
                    is_current = (
                        self.engine.is_remote
                        and self.engine.model_name == m["id"]
                        and self.engine.provider_base_url == provider["base_url"]
                    )
                    remote_models.append({
                        "id": m["id"],
                        "display_name": m.get("name", m["id"]),
                        "is_remote": True,
                        "provider_id": provider["id"],
                        "provider_name": provider["name"],
                        "provider_base_url": provider["base_url"],
                        "provider_api_key": provider["api_key"],
                        "current": is_current,
                        "priority": "available",
                        "priority_reason": provider["name"],
                        "downloaded": True,
                        "size_gb": 0.0,
                        "labels": [],
                    })
            else:
                # Discovery failed — offer a manual entry sentinel
                remote_models.append({
                    "id": f"__manual__{provider['id']}",
                    "display_name": i18n.t('cli.remote.enter_model_name'),
                    "is_remote": True,
                    "is_manual_entry": True,
                    "provider_id": provider["id"],
                    "provider_name": provider["name"],
                    "provider_base_url": provider["base_url"],
                    "provider_api_key": provider["api_key"],
                    "current": False,
                    "priority": "available",
                    "priority_reason": provider["name"],
                    "downloaded": True,
                    "size_gb": 0.0,
                    "labels": [],
                })

        all_models = local_models + remote_models

        if not all_models:
            console.print(f"  [red]{i18n.t('cli.model_picker.load_failed')}[/red]")
            if not remote_providers:
                console.print(
                    f"  [dim]{i18n.t('cli.remote.no_providers')}[/dim]"
                )
            return

        chosen = _interactive_model_picker(all_models)

        if chosen is None or chosen["current"]:
            return

        if chosen.get("is_manual_entry"):
            # Picker can't show a text field — prompt for the model name inline
            try:
                model_id = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('cli.model_picker.model_name_for_provider', provider=chosen['provider_name'])}: ")]
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return
            if not model_id:
                return
            chosen = dict(chosen, id=model_id, display_name=model_id, is_manual_entry=False)

        if chosen.get("is_remote"):
            # Switch to remote provider model
            display = f"{chosen['provider_name']} / {chosen['id']}"
            console.print(f"\n  {i18n.t('cli.model_picker.switching', model=display)}", style="dim")
            with console.status(i18n.t("cli.status.initializing"), spinner="dots"):
                provider = {
                    "base_url": chosen["provider_base_url"],
                    "api_key": chosen["provider_api_key"],
                }
                new_engine, err = switch_engine_model(
                    self.engine,
                    chosen["id"],
                    provider=provider,
                )
                if err:
                    console.print(f"\n  ❌ {i18n.t('cli.model_picker.failed', error=err)}", style="bold red")
                    return
            self.engine = new_engine
            console.print(f"  {i18n.t('cli.model_picker.switched', model=display)}", style="bold green")
            console.print()
        else:
            # Local Lemonade model
            # Download if not yet on disk
            if not chosen["downloaded"]:
                ok, msg = _pull_model_with_progress(chosen["id"])
                if not ok:
                    console.print(f"\n  ❌ {i18n.t('cli.model_picker.failed', error=msg)}", style="bold red")
                    return

            console.print(f"\n  {i18n.t('cli.model_picker.switching', model=chosen['id'])}", style="dim")
            with console.status(i18n.t("cli.status.initializing"), spinner="dots"):
                new_engine, err = switch_engine_model(
                    self.engine,
                    chosen["id"],
                )
                if err:
                    console.print(f"\n  ❌ {i18n.t('cli.model_picker.failed', error=err)}", style="bold red")
                    return
            self.engine = new_engine
            console.print(f"  {i18n.t('cli.model_picker.switched', model=chosen['id'])}", style="bold green")
            console.print()

    def _run_provider_manager(self):
        """Interactive provider manager: list, add, edit, remove."""
        while True:
            providers = get_configured_providers()
            try:
                action, idx = _interactive_provider_picker(providers)
            except (KeyboardInterrupt, EOFError):
                break

            if action in ("done", None):
                break
            elif action == "add":
                self._add_provider()
            elif action == "edit":
                if idx is None or not (0 <= idx < len(providers)):
                    console.print(f"  [red]{i18n.t('cli.providers.invalid_number')}[/red]")
                else:
                    self._edit_provider(providers[idx])
            elif action == "remove":
                if idx is None or not (0 <= idx < len(providers)):
                    console.print(f"  [red]{i18n.t('cli.providers.invalid_number')}[/red]")
                else:
                    p = providers[idx]
                    if p["from_env"]:
                        console.print(f"  [yellow]{i18n.t('cli.providers.cannot_remove_env')}[/yellow]")
                    else:
                        delete_provider(p["id"])
                        console.print(
                            f"  [dim]{i18n.t('cli.providers.removed', name=p['name'])}[/dim]"
                        )

        console.print()

    def _add_provider(self):
        """Prompt for details to add a new provider."""
        console.print()
        console.print(f"  [bold]{i18n.t('cli.providers.add_title')}[/bold]")
        console.print()

        # Choose type
        preset_keys = list(PROVIDER_PRESETS.keys())
        options = "  " + "  ".join(
            f"[bold]{i+1}[/bold] {PROVIDER_PRESETS[k]['name']}"
            for i, k in enumerate(preset_keys)
        ) + f"  [bold]{len(preset_keys)+1}[/bold] {i18n.t('cli.providers.custom')}"
        console.print(options)
        console.print()

        try:
            choice = self.session.prompt([("class:prompt", f"  {i18n.t('cli.providers.type_prompt')}: ")]).strip()
            choice_n = int(choice) - 1
        except (KeyboardInterrupt, EOFError):
            return
        except ValueError:
            console.print(f"  [red]{i18n.t('cli.providers.cancelled')}[/red]")
            return

        if 0 <= choice_n < len(preset_keys):
            pid = preset_keys[choice_n]
            preset = PROVIDER_PRESETS[pid]
            console.print(
                f"  [dim]{i18n.t('remote.env_var_hint', env_var=preset['env_var'])}[/dim]"
            )
            console.print()
            try:
                key = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('remote.api_key_label')}: ")]
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return
            if key:
                save_provider(pid, key)
                console.print(
                    f"  [green]{i18n.t('cli.providers.added', name=preset['name'])}[/green]"
                )
        elif choice_n == len(preset_keys):
            # Custom provider
            try:
                name = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('remote.name_label')}: ")]
                ).strip()
                base_url = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('remote.base_url_label')}: ")]
                ).strip()
                key = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('cli.providers.api_key_optional_prompt')}: ")]
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return
            if not base_url:
                console.print(f"  [red]{i18n.t('cli.providers.base_url_required')}[/red]")
                return
            from time import time as _time
            pid = f"custom_{int(_time())}"
            save_provider(pid, key or "none", base_url, name or i18n.t('cli.providers.custom'))
            console.print(
                f"  [green]{i18n.t('cli.providers.added', name=name or i18n.t('cli.providers.custom'))}[/green]"
            )
        else:
            console.print(f"  [red]{i18n.t('cli.providers.cancelled')}[/red]")

        console.print()

    def _edit_provider(self, provider: dict):
        """Prompt for updated values to edit an existing provider."""
        is_custom = provider["id"] not in PROVIDER_PRESETS
        console.print()
        console.print(
            f"  [bold]{i18n.t('cli.providers.edit_title', name=provider['name'])}[/bold]  "
            f"[dim]{i18n.t('cli.providers.keep_hint')}[/dim]"
        )
        console.print()

        try:
            if is_custom:
                raw_name = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('remote.name_label')} [{provider['name']}]: ")]
                ).strip()
                name = raw_name or provider["name"]

                raw_url = self.session.prompt(
                    [("class:prompt", f"  {i18n.t('remote.base_url_label')} [{provider['base_url']}]: ")]
                ).strip()
                base_url = raw_url or provider["base_url"]
            else:
                name = provider["name"]
                base_url = provider.get("base_url")

            # Show a masked hint for the current key
            current_key = provider.get("api_key", "")
            key_hint = ("••••" + current_key[-4:]) if len(current_key) > 4 else "(set)"
            raw_key = self.session.prompt(
                [("class:prompt", f"  {i18n.t('remote.api_key_label')} [{key_hint}]: ")]
            ).strip()
            key = raw_key or current_key

        except (KeyboardInterrupt, EOFError):
            return

        if is_custom:
            save_provider(provider["id"], key, base_url, name)
        else:
            save_provider(provider["id"], key)

        console.print(
            f"  [green]{i18n.t('cli.providers.updated', name=name)}[/green]"
        )
        console.print()

    def get_response(self, user_message: str) -> str:
        """Get a response from the engine and render it to the terminal."""
        result_holder = [None]
        cancelled = [False]
        done_event = threading.Event()

        def run_chat():
            try:
                result_holder[0] = self.engine.chat(user_message)
            except Exception as e:
                result_holder[0] = {"response": f"Error: {e}", "tool_calls": []}
            finally:
                done_event.set()

        def watch_keys():
            try:
                import tty
                import termios
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                try:
                    while not done_event.is_set():
                        r, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if r:
                            ch = sys.stdin.read(1)
                            if ch == '\x1b':
                                # Check if it's a bare ESC vs an escape sequence
                                r2, _, _ = select.select([sys.stdin], [], [], 0.02)
                                if r2:
                                    sys.stdin.read(2)  # consume rest of sequence (e.g. [A)
                                else:
                                    self.engine.abort()
                                    cancelled[0] = True
                                    done_event.set()
                            elif ch == '\x03':  # Ctrl+C
                                self.engine.abort()
                                cancelled[0] = True
                                done_event.set()
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass

        chat_thread = threading.Thread(target=run_chat, daemon=True)
        key_thread = threading.Thread(target=watch_keys, daemon=True)
        chat_thread.start()
        key_thread.start()

        with console.status("[#E95420]Thinking… [dim](Esc to cancel)[/dim][/]", spinner="dots"):
            done_event.wait()

        chat_thread.join(timeout=10)
        key_thread.join(timeout=1)

        if cancelled[0]:
            console.print(f"⚠ {i18n.t('cli.cancelled')}", style="yellow")
            console.print()
            return ""

        result = result_holder[0]
        if result is None:
            return ""

        if self.debug and result["tool_calls"]:
            for tc in result["tool_calls"]:
                console.print(
                    f"  [dim]⚙ {tc['name']}({json.dumps(tc['args'])}) → {tc['result']}[/dim]"
                )

        response_text = result["response"]
        if response_text:
            console.print(Markdown(response_text))
            console.print()

        return response_text

    def run(self):
        """Main interactive loop"""
        self.setup_prompt_session()
        console.clear()
        self.print_welcome()

        try:
            while True:
                try:
                    user_input = self.session.prompt(self._prompt_message)

                    if not user_input.strip():
                        continue

                    if user_input.startswith("/"):
                        if self.handle_special_command(user_input):
                            break
                        continue

                    console.print()
                    self.get_response(user_input)
                    console.print("\n")

                except KeyboardInterrupt:
                    console.print(f"\n💡 {i18n.t('cli.exit_hint')}", style="yellow")
                    continue
                except EOFError:
                    console.print(f"\n👋 {i18n.t('cli.goodbye')}", style="#E95420")
                    break

        except Exception as e:
            console.print(f"\n❌ {i18n.t('cli.fatal_error', error=str(e))}", style="bold red")
            sys.exit(1)
        finally:
            if not self.engine.is_remote:
                unload_model(self.engine.model_name)
                if self.engine.use_rag:
                    unload_model(self.engine.embed_model)


def _pull_model_with_progress(model_name: str) -> tuple:
    """Pull a model with a Rich progress bar, blocking input until complete."""
    task_id = None
    progress = None

    def _on_progress(status: str, completed: int, total: int):
        nonlocal task_id, progress
        if status == "complete":
            if progress is not None:
                if task_id is not None:
                    progress.update(task_id, completed=total or 1)
                progress.stop()
                progress = None
            return

        if progress is None:
            if total > 0:
                progress = Progress(
                    SpinnerColumn(style="#E95420"),
                    TextColumn("[#E95420]{task.description}"),
                    BarColumn(bar_width=40, style="#5E2750", complete_style="#E95420"),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    console=console,
                )
            else:
                progress = Progress(
                    SpinnerColumn(style="#E95420"),
                    TextColumn("[#E95420]{task.description}"),
                    console=console,
                )
            progress.start()
            task_id = progress.add_task(
                i18n.t('cli.downloading', model=model_name),
                total=total if total > 0 else None,
            )
        elif task_id is not None:
            if total > 0 and progress.tasks[task_id].total is None:
                # Upgrade to determinate progress now that we know the total
                progress.stop()
                progress = Progress(
                    SpinnerColumn(style="#E95420"),
                    TextColumn("[#E95420]{task.description}"),
                    BarColumn(bar_width=40, style="#5E2750", complete_style="#E95420"),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    console=console,
                )
                progress.start()
                task_id = progress.add_task(
                    i18n.t('cli.downloading', model=model_name),
                    total=total,
                    completed=completed,
                )
            else:
                progress.update(task_id, completed=completed)

    return ensure_model_available(model_name, progress_callback=_on_progress)


def main():
    """Entry point"""
    i18n.init()

    parser = argparse.ArgumentParser(
        description=i18n.t('cli.arg_description'),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ask-ubuntu                                        # Use default local model
  ask-ubuntu --model user.Llama-3.3-70B-Instruct-GGUF  # Specific local model
  ask-ubuntu --provider anthropic                   # Use Anthropic (needs ANTHROPIC_API_KEY)
  ask-ubuntu --provider openai --model gpt-4o       # Specific remote model
  ask-ubuntu --no-rag                               # Disable documentation search
        """,
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help=i18n.t('cli.arg_model'),
    )
    parser.add_argument(
        "--embed-model",
        default=None,
        help=i18n.t('cli.arg_embed_model'),
    )
    parser.add_argument(
        "--no-rag", action="store_true", help=i18n.t('cli.arg_no_rag')
    )
    parser.add_argument(
        "--debug", action="store_true", help=i18n.t('cli.arg_debug')
    )
    parser.add_argument(
        "--provider",
        "-p",
        default=None,
        help=i18n.t('cli.arg_provider'),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=i18n.t('cli.arg_api_key'),
    )

    args = parser.parse_args()

    # ── Remote provider path ──────────────────────────────────────────────
    if args.provider:
        selection, err = resolve_explicit_provider_startup(
            provider_id=args.provider,
            model_override=args.model,
            api_key_override=args.api_key,
        )
        if err and err["code"] == "unknown_provider":
            console.print(
                f"\n❌ {i18n.t('cli.remote.unknown_provider', provider=args.provider, known=err['known'])}",
                style="bold red",
            )
            sys.exit(1)
        if err and err["code"] == "no_api_key":
            console.print(
                f"\n❌ {i18n.t('cli.remote.no_api_key', provider=args.provider, env_var=err['env_var'])}",
                style="bold red",
            )
            sys.exit(1)
        if err and err["code"] == "no_models":
            console.print(
                f"\n❌ {i18n.t('cli.remote.no_models_for_provider', provider=args.provider)}",
                style="bold red",
            )
            sys.exit(1)

        console.print(
            f"  {i18n.t('cli.remote.using', provider=selection.provider_name, model=selection.model_id)}",
            style="#0073E5",
        )

        shell = AskUbuntuShell(
            use_rag=False,
            model_name=selection.model_id,
            debug=args.debug,
            provider_base_url=selection.base_url,
            provider_api_key=selection.api_key,
        )
        shell.run()
        return

    # ── Local Lemonade path ───────────────────────────────────────────────
    selection = resolve_local_models(
        requested_model=args.model,
        requested_embed_model=args.embed_model,
    )
    chat_model = selection.chat_model
    embed_model_name = selection.embed_model

    # Ensure chat model is available via Lemonade before starting
    ok, msg = _pull_model_with_progress(chat_model)
    if not ok:
        # Try auto-fallback to a configured remote provider
        p, fallback_model = pick_remote_fallback(chat_model)
        if p:
            console.print(
                f"\n⚠️  {i18n.t('cli.remote.fallback', provider=p['name'], model=fallback_model)}",
                style="yellow",
            )
            shell = AskUbuntuShell(
                use_rag=False,
                model_name=fallback_model,
                debug=args.debug,
                provider_base_url=p["base_url"],
                provider_api_key=p["api_key"],
            )
            shell.run()
            return

        console.print(f"\n❌ {msg}", style="bold red")
        console.print(f"   {i18n.t('cli.lemonade_hint')}\n", style="yellow")
        sys.exit(1)

    shell = AskUbuntuShell(
        use_rag=not args.no_rag,
        model_name=chat_model,
        embed_model=embed_model_name,
        debug=args.debug,
        defer_rag_setup=not args.no_rag,
    )
    shell.run()


if __name__ == "__main__":
    main()
