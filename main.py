#!/usr/bin/env python3
"""
Ubuntu Ask - An interactive shell tool for asking questions about Ubuntu
"""

import sys
import os
import subprocess
import platform
import warnings
import argparse
from typing import List, Dict, Optional
from pathlib import Path
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings
from huggingface_hub import hf_hub_download, snapshot_download

# Suppress all model loading output
warnings.filterwarnings('ignore')
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['HF_HUB_VERBOSITY'] = 'error'

# Disable HuggingFace Hub warnings
import logging
logging.getLogger('huggingface_hub').setLevel(logging.ERROR)

from rag_indexer import RAGIndexer
from system_indexer import SystemIndexer

# Initialize Rich console
console = Console()

# Custom prompt style
prompt_style = Style.from_dict(
    {
        "prompt": "#E95420 bold",  # Ubuntu orange
        "input": "#ffffff",
    }
)

# Model configuration
MODEL_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
MODEL_FILE = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_NAME = "user.Qwen2.5-Coder-7B-Instruct-GGUF"

# Initialize the OpenAI client to use Lemonade Server
def create_client(model_name: str = None):
    """Create OpenAI client with specified model"""
    return OpenAI(
        base_url="http://localhost:8000/api/v1",
        api_key="lemonade"  # required but unused
    )

def get_system_context() -> str:
    """Gather system information to provide context to the assistant"""
    context_parts = []

    try:
        # Get Ubuntu version
        result = subprocess.run(
            ["lsb_release", "-d"],
            capture_output=True,
            text=True,
            timeout=2
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
            ["snap", "--version"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            snap_version = result.stdout.split('\n')[0].replace("snap    ", "")
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


SYSTEM_PROMPT_TEMPLATE = """You are Ubuntu Ask Assistant, an expert guide for Ubuntu Linux users.

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

**Installed Packages Context:**
The system information above includes COMPLETE and ACCURATE information about installed packages.
- "Installed snaps" list shows ALL snap packages currently installed
- "Available snaps in cache" shows snaps that can be installed
- "Key packages installed" shows important apt packages

**CRITICAL: DO NOT ask the user what's installed - you already know from the system context above.**

When the user asks about a package:
- If it's in "Installed snaps", it IS installed via snap - use snap commands (e.g., `sudo snap refresh <package>`)
- If it's NOT in "Installed snaps" but IS in "Available snaps in cache", recommend snap installation
- Never ask "Is it installed as a snap?" - you already have this information

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


def ensure_model_downloaded():
    """Download the model if it's not already in the snap's HuggingFace cache"""
    try:
        # Check lemonade-server snap cache location
        snap_cache_dir = Path("/var/snap/lemonade-server/common/.cache/huggingface/hub")
        model_cache_name = f"models--{MODEL_REPO.replace('/', '--')}"
        snap_model_path = snap_cache_dir / model_cache_name

        # Also check user's local cache
        user_cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        user_model_path = user_cache_dir / model_cache_name

        if snap_model_path.exists():
            console.print(
                f"✓ Model found in lemonade-server cache: {MODEL_REPO}", style="green"
            )
            return True

        # Model not in snap cache, check if it's in user cache
        if user_model_path.exists():
            console.print(f"✓ Model found in user cache: {MODEL_REPO}", style="green")
            console.print(
                f"⚠️  Note: Model is in user cache, not lemonade-server cache",
                style="yellow",
            )
            console.print(
                f"   You may need to copy it to: {snap_cache_dir}", style="yellow"
            )
            console.print(
                f"   Or use: sudo HF_HOME=/var/snap/lemonade-server/common/.cache/huggingface huggingface-cli download {MODEL_REPO} {MODEL_FILE}\n",
                style="dim",
            )
            return True

        # Model not found anywhere, download to user cache first
        console.print(f"\n📥 Downloading model: {MODEL_REPO}", style="#E95420 bold")
        console.print(f"   File: {MODEL_FILE}", style="#E95420")
        console.print(f"   This may take a few minutes...\n", style="yellow")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Downloading {MODEL_FILE}...", total=None)

            # Download to user's cache (doesn't require sudo)
            model_path = hf_hub_download(
                repo_id=MODEL_REPO,
                filename=MODEL_FILE,
                repo_type="model",
            )

            progress.update(task, completed=True)

        console.print(f"\n✓ Model downloaded successfully!", style="green bold")
        console.print(f"   Location: {model_path}\n", style="dim")

        # Provide instructions for moving to snap cache
        console.print(f"📋 Next steps:", style="#E95420 bold")
        console.print(f"   1. Copy model to lemonade-server cache:", style="#E95420")
        console.print(f"      sudo mkdir -p {snap_cache_dir}", style="white")
        console.print(
            f"      sudo cp -r {user_model_path} {snap_cache_dir}/", style="white"
        )
        console.print(f"   2. Or re-download directly to snap cache:", style="#E95420")
        console.print(
            f"      sudo HF_HOME=/var/snap/lemonade-server/common/.cache/huggingface huggingface-cli download {MODEL_REPO} {MODEL_FILE}\n",
            style="white",
        )

        return True

    except Exception as e:
        console.print(f"\n❌ Error downloading model: {str(e)}", style="bold red")
        console.print(
            f"   Please check your internet connection and try again.\n", style="yellow"
        )
        return False


class UbuntuAskShell:
    def __init__(self, use_rag: bool = True, model_name: str = None):
        self.conversation_history: List[Dict[str, str]] = []
        self.session = None
        self.use_rag = use_rag
        self.rag_indexer = None
        self.system_indexer = None
        self.model_name = model_name or DEFAULT_MODEL_NAME
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
                console.print("🔍 Initializing documentation search...", style="#E95420")
                self.rag_indexer = RAGIndexer()
                self.rag_indexer.load_or_create_index()
            except Exception as e:
                console.print(f"⚠️  Failed to initialize RAG: {e}", style="yellow")
                console.print("   Continuing without documentation search.\n", style="yellow")
                self.use_rag = False

    def setup_prompt_session(self):
        """Setup prompt_toolkit session with history"""
        history_file = Path.home() / ".ubuntu_ask_history"

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
# 🟠 Ubuntu Ask

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

    def get_response(self, user_message: str) -> str:
        """Get streaming response from the model"""
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
                        doc_parts.append(f"### {doc.title} (from {doc.source})\n{doc.content[:1000]}")
                    retrieved_docs = "\n\n".join(doc_parts)
            except Exception as e:
                console.print(f"⚠️  Search error: {e}", style="dim yellow")

        # Build system prompt with retrieved docs
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            system_context=self.system_context,
            retrieved_docs=retrieved_docs if retrieved_docs else "No specific documentation retrieved for this query."
        )

        # Prepare messages with system prompt (includes system context and retrieved docs)
        messages = [
            {"role": "system", "content": system_prompt}
        ] + self.conversation_history

        try:
            # Create streaming completion
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=True,
            )

            full_response = ""

            # Display streaming response - print immediately for speed
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    console.print(content, end="", markup=False, highlight=False)

            console.print("\n")  # Newline after streaming

            # Add assistant response to history
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
        description='Ubuntu Ask - AI-powered assistant for Ubuntu',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uask                                    # Use default model
  uask --model user.Llama-3.3-70B-Instruct-GGUF  # Use specific model
  uask --no-rag                           # Disable documentation search
        """
    )
    parser.add_argument(
        '--model', '-m',
        default=DEFAULT_MODEL_NAME,
        help=f'Model to use (default: {DEFAULT_MODEL_NAME})'
    )
    parser.add_argument(
        '--no-rag',
        action='store_true',
        help='Disable documentation search (RAG)'
    )
    
    args = parser.parse_args()

    # Ensure model is downloaded before starting (only for default model)
    if args.model == DEFAULT_MODEL_NAME:
        if not ensure_model_downloaded():
            console.print("Failed to download model. Exiting.", style="bold red")
            sys.exit(1)

    # Start the interactive shell
    shell = UbuntuAskShell(use_rag=not args.no_rag, model_name=args.model)
    shell.run()


if __name__ == "__main__":
    main()
