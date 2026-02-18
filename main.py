#!/usr/bin/env python3
"""
Ask Ubuntu - An interactive shell tool for asking questions about Ubuntu
"""

import sys
import os
import json
import subprocess
import platform
import warnings
import argparse
from typing import List, Dict, Optional
from pathlib import Path
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown, CodeBlock as _RichCodeBlock
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from pygments.style import Style as _PygmentsStyle
from pygments.token import (
    Token, Comment, Keyword, Name, String, Number, Operator, Generic, Error
)
from rich.theme import Theme
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings
import requests

from rag_indexer import RAGIndexer
from system_indexer import SystemIndexer

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

# Model configuration
LEMONADE_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_MODEL_NAME = "Qwen3-4B-Instruct-2507-GGUF"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1-GGUF"

# Tools the LLM can call to look up package information client-side
PACKAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_snap",
            "description": (
                "Check whether a snap package is installed on this system and/or "
                "available in the snap store."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The snap package name"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_apt",
            "description": (
                "Check whether an apt/debian package is installed on this system "
                "and/or available in the apt cache."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The apt package name"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_installed_snaps",
            "description": "Return all snap packages currently installed on this system with their versions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# Initialize the OpenAI client to use Lemonade Server
def create_client(model_name: str = None):
    """Create OpenAI client with specified model"""
    return OpenAI(
        base_url=f"{LEMONADE_BASE_URL}", api_key="lemonade"  # required but unused
    )


def get_system_context() -> str:
    """Gather system information to provide context to the assistant"""
    context_parts = []

    try:
        # Get Ubuntu version
        result = subprocess.run(
            ["lsb_release", "-d"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            ubuntu_version = result.stdout.strip().replace("Description:\t", "")
            context_parts.append(f"Ubuntu Version: {ubuntu_version}")
    except:
        pass

    try:
        # Get kernel version
        kernel = platform.release()
        context_parts.append(f"Kernel: {kernel}")
    except:
        pass

    try:
        # Check if snap is available
        result = subprocess.run(
            ["snap", "--version"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            snap_version = result.stdout.split("\n")[0].replace("snap    ", "")
            context_parts.append(f"Snap: {snap_version}")
    except:
        pass

    try:
        # Get shell
        shell = os.environ.get("SHELL", "").split("/")[-1]
        if shell:
            context_parts.append(f"Shell: {shell}")
    except:
        pass

    try:
        # Check desktop environment
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        if desktop:
            context_parts.append(f"Desktop: {desktop}")
    except:
        pass

    return "\n".join(context_parts)


SYSTEM_PROMPT_TEMPLATE = """You are Ask Ubuntu Assistant, an expert guide for Ubuntu Linux users.

## CRITICAL ASSUMPTIONS - MUST FOLLOW

This is a standard Ubuntu installation. The following tools are ALREADY INSTALLED and WORKING:
- apt, apt-get, dpkg (package management)
- snap, snapd (snap package system - RUNNING by default)
- systemctl, systemd (service management)
- Core utilities: bash, sudo, grep, find, sed, awk, curl, wget, ufw, ssh
- Python 3, pip3

## CRITICAL RULES

**ABSOLUTELY NEVER:**
- ❌ Suggest installing apt, apt-get, snapd, or snap
- ❌ Say "first check if snapd is installed" or "ensure apt is available"
- ❌ Include steps like "sudo apt install snapd" or "sudo systemctl start snapd"
- ❌ Add verification steps for core system tools

**ALWAYS:**
- ✅ Jump directly to the solution using these tools
- ✅ Assume snapd service is running and functional
- ✅ Use apt/snap commands directly without preamble

**Examples:**
❌ WRONG: "First, ensure snapd is installed: `sudo apt install snapd`"
❌ WRONG: "Make sure snap is running: `sudo systemctl start snapd`"
✅ CORRECT: "Install the app: `sudo snap install terminal-fun`"
✅ CORRECT: "Install Docker: `sudo apt install docker.io`"

## User's System Information
{system_context}

**Package Lookup Tools:**
You have tools to check package status on this system — use them instead of guessing or asking the user.

- `check_snap(name)` — is a snap installed? what version? is it in the store?
- `check_apt(name)` — is an apt package installed? is it available in the cache?
- `list_installed_snaps()` — full list of installed snaps with versions

**CRITICAL: DO NOT ask the user what's installed. Call the tools to find out.**

When a question involves a specific package:
- Call `check_snap` and/or `check_apt` before answering
- If installed, use update/manage commands (e.g., `sudo snap refresh <name>`)
- If not installed but available, recommend the appropriate install command
- You may call multiple tools in one response if needed

## Retrieved Documentation
You have access to relevant Ubuntu documentation and man pages for this query.
Use this information to provide accurate, authoritative answers:

{retrieved_docs}

## Your Role
Help users accomplish tasks on their Ubuntu system with clear, direct instructions.
When relevant documentation is provided above, reference it and use it as the authoritative source.

## When Answering Questions
- Use the retrieved documentation when available to provide accurate information
- Jump directly to the solution - don't waste time on setup for core tools
- Provide step-by-step instructions tailored to the user's Ubuntu version
- Include relevant terminal commands with explanations
- For package installations, show the direct install command (apt or snap)
- Prefer apt for traditional system packages, snap for newer apps and developer tools
- Mention important prerequisites ONLY for non-standard software
- Suggest best practices and alternative approaches when relevant
- Use markdown formatting for better readability
- Keep answers concise but complete
- If you're unsure, acknowledge limitations honestly

Focus on practical, actionable advice that gets users to their goal quickly."""


def ensure_model_available(model_name: str) -> bool:
    """Ensure the model is available in Lemonade, pulling it if necessary."""
    try:
        response = requests.get(f"{LEMONADE_BASE_URL}/models", timeout=10)
        response.raise_for_status()
        models = response.json().get("data", [])

        for model in models:
            if model["id"] == model_name:
                if model.get("downloaded"):
                    return True
                break

        # Model not downloaded yet — pull it via Lemonade
        console.print(
            f"\n📥 Pulling model via Lemonade: {model_name}", style="#E95420 bold"
        )
        console.print(f"   This may take a few minutes...\n", style="yellow")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Pulling {model_name}...", total=None)
            pull_response = requests.post(
                f"{LEMONADE_BASE_URL}/pull",
                json={"model": model_name},
                timeout=600,
            )
            pull_response.raise_for_status()
            progress.update(task, completed=True)

        console.print(f"✓ Model ready: {model_name}\n", style="green bold")
        return True

    except requests.ConnectionError:
        console.print(
            "\n❌ Cannot connect to Lemonade server at localhost:8000", style="bold red"
        )
        console.print("   Make sure lemonade-server is running.\n", style="yellow")
        return False
    except Exception as e:
        console.print(
            f"\n❌ Error ensuring model availability: {str(e)}", style="bold red"
        )
        return False


class AskUbuntuShell:
    def __init__(
        self,
        use_rag: bool = True,
        model_name: str = None,
        embed_model: str = None,
        debug: bool = False,
    ):
        self.conversation_history: List[Dict[str, str]] = []
        self.session = None
        self.use_rag = use_rag
        self.rag_indexer = None
        self.system_indexer = None
        self.model_name = model_name or DEFAULT_MODEL_NAME
        self.embed_model = embed_model or DEFAULT_EMBED_MODEL
        self.debug = debug
        self.client = create_client(self.model_name)

        # Initialize system indexer
        try:
            self.system_indexer = SystemIndexer()
            self.system_indexer.load_or_collect()
            self.system_context = self.system_indexer.get_context_summary()
        except Exception as e:
            console.print(f"⚠️  Failed to collect system info: {e}", style="yellow")
            self.system_context = get_system_context()  # Fallback to basic context

        # Initialize RAG if enabled
        if self.use_rag:
            try:
                console.print(
                    "🔍 Initializing documentation search...", style="#E95420"
                )
                self.rag_indexer = RAGIndexer(
                    base_url=LEMONADE_BASE_URL, embed_model=self.embed_model
                )
                self.rag_indexer.load_or_create_index()
            except Exception as e:
                console.print(f"⚠️  Failed to initialize RAG: {e}", style="yellow")
                console.print(
                    "   Continuing without documentation search.\n", style="yellow"
                )
                self.use_rag = False

    def setup_prompt_session(self):
        """Setup prompt_toolkit session with history"""
        history_file = Path.home() / ".ask_ubuntu_history"

        # Key bindings for multi-line support
        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        self.session = PromptSession(
            history=FileHistory(str(history_file)),
            style=prompt_style,
            multiline=False,
            key_bindings=kb,
        )

    def print_welcome(self):
        """Display welcome message"""
        rag_status = "✓ Enabled" if self.use_rag else "✗ Disabled"

        welcome_text = f"""
# 🟠 Ask Ubuntu

Ask me anything about using Ubuntu! I can help you with:
- System administration tasks
- Package management (apt, snap)
- Configuration and customization
- Troubleshooting issues
- Command line tips and tricks

**Model:** `{self.model_name}`
**Documentation Search (RAG):** {rag_status}

**Special commands:**
- `/help` - Show this help message
- `/clear` - Clear the screen
- `/exit` or `/quit` - Exit the assistant
- `Ctrl+C` - Cancel current input
- `Ctrl+D` - Exit

**Tips:**
- Press `Esc` then `Enter` for multi-line input
- Use `↑` and `↓` to navigate command history
- Answers are grounded in actual Ubuntu man pages and documentation
"""
        console.print(Panel(Markdown(welcome_text), border_style="#E95420"))
        console.print()

    def handle_special_command(self, user_input: str) -> bool:
        """Handle special commands. Returns True if command was handled."""
        command = user_input.strip().lower()

        if command in ["/exit", "/quit"]:
            console.print("\n👋 Goodbye!", style="#E95420")
            return True
        elif command == "/clear":
            console.clear()
            self.print_welcome()
            return False
        elif command == "/help":
            self.print_welcome()
            return False

        return False

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a package lookup tool and return a JSON string result"""
        try:
            if name == "check_snap":
                pkg_name = args["name"]
                installed = self.system_indexer.is_snap_installed(pkg_name)
                available = self.system_indexer.is_snap_available(pkg_name)
                result = {"installed": installed, "available_in_store": available}
                if installed:
                    snaps = self.system_indexer.system_info.get("packages", {}).get(
                        "snap_packages", []
                    )
                    pkg = next((p for p in snaps if p["name"] == pkg_name), None)
                    result["version"] = pkg["version"] if pkg else "unknown"
                return json.dumps(result)

            elif name == "check_apt":
                pkg_name = args["name"]
                return json.dumps(
                    {
                        "installed": self.system_indexer.is_apt_installed(pkg_name),
                        "available_in_cache": self.system_indexer.is_apt_available(
                            pkg_name
                        ),
                    }
                )

            elif name == "list_installed_snaps":
                snaps = self.system_indexer.system_info.get("packages", {}).get(
                    "snap_packages", []
                )
                return json.dumps(snaps)

            return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def get_response(self, user_message: str) -> str:
        """Get a response from the model, executing tool calls as needed"""
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": user_message})

        # Retrieve relevant documentation if RAG is enabled
        retrieved_docs = ""
        if self.use_rag and self.rag_indexer:
            try:
                results = self.rag_indexer.search(user_message, top_k=3)
                if results:
                    doc_parts = []
                    for doc, score in results:
                        doc_parts.append(
                            f"### {doc.title} (from {doc.source})\n{doc.content[:1000]}"
                        )
                    retrieved_docs = "\n\n".join(doc_parts)
            except Exception as e:
                console.print(f"⚠️  Search error: {e}", style="dim yellow")

        # Build system prompt
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            system_context=self.system_context,
            retrieved_docs=(
                retrieved_docs
                if retrieved_docs
                else "No specific documentation retrieved for this query."
            ),
        )

        messages = [
            {"role": "system", "content": system_prompt}
        ] + self.conversation_history

        try:
            # Tool-calling loop: keep going until the model stops calling tools
            while True:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=PACKAGE_TOOLS,
                    stream=False,
                )
                msg = response.choices[0].message

                if msg.tool_calls:
                    # Append assistant message with tool calls
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        args = json.loads(tc.function.arguments)
                        result = self._execute_tool(tc.function.name, args)
                        if self.debug:
                            console.print(
                                f"  [dim]⚙ {tc.function.name}({tc.function.arguments}) → {result}[/dim]"
                            )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            }
                        )
                else:
                    # Final answer — render as markdown
                    full_response = msg.content or ""
                    console.print(Markdown(full_response))
                    console.print()
                    self.conversation_history.append(
                        {"role": "assistant", "content": full_response}
                    )
                    return full_response

        except Exception as e:
            error_msg = f"❌ Error: {str(e)}"
            console.print(error_msg, style="bold red")
            return ""

    def run(self):
        """Main interactive loop"""
        self.setup_prompt_session()
        console.clear()
        self.print_welcome()

        try:
            while True:
                try:
                    # Get user input
                    user_input = self.session.prompt(
                        [
                            ("class:prompt", "❯ "),
                        ]
                    )

                    # Skip empty input
                    if not user_input.strip():
                        continue

                    # Handle special commands
                    if user_input.startswith("/"):
                        if self.handle_special_command(user_input):
                            break
                        continue

                    # Print user message
                    console.print()

                    # Get and display response
                    self.get_response(user_input)
                    console.print("\n")

                except KeyboardInterrupt:
                    console.print("\n💡 Use /exit or Ctrl+D to quit", style="yellow")
                    continue
                except EOFError:
                    console.print("\n👋 Goodbye!", style="#E95420")
                    break

        except Exception as e:
            console.print(f"\n❌ Fatal error: {str(e)}", style="bold red")
            sys.exit(1)


def main():
    """Entry point"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Ask Ubuntu - AI-powered assistant for Ubuntu",
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
        default=DEFAULT_MODEL_NAME,
        help=f"Model to use (default: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument(
        "--embed-model",
        default=DEFAULT_EMBED_MODEL,
        help=f"Embedding model to use for RAG (default: {DEFAULT_EMBED_MODEL})",
    )
    parser.add_argument(
        "--no-rag", action="store_true", help="Disable documentation search (RAG)"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Show tool calls and other debug output"
    )

    args = parser.parse_args()

    # Ensure chat model is available via Lemonade before starting
    if not ensure_model_available(args.model):
        console.print("Failed to ensure model is available. Exiting.", style="bold red")
        sys.exit(1)

    # Ensure embedding model is available via Lemonade before starting
    if not args.no_rag and not ensure_model_available(args.embed_model):
        console.print(
            "Failed to ensure embedding model is available. Exiting.", style="bold red"
        )
        sys.exit(1)

    # Start the interactive shell
    shell = AskUbuntuShell(
        use_rag=not args.no_rag,
        model_name=args.model,
        embed_model=args.embed_model,
        debug=args.debug,
    )
    shell.run()


if __name__ == "__main__":
    main()
