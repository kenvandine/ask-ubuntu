# Ask Ubuntu — User Guide

Ask Ubuntu is an AI assistant for Ubuntu Linux. It answers questions about your system, installed packages, running services, hardware, configuration, and general Ubuntu usage.

By default it runs entirely locally using a Lemonade Server model — no cloud required. It can also connect to remote AI providers (Anthropic, OpenAI, Google Gemini, or any OpenAI-compatible endpoint such as Ollama) when you prefer cloud models or when local inference is unavailable.

---

## What Ask Ubuntu can answer

- "How do I install VLC?" — tells you the snap or apt command with version info
- "What version of Firefox do I have?" — checks your actual installed snap version
- "Why is my laptop fan running loud?" — reads your thermal sensors and CPU governor
- "How much disk space is free?" — reads live mount stats
- "Is nginx running?" — checks the systemd service status in real time
- "What snap interfaces does the camera app need?" — looks it up in the snap store
- "How do I enable a firewall?" — pulls the UFW man page and gives you the exact commands
- "What processes are using my RAM?" — fetches a live process snapshot and explains it

Ask Ubuntu has full awareness of your specific machine. When you ask "how much RAM do I have?", it answers with your actual memory, not a generic explanation.

---

## Starting Ask Ubuntu

### Terminal CLI

```bash
./ask-ubuntu
```

Or if installed as a snap:
```bash
ask-ubuntu
```

Ask Ubuntu will start, show a system info header, and drop you into the chat prompt.

### Desktop GUI

Launch from your app launcher, or from the terminal:
```bash
cd electron && npm start
```

The app opens a split-window: system info panel on the left, chat on the right.

### First-run setup

**With Lemonade (local):** On the very first launch, Ask Ubuntu will:
1. Pull the AI model from Lemonade Server (~2–5 GB depending on the model)
2. Pull the embedding model for document search (~500 MB)
3. Build the documentation index — reads man pages and Ubuntu help files (~2–3 minutes)

Everything is cached in `~/.cache/ask-ubuntu/`. Subsequent starts load instantly.

**With a remote provider:** No model download is needed. Ask Ubuntu connects directly to the provider's API. Documentation search (RAG) is disabled when using remote models.

---

## Using the CLI

### Asking questions

Type any question at the `●` prompt and press Enter:

```
● How do I check if a service is enabled?
```

For **multi-line questions** (e.g. pasting an error message), press `Esc` then `Enter` to insert a newline. Press `Enter` alone to submit.

Use `↑` and `↓` to navigate your question history.

### Special commands

| Command | What it does |
|---------|-------------|
| `/model` | Open the interactive model picker — local and remote models |
| `/providers` | Add, edit, or remove remote provider configuration |
| `/help` | Show the help table |
| `/clear` | Clear the screen |
| `/exit` or `/quit` | Quit Ask Ubuntu |
| `Ctrl+D` | Quit |

### Changing the model in the CLI

Type `/model` to open a full-screen interactive picker with two sections:

**Local models** (Lemonade):
- **Type to search** — instantly filters the model list as you type
- `↑` / `↓` — move through the list
- `PgUp` / `PgDn` — scroll faster
- `Enter` — select the highlighted model
- `Esc` — cancel and keep the current model

Badges tell you:
- **★ Recommended** — best match for your hardware
- **NPU** — designed to run on the AMD NPU (fastest on supported hardware)
- **✓ Downloaded** — already on disk, loads immediately
- *(no badge)* — will be downloaded automatically when selected (~2–5 GB)

**Remote models** (☁ cloud):
- Configured providers appear below the local list, with a ☁ prefix
- Models are discovered automatically from the provider's API; if discovery fails, you can type a model name manually
- Selecting a remote model switches immediately (no download)

### Managing remote providers in the CLI

Type `/providers` to open the interactive provider manager:

```
  ☁ Remote Providers

  1. Anthropic [preset]
  2. My Ollama  http://192.168.1.10:11434/v1

  Commands: a=add  e <n>=edit  r <n>=remove  q=done

  providers❯
```

- **`a`** — add a new provider (choose from presets or enter a custom base URL)
- **`e <n>`** — edit provider number n (name, base URL, API key)
- **`r <n>`** — remove provider number n
- **`q`** — close the manager

Providers set via environment variable (e.g. `ANTHROPIC_API_KEY`) are shown but cannot be removed here.

**Using a provider from the command line:**

```bash
./ask-ubuntu --provider anthropic               # key from ANTHROPIC_API_KEY env var
./ask-ubuntu --provider openai --api-key sk-... # key passed directly
./ask-ubuntu --provider my-ollama               # custom provider by ID
```

### Reading responses

Responses appear as streaming text. Code blocks are highlighted. If the assistant looked up live system data before answering (e.g. memory usage, package versions), those tool calls are shown in collapsed details lines before the answer:

```
  ↳ check_snap(firefox)
  ↳ get_system_stats()
```

---

## Using the Desktop GUI

The desktop app follows Ubuntu Yaru styling:
- Accent color follows your GNOME accent setting (Ubuntu orange by default)
- System GNOME font settings (Ubuntu/Ubuntu Mono by default)

### Window layout

The window has a sidebar rail/panel plus the chat panel:

**Left sidebar** — your system info snapshot:
- OS, kernel, hostname, form factor (laptop/desktop)
- CPU, GPU, memory, disk per mount, battery
- Active thermal alerts
- Installed package counts (snap and deb)

**Sidebar rail** (always visible):
- `?` Help
- `⊙` Model picker
- `+` New chat

**Right panel** — the chat area:
- Your messages appear on the right in orange
- Assistant responses appear on the left
- Each assistant response has a speaker button to play audio
- A pulsing dot shows when the model is thinking
- Tool calls (package lookups, live stats) appear as collapsible details

### Audio playback (GUI)

- Use the **speaker button** in the sidebar rail to toggle auto-play for all assistant responses
- Click the **speaker icon** on any assistant bubble to play only that response
- Use the **Voice** selector in the left panel to choose the playback voice
- Audio generation uses the Lemonade TTS model `kokorro-v1` (fallback `kokoro-v1`)

### Changing the model in the GUI

Click the **⊙** (model/sunburst) icon in the top of the left sidebar. This opens the model picker overlay with two tabs:

**Local tab:**
- **Search box** — type to filter the model list instantly
- Each row shows the model name, size, and status badges
- Click a row to select it
- If the model isn't downloaded yet, a progress bar appears — wait for the download to complete before chatting

Badges:
- **Recommended** (orange) — best for your hardware
- **NPU** (blue) — runs on the AMD NPU
- **Downloaded** (green) — already available

**Remote tab:**
- Shows configured providers and their available models
- Models are auto-discovered from the provider's API; for providers with no preset model list (e.g. Ollama) discovery runs automatically, with a manual name entry fallback
- Click **Select** next to any model to switch to it immediately
- Click **+ Add Provider** to add a new provider:
  1. Choose a preset (Anthropic, OpenAI, Gemini) or Custom
  2. Enter the API key (and base URL + name for custom providers)
  3. Click **Save** — models appear immediately
- Click **Edit** on an existing provider to update its details
- Click **Remove** to delete a saved provider

### Managing remote providers in the GUI

Provider API keys can also be provided via environment variables — they take priority over the saved config:

| Provider | Environment variable |
|----------|---------------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |

Providers configured via env var appear in the Remote tab as read-only (no Edit/Remove button). Config-file providers are fully editable in the UI.

### Starting a new conversation

Click the **+** (new chat) button in the sidebar to clear the conversation and start fresh. Your previous messages are not saved.

### Code blocks

Every code block in a response has a **Copy** button. Click it to copy the command to your clipboard. The button flashes to confirm the copy.

---

## How Ask Ubuntu picks the AI model

At startup, Ask Ubuntu automatically selects the best available model for your hardware:

### 1. NPU + FLM (highest priority)

If you have an AMD NPU (XDNA or XDNA2 — present in Ryzen AI and Strix Point processors) and the FastFlowLM (FLM) backend is installed, Ask Ubuntu uses a dedicated FLM model that runs natively on the NPU. This is the fastest and most power-efficient option.

FLM model preference order:
1. Qwen3-8b-FLM (8 billion parameters, best quality)
2. Phi-4-Mini-Instruct-FLM (4B, faster)
3. Llama-3.2-3B-FLM (3B, smallest)

Only already-downloaded FLM models are auto-selected. If none are downloaded, it falls back to the hardware tier.

### 2. Hardware tier (fallback)

| Tier | Hardware | Model |
|------|----------|-------|
| High-End | AMD Strix / Ryzen AI (GPU) | Qwen3-4B-Instruct-2507-GGUF |
| Mid-Intel | Intel Core / Ultra | Phi-4-mini-instruct-GGUF |
| Balanced AMD | AMD CPU, ≥ 16 GB RAM | Llama-3.2-3B-Instruct-GGUF |
| Legacy | Other / low RAM | Llama-3.2-1B-Instruct-GGUF |

### Pinning a specific model

```bash
# CLI — pass on the command line
./ask-ubuntu --model Llama-3.2-3B-Instruct-GGUF

# GUI — set an environment variable before starting
ASK_UBUNTU_MODEL=Llama-3.2-1B-Instruct-GGUF npm start
```

---

## How the system context works

Before your first message, Ask Ubuntu collects a snapshot of your machine:

- Full OS identification (Ubuntu version, codename, kernel)
- CPU model, core count, hyperthreading, L3 cache, active CPU frequency governor
- GPU name, VRAM and GTT memory usage, temperature, clock speed (AMD)
- RAM: used, available, cached; swap usage; memory pressure (PSI)
- Disk: drive type (NVMe SSD / HDD), LVM/LUKS/RAID detection, per-mount usage
- Network interfaces: type, state, speed
- Battery charge and state (laptops)
- Thermal zones — warns you if any zone is hot
- All installed snaps and deb packages
- Running systemd services

This context is included with every question, so answers are always specific to your machine.

The LLM can also call **live tools** mid-conversation to get fresh data:

| Tool | What it fetches |
|------|----------------|
| `check_snap(name)` | Installed version + store version for a snap |
| `check_apt(name)` | Whether a deb package is installed or available |
| `list_installed_snaps()` | All installed snaps with versions |
| `check_service(name)` | Whether a systemd service is active and enabled |
| `list_running_services()` | All running daemons |
| `list_failed_services()` | All failed systemd units |
| `get_system_stats()` | Live memory, GPU, CPU usage, top processes, disk |

---

## How document retrieval (RAG) works

Ask Ubuntu has a local vector index of Ubuntu documentation. Before answering your question, it searches this index for the 3 most relevant documents and includes them as context for the AI model.

The index contains:
- ~500 Ubuntu man pages (apt, snap, systemctl, ufw, etc.)
- ~200 Ubuntu help articles from help.ubuntu.com
- The Ask Ubuntu user guide and FAQ (this document)

Man pages are loaded from:
1. `/usr/share/man/` if the `system-packages-doc` snap interface is connected
2. The local disk cache in `~/.cache/ask-ubuntu/manpages/`
3. Fetched from manpages.ubuntu.com on first use (then cached)

The index is stored in `~/.cache/ask-ubuntu/`. Delete it to force a rebuild:
```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

---

## Tips for good questions

- **Be specific** — "why is apt slow?" gets a better answer than "fix my packages"
- **Include the error** — paste the exact error message, Ask Ubuntu will explain it
- **Ask follow-up questions** — Ask Ubuntu remembers the conversation context
- **Ask for commands** — "give me the command to check my GPU temperature" returns a ready-to-run command
- **Ask about your system** — "is Wayland or X11 running?", "what is my CPU governor set to?"

---

## Remote providers and privacy

When using a remote provider, your questions and system context are sent to that provider's API over the internet. If privacy is a concern, use a local Lemonade model instead.

Providers set via environment variable are never written to disk by Ask Ubuntu. Providers saved through the UI or `/providers` command are stored in `~/.config/ask-ubuntu/remote_providers.json`.

## Supported Ubuntu versions

Ask Ubuntu runs on Ubuntu 22.04 LTS (Jammy) and 24.04 LTS (Noble). It requires Python 3.10+ and either Lemonade Server running locally on port 8000, or a configured remote provider.
