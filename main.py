#!/usr/bin/env python3
"""
Ask Ubuntu - An interactive shell tool for asking questions about Ubuntu
"""

import io
import sys
import json
import argparse
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
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import ANSI, merge_formatted_text

from chat_engine import (
    ChatEngine,
    DEFAULT_MODEL_NAME,
    DEFAULT_EMBED_MODEL,
    LLM_TIER_MAP,
    EMBED_TIER_MAP,
    ensure_model_available,
)
from system_indexer import SystemIndexer
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
    "markdown.code":       "bold #fe8019",   # inline code: warm orange
    "markdown.code_block": "",               # handled by _BorderedCodeBlock
    "markdown.list":       "#E95420",        # list bullets: Ubuntu orange
    "markdown.link":       "bold #fabd2f",   # links: yellow
    "markdown.link_url":   "underline #fabd2f",
})
console = Console(theme=_ubuntu_theme)


class _UbuntuCodeStyle(_PygmentsStyle):
    """Warm-toned syntax theme — no cyan/teal, transparent background."""
    background_color = "default"
    default_style = ""
    styles = {
        Token:                "#ebdbb2",        # warm off-white default
        Comment:              "#928374 italic",  # muted brown-gray
        Comment.PreProc:      "#d79921",
        Keyword:              "#E95420",         # Ubuntu orange
        Keyword.Constant:     "#d3869b",         # rose
        Operator:             "#d79921",         # yellow
        Operator.Word:        "#E95420",
        Name.Builtin:         "#fe8019",         # warm orange
        Name.Function:        "#fabd2f",         # yellow
        Name.Class:           "#fabd2f",
        Name.Namespace:       "#fabd2f",
        Name.Variable:        "#ebdbb2",         # default (no teal)
        Name.Tag:             "#E95420",
        Name.Attribute:       "#fabd2f",
        Name.Decorator:       "#fe8019",
        String:               "#b8bb26",         # olive yellow-green
        String.Escape:        "#fe8019",
        Number:               "#d3869b",         # rose
        Generic.Heading:      "#ebdbb2 bold",
        Generic.Prompt:       "#a89984",
        Generic.Output:       "#d5c4a1",
        Generic.Error:        "#fb4934",
        Error:                "#fb4934",
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


class AskUbuntuShell:
    def __init__(
        self,
        use_rag: bool = True,
        model_name: str = None,
        embed_model: str = None,
        debug: bool = False,
    ):
        self.session = None
        self.debug = debug
        self._info_visible = False
        self._info_panel_cache = None
        self._info_panel_width = 0
        self.engine = ChatEngine(
            model_name=model_name,
            embed_model=embed_model,
            use_rag=use_rag,
            debug=debug,
        )

        console.print(f"🔍 {i18n.t('cli.initializing')}", style="#E95420")
        try:
            self.engine.initialize()
        except Exception as e:
            console.print(f"❌ {i18n.t('cli.init_failed', error=e)}", style="bold red")
            sys.exit(1)

        if use_rag and not self.engine.use_rag:
            console.print(
                f"⚠️  {i18n.t('cli.rag_unavailable')}",
                style="yellow",
            )

    def setup_prompt_session(self):
        """Setup prompt_toolkit session with history"""
        import os
        from prompt_toolkit.formatted_text import HTML
        snap_common = os.environ.get("SNAP_USER_COMMON")
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
                ' <b>F1</b> <style fg="#ebdbb2">{info}</style>'
                ' │ <b>Esc+Enter</b> <style fg="#ebdbb2">{newline}</style>'
                ' │ <b>↑↓</b> <style fg="#ebdbb2">{history}</style>'
                ' │ <b>/help</b>'
                ' │ <b>/clear</b>'
                ' │ <b>/exit</b>'
                ' </style>'.format(
                    info=i18n.t('cli.toolbar.info'),
                    newline=i18n.t('cli.toolbar.newline'),
                    history=i18n.t('cli.toolbar.history'),
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

        self.session = PromptSession(
            history=FileHistory(str(history_file)),
            style=prompt_style,
            multiline=False,
            key_bindings=kb,
            bottom_toolbar=_bottom_toolbar,
        )
        self._prompt_message = _get_prompt_message

    def print_welcome(self):
        """Display welcome message"""
        rag_status = f"✓ {i18n.t('cli.rag_enabled')}" if self.engine.use_rag else f"✗ {i18n.t('cli.rag_disabled')}"

        welcome_text = i18n.t(
            'cli.welcome',
            model=self.engine.model_name,
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
        table.add_column("Value", style="#ebdbb2")

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
            table.add_row(f"[bold #fabd2f]{group_label}[/]", "")
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
            table.add_row(f"[bold #fabd2f]{i18n.t('sidebar.group.other')}[/]", "")
            for f in ungrouped:
                t_label = i18n.t(f"sysinfo.{f['label']}", default=f["label"])
                table.add_row(f"  {t_label}", f["value"])

        return table

    def _build_help_table(self) -> Table:
        """Build a Rich Table of help commands and tips."""
        help_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
        help_table.add_column("Label", style="bold #E95420", no_wrap=True)
        help_table.add_column("Value", style="#ebdbb2")

        help_table.add_row(f"[bold #fabd2f]{i18n.t('cli.info_panel.commands_title')}[/]", "")
        help_table.add_row("  /help", "Show help message")
        help_table.add_row("  /info", "Toggle this info panel")
        help_table.add_row("  /clear", "Clear the screen")
        help_table.add_row("  /exit", "Exit the assistant")
        help_table.add_row("", "")
        help_table.add_row(f"[bold #fabd2f]{i18n.t('cli.info_panel.tips_title')}[/]", "")
        help_table.add_row("  Esc+Enter", "Multi-line input")
        help_table.add_row("  ↑ / ↓", "Navigate history")
        help_table.add_row("  F1", "Toggle this panel")
        help_table.add_row("  Ctrl+C", "Cancel current input")
        help_table.add_row("  Ctrl+D", "Exit")

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
        elif command == "/info":
            self._info_visible = not self._info_visible
            if self._info_visible:
                self._info_panel_cache = ANSI(self._render_info_panel_ansi())
            else:
                self._info_panel_cache = None

        return False

    def get_response(self, user_message: str) -> str:
        """Get a response from the engine and render it to the terminal."""
        with console.status("[#E95420]Thinking…[/]", spinner="dots"):
            result = self.engine.chat(user_message)

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
                    BarColumn(bar_width=40, style="#4a1535", complete_style="#E95420"),
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
                    BarColumn(bar_width=40, style="#4a1535", complete_style="#E95420"),
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
  ask-ubuntu                                    # Use default model
  ask-ubuntu --model user.Llama-3.3-70B-Instruct-GGUF  # Use specific model
  ask-ubuntu --no-rag                           # Disable documentation search
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

    args = parser.parse_args()

    # Determine models via hardware tier detection (unless explicitly specified)
    if args.model is None or (not args.no_rag and args.embed_model is None):
        si = SystemIndexer()
        tier = si.get_hardware_tier()
        chat_model = args.model if args.model is not None else LLM_TIER_MAP.get(tier, DEFAULT_MODEL_NAME)
        embed_model_name = args.embed_model if args.embed_model is not None else EMBED_TIER_MAP.get(tier, DEFAULT_EMBED_MODEL)
    else:
        chat_model = args.model
        embed_model_name = args.embed_model if args.embed_model is not None else DEFAULT_EMBED_MODEL

    # Ensure chat model is available via Lemonade before starting
    ok, msg = _pull_model_with_progress(chat_model)
    if not ok:
        console.print(f"\n❌ {msg}", style="bold red")
        console.print(f"   {i18n.t('cli.lemonade_hint')}\n", style="yellow")
        sys.exit(1)

    # Ensure embedding model is available via Lemonade before starting
    if not args.no_rag:
        ok, msg = _pull_model_with_progress(embed_model_name)
        if not ok:
            console.print(f"\n❌ {msg}", style="bold red")
            sys.exit(1)

    shell = AskUbuntuShell(
        use_rag=not args.no_rag,
        model_name=chat_model,
        embed_model=embed_model_name,
        debug=args.debug,
    )
    shell.run()


if __name__ == "__main__":
    main()
