#!/usr/bin/env python3
"""
Chat Engine - Shared AI engine for Ask Ubuntu (used by CLI and Electron app)
"""

import json
import io
import logging
import requests
import threading
from pathlib import Path
from typing import List, Dict, Optional
import httpx
from openai import OpenAI
from rich.console import Console

from app_env import app_cache_dir
from rag_indexer import RAGIndexer
from system_indexer import SystemIndexer

# Model / server configuration
LEMONADE_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_MODEL_NAME = "Qwen3.5-4B-GGUF"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1-GGUF"


def _ask_ubuntu_cache_dir() -> Path:
    """Return the snap-aware cache directory for Ask Ubuntu."""
    return app_cache_dir()


_LAST_MODEL_FILE = "last_model.txt"


def save_last_model(model_name: str) -> None:
    """Persist the user's last chosen model to disk."""
    try:
        (_ask_ubuntu_cache_dir() / _LAST_MODEL_FILE).write_text(
            model_name.strip(), encoding="utf-8"
        )
    except Exception:
        pass


def load_last_model() -> Optional[str]:
    """Return the last model the user chose, or None if never saved."""
    try:
        path = _ask_ubuntu_cache_dir() / _LAST_MODEL_FILE
        if path.exists():
            val = path.read_text(encoding="utf-8").strip()
            return val if val else None
    except Exception:
        pass
    return None


# Tier-to-Model Map (models must exist in Lemonade's catalog)
LLM_TIER_MAP = {
    "high_end": "Qwen3.5-27B-GGUF",  # High memory: largest Qwen model
    "mid_intel": "Qwen3.5-9B-GGUF",  # Mid-range memory
    "balanced_amd": "Qwen3.5-4B-GGUF",  # Balanced memory
    "legacy": "Qwen3.5-2B-GGUF",  # Smallest footprint
}

# FLM models that can leverage the NPU, in preference order
FLM_NPU_MODEL_PREFERENCE = [
    "Qwen3.5-4B-FLM",
    "Qwen3-8b-FLM",
]

# Tier-to-Embedding Model Map
# nomic-embed-text-v1-GGUF is the only embedding model in Lemonade's catalog
# that is broadly available across all hardware tiers.
EMBED_TIER_MAP = {
    "high_end": "nomic-embed-text-v1-GGUF",
    "mid_intel": "nomic-embed-text-v1-GGUF",
    "balanced_amd": "nomic-embed-text-v1-GGUF",
    "legacy": "nomic-embed-text-v1-GGUF",
}

# Tools the LLM can call to look up package information
PACKAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_snap",
            "description": (
                "Check whether a snap package is installed on this system "
                "and what version is available in the Snap Store. "
                "For installed snaps, compares the installed version against "
                "the version in the snap's tracking channel. "
                "For uninstalled snaps, checks the store and returns the "
                "latest stable version if the snap exists."
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
    {
        "type": "function",
        "function": {
            "name": "check_service",
            "description": (
                "Check the status of a systemd service on this system. "
                "Returns whether it is active (running/inactive/failed) and "
                "whether it is enabled (starts at boot). "
                "Use this for any question about a specific service or daemon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "The service name, with or without the .service suffix "
                            "(e.g. 'ssh', 'docker', 'NetworkManager')"
                        ),
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_failed_services",
            "description": "Return all currently failed systemd services on this system.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_running_services",
            "description": (
                "Return all currently running system daemons and snap services. "
                "Includes every PPID=1 process (direct systemd children) plus "
                "a mapping of which installed snaps have active service processes."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_stats",
            "description": (
                "Fetch live system resource statistics. "
                "Returns current memory usage, GPU utilisation and VRAM/GTT, "
                "CPU frequency and temperature, top processes by RAM, "
                "load average, and disk usage for every mount point. "
                "Call this for any question about system performance, memory usage, "
                "GPU activity, CPU temperature, disk space, or what is using resources."
            ),
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
You have tools to check live package status — these query the actual system and
the Snap Store in real time. NEVER rely on training data for package availability.

- `check_snap(name)` — queries the system AND the Snap Store; returns installed
  version, store version, and availability. Use this for ANY snap-related question.
- `check_apt(name)` — checks if a deb package is installed or available via apt.
- `list_installed_snaps()` — full list of installed snaps with versions.
- `check_service(name)` — live status of a specific service or daemon (active/inactive).
- `list_running_services()` — all running system daemons (PPID=1) plus active snap services.
- `list_failed_services()` — returns all currently failed systemd services.
- `get_system_stats()` — **live** memory, GPU, CPU, process, and disk stats. Call this
  whenever the user asks about performance, memory usage, GPU activity, temperature,
  what is slowing the system down, disk space, or current resource consumption.
  The system context above was captured at startup; this tool returns fresh live data.

**MANDATORY TOOL USE — NO EXCEPTIONS:**
- ALWAYS call `check_snap` before making ANY claim about whether a snap exists,
  is available, is installed, or what version it is.
- ALWAYS call `check_apt` before making ANY claim about an apt package.
- NEVER say a package "does not exist", "is not available", or "cannot be found"
  without calling the tool first — your training data is outdated and wrong.
- If the tool returns `available_in_store: true`, the snap EXISTS in the store.
- If the tool returns a `store_version`, recommend `sudo snap install <name>`.

When a question involves a specific package:
1. Call `check_snap` and/or `check_apt` FIRST — no exceptions
2. Base your answer entirely on the tool result, not on training knowledge
3. If installed, use update/manage commands (e.g., `sudo snap refresh <name>`)
4. If not installed but in the store, show `sudo snap install <name>`
5. Only say a package is unavailable if the tool explicitly confirms it

## Retrieved Documentation
You have access to relevant Ubuntu documentation and man pages for this query.
Use this information to provide accurate, authoritative answers:

{retrieved_docs}

## Response Language
{response_language}

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


def detect_npu_flm_model() -> Optional[str]:
    """
    Query the lemonade-server API to determine whether an NPU and a usable FLM
    backend are present. Returns the best downloaded FLM model ID, or None.

    Detection logic:
    1. GET /api/v1/system-info → devices.amd_npu.available must be True
    2. recipes.flm.backends.npu.state must be "installed" or "update_required"
       (both mean the FLM backend binary is present on disk)
    3. GET /api/v1/models → pick the highest-priority downloaded FLM model
    """
    try:
        resp = requests.get(f"{LEMONADE_BASE_URL}/system-info", timeout=5)
        resp.raise_for_status()
        info = resp.json()

        npu = info.get("devices", {}).get("amd_npu", {})
        if not npu.get("available"):
            return None

        flm_npu = (
            info.get("recipes", {}).get("flm", {}).get("backends", {}).get("npu", {})
        )
        if flm_npu.get("state") not in ("installed", "update_required"):
            return None

        # Find the best downloaded FLM model from the catalog
        resp = requests.get(f"{LEMONADE_BASE_URL}/models", timeout=10)
        resp.raise_for_status()
        catalog = {m["id"]: m for m in resp.json().get("data", [])}

        for model_id in FLM_NPU_MODEL_PREFERENCE:
            m = catalog.get(model_id)
            if m and m.get("recipe") == "flm" and m.get("downloaded"):
                return model_id

        # Fall back to any downloaded FLM model in the catalog
        for m in catalog.values():
            if m.get("recipe") == "flm" and m.get("downloaded"):
                return m["id"]

    except Exception:
        pass

    return None


# Labels that mark non-chat models (embeddings, image gen, audio, TTS)
_NON_CHAT_LABELS = {"embeddings", "image", "audio", "transcription", "tts"}


def get_chat_models(current_model: str = None) -> list:
    """
    Return a prioritized list of chat-capable models from lemonade.

    Priority rules:
    - "recommended": NPU-accelerated FLM model (if NPU present) OR the tier-matched
      GGUF model (if no NPU/FLM).  At most one model gets this badge.
    - "available": everything else (downloaded or not).

    Each entry: {id, recipe, downloaded, size_gb, labels, priority, priority_reason, current}
    Sorted: recommended first, then downloaded, then by size ascending.
    """
    npu_flm = detect_npu_flm_model()

    try:
        si = SystemIndexer()
        tier = si.get_hardware_tier()
        tier_model = LLM_TIER_MAP.get(tier, DEFAULT_MODEL_NAME)
    except Exception:
        tier_model = DEFAULT_MODEL_NAME

    try:
        resp = requests.get(f"{LEMONADE_BASE_URL}/models?show_all=true", timeout=10)
        resp.raise_for_status()
        raw_models = resp.json().get("data", [])
    except Exception:
        return []

    result = []
    for m in raw_models:
        labels = set(m.get("labels", []))
        recipe = m.get("recipe", "")

        if recipe not in ("flm", "llamacpp"):
            continue
        if labels & _NON_CHAT_LABELS:
            continue

        model_id = m["id"]

        if npu_flm and model_id == npu_flm:
            priority, priority_reason = "recommended", "NPU-accelerated"
        elif not npu_flm and model_id == tier_model:
            priority, priority_reason = "recommended", "best for your hardware"
        else:
            priority, priority_reason = "available", ""

        result.append(
            {
                "id": model_id,
                "recipe": recipe,
                "downloaded": bool(m.get("downloaded")),
                "size_gb": m.get("size", 0),
                "labels": sorted(labels - _NON_CHAT_LABELS),
                "priority": priority,
                "priority_reason": priority_reason,
                "current": model_id == current_model,
            }
        )

    def _sort_key(m):
        return (
            0 if m["priority"] == "recommended" else 1,
            0 if m["downloaded"] else 1,
            m["size_gb"],
        )

    result.sort(key=_sort_key)
    return result


def unload_model(model_name: str) -> bool:
    """Ask Lemonade to unload a specific model from memory.

    Returns True on success, False on error (e.g. server unreachable).
    """
    try:
        resp = requests.post(
            f"{LEMONADE_BASE_URL}/unload",
            json={"model": model_name},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def create_client(base_url: str = None, api_key: str = None) -> OpenAI:
    """Create OpenAI client. Defaults to Lemonade Server if no base_url given."""
    # Use a short idle-connection timeout so that TCP connections to the local
    # inference server (Lemonade / llama.cpp) are closed promptly after each
    # request.  Persistent idle connections can prevent the server from
    # releasing GPU compute resources.
    return OpenAI(
        base_url=base_url or LEMONADE_BASE_URL,
        api_key=api_key or "lemonade",
        http_client=httpx.Client(
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=0,
            ),
        ),
    )


def ensure_model_available(
    model_name: str,
    progress_callback=None,
) -> tuple[bool, str]:
    """
    Ensure the model is available in Lemonade, pulling it if necessary.

    Args:
        model_name: The model identifier to check / pull.
        progress_callback: Optional callable(status, completed, total).
            *status* is a short description string (e.g. "downloading").
            *completed* and *total* are byte counts (may be 0 when unknown).

    Returns (success, message).
    """
    try:
        response = requests.get(f"{LEMONADE_BASE_URL}/models?show_all=true", timeout=10)
        response.raise_for_status()
        models = response.json().get("data", [])

        found_in_catalog = False
        for model in models:
            if model["id"] == model_name:
                found_in_catalog = True
                if model.get("downloaded"):
                    return True, f"Model ready: {model_name}"
                break

        if not found_in_catalog:
            return False, (
                f"Model '{model_name}' not found in Lemonade's catalog. "
                f"Check available models with: curl http://localhost:8000/api/v1/models"
            )

        # Model in catalog but not downloaded yet — pull it via Lemonade (stream progress)
        if progress_callback:
            progress_callback("starting", 0, 0)

        pull_response = requests.post(
            f"{LEMONADE_BASE_URL}/pull",
            json={"model": model_name},
            stream=True,
            timeout=600,
        )
        pull_response.raise_for_status()

        if progress_callback:
            # Try to parse streaming JSON lines for progress updates
            for line in pull_response.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    status = chunk.get("status", "downloading")
                    completed = chunk.get("completed", 0)
                    total = chunk.get("total", 0)
                    progress_callback(status, completed, total)
                except (json.JSONDecodeError, ValueError):
                    pass
            progress_callback("complete", 0, 0)
        else:
            # Consume the response fully (no progress tracking)
            pull_response.content

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
        model_name: str = None,
        embed_model: str = None,
        use_rag: bool = True,
        debug: bool = False,
        provider_base_url: str = None,
        provider_api_key: str = None,
    ):
        self._explicit_model = model_name is not None
        self._explicit_embed = embed_model is not None
        self.model_name = model_name if model_name is not None else DEFAULT_MODEL_NAME
        self.embed_model = (
            embed_model if embed_model is not None else DEFAULT_EMBED_MODEL
        )
        self.provider_base_url = provider_base_url
        self.provider_api_key = provider_api_key
        self.is_remote = provider_base_url is not None
        # RAG requires a local embedding model; disable for remote providers
        self.use_rag = use_rag and not self.is_remote
        self.debug = debug
        self.client = create_client(provider_base_url, provider_api_key)
        self.conversation_history: List[Dict] = []
        self.system_indexer: Optional[SystemIndexer] = None
        self.rag_indexer: Optional[RAGIndexer] = None
        self.system_context: str = ""
        self._initialized: bool = False
        self._abort_event = threading.Event()

    def abort(self) -> None:
        """Signal the current chat() call to stop after the current LLM call."""
        self._abort_event.set()

    def reset_abort(self) -> None:
        """Clear the abort flag before starting a new chat."""
        self._abort_event.clear()

    def load_rag_index(self, quiet: bool = False) -> None:
        """Load or build the RAG index for the current embedding model."""
        if not self.use_rag:
            return
        try:
            self.rag_indexer = RAGIndexer(
                base_url=LEMONADE_BASE_URL,
                embed_model=self.embed_model,
            )
            if quiet:
                # RAGIndexer writes progress/status via its module-level rich console.
                # Swap in a sink console to avoid corrupting interactive prompts.
                import rag_indexer as _rag_indexer

                old_console = _rag_indexer.console
                _rag_indexer.console = Console(
                    file=io.StringIO(),
                    force_terminal=False,
                    color_system=None,
                )
                try:
                    self.rag_indexer.load_or_create_index()
                finally:
                    _rag_indexer.console = old_console
            else:
                self.rag_indexer.load_or_create_index()
        except Exception:
            self.rag_indexer = None
            self.use_rag = False

    def initialize(self, defer_rag: bool = False) -> None:
        """
        Blocking initialization: loads system info and RAG index.
        Call this from asyncio.to_thread() in async contexts.
        """
        # System indexer
        self.system_indexer = SystemIndexer()
        self.system_indexer.load_or_collect()
        self.system_context = self.system_indexer.get_context_summary()

        # For remote providers, skip Lemonade model detection
        if self.is_remote:
            pass  # model_name was set explicitly by caller
        # Detect hardware tier and set appropriate models (only when not explicitly specified)
        elif not self._explicit_model or not self._explicit_embed:
            saved_model = load_last_model() if not self._explicit_model else None
            npu_flm = (
                detect_npu_flm_model()
                if not self._explicit_model and not saved_model
                else None
            )
            if saved_model:
                if not self._explicit_model:
                    self.model_name = saved_model
                    logging.getLogger(__name__).info(
                        f"Resuming last model: {saved_model}"
                    )
                if not self._explicit_embed:
                    self.embed_model = DEFAULT_EMBED_MODEL
            elif npu_flm:
                if not self._explicit_model:
                    self.model_name = npu_flm
                    logging.getLogger(__name__).info(
                        f"NPU+FLM detected: using {npu_flm}"
                    )
                if not self._explicit_embed:
                    self.embed_model = DEFAULT_EMBED_MODEL
            else:
                tier = self.system_indexer.get_hardware_tier()
                if not self._explicit_model:
                    self.model_name = LLM_TIER_MAP.get(tier, DEFAULT_MODEL_NAME)
                if not self._explicit_embed:
                    self.embed_model = EMBED_TIER_MAP.get(tier, DEFAULT_EMBED_MODEL)

        # RAG indexer (optionally deferred for faster startup)
        if self.use_rag and not defer_rag:
            self.load_rag_index()

        self._initialized = True

    def clear(self) -> None:
        """Reset conversation history."""
        self.conversation_history = []

    def rewind(self, exchange_index: int) -> None:
        """Truncate history to just before the given exchange index.

        Each exchange is one user+assistant pair (2 entries).  Passing
        exchange_index=0 clears everything; exchange_index=1 keeps only
        the first Q&A pair, etc.
        """
        self.conversation_history = self.conversation_history[: exchange_index * 2]

    def get_system_info(self) -> str:
        """Return the system context summary string."""
        if not self._initialized and self.system_indexer:
            self.system_context = self.system_indexer.get_context_summary()
        return self.system_context

    def get_neofetch_fields(self) -> list:
        """Return neofetch-style system info fields for the sidebar."""
        if self.system_indexer:
            return self.system_indexer.get_neofetch_fields()
        return []

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a package lookup tool and return a JSON string result."""
        try:
            if name == "check_snap":
                pkg_name = args["name"]
                installed = self.system_indexer.is_snap_installed(pkg_name)
                result = {"installed": installed}
                store_version = self.system_indexer.get_snap_store_version(pkg_name)
                if store_version:
                    result["store_version"] = store_version
                if installed:
                    snaps = self.system_indexer.system_info.get("packages", {}).get(
                        "snap_packages", []
                    )
                    pkg = next((p for p in snaps if p["name"] == pkg_name), None)
                    result["installed_version"] = pkg["version"] if pkg else "unknown"
                else:
                    result["available_in_store"] = store_version is not None
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

            elif name == "check_service":
                return json.dumps(
                    self.system_indexer.check_service_status(args["name"])
                )

            elif name == "list_failed_services":
                return json.dumps(self.system_indexer.list_failed_services())

            elif name == "list_running_services":
                daemons = self.system_indexer.get_running_daemons()
                snap_svcs = self.system_indexer.system_info.get("services", {}).get(
                    "snap_services", {}
                )
                return json.dumps(
                    {"system_daemons": daemons, "snap_services": snap_svcs}
                )

            elif name == "get_system_stats":
                return self.system_indexer.get_live_stats()

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
                    parts.append(
                        f"### {doc.title} (from {doc.source})\n{doc.content[:1000]}"
                    )
                return "\n\n".join(parts)
        except Exception:
            pass
        return ""

    def _get_response_language_instruction(self) -> str:
        """Return an instruction telling the LLM which language to respond in."""
        try:
            import i18n as _i18n

            locale_code = _i18n.get_locale()
        except Exception:
            locale_code = "en"

        _LOCALE_LANGUAGES = {
            "en": "English",
            "en_GB": "English (British)",
            "en_US": "English",
            "es": "Spanish",
            "de": "German",
            "fr": "French",
        }

        lang = _LOCALE_LANGUAGES.get(locale_code)
        if lang and locale_code not in ("en", "en_US"):
            return f"Always respond in {lang}. Keep terminal commands and code in their original form, but write all explanations, headings, and prose in {lang}."
        return "Respond in English."

    def chat(self, message: str, on_delta=None) -> dict:
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

        self._abort_event.clear()
        retrieved_docs = self._get_retrieved_docs(message)

        # Unload the embedding model before chat inference so both models
        # don't compete for GPU compute.  The lemonade-router allows one
        # model per type slot, so the embed and chat llama-server processes
        # can coexist — both offloaded to GPU — pegging utilisation at 100%.
        if self.use_rag and not self.is_remote:
            unload_model(self.embed_model)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            system_context=self.system_context,
            retrieved_docs=(
                retrieved_docs
                if retrieved_docs
                else "No specific documentation retrieved for this query."
            ),
            response_language=self._get_response_language_instruction(),
        )

        messages = [
            {"role": "system", "content": system_prompt}
        ] + self.conversation_history

        executed_tool_calls = []

        try:
            while True:
                if self._abort_event.is_set():
                    self.conversation_history.pop()  # remove the unanswered user message
                    return {
                        "response": "",
                        "tool_calls": executed_tool_calls,
                        "aborted": True,
                    }

                content_parts = []
                tool_calls_acc = {}
                saw_any_chunk = False

                with self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=PACKAGE_TOOLS,
                    stream=True,
                    timeout=300,
                ) as stream:
                    for chunk in stream:
                        saw_any_chunk = True
                        if self._abort_event.is_set():
                            break
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta is None:
                            continue

                        piece = getattr(delta, "content", None)
                        if piece:
                            content_parts.append(piece)
                            if on_delta:
                                try:
                                    on_delta(piece)
                                except Exception:
                                    pass

                        tc_deltas = getattr(delta, "tool_calls", None) or []
                        for tc in tc_deltas:
                            idx = getattr(tc, "index", 0) or 0
                            entry = tool_calls_acc.setdefault(
                                idx,
                                {"id": "", "name": "", "arguments": ""},
                            )
                            tc_id = getattr(tc, "id", None)
                            if tc_id:
                                entry["id"] = tc_id
                            fn = getattr(tc, "function", None)
                            if fn:
                                fn_name = getattr(fn, "name", None)
                                if fn_name:
                                    entry["name"] = fn_name
                                fn_args = getattr(fn, "arguments", None)
                                if fn_args:
                                    entry["arguments"] += fn_args

                if self._abort_event.is_set():
                    self.conversation_history.pop()  # remove the unanswered user message
                    return {
                        "response": "",
                        "tool_calls": executed_tool_calls,
                        "aborted": True,
                    }

                if tool_calls_acc:
                    tool_calls = []
                    for _, tc in sorted(
                        tool_calls_acc.items(), key=lambda item: item[0]
                    ):
                        if not tc["name"]:
                            continue
                        tool_calls.append(
                            {
                                "id": tc["id"] or f"call_{len(tool_calls) + 1}",
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc["arguments"] or "{}",
                                },
                            }
                        )

                    messages.append(
                        {"role": "assistant", "content": None, "tool_calls": tool_calls}
                    )
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc["function"]["arguments"] or "{}")
                        except Exception:
                            args = {}
                        result = self._execute_tool(tc["function"]["name"], args)
                        executed_tool_calls.append(
                            {
                                "name": tc["function"]["name"],
                                "args": args,
                                "result": result,
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result,
                            }
                        )
                else:
                    if not saw_any_chunk:
                        full_response = ""
                    else:
                        full_response = "".join(content_parts)
                    self.conversation_history.append(
                        {"role": "assistant", "content": full_response}
                    )
                    return {
                        "response": full_response,
                        "tool_calls": executed_tool_calls,
                    }

        except Exception as e:
            return {"response": f"Error: {e}", "tool_calls": executed_tool_calls}
