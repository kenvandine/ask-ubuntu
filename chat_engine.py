#!/usr/bin/env python3
"""
Chat Engine - Shared AI engine for Ask Ubuntu (used by CLI and Electron app)
"""

import json
import requests
from typing import List, Dict, Optional
from openai import OpenAI

from rag_indexer import RAGIndexer
from system_indexer import SystemIndexer

# Model / server configuration
LEMONADE_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_MODEL_NAME = "Qwen3-4B-Instruct-2507-GGUF"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1-GGUF"

# Tools the LLM can call to look up package information
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


def create_client() -> OpenAI:
    """Create OpenAI client pointed at Lemonade Server."""
    return OpenAI(base_url=LEMONADE_BASE_URL, api_key="lemonade")


def ensure_model_available(model_name: str) -> tuple[bool, str]:
    """
    Ensure the model is available in Lemonade, pulling it if necessary.
    Returns (success, message).
    """
    try:
        response = requests.get(f"{LEMONADE_BASE_URL}/models", timeout=10)
        response.raise_for_status()
        models = response.json().get("data", [])

        for model in models:
            if model["id"] == model_name:
                if model.get("downloaded"):
                    return True, f"Model ready: {model_name}"
                break

        # Model not downloaded yet — pull it via Lemonade
        pull_response = requests.post(
            f"{LEMONADE_BASE_URL}/pull",
            json={"model": model_name},
            timeout=600,
        )
        pull_response.raise_for_status()
        return True, f"Model pulled: {model_name}"

    except requests.ConnectionError:
        return False, "Cannot connect to Lemonade server at localhost:8000"
    except Exception as e:
        return False, f"Error ensuring model availability: {e}"


class ChatEngine:
    """
    Shared AI engine. Framework-agnostic — no Rich, no prompt_toolkit.
    Suitable for use by both the CLI (main.py) and the Electron server (server.py).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        embed_model: str = DEFAULT_EMBED_MODEL,
        use_rag: bool = True,
        debug: bool = False,
    ):
        self.model_name = model_name
        self.embed_model = embed_model
        self.use_rag = use_rag
        self.debug = debug
        self.client = create_client()
        self.conversation_history: List[Dict] = []
        self.system_indexer: Optional[SystemIndexer] = None
        self.rag_indexer: Optional[RAGIndexer] = None
        self.system_context: str = ""
        self._initialized: bool = False

    def initialize(self) -> None:
        """
        Blocking initialization: loads system info and RAG index.
        Call this from asyncio.to_thread() in async contexts.
        """
        # System indexer
        self.system_indexer = SystemIndexer()
        self.system_indexer.load_or_collect()
        self.system_context = self.system_indexer.get_context_summary()

        # RAG indexer
        if self.use_rag:
            try:
                self.rag_indexer = RAGIndexer(
                    base_url=LEMONADE_BASE_URL,
                    embed_model=self.embed_model,
                )
                self.rag_indexer.load_or_create_index()
            except Exception as e:
                self.rag_indexer = None
                self.use_rag = False
                # Caller can inspect self.use_rag to detect failure

        self._initialized = True

    def clear(self) -> None:
        """Reset conversation history."""
        self.conversation_history = []

    def get_system_info(self) -> str:
        """Return the system context summary string."""
        if not self._initialized and self.system_indexer:
            self.system_context = self.system_indexer.get_context_summary()
        return self.system_context

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a package lookup tool and return a JSON string result."""
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
                        "available_in_cache": self.system_indexer.is_apt_available(pkg_name),
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

    def _get_retrieved_docs(self, query: str) -> str:
        """Search RAG index and return formatted doc snippets, or empty string."""
        if not self.use_rag or not self.rag_indexer:
            return ""
        try:
            results = self.rag_indexer.search(query, top_k=3)
            if results:
                parts = []
                for doc, score in results:
                    parts.append(f"### {doc.title} (from {doc.source})\n{doc.content[:1000]}")
                return "\n\n".join(parts)
        except Exception:
            pass
        return ""

    def chat(self, message: str) -> dict:
        """
        Send a message and run the tool-calling loop until the model produces a final answer.

        Returns:
            {
                "response": str,          # final assistant text
                "tool_calls": [           # may be empty
                    {"name": str, "args": dict, "result": str},
                    ...
                ]
            }
        """
        self.conversation_history.append({"role": "user", "content": message})

        retrieved_docs = self._get_retrieved_docs(message)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            system_context=self.system_context,
            retrieved_docs=(
                retrieved_docs
                if retrieved_docs
                else "No specific documentation retrieved for this query."
            ),
        )

        messages = [{"role": "system", "content": system_prompt}] + self.conversation_history

        executed_tool_calls = []

        try:
            while True:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=PACKAGE_TOOLS,
                    stream=False,
                    timeout=300,
                )
                msg = response.choices[0].message

                if msg.tool_calls:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        args = json.loads(tc.function.arguments)
                        result = self._execute_tool(tc.function.name, args)
                        executed_tool_calls.append(
                            {"name": tc.function.name, "args": args, "result": result}
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            }
                        )
                else:
                    full_response = msg.content or ""
                    self.conversation_history.append(
                        {"role": "assistant", "content": full_response}
                    )
                    return {"response": full_response, "tool_calls": executed_tool_calls}

        except Exception as e:
            return {"response": f"Error: {e}", "tool_calls": executed_tool_calls}
