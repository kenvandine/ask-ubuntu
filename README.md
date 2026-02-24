# Ask Ubuntu — AI-Powered Ubuntu Assistant

An AI assistant for Ubuntu Linux, powered by a local [Lemonade Server](https://github.com/lemonade-sdk/lemonade) LLM. Available as both a **desktop GUI** (Electron) and an **interactive terminal CLI**.

The assistant is system-aware, RAG-powered, and can look up package status in real time — so it gives answers tailored to your specific machine rather than generic advice.

---

## Features

- **System-aware** — reads your Ubuntu version, kernel, desktop, CPU, RAM, disk, installed snap/deb packages, and active services; tailors every answer to your machine
- **RAG-powered** — indexes ~500 man pages and ~200 Ubuntu help files; retrieves the top-3 most relevant docs for each question
- **Tool calling** — can check whether a snap or apt package is installed/available before recommending install commands
- **Markdown rendering** — formatted responses with syntax-highlighted code blocks
- **Conversation memory** — maintains context across follow-up questions; start fresh with "New chat"

---

## Architecture

| File | Role |
|------|------|
| `chat_engine.py` | Shared AI engine (LLM client, tool calling, RAG, system context) |
| `main.py` | Terminal CLI — Rich/prompt_toolkit UI |
| `server.py` | FastAPI + WebSocket backend for the Electron GUI |
| `rag_indexer.py` | Indexes man pages and Ubuntu help docs |
| `system_indexer.py` | Collects and caches system info |
| `electron/` | Electron desktop app |

---

## Prerequisites

- Python 3.10+
- [Lemonade Server](https://github.com/lemonade-sdk/lemonade) installed and running
- Node.js + npm (for the Electron GUI only)
- `python3-apt` system package (pre-installed on Ubuntu; enables apt package lookups)

---

## Installation

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

The Electron window has a custom title bar (matching the sidebar colour) and two panels:

**Left sidebar**
- Ubuntu logo and app title
- Neofetch-style system info (OS, host, kernel, uptime, shell, DE, CPU, GPU, memory, disk, package counts)
- "New chat" button to clear conversation history

**Main chat area**
- Conversation bubbles (user messages right-aligned in orange, assistant responses left)
- Markdown rendering with syntax-highlighted, copyable code blocks
- Collapsible tool-call details (package lookups performed before answering)
- Animated thinking indicator while the model is working

---

## Configuration

Default models and server URL are set at the top of `chat_engine.py`:

```python
LEMONADE_BASE_URL  = "http://localhost:8000/api/v1"
DEFAULT_MODEL_NAME = "Qwen3-4B-Instruct-2507-GGUF"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1-GGUF"
```

The system automatically detects your hardware and selects the most appropriate model for optimal performance:

| Tier | Hardware | Model |
|------|----------|-------|
| High-End | Strix / Ryzen AI (NPU) | `Qwen3-4B-Instruct-2507-GGUF` |
| Mid-Intel | Intel Core / Ultra | `Phi-4-mini-instruct-GGUF` |
| Balanced AMD | AMD CPU, ≥16 GB RAM | `Llama-3.2-3B-Instruct-GGUF` |
| Legacy | Other / low RAM | `Llama-3.2-1B-Instruct-GGUF` |

All tiers use `nomic-embed-text-v1-GGUF` for document embeddings.

To override the auto-detected model from the CLI:
```bash
./ask-ubuntu --model <model-id>
```

To override the model for the Electron GUI, set the `ASK_UBUNTU_MODEL` environment variable or use the wrapper script:
```bash
ASK_UBUNTU_MODEL=Llama-3.2-3B-Instruct-GGUF cd electron && npm start
# or
cd electron && npm run start-with-model -- --model Llama-3.2-3B-Instruct-GGUF
```

The model must exist in Lemonade's catalog (`curl http://localhost:8000/api/v1/models`).

---

## Troubleshooting

**Lemonade not running**
```bash
lemonade-server start
```

**Model not found / pull error**
Check available models and disk space:
```bash
curl http://localhost:8000/api/v1/models
```

**`python3-apt` missing**
This is a system package; install it with:
```bash
sudo apt install python3-apt
```
Without it, apt package lookups will fall back to `dpkg-query` for counts and will not support availability checks.

**Import error / missing dependencies**
Ensure the venv is active and dependencies are installed:
```bash
source .venv/bin/activate && pip3 install -r requirements.txt
```

**Electron app stuck on "Starting backend…"**
- Confirm Lemonade Server is running on port 8000
- Check the terminal for `[server]` error lines from the backend process
