# Ask Ubuntu — AI-Powered Ubuntu Assistant

An AI assistant for Ubuntu Linux, powered by a local [Lemonade Server](https://github.com/lemonade-sdk/lemonade) LLM. Available as both a **desktop GUI** (Electron) and an **interactive terminal CLI**.

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

- **Markdown rendering** — formatted responses with syntax-highlighted, copyable code blocks
- **Conversation memory** — maintains context across follow-up questions; start fresh with "New chat"

---

## Architecture

| File | Role |
|------|------|
| `chat_engine.py` | Shared AI engine (LLM client, tool calling, RAG, system context) |
| `main.py` | Terminal CLI — Rich/prompt_toolkit UI |
| `server.py` | FastAPI + WebSocket backend for the Electron GUI |
| `rag_indexer.py` | Indexes man pages and Ubuntu help docs; three-tier lookup (local → cache → online) |
| `system_indexer.py` | Collects and caches comprehensive system info; provides live stat refresh |
| `electron/` | Electron desktop app |
| `snap/snapcraft.yaml` | Snap packaging (strict confinement, core24) |

---

## Prerequisites

- Python 3.10+
- [Lemonade Server](https://github.com/lemonade-sdk/lemonade) installed and running at `http://localhost:8000`
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

Make sure Lemonade Server is running, then:

```bash
cd electron && npm start
```

The app spawns the FastAPI backend (`server.py`) automatically on port 8765, waits for the LLM engine to initialize (model download + RAG index on first run), then opens the chat window.

On first run this will:
- Pull the specified chat model via Lemonade if not already downloaded (~2.5 GB)
- Pull the embedding model (`nomic-embed-text-v1-GGUF`) via Lemonade if needed
- Build the RAG index from man pages and Ubuntu help files (~2–3 minutes)

All caches are stored in `~/.cache/ask-ubuntu/` and reused on subsequent runs.

### Terminal CLI

```bash
source .venv/bin/activate
lemonade-server start   # if not already running
./ask-ubuntu
```

**CLI special commands:**

| Command | Action |
|---------|--------|
| `/clear` | Clear the screen |
| `/help` | Show help |
| `/exit` or `/quit` | Quit |
| `Ctrl+D` | Quit |
| `Esc` + `Enter` | Insert newline (multi-line input) |
| `↑` / `↓` | Navigate history |

---

## GUI Overview

The Electron window has a custom title bar and two panels:

**Left sidebar — neofetch-style system info**

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
- "New chat" button

**Main chat area**

- Conversation bubbles (user messages right-aligned in orange, assistant responses left)
- Markdown rendering with syntax-highlighted, copyable code blocks
- Collapsible tool-call details (package lookups and live stat queries performed before answering)
- Animated thinking indicator while the model is working

---

## Configuration

Default models and server URL are set at the top of `chat_engine.py`:

```python
LEMONADE_BASE_URL   = "http://localhost:8000/api/v1"
DEFAULT_MODEL_NAME  = "Qwen3-4B-Instruct-2507-GGUF"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1-GGUF"
```

The system automatically detects your hardware and selects the most appropriate model:

| Tier | Hardware | LLM Model |
|------|----------|-----------|
| High-End | Strix / Ryzen AI (NPU) | `Qwen3-4B-Instruct-2507-GGUF` |
| Mid-Intel | Intel Core / Ultra | `Phi-4-mini-instruct-GGUF` |
| Balanced AMD | AMD CPU, ≥ 16 GB RAM | `Llama-3.2-3B-Instruct-GGUF` |
| Legacy | Other / low RAM | `Llama-3.2-1B-Instruct-GGUF` |

All tiers use `nomic-embed-text-v1-GGUF` for document embeddings.

To override the auto-detected model from the CLI:
```bash
./ask-ubuntu --model <model-id>
```

To override the model for the Electron GUI:
```bash
ASK_UBUNTU_MODEL=Llama-3.2-3B-Instruct-GGUF cd electron && npm start
```

The model must exist in Lemonade's catalog:
```bash
curl http://localhost:8000/api/v1/models
```

---

## Troubleshooting

**Lemonade not running**
```bash
lemonade-server start
```

**Model not found / pull error**
```bash
curl http://localhost:8000/api/v1/models
```

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
