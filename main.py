#!/usr/bin/env python3
"""
Ubuntu Help - An interactive shell tool for asking questions about Ubuntu
"""

import sys
import os
import subprocess
import platform
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

# Initialize Rich console
console = Console()

# Custom prompt style
prompt_style = Style.from_dict(
    {
        "prompt": "#00d7ff bold",
        "input": "#ffffff",
    }
)

# Model configuration
MODEL_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
MODEL_FILE = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
MODEL_NAME = "user.Qwen2.5-Coder-7B-Instruct-GGUF"

# Initialize the OpenAI client to use Lemonade Server
client = OpenAI(
    base_url="http://localhost:8000/api/v1", api_key="lemonade"  # required but unused
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


SYSTEM_PROMPT_TEMPLATE = """You are Ubuntu Help Assistant, an expert guide for Ubuntu Linux users.

## CRITICAL RULES - READ FIRST

**NEVER suggest installing or checking these tools - they are GUARANTEED to be present:**
- apt/apt-get (DO NOT say "ensure apt is installed" or "install apt")
- snap/snapd (DO NOT say "install snapd" or "ensure snapd is installed/running")
- systemctl, ufw, grep, find, sed, awk, curl, wget, bash, sudo

**SKIP all "ensure X is installed" steps for these core tools. Jump directly to using them.**

Example of what NOT to do:
❌ "First, ensure snapd is installed: `sudo apt install snapd`"
❌ "Make sure snap is running: `sudo systemctl start snapd`"

Example of what TO do:
✅ "Install terminal-fun: `sudo snap install terminal-fun`"
✅ "Install Docker: `sudo apt install docker.io`"

## User's System Information
{system_context}

## Your Role
Help users accomplish tasks on their Ubuntu system with clear, direct instructions.

## When Answering Questions
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
        console.print(f"\n📥 Downloading model: {MODEL_REPO}", style="cyan bold")
        console.print(f"   File: {MODEL_FILE}", style="cyan")
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
        console.print(f"📋 Next steps:", style="cyan bold")
        console.print(f"   1. Copy model to lemonade-server cache:", style="cyan")
        console.print(f"      sudo mkdir -p {snap_cache_dir}", style="white")
        console.print(
            f"      sudo cp -r {user_model_path} {snap_cache_dir}/", style="white"
        )
        console.print(f"   2. Or re-download directly to snap cache:", style="cyan")
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


class UbuntuHelpShell:
    def __init__(self):
        self.conversation_history: List[Dict[str, str]] = []
        self.session = None
        self.system_context = get_system_context()
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(system_context=self.system_context)

    def setup_prompt_session(self):
        """Setup prompt_toolkit session with history"""
        history_file = Path.home() / ".ubuntu_help_history"

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
        # Format system info for display
        system_info_lines = self.system_context.split('\n')
        system_info_display = "\n".join(f"- {line}" for line in system_info_lines if line)

        welcome_text = f"""
# 🐧 Ubuntu Help Assistant

Ask me anything about using Ubuntu! I can help you with:
- System administration tasks
- Package management (apt, snap)
- Configuration and customization
- Troubleshooting issues
- Command line tips and tricks

**Your System:**
{system_info_display}

**Model:** `{MODEL_NAME}`

**Special commands:**
- `/help` - Show this help message
- `/clear` - Clear the screen
- `/exit` or `/quit` - Exit the assistant
- `Ctrl+C` - Cancel current input
- `Ctrl+D` - Exit

**Tips:**
- Press `Esc` then `Enter` for multi-line input
- Use `↑` and `↓` to navigate command history
"""
        console.print(Panel(Markdown(welcome_text), border_style="cyan"))
        console.print()

    def handle_special_command(self, user_input: str) -> bool:
        """Handle special commands. Returns True if command was handled."""
        command = user_input.strip().lower()

        if command in ["/exit", "/quit"]:
            console.print("\n👋 Goodbye!", style="cyan")
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

        # Prepare messages with system prompt (includes system context)
        messages = [
            {"role": "system", "content": self.system_prompt}
        ] + self.conversation_history

        try:
            # Create streaming completion
            stream = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                stream=True,
            )

            full_response = ""
            buffer = ""
            buffer_size = 5  # Print every N chunks for balance of speed and smoothness

            # Display streaming response - batch chunks for performance
            for i, chunk in enumerate(stream):
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    buffer += content

                    # Flush buffer every N chunks
                    if i % buffer_size == 0 or len(buffer) > 50:
                        console.print(buffer, end="", markup=False, highlight=False)
                        buffer = ""

            # Flush remaining buffer
            if buffer:
                console.print(buffer, end="", markup=False, highlight=False)

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
                    console.print("\n👋 Goodbye!", style="cyan")
                    break

        except Exception as e:
            console.print(f"\n❌ Fatal error: {str(e)}", style="bold red")
            sys.exit(1)


def main():
    """Entry point"""
    # Ensure model is downloaded before starting
    if not ensure_model_downloaded():
        console.print("Failed to download model. Exiting.", style="bold red")
        sys.exit(1)

    # Start the interactive shell
    shell = UbuntuHelpShell()
    shell.run()


if __name__ == "__main__":
    main()
