# Ask Ubuntu — AI-Powered Ubuntu Assistant

An AI assistant for Ubuntu Linux. Available as both a **desktop GUI** (Electron) and an **interactive terminal CLI**.

Ask Ubuntu can run entirely **locally** using [Lemonade Server](https://github.com/lemonade-sdk/lemonade), or connect to **remote cloud providers** (Anthropic, OpenAI, Google Gemini, or any OpenAI-compatible endpoint such as Ollama). Remote providers are used automatically when Lemonade is unavailable.

The assistant is deeply system-aware, RAG-powered, and can query live system state — so it gives answers tailored to your specific machine rather than generic advice.

---

## Features

- **Deep system context** — at startup, collects a comprehensive snapshot of your machine:
  - OS, kernel, desktop environment, shell
  - CPU topology (sockets, physical/logical cores, hyperthreading, L3 cache, governor)
  - GPU name, utilisation %, VRAM/GTT usage, clock speed, power draw, temperature (AMD)
  - Memory: used/available/cached, swap, PSI pressure, swappiness
  - Storage: drive type/model/size (NVMe SSD, HDD, etc.), LVM/LUKS/RAID detection, per-mount disk usage, EFI vs BIOS
  - Network interfaces: type (ethernet/wifi/VPN), state, speed
  - Form factor (laptop/desktop/server), battery state and health
  - Installed snap and deb packages, active system services

- **Live resource lookup** — the LLM can call `get_system_stats` mid-conversation to fetch
  fresh memory, GPU, CPU, process, and disk data; useful for "what's using my RAM?" questions

- **RAG-powered docs** — indexes ~500 man pages and ~200 Ubuntu help files; retrieves the
  top-3 most relevant docs for each question. When the `system-packages-doc` snap interface is
  connected, uses local man pages directly; otherwise fetches from manpages.ubuntu.com

- **Tool calling** — the LLM calls live tools before answering package or service questions:

  | Tool | What it does |
  |------|--------------|
  | `check_snap(name)` | Is a snap installed? What version is in the store? |
  | `check_apt(name)` | Is a deb package installed or available? |
  | `list_installed_snaps()` | All installed snaps with versions |
  | `check_service(name)` | Is a systemd service active/enabled? |
  | `list_running_services()` | All running daemons + active snap services |
  | `list_failed_services()` | All currently failed systemd units |
  | `get_system_stats()` | Fresh live: memory, GPU, CPU, processes, disk |

- **Remote provider support** — when Lemonade is unavailable or you prefer cloud models, connect Anthropic, OpenAI, Gemini, or any OpenAI-compatible endpoint (e.g. Ollama on another machine). Configure via environment variable, settings UI, or CLI. Auto-fallback activates when Lemonade cannot be reached.
- **Markdown rendering** — formatted responses with syntax-highlighted, copyable code blocks
- **Conversation memory** — maintains context across follow-up questions; start fresh with "New chat"

---

## Architecture

| File | Role |
|------|------|
| `chat_engine.py` | Shared AI engine (LLM client, tool calling, RAG, system context) |
| `main.py` | Terminal CLI — Rich/prompt_toolkit UI |
| `server.py` | FastAPI + WebSocket backend for the Electron GUI |
| `remote_providers.py` | Remote provider config — presets, env var detection, config file I/O |
| `rag_indexer.py` | Indexes man pages and Ubuntu help docs; three-tier lookup (local → cache → online) |
| `system_indexer.py` | Collects and caches comprehensive system info; provides live stat refresh |
| `electron/` | Electron desktop app |
| `snap/snapcraft.yaml` | Snap packaging (strict confinement, core24) |

---

## Prerequisites

- Python 3.10+
- **One of:**
  - [Lemonade Server](https://github.com/lemonade-sdk/lemonade) installed and running at `http://localhost:8000` (for local models), **or**
  - An API key for a remote provider (Anthropic, OpenAI, Gemini, or a custom OpenAI-compatible endpoint)
- Node.js + npm (for the Electron GUI only)

---

## Installation

### From source

**1. Create and activate a virtual environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**2. Install Python dependencies:**
```bash
pip3 install -r requirements.txt
```

**3. (GUI only) Install Electron dependencies:**
```bash
cd electron && npm install
```

### As a snap

```bash
sudo snap install ask-ubuntu
```

After installation, connect the required interfaces:

```bash
sudo snap connect ask-ubuntu:desktop-launch
sudo snap connect ask-ubuntu:var-lib-dpkg
sudo snap connect ask-ubuntu:var-lib-apt-lists
sudo snap connect ask-ubuntu:system-packages-doc   # pending interface in snapd
```

> **Note on `system-packages-doc`:** This interface (still being landed in snapd) exposes
> `/usr/share/man` and `/usr/share/help` inside the snap via bind mount. Without it, man
> page lookups fall back to the disk cache and online fetch.

> **Note on `var-lib-dpkg` / `var-lib-apt-lists`:** These use the `system-files` interface
> which adds AppArmor rules but does **not** bind-mount the paths. The snap reads these via
> `/var/lib/snapd/hostfs/var/lib/...`, which is always a visible bind mount of the real host
> root inside every snap.

---

## Running

### Desktop GUI (Electron)

Make sure Lemonade Server is running (or a remote provider is configured), then:

```bash
cd electron && npm start
```

The app spawns the FastAPI backend (`server.py`) automatically on port 8765, waits for the LLM engine to initialize (model download + RAG index on first run), then opens the chat window.

On first run with Lemonade this will:
- Pull the specified chat model via Lemonade if not already downloaded (~2.5 GB)
- Pull the embedding model (`nomic-embed-text-v1-GGUF`) via Lemonade if needed
- Build the RAG index from man pages and Ubuntu help files (~2–3 minutes)

All caches are stored in `~/.cache/ask-ubuntu/` and reused on subsequent runs.

If Lemonade is unavailable and a remote provider is configured, the app falls back to the remote provider automatically — no model download required.

### Terminal CLI

```bash
source .venv/bin/activate
lemonade-server start   # if not already running, or use a remote provider
./ask-ubuntu
```

**CLI special commands:**

| Command | Action |
|---------|--------|
| `/model` | Open interactive model picker (local and remote models) |
| `/providers` | Manage remote provider configuration |
| `/clear` | Clear the screen |
| `/help` | Show help |
| `/exit` or `/quit` | Quit |
| `Ctrl+D` | Quit |
| `Esc` + `Enter` | Insert newline (multi-line input) |
| `↑` / `↓` | Navigate history |

---

## GUI Overview

The Electron window uses the native system title bar and has two main areas:
- A left sidebar rail/panel for controls and system context
- A main chat area for conversation

The GUI is styled to match Ubuntu Yaru conventions:
- Accent color follows GNOME `org.gnome.desktop.interface accent-color` (Ubuntu orange by default)
- System Ubuntu fonts from GNOME settings (no external font downloads)

**Left sidebar panel — neofetch-style system info**

Displayed at startup and updated on each session:

- OS, Host, Type (Laptop/Desktop/Server)
- Kernel, Uptime, Shell, DE (Wayland/X11)
- CPU with core count and active governor
- GPU name; GPU GTT usage (system RAM mapped to GPU — key for APUs)
- Memory used/total
- Per-mount disk usage (real filesystems only)
- Battery % and status (laptops)
- Thermal alert (if any zone ≥ 60 °C)
- Deb and snap package counts

**Sidebar rail controls**
- `?` help dialog
- `⊙` model picker (Local/Remote tabs)
- `+` new chat

**Main chat area**

- Conversation bubbles (user messages right-aligned in orange, assistant responses left)
- Markdown rendering with syntax-highlighted, copyable code blocks
- Per-response audio playback button on assistant messages
- Collapsible tool-call details (package lookups and live stat queries performed before answering)
- Animated thinking indicator while the model is working

**Audio playback (Electron)**
- Sidebar rail speaker button toggles auto-play for all assistant responses
- Assistant bubbles include a play button for one-off playback
- Sidebar voice selector chooses the TTS voice used for playback
- TTS uses Lemonade audio model `kokorro-v1` (fallback: `kokoro-v1`)
- Default voice is `af_heart` (Kokoro voice set)
- With auto-play enabled, TTS starts sentence-by-sentence while responses stream in
- The app keeps local runtime models warm in the background (chat, embeddings, TTS)
- Audio status text in the sidebar shows generating/playing/errors
- Optional overrides:
  - `ASK_UBUNTU_TTS_MODEL` to choose a different TTS model
  - `ASK_UBUNTU_TTS_VOICE` to choose the voice (default: `af_heart`)

---

## Configuration

### Model auto-detection

At startup, Ask Ubuntu queries the Lemonade server's `GET /api/v1/system-info` endpoint to
detect your hardware and automatically choose the best available model:

1. **NPU + FLM** (highest priority) — if an AMD NPU (XDNA/XDNA2) is detected *and* the
   FastFlowLM (FLM) backend is installed or pending update, the best downloaded FLM model
   is chosen (preference order: `Qwen3-8b-FLM` → `Phi-4-Mini-Instruct-FLM` → `Llama-3.2-3B-FLM`).
   FLM models run natively on the NPU for maximum efficiency.

2. **Hardware tier fallback** — if no NPU/FLM stack is available:

   | Tier | Hardware | LLM Model |
   |------|----------|-----------|
   | High-End | AMD Strix / Ryzen AI (GPU) | `Qwen3-4B-Instruct-2507-GGUF` |
   | Mid-Intel | Intel Core / Ultra | `Phi-4-mini-instruct-GGUF` |
   | Balanced AMD | AMD CPU, ≥ 16 GB RAM | `Llama-3.2-3B-Instruct-GGUF` |
   | Legacy | Other / low RAM | `Llama-3.2-1B-Instruct-GGUF` |

All tiers use `nomic-embed-text-v1-GGUF` for document embeddings.

### Changing the model at runtime

**GUI** — click the 🔘 model button in the sidebar rail to open the model picker.
Models are sorted by hardware suitability, with **Recommended** and **NPU** badges on the
best choices. Not-yet-downloaded models can be pulled inline with a progress bar.

**CLI** — type `/model` during a session to open the full-screen interactive picker:
type to filter, `↑↓` to navigate, `Enter` to select (downloads automatically if needed).

### Environment variable override

To pin a specific local model regardless of hardware detection:

```bash
# CLI
./ask-ubuntu --model <model-id>

# Electron GUI
ASK_UBUNTU_MODEL=Llama-3.2-3B-Instruct-GGUF cd electron && npm start
```

The model must exist in Lemonade's catalog (use `show_all=true` to see the full list):
```bash
curl "http://localhost:8000/api/v1/models?show_all=true"
```

### Remote providers

Ask Ubuntu supports remote OpenAI-compatible providers as an alternative (or fallback) to local Lemonade models.

**Supported presets:**

| Provider | Environment variable |
|----------|---------------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |
| Custom (Ollama, LiteLLM, etc.) | configured via UI or CLI |

**Quickstart — environment variables (simplest):**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./ask-ubuntu                          # CLI auto-selects Anthropic if Lemonade is unavailable
```

**CLI — specify provider explicitly:**

```bash
./ask-ubuntu --provider anthropic --api-key sk-ant-...
./ask-ubuntu --provider openai      # key from OPENAI_API_KEY env var
```

**CLI — manage saved providers:**

```bash
/providers   # interactive manager (keyboard + mouse) for add / edit / remove
```

**GUI — Remote tab in the model picker:**

Click the **⊙** model button → **Remote** tab → fill in provider and API key → Save. The provider's models appear for selection.

**Auto-fallback:**

If Lemonade is unreachable at startup and at least one remote provider is configured, Ask Ubuntu automatically switches to the first available remote provider without requiring any action.

---

## Troubleshooting

**Lemonade not running**
```bash
lemonade-server start
```

If you have a remote provider configured, Ask Ubuntu will fall back to it automatically when Lemonade is unreachable.

**Model not found / pull error**
```bash
curl http://localhost:8000/api/v1/models
```

**Remote provider not working**

Check the API key is set correctly (env var takes priority over saved config):
```bash
echo $ANTHROPIC_API_KEY    # or OPENAI_API_KEY / GEMINI_API_KEY
```
For custom providers (Ollama etc.), verify the base URL is reachable and the `/v1/models` endpoint responds.

**Snap: permission denied on `/var/lib/apt/lists` or `/var/lib/dpkg`**

These paths are accessed via `/var/lib/snapd/hostfs/var/lib/...`. Make sure the interfaces are connected:
```bash
snap connections ask-ubuntu
sudo snap connect ask-ubuntu:var-lib-dpkg
sudo snap connect ask-ubuntu:var-lib-apt-lists
```

**Snap: man pages not loading from local files**

The `system-packages-doc` interface is still being landed in snapd. Until it ships, the snap falls back to cached and online man pages automatically.

**Import error / missing Python dependencies**
```bash
source .venv/bin/activate && pip3 install -r requirements.txt
```

**Electron app stuck on "Starting backend…"**
- Confirm Lemonade Server is running on port 8000
- Check the terminal for `[server]` error lines from the backend process
